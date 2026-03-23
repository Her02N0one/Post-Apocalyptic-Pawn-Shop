"""tests/conftest.py — shared test fixtures & auto-generated test zones.

Generates ``zones/showcase.zone`` before the test session runs (if it
doesn't already exist).  This allows all tests that call
``load_zone("showcase")`` to work without requiring a hand-authored
zone file.

The generated zone is a 12×12 interior shop with:
  - Walls around the perimeter (tiles = "stone_wall")
  - Open interior cells with floor_height=0.0, ceil_height=0.95
  - A few cells with ceil_height=2.0 (high-ceiling area)
  - Mixed textures (stone_floor, wood_floor, brick_wall)
  - Two entities (npc, crate) for entity-related tests
  - first_person=True (interior mode)
  - An anchor in the middle
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is on sys.path for all tests
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _generate_showcase_zone() -> None:
    """Create a zones/showcase.zone with enough structure for tests."""
    from core.zones import Zone, ZONES_DIR
    from core.zones.game_registry import GameRegistry

    path = ZONES_DIR / "showcase.zone"
    if path.exists():
        return  # already present (user-authored or previous run)

    W, H = 12, 12

    tiles = [["stone_wall"] * W for _ in range(H)]
    floor_heights = [[0.0] * W for _ in range(H)]
    ceil_heights = [[10.0] * W for _ in range(H)]
    floor_textures = [[""] * W for _ in range(H)]
    ceil_textures = [[""] * W for _ in range(H)]
    wall_textures = [[""] * W for _ in range(H)]
    face_textures = [[[""] * 4 for _ in range(W)] for _ in range(H)]
    light_levels = [[1.0] * W for _ in range(H)]
    rotations = [[0] * W for _ in range(H)]
    wall_segments = [[[[], [], [], []] for _ in range(W)] for _ in range(H)]
    floor_step_textures = [[[""] * 4 for _ in range(W)] for _ in range(H)]
    ceil_step_textures = [[[""] * 4 for _ in range(W)] for _ in range(H)]
    floor_step_segments = [[[[], [], [], []] for _ in range(W)] for _ in range(H)]
    ceil_step_segments = [[[[], [], [], []] for _ in range(W)] for _ in range(H)]
    upper_wall_height = [[0.0] * W for _ in range(H)]

    # Interior cells: rows 1..10, cols 1..10 → open with low ceiling
    for r in range(1, H - 1):
        for c in range(1, W - 1):
            tiles[r][c] = "stone_platform"
            floor_heights[r][c] = 0.0
            ceil_heights[r][c] = 0.95
            floor_textures[r][c] = "stone_floor"
            wall_textures[r][c] = "brick_wall"

    # High-ceiling area: a 3×3 section in the upper-right interior
    for r in range(1, 4):
        for c in range(8, 11):
            ceil_heights[r][c] = 2.0
            tiles[r][c] = "stone_platform"
            floor_textures[r][c] = "wood_floor"

    # A few cells with varied textures for find/replace tests
    floor_textures[5][5] = "wood_floor"
    floor_textures[5][6] = "wood_floor"
    ceil_textures[5][5] = "wood_floor"

    # Perimeter wall textures
    for r in range(H):
        for c in range(W):
            if tiles[r][c] == "stone_wall":
                wall_textures[r][c] = "brick_wall"
                ceil_heights[r][c] = 10.0  # full-height wall

    # Entities: an NPC and a crate (plain dicts, matching Zone.entities type)
    entities = [
        {"uid": 1, "type": "npc", "x": 5.5, "y": 5.5,
         "angle": 0.0, "state": "default"},
        {"uid": 2, "type": "crate", "x": 3.5, "y": 3.5,
         "angle": 0.0, "state": "default"},
    ]

    zone = Zone(
        name="showcase",
        width=W,
        height=H,
        anchor=(6.0, 6.0),
        first_person=True,
        tiles=tiles,
        rotations=rotations,
        floor_heights=floor_heights,
        ceil_heights=ceil_heights,
        floor_textures=floor_textures,
        ceil_textures=ceil_textures,
        wall_textures=wall_textures,
        face_textures=face_textures,
        light_levels=light_levels,
        wall_segments=wall_segments,
        floor_step_textures=floor_step_textures,
        ceil_step_textures=ceil_step_textures,
        floor_step_segments=floor_step_segments,
        ceil_step_segments=ceil_step_segments,
        upper_wall_height=upper_wall_height,
        entities=entities,
    )

    # Save to disk
    ZONES_DIR.mkdir(parents=True, exist_ok=True)
    registry = GameRegistry()
    zone.save_to_file(path, registry)


def pytest_configure(config) -> None:
    """Hook: runs before test collection, generates test zones."""
    try:
        from core.tiles.registry import rebuild_derived
        rebuild_derived()
    except Exception:
        pass  # tiles may not be loadable in all CI environments
    try:
        _generate_showcase_zone()
    except Exception as exc:
        import warnings
        warnings.warn(
            f"Could not generate showcase.zone for tests: {exc}",
            stacklevel=2,
        )
