"""editor/commands/events.py — Read-only event types emitted by the command bus.

Events are passive notifications — no mutation is allowed inside
event handlers.  Subscribe via ``event_bus.subscribe(EventType, cb)``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from editor.commands.base import Command


@dataclass(frozen=True)
class StateChanged:
    """A mutation occurred via the command bus."""
    source_command: Command


@dataclass(frozen=True)
class SelectionChanged:
    """The cell or object selection changed."""
    cells: frozenset[tuple[int, int]]
    objects: frozenset[tuple[str, int]]


@dataclass(frozen=True)
class ToolChanged:
    """The active tool was switched."""
    old_tool: str
    new_tool: str


@dataclass(frozen=True)
class ViewDirtied:
    """The viewport surface needs a re-render."""
    pass
