"""editor/commands/l2_cmds.py — Layer 2 command definitions + handlers.

Phase 0: wraps existing Layer 2 methods on the editor.

Commands
~~~~~~~~
Click path:
* ``L2Raise``            — raise L2 surface (LMB, selection-aware)
* ``L2Lower``            — lower L2 surface (RMB, selection-aware)
* ``L2Paint``            — paint L2 surface (LMB in paint mode)
* ``L2EraseSingle``      — erase L2 texture at aimed cell (RMB in paint mode)
* ``L2PaintSelection``   — paint L2 across selection (LMB+selection in paint mode)
* ``L2EraseSelection``   — erase L2 across selection (RMB+selection in paint mode)

Scroll / key path:
* ``L2Scroll``           — scroll raise/lower at aimed cell
* ``L2Reset``            — reset L2 data (R key, selection-aware)
* ``L2SelScroll``        — batch raise/lower L2 across selection
* ``L2FlattenFloors``    — flatten L2 floors in selection
* ``L2FlattenCeilings``  — flatten L2 ceilings in selection
* ``L2ToggleCeil``       — toggle L2 ceilings (T key, selection-aware)
* ``L2SelectionReset``   — reset L2 across selection (Delete/reset key)
* ``L2DeleteAimed``      — delete L2 data at aimed cell (Delete key, no selection)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from editor.commands.base import (
    Command, CommandBus,
    suppress_undo, suppress_and_detect,
)


# ── Command definitions — click path ─────────────────────────────

@dataclass(frozen=True)
class L2Raise(Command):
    """Raise L2 surface (LMB). Selection-aware."""
    shift: bool = False
    ctrl: bool = False


@dataclass(frozen=True)
class L2Lower(Command):
    """Lower L2 surface (RMB). Selection-aware."""
    shift: bool = False


@dataclass(frozen=True)
class L2Paint(Command):
    """Paint L2 texture at aimed cell."""
    pass


@dataclass(frozen=True)
class L2EraseSingle(Command):
    """Erase L2 texture at aimed cell (RMB in paint mode, no selection)."""
    pass


@dataclass(frozen=True)
class L2PaintSelection(Command):
    """Paint L2 across selection (LMB+selection in paint mode)."""
    pass


@dataclass(frozen=True)
class L2EraseSelection(Command):
    """Erase L2 across selection (RMB+selection in paint mode)."""
    pass


# ── Command definitions — scroll / key path ──────────────────────

@dataclass(frozen=True)
class L2Scroll(Command):
    """Scroll raise/lower at aimed cell."""
    direction: int = 1


@dataclass(frozen=True)
class L2Reset(Command):
    """Reset L2 data (R key). Selection-aware."""
    pass


@dataclass(frozen=True)
class L2SelScroll(Command):
    """Batch raise/lower L2 across selection."""
    direction: int = 1


@dataclass(frozen=True)
class L2FlattenFloors(Command):
    """Flatten L2 floors in selection."""
    pass


@dataclass(frozen=True)
class L2FlattenCeilings(Command):
    """Flatten L2 ceilings in selection."""
    pass


@dataclass(frozen=True)
class L2ToggleCeil(Command):
    """Toggle L2 ceilings (T key). Selection-aware."""
    pass


@dataclass(frozen=True)
class L2SelectionReset(Command):
    """Reset L2 across selection (sel.reset / sel.remove_ceilings)."""
    pass


@dataclass(frozen=True)
class L2DeleteAimed(Command):
    """Delete L2 data at aimed cell (Delete key, no selection)."""
    pass


# ── Handler factories — click path ───────────────────────────────

def _make_l2_raise_handler(editor: Any):
    def handle(cmd: L2Raise) -> bool:
        return suppress_and_detect(editor, editor._layer2_raise,
                                   cmd.shift, cmd.ctrl)
    return handle


def _make_l2_lower_handler(editor: Any):
    def handle(cmd: L2Lower) -> bool:
        return suppress_and_detect(editor, editor._layer2_lower, cmd.shift)
    return handle


def _make_l2_paint_handler(editor: Any):
    def handle(cmd: L2Paint) -> bool:
        return suppress_and_detect(editor, editor._layer2_paint)
    return handle


def _make_l2_erase_single_handler(editor: Any):
    """Erase L2 at aimed — the editor.py call site does:
        ensure_grids + push_undo + erase_at + dirty
    We replicate that inline (suppress_undo on the whole block).
    """
    def handle(cmd: L2EraseSingle) -> bool:
        hit = editor.aimed
        if not hit:
            return False
        editor._layer2_ensure_grids()
        return editor._layer2_erase_at(hit.row, hit.col)
    return handle


def _make_l2_paint_selection_handler(editor: Any):
    """Paint L2 across selection — editor.py does:
        ensure_grids + push_undo + apply_to_selection(paint_at) + dirty
    """
    def handle(cmd: L2PaintSelection) -> bool:
        editor._layer2_ensure_grids()
        return editor._apply_to_selection(editor._layer2_paint_at)
    return handle


def _make_l2_erase_selection_handler(editor: Any):
    """Erase L2 across selection — editor.py does:
        ensure_grids + push_undo + apply_to_selection(erase_at) + dirty
    """
    def handle(cmd: L2EraseSelection) -> bool:
        editor._layer2_ensure_grids()
        return editor._apply_to_selection(editor._layer2_erase_at)
    return handle


# ── Handler factories — scroll / key path ─────────────────────────

def _make_l2_scroll_handler(editor: Any):
    def handle(cmd: L2Scroll) -> bool:
        return suppress_and_detect(editor, editor._layer2_scroll,
                                   cmd.direction)
    return handle


def _make_l2_reset_handler(editor: Any):
    def handle(cmd: L2Reset) -> bool:
        return suppress_undo(editor, editor._layer2_reset)
    return handle


def _make_l2_sel_scroll_handler(editor: Any):
    def handle(cmd: L2SelScroll) -> bool:
        return suppress_undo(editor, editor._layer2_sel_scroll,
                             cmd.direction)
    return handle


def _make_l2_flatten_floors_handler(editor: Any):
    def handle(cmd: L2FlattenFloors) -> bool:
        return suppress_undo(editor, editor._layer2_flatten_floors)
    return handle


def _make_l2_flatten_ceilings_handler(editor: Any):
    def handle(cmd: L2FlattenCeilings) -> bool:
        return suppress_undo(editor, editor._layer2_flatten_ceilings)
    return handle


def _make_l2_toggle_ceil_handler(editor: Any):
    def handle(cmd: L2ToggleCeil) -> bool:
        return suppress_undo(editor, editor._layer2_toggle_ceil)
    return handle


def _make_l2_selection_reset_handler(editor: Any):
    """Reset L2 at every selected cell."""
    def handle(cmd: L2SelectionReset) -> bool:
        editor._layer2_ensure_grids()
        return editor._apply_to_selection(editor._layer2_reset_at)
    return handle


def _make_l2_delete_aimed_handler(editor: Any):
    """Delete L2 at aimed cell (no selection)."""
    def handle(cmd: L2DeleteAimed) -> bool:
        hit = editor.aimed
        if not hit:
            return False
        editor._layer2_ensure_grids()
        changed = editor._layer2_reset_at(hit.row, hit.col)
        if changed:
            editor._flash("L2 cleared — Ct+Z to undo", 1.2,
                          (0.8, 0.6, 1.0, 1.0))
        return changed
    return handle


# ── Bulk registration ─────────────────────────────────────────────

def register_l2_handlers(bus: CommandBus, editor: Any) -> None:
    """Register all Layer 2 command handlers on *bus*."""
    # Click path
    bus.register(L2Raise,            _make_l2_raise_handler(editor))
    bus.register(L2Lower,            _make_l2_lower_handler(editor))
    bus.register(L2Paint,            _make_l2_paint_handler(editor))
    bus.register(L2EraseSingle,      _make_l2_erase_single_handler(editor))
    bus.register(L2PaintSelection,   _make_l2_paint_selection_handler(editor))
    bus.register(L2EraseSelection,   _make_l2_erase_selection_handler(editor))
    # Scroll / key path
    bus.register(L2Scroll,           _make_l2_scroll_handler(editor))
    bus.register(L2Reset,            _make_l2_reset_handler(editor))
    bus.register(L2SelScroll,        _make_l2_sel_scroll_handler(editor))
    bus.register(L2FlattenFloors,    _make_l2_flatten_floors_handler(editor))
    bus.register(L2FlattenCeilings,  _make_l2_flatten_ceilings_handler(editor))
    bus.register(L2ToggleCeil,       _make_l2_toggle_ceil_handler(editor))
    bus.register(L2SelectionReset,   _make_l2_selection_reset_handler(editor))
    bus.register(L2DeleteAimed,      _make_l2_delete_aimed_handler(editor))
