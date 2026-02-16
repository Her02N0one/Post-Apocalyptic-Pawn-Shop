"""systems/raycaster.py — Wolfenstein-style DDA raycaster.

Pure functions that read the tile grid and produce rendering data.
No pygame dependency — only math + dataclasses.

Usage::

    slices = cast_walls(px, py, angle, FOV, sw, sh, tiles)
    sprites = project_entities(px, py, angle, FOV, sw, sh, entities)

The renderer (FirstPerson) converts these to draw calls.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from core.constants import TILE_WALL


# ═════════════════════════════════════════════════════════════════════
#  Data types
# ═════════════════════════════════════════════════════════════════════

@dataclass
class WallSlice:
    """One vertical column of a rendered wall."""
    screen_x: int
    distance: float   # perpendicular distance (fisheye-corrected)
    height: int       # pixel height on screen
    tile_id: int      # which tile was hit (for colour lookup)
    side: int         # 0 = hit a vertical (E/W) face, 1 = horizontal (N/S)
    tex_x: float      # 0..1 position along the wall face
    # For textured floor/ceiling casting
    ray_dir_x: float = 0.0
    ray_dir_y: float = 0.0
    wall_x: float = 0.0  # exact fractional hit position (before floor())


@dataclass
class BillboardSprite:
    """An entity projected into screen space."""
    eid: int
    screen_x: float
    screen_y: float
    height: int       # pixel height
    distance: float
    char: str
    color: tuple[int, int, int]


# ═════════════════════════════════════════════════════════════════════
#  Wall raycasting (DDA)
# ═════════════════════════════════════════════════════════════════════

_WALL_TILES: frozenset[int] = frozenset({TILE_WALL})
_MAX_STEPS = 64


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
    slices: list[WallSlice] = []

    for x in range(0, screen_w, step):
        # Camera-space x in [-1, 1]
        cam_x = 2.0 * x / screen_w - 1.0
        ray_a = angle + cam_x * half_fov
        rd_x = math.cos(ray_a)
        rd_y = math.sin(ray_a)

        # Map cell
        mx = int(px)
        my = int(py)

        # Delta distances (distance ray must travel for one grid line)
        dd_x = abs(1.0 / rd_x) if abs(rd_x) > 1e-10 else 1e10
        dd_y = abs(1.0 / rd_y) if abs(rd_y) > 1e-10 else 1e10

        # Step direction and initial side distances
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

        # DDA stepping
        hit = False
        side = 0
        for _ in range(_MAX_STEPS):
            if sd_x < sd_y:
                sd_x += dd_x
                mx += sx
                side = 0
            else:
                sd_y += dd_y
                my += sy
                side = 1

            # Out-of-bounds → treat as wall
            if mx < 0 or mx >= map_w or my < 0 or my >= map_h:
                hit = True
                break

            if tiles[my][mx] in wall_tiles:
                hit = True
                break

        if not hit:
            continue

        # Perpendicular distance (corrects fisheye)
        if side == 0:
            perp = (mx - px + (1 - sx) * 0.5) / rd_x if abs(rd_x) > 1e-10 else 1e10
        else:
            perp = (my - py + (1 - sy) * 0.5) / rd_y if abs(rd_y) > 1e-10 else 1e10
        perp = max(perp, 0.01)

        line_h = int(screen_h / perp)

        # Where on the wall face the ray hit (0..1 texture coord)
        if side == 0:
            wx = py + perp * rd_y
        else:
            wx = px + perp * rd_x
        wx -= math.floor(wx)

        tid = tiles[my][mx] if (0 <= my < map_h and 0 <= mx < map_w) else 0

        # Exact wall hit position (for floor casting)
        if side == 0:
            wall_exact = py + perp * rd_y
        else:
            wall_exact = px + perp * rd_x

        slices.append(WallSlice(
            screen_x=x,
            distance=perp,
            height=line_h,
            tile_id=tid,
            side=side,
            tex_x=wx,
            ray_dir_x=rd_x,
            ray_dir_y=rd_y,
            wall_x=wall_exact,
        ))

    return slices


# ═════════════════════════════════════════════════════════════════════
#  Entity billboard projection
# ═════════════════════════════════════════════════════════════════════

def project_entities(
    px: float, py: float,
    angle: float,
    fov: float,
    screen_w: int, screen_h: int,
    entities: list[tuple[int, float, float, str, tuple[int, int, int]]],
) -> list[BillboardSprite]:
    """Project world entities into screen-space billboards.

    Parameters
    ----------
    entities : list of (eid, ex, ey, char, color)
        The entity data to project (pre-filtered to current zone).

    Returns a list sorted by distance (far → near) for painter's-algo
    draw order.
    """
    dir_x = math.cos(angle)
    dir_y = math.sin(angle)
    # Camera plane (perpendicular, scaled by half-FOV tangent)
    plane_scale = math.tan(fov * 0.5)
    plane_x = -dir_y * plane_scale
    plane_y = dir_x * plane_scale

    inv_det = 1.0 / (plane_x * dir_y - dir_x * plane_y + 1e-10)

    result: list[BillboardSprite] = []

    for eid, ex, ey, char, color in entities:
        dx = ex - px
        dy = ey - py

        # Transform to camera space
        tx = inv_det * (dir_y * dx - dir_x * dy)
        ty = inv_det * (-plane_y * dx + plane_x * dy)  # depth

        if ty <= 0.1:
            continue  # behind camera

        # Screen projection
        sprite_sx = (screen_w * 0.5) * (1.0 + tx / ty)
        sprite_h = int(screen_h / ty)
        sprite_sy = (screen_h - sprite_h) * 0.5

        result.append(BillboardSprite(
            eid=eid,
            screen_x=sprite_sx,
            screen_y=sprite_sy,
            height=sprite_h,
            distance=ty,
            char=char,
            color=color,
        ))

    # Sort far-to-near for painter's algorithm
    result.sort(key=lambda s: s.distance, reverse=True)
    return result


# ═════════════════════════════════════════════════════════════════════
#  Z-buffer helper
# ═════════════════════════════════════════════════════════════════════

def build_zbuffer(slices: list[WallSlice], screen_w: int,
                  step: int = 1) -> list[float]:
    """Build a per-column depth buffer from wall slices.

    Used to occlude sprite columns that are behind walls.
    """
    zbuf = [1e10] * screen_w
    for ws in slices:
        for c in range(ws.screen_x, min(ws.screen_x + step, screen_w)):
            zbuf[c] = ws.distance
    return zbuf
