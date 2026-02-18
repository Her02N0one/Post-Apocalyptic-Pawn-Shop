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
