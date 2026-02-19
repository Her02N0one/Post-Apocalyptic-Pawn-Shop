"""systems/raycaster.py — Wolfenstein-style DDA raycaster.

Pure functions that read the tile grid and produce rendering data.
No pygame dependency — only math.

Usage::

    slices = cast_walls(px, py, angle, FOV, sw, sh, tiles)
    sprites = project_entities(px, py, angle, FOV, sw, sh, entities)

The renderer (FirstPerson) converts these to draw calls.

If the compiled C extension ``_fast_cast`` is available (built via
``python build_ext.py build_ext --inplace``), the DDA loop runs at
native speed (~50× faster).  Otherwise falls back to pure Python.
"""

from __future__ import annotations

import array as _array
import math
import operator
from collections import namedtuple

from core.tiles import WALL_IDS, HALF_WALL_IDS, tile_def

# ── Try to load C-accelerated raycaster ──────────────────────────
try:
    from systems._fast_cast import cast_walls as _c_cast_walls
    _USE_C_CAST = True
except ImportError:
    _c_cast_walls = None  # type: ignore[assignment]
    _USE_C_CAST = False


# ═════════════════════════════════════════════════════════════════════
#  Data types  —  namedtuple for fast C-level construction
# ═════════════════════════════════════════════════════════════════════

WallSlice = namedtuple('WallSlice', [
    'screen_x', 'distance', 'height', 'tile_id', 'side',
    'tex_x', 'height_scale', 'ray_dir_x', 'ray_dir_y', 'wall_x',
], defaults=[0, 0.0, 0, 0, 0, 0.0, 1.0, 0.0, 0.0, 0.0])
WallSlice.__doc__ = """One vertical column of a rendered wall."""

BillboardSprite = namedtuple('BillboardSprite', [
    'eid', 'screen_x', 'screen_y', 'height', 'distance',
    'char', 'color', 'width',
], defaults=[0, 0.0, 0.0, 0, 0.0, '', (0, 0, 0), 0])
BillboardSprite.__doc__ = """An entity projected into screen space."""


# ═════════════════════════════════════════════════════════════════════
#  Wall raycasting (DDA)
# ═════════════════════════════════════════════════════════════════════

_WALL_TILES: frozenset[int] = WALL_IDS
_HALF_TILES: frozenset[int] = HALF_WALL_IDS
_MAX_STEPS = 32

# Height-scale cache — avoids repeated tile_def() lookups per frame
_HS_CACHE: dict[int, float] = {}

# Pre-computed trig table: (angle_q, fov_q, n_rays) → (cos[], sin[])
_TRIG_CACHE: dict[tuple, tuple[list[float], list[float]]] = {}
_TRIG_Q = 2048  # quantisation granularity for angle caching


def _get_hs(tid: int) -> float:
    """Get height_scale for a tile id, cached."""
    hs = _HS_CACHE.get(tid)
    if hs is None:
        td = tile_def(tid)
        hs = td.height_scale if td else 1.0
        _HS_CACHE[tid] = hs
    return hs


