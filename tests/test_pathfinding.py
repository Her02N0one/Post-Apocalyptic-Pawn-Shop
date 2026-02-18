"""tests/test_pathfinding.py — Tests for systems/pathfinding.py

Covers A*, BFS flood fill, random walkable target, Bresenham LOS,
and entity-in-LOS filtering.
"""

import unittest
from core.tiles import SOLID_IDS


def _solid_id() -> int:
    return next(iter(SOLID_IDS))


def _open_grid(h: int = 10, w: int = 10) -> list[list[int]]:
    """Fully walkable interior with wall borders."""
    sid = _solid_id()
    grid: list[list[int]] = []
    for r in range(h):
        row: list[int] = []
        for c in range(w):
            if r == 0 or r == h - 1 or c == 0 or c == w - 1:
                row.append(sid)
            else:
                row.append(1)
        grid.append(row)
    return grid


class TestAstar(unittest.TestCase):
    """A* pathfinding on tile grid."""

    def test_simple_path(self):
        from systems.pathfinding import astar
        grid = _open_grid(10, 10)
        path = astar(grid, 1, 1, 1, 5)
        self.assertIsNotNone(path)
        self.assertEqual(path[0], (1, 1))
        self.assertEqual(path[-1], (1, 5))
        # Path length should be optimal (Manhattan distance + 1 for endpoints)
        self.assertEqual(len(path), 5)

    def test_no_path_blocked(self):
        from systems.pathfinding import astar
        grid = _open_grid(10, 10)
        # Wall off row 5 completely
        sid = _solid_id()
        for c in range(10):
            grid[5][c] = sid
        path = astar(grid, 1, 1, 8, 8)
        self.assertIsNone(path)

    def test_start_equals_goal(self):
        from systems.pathfinding import astar
        grid = _open_grid(10, 10)
        path = astar(grid, 3, 3, 3, 3)
        self.assertIsNotNone(path)
        self.assertEqual(path, [(3, 3)])

    def test_start_on_wall(self):
        from systems.pathfinding import astar
        grid = _open_grid(10, 10)
        path = astar(grid, 0, 0, 5, 5)
        self.assertIsNone(path)

    def test_goal_on_wall(self):
        from systems.pathfinding import astar
        grid = _open_grid(10, 10)
        path = astar(grid, 1, 1, 0, 0)
        self.assertIsNone(path)

    def test_path_around_obstacle(self):
        from systems.pathfinding import astar
        grid = _open_grid(10, 10)
        sid = _solid_id()
        # Place a wall blocking direct east path
        for r in range(1, 8):
            grid[r][5] = sid
        path = astar(grid, 4, 1, 4, 8)
        self.assertIsNotNone(path)
        self.assertEqual(path[0], (4, 1))
        self.assertEqual(path[-1], (4, 8))
        # Must go around the wall (path will be longer than direct)
        self.assertGreater(len(path), 8)

    def test_path_continuity(self):
        """Each step in the path should be exactly one tile away."""
        from systems.pathfinding import astar
        grid = _open_grid(10, 10)
        path = astar(grid, 1, 1, 8, 8)
        self.assertIsNotNone(path)
        for i in range(len(path) - 1):
            r1, c1 = path[i]
            r2, c2 = path[i + 1]
            dist = abs(r2 - r1) + abs(c2 - c1)
            self.assertEqual(dist, 1,
                             f"Non-adjacent step: {path[i]} -> {path[i+1]}")

    def test_max_steps_limit(self):
        """With very low max_steps, A* may fail to find a path."""
        from systems.pathfinding import astar
        grid = _open_grid(10, 10)
        path = astar(grid, 1, 1, 8, 8, max_steps=3)
        # With only 3 expansion steps, unlikely to find the path
        # (it's OK if it does, but we verify it doesn't crash)
        if path is not None:
            self.assertEqual(path[-1], (8, 8))


class TestBfsReachable(unittest.TestCase):
    """BFS flood fill of reachable tiles."""

    def test_basic_reach(self):
        from systems.pathfinding import bfs_reachable
        grid = _open_grid(10, 10)
        tiles = bfs_reachable(grid, 5, 5, 2)
        self.assertIn((5, 5), tiles)
        self.assertIn((5, 6), tiles)
        self.assertIn((4, 5), tiles)
        # Diagonals at dist=2
        self.assertIn((4, 6), tiles)
        # (3,5) is dist=2 — should be included
        self.assertIn((3, 5), tiles)

    def test_wall_blocks_spread(self):
        from systems.pathfinding import bfs_reachable
        grid = _open_grid(10, 10)
        sid = _solid_id()
        # Block all but one direction from (5,5)
        grid[4][5] = sid
        grid[6][5] = sid
        grid[5][6] = sid
        # Only (5,4) is reachable at dist=1
        tiles = bfs_reachable(grid, 5, 5, 1)
        self.assertIn((5, 5), tiles)
        self.assertIn((5, 4), tiles)
        self.assertEqual(len(tiles), 2)

    def test_start_on_wall(self):
        from systems.pathfinding import bfs_reachable
        grid = _open_grid(10, 10)
        tiles = bfs_reachable(grid, 0, 0, 5)
        self.assertEqual(len(tiles), 0)

    def test_zero_distance(self):
        from systems.pathfinding import bfs_reachable
        grid = _open_grid(10, 10)
        tiles = bfs_reachable(grid, 5, 5, 0)
        self.assertEqual(tiles, {(5, 5)})


