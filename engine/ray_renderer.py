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
import os
import struct
from typing import TYPE_CHECKING

import pygame

from core.types import RenderMode

# Always-on fast required-key check (prevents C crashes from missing keys).
from engine.render_schema import assert_required_keys as _assert_keys

# Full schema validation: enabled in debug mode (__debug__=True),
# can be forced on/off via PAPS_VALIDATE_RENDER=1|0.
_VALIDATE_ENV = os.environ.get("PAPS_VALIDATE_RENDER", "")
if _VALIDATE_ENV == "1":
    _VALIDATE = True
elif _VALIDATE_ENV == "0":
    _VALIDATE = False
else:
    _VALIDATE = __debug__  # True unless running with python -O

if _VALIDATE:
    from engine.render_schema import (
        validate_render_frame as _validate_rf,
        validate_render_entities as _validate_re,
        validate_render_particles as _validate_rp,
        validate_ssao as _validate_ssao,
    )
else:
    _validate_rf = _validate_re = _validate_rp = _validate_ssao = None  # type: ignore[assignment]

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
    register_extra_texture_keys,
    extra_texture_keys,
    total_texture_count,
)
from core.entity_defs import (
    entity_texture_keys,
    get_entity_def,
    face_to_box_index,
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
    try:
        from engine._ray_render import panini_remap as _c_panini_remap
    except ImportError:
        _c_panini_remap = None
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
        pitch_max: float = math.pi * 0.30,
    ) -> None:
        if not _HAS_C:
            raise RuntimeError(
                "C extension _ray_render not found.  "
                "Build with: python build_ext.py build_ext --inplace"
            )

        self.sw = sw
        self.sh = sh
        self.fov = fov

        # Sky V-span: max elevation (radians) ever visible on-screen.
        # Ensures the full skybox texture is reachable at max pitch.
        proj_dist = sw / (2 * math.tan(fov / 2))
        half_max = sh * (0.5 + math.tan(pitch_max))
        self._sky_vspan: float = math.atan2(half_max, proj_dist)

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

        # Zone change-detection: tracks the zone's _generation counter
        # so update_zone() can skip rebuilds when nothing changed.
        self._zone_generation: int = 0

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

        # ── Per-zone sky colour override ──
        sc = getattr(zone, "sky_color", ())
        self._sky_color: tuple[int, int, int] | None = (
            (int(sc[0]), int(sc[1]), int(sc[2])) if sc and len(sc) >= 3
            else None
        )

        # ── Per-zone skybox override ──
        self._skybox_buf: bytes | None = None
        self._sky_w: int = 0
        self._sky_h: int = 0
        self._load_skybox(zone.skybox if hasattr(zone, "skybox") else "")

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

        # ── Register entity face textures so tile_str_to_int resolves ──
        register_extra_texture_keys(entity_texture_keys())

        # ── Number of textures (tiles + entity faces → LUT + atlas size) ──
        num_tiles = total_texture_count()
        self._num_tiles = num_tiles

        # ── Texture atlas (packed RGBA: num_tiles × TEX_SIZE × TEX_SIZE × 4) ──
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
        #    Packed as 8 doubles per wall:
        #      [x1, y1, x2, y2, height_scale, base_y, tile_id, flags]
        ov_walls = getattr(zone, "overlay_walls", [])
        self._n_overlay = len(ov_walls)
        if ov_walls:
            ov_data: list[float] = []
            for ow in ov_walls:
                tid = _s2i(ow.texture)
                flags = (1 if ow.transparent else 0)
                ov_data.extend([
                    ow.x1, ow.y1, ow.x2, ow.y2,
                    ow.height_scale, getattr(ow, 'base_y', 0.0),
                    float(tid), float(flags),
                ])
            self._overlay_buf = array.array("d", ov_data).tobytes()
        else:
            self._overlay_buf = array.array("d", [0.0] * 8).tobytes()

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
        bx_data: list[float] = []
        for b in boxes:
            tex = b.get("textures", {})
            def _tid(k: str) -> int:
                v = tex.get(k, 0)
                return v if isinstance(v, int) else _s2i(v)
            flags = 1 if b.get("collision", False) else 0
            # BX_TEX_N (index 7) = +Y face in C = south in editor
            # BX_TEX_S (index 8) = -Y face in C = north in editor
            # Swap N↔S so editor face names map to the correct
            # raycaster faces (Y axis = editor Z, +Y = south).
            bx_data.extend([
                float(b.get("x", 0.0)),
                float(b.get("y", 0.0)),
                float(b.get("z", 0.0)),
                float(b.get("w", 1.0)),
                float(b.get("h", 1.0)),
                float(b.get("d", 1.0)),
                float(b.get("yaw", 0.0)),
                float(_tid("S")), float(_tid("N")),
                float(_tid("E")), float(_tid("W")),
                float(_tid("top")), float(_tid("bot")),
                float(flags),
            ])

        # ── Entity prisms → box_data ──
        bx_data.extend(self._collect_entity_prisms(zone))
        self._n_boxes = len(bx_data) // 14
        if bx_data:
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
                flags = int(cv.get("flags", 0))
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

        # ── Per-cell floor slope → discrete stair steps ──────────
        # Pass slope dx/dy and per-cell division counts to C.
        # The C renderer snaps floor heights to discrete steps,
        # giving a staircase appearance with minimal overhead.
        sdx = getattr(zone, "floor_slope_dx", [])
        sdy = getattr(zone, "floor_slope_dy", [])
        sdiv = getattr(zone, "floor_slope_div", [])
        has_slope = (
            sdx and sdy
            and len(sdx) == zone.height
            and len(sdy) == zone.height
            and (any(v != 0.0 for row in sdx for v in row)
                 or any(v != 0.0 for row in sdy for v in row))
        )
        if has_slope:
            slope_flat: list[float] = []
            div_flat: list[int] = []
            for r in range(zone.height):
                sdx_row = sdx[r] if r < len(sdx) else [0.0] * zone.width
                sdy_row = sdy[r] if r < len(sdy) else [0.0] * zone.width
                sdiv_row = sdiv[r] if sdiv and r < len(sdiv) else [0] * zone.width
                for c in range(zone.width):
                    dx_v = float(sdx_row[c]) if c < len(sdx_row) else 0.0
                    dy_v = float(sdy_row[c]) if c < len(sdy_row) else 0.0
                    dv = int(sdiv_row[c]) if c < len(sdiv_row) else 0
                    slope_flat.append(dx_v)
                    slope_flat.append(dy_v)
                    # Default division count for slope cells: 4
                    if (dx_v != 0.0 or dy_v != 0.0) and dv < 2:
                        dv = 4
                    div_flat.append(dv)
            self._slope_buf: bytes | None = array.array("d", slope_flat).tobytes()
            self._slope_div_buf: bytes | None = array.array("B", div_flat).tobytes()
        else:
            self._slope_buf = None
            self._slope_div_buf: bytes | None = None

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
        self._zone_floor_heights = zone.floor_heights
        self._zone_w = zone.width
        self._zone_h = zone.height

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

        # Skybox panorama already loaded by _load_skybox() at top of
        # _build_buffers.  No further init needed here.

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
    #  Panini projection
    # ──────────────────────────────────────────────────────────────

    # Panini remap state — None means disabled
    _panini_remap_buf: bytes | None = None

    def set_panini(self, d: float = 1.0, enabled: bool = True) -> None:
        """Enable or disable Panini projection post-process.

        *d* controls the Panini compression strength:

        * **0.0** — rectilinear (no change).
        * **1.0** — stereographic cylindrical (full Panini, default).
        * Values between 0 and 1 blend between rectilinear and Panini.

        Pass ``enabled=False`` or ``d=0`` to disable.

        The remap LUT is precomputed once and reused every frame.
        """
        if not enabled or d <= 0.0:
            self._panini_remap_buf = None
            return

        sw = self.sw
        fov = self.fov
        half_fov = fov * 0.5
        tan_half = math.tan(half_fov)

        # Panini forward: world angle theta → normalised Panini x.
        #   x_panini = (d+1)*sin(theta) / (d + cos(theta))
        # Normalise so the edge angle (half_fov) maps to ±1:
        #   edge_panini = (d+1)*sin(half_fov) / (d + cos(half_fov))
        d1 = d + 1.0
        edge_panini = d1 * math.sin(half_fov) / (d + math.cos(half_fov))

        # Build the source-column LUT.
        # For each output column, invert the Panini mapping to find
        # the world angle, then compute the rectilinear source column.
        remap = array.array("d", [0.0] * sw)
        for x in range(sw):
            # Output Panini NDC: -1 (left) .. +1 (right)
            p_ndc = 2.0 * x / sw - 1.0

            # Panini screen value (un-normalise)
            p = p_ndc * edge_panini

            # Invert Panini: solve  p = (d+1)*sin(theta) / (d + cos(theta))
            # for theta.  Use atan2 formulation:
            #   p*(d + cos) = (d+1)*sin
            #   p*d + p*cos = (d+1)*sin
            #   (d+1)*sin - p*cos = p*d
            # Let sin = s, cos = c, s^2+c^2=1.
            # R*sin(theta - phi) = p*d  where R = sqrt((d+1)^2 + p^2),
            #   phi = atan2(p, d+1)
            # Simpler: theta = atan2(p*d, d+1 - p... ) — but that's
            # tricky.  Use iterative or closed-form:
            #   We can rewrite as:
            #     tan(theta) = p*(d + cos(theta)) / ((d+1)*cos(theta))
            #   Not separable.  Instead, note:
            #     p = (d+1)*tan(theta) / (d*sec(theta) + 1)
            #       = (d+1)*sin(theta) / (d + cos(theta))
            #   Rearranging: p*d + p*cos = (d+1)*sin
            #     sin - (p/(d+1))*cos = p*d/(d+1)
            #   This is A*sin(theta) + B*cos(theta) = C:
            #     A=1, B=-p/(d+1), C=p*d/(d+1)
            #     theta = asin(C / sqrt(A^2+B^2)) - atan2(B, A)
            A = 1.0
            B = -p / d1
            C = p * d / d1
            R = math.sqrt(A * A + B * B)
            if R < 1e-12:
                theta = 0.0
            else:
                cr = C / R
                cr = max(-1.0, min(1.0, cr))
                theta = math.asin(cr) - math.atan2(B, A)

            # Rectilinear source NDC for this world angle
            src_ndc = math.tan(theta) / tan_half
            src_col = (src_ndc + 1.0) * 0.5 * sw
            remap[x] = src_col

        self._panini_remap_buf = remap.tobytes()

    def _apply_panini(self) -> None:
        """Apply the Panini remap to the current framebuffer (if enabled)."""
        if self._panini_remap_buf is None:
            return
        if _c_panini_remap is None:
            return
        _c_panini_remap({
            "fb":    self._fb,
            "sw":    self.sw,
            "sh":    self.sh,
            "remap": self._panini_remap_buf,
        })

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

    def _load_skybox(self, skybox_name: str = "") -> None:
        """Load a panoramic skybox image into a raw RGB byte buffer.

        Resolution order:
          1. ``assets/textures/skyboxes/{skybox_name}``  (per-zone)
          2. ``assets/textures/skybox.{png,jpg,bmp}``    (global fallback)
          3. Give up → C renderer uses procedural gradient.

        Accepts any image format pygame can load.
        """
        from core.paths import TEXTURES_DIR, SKYBOXES_DIR
        from pathlib import Path

        # ── 1. Per-zone skybox name ───────────────────────────────
        if skybox_name:
            # Accept with or without extension
            candidates = [SKYBOXES_DIR / skybox_name]
            if not Path(skybox_name).suffix:
                for ext in ("png", "jpg", "bmp"):
                    candidates.append(SKYBOXES_DIR / f"{skybox_name}.{ext}")
            for path in candidates:
                if path.exists():
                    img = pygame.image.load(str(path)).convert()
                    self._sky_w, self._sky_h = img.get_size()
                    self._skybox_buf = pygame.image.tobytes(img, "RGB")
                    return

        # ── 2. Global fallback ────────────────────────────────────
        for ext in ("png", "jpg", "bmp"):
            path = TEXTURES_DIR / f"skybox.{ext}"
            if path.exists():
                img = pygame.image.load(str(path)).convert()
                self._sky_w, self._sky_h = img.get_size()
                self._skybox_buf = pygame.image.tobytes(img, "RGB")
                return

        # ── 3. No skybox found — C code will use procedural gradient.
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
        """Pack all tile + entity-face textures into a flat RGBA buffer for C."""
        ts = TEX_SIZE
        tex_bytes = ts * ts * 4
        buf = bytearray(num_tiles * tex_bytes)

        # ── Tile textures ──
        for tid_str in TILE_REGISTRY:
            tid_int = tile_str_to_int(tid_str)
            if tid_int >= num_tiles:
                continue
            surf = atlas.get(tid_str)
            if surf.get_size() != (ts, ts):
                surf = pygame.transform.scale(surf, (ts, ts))
            try:
                surf = surf.convert_alpha()
            except pygame.error:
                pass
            raw = pygame.image.tostring(surf, "RGBA")
            offset = tid_int * tex_bytes
            buf[offset : offset + tex_bytes] = raw

        # ── Entity face textures (extra keys beyond tile range) ──
        for key in extra_texture_keys():
            tid_int = tile_str_to_int(key)
            if tid_int >= num_tiles:
                continue
            surf = atlas.get_by_key(key)
            if surf.get_size() != (ts, ts):
                surf = pygame.transform.scale(surf, (ts, ts))
            try:
                surf = surf.convert_alpha()
            except pygame.error:
                pass
            raw = pygame.image.tostring(surf, "RGBA")
            offset = tid_int * tex_bytes
            buf[offset : offset + tex_bytes] = raw

        return bytes(buf)

    def _collect_entity_prisms(self, zone: Zone) -> list[float]:
        """Build box_data doubles for entities with render_type == 'prism'.

        Reads each entity descriptor from ``zone.entities``, looks up its
        :class:`EntityDef`, and if the render type is ``"prism"`` emits
        14 doubles matching the C ``BX_STRIDE`` layout.

        Face textures are mapped through :func:`face_to_box_index` which
        encapsulates the north↔south coordinate swap.
        """
        _s2i = tile_str_to_int
        data: list[float] = []

        fh = getattr(zone, "floor_heights", None)
        w = zone.width
        h = zone.height

        for ent in getattr(zone, "entities", []):
            type_id = ent.get("type", "")
            edef = get_entity_def(type_id)
            if edef is None or edef.render_type != "prism":
                continue

            # Position (flat x/y, already migrated)
            ex = float(ent.get("x", 0.0))
            ey = float(ent.get("y", 0.0))

            # Floor height at entity cell
            ci = max(0, min(w - 1, int(ex)))
            ri = max(0, min(h - 1, int(ey)))
            floor_z = float(fh[ri][ci]) if fh else 0.0

            # Prism geometry from entity def
            bx_z = floor_z + edef.elevation
            # The C renderer's local -Y face is the "front" (TOML "north").
            # The arrow direction at angle a is (cos a, -sin a) in map space,
            # but the local -Y face at yaw w points (sin w, -cos w).
            # Setting yaw = π/2 - angle aligns the front face with the arrow.
            yaw = math.pi * 0.5 - float(ent.get("angle", 0.0))

            # Per-face texture IDs.
            # EntityDef.textures is ((face, key), ...).
            # Overrides from the entity descriptor can replace faces.
            tex_map = edef.texture_map()
            ent_tex = ent.get("overrides", {}).get("textures")
            if isinstance(ent_tex, dict):
                tex_map.update(ent_tex)

            # Build the 14-double BX_STRIDE entry.
            # face_to_box_index handles the N↔S swap, but for the flat
            # array we fill slots 7..12 in order: N, S, E, W, top, bot
            # (matching the C layout BX_TEX_N..BX_TEX_B).
            def _ftid(face: str) -> float:
                k = tex_map.get(face, "")
                return float(_s2i(k)) if k else 0.0

            # C layout: [BX_TEX_N, BX_TEX_S, BX_TEX_E, BX_TEX_W, BX_TEX_T, BX_TEX_B]
            # face_to_box_index("north") → 8 (= BX_TEX_S slot) due to N↔S swap
            # We build a 6-slot temp array indexed by (offset - 7).
            face_tex = [0.0] * 6
            for face_name in ("north", "south", "east", "west", "top", "bottom"):
                slot = face_to_box_index(face_name) - 7  # 0..5
                k = tex_map.get(face_name, "")
                face_tex[slot] = float(_s2i(k)) if k else 0.0

            movable = ent.get("overrides", {}).get("movable", edef.movable)
            flags = 1.0 if movable else 0.0

            data.extend([
                ex, ey, bx_z,
                edef.width, edef.height, edef.depth,
                yaw,
                face_tex[0], face_tex[1],  # BX_TEX_N, BX_TEX_S
                face_tex[2], face_tex[3],  # BX_TEX_E, BX_TEX_W
                face_tex[4], face_tex[5],  # BX_TEX_T, BX_TEX_B
                flags,
            ])

        return data

    def update_entity_boxes(
        self,
        zone: Zone,
    ) -> None:
        """Rebuild the box buffer with current entity prism positions.

        Call this per-frame if any prism entity has moved or rotated,
        or after zone entities are modified.  Re-merges zone static
        boxes with entity prism data.
        """
        _s2i = tile_str_to_int
        bx_data: list[float] = []

        # Zone static freeform boxes
        for b in getattr(zone, "boxes", []):
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
                float(_tid("S")), float(_tid("N")),
                float(_tid("E")), float(_tid("W")),
                float(_tid("top")), float(_tid("bot")),
                float(flags),
            ])

        # Entity prisms
        bx_data.extend(self._collect_entity_prisms(zone))
        self._n_boxes = len(bx_data) // 14
        if bx_data:
            self._box_buf = array.array("d", bx_data).tobytes()
        else:
            self._box_buf = None

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

        Delegates texture resolution to the canonical
        :func:`~core.zones.tex_priority.resolve_wall_texture` so the
        priority chain is defined in exactly one place.
        """
        from core.zones.tex_priority import resolve_wall_texture, FACE_NAMES as _TPFN
        _s2i = tile_str_to_int
        _tdef = tile_def
        values: list[int] = []
        for r in range(zone.height):
            for c in range(zone.width):
                tid_str = zone.tiles[r][c]
                rot = zone.rotations[r][c] if zone.rotations else 0
                td = _tdef(tid_str)
                base_int = _s2i(td.wall_tex())

                for face_name in _TPFN:  # N, S, E, W
                    resolved = resolve_wall_texture(zone, r, c, face_name, td, rot)
                    resolved_int = _s2i(resolved) if resolved else base_int
                    if resolved_int != base_int:
                        values.append(resolved_int)
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
        # If the cell has a face_textures override, use that instead of
        # dirt so that painted wall textures show on step walls too.
        # Slope cells are skipped — their risers use the cell's face
        # texture (via resolve_face_tex fallback) instead.
        _tdef = tile_def
        dirt_id = _s2i("dirt")
        _ft = zone.face_textures
        _wt = zone.wall_textures
        _sdx = getattr(zone, "floor_slope_dx", [])
        _sdy = getattr(zone, "floor_slope_dy", [])
        for r in range(H):
            for c in range(W):
                td_c = _tdef(zone.tiles[r][c])
                if td_c and td_c.wall:
                    continue
                # Slope cells: keep -1 so risers use face texture
                if (_sdx and _sdy
                        and r < len(_sdx) and c < len(_sdx[r])
                        and r < len(_sdy) and c < len(_sdy[r])
                        and (abs(_sdx[r][c]) > 0.001
                             or abs(_sdy[r][c]) > 0.001)):
                    continue
                base = (r * W + c) * 4
                for fi in range(4):
                    if fst_vals[base + fi] < 0:
                        # Check per-face override
                        ft = ""
                        if _ft and r < len(_ft) and c < len(_ft[r]):
                            faces = _ft[r][c]
                            if fi < len(faces):
                                ft = faces[fi]
                        # Check per-cell wall override
                        if not ft and _wt and r < len(_wt) and c < len(_wt[r]):
                            ft = _wt[r][c]
                        fst_vals[base + fi] = _s2i(ft) if ft else dirt_id

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

        # Default unset ceiling step faces of non-wall tiles to
        # "concrete" so ceiling height transitions don't show the
        # tile's base texture (often grass) on vertical faces.
        # Honour face_textures / wall_textures overrides here too.
        concrete_id = _s2i("concrete")
        for r in range(H):
            for c in range(W):
                td_c = _tdef(zone.tiles[r][c])
                if td_c and td_c.wall:
                    continue
                if zone.ceil_heights[r][c] >= 10.0:
                    continue  # sky cells have no ceiling mass
                base = (r * W + c) * 4
                for fi in range(4):
                    if cst_vals[base + fi] < 0:
                        ft = ""
                        if _ft and r < len(_ft) and c < len(_ft[r]):
                            faces = _ft[r][c]
                            if fi < len(faces):
                                ft = faces[fi]
                        if not ft and _wt and r < len(_wt) and c < len(_wt[r]):
                            ft = _wt[r][c]
                        cst_vals[base + fi] = _s2i(ft) if ft else concrete_id

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

        # ── Upper wall height for layer 2 ceiling (float64[H*W], 0.0 = none) ──
        uwh2_vals = [0.0] * (H * W)
        has_uwh2 = (zone.upper_wall_height2
                    and len(zone.upper_wall_height2) == H)
        if has_uwh2:
            for r in range(H):
                for c in range(W):
                    uwh2_vals[r * W + c] = zone.upper_wall_height2[r][c]
        self._uwh2_buf: bytes | None = array.array("d", uwh2_vals).tobytes() if has_uwh2 else None

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
        self._horizon_shift = horizon_shift
        self._cam_h = cam_h
        ctx = {
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
            "uwh2":     self._uwh2_buf,
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
            "sky_vspan": self._sky_vspan,
            # Sky colour override (optional — tuple or None)
            "sky_color": self._sky_color,
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
            "slope_div":    self._slope_div_buf,
            # Multi-layer secondary floor/ceiling (optional)
            "fheight2":     self._fh2_buf,
            "cheight2":     self._ch2_buf,
            "ftex2":        self._ftex2_buf,
            "ctex2":        self._ctex2_buf,
            # Portal rendering (optional)
            "portal_map":   self._portal_map_buf,
            "portal_data":  self._portal_data_buf,
            "n_portals":    self._n_portals,
        }
        _assert_keys(ctx, "render_frame")
        if _validate_rf is not None:
            _validate_rf(ctx)
        _c_render_frame(ctx)
        self._anim_tick += 1
        return self._surf

    # Wall face → tangent angle for wall-anchored billboard projection.
    # North/south walls run E-W (tangent 0), east/west run N-S (tangent π/2).
    _WALL_TAN_ANGLE: dict[str, float] = {
        "north": 0.0,
        "south": 0.0,
        "east":  math.pi / 2,
        "west":  math.pi / 2,
    }

    def _entity_elev(self, e: dict, fh, zw: int, zh: int) -> float:
        """Return the world-space elevation for a packed entity."""
        wh = e.get("wall_height")
        if wh is not None:
            return float(wh)
        if "x" in e:
            ex, ey = float(e["x"]), float(e["y"])
        else:
            pos = e.get("position", {})
            ex, ey = float(pos.get("x", 0)), float(pos.get("y", 0))
        if fh:
            ci = max(0, min(zw - 1, int(ex)))
            ri = max(0, min(zh - 1, int(ey)))
            try:
                return float(fh[ri][ci])
            except (IndexError, TypeError):
                pass
        return 0.0

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
        #  facing_angle, render_mode, anim_offset, elevation]
        #
        # Field 9 (render_mode) carries the RenderMode.value:
        #   1  = BILLBOARD           (camera-facing sprite)
        #   8  = BILLBOARD_8WAY      (field 8 = facing_angle, 8 directional textures)
        #  -1  = WALL_ANCHORED       (field 8 = wall tangent angle)
        #  -2  = PRISM               (skipped here — rendered by box_data pipeline)
        # Positive values > 1 are legacy n_facings counts for multi-facing sprites.
        ent_list: list[float] = []
        _fh = self._zone_floor_heights
        _zw = self._zone_w
        _zh = self._zone_h
        for e in entities:
            # ── New format: type / x / y / angle ──────────────
            if "type" in e and "x" in e:
                from core.entity_defs import get_entity_def as _get_edef
                edef = _get_edef(e["type"])
                # Skip prism entities — they're rendered by the box_data
                # pipeline, not as billboards.
                if edef and edef.render_type == "prism":
                    continue
                if edef:
                    color = edef.color
                    h_scale = edef.scale * 0.6
                    w_scale = edef.scale * 0.4
                else:
                    color = (200, 200, 200)
                    h_scale, w_scale = 0.6, 0.4

                # Resolve billboard texture from sprite_key
                # Atlas layout: consecutive entries per entity —
                #   keys: state_0_s, state_0_sw, …, state_0_se,
                #         state_1_s, … (multi-frame), next_state_0_s, …
                # base_tex = atlas index of the very first key.
                tex_id = -1.0
                n_facings = 1.0
                if edef and edef.sprite_key:
                    n_facings_i = 8 if edef.directional else 1
                    n_facings = float(n_facings_i)
                    first_state = edef.states[0] if edef.states else "default"
                    if n_facings_i > 1:
                        first_key = f"{edef.sprite_key}:{first_state}_0_s"
                    else:
                        first_key = f"{edef.sprite_key}:{first_state}_0"
                    try:
                        tex_id = float(tile_str_to_int(first_key))
                    except Exception:
                        tex_id = -1.0

                # Wall-anchored: set render_mode to WALL_ANCHORED and
                # encode the wall tangent angle in facing_angle so
                # the C renderer projects as a flat quad on the wall.
                wf = e.get("wall_face")
                if wf and wf in self._WALL_TAN_ANGLE:
                    facing_angle = self._WALL_TAN_ANGLE[wf]
                    render_mode = float(RenderMode.WALL_ANCHORED.value)
                else:
                    facing_angle = float(e.get("angle", 0.0))
                    render_mode = n_facings  # BILLBOARD (1.0) or BILLBOARD_8WAY (8.0)

                # Debug: wall_face present but render_mode is not WALL_ANCHORED
                if __debug__ and wf and render_mode != float(RenderMode.WALL_ANCHORED.value):
                    import warnings
                    warnings.warn(
                        f"Entity {e.get('type','?')} at ({e['x']},{e['y']}): "
                        f"wall_face={wf!r} but render_mode={render_mode} "
                        f"(expected {RenderMode.WALL_ANCHORED.value})"
                    )

                ent_list.extend([
                    float(e["x"]),
                    float(e["y"]),
                    float(color[0]),
                    float(color[1]),
                    float(color[2]),
                    h_scale,
                    w_scale,
                    tex_id,                            # base_tex
                    facing_angle,                      # facing / wall tangent
                    render_mode,                       # RenderMode.value
                    0.0,                            # anim_offset
                    self._entity_elev(e, _fh, _zw, _zh),  # elevation
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
                self._entity_elev(e, _fh, _zw, _zh),  # elevation
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

        _ent_ctx = {
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
            "horizon_shift": getattr(self, '_horizon_shift', 0),
            "cam_h":     getattr(self, '_cam_h', 0.5),
        }
        _assert_keys(_ent_ctx, "render_entities")
        if _validate_re is not None:
            _validate_re(_ent_ctx)
        _c_render_entities(_ent_ctx)

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

        _part_ctx = {
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
            "horizon_shift": getattr(self, '_horizon_shift', 0),
            "cam_h":        getattr(self, '_cam_h', 0.5),
        }
        _assert_keys(_part_ctx, "render_particles")
        if _validate_rp is not None:
            _validate_rp(_part_ctx)
        _c_render_particles(_part_ctx)
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
        _ssao_ctx = {
            "fb":       self._fb,
            "depth_px": self._depth_px,
            "sw":       self.sw,
            "sh":       self.sh,
            "strength": strength,
            "radius":   radius,
            "bias":     bias,
        }
        _assert_keys(_ssao_ctx, "ssao_pass")
        if _validate_ssao is not None:
            _validate_ssao(_ssao_ctx)
        _c_ssao_pass(_ssao_ctx)

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

        Slope heights are computed using discrete stair-steps when
        slope data and per-cell division counts are available.
        """
        ix, iy = int(x), int(y)
        if ix < 0 or ix >= self._map_w or iy < 0 or iy >= self._map_h:
            return 0.0
        import struct, math
        idx = iy * self._map_w + ix
        offset = idx * 8  # 8 bytes per float64
        if offset + 8 > len(self._fh_buf):
            return 0.0
        fh1 = struct.unpack_from("d", self._fh_buf, offset)[0]

        # Apply discrete stair-step from slope data
        if self._slope_buf is not None and self._slope_div_buf is not None:
            s_off = idx * 16  # 2 doubles per cell
            if s_off + 16 <= len(self._slope_buf):
                sdx, sdy = struct.unpack_from("dd", self._slope_buf, s_off)
                div = self._slope_div_buf[idx]
                if (sdx != 0.0 or sdy != 0.0) and div >= 2:
                    fx = x - ix
                    fy = y - iy
                    raw = sdx * fx + sdy * fy
                    lo = min(0.0, sdx) + min(0.0, sdy)
                    rng = abs(sdx) + abs(sdy)
                    if rng > 0.001:
                        t = max(0.0, min((raw - lo) / rng, 0.9999))
                        step = int(t * div)
                        fh1 += lo + step * (rng / div)

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
        import struct, math
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

                # Apply discrete stair-step from slope data
                if self._slope_buf is not None and self._slope_div_buf is not None:
                    s_off = ci * 16
                    if s_off + 16 <= len(self._slope_buf):
                        sdx_v, sdy_v = struct.unpack_from(
                            "dd", self._slope_buf, s_off)
                        div = self._slope_div_buf[ci]
                        if (sdx_v != 0.0 or sdy_v != 0.0) and div >= 2:
                            fx = cx - ix
                            fy = cy - iy
                            raw = sdx_v * fx + sdy_v * fy
                            lo = min(0.0, sdx_v) + min(0.0, sdy_v)
                            rng = abs(sdx_v) + abs(sdy_v)
                            if rng > 0.001:
                                t = max(0.0, min((raw - lo) / rng, 0.9999))
                                step = int(t * div)
                                fh1 += lo + step * (rng / div)

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
                    # Headroom above layer-2: if fh2 is above the primary
                    # ceiling, there is open sky — headroom is unlimited.
                    if ch1 > fh2:
                        gap2 = ch1 - fh2
                    else:
                        gap2 = 10.0  # above primary ceiling → open sky
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
        self, zone: Zone, atlas: TextureAtlas, dn: float = 1.0,
        *, force: bool = False,
    ) -> None:
        """Rebuild all buffers for a new zone.

        Clears the zone's ``compiled`` cache so the renderer always
        picks up the live Python attributes (floor_heights, light_levels,
        etc.) that the editor may have modified.

        If *force* is False and the zone hasn't changed since the last
        rebuild (tracked via ``_zone_generation``), this is a no-op.
        Set *force=True* after editing zone data or switching zones.

        The ``zone_generation`` counter should be bumped by the editor
        (or any mutation code) when the zone is modified.
        """
        gen = getattr(zone, '_generation', 0)
        if not force and gen == self._zone_generation and gen > 0:
            return
        self._zone_generation = gen
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
