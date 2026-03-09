"""editor/commands/sculpt_cmds.py — Sculpt tool command definitions + handlers.

Phase 0: each command wraps an existing ``_*_at()`` method on the editor.
The handler calls the method directly — no logic is moved yet.  This
establishes the command pattern so future phases can replace the
implementation with proper inverse commands and decoupled mutations.

Commands — click path (single cell)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
* ``SculptFloorRaise``  — raise floor at one cell
* ``SculptFloorLower``  — lower floor at one cell
* ``SculptCeilRaise``   — raise ceiling at one cell
* ``SculptCeilLower``   — lower ceiling at one cell

Commands — key / scroll / batch
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
* ``SculptToggleCeiling``       — toggle ceiling (T key)
* ``SculptResetCeiling``        — reset ceiling height (R on ceiling)
* ``SculptResetFloor``          — reset floor height (R on floor)
* ``SculptClearCell``            — clear cell (Delete on L1)
* ``SculptAdjustUpperWall``      — adjust upper wall (U key variants)
* ``SculptScrollUpperWall``      — scroll upper wall height
* ``SculptExtendFloor``          — extend floor via scroll
* ``SculptExtendWallCeiling``    — extend wall ceiling via scroll
* ``SculptBatchMakeWall``        — convert selection to walls
* ``SculptBatchMakeOpen``        — convert selection to open
* ``SculptFlattenFloors``        — flatten selected floors
* ``SculptFlattenCeilings``      — flatten selected ceilings
* ``SculptBatchRaiseUpperWall``  — raise upper walls in selection
* ``SculptBatchLowerUpperWall``  — lower upper walls in selection
* ``SculptBatchResetUpperWall``  — reset upper walls in selection
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
class SculptFloorRaise(Command):
    """Raise floor height at a single cell by the editor's snap_y."""
    cell: tuple[int, int]


@dataclass(frozen=True)
class SculptFloorLower(Command):
    """Lower floor height at a single cell by the editor's snap_y."""
    cell: tuple[int, int]


@dataclass(frozen=True)
class SculptCeilRaise(Command):
    """Raise ceiling height at a single cell by the editor's snap_y."""
    cell: tuple[int, int]


@dataclass(frozen=True)
class SculptCeilLower(Command):
    """Lower ceiling height at a single cell by the editor's snap_y."""
    cell: tuple[int, int]


# ── Command definitions — key / scroll / batch ───────────────────

@dataclass(frozen=True)
class SculptToggleCeiling(Command):
    """Toggle ceiling at aimed cell or selection (T key)."""
    remove_only: bool = False
    add_only: bool = False


@dataclass(frozen=True)
class SculptResetCeiling(Command):
    """Reset ceiling height at aimed cell (R key on ceiling)."""
    pass


@dataclass(frozen=True)
class SculptResetFloor(Command):
    """Reset floor height at aimed cell (R key on floor)."""
    pass


@dataclass(frozen=True)
class SculptClearCell(Command):
    """Clear cell geometry (Delete key on L1)."""
    pass


@dataclass(frozen=True)
class SculptAdjustUpperWall(Command):
    """Adjust upper wall height (U key variants)."""
    modifier: int  # 0=raise, KMOD_SHIFT=lower, KMOD_CTRL=reset


@dataclass(frozen=True)
class SculptScrollUpperWall(Command):
    """Scroll upper wall height (mouse scroll on ceiling)."""
    direction: int


@dataclass(frozen=True)
class SculptExtendFloor(Command):
    """Extend floor height via scroll."""
    cell: tuple[int, int]
    direction: int


@dataclass(frozen=True)
class SculptExtendWallCeiling(Command):
    """Extend wall ceiling via scroll."""
    cell: tuple[int, int]
    direction: int


@dataclass(frozen=True)
class SculptBatchMakeWall(Command):
    """Convert selected/aimed cells to walls (Shift+H or sel.make_wall)."""
    pass


@dataclass(frozen=True)
class SculptBatchMakeOpen(Command):
    """Convert selected/aimed cells to open (H or sel.make_open)."""
    pass


@dataclass(frozen=True)
class SculptFlattenFloors(Command):
    """Flatten all selected floors to the same height."""
    pass


@dataclass(frozen=True)
class SculptFlattenCeilings(Command):
    """Flatten all selected ceilings to the same height."""
    pass


@dataclass(frozen=True)
class SculptBatchRaiseUpperWall(Command):
    """Raise upper walls on all selected cells."""
    pass


@dataclass(frozen=True)
class SculptBatchLowerUpperWall(Command):
    """Lower upper walls on all selected cells."""
    pass


@dataclass(frozen=True)
class SculptBatchResetUpperWall(Command):
    """Reset upper walls on all selected cells."""
    pass


# ── Handler factories — click path ───────────────────────────────
#
# Each handler closes over the editor reference.  In Phase 1 these
# will be refactored to read the old value and return inverse commands.


def _make_floor_raise_handler(editor: Any):
    def handle(cmd: SculptFloorRaise) -> bool:
        return editor._floor_raise_at(cmd.cell[0], cmd.cell[1])
    return handle


def _make_floor_lower_handler(editor: Any):
    def handle(cmd: SculptFloorLower) -> bool:
        return editor._floor_lower_at(cmd.cell[0], cmd.cell[1])
    return handle


def _make_ceil_raise_handler(editor: Any):
    def handle(cmd: SculptCeilRaise) -> bool:
        return editor._ceiling_raise_at(cmd.cell[0], cmd.cell[1])
    return handle


