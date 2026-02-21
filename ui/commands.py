"""ui/commands.py — UI command types.

Commands are returned from ``Modal.handle_event()`` and processed by the
scene that owns the modal stack.  This keeps modals decoupled from game
logic — they only *request* effects, never execute them.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Union


@dataclass(frozen=True)
class CloseModal:
    """Request to close / pop the topmost modal."""


@dataclass(frozen=True)
class HealPlayer:
    """Request to heal the player by *amount* HP."""
    amount: float = 0.0


@dataclass(frozen=True)
class OpenTrade:
    """Request to open the trade UI with an NPC."""
    npc_eid: int = -1


@dataclass(frozen=True)
class SetFlag:
    """Set a quest-log flag."""
    flag: str = ""
    value: object = True


# Union of every possible UI command (for type hints)
UICommand = Union[CloseModal, HealPlayer, OpenTrade, SetFlag]
