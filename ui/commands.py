"""ui.commands — Command objects emitted by modals.

Modals return these instead of directly mutating game state that lives
outside their scope.  The scene (or a command processor) reads the list
and applies each effect.

Add new command types here whenever a modal needs to trigger a
cross-cutting side-effect (play sound, spawn particle, etc.).
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Union


@dataclass(frozen=True, slots=True)
class CloseModal:
    """Pop the top modal off the stack."""


@dataclass(frozen=True, slots=True)
class HealPlayer:
    """Apply HP healing to the player entity."""
    amount: float


@dataclass(frozen=True, slots=True)
class OpenTrade:
    """Close dialogue and open the transfer modal with an NPC."""
    npc_eid: int


@dataclass(frozen=True, slots=True)
class SetFlag:
    """Set a flag in the QuestLog resource."""
    flag: str
    value: object = True


# Union of every command type — extend as new commands are added.
UICommand = Union[CloseModal, HealPlayer, OpenTrade, SetFlag]
