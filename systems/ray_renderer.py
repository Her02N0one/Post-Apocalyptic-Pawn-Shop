"""systems/ray_renderer.py — Python wrapper for the C raycasting renderer.

Manages buffer construction and provides a clean Python API around the
``_ray_render`` C extension.  Designed for both the standalone demo and
future integration with the editor/game renderer.

Usage
-----
    from systems.ray_renderer import RayRenderer

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

from core.tiles import (
    TILE_REGISTRY,
    tile_str_to_int,
    tile_def,
    wall_lut,
    thin_wall_lut,
    tall_wall_lut,
    alt_tex_lut,
    transparent_lut,
    hs_lut,
    solid_int_set,
    color_lut,
)
from core.types import FACE_NAMES
from systems.textures import TEX_SIZE

if TYPE_CHECKING:
    from core.zones import Zone
    from systems.textures import TextureAtlas

try:
    from systems._ray_render import render_frame as _c_render_frame
    try:
        from systems._ray_render import render_entities as _c_render_entities
    except ImportError:
        _c_render_entities = None
    try:
        from systems._ray_render import depth_to_grayscale as _c_depth_to_grayscale
    except ImportError:
        _c_depth_to_grayscale = None
    _HAS_C = True
except ImportError:
    _HAS_C = False
    _c_render_entities = None
    _c_depth_to_grayscale = None

# ═══════════════════════════════════════════════════════════════════
#  FOG COMPUTATION  (matches scenes/world/fp_lighting.py)
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

        # ── Wall LUT ──
        self._wall_buf = bytes(wall_lut())

        # ── Number of tiles (determines atlas size) ──
        num_tiles = max(len(self._wall_buf), 1)
        self._num_tiles = num_tiles

        # ── Texture atlas (packed RGB: num_tiles × 64 × 64 × 3) ──
        self._atlas_buf = self._build_atlas(atlas, num_tiles)

        # ── Fog LUT ──
        ambient = int(200 + 55 * dn)
        self._fog_buf = build_fog_lut(ambient, dn)

        # ── Floor / ceiling heights (flat float64) ──
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
        self._light_buf = array.array(
            "d", [v for row in zone.light_levels for v in row]
        ).tobytes()

        # ── Collision data (kept in Python for demo movement) ──
        self._solid_set = solid_int_set()
        tiles_ints = array.array(
            "i", [_s2i(t) for row in zone.tiles for t in row]
        )
        self._tiles_int_grid = tiles_ints

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

        Uses TileDef.tex_for_face(face_name, rotation) which resolves:
        1. Explicit per-face (tex_n/s/e/w) — absolute, ignores rotation
        2. Front/back system — rotation-relative
        3. Default wall_tex()
        """
        _s2i = tile_str_to_int
        _tdef = tile_def
        values: list[int] = []
        for r in range(zone.height):
            for c in range(zone.width):
                tid_str = zone.tiles[r][c]
                rot = zone.rotations[r][c] if zone.rotations else 0
                td = _tdef(tid_str)
                base_tex = td.wall_tex()
                base_int = _s2i(base_tex)
                for face_name in FACE_NAMES:  # N, S, E, W
                    ftex = td.tex_for_face(face_name, rot)
                    ftex_int = _s2i(ftex) if ftex else base_int
                    # Only store override if different from base
                    if ftex_int != base_int:
                        values.append(ftex_int)
                    else:
                        values.append(-1)
        return array.array("i", values).tobytes()

    # ──────────────────────────────────────────────────────────────
    #  Rendering
    # ──────────────────────────────────────────────────────────────

    def render(self, px: float, py: float, angle: float) -> pygame.Surface:
        """Render the scene and return the framebuffer Surface.

        The returned Surface references internal memory and is valid
        until the next call to ``render()``.
        """
        _c_render_frame(
            self._fb,
            px, py, angle, self.fov,
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
        _PREFAB_TEX_MAP = {
            "crate": "crate_stack",
            "wooden_crate": "crate_stack",
            "shelf": "shelf_wall",
            "table": "table",
            "stool": "stool",
            "counter": "counter_top",
            "lantern": "metal",
        }
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
        """Check if a world position is inside a solid tile."""
        ix, iy = int(x), int(y)
        if ix < 0 or ix >= self._map_w or iy < 0 or iy >= self._map_h:
            return True
        tid = self._tiles_int_grid[iy * self._map_w + ix]
        return tid in self._solid_set

    def can_move_to(
        self, x: float, y: float, radius: float = 0.2
    ) -> bool:
        """Collision check with a small radius buffer."""
        for dx in (-radius, 0, radius):
            for dy in (-radius, 0, radius):
                if self.is_solid(x + dx, y + dy):
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
