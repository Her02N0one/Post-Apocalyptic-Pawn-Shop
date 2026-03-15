"""scenes/world/fp_walls.py — Wall column rendering.

Defines ``draw_walls`` which is attached to ``Renderer`` as a method.
Uses a **generational strip cache** (two-buffer rotation) so that a
cache roll-over never causes a full-miss spike.

When the C extension ``systems._fast_walls`` is available, geometry
computation (cy0/cy1, tv0/tv1, cache_key, fog, etc.) runs in bulk C
instead of per-slice Python math — saving ~0.3 ms per frame.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pygame

from engine.raycaster import cast_walls
from engine.textures import TEX_SIZE
from core.tiles import tile_def as _tile_def, tile_str_to_int, tile_int_to_str
from core.types import FACE_NAMES

if TYPE_CHECKING:
    from scenes.world.fp_renderer import Renderer

# ── Try to import C-accelerated geometry ─────────────────────────
try:
    from engine._fast_walls import compute_wall_geometry as _c_geom
    _USE_C_WALLS = True
except ImportError:
    _USE_C_WALLS = False

# ── Module constant ──────────────────────────────────────────────
RAY_STEP = 4  # cast every Nth column (1 = full res)

_CACHE_GEN_LIMIT = 8000  # entries before rotating to a new generation

# WallSlice field indices (avoids namedtuple attribute overhead)
_WS_SX = 0          # screen_x
_WS_DIST = 1        # distance
_WS_H = 2           # height
_WS_TID = 3         # tile_id
_WS_SIDE = 4        # side
_WS_TEX_X = 5       # tex_x
_WS_HS = 6          # height_scale
_WS_RDX = 7         # ray_dir_x
_WS_RDY = 8         # ray_dir_y
_WS_MAP_X = 10      # map_x (grid column of hit cell)
_WS_MAP_Y = 11      # map_y (grid row of hit cell)
_WS_FACE = 12       # face (FACE_NORTH..FACE_WEST)

# AO distance cutoff — skip AO shadows for walls farther than this
_AO_MAX_DIST = 6.0

# Face name derivation — now uses pre-computed face constant from WallSlice
def _face_name_from_idx(face_idx: int) -> str:
    """Convert face constant (0–3) to cardinal name string."""
    return FACE_NAMES[face_idx] if 0 <= face_idx < 4 else "south"

# Per-tile face texture resolution (rotation-aware)
_face_has_dir: dict[str, bool] = {}

def _has_directional(tid: str) -> bool:
    """Does this tile have any directional texture overrides?"""
    cached = _face_has_dir.get(tid)
    if cached is not None:
        return cached
    td = _tile_def(tid)
    result = bool(td and td.has_directional_textures())
    _face_has_dir[tid] = result
    return result

def invalidate_face_cache() -> None:
    """Clear the face override cache (call after tile edits)."""
    _face_has_dir.clear()


def draw_walls(
    self: "Renderer",
    surface: pygame.Surface,
    sw: int, sh: int, half: int,
    px: float, py: float,
    angle: float, fov: float,
    tiles: list[list[str]],
    fog_lut: list[int], dn: float,
    rotations: list[list[int]] | None = None,
) -> tuple[list, dict, list[float], list[tuple]]:
    """Cast rays, draw wall columns.

    Returns ``(slices, plat_col, zbuf_full, deferred_halves)``.

    *plat_col* maps ``screen_x → (cy0, tile_id, hs, col_w)`` for
    the pre-rendered visplane surface.

    *zbuf_full* is the depth of the nearest **full-height** wall
    per column — used to cull entities behind solid walls.

    *deferred_halves* is a list of half-wall strip data that will
    be interleaved with entity billboards in painter's order so
    that half-walls naturally occlude entities behind them.
    """
    _ct0 = time.perf_counter()
    slices = cast_walls(
        px, py, angle, fov,
        sw, sh, tiles,
        step=RAY_STEP,
    )
    self._cast_time = time.perf_counter() - _ct0

    atlas = self._atlas
    _atlas_get = atlas.get
    _scale = pygame.transform.scale
    _fill = surface.fill
    _TEX = TEX_SIZE
    _TEX_M1 = TEX_SIZE - 1
    _step = RAY_STEP
    _BLEND = pygame.BLEND_MULT
    _sh = sh
    _half = half

    # ── Generational strip cache ─────────────────────────────
    strip_cache = self._strip_cache
    prev_cache = self._strip_cache_prev
    if len(strip_cache) > _CACHE_GEN_LIMIT:
        # Drain the old prev-gen's Surfaces into a size-keyed
        # free-list so that cache misses can RECYCLE existing
        # Surfaces instead of calling pygame.Surface() which
        # costs ~40-50 ms on Windows due to OS page-fault storms.
        _free = self._strip_free
        old_prev = prev_cache
        for _surf in old_prev.values():
            _sz = _surf.get_size()      # (col_w, draw_h_q)
            bucket = _free.get(_sz)
            if bucket is None:
                bucket = []
                _free[_sz] = bucket
            bucket.append(_surf)
        self._strip_cache_prev = strip_cache
        prev_cache = strip_cache
        strip_cache = {}
        self._strip_cache = strip_cache
    _cache_get = strip_cache.get
    _prev_get = prev_cache.get
    _free_list = self._strip_free

    col_cache = self._col_cache
    if len(col_cache) > 2000:
        col_cache.clear()

    plat_col: dict[int, tuple[int, int, float, int]] = {}

    # Full-wall-only depth buffer for entity culling.
    zbuf_full: list[float] = [1e10] * sw
    deferred_halves: list[tuple] = []

    # Batch blit list — collect (strip_surf, (x, y)) for full walls
    # and blit them all via surface.blits() in a single C-level call.
    full_blits: list[tuple] = []
    _full_append = full_blits.append

    # AO rects collected for batch processing
    ao_rects: list[tuple[int, int, int, int]] = []
    _ao_append = ao_rects.append
    _ao_max_dist = _AO_MAX_DIST

    # ── Choose C or Python geometry path ─────────────────────
    _has_dir = _has_directional
    _get_by_key = atlas.get_by_key
    _face_nm_idx = _face_name_from_idx
    _rots = rotations  # may be None

    if _USE_C_WALLS:
        # Bulk-compute geometry in C — eliminates ~120 iterations
        # of Python-level float math + bitwise cache-key packing.
        _fog_bytes = bytes(fog_lut)
        # C ext needs int tile_ids — convert at the boundary
        _s2i = tile_str_to_int
        c_slices = [
            (ws[0], ws[1], ws[2], _s2i(ws[3]), ws[4], ws[5], ws[6])
            for ws in slices
        ]
        geom = _c_geom(c_slices, sh, half, _TEX, _fog_bytes, _step, sw)

        for gi, g in enumerate(geom):
            ws_sx     = g[0]
            ws_dist   = g[1]
            cy0       = g[2]
            cy1       = g[3]
            draw_h    = g[4]
            draw_h_q  = g[5]
            tv0       = g[6]
            tv1       = g[7]
            col_w     = g[8]
            fog       = g[9]
            tx_s      = g[10]
            cache_key = g[11]
            tid       = tile_int_to_str(g[12])  # int→str at boundary
            ws_side   = g[13]
            hs        = g[14]
            is_full   = g[15]
            ao_y      = g[16]
            ao_h      = g[17]
            has_vp    = g[18]
            src_idx   = g[19]  # original index into slices[]
            ao_y      = g[16]
            ao_h      = g[17]
            has_vp    = g[18]

            # Face-texture override check (rotation-aware)
            face_key = None
            if _has_dir(tid):
                _ws = slices[src_idx]
                face = _face_nm_idx(_ws[_WS_FACE])
                _rot = 0
                if _rots:
                    _my = _ws[_WS_MAP_Y]; _mx = _ws[_WS_MAP_X]
                    if 0 <= _my < len(_rots) and 0 <= _mx < len(_rots[0]):
                        _rot = _rots[_my][_mx]
                td = _tile_def(tid)
                if td:
                    face_key = td.tex_for_face(face, _rot)
                    # Only use override if it differs from default wall tex
                    if face_key == td.wall_tex():
                        face_key = None
                if face_key:
                    cache_key = hash((face_key, tx_s, tv0, tv1,
                                      draw_h_q, col_w, ws_side, fog >> 6))

            # Two-generation lookup: current first, then previous.
            cached = _cache_get(cache_key)
            if cached is not None:
                strip_surf = cached
            else:
                prev_hit = _prev_get(cache_key)
                if prev_hit is not None:
                    strip_surf = prev_hit
                else:
                    tex_surf = _get_by_key(face_key) if face_key else _atlas_get(tid)
                    strip = tex_surf.subsurface((tx_s, tv0, 1, tv1 - tv0))

                    _sz = (col_w, draw_h_q)
                    _bucket = _free_list.get(_sz)
                    if _bucket:
                        strip_surf = _bucket.pop()
                        _scale(strip, _sz, strip_surf)
                    else:
                        strip_surf = _scale(strip, _sz)

                    if ws_side == 1 and fog < 250:
                        strip_surf.fill(
                            (175 * fog // 255, 168 * fog // 255,
                             155 * fog // 255),
                            special_flags=_BLEND,
                        )
                    elif ws_side == 1:
                        strip_surf.fill((175, 168, 155), special_flags=_BLEND)
                    elif fog < 250:
                        strip_surf.fill((fog, fog, fog), special_flags=_BLEND)

                    strip_cache[cache_key] = strip_surf

            if is_full:
                # Check if this full-height wall is transparent →
                # defer it for painter's-order alpha compositing.
                _ws_c = slices[src_idx]
                _td_c = _tile_def(_ws_c[_WS_TID])
                if _td_c and _td_c.transparent:
                    deferred_halves.append((
                        ws_dist, strip_surf,
                        ws_sx, cy0, cy1, col_w, draw_h,
                        False, tid, hs, _half, True,
                    ))
                else:
                    _full_append((strip_surf, (ws_sx, cy0)))
                    _sx_end = ws_sx + col_w
                    if _sx_end > sw:
                        _sx_end = sw
                    zbuf_full[ws_sx:_sx_end] = [ws_dist] * (_sx_end - ws_sx)
                    if ao_h > 0:
                        _ao_append((ws_sx, ao_y, col_w, ao_h))
                    # ── Tall wall extension (tiling texture above) ──
                    if cy0 > 0 and _td_c and _td_c.tall_wall:
                        _tw_h = _ws_c[_WS_H]
                        _tw_key = _td_c.alt_texture
                        _tw_tex = (_get_by_key(_tw_key) if _tw_key
                                   else _atlas_get(tid))
                        _rep = max(1, int(_tw_h))
                        _cur = cy0
                        while _cur > 0:
                            _tw_top = max(0, _cur - _rep)
                            _tw_sh = _cur - _tw_top
                            if _tw_sh < 1:
                                break
                            _v1 = _TEX
                            _v0 = _TEX - int((_tw_sh / _rep) * _TEX)
                            if _v0 < 0:
                                _v0 = 0
                            if _v1 - _v0 < 1:
                                break
                            _tw_sub = _tw_tex.subsurface(
                                (tx_s, _v0, 1, _v1 - _v0))
                            _tw_s = _scale(_tw_sub, (col_w, _tw_sh))
                            if ws_side == 1 and fog < 250:
                                _tw_s.fill(
                                    (175*fog//255, 168*fog//255,
                                     155*fog//255),
                                    special_flags=_BLEND)
                            elif ws_side == 1:
                                _tw_s.fill((175, 168, 155),
                                           special_flags=_BLEND)
                            elif fog < 250:
                                _tw_s.fill((fog, fog, fog),
                                           special_flags=_BLEND)
                            _full_append((_tw_s, (ws_sx, _tw_top)))
                            _cur = _tw_top
            else:
                if has_vp:
                    plat_col[ws_sx] = (cy0, tid, hs, col_w)
                deferred_halves.append((
                    ws_dist, strip_surf,
                    ws_sx, cy0, cy1, col_w, draw_h,
                    bool(has_vp), tid, hs, _half, False,
                ))
    else:
        # ── Pure-Python fallback ─────────────────────────────
        for ws in slices:
            ws_sx = ws[_WS_SX]
            ws_dist = ws[_WS_DIST]
            ws_h = ws[_WS_H]
            ws_side = ws[_WS_SIDE]

            tid = ws[_WS_TID]
            tid_int = tile_str_to_int(tid)
            tx = int(ws[_WS_TEX_X] * _TEX) & _TEX_M1

            full_half_h = ws_h * 0.5
            full_top = _half - full_half_h
            full_bot = _half + full_half_h

            hs = ws[_WS_HS]
            if hs < 0.99:
                scaled_h = ws_h * hs
                y_top = full_bot - scaled_h
                y_bot = full_bot
            else:
                y_top = full_top
                y_bot = full_bot

            cy0 = max(0, int(y_top))
            cy1 = min(_sh, int(y_bot))
            draw_h = cy1 - cy0
            if draw_h < 1:
                continue

            actual_h = y_bot - y_top
            if actual_h > 0:
                v0 = (cy0 - y_top) / actual_h
                v1 = (cy1 - y_top) / actual_h
            else:
                v0, v1 = 0.0, 1.0

            tv0 = max(0, min(_TEX_M1, int(v0 * _TEX)))
            tv1 = max(tv0 + 1, min(_TEX, int(v1 * _TEX)))

            col_w = min(_step, sw - ws_sx)

            fog_idx = min(255, int(ws_dist * 8.0))
            fog = fog_lut[fog_idx]

            draw_h_q = max(8, (draw_h + 4) & ~7)
            tx_s = tx & ~3
            fog_q = fog >> 6
            cache_key = (tid_int | (tx_s << 10) | ((tv1 - tv0) << 16) |
                         (draw_h_q << 23) | (col_w << 33) |
                         (ws_side << 37) | (fog_q << 38))

            # Face-texture override check (rotation-aware)
            face_key = None
            if _has_dir(tid):
                face = _face_nm_idx(ws[_WS_FACE])
                _rot = 0
                if _rots:
                    _my = ws[_WS_MAP_Y]; _mx = ws[_WS_MAP_X]
                    if 0 <= _my < len(_rots) and 0 <= _mx < len(_rots[0]):
                        _rot = _rots[_my][_mx]
                td = _tile_def(tid)
                if td:
                    face_key = td.tex_for_face(face, _rot)
                    if face_key == td.wall_tex():
                        face_key = None
            if face_key:
                cache_key = hash((face_key, tx_s, tv0, tv1,
                                      draw_h_q, col_w, ws_side, fog_q))

            # Two-generation lookup — NO prev-hit promotion.
            cached = _cache_get(cache_key)
            if cached is not None:
                strip_surf = cached
            else:
                prev_hit = _prev_get(cache_key)
                if prev_hit is not None:
                    strip_surf = prev_hit
                else:
                    tex_surf = _get_by_key(face_key) if face_key else _atlas_get(tid)
                    strip = tex_surf.subsurface((tx_s, tv0, 1, tv1 - tv0))

                    _sz = (col_w, draw_h_q)
                    _bucket = _free_list.get(_sz)
                    if _bucket:
                        strip_surf = _bucket.pop()
                        _scale(strip, _sz, strip_surf)
                    else:
                        strip_surf = _scale(strip, _sz)

                    if ws_side == 1 and fog < 250:
                        strip_surf.fill(
                            (175 * fog // 255, 168 * fog // 255,
                             155 * fog // 255),
                            special_flags=_BLEND,
                        )
                    elif ws_side == 1:
                        strip_surf.fill((175, 168, 155), special_flags=_BLEND)
                    elif fog < 250:
                        strip_surf.fill((fog, fog, fog), special_flags=_BLEND)

                    strip_cache[cache_key] = strip_surf

            if hs > 0.99:
                # Transparent full-height walls → defer for alpha
                _td_py = _tile_def(tid)
                if _td_py and _td_py.transparent:
                    deferred_halves.append((
                        ws_dist, strip_surf,
                        ws_sx, cy0, cy1, col_w, draw_h,
                        False, tid, hs, _half, True,
                    ))
                else:
                    _full_append((strip_surf, (ws_sx, cy0)))

                    _sx_end = min(ws_sx + col_w, sw)
                    zbuf_full[ws_sx:_sx_end] = [ws_dist] * (_sx_end - ws_sx)

                    if ws_dist < _ao_max_dist and cy1 < _sh:
                        _ao = min(6, max(1, draw_h >> 3))
                        _ao_h = min(_ao, _sh - cy1)
                        if _ao_h > 0:
                            _ao_append((ws_sx, cy1, col_w, _ao_h))

                    # ── Tall wall extension (tiling texture above) ──
                    if cy0 > 0 and _td_py and _td_py.tall_wall:
                        _tw_h = ws_h  # full wall height in pixels
                        _tw_key = _td_py.alt_texture
                        _tw_tex = (_get_by_key(_tw_key) if _tw_key
                                   else _atlas_get(tid))
                        _rep = max(1, int(_tw_h))
                        _cur = cy0
                        while _cur > 0:
                            _tw_top = max(0, _cur - _rep)
                            _tw_sh = _cur - _tw_top
                            if _tw_sh < 1:
                                break
                            _v1 = _TEX
                            _v0 = _TEX - int((_tw_sh / _rep) * _TEX)
                            if _v0 < 0:
                                _v0 = 0
                            if _v1 - _v0 < 1:
                                break
                            _tw_sub = _tw_tex.subsurface(
                                (tx_s, _v0, 1, _v1 - _v0))
                            _tw_s = _scale(_tw_sub, (col_w, _tw_sh))
                            if ws_side == 1 and fog < 250:
                                _tw_s.fill(
                                    (175*fog//255, 168*fog//255,
                                     155*fog//255),
                                    special_flags=_BLEND)
                            elif ws_side == 1:
                                _tw_s.fill((175, 168, 155),
                                           special_flags=_BLEND)
                            elif fog < 250:
                                _tw_s.fill((fog, fog, fog),
                                           special_flags=_BLEND)
                            _full_append((_tw_s, (ws_sx, _tw_top)))
                            _cur = _tw_top
            else:
                has_vp = False
                if 0 < cy0 < _sh:
                    _delta_h = 0.5 - hs
                    if _delta_h > 0.01 and cy0 > _half:
                        has_vp = True
                        plat_col[ws_sx] = (cy0, tid, hs, col_w)
                deferred_halves.append((
                    ws_dist, strip_surf,
                    ws_sx, cy0, cy1, col_w, draw_h,
                    has_vp, tid, hs, _half, False,
                ))

    # ── Batch blit all full walls in one C-level call ────────
    if full_blits:
        surface.blits(full_blits, doreturn=False)

    # ── Batch AO shadows ─────────────────────────────────────
    _AO_COL = (120, 120, 115)
    for _r in ao_rects:
        _fill(_AO_COL, _r, special_flags=_BLEND)

    return slices, plat_col, zbuf_full, deferred_halves