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

from systems.raycaster import cast_walls
from systems.textures import TEX_SIZE

if TYPE_CHECKING:
    from scenes.world.fp_renderer import Renderer

# ── Try to import C-accelerated geometry ─────────────────────────
try:
    from systems._fast_walls import compute_wall_geometry as _c_geom
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

# AO distance cutoff — skip AO shadows for walls farther than this
_AO_MAX_DIST = 6.0


def draw_walls(
    self: "Renderer",
    surface: pygame.Surface,
    sw: int, sh: int, half: int,
    px: float, py: float,
    angle: float, fov: float,
    tiles: list[list[int]],
    fog_lut: list[int], dn: float,
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
    if _USE_C_WALLS:
        # Bulk-compute geometry in C — eliminates ~120 iterations
        # of Python-level float math + bitwise cache-key packing.
        _fog_bytes = bytes(fog_lut)
        geom = _c_geom(slices, sh, half, _TEX, _fog_bytes, _step, sw)

        for g in geom:
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
            tid       = g[12]
            ws_side   = g[13]
            hs        = g[14]
            is_full   = g[15]
            ao_y      = g[16]
            ao_h      = g[17]
            has_vp    = g[18]

            # Two-generation lookup: current first, then previous.
            cached = _cache_get(cache_key)
            if cached is not None:
                strip_surf = cached
            else:
                prev_hit = _prev_get(cache_key)
                if prev_hit is not None:
                    strip_surf = prev_hit
                else:
                    tex_surf = _atlas_get(tid)
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
                _full_append((strip_surf, (ws_sx, cy0)))
                _sx_end = ws_sx + col_w
                if _sx_end > sw:
                    _sx_end = sw
                zbuf_full[ws_sx:_sx_end] = [ws_dist] * (_sx_end - ws_sx)
                if ao_h > 0:
                    _ao_append((ws_sx, ao_y, col_w, ao_h))
            else:
                if has_vp:
                    plat_col[ws_sx] = (cy0, tid, hs, col_w)
                deferred_halves.append((
                    ws_dist, strip_surf,
                    ws_sx, cy0, cy1, col_w, draw_h,
                    bool(has_vp), tid, hs, _half,
                ))
    else:
        # ── Pure-Python fallback ─────────────────────────────
        for ws in slices:
            ws_sx = ws[_WS_SX]
            ws_dist = ws[_WS_DIST]
            ws_h = ws[_WS_H]
            ws_side = ws[_WS_SIDE]

            tid = ws[_WS_TID]
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
            cache_key = (tid | (tx_s << 10) | ((tv1 - tv0) << 16) |
                         (draw_h_q << 23) | (col_w << 33) |
                         (ws_side << 37) | (fog_q << 38))

            # Two-generation lookup — NO prev-hit promotion.
            cached = _cache_get(cache_key)
            if cached is not None:
                strip_surf = cached
            else:
                prev_hit = _prev_get(cache_key)
                if prev_hit is not None:
                    strip_surf = prev_hit
                else:
                    tex_surf = _atlas_get(tid)
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
                _full_append((strip_surf, (ws_sx, cy0)))

                _sx_end = min(ws_sx + col_w, sw)
                zbuf_full[ws_sx:_sx_end] = [ws_dist] * (_sx_end - ws_sx)

                if ws_dist < _ao_max_dist and cy1 < _sh:
                    _ao = min(6, max(1, draw_h >> 3))
                    _ao_h = min(_ao, _sh - cy1)
                    if _ao_h > 0:
                        _ao_append((ws_sx, cy1, col_w, _ao_h))
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
                    has_vp, tid, hs, _half,
                ))

    # ── Batch blit all full walls in one C-level call ────────
    if full_blits:
        surface.blits(full_blits, doreturn=False)

    # ── Batch AO shadows ─────────────────────────────────────
    _AO_COL = (120, 120, 115)
    for _r in ao_rects:
        _fill(_AO_COL, _r, special_flags=_BLEND)

    return slices, plat_col, zbuf_full, deferred_halves