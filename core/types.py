"""core/types.py — Canonical enum types.

Replaces magic strings with validated enums.  A typo like
``Direction.DONW`` is an immediate AttributeError, not a silent bug.
"""

from __future__ import annotations

from enum import Enum, auto


class Direction(Enum):
    """Cardinal facing direction."""
    UP = auto()
    DOWN = auto()
    LEFT = auto()
    RIGHT = auto()


class EntityKind(Enum):
    """What role an entity plays in the game."""
    PLAYER = auto()
    NPC = auto()
    ITEM = auto()
    CONTAINER = auto()
    DUMMY = auto()
    BEAST = auto()
    GROUND_ITEM = auto()
    CROP = auto()


# ── Wall face constants (used by raycaster + renderer) ───────────

FACE_NORTH = 0
FACE_SOUTH = 1
FACE_EAST  = 2
FACE_WEST  = 3

FACE_NAMES: tuple[str, ...] = ("north", "south", "east", "west")


def face_from_side(side: int, ray_dir_x: float, ray_dir_y: float) -> int:
    """Derive which compass face was hit from DDA ``side`` + ray direction.

    ``side == 0`` → X-axis boundary (east/west face)
    ``side == 1`` → Y-axis boundary (north/south face)
    """
    if side == 0:
        return FACE_WEST if ray_dir_x > 0 else FACE_EAST
    else:
        return FACE_NORTH if ray_dir_y > 0 else FACE_SOUTH
