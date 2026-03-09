"""editor/commands/select_cmds.py — Selection tool command definitions + handlers.

Phase 0: wraps existing selection-batch methods.

Commands
~~~~~~~~
* ``SelScroll``       — batch raise/lower selected cells (scroll)
* ``SelDelete``       — delete/reset selected cells (Delete key)
* ``SelResetCells``   — reset all selected cells to defaults
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from editor.commands.base import Command, CommandBus, suppress_undo


# ── Command definitions ───────────────────────────────────────────

@dataclass(frozen=True)
class SelScroll(Command):
    """Batch raise/lower selected cell floors or ceilings."""
    direction: int = 1
    ceiling: bool = False


@dataclass(frozen=True)
class SelDelete(Command):
    """Handle Delete/Backspace in select tool mode."""
    pass


@dataclass(frozen=True)
class SelResetCells(Command):
    """Reset all selected cells to default state."""
    pass


# ── Handler factories ─────────────────────────────────────────────

def _make_sel_scroll_handler(editor: Any):
    def handle(cmd: SelScroll) -> bool:
        return suppress_undo(editor, editor._sel_scroll,
                             cmd.direction, ceiling=cmd.ceiling)
    return handle


def _make_sel_delete_handler(editor: Any):
    def handle(cmd: SelDelete) -> bool:
        return suppress_undo(editor, editor._sel_delete)
    return handle


def _make_sel_reset_cells_handler(editor: Any):
    def handle(cmd: SelResetCells) -> bool:
        return suppress_undo(editor, editor._sel_reset_cells)
    return handle


# ── Bulk registration ─────────────────────────────────────────────

def register_select_handlers(bus: CommandBus, editor: Any) -> None:
    """Register all selection command handlers on *bus*."""
    bus.register(SelScroll,     _make_sel_scroll_handler(editor))
    bus.register(SelDelete,     _make_sel_delete_handler(editor))
    bus.register(SelResetCells, _make_sel_reset_cells_handler(editor))
