"""engine/ray_renderer.py — Python wrapper for the C raycasting renderer.

Manages buffer construction and provides a clean Python API around the
``_ray_render`` C extension.  Designed for both the standalone demo and
future integration with the editor/game renderer.

Usage
-----
    from engine.ray_renderer import RayRenderer

    renderer = RayRenderer(zone, atlas, sw=640, sh=360)
    surface = renderer.render(px, py, angle)
    screen.blit(surface, (0, 0))
"""

from __future__ import annotations

import array
import math
import struct
from typing import TYPE_CHECKING

import pygame

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False

from core.tiles import (
    TILE_REGISTRY,
    tile_str_to_int,
    tile_def,
    thin_wall_lut,
    tall_wall_lut,
    alt_tex_lut,
    transparent_lut,
    hs_lut,
)
from core.types import FACE_NAMES
from core.zones.format import NAV_SOLID
from engine.textures import TEX_SIZE

if TYPE_CHECKING:
    from core.zones import Zone
    from engine.textures import TextureAtlas

try:
    from engine._ray_render import render_frame as _c_render_frame
    try:
        from engine._ray_render import render_entities as _c_render_entities
    except ImportError:
        _c_render_entities = None
    _HAS_C = True
except ImportError:
    _HAS_C = False
    _c_render_entities = None

# ═══════════════════════════════════════════════════════════════════#  ENTITY PREFAB → TEXTURE MAPPING
# ═════════════════════════════════════════════════════════════════
_PREFAB_TEX_MAP = {
    "crate": "crate_stack",
    "wooden_crate": "crate_stack",
    "shelf": "shelf_wall",
    "table": "table",
    "stool": "stool",
    "counter": "counter_top",
    "lantern": "metal",
}

# ═════════════════════════════════════════════════════════════════#  FOG COMPUTATION  (matches scenes/world/fp_lighting.py)
# ═══════════════════════════════════════════════════════════════════

def build_fog_lut(ambient: int = 255, dn: float = 1.0) -> bytes:
    """Build a 256-byte fog brightness LUT matching the game renderer."""
    _exp = math.exp
    lut = bytearray(256)
    for i in range(256):
        dist = i * 0.125                     # distance in tiles
        dist_norm = dist / 16.0
        fog_exp = max(40, min(ambient, int(ambient * _exp(-dist_norm * 1.8))))
        fog = int(fog_exp * (0.4 + 0.6 * dn))
        lut[i] = max(20, min(255, fog))
    return bytes(lut)


# ═══════════════════════════════════════════════════════════════════
#  RayRenderer
# ═══════════════════════════════════════════════════════════════════

