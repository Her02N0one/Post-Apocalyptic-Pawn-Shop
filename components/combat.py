"""components.combat — Fighting, loot, and projectiles."""

from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class CombatStats:
    """Entity that can fight."""
    damage: float = 10.0       # HP per hit
    defense: float = 0.0       # HP absorbed per hit


@dataclass
class Loot:
    """Entity that can be looted (one-time)."""
    items: list[str] = field(default_factory=list)  # item IDs to give when looted
    looted: bool = False       # track if already looted


@dataclass
class LootTableRef:
    """Reference to a loot table for dynamic loot generation."""
    table_name: str = ""


@dataclass
class Projectile:
    """A bullet / arrow / thrown object flying through the world.

    Created by the ranged-attack action, ticked in the projectile system.
    ``owner_eid`` is the entity that fired it (excluded from self-hits).
    ``damage`` is the *total* damage this projectile deals on contact.
    """
    owner_eid: int = -1
    damage: float = 10.0       # HP
    speed: float = 12.0        # m/s
    dx: float = 0.0            # normalised direction (unitless)
    dy: float = 0.0
    max_range: float = 10.0    # m  (despawn distance)
    traveled: float = 0.0      # m  (distance flown so far)
    char: str = "."
    color: tuple = (255, 255, 150)
    radius: float = 0.15       # m  (collision radius)