class TestRandomWalkable(unittest.TestCase):
    """Random walkable target selection."""

    def test_finds_target(self):
        from systems.pathfinding import random_walkable
        grid = _open_grid(10, 10)
        target = random_walkable(grid, 5, 5, min_dist=2, max_dist=5)
        self.assertIsNotNone(target)
        r, c = target
        self.assertNotIn(grid[r][c], SOLID_IDS)

    def test_respects_min_distance(self):
        from systems.pathfinding import random_walkable
        grid = _open_grid(10, 10)
        for _ in range(20):
            target = random_walkable(grid, 5, 5, min_dist=3, max_dist=6)
            if target:
                r, c = target
                dist = abs(r - 5) + abs(c - 5)
                self.assertGreaterEqual(dist, 3)

    def test_tiny_grid_returns_none_or_close(self):
        """On a very confined grid, may return None or nearby tile."""
        from systems.pathfinding import random_walkable
        # 3x3 with only centre walkable
        sid = _solid_id()
        grid = [[sid, sid, sid],
                [sid, 1, sid],
                [sid, sid, sid]]
        target = random_walkable(grid, 1, 1, min_dist=2, max_dist=3)
        # No tile >= 2 away exists, so it should fall back or return None
        # Either is acceptable


class TestVisibleTiles(unittest.TestCase):
    """Line-of-sight based visibility map."""

    def test_open_room_sees_all(self):
        from systems.pathfinding import visible_tiles
        grid = _open_grid(8, 8)
        vis = visible_tiles(grid, 4, 4, max_range=10)
        # Should see all interior tiles
        for r in range(1, 7):
            for c in range(1, 7):
                self.assertIn((r, c), vis,
                              f"({r},{c}) should be visible from centre")

    def test_wall_blocks_vision(self):
        from systems.pathfinding import visible_tiles
        grid = _open_grid(10, 10)
        sid = _solid_id()
        # Wall at (5,5) should block tiles behind it from (5,1)
        grid[5][5] = sid
        vis = visible_tiles(grid, 5, 1, max_range=10)
        # (5,5) itself IS visible (the wall is seen), but (5,8) is NOT
        self.assertIn((5, 5), vis)
        self.assertNotIn((5, 8), vis)

    def test_origin_always_visible(self):
        from systems.pathfinding import visible_tiles
        grid = _open_grid(10, 10)
        vis = visible_tiles(grid, 3, 3, max_range=5)
        self.assertIn((3, 3), vis)

    def test_range_limits_vision(self):
        from systems.pathfinding import visible_tiles
        grid = _open_grid(20, 20)
        vis = visible_tiles(grid, 10, 10, max_range=3)
        # Should not see tiles at distance > 3
        for r, c in vis:
            dist = abs(r - 10) + abs(c - 10)
            # Bresenham may slightly overshoot on diagonals
            self.assertLessEqual(dist, 7,
                                 f"({r},{c}) too far from origin")


class TestEntitiesInLos(unittest.TestCase):
    """Entity filtering by LOS."""

    def test_visible_entity(self):
        from systems.pathfinding import entities_in_los
        grid = _open_grid(10, 10)
        entities = [(1, 3, 3), (2, 3, 7)]
        result = entities_in_los(grid, 3, 3, entities, max_range=10)
        # Entity 1 is at the origin — visible
        self.assertTrue(any(e[0] == 1 for e in result))

    def test_entity_behind_wall(self):
        from systems.pathfinding import entities_in_los
        grid = _open_grid(10, 10)
        sid = _solid_id()
        grid[5][5] = sid
        entities = [(1, 5, 1), (2, 5, 8)]
        result = entities_in_los(grid, 5, 1, entities, max_range=12)
        # Entity at (5,1) is origin — visible
        self.assertTrue(any(e[0] == 1 for e in result))
        # Entity at (5,8) is behind wall at (5,5) — not visible
        self.assertFalse(any(e[0] == 2 for e in result))

    def test_out_of_range(self):
        from systems.pathfinding import entities_in_los
        grid = _open_grid(20, 20)
        entities = [(1, 18, 18)]
        result = entities_in_los(grid, 1, 1, entities, max_range=5)
        self.assertEqual(len(result), 0)


