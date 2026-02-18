"""systems/pathfinding.py — Tile-grid pathfinding and spatial queries.

Provides A* search, BFS flood-fill (reachable area), and line-of-sight
based visibility queries.  All operate on the integer tile grid.

    from systems.pathfinding import astar, bfs_reachable, visible_tiles

    path = astar(tiles, 3, 5, 10, 12)        # list of (r,c) or None
    area = bfs_reachable(tiles, 3, 5, 8)      # set of (r,c) within 8 steps
    seen = visible_tiles(tiles, 3, 5, 12)     # set of (r,c) in LOS

Design goals:
    * Pure functions — no ECS coupling, no side effects.
    * Tile grid only — systems/zone_sim.py feeds tile data from ZoneCache.
    * Suitable for both coarse (off-screen) and fine (active) simulation.
"""

from __future__ import annotations

import heapq
from core.tiles import SOLID_IDS


# ═══════════════════════════════════════════════════════════════════
#  A* pathfinding
# ═══════════════════════════════════════════════════════════════════

def _walkable(tiles: list[list[int]], r: int, c: int) -> bool:
    """True if (r,c) is in-bounds and not solid."""
    if r < 0 or c < 0:
        return False
    if r >= len(tiles) or c >= len(tiles[0]):
        return False
    return tiles[r][c] not in SOLID_IDS


_DIRS_4 = ((-1, 0), (1, 0), (0, -1), (0, 1))


def astar(
    tiles: list[list[int]],
    start_r: int, start_c: int,
    goal_r: int, goal_c: int,
    max_steps: int = 800,
) -> list[tuple[int, int]] | None:
    """Find a path from start to goal on the tile grid.

    Returns a list of ``(row, col)`` tiles from start to goal
    (inclusive), or ``None`` if no path exists.  Uses Manhattan
    distance as the heuristic.

    *max_steps* caps the search to avoid runaway on large maps.
    """
    if not _walkable(tiles, start_r, start_c):
        return None
    if not _walkable(tiles, goal_r, goal_c):
        return None
    if (start_r, start_c) == (goal_r, goal_c):
        return [(start_r, start_c)]

    # Priority queue: (f_score, tie-breaker, row, col)
    open_set: list[tuple[int, int, int, int]] = []
    counter = 0
    h = abs(goal_r - start_r) + abs(goal_c - start_c)
    heapq.heappush(open_set, (h, counter, start_r, start_c))

    came_from: dict[tuple[int, int], tuple[int, int]] = {}
    g_score: dict[tuple[int, int], int] = {(start_r, start_c): 0}

    steps = 0
    while open_set and steps < max_steps:
        steps += 1
        _, _, cr, cc = heapq.heappop(open_set)

        if (cr, cc) == (goal_r, goal_c):
            # Reconstruct path
            path: list[tuple[int, int]] = [(cr, cc)]
            while (cr, cc) in came_from:
                cr, cc = came_from[(cr, cc)]
                path.append((cr, cc))
            path.reverse()
            return path

        cur_g = g_score[(cr, cc)]

        for dr, dc in _DIRS_4:
            nr, nc = cr + dr, cc + dc
            if not _walkable(tiles, nr, nc):
                continue
            ng = cur_g + 1
            if ng < g_score.get((nr, nc), 999999):
                g_score[(nr, nc)] = ng
                came_from[(nr, nc)] = (cr, cc)
                h = abs(goal_r - nr) + abs(goal_c - nc)
                counter += 1
                heapq.heappush(open_set, (ng + h, counter, nr, nc))

    return None  # no path found


# ═══════════════════════════════════════════════════════════════════
#  BFS flood fill (reachable area)
# ═══════════════════════════════════════════════════════════════════

def bfs_reachable(
    tiles: list[list[int]],
    start_r: int, start_c: int,
    max_dist: int,
) -> set[tuple[int, int]]:
    """Return all walkable tiles reachable from (start_r, start_c)
    within *max_dist* steps (Manhattan movement, no diagonals).
    """
    if not _walkable(tiles, start_r, start_c):
        return set()

    visited: set[tuple[int, int]] = {(start_r, start_c)}
    frontier: list[tuple[int, int, int]] = [(start_r, start_c, 0)]

    while frontier:
        cr, cc, dist = frontier.pop(0)
        if dist >= max_dist:
            continue
        for dr, dc in _DIRS_4:
            nr, nc = cr + dr, cc + dc
            if (nr, nc) in visited:
                continue
            if _walkable(tiles, nr, nc):
                visited.add((nr, nc))
                frontier.append((nr, nc, dist + 1))

    return visited


# ═══════════════════════════════════════════════════════════════════
#  Random walkable target
# ═══════════════════════════════════════════════════════════════════

