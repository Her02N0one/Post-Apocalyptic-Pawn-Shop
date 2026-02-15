"""components.spatial — Position, movement, and collision shapes.

All coordinates and dimensions are in metres (1 tile = 1 m).
"""

from __future__ import annotations
from dataclasses import dataclass


@dataclass
class Position:
    x: float = 0.0        # m
    y: float = 0.0        # m
    zone: str = "overworld"


@dataclass
class Velocity:
    x: float = 0.0        # m/s
    y: float = 0.0        # m/s


@dataclass
class Collider:
    width: float = 0.8    # m
    height: float = 0.8   # m
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
        (pos.x + ox, pos.y + oy, w, h)   — in metres
    """
    ox: float = 0.0    # m
    oy: float = 0.0    # m
    w: float = 0.8     # m
    h: float = 0.8     # m