def cast_walls(
    px: float, py: float,
    angle: float,
    fov: float,
    screen_w: int, screen_h: int,
    tiles: list[list[int]],
    *,
    wall_tiles: frozenset[int] = _WALL_TILES,
    step: int = 1,
) -> list[WallSlice]:
    """Cast one ray per *step* screen columns and return wall slices.

    Parameters
    ----------
    px, py : float
        Player position in tile coords.
    angle : float
        Player look direction in radians (0 = east, increases CCW).
    fov : float
        Horizontal field of view in radians.
    screen_w, screen_h : int
        Viewport pixel dimensions.
    tiles : list[list[int]]
        2-D tile grid (``tiles[row][col]``).
    wall_tiles : frozenset[int]
        Tile IDs treated as solid walls.
    step : int
        Cast every *step*-th column (1 = full res, 2 = half, …).
    """
    # ── C-accelerated fast path ──────────────────────────────
    if _USE_C_CAST and wall_tiles is _WALL_TILES:
        return _cast_walls_c(px, py, angle, fov,
                             screen_w, screen_h, tiles, step)

    map_h = len(tiles)
    map_w = len(tiles[0]) if map_h else 0
    half_fov = fov * 0.5
    n_rays = (screen_w + step - 1) // step

    # Pre-compute per-ray basics
    inv_sw = 2.0 / screen_w
    _cos = math.cos
    _sin = math.sin
    _abs = abs
    _floor = math.floor
    _int = int

    # ── Pre-computed trig table (cached across frames) ───────
    # Quantise angle so small floating-point jitter doesn't
    # invalidate the cache every single frame.
    _aq = _int(angle * _TRIG_Q) & (_TRIG_Q * 8 - 1)
    _fq = _int(fov * _TRIG_Q)
    _trig_key = (_aq, _fq, n_rays)
    _trig = _TRIG_CACHE.get(_trig_key)
    if _trig is None:
        _rd_x_arr: list[float] = []
        _rd_y_arr: list[float] = []
        for _ci in range(n_rays):
            _ra = angle + (_ci * step * inv_sw - 1.0) * half_fov
            _rd_x_arr.append(_cos(_ra))
            _rd_y_arr.append(_sin(_ra))
        _trig = (_rd_x_arr, _rd_y_arr)
        if len(_TRIG_CACHE) > 4:
            _TRIG_CACHE.clear()
        _TRIG_CACHE[_trig_key] = _trig
    _rd_x_lut, _rd_y_lut = _trig

    # Local aliases for speed
    _wall_check = wall_tiles.__contains__
    _half_check = _HALF_TILES.__contains__
    _max_steps = _MAX_STEPS

    slices: list[WallSlice] = []
    _append = slices.append
    _WS = WallSlice
    half_hits: list[WallSlice] = []
    _hh_append = half_hits.append
    _hh_clear = half_hits.clear

    for col_idx in range(n_rays):
        x = col_idx * step
        rd_x = _rd_x_lut[col_idx]
        rd_y = _rd_y_lut[col_idx]

        mx = _int(px)
        my = _int(py)

        ard_x = _abs(rd_x)
        ard_y = _abs(rd_y)
        dd_x = (1.0 / ard_x) if ard_x > 1e-10 else 1e10
        dd_y = (1.0 / ard_y) if ard_y > 1e-10 else 1e10

        if rd_x < 0:
            sx = -1
            sd_x = (px - mx) * dd_x
        else:
            sx = 1
            sd_x = (mx + 1.0 - px) * dd_x

        if rd_y < 0:
            sy = -1
            sd_y = (py - my) * dd_y
        else:
            sy = 1
            sd_y = (my + 1.0 - py) * dd_y

        half_sx = (1 - sx) * 0.5
        half_sy = (1 - sy) * 0.5

        hit = False
        side = 0
        _hh_clear()
        for _ in range(_max_steps):
            if sd_x < sd_y:
                sd_x += dd_x
                mx += sx
                side = 0
            else:
                sd_y += dd_y
                my += sy
                side = 1

            if mx < 0 or mx >= map_w or my < 0 or my >= map_h:
                # Out of bounds — only treat as a wall hit if there are
                # no half-walls recorded.  Otherwise the half-walls
                # stand alone and the player can see over/through them.
                if not half_hits:
                    hit = True
                break

            tid = tiles[my][mx]
            if _wall_check(tid):
                if _half_check(tid):
                    if side == 0:
                        _perp = (mx - px + half_sx) / rd_x if ard_x > 1e-10 else 1e10
                    else:
                        _perp = (my - py + half_sy) / rd_y if ard_y > 1e-10 else 1e10
                    if _perp < 0.01:
                        _perp = 0.01
                    _line_h = _int(screen_h / _perp)
                    if side == 0:
                        _wx = py + _perp * rd_y
                    else:
                        _wx = px + _perp * rd_x
                    _hh_append(_WS(
                        x, _perp, _line_h, tid, side,
                        _wx - _floor(_wx), _get_hs(tid),
                        rd_x, rd_y, _wx,
                    ))
                    # Skip half-walls so the ray keeps going until a
                    # full wall or map edge.
                    continue
                hit = True
                break

        if not hit and not half_hits:
            continue

        if not hit:
            # Only half-walls, no full wall behind.
            # Emit farthest-to-nearest (painter's order); the list
            # is already nearest-first from DDA traversal.
            for _hd in reversed(half_hits):
                _append(_hd)
            continue

        if side == 0:
            perp = (mx - px + half_sx) / rd_x if ard_x > 1e-10 else 1e10
        else:
            perp = (my - py + half_sy) / rd_y if ard_y > 1e-10 else 1e10
        if perp < 0.01:
            perp = 0.01

        line_h = _int(screen_h / perp)

        if side == 0:
            wx = py + perp * rd_y
        else:
            wx = px + perp * rd_x
        wx_frac = wx - _floor(wx)

        tid_hit = tiles[my][mx] if (0 <= my < map_h and 0 <= mx < map_w) else 0

        # Emit background (full) wall FIRST, then half-walls
        # farthest-to-nearest (painter's order).
        _append(_WS(x, perp, line_h, tid_hit, side, wx_frac,
                     _get_hs(tid_hit), rd_x, rd_y, wx))

        for _hd in reversed(half_hits):
            _append(_hd)

    return slices


# ═════════════════════════════════════════════════════════════════════
#  C-extension wrapper  (only used when _USE_C_CAST is True)
# ═════════════════════════════════════════════════════════════════════

_C_LUT_LEN = 512
_c_wall_lut: bytearray | None = None
_c_half_lut: bytearray | None = None
_c_hs_lut: _array.array | None = None
_c_tiles_id: int | None = None
_c_tiles_flat: _array.array | None = None