def _make_ceil_lower_handler(editor: Any):
    def handle(cmd: SculptCeilLower) -> bool:
        return editor._ceiling_lower_at(cmd.cell[0], cmd.cell[1])
    return handle


# ── Handler factories — key / scroll / batch ─────────────────────


def _make_toggle_ceiling_handler(editor: Any):
    def handle(cmd: SculptToggleCeiling) -> bool:
        return suppress_undo(editor, editor._toggle_ceiling,
                             remove_only=cmd.remove_only,
                             add_only=cmd.add_only)
    return handle


def _make_reset_ceiling_handler(editor: Any):
    def handle(cmd: SculptResetCeiling) -> bool:
        return suppress_undo(editor, editor._reset_ceiling)
    return handle


def _make_reset_floor_handler(editor: Any):
    def handle(cmd: SculptResetFloor) -> bool:
        return suppress_undo(editor, editor._reset_floor)
    return handle


def _make_clear_cell_handler(editor: Any):
    def handle(cmd: SculptClearCell) -> bool:
        return suppress_undo(editor, editor._clear_cell)
    return handle


def _make_adjust_upper_wall_handler(editor: Any):
    def handle(cmd: SculptAdjustUpperWall) -> bool:
        return suppress_undo(editor, editor._adjust_upper_wall_height,
                             cmd.modifier)
    return handle


def _make_scroll_upper_wall_handler(editor: Any):
    def handle(cmd: SculptScrollUpperWall) -> bool:
        return suppress_and_detect(editor, editor._scroll_upper_wall,
                                   cmd.direction)
    return handle


def _make_extend_floor_handler(editor: Any):
    def handle(cmd: SculptExtendFloor) -> bool:
        return suppress_and_detect(editor, editor._extend_floor,
                                   cmd.cell[0], cmd.cell[1], cmd.direction)
    return handle


def _make_extend_wall_ceiling_handler(editor: Any):
    def handle(cmd: SculptExtendWallCeiling) -> bool:
        return suppress_and_detect(editor, editor._extend_wall_ceiling,
                                   cmd.cell[0], cmd.cell[1], cmd.direction)
    return handle


def _make_batch_make_wall_handler(editor: Any):
    def handle(cmd: SculptBatchMakeWall) -> bool:
        return suppress_undo(editor, editor._batch_make_wall)
    return handle


def _make_batch_make_open_handler(editor: Any):
    def handle(cmd: SculptBatchMakeOpen) -> bool:
        return suppress_undo(editor, editor._batch_make_open)
    return handle


def _make_flatten_floors_handler(editor: Any):
    def handle(cmd: SculptFlattenFloors) -> bool:
        return suppress_undo(editor, editor._flatten_floors)
    return handle


def _make_flatten_ceilings_handler(editor: Any):
    def handle(cmd: SculptFlattenCeilings) -> bool:
        return suppress_undo(editor, editor._flatten_ceilings)
    return handle


def _make_batch_raise_upper_wall_handler(editor: Any):
    def handle(cmd: SculptBatchRaiseUpperWall) -> bool:
        return suppress_undo(editor, editor._batch_raise_upper_wall)
    return handle


def _make_batch_lower_upper_wall_handler(editor: Any):
    def handle(cmd: SculptBatchLowerUpperWall) -> bool:
        return suppress_undo(editor, editor._batch_lower_upper_wall)
    return handle


def _make_batch_reset_upper_wall_handler(editor: Any):
    def handle(cmd: SculptBatchResetUpperWall) -> bool:
        return suppress_undo(editor, editor._batch_reset_upper_wall)
    return handle


# ── Bulk registration ─────────────────────────────────────────────

def register_sculpt_handlers(bus: CommandBus, editor: Any) -> None:
    """Register all sculpt command handlers on *bus*."""
    # Click-path
    bus.register(SculptFloorRaise, _make_floor_raise_handler(editor))
    bus.register(SculptFloorLower, _make_floor_lower_handler(editor))
    bus.register(SculptCeilRaise,  _make_ceil_raise_handler(editor))
    bus.register(SculptCeilLower,  _make_ceil_lower_handler(editor))
    # Key / scroll / batch
    bus.register(SculptToggleCeiling,      _make_toggle_ceiling_handler(editor))
    bus.register(SculptResetCeiling,       _make_reset_ceiling_handler(editor))
    bus.register(SculptResetFloor,         _make_reset_floor_handler(editor))
    bus.register(SculptClearCell,          _make_clear_cell_handler(editor))
    bus.register(SculptAdjustUpperWall,    _make_adjust_upper_wall_handler(editor))
    bus.register(SculptScrollUpperWall,    _make_scroll_upper_wall_handler(editor))
    bus.register(SculptExtendFloor,        _make_extend_floor_handler(editor))
    bus.register(SculptExtendWallCeiling,  _make_extend_wall_ceiling_handler(editor))
    bus.register(SculptBatchMakeWall,      _make_batch_make_wall_handler(editor))
    bus.register(SculptBatchMakeOpen,      _make_batch_make_open_handler(editor))
    bus.register(SculptFlattenFloors,      _make_flatten_floors_handler(editor))
    bus.register(SculptFlattenCeilings,    _make_flatten_ceilings_handler(editor))
    bus.register(SculptBatchRaiseUpperWall,  _make_batch_raise_upper_wall_handler(editor))
    bus.register(SculptBatchLowerUpperWall,  _make_batch_lower_upper_wall_handler(editor))
    bus.register(SculptBatchResetUpperWall,  _make_batch_reset_upper_wall_handler(editor))