class RayRenderer:
    """High-performance raycasting renderer backed by a C extension.

    Parameters
    ----------
    zone : Zone
        Loaded zone data with tiles, heights, textures.
    atlas : TextureAtlas
        Pre-loaded texture atlas for tile textures.
    sw, sh : int
        Internal render resolution (framebuffer pixel size).
    fov : float
        Horizontal field of view in radians (default: 60°).
    dn : float
        Day/night factor 0.0 (night) – 1.0 (day).
    """

    def __init__(
        self,
        zone: Zone,
        atlas: TextureAtlas,
        *,
        sw: int = 640,
        sh: int = 360,
        fov: float = math.pi / 3.0,
        dn: float = 1.0,
    ) -> None:
        if not _HAS_C:
            raise RuntimeError(
                "C extension _ray_render not found.  "
                "Build with: python build_ext.py build_ext --inplace"
            )

        self.sw = sw
        self.sh = sh
        self.fov = fov

        # Allocate framebuffer (reused every frame)
        self._fb = bytearray(sw * sh * 3)

        # Allocate depth buffer (output from render_frame, input to entities)
        self._zbuf = bytearray(sw * 8)  # float64 per column

        # Allocate per-pixel depth buffer (float32 per pixel)
        self._depth_px = bytearray(sw * sh * 4)

        # Create a pygame Surface that references the framebuffer
        self._surf = pygame.image.frombuffer(self._fb, (sw, sh), "RGB")

        # Build all static buffers from zone + atlas
        self._build_buffers(zone, atlas, dn)

    # ──────────────────────────────────────────────────────────────
    #  Buffer construction
    # ──────────────────────────────────────────────────────────────

    def _build_buffers(
        self,
        zone: Zone,
        atlas: TextureAtlas,
        dn: float,
    ) -> None:
        """Pre-compute all data buffers for the C renderer."""
        self._map_w = zone.width
        self._map_h = zone.height
        self._is_interior = int(zone.first_person)

        # ── Tile grid (flat int32) ──
        _s2i = tile_str_to_int
        self._tiles_buf = array.array(
            "i", [_s2i(t) for row in zone.tiles for t in row]
        ).tobytes()

        # ── Per-cell solid map (replaces per-tile wall_lut) ──
        #
        # A cell is solid (blocks rays, blocks movement) if:
        #   1. It's a full-height wall tile, OR
        #   2. The floor/ceiling gap is < 0.1 (geometry-based wall)
        #
        # Short walls (counters, railings) are NOT solid — they are
        # geometry features rendered by floor/ceiling step walls.
        #
        # NOTE: navi_grid NAV_SOLID is for pathfinding, not raycasting.
        # Counter-tops and low-gap cells are pathfinding-solid but ray-
        # transparent, so we always use the renderer-specific logic here.
        compiled = getattr(zone, "compiled", None)
        self._cell_solid = self._build_cell_solid(zone)
        self._wall_buf = bytes(self._cell_solid)

        # ── Number of tiles (determines per-tile LUT sizes & atlas) ──
        num_tiles = max(len(thin_wall_lut()), 1)
        self._num_tiles = num_tiles

        # ── Texture atlas (packed RGB: num_tiles × 64 × 64 × 3) ──
        self._atlas_buf = self._build_atlas(atlas, num_tiles)

        # ── Fog LUT ──
        ambient = int(200 + 55 * dn)
        self._fog_buf = build_fog_lut(ambient, dn)

        # ── Floor / ceiling heights (flat float64) ──
        if compiled and _HAS_NUMPY and "floor_z" in compiled:
            self._fh_buf = compiled["floor_z"].astype(np.float64).tobytes()
            self._ch_buf = compiled["ceil_z"].astype(np.float64).tobytes()
        else:
            self._fh_buf = array.array(
                "d", [h for row in zone.floor_heights for h in row]
            ).tobytes()
            self._ch_buf = array.array(
                "d", [h for row in zone.ceil_heights for h in row]
            ).tobytes()

        # ── Floor / ceiling texture overrides (flat int32, -1 = use tile) ──
        self._ft_buf = self._build_tex_override(zone.floor_textures)
        # Ceiling: default to "concrete" instead of mirroring the floor tile
        self._ct_buf = self._build_tex_override(
            zone.ceil_textures, default_tile="concrete"
        )

        # ── Per-cell face texture grid (int32[map_h * map_w * 4]) ──
        # Resolves TileDef.tex_for_face(face, rotation) for each cell.
        # Layout: for cell index ci, ci*4+0=N, ci*4+1=S, ci*4+2=E, ci*4+3=W
        # Value of -1 means "use the base tile texture" (no per-face override).
        self._face_tex_buf = self._build_face_tex_grid(zone)

        # ── Wall type LUTs (for multi-type DDA) ──
        self._thin_buf  = bytes(thin_wall_lut())
        self._tall_buf  = bytes(tall_wall_lut())

        # ── Height-scale LUT (float64 per tile) ──
        hs_list = hs_lut()
        # Pad to num_tiles if needed
        while len(hs_list) < num_tiles:
            hs_list.append(1.0)
        self._hs_buf = array.array("d", hs_list[:num_tiles]).tobytes()

        # ── Alt-texture LUT for tall wall extensions (int32 per tile) ──
        at_list = alt_tex_lut()
        while len(at_list) < num_tiles:
            at_list.append(-1)
        self._alt_tex_buf = array.array("i", at_list[:num_tiles]).tobytes()

        # ── Per-cell spatial lighting (float64 flat grid) ──
        if (compiled and _HAS_NUMPY
                and "light_levels" in compiled):
            self._light_buf = compiled["light_levels"].astype(
                np.float64).tobytes()
        else:
            ll = zone.light_levels
            if not ll or len(ll) != zone.height:
                ll = [[1.0] * zone.width for _ in range(zone.height)]
            self._light_buf = array.array(
                "d", [v for row in ll for v in row]
            ).tobytes()

        # ── Transparent wall LUT (for see-through tile walls) ──
        trans_ba = transparent_lut()
        while len(trans_ba) < num_tiles:
            trans_ba.append(0)
        self._trans_buf = bytes(trans_ba[:num_tiles])

        # ── Overlay wall buffers (free-form segments) ──
        #    Packed as 7 doubles per wall:
        #      [x1, y1, x2, y2, height_scale, tile_id, flags]
        ov_walls = getattr(zone, "overlay_walls", [])
        self._n_overlay = len(ov_walls)
        if ov_walls:
            ov_data: list[float] = []
            for ow in ov_walls:
                tid = _s2i(ow.texture)
                flags = (1 if ow.transparent else 0)
                ov_data.extend([
                    ow.x1, ow.y1, ow.x2, ow.y2,
                    ow.height_scale, float(tid), float(flags),
                ])
            self._overlay_buf = array.array("d", ov_data).tobytes()
        else:
            self._overlay_buf = array.array("d", [0.0] * 7).tobytes()

        # ── Cache zone entities for billboard rendering ──
        self._zone_entities = zone.entities

        # ── Wall-segment buffers (stacked textures per face) ──
        self._build_segment_buffers(zone)

        # ── Step-wall buffers (floor/ceiling mass side faces) ──
        self._build_step_wall_buffers(zone)

        # ── Per-tile v_scale LUT (float64 per tile) ──
        vs_list: list[float] = []
        for tid_str in TILE_REGISTRY:
            tid_int = tile_str_to_int(tid_str)
            while len(vs_list) <= tid_int:
                vs_list.append(1.0)
            td = tile_def(tid_str)
            vs_list[tid_int] = getattr(td, "v_scale", 1.0)
        while len(vs_list) < num_tiles:
            vs_list.append(1.0)
        self._vscale_buf = array.array("d", vs_list[:num_tiles]).tobytes()

    # ──────────────────────────────────────────────────────────────
    #  Geometry-based cell solid computation
    # ──────────────────────────────────────────────────────────────

    @staticmethod
    def _build_cell_solid(zone: Zone) -> bytearray:
        """Compute per-cell solid map from tile type + geometry.

        A cell is solid (opaque, blocks rays and movement) if:
          * It's a full-height wall tile (hs >= 1, not thin/transparent), OR
          * The floor-to-ceiling gap is < 0.1 (geometry says no air gap).

        Short walls / half-walls (counter_top, railing) are NOT solid.
        Their visual wall faces are rendered by floor/ceiling step walls.

        Returns a bytearray of size ``H * W`` (row-major).
        """
        MIN_GAP = 0.1
        H, W = zone.height, zone.width
        cell_solid = bytearray(H * W)
        _td = tile_def
        for r in range(H):
            for c in range(W):
                ci = r * W + c
                fh = zone.floor_heights[r][c]
                ch = zone.ceil_heights[r][c]
                gap = ch - fh

                # Tile-type detection (full-height walls)
                td = _td(zone.tiles[r][c])
                if td and td.wall:
                    if td.height_scale >= 0.999 and not td.thin_wall:
                        trans = getattr(td, "transparent", False)
                        if not trans:
                            cell_solid[ci] = 1
                            continue

                # Geometry-based: no passable gap (floor at or above ceiling)
                if gap < MIN_GAP:
                    cell_solid[ci] = 1

        return cell_solid

    def _build_atlas(self, atlas: TextureAtlas, num_tiles: int) -> bytes:
        """Pack all tile textures into a flat RGB buffer for C."""
        ts = TEX_SIZE
        tex_bytes = ts * ts * 3
        buf = bytearray(num_tiles * tex_bytes)

        for tid_str in TILE_REGISTRY:
            tid_int = tile_str_to_int(tid_str)
            if tid_int >= num_tiles:
                continue
            surf = atlas.get(tid_str)
            # Ensure correct size
            if surf.get_size() != (ts, ts):
                surf = pygame.transform.scale(surf, (ts, ts))
            # Convert to display format then extract raw RGB
            surf = surf.convert()
            raw = pygame.image.tostring(surf, "RGB")
            offset = tid_int * tex_bytes
            buf[offset : offset + tex_bytes] = raw

        return bytes(buf)

    @staticmethod
    def _build_tex_override(
        tex_grid: list[list[str]],
        default_tile: str = "",
    ) -> bytes:
        """Convert a string texture grid to flat int32 (-1 = use tile).

        If *default_tile* is set, empty cells use that tile's compact int
        instead of -1 (useful for ceiling defaults).
        """
        _s2i = tile_str_to_int
        default_id = _s2i(default_tile) if default_tile else -1
        values: list[int] = []
        for row in tex_grid:
            for cell in row:
                if cell:
                    try:
                        values.append(_s2i(cell))
                    except Exception:
                        values.append(default_id)
                else:
                    values.append(default_id)
        return array.array("i", values).tobytes()

    @staticmethod
    def _build_face_tex_grid(zone: Zone) -> bytes:
        """Build per-cell face-texture grid for directional wall textures.

        For each cell, stores 4 int32 values (N, S, E, W) that give the
        compact texture int to use for that face.  -1 means "use the base
        tile texture" (no per-face override).

        Resolution order (highest priority first):
        1. zone.face_textures[r][c][face] — per-face override (sculpt editor)
        2. zone.wall_textures[r][c]       — single texture, all 4 faces
        3. TileDef per-face (tex_n/s/e/w, front/back)
        4. Default wall_tex()
        """
        _s2i = tile_str_to_int
        _tdef = tile_def
        has_wt = (hasattr(zone, "wall_textures")
                  and zone.wall_textures
                  and len(zone.wall_textures) == zone.height)
        has_ft = (hasattr(zone, "face_textures")
                  and zone.face_textures
                  and len(zone.face_textures) == zone.height)
        values: list[int] = []
        for r in range(zone.height):
            for c in range(zone.width):
                tid_str = zone.tiles[r][c]
                rot = zone.rotations[r][c] if zone.rotations else 0
                td = _tdef(tid_str)
                base_tex = td.wall_tex()
                base_int = _s2i(base_tex)

                # ── face_textures: per-face overrides ─────────────
                ft: list[str] | None = None
                if has_ft:
                    ft_cell = zone.face_textures[r][c]
                    if ft_cell and any(ft_cell):
                        ft = ft_cell  # [N, S, E, W]

                # ── wall_textures: single override for all faces ──
                wt = ""
                if has_wt:
                    wt = zone.wall_textures[r][c]

                for fi, face_name in enumerate(FACE_NAMES):  # N,S,E,W
                    # Priority 1: face_textures per-face
                    if ft and ft[fi]:
                        values.append(_s2i(ft[fi]))
                        continue
                    # Priority 2: wall_textures (all faces)
                    if wt:
                        values.append(_s2i(wt))
                        continue
                    # Priority 3: TileDef per-face
                    ftex = td.tex_for_face(face_name, rot)
                    ftex_int = _s2i(ftex) if ftex else base_int
                    if ftex_int != base_int:
                        values.append(ftex_int)
                    else:
                        values.append(-1)
        return array.array("i", values).tobytes()

    def _build_segment_buffers(self, zone: Zone) -> None:
        """Build flat C-compatible buffers for per-face wall segments.

        The zone's ``wall_segments`` grid is ``[H][W][4]`` where each
        face entry is a list of ``[tex_key, y_top]`` pairs sorted
        bottom-to-top.  We pack these into four flat arrays for C:

        * ``seg_off``  — int32[H*W*4]: start offset into seg_tex/seg_ytop
        * ``seg_cnt``  — int32[H*W*4]: segment count for this face
        * ``seg_tex``  — int32[total]: texture compact-int per segment
        * ``seg_ytop`` — float64[total]: Y-top per segment
        """
        _s2i = tile_str_to_int
        H, W = zone.height, zone.width
        face_count = H * W * 4
        seg_off_list: list[int] = [0] * face_count
        seg_cnt_list: list[int] = [0] * face_count
        seg_tex_list: list[int] = []
        seg_ytop_list: list[float] = []

        has_ws = (hasattr(zone, "wall_segments")
                  and zone.wall_segments
                  and len(zone.wall_segments) == H)

        if has_ws:
            for r in range(H):
                for c in range(W):
                    cell = zone.wall_segments[r][c]
                    for fi in range(4):
                        key = (r * W + c) * 4 + fi
                        segs = cell[fi] if (cell and fi < len(cell)) else []
                        if not segs:
                            seg_off_list[key] = len(seg_tex_list)
                            seg_cnt_list[key] = 0
                            continue
                        seg_off_list[key] = len(seg_tex_list)
                        seg_cnt_list[key] = len(segs)
                        for seg in segs:
                            tex_key = str(seg[0]) if seg else ""
                            y_top = float(seg[1]) if len(seg) > 1 else 1.0
                            try:
                                seg_tex_list.append(_s2i(tex_key) if tex_key else -1)
                            except Exception:
                                seg_tex_list.append(-1)
                            seg_ytop_list.append(y_top)

        self._n_total_segs = len(seg_tex_list)
        self._seg_off_buf = array.array("i", seg_off_list).tobytes()
        self._seg_cnt_buf = array.array("i", seg_cnt_list).tobytes()
        # C expects at least 1 element even when empty
        if seg_tex_list:
            self._seg_tex_buf = array.array("i", seg_tex_list).tobytes()
            self._seg_ytop_buf = array.array("d", seg_ytop_list).tobytes()
        else:
            self._seg_tex_buf = array.array("i", [0]).tobytes()
            self._seg_ytop_buf = array.array("d", [0.0]).tobytes()

    def _build_step_wall_buffers(self, zone: Zone) -> None:
        """Build buffers for floor/ceiling step-wall textures, segments,
        and upper_wall_height."""
        _s2i = tile_str_to_int
        H, W = zone.height, zone.width
        face_count = H * W * 4

        # ── Floor step textures (int32[H*W*4], -1 = use face_tex) ──
        fst_vals = [-1] * face_count
        has_fst = (zone.floor_step_textures
                   and len(zone.floor_step_textures) == H)
        if has_fst:
            for r in range(H):
                for c in range(W):
                    cell = zone.floor_step_textures[r][c]
                    for fi in range(4):
                        t = cell[fi] if cell and fi < len(cell) else ""
                        if t:
                            fst_vals[(r * W + c) * 4 + fi] = _s2i(t)

        # Default unset step faces of non-wall tiles to "dirt" so
        # floor height transitions don't show grass on vertical faces.
        _tdef = tile_def
        dirt_id = _s2i("dirt")
        for r in range(H):
            for c in range(W):
                td_c = _tdef(zone.tiles[r][c])
                if td_c and td_c.wall:
                    continue
                base = (r * W + c) * 4
                for fi in range(4):
                    if fst_vals[base + fi] < 0:
                        fst_vals[base + fi] = dirt_id

        self._fstep_tex_buf = array.array("i", fst_vals).tobytes()

        # ── Ceiling step textures (int32[H*W*4], -1 = use face_tex) ──
        cst_vals = [-1] * face_count
        has_cst = (zone.ceil_step_textures
                   and len(zone.ceil_step_textures) == H)
        if has_cst:
            for r in range(H):
                for c in range(W):
                    cell = zone.ceil_step_textures[r][c]
                    for fi in range(4):
                        t = cell[fi] if cell and fi < len(cell) else ""
                        if t:
                            cst_vals[(r * W + c) * 4 + fi] = _s2i(t)
        self._cstep_tex_buf = array.array("i", cst_vals).tobytes()

        # ── Upper wall height (float64[H*W], 0.0 = auto) ──
        uwh_vals = [0.0] * (H * W)
        has_uwh = (zone.upper_wall_height
                   and len(zone.upper_wall_height) == H)
        if has_uwh:
            for r in range(H):
                for c in range(W):
                    uwh_vals[r * W + c] = zone.upper_wall_height[r][c]
        self._uwh_buf = array.array("d", uwh_vals).tobytes()

        # ── Floor step segments ──
        self._build_step_seg_arrays(
            zone.floor_step_segments, H, W,
            "_fstep_seg_off_buf", "_fstep_seg_cnt_buf",
            "_fstep_seg_tex_buf", "_fstep_seg_ytop_buf",
            "_n_fstep_segs")

        # ── Ceiling step segments ──
        self._build_step_seg_arrays(
            zone.ceil_step_segments, H, W,
            "_cstep_seg_off_buf", "_cstep_seg_cnt_buf",
            "_cstep_seg_tex_buf", "_cstep_seg_ytop_buf",
            "_n_cstep_segs")

    def _build_step_seg_arrays(
        self, seg_grid, H: int, W: int,
        off_attr: str, cnt_attr: str,
        tex_attr: str, ytop_attr: str, n_attr: str,
    ) -> None:
        """Build segment offset/count/tex/ytop arrays for step walls."""
        _s2i = tile_str_to_int
        face_count = H * W * 4
        off_list = [0] * face_count
        cnt_list = [0] * face_count
        tex_list: list[int] = []
        ytop_list: list[float] = []

        has_data = seg_grid and len(seg_grid) == H

        if has_data:
            for r in range(H):
                for c in range(W):
                    cell = seg_grid[r][c]
                    for fi in range(4):
                        key = (r * W + c) * 4 + fi
                        segs = cell[fi] if (cell and fi < len(cell)) else []
                        if not segs:
                            off_list[key] = len(tex_list)
                            cnt_list[key] = 0
                            continue
                        off_list[key] = len(tex_list)
                        cnt_list[key] = len(segs)
                        for seg in segs:
                            tk = str(seg[0]) if seg else ""
                            yt = float(seg[1]) if len(seg) > 1 else 1.0
                            try:
                                tex_list.append(_s2i(tk) if tk else -1)
                            except Exception:
                                tex_list.append(-1)
                            ytop_list.append(yt)

        setattr(self, n_attr, len(tex_list))
        setattr(self, off_attr, array.array("i", off_list).tobytes())
        setattr(self, cnt_attr, array.array("i", cnt_list).tobytes())
        if tex_list:
            setattr(self, tex_attr, array.array("i", tex_list).tobytes())
            setattr(self, ytop_attr, array.array("d", ytop_list).tobytes())
        else:
            setattr(self, tex_attr, array.array("i", [0]).tobytes())
            setattr(self, ytop_attr, array.array("d", [0.0]).tobytes())

    # ──────────────────────────────────────────────────────────────
    #  Rendering
    # ──────────────────────────────────────────────────────────────

    def render(self, px: float, py: float, angle: float,
               cam_h: float = 0.5, pitch: float = 0.0) -> pygame.Surface:
        """Render the scene and return the framebuffer Surface.

        The returned Surface references internal memory and is valid
        until the next call to ``render()``.

        *cam_h* is the camera height in world units (0 = floor, 1 = ceiling).
        *pitch* is the vertical look angle in radians (positive = up).
        Implemented as a horizon-line shift (2.5D y-shearing).
        """
        # Convert pitch angle to pixel horizon offset.
        # tan(pitch) * sh gives a screen-space shift that approximates
        # vertical look for moderate angles.
        horizon_shift = int(math.tan(pitch) * self.sh)
        _c_render_frame(
            self._fb,
            px, py, angle, self.fov, cam_h,
            horizon_shift,
            self.sw, self.sh,
            self._map_w, self._map_h,
            self._tiles_buf,
            self._wall_buf,
            self._atlas_buf,
            TEX_SIZE, self._num_tiles,
            self._fog_buf,
            self._fh_buf, self._ch_buf,
            self._ft_buf, self._ct_buf,
            self._is_interior,
            self._thin_buf,
            self._tall_buf,
            self._hs_buf,
            self._face_tex_buf,
            self._zbuf,
            self._light_buf,
            self._alt_tex_buf,
            self._depth_px,
            self._trans_buf,
            self._overlay_buf,
            self._n_overlay,
            # Wall-segment stacked textures
            self._seg_off_buf,
            self._seg_cnt_buf,
            self._seg_tex_buf,
            self._seg_ytop_buf,
            self._n_total_segs,
            self._vscale_buf,
            # Step-wall per-face textures + segments
            self._fstep_tex_buf,
            self._cstep_tex_buf,
            self._uwh_buf,
            self._fstep_seg_off_buf,
            self._fstep_seg_cnt_buf,
            self._fstep_seg_tex_buf,
            self._fstep_seg_ytop_buf,
            self._n_fstep_segs,
            self._cstep_seg_off_buf,
            self._cstep_seg_cnt_buf,
            self._cstep_seg_tex_buf,
            self._cstep_seg_ytop_buf,
            self._n_cstep_segs,
        )
        return self._surf

    def render_entities(
        self, px: float, py: float, angle: float
    ) -> None:
        """Render entity billboards into the current framebuffer.

        Must be called after ``render()`` so the z-buffer is populated.
        """
        if _c_render_entities is None:
            return
        entities = self._zone_entities
        if not entities:
            return

        # Build packed entity data: [x, y, r, g, b, h_scale, w_scale, tex_id]
        ent_list: list[float] = []
        for e in entities:
            pos = e.get("position")
            if not pos:
                continue
            spr = e.get("sprite", {})
            color = spr.get("color", [200, 200, 200])
            if len(color) < 3:
                color = [200, 200, 200]

            # Resolve texture: tile_entity.tile_type → prefab → -1
            tex_id = -1.0
            te = e.get("tile_entity", {})
            if te and te.get("tile_type"):
                try:
                    tex_id = float(tile_str_to_int(te["tile_type"]))
                except Exception:
                    pass
            if tex_id < 0:
                prefab = e.get("prefab", "")
                tex_key = _PREFAB_TEX_MAP.get(prefab, "")
                if tex_key:
                    try:
                        tex_id = float(tile_str_to_int(tex_key))
                    except Exception:
                        pass

            ent_list.extend([
                float(pos.get("x", 0)),
                float(pos.get("y", 0)),
                float(color[0]),
                float(color[1]),
                float(color[2]),
                0.6,      # h_scale (entity height relative to wall)
                0.4,      # w_scale (entity width relative to wall)
                tex_id,   # texture atlas ID (-1 = flat colour)
            ])

        n_ents = len(ent_list) // 8
        if n_ents == 0:
            return

        ent_buf = array.array("d", ent_list).tobytes()

        # Camera vectors for projection
        dir_x = math.cos(angle)
        dir_y = math.sin(angle)
        tan_hf = math.tan(self.fov * 0.5)
        plane_x = -dir_y * tan_hf
        plane_y = dir_x * tan_hf

        _c_render_entities(
            self._fb,
            self.sw, self.sh,
            px, py,
            dir_x, dir_y,
            plane_x, plane_y,
            self._depth_px,
            self._fog_buf,
            self._atlas_buf,
            TEX_SIZE, self._num_tiles,
            ent_buf,
            n_ents,
        )

    # ──────────────────────────────────────────────────────────────
    #  Collision helpers (for the demo)
    # ──────────────────────────────────────────────────────────────

    def is_solid(self, x: float, y: float) -> bool:
        """Check if a world position is inside a solid cell (geometry-based)."""
        ix, iy = int(x), int(y)
        if ix < 0 or ix >= self._map_w or iy < 0 or iy >= self._map_h:
            return True
        return bool(self._cell_solid[iy * self._map_w + ix])

    def floor_height_at(self, x: float, y: float) -> float:
        """Return floor height at a world position (0.0 for out-of-bounds)."""
        ix, iy = int(x), int(y)
        if ix < 0 or ix >= self._map_w or iy < 0 or iy >= self._map_h:
            return 0.0
        # _fh_buf is a flat float64 array (row-major)
        import struct
        idx = iy * self._map_w + ix
        offset = idx * 8  # 8 bytes per float64
        if offset + 8 > len(self._fh_buf):
            return 0.0
        return struct.unpack_from("d", self._fh_buf, offset)[0]

    def ceil_height_at(self, x: float, y: float) -> float:
        """Return ceiling height at a world position (1.0 for out-of-bounds)."""
        ix, iy = int(x), int(y)
        if ix < 0 or ix >= self._map_w or iy < 0 or iy >= self._map_h:
            return 1.0
        import struct
        idx = iy * self._map_w + ix
        offset = idx * 8
        if offset + 8 > len(self._ch_buf):
            return 1.0
        return struct.unpack_from("d", self._ch_buf, offset)[0]

    def can_move_to(
        self, x: float, y: float, radius: float = 0.2
    ) -> bool:
        """Collision check with a small radius buffer."""
        for dx in (-radius, 0, radius):
            for dy in (-radius, 0, radius):
                if self.is_solid(x + dx, y + dy):
                    return False
        return True

    def can_step_to(
        self, x: float, y: float, current_fh: float,
        max_step_up: float = 0.5, head_clearance: float = 0.4,
        radius: float = 0.2, max_step_down: float = 0.5,
    ) -> bool:
        """Height-aware collision: allow steps up/down within limits.

        Returns True if the player can move to (x, y) given their
        current floor height.  Checks that:
          1. The cell is not solid (full wall).
          2. The floor step-up is within *max_step_up*.
          3. The floor drop is within *max_step_down* (prevents
             walking off tall ledges and getting stuck).
          4. There is enough ceiling clearance for the player.
        """
        for dx_off in (-radius, 0, radius):
            for dy_off in (-radius, 0, radius):
                cx, cy = x + dx_off, y + dy_off
                ix, iy = int(cx), int(cy)
                if ix < 0 or ix >= self._map_w or iy < 0 or iy >= self._map_h:
                    return False
                ci = iy * self._map_w + ix
                if self._cell_solid[ci]:
                    return False
                target_fh = self.floor_height_at(cx, cy)
                target_ch = self.ceil_height_at(cx, cy)
                step = target_fh - current_fh
                if step > max_step_up:
                    return False  # step too high
                if -step > max_step_down:
                    return False  # drop too far — would get stuck
                # Check head clearance (player needs gap between fh and ch)
                gap = target_ch - target_fh
                if gap < head_clearance:
                    return False
        return True

    # ──────────────────────────────────────────────────────────────
    #  Zone update
    # ──────────────────────────────────────────────────────────────

    def update_zone(
        self, zone: Zone, atlas: TextureAtlas, dn: float = 1.0
    ) -> None:
        """Rebuild all buffers for a new zone."""
        self._build_buffers(zone, atlas, dn)

    def update_fog(self, dn: float) -> None:
        """Rebuild only the fog LUT (for day/night cycle)."""
        ambient = int(200 + 55 * dn)
        self._fog_buf = build_fog_lut(ambient, dn)

    def resize(self, sw: int, sh: int) -> None:
        """Change internal render resolution (reallocates framebuffer)."""
        if sw == self.sw and sh == self.sh:
            return
        self.sw = sw
        self.sh = sh
        self._fb = bytearray(sw * sh * 3)
        self._zbuf = bytearray(sw * 8)  # float64 per column
        self._depth_px = bytearray(sw * sh * 4)  # float32 per pixel
        self._surf = pygame.image.frombuffer(self._fb, (sw, sh), "RGB")