def _ensure_c_luts() -> tuple[bytearray, bytearray, _array.array]:
    """Build/return wall, half-wall, and height-scale lookup tables."""
    global _c_wall_lut, _c_half_lut, _c_hs_lut
    if _c_wall_lut is not None:
        return _c_wall_lut, _c_half_lut, _c_hs_lut  # type: ignore[return-value]
    n = _C_LUT_LEN
    wl = bytearray(n)
    for wid in _WALL_TILES:
        if wid < n:
            wl[wid] = 1
    hl = bytearray(n)
    for hid in _HALF_TILES:
        if hid < n:
            hl[hid] = 1
    hs = _array.array('d', [1.0] * n)
    for tid in range(n):
        td = tile_def(tid)
        if td:
            hs[tid] = td.height_scale
    _c_wall_lut = wl
    _c_half_lut = hl
    _c_hs_lut = hs
    return wl, hl, hs


def _flatten_tiles(tiles: list[list[int]]) -> _array.array:
    """Return *tiles* as a flat int32 array, cached by identity."""
    global _c_tiles_id, _c_tiles_flat
    tid = id(tiles)
    if tid == _c_tiles_id and _c_tiles_flat is not None:
        return _c_tiles_flat
    flat = _array.array('i')
    for row in tiles:
        flat.extend(row)
    _c_tiles_id = tid
    _c_tiles_flat = flat
    return flat


def _cast_walls_c(
    px: float, py: float,
    angle: float, fov: float,
    sw: int, sh: int,
    tiles: list[list[int]],
    step: int,
) -> list[WallSlice]:
    """Call the C extension and wrap results as WallSlice namedtuples."""
    map_h = len(tiles)
    map_w = len(tiles[0]) if map_h else 0
    wl, hl, hs = _ensure_c_luts()
    flat = _flatten_tiles(tiles)
    raw = _c_cast_walls(
        px, py, angle, fov, sw, sh, map_h, map_w,
        flat, wl, hl, hs, step,
    )
    _WS = WallSlice
    return [_WS._make(t) for t in raw]


# ═════════════════════════════════════════════════════════════════════
#  Entity billboard projection
# ═════════════════════════════════════════════════════════════════════

def project_entities(
    px: float, py: float,
    angle: float,
    fov: float,
    screen_w: int, screen_h: int,
    entities: list[tuple[int, float, float, str, tuple[int, int, int], float, float]],
) -> list[BillboardSprite]:
    """Project world entities into screen-space billboards.

    Parameters
    ----------
    entities : list of (eid, ex, ey, char, color, height_scale, width_scale[, elevation])
        An optional 8th element *elevation* (0.0–1.0) lifts the sprite
        above the floor by that fraction of a full wall height (e.g. a
        platform with height_scale 0.35 passes elevation=0.35).

    Returns a list sorted by distance (far → near) for painter's-algo
    draw order.
    """
    dir_x = math.cos(angle)
    dir_y = math.sin(angle)
    plane_scale = math.tan(fov * 0.5)
    plane_x = -dir_y * plane_scale
    plane_y = dir_x * plane_scale

    inv_det = 1.0 / (plane_x * dir_y - dir_x * plane_y + 1e-10)

    half_sw = screen_w * 0.5
    _int = int
    _max = max
    _BB = BillboardSprite

    result: list[BillboardSprite] = []
    _append = result.append

    for ent in entities:
        eid, ex, ey, char, color, h_scale, w_scale = ent[:7]
        elev = ent[7] if len(ent) > 7 else 0.0

        dx = ex - px
        dy = ey - py

        tx = inv_det * (dir_y * dx - dir_x * dy)
        ty = inv_det * (-plane_y * dx + plane_x * dy)

        if ty <= 0.1:
            continue

        sprite_sx = half_sw * (1.0 + tx / ty)
        wall_h = screen_h / ty
        sprite_h = _max(1, _int(wall_h * h_scale))
        sprite_w = _max(1, _int(wall_h * w_scale))

        floor_y = (screen_h + wall_h) * 0.5
        # Lift sprite by elevation (fraction of wall height)
        lift = wall_h * elev
        sprite_sy = floor_y - sprite_h - lift

        _append(_BB(eid, sprite_sx, sprite_sy, sprite_h, ty,
                     char, color, sprite_w))

    result.sort(key=operator.attrgetter('distance'), reverse=True)
    return result


# ═════════════════════════════════════════════════════════════════════
#  Z-buffer helper
# ═════════════════════════════════════════════════════════════════════

def build_zbuffer(slices: list[WallSlice], screen_w: int,
                  step: int = 1) -> list[float]:
    """Build a per-column depth buffer from wall slices."""
    zbuf = [1e10] * screen_w
    for ws in slices:
        d = ws.distance
        sx = ws.screen_x
        end = min(sx + step, screen_w)
        # For the common case step <= 4, unrolled is faster than range()
        if step <= 2:
            if d < zbuf[sx]:
                zbuf[sx] = d
            if step == 2 and end > sx + 1:
                c1 = sx + 1
                if d < zbuf[c1]:
                    zbuf[c1] = d
        else:
            for c in range(sx, end):
                if d < zbuf[c]:
                    zbuf[c] = d
    return zbuf