"""core/collision.py — Low-level AABB / tile-grid collision primitives.

These live in ``core/`` (not ``logic/``) because both the engine layer
(zone safe-spawn resolution) and gameplay systems (movement, projectiles)
need them.  Keeping them here prevents a circular dependency.
"""

from __future__ import annotations
import math
from core.constants import TILE_WALL

# Entity occupies an axis-aligned box of this size (tile units).
# Matches the canonical 0.8×0.8 "player size" used everywhere.
HITBOX_W = 0.8
HITBOX_H = 0.8


def aabb_hits_wall(x: float, y: float, bw: float, bh: float,
                   map_h: int, map_w: int,
                   tiles: list[list[int]]) -> bool:
    """Return True if the box (x, y)→(x+bw, y+bh) overlaps a wall or OOB.

    Parameters
    ----------
    x, y : float
        Top-left corner of the AABB in tile coordinates.
    bw, bh : float
        Width / height of the AABB (tile units).
    map_h, map_w : int
        Tile-map dimensions (rows × cols).
    tiles : list[list[int]]
        2-D tile-ID grid.
    """
    min_c = int(math.floor(x))
    max_c = int(math.floor(x + bw - 0.001))
    min_r = int(math.floor(y))
    max_r = int(math.floor(y + bh - 0.001))
    for r in range(min_r, max_r + 1):
        for c in range(min_c, max_c + 1):
            if r < 0 or r >= map_h or c < 0 or c >= map_w:
                return True
            if tiles[r][c] == TILE_WALL:
                return True
    return False
