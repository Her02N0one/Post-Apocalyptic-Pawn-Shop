"""systems/raycaster.py — Wolfenstein-style DDA raycaster.

Pure functions that read the tile grid and produce rendering data.
No pygame dependency — only math.

Usage::

    slices = cast_walls(px, py, angle, FOV, sw, sh, tiles)
    sprites = project_entities(px, py, angle, FOV, sw, sh, entities)

The renderer (FirstPerson) converts these to draw calls.
"""

from __future__ import annotations

import math
from collections import namedtuple

from core.tiles import WALL_IDS, HALF_WALL_IDS, tile_def


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
_MAX_STEPS = 64

# Height-scale cache — avoids repeated tile_def() lookups per frame
_HS_CACHE: dict[int, float] = {}


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

    # Local aliases for speed
    _wall_check = wall_tiles.__contains__
    _half_check = _HALF_TILES.__contains__
    _max_steps = _MAX_STEPS

    slices: list[WallSlice] = []
    _append = slices.append
    _WS = WallSlice

    for col_idx in range(n_rays):
        x = col_idx * step
        cam_x = x * inv_sw - 1.0
        ray_a = angle + cam_x * half_fov
        rd_x = _cos(ray_a)
        rd_y = _sin(ray_a)

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
        half_hit_data = None
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
                # Out of bounds — only treat as a wall hit if there's
                # no half-wall recorded.  Otherwise the half-wall
                # stands alone and the player can see over/through it.
                if half_hit_data is None:
                    hit = True
                break

            tid = tiles[my][mx]
            if _wall_check(tid):
                if _half_check(tid):
                    if half_hit_data is None:
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
                        half_hit_data = (
                            x, _perp, _line_h, tid, side,
                            _wx - _floor(_wx), _get_hs(tid),
                            rd_x, rd_y, _wx,
                        )
                    # Always skip half-walls (record only the nearest one)
                    # so the ray keeps going until a full wall or map edge.
                    continue
                hit = True
                break

        if not hit and half_hit_data is None:
            continue

        if not hit:
            _append(_WS(*half_hit_data))
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

        # Emit background (full) wall FIRST so that the closer
        # half-wall can paint over its lower portion (painter's order).
        _append(_WS(x, perp, line_h, tid_hit, side, wx_frac,
                     _get_hs(tid_hit), rd_x, rd_y, wx))

        if half_hit_data is not None:
            _append(_WS(*half_hit_data))

    return slices


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
    entities : list of (eid, ex, ey, char, color, height_scale, width_scale)

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

    for eid, ex, ey, char, color, h_scale, w_scale in entities:
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
        sprite_sy = floor_y - sprite_h

        _append(_BB(eid, sprite_sx, sprite_sy, sprite_h, ty,
                     char, color, sprite_w))

    result.sort(key=lambda s: s.distance, reverse=True)
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