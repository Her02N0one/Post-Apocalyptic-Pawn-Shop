"""components.spatial — Position, movement, and collision shapes."""

from __future__ import annotations
from dataclasses import dataclass


@dataclass
class Position:
    x: float = 0.0
    y: float = 0.0
    zone: str = "overworld"


@dataclass
class Velocity:
    x: float = 0.0
    y: float = 0.0


@dataclass
class Collider:
    width: float = 0.8
    height: float = 0.8
    solid: bool = True


@dataclass
class Facing:
    """Which direction an entity faces.  Updated from Velocity each frame.

    Values: 'right', 'left', 'up', 'down'
    Used by sprite rendering and attack hitbox placement.
    """
    direction: str = "down"


@dataclass
class Hurtbox:
    """Axis-aligned box that can receive damage, offset from Position.

    The final world-space rect is:
        (pos.x + ox, pos.y + oy, w, h)   — in tile units
    """
    ox: float = 0.0
    oy: float = 0.0
    w: float = 0.8
    h: float = 0.8
