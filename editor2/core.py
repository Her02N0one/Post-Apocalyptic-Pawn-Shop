"""editor2/core.py — EditorCore, command bus, and zone mutation commands."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from PySide6.QtCore import QObject, Signal

from core.zones import Zone


# ── Command protocol ─────────────────────────────────────────────


@runtime_checkable
class Command(Protocol):
    """A reversible zone mutation."""

    def execute(self, zone: Zone) -> None: ...
    def undo(self, zone: Zone) -> None: ...

    @property
    def description(self) -> str: ...


# ── Generic commands ─────────────────────────────────────────────


@dataclass(slots=True)
class SetCellFieldCmd:
    """Set zone.<field>[row][col] = new_value.

    Covers wall_textures, floor_textures, ceil_textures,
    floor_heights, ceil_heights, tiles, etc.
    """
    row: int
    col: int
    field: str             # attribute name on Zone
    new_value: str | float
    _old_value: str | float = ""

    @property
    def description(self) -> str:
        return f"Set {self.field} ({self.row},{self.col})"

    def execute(self, zone: Zone) -> None:
        grid = getattr(zone, self.field)
        self._old_value = grid[self.row][self.col]
        grid[self.row][self.col] = self.new_value

    def undo(self, zone: Zone) -> None:
        getattr(zone, self.field)[self.row][self.col] = self._old_value


@dataclass(slots=True)
class SetFaceFieldCmd:
    """Set zone.<field>[row][col][face_idx] = new_value.

    Covers face_textures (and any future per-face-index grid).
    """
    row: int
    col: int
    face_idx: int
    field: str
    new_value: str | float
    _old_value: str | float = ""

    @property
    def description(self) -> str:
        return f"Set {self.field} ({self.row},{self.col})[{self.face_idx}]"

    def execute(self, zone: Zone) -> None:
        self._old_value = getattr(zone, self.field)[self.row][self.col][self.face_idx]
        getattr(zone, self.field)[self.row][self.col][self.face_idx] = self.new_value

    def undo(self, zone: Zone) -> None:
        getattr(zone, self.field)[self.row][self.col][self.face_idx] = self._old_value


@dataclass(slots=True)
class BatchCmd:
    """Group multiple commands into one undo step."""
    commands: list[Command] = field(default_factory=list)
    desc: str = "Batch"

    @property
    def description(self) -> str:
        return self.desc

    def execute(self, zone: Zone) -> None:
        for cmd in self.commands:
            cmd.execute(zone)

    def undo(self, zone: Zone) -> None:
        for cmd in reversed(self.commands):
            cmd.undo(zone)


# ── Command Bus ──────────────────────────────────────────────────


class CommandBus(QObject):
    """Executes commands against a zone with undo/redo support.

    Signals
    -------
    zone_changed : emitted after execute / undo / redo so the viewport
                   and panels can react.
    """
    zone_changed = Signal()

    def __init__(self, zone: Zone, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._zone = zone
        self._undo_stack: list[Command] = []
        self._redo_stack: list[Command] = []
        self._batch: list[Command] | None = None
        self._batch_desc: str = ""
        self._batch_defer_signal: bool = False

    @property
    def zone(self) -> Zone:
        return self._zone

    # ── Batch support ─────────────────────────────────────────────

    def begin_batch(self, description: str = "Batch",
                    defer_signal: bool = False) -> None:
        """Start accumulating commands into a single undo step.

        While a batch is open, execute() runs each command immediately
        but defers pushing to the undo stack until commit_batch().
        If *defer_signal* is True, zone_changed is NOT emitted per
        command — only once when the batch is committed.
        """
        self._batch = []
        self._batch_desc = description
        self._batch_defer_signal = defer_signal

    def commit_batch(self) -> None:
        """Close the current batch and push it as one undo entry."""
        if self._batch is None:
            return
        cmds = self._batch
        deferred = self._batch_defer_signal
        self._batch = None
        self._batch_defer_signal = False
        if not cmds:
            return
        if len(cmds) == 1:
            self._undo_stack.append(cmds[0])
        else:
            self._undo_stack.append(BatchCmd(cmds, self._batch_desc))
        self._redo_stack.clear()
        if deferred:
            self.zone_changed.emit()

    def cancel_batch(self) -> None:
        """Cancel and undo all commands in the open batch."""
        if self._batch is None:
            return
        for cmd in reversed(self._batch):
            cmd.undo(self._zone)
        self._batch = None
        self.zone_changed.emit()

    # ── Execute / Undo / Redo ─────────────────────────────────────

    def execute(self, cmd: Command) -> None:
        """Execute a command and push it onto the undo stack."""
        cmd.execute(self._zone)
        if self._batch is not None:
            self._batch.append(cmd)
            if not self._batch_defer_signal:
                self.zone_changed.emit()
        else:
            self._undo_stack.append(cmd)
            self._redo_stack.clear()
            self.zone_changed.emit()

    def undo(self) -> None:
        if not self._undo_stack:
            return
        cmd = self._undo_stack.pop()
        cmd.undo(self._zone)
        self._redo_stack.append(cmd)
        self.zone_changed.emit()

    def redo(self) -> None:
        if not self._redo_stack:
            return
        cmd = self._redo_stack.pop()
        cmd.execute(self._zone)
        self._undo_stack.append(cmd)
        self.zone_changed.emit()

    @property
    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo_stack)
