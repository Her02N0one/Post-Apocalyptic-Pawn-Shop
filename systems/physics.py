"""systems/physics.py — Movement & tile collision.

Moves all entities that have Position + Velocity.  Uses axis-separated
wall collision to allow wall-sliding.

    from systems.physics import movement_system
    movement_system(world, dt, tiles)
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from components import Position, Velocity, Collider, Player
from core.constants import TILE_WALL

if TYPE_CHECKING:
    from core.ecs import World


# ── Tile collision ───────────────────────────────────────────────────

def _hits_wall(x: float, y: float,
               hw: float, hh: float,
               map_h: int, map_w: int,
               tiles: list[list[int]]) -> bool:
    """Return True if an AABB centred at (x, y) overlaps a wall or OOB."""
    left  = x - hw * 0.5
    right = x + hw * 0.5 - 0.001
    top   = y - hh * 0.5
    bot   = y + hh * 0.5 - 0.001
    for r in range(int(math.floor(top)), int(math.floor(bot)) + 1):
        for c in range(int(math.floor(left)), int(math.floor(right)) + 1):
            if r < 0 or r >= map_h or c < 0 or c >= map_w:
                return True
            if tiles[r][c] == TILE_WALL:
                return True
    return False


# ── Movement system ──────────────────────────────────────────────────

def movement_system(world: "World", dt: float,
                    tiles: list[list[int]]) -> None:
    """Apply velocities to positions with axis-separated wall collision."""
    h = len(tiles)
    w = len(tiles[0]) if h else 0

    for eid, pos, vel in world.query(Position, Velocity):
        if abs(vel.x) < 0.001 and abs(vel.y) < 0.001:
            continue

        # Use collider dimensions if available, else default 0.8x0.8
        col = world.get(eid, Collider)
        hw = col.w if col else 0.8
        hh = col.h if col else 0.8

        nx = pos.x + vel.x * dt
        ny = pos.y + vel.y * dt

        # X axis
        if _hits_wall(nx, pos.y, hw, hh, h, w, tiles):
            nx = pos.x
            vel.x = 0.0

        # Y axis
        if _hits_wall(nx, ny, hw, hh, h, w, tiles):
            ny = pos.y
            vel.y = 0.0

        pos.x = nx
        pos.y = ny
