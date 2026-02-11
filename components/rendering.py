"""components.rendering — Visual identity and display."""

from __future__ import annotations
from dataclasses import dataclass


@dataclass
class Identity:
    name: str = "unnamed"
    kind: str = "npc"          # "npc", "item", "object", "player"


@dataclass
class Sprite:
    char: str = "?"            # single character for debug rendering
    color: tuple = (255, 255, 255)
    layer: int = 0             # draw order


@dataclass
class HitFlash:
    """Brief visual feedback when entity is hit."""
    remaining: float = 0.1  # seconds to show flash effect
