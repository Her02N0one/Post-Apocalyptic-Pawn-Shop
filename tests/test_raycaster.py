"""tests/test_raycaster.py — Raycaster unit tests."""

import math
import pytest
from systems.raycaster import (
    cast_walls, project_entities, build_zbuffer,
    WallSlice, BillboardSprite,
)
from core.constants import TILE_WALL, TILE_GRASS


def _box_map(w: int = 10, h: int = 10) -> list[list[int]]:
    """Create a walled box with grass interior."""
    tiles: list[list[int]] = []
    for r in range(h):
        row = []
        for c in range(w):
            if r == 0 or r == h - 1 or c == 0 or c == w - 1:
                row.append(TILE_WALL)
            else:
                row.append(TILE_GRASS)
        tiles.append(row)
    return tiles


class TestCastWalls:
    def test_returns_slices(self):
        tiles = _box_map()
        slices = cast_walls(5.0, 5.0, 0.0, math.pi / 3, 80, 60, tiles)
        assert len(slices) > 0
        assert all(isinstance(s, WallSlice) for s in slices)

    def test_all_columns_hit(self):
        """Every column should produce a slice in a fully walled map."""
        tiles = _box_map()
        slices = cast_walls(5.0, 5.0, 0.0, math.pi / 3, 40, 30, tiles, step=1)
        assert len(slices) == 40

    def test_distances_positive(self):
        tiles = _box_map()
        slices = cast_walls(5.0, 5.0, 0.0, math.pi / 3, 40, 30, tiles)
        for s in slices:
            assert s.distance > 0

    def test_wall_tile_id(self):
        tiles = _box_map()
        slices = cast_walls(5.0, 5.0, 0.0, math.pi / 3, 40, 30, tiles)
        for s in slices:
            assert s.tile_id == TILE_WALL

    def test_step_reduces_count(self):
        tiles = _box_map()
        full = cast_walls(5.0, 5.0, 0.0, math.pi / 3, 80, 60, tiles, step=1)
        half = cast_walls(5.0, 5.0, 0.0, math.pi / 3, 80, 60, tiles, step=2)
        assert len(half) == len(full) // 2

    def test_facing_east_nearest_wall(self):
        """Facing east at (5,5) in 10x10 box — nearest wall at col 9 = dist ~4."""
        tiles = _box_map()
        slices = cast_walls(5.0, 5.0, 0.0, math.pi / 3, 1, 60, tiles, step=1)
        # Centre ray → should hit east wall at x=9, distance ≈ 4
        assert len(slices) == 1
        assert 3.5 < slices[0].distance < 5.0


class TestProjectEntities:
    def test_entity_in_front(self):
        # Player at (5,5) facing east, entity at (8,5)
        ents = [(1, 8.0, 5.0, "D", (200, 200, 200), 1.0, 1.0)]
        bbs = project_entities(5.0, 5.0, 0.0, math.pi / 3, 80, 60, ents)
        assert len(bbs) == 1
        assert bbs[0].distance > 0
        # Should be roughly centred horizontally
        assert 20 < bbs[0].screen_x < 60

    def test_entity_behind_excluded(self):
        # Player at (5,5) facing east, entity at (2,5) — behind
        ents = [(1, 2.0, 5.0, "D", (200, 200, 200), 1.0, 1.0)]
        bbs = project_entities(5.0, 5.0, 0.0, math.pi / 3, 80, 60, ents)
        assert len(bbs) == 0

    def test_sorted_far_to_near(self):
        ents = [
            (1, 8.0, 5.0, "A", (200, 200, 200), 1.0, 1.0),
            (2, 6.0, 5.0, "B", (200, 200, 200), 1.0, 1.0),
        ]
        bbs = project_entities(5.0, 5.0, 0.0, math.pi / 3, 80, 60, ents)
        assert len(bbs) == 2
        assert bbs[0].distance >= bbs[1].distance  # far first


class TestZBuffer:
    def test_size_matches_screen(self):
        slices = [WallSlice(screen_x=0, distance=5.0, height=20,
                            tile_id=6, side=0, tex_x=0.5)]
        zbuf = build_zbuffer(slices, 80, step=1)
        assert len(zbuf) == 80

    def test_filled_at_slice_position(self):
        slices = [WallSlice(screen_x=10, distance=3.0, height=20,
                            tile_id=6, side=0, tex_x=0.5)]
        zbuf = build_zbuffer(slices, 80, step=2)
        assert zbuf[10] == 3.0
        assert zbuf[11] == 3.0
        assert zbuf[9] > 100  # unfilled = 1e10