def random_walkable(
    tiles: list[list[int]],
    origin_r: int, origin_c: int,
    min_dist: int = 3,
    max_dist: int = 10,
    attempts: int = 20,
) -> tuple[int, int] | None:
    """Pick a random walkable tile within distance range of origin.

    Tries *attempts* random samples from the reachable area.
    Returns ``(row, col)`` or ``None`` if no suitable tile found.
    """
    import random
    reachable = bfs_reachable(tiles, origin_r, origin_c, max_dist)
    candidates = [
        (r, c) for r, c in reachable
        if abs(r - origin_r) + abs(c - origin_c) >= min_dist
    ]
    if not candidates:
        # Fall back to any reachable tile
        candidates = [
            (r, c) for r, c in reachable
            if (r, c) != (origin_r, origin_c)
        ]
    if not candidates:
        return None
    return random.choice(candidates)


# ═══════════════════════════════════════════════════════════════════
#  Line-of-sight visibility
# ═══════════════════════════════════════════════════════════════════

def _bresenham_los(
    tiles: list[list[int]],
    r0: int, c0: int,
    r1: int, c1: int,
) -> bool:
    """True if clear LOS between two tiles (Bresenham ray)."""
    h = len(tiles)
    w = len(tiles[0]) if h else 0
    dr = abs(r1 - r0)
    dc = abs(c1 - c0)
    sr = 1 if r1 > r0 else -1
    sc = 1 if c1 > c0 else -1
    err = dc - dr
    r, c = r0, c0

    limit = (dr + dc) * 2 + 2
    for _ in range(limit):
        if r == r1 and c == c1:
            return True
        if r < 0 or r >= h or c < 0 or c >= w:
            return False
        if tiles[r][c] in SOLID_IDS and (r, c) != (r0, c0):
            return False
        e2 = 2 * err
        if e2 > -dr:
            err -= dr
            c += sc
        if e2 < dc:
            err += dc
            r += sr

    return False


def visible_tiles(
    tiles: list[list[int]],
    origin_r: int, origin_c: int,
    max_range: int = 12,
) -> set[tuple[int, int]]:
    """Return all tiles visible from *origin* via LOS.

    Casts rays to every tile on the border of the range box,
    marking all tiles along clear rays as visible.
    """
    h = len(tiles)
    w = len(tiles[0]) if h else 0
    visible: set[tuple[int, int]] = {(origin_r, origin_c)}

    # Cast to border of the range box
    r_min = max(0, origin_r - max_range)
    r_max = min(h - 1, origin_r + max_range)
    c_min = max(0, origin_c - max_range)
    c_max = min(w - 1, origin_c + max_range)

    border: set[tuple[int, int]] = set()
    for r in range(r_min, r_max + 1):
        border.add((r, c_min))
        border.add((r, c_max))
    for c in range(c_min, c_max + 1):
        border.add((r_min, c))
        border.add((r_max, c))

    for tr, tc in border:
        # Always collect — _collect_ray stops at walls but adds them
        _collect_ray(tiles, origin_r, origin_c, tr, tc, visible)

    return visible


def _collect_ray(
    tiles: list[list[int]],
    r0: int, c0: int,
    r1: int, c1: int,
    out: set[tuple[int, int]],
) -> None:
    """Walk a Bresenham ray, adding all clear tiles to *out*."""
    h = len(tiles)
    w = len(tiles[0]) if h else 0
    dr = abs(r1 - r0)
    dc = abs(c1 - c0)
    sr = 1 if r1 > r0 else -1
    sc = 1 if c1 > c0 else -1
    err = dc - dr
    r, c = r0, c0

    limit = (dr + dc) * 2 + 2
    for _ in range(limit):
        if r < 0 or r >= h or c < 0 or c >= w:
            return
        out.add((r, c))
        if tiles[r][c] in SOLID_IDS and (r, c) != (r0, c0):
            return  # hit wall — it's visible but stop
        if r == r1 and c == c1:
            return
        e2 = 2 * err
        if e2 > -dr:
            err -= dr
            c += sc
        if e2 < dc:
            err += dc
            r += sr


def entities_in_los(
    tiles: list[list[int]],
    origin_r: int, origin_c: int,
    entities: list[tuple[int, int, int]],
    max_range: int = 12,
) -> list[tuple[int, int, int]]:
    """Filter *entities* to only those visible from origin via LOS.

    *entities* is a list of ``(eid, row, col)`` tuples.
    Returns the subset that are within range AND have clear LOS.
    """
    result: list[tuple[int, int, int]] = []
    for eid, er, ec in entities:
        dist = abs(er - origin_r) + abs(ec - origin_c)
        if dist > max_range:
            continue
        if _bresenham_los(tiles, origin_r, origin_c, er, ec):
            result.append((eid, er, ec))
    return result
