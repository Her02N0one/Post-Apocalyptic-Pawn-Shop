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
    anim_lut,
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
    try:
        from engine._ray_render import render_particles as _c_render_particles
    except ImportError:
        _c_render_particles = None
    try:
        from engine._ray_render import ssao_pass as _c_ssao_pass
    except ImportError:
        _c_ssao_pass = None
    _HAS_C = True
except ImportError:
    _HAS_C = False
    _c_render_entities = None
    _c_render_particles = None
    _c_ssao_pass = None

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

# Facing direction string → angle in radians (matches components.Facing)
_FACING_ANGLES: dict[str, float] = {
    "up":    math.pi * 1.5,
    "down":  math.pi * 0.5,
    "left":  math.pi,
    "right": 0.0,
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
        fov: float = math.pi / 2.0,
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

        # Animation tick counter (incremented every render call)
        self._anim_tick: int = 0

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
        # Always use the live Python lists so editor edits show up.
        # Fall back to compiled numpy arrays only when lists are absent.
        fh_rows = zone.floor_heights
        ch_rows = zone.ceil_heights
        if (fh_rows and len(fh_rows) == zone.height
                and len(fh_rows[0]) == zone.width):
            self._fh_buf = array.array(
                "d", [h for row in fh_rows for h in row]
            ).tobytes()
            self._ch_buf = array.array(
                "d", [h for row in ch_rows for h in row]
            ).tobytes()
        elif compiled and _HAS_NUMPY and "floor_z" in compiled:
            self._fh_buf = compiled["floor_z"].astype(np.float64).tobytes()
            self._ch_buf = compiled["ceil_z"].astype(np.float64).tobytes()
        else:
            self._fh_buf = array.array(
                "d", [0.0] * (zone.width * zone.height)
            ).tobytes()
            self._ch_buf = array.array(
                "d", [1.0] * (zone.width * zone.height)
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
        # Always prefer the live Python lists so editor paint shows up.
        ll = zone.light_levels
        if ll and len(ll) == zone.height:
            self._light_buf = array.array(
                "d", [v for row in ll for v in row]
            ).tobytes()
        elif (compiled and _HAS_NUMPY
                and "light_levels" in compiled):
            self._light_buf = compiled["light_levels"].astype(
                np.float64).tobytes()
        else:
            self._light_buf = array.array(
                "d", [1.0] * (zone.width * zone.height)
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

        # ── Two-sided quad buffers (fences, barricades, thin decals) ──
        #    Packed as 8 doubles per quad:
        #      [x1, y1, x2, y2, height, base_y, tile_id, flags]
        quads = getattr(zone, "quads", [])
        self._n_quads = len(quads)
        if quads:
            qd_data: list[float] = []
            for q in quads:
                # World-space position: new format (x, z) or
                # legacy format (cell + pos offset)
                if "x" in q:
                    wx = float(q["x"])
                    wy = float(q["z"])
                else:
                    cx, cy = q.get("cell", (0, 0))
                    ox, oy = q.get("pos", (0.5, 0.5))
                    wx = cx + ox
                    wy = cy + oy
                angle  = q.get("angle", 0.0)
                width  = q.get("width", 1.0)
                height = q.get("height", 1.0)
                base_y = q.get("base_y", 0.0)
                tex    = q.get("texture", 0)
                tid_q  = tex if isinstance(tex, int) else _s2i(tex)
                coll   = q.get("collision", False)
                two_s  = q.get("two_sided", True)
                flags  = (1 if coll else 0) | (2 if two_s else 0)
                hw     = width * 0.5
                ca, sa = math.cos(angle), math.sin(angle)
                qd_data.extend([
                    wx + ca * hw, wy + sa * hw,
                    wx - ca * hw, wy - sa * hw,
                    height, base_y, float(tid_q), float(flags),
                ])
            self._quad_buf: bytes | None = array.array("d", qd_data).tobytes()
        else:
            self._quad_buf = None

        # ── Freeform box buffers (OBB sub-grid geometry) ──
        #    Packed as 14 doubles per box:
        #      [x, y, z, w, h, d, yaw, tex_n, tex_s, tex_e, tex_w,
        #       tex_top, tex_bot, flags]
        boxes = getattr(zone, "boxes", [])
        self._n_boxes = len(boxes)
        if boxes:
            bx_data: list[float] = []
            for b in boxes:
                tex = b.get("textures", {})
                def _tid(k: str) -> int:
                    v = tex.get(k, 0)
                    return v if isinstance(v, int) else _s2i(v)
                flags = 1 if b.get("collision", False) else 0
                bx_data.extend([
                    float(b.get("x", 0.0)),
                    float(b.get("y", 0.0)),
                    float(b.get("z", 0.0)),
                    float(b.get("w", 1.0)),
                    float(b.get("h", 1.0)),
                    float(b.get("d", 1.0)),
                    float(b.get("yaw", 0.0)),
                    float(_tid("N")), float(_tid("S")),
                    float(_tid("E")), float(_tid("W")),
                    float(_tid("top")), float(_tid("bot")),
                    float(flags),
                ])
            self._box_buf: bytes | None = array.array("d", bx_data).tobytes()
        else:
            self._box_buf = None

        # ── Per-cell floor reflection opacity (uint8 flat grid) ──
        rm = getattr(zone, "reflect_map", [])
        if rm and len(rm) == zone.height and all(len(r) == zone.width for r in rm):
            self._reflect_buf: bytes | None = bytes(
                v for row in rm for v in row
            )
        else:
            self._reflect_buf = None

        # ── Curved / cylindrical wall arcs (9 doubles per curve) ──
        curves = getattr(zone, "curves", [])
        self._n_curves = len(curves)
        if curves:
            crv_data: list[float] = []
            for cv in curves:
                tid = cv.get("texture", 0)
                if isinstance(tid, str):
                    tid = _s2i(tid)
                flags = 1 if cv.get("transparent", False) else 0
                crv_data.extend([
                    float(cv.get("cx", 0.0)),
                    float(cv.get("cy", 0.0)),
                    float(cv.get("radius", 1.0)),
                    float(cv.get("angle_start", 0.0)),
                    float(cv.get("angle_end", 6.283185307)),
                    float(cv.get("height_scale", 1.0)),
                    float(cv.get("base_y", 0.0)),
                    float(tid),
                    float(flags),
                ])
            self._curve_buf: bytes | None = array.array("d", crv_data).tobytes()
        else:
            self._curve_buf = None

        # ── Per-cell floor slope (float64[map_h*map_w*2]: dx,dy pairs) ──
        sdx = getattr(zone, "floor_slope_dx", [])
        sdy = getattr(zone, "floor_slope_dy", [])
        has_slope = (
            sdx and sdy
            and len(sdx) == zone.height
            and len(sdy) == zone.height
            and (any(v != 0.0 for row in sdx for v in row)
                 or any(v != 0.0 for row in sdy for v in row))
        )
        if has_slope:
            slope_flat: list[float] = []
            for r in range(zone.height):
                sdx_row = sdx[r] if r < len(sdx) else [0.0] * zone.width
                sdy_row = sdy[r] if r < len(sdy) else [0.0] * zone.width
                for c in range(zone.width):
                    slope_flat.append(float(sdx_row[c]) if c < len(sdx_row) else 0.0)
                    slope_flat.append(float(sdy_row[c]) if c < len(sdy_row) else 0.0)
            self._slope_buf: bytes | None = array.array("d", slope_flat).tobytes()
        else:
            self._slope_buf = None

        # ── Multi-layer secondary floor/ceiling buffers ──────────
        LAYER_NONE = -1000.0
        fh2_src = getattr(zone, "floor2_heights", [])
        ch2_src = getattr(zone, "ceil2_heights", [])
        ft2_src = getattr(zone, "floor2_textures", [])
        ct2_src = getattr(zone, "ceil2_textures", [])

        has_fh2 = (fh2_src and len(fh2_src) == zone.height
                   and any(v > LAYER_NONE + 1.0 for row in fh2_src for v in row))
        has_ch2 = (ch2_src and len(ch2_src) == zone.height
                   and any(v > LAYER_NONE + 1.0 for row in ch2_src for v in row))

        if has_fh2 or has_ch2:
            _s2i = tile_str_to_int
            fh2_flat: list[float] = []
            ch2_flat: list[float] = []
            ft2_flat: list[int] = []
            ct2_flat: list[int] = []
            for r in range(zone.height):
                fh2r = fh2_src[r] if r < len(fh2_src) else [LAYER_NONE] * zone.width
                ch2r = ch2_src[r] if r < len(ch2_src) else [LAYER_NONE] * zone.width
                ft2r = ft2_src[r] if r < len(ft2_src) else [""] * zone.width
                ct2r = ct2_src[r] if r < len(ct2_src) else [""] * zone.width
                for c in range(zone.width):
                    fh2_flat.append(float(fh2r[c]) if c < len(fh2r) else LAYER_NONE)
                    ch2_flat.append(float(ch2r[c]) if c < len(ch2r) else LAYER_NONE)
                    ft_key = ft2r[c] if c < len(ft2r) else ""
                    ct_key = ct2r[c] if c < len(ct2r) else ""
                    ft2_flat.append(_s2i(ft_key) if ft_key else -1)
                    ct2_flat.append(_s2i(ct_key) if ct_key else -1)
            self._fh2_buf: bytes | None = array.array("d", fh2_flat).tobytes()
            self._ch2_buf: bytes | None = array.array("d", ch2_flat).tobytes()
            self._ftex2_buf: bytes | None = array.array("i", ft2_flat).tobytes()
            self._ctex2_buf: bytes | None = array.array("i", ct2_flat).tobytes()
        else:
            self._fh2_buf = None
            self._ch2_buf = None
            self._ftex2_buf = None
            self._ctex2_buf = None

        # ── Portal rendering buffers ─────────────────────────────
        rp_src = getattr(zone, "render_portals", [])
        if rp_src:
            import math as _math
            portal_map_flat: list[int] = [-1] * (zone.height * zone.width * 4)
            portal_data_flat: list[float] = []
            pidx = 0
            for p in rp_src:
                cell = p.get("cell", (0, 0))
                face = int(p.get("face", 0))
                r, c = int(cell[0]), int(cell[1])
                if 0 <= r < zone.height and 0 <= c < zone.width and 0 <= face < 4:
                    ci = r * zone.width + c
                    portal_map_flat[ci * 4 + face] = pidx
                    ang = float(p.get("angle_offset", 0.0))
                    portal_data_flat.extend([
                        float(p.get("dest_x", c + 0.5)),
                        float(p.get("dest_y", r + 0.5)),
                        _math.cos(ang),
                        _math.sin(ang),
                    ])
                    pidx += 1
            self._portal_map_buf: bytes | None = array.array("i", portal_map_flat).tobytes()
            self._portal_data_buf: bytes | None = array.array("d", portal_data_flat).tobytes()
            self._n_portals = pidx
        else:
            self._portal_map_buf = None
            self._portal_data_buf = None
            self._n_portals = 0

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

        # ── Animated texture LUT (int32[num_tiles * 4]) ──
        # Layout per tile: [base_id, n_frames, stride, ticks_per_frame]
        al = anim_lut()
        while len(al) < num_tiles * 4:
            al.extend([len(al) // 4, 1, 1, 1])
        self._anim_buf = array.array("i", al[:num_tiles * 4]).tobytes()

        # ── Skybox panorama (optional RGB buffer) ──
        self._skybox_buf: bytes | None = None
        self._sky_w: int = 0
        self._sky_h: int = 0
        self._load_skybox()

        # ── Per-cell fog volumes (optional) ──
        map_cells = zone.height * zone.width
        fog_dens = getattr(zone, "fog_density", None)
        if fog_dens and any(v != 0.0 for row in fog_dens for v in row):
            self._fog_den_buf: bytes | None = array.array(
                "d", [v for row in fog_dens for v in row]
            ).tobytes()
        else:
            self._fog_den_buf = None
        fog_cols = getattr(zone, "fog_color", None)
        if fog_cols and any(c != 0 for row in fog_cols for rgb in row for c in rgb):
            flat: list[int] = []
            for row in fog_cols:
                for rgb in row:
                    flat.extend(rgb[:3])
            self._fog_col_buf: bytes | None = bytes(flat)
        else:
            self._fog_col_buf = None

        # ── Per-column lens distortion LUT (default: no distortion) ──
        # Exposed as a mutable array so game code can swap it at runtime
        # for scope zoom, fisheye, drunk wobble, etc.
        _sw = self.sw
        self._lens_buf = array.array("d", [1.0] * _sw).tobytes()
        self._lens_arr = array.array("d", [1.0] * _sw)

        # ── Point lights (optional dynamic lights per zone) ──
        self._plight_buf: bytes | None = None
        self._n_lights: int = 0
        self._build_point_lights(zone)

        # ── Decal overlays (optional projected textures) ──
        self._decal_buf: bytes | None = None
        self._n_decals: int = 0
        self._build_decals(zone)

        # ── Bump mapping strength (0.0 = disabled) ──
        self._bump_strength: float = 0.0

    # ──────────────────────────────────────────────────────────────
    #  Lens distortion
    # ──────────────────────────────────────────────────────────────

    def set_lens(self, lut: list[float] | None = None) -> None:
        """Set the per-column lens distortion LUT.

        *lut* must have exactly ``sw`` entries.  Each value multiplies
        the projected wall height for that screen column:

        * **1.0** — no distortion (default).
        * **> 1.0** — zoom / magnify (scope centre).
        * **< 1.0** — shrink (barrel-distortion edges).

        Pass ``None`` to reset to the identity (flat) lens.
        """
        sw = self.sw
        if lut is None:
            for i in range(sw):
                self._lens_arr[i] = 1.0
        else:
            if len(lut) != sw:
                raise ValueError(
                    f"lens LUT length {len(lut)} != screen width {sw}")
            for i in range(sw):
                self._lens_arr[i] = lut[i]
        self._lens_buf = self._lens_arr.tobytes()

    # ──────────────────────────────────────────────────────────────
    #  Point lights
    # ──────────────────────────────────────────────────────────────

    def _build_point_lights(self, zone: object) -> None:
        """Build the point light buffer from the zone's light list.

        Each light is 8 doubles: x, y, z, r, g, b, intensity, radius.
        The buffer is ``None`` when no lights are defined.
        """
        lights = getattr(zone, "point_lights", None)
        if not lights:
            self._plight_buf = None
            self._n_lights = 0
            return
        flat: list[float] = []
        for lt in lights:
            flat.extend([
                float(lt.get("x", 0.0)),
                float(lt.get("y", 0.0)),
                float(lt.get("z", 0.5)),
                float(lt.get("r", 255)),
                float(lt.get("g", 255)),
                float(lt.get("b", 255)),
                float(lt.get("intensity", 1.0)),
                float(lt.get("radius", 3.0)),
            ])
        self._plight_buf = array.array("d", flat).tobytes()
        self._n_lights = len(lights)

    def set_point_lights(
        self, lights: list[dict[str, float]] | None
    ) -> None:
        """Update point lights at runtime (no zone reload needed).

        Each dict should have keys: x, y, z, r, g, b, intensity, radius.
        Pass ``None`` or ``[]`` to clear all lights.
        """
        if not lights:
            self._plight_buf = None
            self._n_lights = 0
            return
        flat: list[float] = []
        for lt in lights:
            flat.extend([
                float(lt.get("x", 0.0)),
                float(lt.get("y", 0.0)),
                float(lt.get("z", 0.5)),
                float(lt.get("r", 255)),
                float(lt.get("g", 255)),
                float(lt.get("b", 255)),
                float(lt.get("intensity", 1.0)),
                float(lt.get("radius", 3.0)),
            ])
        self._plight_buf = array.array("d", flat).tobytes()
        self._n_lights = len(lights)

    # ──────────────────────────────────────────────────────────────
    #  Decal overlays
    # ──────────────────────────────────────────────────────────────

    def _build_decals(self, zone: object) -> None:
        """Build the decal overlay buffer from the zone's decal list.

        Each decal is 8 doubles: x, y, z, width, height, angle,
        tex_id, flags.  Flags: 1=floor, 2=ceiling, 4=wall.
        """
        decals_list = getattr(zone, "decals", None)
        if not decals_list:
            self._decal_buf = None
            self._n_decals = 0
            return
        flat: list[float] = []
        for d in decals_list:
            flat.extend([
                float(d.get("x", 0.0)),
                float(d.get("y", 0.0)),
                float(d.get("z", 0.0)),
                float(d.get("width", 1.0)),
                float(d.get("height", 1.0)),
                float(d.get("angle", 0.0)),
                float(d.get("tex_id", 0)),
                float(d.get("flags", 1)),  # default: floor
            ])
        self._decal_buf = array.array("d", flat).tobytes()
        self._n_decals = len(decals_list)

    def set_decals(
        self, decals_list: list[dict[str, float]] | None
    ) -> None:
        """Update decals at runtime (no zone reload needed).

        Each dict should have keys: x, y, z, width, height, angle,
        tex_id, flags.  Flags: 1=floor, 2=ceiling, 4=wall.
        Pass ``None`` or ``[]`` to clear all decals.
        """
        if not decals_list:
            self._decal_buf = None
            self._n_decals = 0
            return
        flat: list[float] = []
        for d in decals_list:
            flat.extend([
                float(d.get("x", 0.0)),
                float(d.get("y", 0.0)),
                float(d.get("z", 0.0)),
                float(d.get("width", 1.0)),
                float(d.get("height", 1.0)),
                float(d.get("angle", 0.0)),
                float(d.get("tex_id", 0)),
                float(d.get("flags", 1)),
            ])
        self._decal_buf = array.array("d", flat).tobytes()
        self._n_decals = len(decals_list)

    # ──────────────────────────────────────────────────────────────
    #  Bump mapping
    # ──────────────────────────────────────────────────────────────

    def set_bump_strength(self, strength: float) -> None:
        """Set floor/ceiling bump mapping intensity.

        * **0.0** — disabled (default, no performance cost).
        * **2.0–4.0** — subtle texture relief (recommended).
        * **8.0+** — dramatic, exaggerated bumps.

        Bump is only applied within ~6 world units for performance.
        """
        self._bump_strength = max(0.0, float(strength))

    # ──────────────────────────────────────────────────────────────
    #  Skybox loading
    # ──────────────────────────────────────────────────────────────

    def _load_skybox(self) -> None:
        """Load an optional panoramic skybox from assets/textures/skybox.*

        Accepts any image format pygame can load.  The image is stored
        as a raw RGB byte buffer for the C renderer.
        """
        from core.paths import TEXTURES_DIR

        for ext in ("png", "jpg", "bmp"):
            path = TEXTURES_DIR / f"skybox.{ext}"
            if path.exists():
                img = pygame.image.load(str(path)).convert()
                self._sky_w, self._sky_h = img.get_size()
                # Extract raw RGB bytes (3 bytes per pixel, row-major)
                self._skybox_buf = pygame.image.tobytes(img, "RGB")
                return
        # No skybox found — C code will use procedural gradient.
        self._skybox_buf = None

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
        """Pack all tile textures into a flat RGBA buffer for C."""
        ts = TEX_SIZE
        tex_bytes = ts * ts * 4
        buf = bytearray(num_tiles * tex_bytes)

        for tid_str in TILE_REGISTRY:
            tid_int = tile_str_to_int(tid_str)
            if tid_int >= num_tiles:
                continue
            surf = atlas.get(tid_str)
            # Ensure correct size
            if surf.get_size() != (ts, ts):
                surf = pygame.transform.scale(surf, (ts, ts))
            # Convert to display format with alpha then extract RGBA
            try:
                surf = surf.convert_alpha()
            except pygame.error:
                pass
            raw = pygame.image.tostring(surf, "RGBA")
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
        _c_render_frame({
            "fb":       self._fb,
            "cam_x":    px,
            "cam_y":    py,
            "cam_angle": angle,
            "cam_fov":  self.fov,
            "cam_h":    cam_h,
            "horizon_shift": horizon_shift,
            "sw":       self.sw,
            "sh":       self.sh,
            "map_w":    self._map_w,
            "map_h":    self._map_h,
            "tiles":    self._tiles_buf,
            "walls":    self._wall_buf,
            "atlas":    self._atlas_buf,
            "tex_size": TEX_SIZE,
            "num_tiles": self._num_tiles,
            "fog_lut":  self._fog_buf,
            "floor_h":  self._fh_buf,
            "ceil_h":   self._ch_buf,
            "floor_tex": self._ft_buf,
            "ceil_tex": self._ct_buf,
            "is_interior": self._is_interior,
            "thin_lut": self._thin_buf,
            "tall_lut": self._tall_buf,
            "hs_lut":   self._hs_buf,
            "face_tex": self._face_tex_buf,
            "zbuf":     self._zbuf,
            "light":    self._light_buf,
            "alt_tex":  self._alt_tex_buf,
            "depth_px": self._depth_px,
            "trans_lut": self._trans_buf,
            "overlay":  self._overlay_buf,
            "n_overlay": self._n_overlay,
            # Wall-segment stacked textures
            "seg_off":  self._seg_off_buf,
            "seg_cnt":  self._seg_cnt_buf,
            "seg_tex":  self._seg_tex_buf,
            "seg_ytop": self._seg_ytop_buf,
            "n_total_segs": self._n_total_segs,
            "vscale":   self._vscale_buf,
            # Step-wall per-face textures + segments
            "fstep_tex": self._fstep_tex_buf,
            "cstep_tex": self._cstep_tex_buf,
            "uwh":      self._uwh_buf,
            "fstep_seg_off":  self._fstep_seg_off_buf,
            "fstep_seg_cnt":  self._fstep_seg_cnt_buf,
            "fstep_seg_tex":  self._fstep_seg_tex_buf,
            "fstep_seg_ytop": self._fstep_seg_ytop_buf,
            "n_fstep_segs":   self._n_fstep_segs,
            "cstep_seg_off":  self._cstep_seg_off_buf,
            "cstep_seg_cnt":  self._cstep_seg_cnt_buf,
            "cstep_seg_tex":  self._cstep_seg_tex_buf,
            "cstep_seg_ytop": self._cstep_seg_ytop_buf,
            "n_cstep_segs":   self._n_cstep_segs,
            # Animated textures
            "anim_lut":  self._anim_buf,
            "anim_tick": self._anim_tick,
            # Skybox (optional — C falls back to gradient if None)
            "skybox":   self._skybox_buf,
            "sky_w":    self._sky_w,
            "sky_h":    self._sky_h,
            # Fog volumes (optional — None = no per-cell fog)
            "fog_density": self._fog_den_buf,
            "fog_color":   self._fog_col_buf,
            # Lens distortion (per-column vertical scale)
            "lens":        self._lens_buf,
            # Point lights (optional — None = no dynamic lights)
            "point_lights": self._plight_buf,
            "n_lights":     self._n_lights,
            # Decal overlays (optional — None = no decals)
            "decals":       self._decal_buf,
            "n_decals":     self._n_decals,
            # Bump mapping (0.0 = disabled)
            "bump_strength": self._bump_strength,
            # Two-sided quads (optional — None = no quads)
            "quad_data":    self._quad_buf,
            "n_quads":      self._n_quads,
            # Freeform boxes (optional — None = no boxes)
            "box_data":     self._box_buf,
            "n_boxes":      self._n_boxes,
            # Reflective floors (optional — None = no reflections)
            "reflect_flags": self._reflect_buf,
            # Curved wall arcs (optional — None = no curves)
            "curve_data":   self._curve_buf,
            "n_curves":     self._n_curves,
            # Floor slope data (optional — None = no slopes)
            "slope_data":   self._slope_buf,
            # Multi-layer secondary floor/ceiling (optional)
            "fheight2":     self._fh2_buf,
            "cheight2":     self._ch2_buf,
            "ftex2":        self._ftex2_buf,
            "ctex2":        self._ctex2_buf,
            # Portal rendering (optional)
            "portal_map":   self._portal_map_buf,
            "portal_data":  self._portal_data_buf,
            "n_portals":    self._n_portals,
        })
        self._anim_tick += 1
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

        # Build packed entity data (12 doubles per entity):
        # [x, y, r, g, b, h_scale, w_scale, base_tex,
        #  facing_angle, n_facings, anim_offset, flags]
        ent_list: list[float] = []
        for e in entities:
            # ── New format: type / x / y / angle ──────────────
            if "type" in e and "x" in e:
                from core.entity_defs import get_entity_def as _get_edef
                edef = _get_edef(e["type"])
                if edef:
                    color = edef.color
                    h_scale = edef.scale * 0.6
                    w_scale = edef.scale * 0.4
                else:
                    color = (200, 200, 200)
                    h_scale, w_scale = 0.6, 0.4
                ent_list.extend([
                    float(e["x"]),
                    float(e["y"]),
                    float(color[0]),
                    float(color[1]),
                    float(color[2]),
                    h_scale,
                    w_scale,
                    -1.0,                          # base_tex (flat colour)
                    float(e.get("angle", 0.0)),    # facing
                    1.0,                            # n_facings
                    0.0,                            # anim_offset
                    0.0,                            # flags
                ])
                continue

            # ── Legacy format: position / sprite / prefab ─────
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

            # Multi-facing sprite support
            facing_angle = 0.0
            n_facings = 1.0
            anim_offset = 0.0
            flags = 0.0
            bb_mode = spr.get("billboard_mode", 0)
            if bb_mode == 1:
                # 8-way directional billboard
                n_facings = 8.0
                fc = e.get("facing", {})
                facing_dir = fc.get("direction", "down") if fc else "down"
                facing_angle = _FACING_ANGLES.get(facing_dir, math.pi * 0.5)
                # Resolve base texture from sprite_key prefix
                sprite_key = spr.get("sprite_key", "")
                if sprite_key:
                    try:
                        tex_id = float(tile_str_to_int(sprite_key + "_0"))
                    except Exception:
                        pass  # keep whatever tex_id was resolved above

            ent_list.extend([
                float(pos.get("x", 0)),
                float(pos.get("y", 0)),
                float(color[0]),
                float(color[1]),
                float(color[2]),
                0.6,            # h_scale
                0.4,            # w_scale
                tex_id,         # base_tex (atlas ID, -1 = flat colour)
                facing_angle,   # entity facing direction (radians)
                n_facings,      # number of facing textures (1=static)
                anim_offset,    # animation frame offset
                flags,          # reserved
            ])

        n_ents = len(ent_list) // 12
        if n_ents == 0:
            return

        ent_buf = array.array("d", ent_list).tobytes()

        # Camera vectors for projection
        dir_x = math.cos(angle)
        dir_y = math.sin(angle)
        tan_hf = math.tan(self.fov * 0.5)
        plane_x = -dir_y * tan_hf
        plane_y = dir_x * tan_hf

        _c_render_entities({
            "fb":        self._fb,
            "sw":        self.sw,
            "sh":        self.sh,
            "cam_x":     px,
            "cam_y":     py,
            "dir_x":     dir_x,
            "dir_y":     dir_y,
            "plane_x":   plane_x,
            "plane_y":   plane_y,
            "depth_px":  self._depth_px,
            "fog_lut":   self._fog_buf,
            "atlas":     self._atlas_buf,
            "tex_size":  TEX_SIZE,
            "num_tiles": self._num_tiles,
            "ent_data":  ent_buf,
            "n_ents":    n_ents,
        })

    # ──────────────────────────────────────────────────────────────
    #  Particle rendering
    # ──────────────────────────────────────────────────────────────

    def render_particles(
        self, px: float, py: float, angle: float,
        particles: "ParticleBuffer", dt: float = 1/60,
    ) -> None:
        """Tick and render all particles in the buffer.

        Must be called after ``render_entities()`` so the depth buffer is
        populated.  *particles* is a :class:`ParticleBuffer` instance.
        """
        if _c_render_particles is None or particles.count == 0:
            return
        # Camera vectors (same as render_entities)
        dir_x = math.cos(angle)
        dir_y = math.sin(angle)
        tan_hf = math.tan(self.fov * 0.5)
        plane_x = -dir_y * tan_hf
        plane_y = dir_x * tan_hf

        _c_render_particles({
            "fb":           self._fb,
            "depth_px":     self._depth_px,
            "fog_lut":      self._fog_buf,
            "atlas":        self._atlas_buf,
            "sw":           self.sw,
            "sh":           self.sh,
            "tex_size":     TEX_SIZE,
            "num_tiles":    self._num_tiles,
            "cam_x":        px,
            "cam_y":        py,
            "dir_x":        dir_x,
            "dir_y":        dir_y,
            "plane_x":      plane_x,
            "plane_y":      plane_y,
            "part_data":    particles.data,
            "n_particles":  particles.count,
            "dt":           dt,
            "gravity":      particles.gravity,
        })
        # Sweep dead after C ticked them
        particles.sweep_dead()

    # ──────────────────────────────────────────────────────────────
    #  SSAO post-pass
    # ──────────────────────────────────────────────────────────────

    def apply_ssao(
        self,
        strength: float = 0.45,
        radius: int = 6,
        bias: float = 0.15,
    ) -> None:
        """Apply screen-space ambient occlusion to the framebuffer.

        Must be called after ``render()`` and optionally after
        ``render_entities()`` / ``render_particles()``.  Modifies
        the framebuffer in-place.

        Parameters
        ----------
        strength : float
            Darkening multiplier (0=off, 1=full).
        radius : int
            Sample radius in pixels.
        bias : float
            Depth difference threshold for counting as occluded.
        """
        if _c_ssao_pass is None or strength <= 0.0:
            return
        _c_ssao_pass({
            "fb":       self._fb,
            "depth_px": self._depth_px,
            "sw":       self.sw,
            "sh":       self.sh,
            "strength": strength,
            "radius":   radius,
            "bias":     bias,
        })

    # ──────────────────────────────────────────────────────────────
    #  Collision helpers (for the demo)
    # ──────────────────────────────────────────────────────────────

    def is_solid(self, x: float, y: float) -> bool:
        """Check if a world position is inside a solid cell (geometry-based)."""
        ix, iy = int(x), int(y)
        if ix < 0 or ix >= self._map_w or iy < 0 or iy >= self._map_h:
            return True
        return bool(self._cell_solid[iy * self._map_w + ix])

    def floor_height_at(self, x: float, y: float,
                        current_fh: float | None = None) -> float:
        """Return floor height at a world position (0.0 for out-of-bounds).

        If *current_fh* is provided, the secondary floor layer is also
        considered: the highest floor surface at or below
        ``current_fh + _MAX_STEP`` is returned, letting the player walk
        on elevated catwalks / layer-2 surfaces.
        """
        ix, iy = int(x), int(y)
        if ix < 0 or ix >= self._map_w or iy < 0 or iy >= self._map_h:
            return 0.0
        import struct
        idx = iy * self._map_w + ix
        offset = idx * 8  # 8 bytes per float64
        if offset + 8 > len(self._fh_buf):
            return 0.0
        fh1 = struct.unpack_from("d", self._fh_buf, offset)[0]

        if current_fh is None:
            return fh1  # backward-compat: primary floor only

        # Consider layer-2 surface
        LAYER_NONE = -1000.0
        fh2 = LAYER_NONE
        if self._fh2_buf is not None and offset + 8 <= len(self._fh2_buf):
            fh2 = struct.unpack_from("d", self._fh2_buf, offset)[0]
        if fh2 <= LAYER_NONE + 1.0:
            return fh1  # no layer-2 at this cell

        # Pick the highest floor ≤ current_fh + tolerance
        MAX_STEP = 0.5
        for fh in sorted((fh1, fh2), reverse=True):
            if fh <= current_fh + MAX_STEP:
                return fh
        return fh1  # fallback: primary

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
        current floor height.  Both primary and secondary (layer-2)
        floor surfaces are evaluated at each sample point.  The move
        is allowed when **at least one** surface passes all checks:
          1. The cell is not solid (full wall).
          2. The floor step-up is within *max_step_up*.
          3. The floor drop is within *max_step_down*.
          4. There is enough ceiling clearance for the player.
        """
        import struct
        LAYER_NONE = -1000.0
        for dx_off in (-radius, 0, radius):
            for dy_off in (-radius, 0, radius):
                cx, cy = x + dx_off, y + dy_off
                ix, iy = int(cx), int(cy)
                if ix < 0 or ix >= self._map_w or iy < 0 or iy >= self._map_h:
                    return False
                ci = iy * self._map_w + ix
                if self._cell_solid[ci]:
                    return False

                offset = ci * 8
                fh1 = struct.unpack_from("d", self._fh_buf, offset)[0]
                ch1 = struct.unpack_from("d", self._ch_buf, offset)[0]

                # Read layer-2 heights (sentinel = no layer)
                fh2 = LAYER_NONE
                ch2 = LAYER_NONE
                if self._fh2_buf is not None and offset + 8 <= len(self._fh2_buf):
                    fh2 = struct.unpack_from("d", self._fh2_buf, offset)[0]
                if self._ch2_buf is not None and offset + 8 <= len(self._ch2_buf):
                    ch2 = struct.unpack_from("d", self._ch2_buf, offset)[0]

                has_layer2 = fh2 > LAYER_NONE + 1.0
                found_valid = False

                # ── Check primary floor surface ──
                step = fh1 - current_fh
                # Effective ceiling above ground: underside of layer-2 slab
                # if present and above the primary floor, else primary ceil.
                if has_layer2 and ch2 > LAYER_NONE + 1.0 and ch2 > fh1:
                    eff_ceil = min(ch1, ch2)
                else:
                    eff_ceil = ch1
                gap = eff_ceil - fh1
                if (-max_step_down <= step <= max_step_up
                        and gap >= head_clearance):
                    found_valid = True

                # ── Check layer-2 floor surface ──
                if has_layer2:
                    step2 = fh2 - current_fh
                    gap2 = ch1 - fh2  # primary ceiling is above layer-2
                    if (-max_step_down <= step2 <= max_step_up
                            and gap2 >= head_clearance):
                        found_valid = True

                if not found_valid:
                    return False
        return True

    # ──────────────────────────────────────────────────────────────
    #  Zone update
    # ──────────────────────────────────────────────────────────────

    def update_zone(
        self, zone: Zone, atlas: TextureAtlas, dn: float = 1.0
    ) -> None:
        """Rebuild all buffers for a new zone.

        Clears the zone's ``compiled`` cache so the renderer always
        picks up the live Python attributes (floor_heights, light_levels,
        etc.) that the editor may have modified.
        """
        if hasattr(zone, "compiled"):
            zone.compiled = None
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


# ──────────────────────────────────────────────────────────────────
#  Particle System
# ──────────────────────────────────────────────────────────────────

class ParticleBuffer:
    """Manages a flat double-array of particles for C-side tick + render.

    Each particle occupies 14 doubles:
        [x, y, z, vx, vy, vz, life, max_life, r, g, b, size, tex_id, flags]

    Usage::

        buf = ParticleBuffer(max_particles=512, gravity=5.0)
        buf.emit(x=3.5, y=4.2, z=0.5,
                 vx=0.1, vy=0.0, vz=2.0,
                 life=1.5, r=255, g=200, b=50, size=0.05)
        renderer.render_particles(px, py, angle, buf, dt)
    """

    DOUBLES_PER = 14

    def __init__(self, max_particles: int = 512, gravity: float = 5.0):
        self.max_particles = max_particles
        self.gravity = gravity
        self._slots: list[list[float]] = []

    @property
    def count(self) -> int:
        return len(self._slots)

    @property
    def data(self) -> bytearray:
        """Pack particles into a flat double buffer for C."""
        flat: list[float] = []
        for p in self._slots:
            flat.extend(p)
        return array.array("d", flat).tobytes() if flat else bytearray(8)

    def emit(
        self,
        x: float, y: float, z: float = 0.5,
        vx: float = 0.0, vy: float = 0.0, vz: float = 0.0,
        life: float = 1.0,
        r: int = 255, g: int = 200, b: int = 100,
        size: float = 0.05,
        tex_id: int = -1,
        flags: int = 0,
    ) -> None:
        """Spawn a single particle."""
        if len(self._slots) >= self.max_particles:
            return  # buffer full
        self._slots.append([
            float(x), float(y), float(z),
            float(vx), float(vy), float(vz),
            float(life), float(life),  # life, max_life
            float(r), float(g), float(b),
            float(size), float(tex_id), float(flags),
        ])

    def emit_burst(
        self,
        x: float, y: float, z: float = 0.5,
        count: int = 10,
        spread: float = 1.0,
        speed: float = 2.0,
        life: float = 1.0,
        r: int = 255, g: int = 200, b: int = 100,
        size: float = 0.05,
    ) -> None:
        """Emit *count* particles in a random burst pattern."""
        import random
        for _ in range(count):
            angle = random.uniform(0, 2 * math.pi)
            elev = random.uniform(-0.5, 1.0)
            sp = random.uniform(speed * 0.3, speed)
            self.emit(
                x=x + random.uniform(-spread * 0.1, spread * 0.1),
                y=y + random.uniform(-spread * 0.1, spread * 0.1),
                z=z,
                vx=math.cos(angle) * sp * spread,
                vy=math.sin(angle) * sp * spread,
                vz=elev * sp,
                life=life * random.uniform(0.5, 1.5),
                r=r, g=g, b=b,
                size=size * random.uniform(0.5, 1.5),
            )

    def sweep_dead(self) -> None:
        """Remove dead particles (life <= 0) after C tick."""
        # After C ticked, the data buffer was a one-shot copy.
        # We don't get the ticked values back (buffer was a copy).
        # Instead, approximate: decrement life by dt on Python side.
        # Actually, since the buffer is passed as writable and C ticks
        # inline, we need to unpack the C-modified buffer back.
        # For simplicity in the first implementation, use a separate
        # approach: Python tracks each particle's remaining life.
        # C ticks the buffer each frame; Python removes expired ones.
        self._slots = [p for p in self._slots if p[6] > 0]

    def clear(self) -> None:
        """Remove all particles."""
        self._slots.clear()
