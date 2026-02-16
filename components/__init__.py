"""components — Typed ECS component dataclasses.

Every game component subclasses ``core.ecs.Component``.
Resources (Camera, GameClock) are plain dataclasses — NOT Components —
so they can only live in ``world.resources``, never on an entity.

Set ``_persist = True`` on components that should survive save/load.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.ecs import Component
from core.types import Direction, EntityKind


# ── Spatial ──────────────────────────────────────────────────────────

@dataclass
class Position(Component):
    """Entity location in the world (tiles)."""
    _persist = True
    x: float = 0.0
    y: float = 0.0
    zone: str = "playground"


@dataclass
class Velocity(Component):
    """Movement vector (tiles/second)."""
    x: float = 0.0
    y: float = 0.0


@dataclass
class Facing(Component):
    """Which direction the entity faces."""
    direction: Direction = Direction.DOWN


@dataclass
class Collider(Component):
    """Axis-aligned collision box (tile units, relative to Position)."""
    w: float = 0.8
    h: float = 0.8
    ox: float = 0.0
    oy: float = 0.0
    solid: bool = True


# ── Rendering ────────────────────────────────────────────────────────

@dataclass
class Sprite(Component):
    """Visual representation — a colored character."""
    char: str = "?"
    color: tuple[int, int, int] = (255, 255, 255)
    layer: int = 0


@dataclass
class Identity(Component):
    """Name and role tag."""
    name: str = ""
    kind: EntityKind = EntityKind.NPC


# ── RPG ──────────────────────────────────────────────────────────────

@dataclass
class Health(Component):
    """Hit points."""
    _persist = True
    current: float = 100.0
    maximum: float = 100.0


@dataclass
class Inventory(Component):
    """Item bag — maps item name → count."""
    _persist = True
    items: dict[str, int] = field(default_factory=dict)


# ── Player ───────────────────────────────────────────────────────────

@dataclass
class Player(Component):
    """Marks this entity as the player-controlled character."""
    speed: float = 6.0


# ═════════════════════════════════════════════════════════════════════
#  Resources (plain dataclasses — NOT Components)
# ═════════════════════════════════════════════════════════════════════

@dataclass
class Camera:
    """Viewport position.  World resource, never attached to an entity."""
    x: float = 0.0
    y: float = 0.0


@dataclass
class GameClock:
    """Canonical game timer (real seconds)."""
    time: float = 0.0


__all__ = [
    # Components
    "Position", "Velocity", "Facing", "Collider",
    "Sprite", "Identity",
    "Health", "Inventory",
    "Player",
    # Resources
    "Camera", "GameClock",
]
