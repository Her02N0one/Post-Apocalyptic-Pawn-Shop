"""editor/commands/misc_cmds.py — Miscellaneous command definitions + handlers.

Phase 0: wraps clipboard, duplicate, and object-layer operations.

Commands
~~~~~~~~
* ``ClipboardPaste``       — paste clipboard onto selection/aimed cell
* ``DuplicateSelection``   — duplicate selected cells (Ctrl+D)
* ``ObjectDeleteSelected`` — delete all selected objects (Delete key)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from editor.commands.base import (
    Command, CommandBus,
    suppress_undo, suppress_and_detect,
)


# ── Command definitions ───────────────────────────────────────────

@dataclass(frozen=True)
class ClipboardPaste(Command):
    """Paste the clipboard state onto the selection or aimed cell."""
    pass


@dataclass(frozen=True)
class DuplicateSelection(Command):
    """Duplicate selected cells, shifting +1 row/+1 col (Ctrl+D)."""
    pass


@dataclass(frozen=True)
class ObjectDeleteSelected(Command):
    """Delete all currently selected objects."""
    pass


# ── Handler factories ─────────────────────────────────────────────

def _make_clipboard_paste_handler(editor: Any):
    def handle(cmd: ClipboardPaste) -> bool:
        return suppress_and_detect(editor, editor._clipboard_paste)
    return handle


def _make_duplicate_selection_handler(editor: Any):
    def handle(cmd: DuplicateSelection) -> bool:
        return suppress_and_detect(editor, editor._duplicate_selection)
    return handle


def _make_object_delete_selected_handler(editor: Any):
    def handle(cmd: ObjectDeleteSelected) -> bool:
        return suppress_and_detect(editor, editor.objects.delete_selected)
    return handle


# ── Bulk registration ─────────────────────────────────────────────

def register_misc_handlers(bus: CommandBus, editor: Any) -> None:
    """Register clipboard/duplicate/object-layer handlers on *bus*."""
    bus.register(ClipboardPaste,       _make_clipboard_paste_handler(editor))
    bus.register(DuplicateSelection,   _make_duplicate_selection_handler(editor))
    bus.register(ObjectDeleteSelected, _make_object_delete_selected_handler(editor))
