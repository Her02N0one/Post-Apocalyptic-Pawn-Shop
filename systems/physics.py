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
from core.tiles import SOLID_IDS

if TYPE_CHECKING:
    from core.ecs import World


# ── Tile collision ───────────────────────────────────────────────────

def _hits_wall(x: float, y: float,
               hw: float, hh: float,
               map_h: int, map_w: int,
               tiles: list[list[str]],
               solid_ids: frozenset[str] = SOLID_IDS) -> bool:
    """Return True if an AABB centred at (x, y) overlaps a wall or OOB."""
    left  = x - hw * 0.5
    right = x + hw * 0.5 - 0.001
    top   = y - hh * 0.5
    bot   = y + hh * 0.5 - 0.001
    for r in range(int(math.floor(top)), int(math.floor(bot)) + 1):
        for c in range(int(math.floor(left)), int(math.floor(right)) + 1):
            if r < 0 or r >= map_h or c < 0 or c >= map_w:
                return True
            if tiles[r][c] in solid_ids:
                return True
    return False


def _find_nearby_portal(x: float, y: float,
                        portal_tiles: set[tuple[int, int]]) -> tuple[float, float] | None:
    """If (x, y) is within ~1.5 tiles of a portal, return its centre.

    Uses the data-driven set of portal coordinates instead of scanning
    the tile grid for a specific tile ID.
    """
    r = int(y)
    c = int(x)
    best_dist = 2.5
    best: tuple[float, float] | None = None
    for dr in range(-2, 3):
        for dc in range(-2, 3):
            nr, nc = r + dr, c + dc
            if (nr, nc) in portal_tiles:
                cx, cy = nc + 0.5, nr + 0.5
                d = math.sqrt((x - cx) ** 2 + (y - cy) ** 2)
                if d < best_dist:
                    best_dist = d
                    best = (cx, cy)
    return best


def _doorway_nudge(pos_x: float, pos_y: float,
                   vel_x: float, vel_y: float,
                   hw: float, hh: float,
                   map_h: int, map_w: int,
                   tiles: list[list[str]],
                   portal_tiles: set[tuple[int, int]],
                   dt: float) -> tuple[float, float]:
    """Apply a gentle centering nudge when approaching a doorway.

    Returns (adjusted_vx, adjusted_vy) with a small perpendicular
    correction toward the portal centre so the player glides through.
    """
    tp = _find_nearby_portal(pos_x, pos_y, portal_tiles)
    if tp is None:
        return vel_x, vel_y

    tx, ty = tp
    # Only nudge if the player is actually moving
    speed = math.sqrt(vel_x * vel_x + vel_y * vel_y)
    if speed < 0.5:
        return vel_x, vel_y

    # Determine which axis the doorway gap runs along by checking
    # whether the portal has walls to its N/S vs E/W.
    tr, tc = int(ty), int(tx)
    wall_ns = 0  # walls to north/south
    wall_ew = 0  # walls to east/west
    for dr, dc in [(-1, 0), (1, 0)]:
        nr, nc = tr + dr, tc + dc
        if 0 <= nr < map_h and 0 <= nc < map_w:
            if tiles[nr][nc] in SOLID_IDS:
                wall_ns += 1
    for dr, dc in [(0, -1), (0, 1)]:
        nr, nc = tr + dr, tc + dc
        if 0 <= nr < map_h and 0 <= nc < map_w:
            if tiles[nr][nc] in SOLID_IDS:
                wall_ew += 1

    nudge_strength = 6.0  # tiles/s² — gentle but effective

    if wall_ew >= 1:
        # Walls to left/right — doorway runs N/S, nudge X toward centre
        diff = tx - pos_x
        if abs(diff) > 0.02:
            vel_x += diff * nudge_strength * dt
    if wall_ns >= 1:
        # Walls above/below — doorway runs E/W, nudge Y toward centre
        diff = ty - pos_y
        if abs(diff) > 0.02:
            vel_y += diff * nudge_strength * dt

    return vel_x, vel_y


# ── Movement system ──────────────────────────────────────────────────

def movement_system(world: "World", dt: float,
                    tiles: list[list[str]],
                    portal_tiles: set[tuple[int, int]] | None = None) -> None:
    """Apply velocities to positions with axis-separated wall collision.

    Parameters
    ----------
    portal_tiles
        Set of (row, col) coordinates that host a portal, used for
        doorway magnetism.  Pass ``session._portal_map.keys()`` or
        ``session.portal_positions``.  ``None`` disables nudge.
    """
    h = len(tiles)
    w = len(tiles[0]) if h else 0
    _ptiles: set[tuple[int, int]] = portal_tiles or set()

    for eid, pos, vel in world.query(Position, Velocity):
        if abs(vel.x) < 0.001 and abs(vel.y) < 0.001:
            continue

        # Use collider dimensions if available, else default 0.6x0.6
        col = world.get(eid, Collider)
        hw = col.w if col else 0.6
        hh = col.h if col else 0.6

        # Doorway magnetism — gently steer toward portal centres
        if world.has(eid, Player) and _ptiles:
            vel.x, vel.y = _doorway_nudge(
                pos.x, pos.y, vel.x, vel.y,
                hw, hh, h, w, tiles, _ptiles, dt,
            )

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
