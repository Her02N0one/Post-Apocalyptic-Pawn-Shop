"""systems/physics.py — Movement & tile collision.

Moves all entities that have Position + Velocity.  Uses axis-separated
wall collision to allow wall-sliding.  Optionally supports height-aware
collision for the player (layer-1 + layer-2 floors).

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


# ── Height collision constants ───────────────────────────────────────
LAYER_NONE     = -1000.0
MAX_STEP_UP    = 0.5
MAX_STEP_DOWN  = 1.0
HEAD_CLEARANCE = 0.4
STEP_RADIUS    = 0.2


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


# ── Height-aware helpers ─────────────────────────────────────────────

def floor_height_at(
    x: float, y: float,
    map_h: int, map_w: int,
    floor_heights: list[list[float]],
    floor2_heights: list[list[float]] | None,
    current_fh: float,
) -> float:
    """Return the best floor height at (x, y) considering both layers.

    Returns the highest surface that is at or below
    ``current_fh + MAX_STEP_UP``, preferring layer-2 when valid.
    """
    ix, iy = int(x), int(y)
    if ix < 0 or ix >= map_w or iy < 0 or iy >= map_h:
        return 0.0

    fh1 = floor_heights[iy][ix] if iy < len(floor_heights) and ix < len(floor_heights[iy]) else 0.0

    fh2 = LAYER_NONE
    if floor2_heights and iy < len(floor2_heights) and ix < len(floor2_heights[iy]):
        fh2 = floor2_heights[iy][ix]

    if fh2 <= LAYER_NONE + 1.0:
        return fh1  # no layer-2

    # Pick the highest floor within stepping range
    for fh in sorted((fh1, fh2), reverse=True):
        if fh <= current_fh + MAX_STEP_UP:
            return fh
    return fh1  # fallback: primary


def _can_step_height(
    x: float, y: float,
    current_fh: float,
    map_h: int, map_w: int,
    tiles: list[list[str]],
    floor_heights: list[list[float]],
    ceil_heights: list[list[float]],
    floor2_heights: list[list[float]] | None,
    ceil2_heights: list[list[float]] | None,
) -> bool:
    """Return True if the player can step to (x, y) from *current_fh*.

    Checks multiple sample points within STEP_RADIUS.  At each point
    the move is valid when **at least one** floor surface (primary or
    layer-2) satisfies step-up, step-down, and head-clearance checks.
    """
    for dx in (-STEP_RADIUS, 0.0, STEP_RADIUS):
        for dy in (-STEP_RADIUS, 0.0, STEP_RADIUS):
            cx, cy = x + dx, y + dy
            ix, iy = int(cx), int(cy)
            if ix < 0 or ix >= map_w or iy < 0 or iy >= map_h:
                return False
            if tiles[iy][ix] in SOLID_IDS:
                return False

            fh1 = floor_heights[iy][ix] if iy < len(floor_heights) and ix < len(floor_heights[iy]) else 0.0
            ch1 = ceil_heights[iy][ix] if iy < len(ceil_heights) and ix < len(ceil_heights[iy]) else 1.0

            fh2 = LAYER_NONE
            ch2 = LAYER_NONE
            if floor2_heights and iy < len(floor2_heights) and ix < len(floor2_heights[iy]):
                fh2 = floor2_heights[iy][ix]
            if ceil2_heights and iy < len(ceil2_heights) and ix < len(ceil2_heights[iy]):
                ch2 = ceil2_heights[iy][ix]

            has_layer2 = fh2 > LAYER_NONE + 1.0
            found_valid = False

            # ── Primary floor surface ──
            step = fh1 - current_fh
            # If layer-2 underside is above primary floor, it limits headroom
            if has_layer2 and ch2 > LAYER_NONE + 1.0 and ch2 > fh1:
                eff_ceil = min(ch1, ch2)
            else:
                eff_ceil = ch1
            gap = eff_ceil - fh1
            if -MAX_STEP_DOWN <= step <= MAX_STEP_UP and gap >= HEAD_CLEARANCE:
                found_valid = True

            # ── Layer-2 floor surface ──
            if has_layer2:
                step2 = fh2 - current_fh
                # Headroom above layer-2: if fh2 is above primary ceiling,
                # there's open sky — headroom is unlimited.
                if ch1 > fh2:
                    gap2 = ch1 - fh2
                else:
                    gap2 = 10.0  # above primary ceiling → open sky
                if -MAX_STEP_DOWN <= step2 <= MAX_STEP_UP and gap2 >= HEAD_CLEARANCE:
                    found_valid = True

            if not found_valid:
                return False
    return True


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
                    portal_tiles: set[tuple[int, int]] | None = None,
                    *,
                    floor_heights: list[list[float]] | None = None,
                    ceil_heights: list[list[float]] | None = None,
                    floor2_heights: list[list[float]] | None = None,
                    ceil2_heights: list[list[float]] | None = None,
                    player_fh: float | None = None,
                    ) -> float | None:
    """Apply velocities to positions with axis-separated wall collision.

    Parameters
    ----------
    portal_tiles
        Set of (row, col) coordinates that host a portal, used for
        doorway magnetism.  Pass ``session._portal_map.keys()`` or
        ``session.portal_positions``.  ``None`` disables nudge.
    floor_heights, ceil_heights, floor2_heights, ceil2_heights
        Optional per-cell height grids.  When provided together with
        *player_fh*, the **Player** entity gets height-aware collision
        that supports walking on raised floors and layer-2 surfaces.
    player_fh
        Current floor height under the player.  Required for height-
        aware collision; ignored for non-Player entities.

    Returns
    -------
    float | None
        Updated player floor height when height-aware collision is
        active, otherwise ``None``.
    """
    h = len(tiles)
    w = len(tiles[0]) if h else 0
    _ptiles: set[tuple[int, int]] = portal_tiles or set()

    use_height = (floor_heights is not None
                  and ceil_heights is not None
                  and player_fh is not None)
    new_player_fh: float | None = None

    for eid, pos, vel in world.query(Position, Velocity):
        if abs(vel.x) < 0.001 and abs(vel.y) < 0.001:
            # Still need to update player_fh for current position
            if use_height and world.has(eid, Player):
                new_player_fh = floor_height_at(
                    pos.x, pos.y, h, w,
                    floor_heights, floor2_heights, player_fh)
            continue

        # Use collider dimensions if available, else default 0.6x0.6
        col = world.get(eid, Collider)
        hw = col.w if col else 0.6
        hh = col.h if col else 0.6

        is_player = world.has(eid, Player)

        # Doorway magnetism — gently steer toward portal centres
        if is_player and _ptiles:
            vel.x, vel.y = _doorway_nudge(
                pos.x, pos.y, vel.x, vel.y,
                hw, hh, h, w, tiles, _ptiles, dt,
            )

        nx = pos.x + vel.x * dt
        ny = pos.y + vel.y * dt

        # X axis — tile collision first, then height check for player
        if _hits_wall(nx, pos.y, hw, hh, h, w, tiles):
            nx = pos.x
            vel.x = 0.0
        elif use_height and is_player and not _can_step_height(
                nx, pos.y, player_fh, h, w,
                tiles, floor_heights, ceil_heights,
                floor2_heights, ceil2_heights):
            nx = pos.x
            vel.x = 0.0

        # Y axis
        if _hits_wall(nx, ny, hw, hh, h, w, tiles):
            ny = pos.y
            vel.y = 0.0
        elif use_height and is_player and not _can_step_height(
                nx, ny, player_fh, h, w,
                tiles, floor_heights, ceil_heights,
                floor2_heights, ceil2_heights):
            ny = pos.y
            vel.y = 0.0

        pos.x = nx
        pos.y = ny

        # Update player floor height after movement
        if use_height and is_player:
            new_player_fh = floor_height_at(
                pos.x, pos.y, h, w,
                floor_heights, floor2_heights, player_fh)

    return new_player_fh
