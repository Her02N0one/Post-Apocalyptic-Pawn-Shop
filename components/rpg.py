"""components.rpg — Health, hunger, skills, inventory, equipment."""

from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Health:
    current: float = 100.0     # HP
    maximum: float = 100.0     # HP


@dataclass
class Hunger:
    """Hunger gauge — drains over time, restored by eating food.

    ``current`` runs from 0 (starving) to ``maximum`` (full).
    ``rate`` is hunger drained per second (hunger/s).
    ``starve_dps`` is HP damage per second when ``current <= 0``.

    Default rate 0.03/s ≈ 55 minutes from full to starving.
    """
    current: float = 80.0
    maximum: float = 100.0
    rate: float = 0.03         # hunger/s  (~55 min full→starve)
    starve_dps: float = 0.3    # HP/s  when starving


@dataclass
class Needs:
    """High-level motivation derived from stats like hunger.

    Brains read ``priority`` to decide what to do next.
    Values: 'none', 'eat', 'rest', 'flee', 'scavenge', etc.
    ``urgency`` is 0.0–1.0, higher = more desperate.
    """
    priority: str = "none"
    urgency: float = 0.0


@dataclass
class Inventory:
    items: dict[str, int] = field(default_factory=dict)
    capacity: float = 50.0


@dataclass
class Equipment:
    """Tracks which items are equipped in named slots.

    Each value is an item_id string (or "" for empty).
    Equipped items must also exist in the entity's Inventory (count >= 1).
    """
    weapon: str = ""
    armor: str = ""