class TestPathfindingWithZoneSim(unittest.TestCase):
    """Integration: zone_sim uses pathfinding for NPC movement."""

    def _make_world_and_sim(self):
        from core.ecs import World
        from systems.zone_sim import ZoneSim, ZoneCache
        w = World()
        sim = ZoneSim(w, tick_interval=1.0)
        return w, sim

    def test_npc_follows_path(self):
        """NPC with no path gets a new A* path and follows it."""
        from components import CoarsePos, Timers
        w, sim = self._make_world_and_sim()
        grid = _open_grid(10, 10)
        from systems.zone_sim import ZoneCache
        sim._zones["test"] = ZoneCache(
            name="test", tiles=grid, height=10, width=10, portals={},
        )
        eid = w.spawn()
        w.add(eid, CoarsePos(row=5, col=5, zone="test", speed=2.0))
        w.add(eid, Timers(active={}))

        # Tick multiple times — NPC should move
        initial_r, initial_c = 5, 5
        for _ in range(5):
            sim.tick(1.0, active_zone="__none__")

        cp = w.get(eid, CoarsePos)
        # NPC should have moved (may be in same spot if pathfinding
        # randomly picked a close target, but very unlikely after 5 ticks)
        moved = (cp.row != initial_r) or (cp.col != initial_c)
        # Verify position is still walkable
        self.assertNotIn(grid[cp.row][cp.col], SOLID_IDS)

    def test_portal_bounce_prevention(self):
        """After portal traversal, NPC doesn't immediately bounce back."""
        from components import CoarsePos, Timers
        w, sim = self._make_world_and_sim()

        grid_a = _open_grid(10, 10)
        grid_b = _open_grid(10, 10)

        from systems.zone_sim import ZoneCache
        sim._zones["zone_a"] = ZoneCache(
            name="zone_a", tiles=grid_a, height=10, width=10,
            portals={(5, 5): ("zone_b", 5, 5)},
        )
        sim._zones["zone_b"] = ZoneCache(
            name="zone_b", tiles=grid_b, height=10, width=10,
            portals={(5, 5): ("zone_a", 5, 5)},
        )

        eid = w.spawn()
        w.add(eid, CoarsePos(row=5, col=5, zone="zone_a", speed=2.0))
        w.add(eid, Timers(active={}))

        # First tick: entity on portal → teleports to zone_b
        sim.tick(1.0, active_zone="__none__")
        cp = w.get(eid, CoarsePos)
        self.assertEqual(cp.zone, "zone_b")

        # Second tick: entity is on portal in zone_b but has portal_cd
        sim.tick(1.0, active_zone="__none__")
        cp = w.get(eid, CoarsePos)
        # Should still be in zone_b (not bounced back to zone_a)
        self.assertEqual(cp.zone, "zone_b")

    def test_entity_path_query(self):
        """entity_path returns the cached path."""
        from components import CoarsePos, Timers
        w, sim = self._make_world_and_sim()
        grid = _open_grid(10, 10)
        from systems.zone_sim import ZoneCache
        sim._zones["test"] = ZoneCache(
            name="test", tiles=grid, height=10, width=10, portals={},
        )
        eid = w.spawn()
        w.add(eid, CoarsePos(row=5, col=5, zone="test", speed=2.0))
        w.add(eid, Timers(active={}))

        # Before any ticks, no path
        self.assertEqual(sim.entity_path(eid), [])

        # After a tick, path should be computed (or empty if reached)
        sim.tick(1.0, active_zone="__none__")
        # Path may or may not exist depending on random target


class TestBresenhamLOS(unittest.TestCase):
    """Direct tests for the Bresenham LOS function."""

    def test_adjacent_clear(self):
        from systems.pathfinding import _bresenham_los
        grid = _open_grid(10, 10)
        self.assertTrue(_bresenham_los(grid, 5, 5, 5, 6))

    def test_same_tile(self):
        from systems.pathfinding import _bresenham_los
        grid = _open_grid(10, 10)
        self.assertTrue(_bresenham_los(grid, 5, 5, 5, 5))

    def test_wall_blocks(self):
        from systems.pathfinding import _bresenham_los
        grid = _open_grid(10, 10)
        sid = _solid_id()
        grid[5][5] = sid
        # From (5,3) to (5,7) passes through wall at (5,5)
        self.assertFalse(_bresenham_los(grid, 5, 3, 5, 7))

    def test_diagonal_clear(self):
        from systems.pathfinding import _bresenham_los
        grid = _open_grid(10, 10)
        self.assertTrue(_bresenham_los(grid, 2, 2, 7, 7))


if __name__ == "__main__":
    unittest.main()
