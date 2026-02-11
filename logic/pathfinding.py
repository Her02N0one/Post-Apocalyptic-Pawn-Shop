"""logic/pathfinding.py — A* pathfinding on the tile grid.

Tile penalties
--------------
Each tile type has a traversal cost.  Negative means impassable.
Costs are added to the base movement cost (1.0 cardinal, ~1.41 diagonal).

The default penalty map:

    VOID / WALL  → -1  (blocked)
    GRASS / DIRT / STONE / WOOD_FLOOR / TELEPORTER → 0  (free)
    WATER        → 8   (strongly avoided)

Public API
----------
``find_path(zone, sx, sy, gx, gy, ...)`` → ``list[(x,y)]`` or ``None``
``path_next_waypoint(path, px, py)`` → ``(wx, wy)`` or ``None``
"""

from __future__ import annotations
import heapq
import math
from typing import Optional

from core.zone import ZONE_MAPS
from core.constants import (
    TILE_VOID, TILE_GRASS, TILE_DIRT, TILE_STONE,
    TILE_WATER, TILE_WOOD_FLOOR, TILE_WALL, TILE_TELEPORTER,
)


# ── Penalty table ────────────────────────────────────────────────────

DEFAULT_PENALTIES: dict[int, float] = {
    TILE_VOID:       -1,
    TILE_GRASS:       0,
    TILE_DIRT:        0,
    TILE_STONE:       0,
    TILE_WATER:       8,
    TILE_WOOD_FLOOR:  0,
    TILE_WALL:       -1,
    TILE_TELEPORTER:  0,
}

# Allow callers to compose custom penalty dicts
PENALTY_BLOCKED = -1
PENALTY_OPEN    =  0
PENALTY_WATER   =  8
PENALTY_DANGER  =  8
PENALTY_DAMAGE  = 16


# ── 8-directional offsets ────────────────────────────────────────────

_DIRS = (
    (-1,  0), ( 1,  0), ( 0, -1), ( 0,  1),    # cardinal
    (-1, -1), (-1,  1), ( 1, -1), ( 1,  1),     # diagonal
)
_COSTS = (
    1.0, 1.0, 1.0, 1.0,
    1.414, 1.414, 1.414, 1.414,
)


# ── A* search ────────────────────────────────────────────────────────

def find_path(
    zone_name: str,
    sx: float, sy: float,
    gx: float, gy: float,
    max_dist: int = 32,
    penalties: Optional[dict[int, float]] = None,
) -> list[tuple[float, float]] | None:
    """A* pathfind on the zone tile grid.

    Parameters
    ----------
    zone_name : str
        Name of the loaded zone (key into ``ZONE_MAPS``).
    sx, sy : float
        Start position in tile coordinates.
    gx, gy : float
        Goal position in tile coordinates.
    max_dist : int
        Maximum search radius in tiles (limits work per call).
    penalties : dict | None
        Override tile-type → penalty map.  Negative = impassable.

    Returns
    -------
    list[(float, float)] | None
        List of (x, y) waypoints (tile centres) from near-start to goal,
        or ``None`` if no path exists.
    """
    tiles = ZONE_MAPS.get(zone_name)
    if not tiles:
        return None

    rows = len(tiles)
    cols = len(tiles[0]) if rows else 0
    if rows == 0 or cols == 0:
        return None

    sr, sc = int(sy), int(sx)
    gr, gc = int(gy), int(gx)

    # Clamp to grid
    if not (0 <= sr < rows and 0 <= sc < cols):
        return None
    if not (0 <= gr < rows and 0 <= gc < cols):
        return None

    # Trivial case — already there
    if sr == gr and sc == gc:
        return [(gx, gy)]

    pen = penalties or DEFAULT_PENALTIES

    # Goal must be passable
    goal_tile = tiles[gr][gc]
    if pen.get(goal_tile, 0) < 0:
        return None

    # Open set: (f_score, row, col)
    open_set: list[tuple[float, int, int]] = [(0.0, sr, sc)]
    g_score: dict[tuple[int, int], float] = {(sr, sc): 0.0}
    came_from: dict[tuple[int, int], tuple[int, int]] = {}
    closed: set[tuple[int, int]] = set()

    while open_set:
        _f, r, c = heapq.heappop(open_set)

        if (r, c) in closed:
            continue
        closed.add((r, c))

        if r == gr and c == gc:
            # ── Reconstruct path ─────────────────────────────────────
            path: list[tuple[float, float]] = []
            node = (gr, gc)
            while node in came_from:
                path.append((node[1] + 0.5, node[0] + 0.5))
                node = came_from[node]
            path.reverse()
            return path

        # Limit search radius
        if abs(r - sr) > max_dist or abs(c - sc) > max_dist:
            continue

        for (dr, dc), move_cost in zip(_DIRS, _COSTS):
            nr, nc = r + dr, c + dc
            if nr < 0 or nc < 0 or nr >= rows or nc >= cols:
                continue
            if (nr, nc) in closed:
                continue

            tile_type = tiles[nr][nc]
            tile_pen = pen.get(tile_type, 0)
            if tile_pen < 0:
                continue  # impassable

            # Diagonal: prevent corner-cutting through walls
            if dr != 0 and dc != 0:
                adj_a = tiles[r][nc]
                adj_b = tiles[nr][c]
                if pen.get(adj_a, 0) < 0 or pen.get(adj_b, 0) < 0:
                    continue

            new_g = g_score[(r, c)] + move_cost + tile_pen
            if new_g < g_score.get((nr, nc), float("inf")):
                g_score[(nr, nc)] = new_g
                came_from[(nr, nc)] = (r, c)
                # Chebyshev heuristic (consistent for 8-dir)
                h = max(abs(nr - gr), abs(nc - gc))
                heapq.heappush(open_set, (new_g + h, nr, nc))

    return None  # no path found


# ── Path following helper ────────────────────────────────────────────

def path_next_waypoint(
    path: list[tuple[float, float]],
    px: float, py: float,
    reach: float = 0.4,
) -> tuple[float, float] | None:
    """Pop reached waypoints and return the next one to steer toward.

    Mutates *path* in-place — removes waypoints the entity has reached.
    Returns ``None`` when the path is exhausted.
    """
    while path:
        wx, wy = path[0]
        if math.hypot(wx - px, wy - py) < reach:
            path.pop(0)
            continue
        return (wx, wy)
    return None
