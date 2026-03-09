"""editor/commands/base.py — Command protocol, CommandBus, and EventBus.

Phase 0 architecture
~~~~~~~~~~~~~~~~~~~~
* **Command** — immutable value objects describing mutations.
* **BatchCommand** — groups multiple commands into one undo entry.
* **CommandBus** — dispatches commands to handlers, manages undo/redo,
  emits events.  During Phase 0 the bus wraps the existing snapshot-based
  undo system; Phase 1 replaces snapshots with inverse commands.
* **EventBus** — lightweight pub/sub for decoupled read-only notifications.

The bus is designed for incremental adoption: migrated tools dispatch
commands; unmigrated tools still call ``_push_undo()`` directly on the
editor.  Both paths share the same undo/redo stacks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, TYPE_CHECKING

from editor.commands.events import StateChanged, ViewDirtied

if TYPE_CHECKING:
    pass  # forward references only


# ── Handler helpers ───────────────────────────────────────────────
#
# Shared utilities for Phase 0 command handlers.  They manage the
# monkey-patch undo-suppression pattern and dirty-flag detection so
# that individual handler factories stay concise.

def suppress_undo(editor: Any, fn: Callable, *args: Any, **kw: Any) -> Any:
    """Call *fn* with ``editor._push_undo`` suppressed.

    Use for methods that **return bool** and call ``_push_undo``
    internally.  The bus already pushed undo before the handler ran.
    """
    _orig = editor._push_undo
    editor._push_undo = lambda: None
    try:
        return fn(*args, **kw)
    finally:
        editor._push_undo = _orig


def detect_change(editor: Any, fn: Callable, *args: Any, **kw: Any) -> bool:
    """Call void *fn* and return True if ``editor.dirty`` was set.

    Use for methods that don't return bool **and** don't call
    ``_push_undo`` (e.g. scroll ops with missing undo).
    """
    old = editor.dirty
    editor.dirty = False
    fn(*args, **kw)
    changed = editor.dirty
    editor.dirty = old
    return changed


def suppress_and_detect(editor: Any, fn: Callable, *args: Any, **kw: Any) -> bool:
    """Suppress ``_push_undo`` + detect dirty change for void methods.

    Combines :func:`suppress_undo` and :func:`detect_change` for void
    methods that call ``_push_undo`` internally.
    """
    old = editor.dirty
    editor.dirty = False
    _orig = editor._push_undo
    editor._push_undo = lambda: None
    try:
        fn(*args, **kw)
    finally:
        editor._push_undo = _orig
    changed = editor.dirty
    editor.dirty = old
    return changed


# ── Command base types ────────────────────────────────────────────

@dataclass(frozen=True)
class Command:
    """Base for all state-mutating operations.

    Commands are immutable value objects.  They carry *what* should
    change but contain no logic.  They are serialisable (for potential
    macro recording and replay).
    """
    pass


@dataclass(frozen=True)
class BatchCommand(Command):
    """Groups multiple commands into one undo entry."""
    children: tuple[Command, ...]


# ── EventBus ──────────────────────────────────────────────────────

class EventBus:
    """Lightweight publish/subscribe for read-only notifications.

    Subscribers must not mutate state inside their callbacks.
    """

    __slots__ = ("_subs",)

    def __init__(self) -> None:
        self._subs: dict[type, list[Callable]] = {}

    def subscribe(self, event_type: type, callback: Callable) -> None:
        """Register *callback* to receive events of *event_type*."""
        self._subs.setdefault(event_type, []).append(callback)

    def unsubscribe(self, event_type: type, callback: Callable) -> None:
        """Remove a previously registered callback."""
        lst = self._subs.get(event_type)
        if lst and callback in lst:
            lst.remove(callback)

    def emit(self, event: Any) -> None:
        """Dispatch *event* to all registered subscribers."""
        for cb in self._subs.get(type(event), ()):
            cb(event)


# ── CommandBus ────────────────────────────────────────────────────

class CommandBus:
    """Central dispatcher for all state-mutating operations.

    Phase 0 strategy
    ~~~~~~~~~~~~~~~~
    * Each ``execute()`` call wraps the existing snapshot-based undo:
      ``_push_undo()`` is called before the handler runs so the zone
      state prior to mutation is captured on the undo stack.
    * Handlers call existing ``_*_at()`` methods on the editor mixins
      **without** pushing undo themselves.
    * The bus emits :class:`StateChanged` after every successful mutation.
    * Unmigrated tools continue to call ``_push_undo()`` directly — the
      same stacks are shared, so ``undo()`` / ``redo()`` work uniformly.

    Phase 1 will replace snapshot undo with inverse commands returned
    by handlers.

    Parameters
    ----------
    editor : Zone3DEditor
        The editor instance whose zone state is mutated.
    event_bus : EventBus
        Bus for read-only notifications.
    """

    __slots__ = ("_editor", "_event_bus", "_handlers")

    def __init__(self, editor: Any, event_bus: EventBus) -> None:
        self._editor = editor
        self._event_bus = event_bus
        self._handlers: dict[type, Callable[..., bool]] = {}

    # ── Registration ──────────────────────────────────────────────

    def register(self, cmd_type: type, handler: Callable[..., bool]) -> None:
        """Register a handler for *cmd_type*.

        The handler signature is ``(Command) -> bool`` where the return
        value indicates whether the zone was actually changed.  Handlers
        must NOT call ``_push_undo()`` — the bus does that.
        """
        self._handlers[cmd_type] = handler

    # ── Execution ─────────────────────────────────────────────────

    def execute(self, cmd: Command) -> bool:
        """Execute *cmd*, push undo, and emit events.

        Returns True if the mutation changed anything.
        """
        if isinstance(cmd, BatchCommand):
            return self._execute_batch(cmd)

        handler = self._handlers.get(type(cmd))
        if handler is None:
            raise TypeError(
                f"No handler registered for {type(cmd).__name__}"
            )

        ed = self._editor
        ed._push_undo()
        ed._ensure_face_textures()
        changed = bool(handler(cmd))

        if changed:
            ed.dirty = True

        self._event_bus.emit(StateChanged(cmd))
        return changed

    def _execute_batch(self, batch: BatchCommand) -> bool:
        """Execute all children under a single undo snapshot."""
        if not batch.children:
            return False

        ed = self._editor
        ed._push_undo()
        ed._ensure_face_textures()

        any_changed = False
        for child in batch.children:
            handler = self._handlers.get(type(child))
            if handler is not None and handler(child):
                any_changed = True

        if any_changed:
            ed.dirty = True

        self._event_bus.emit(StateChanged(batch))
        return any_changed

    def execute_continuation(self, cmd: Command) -> bool:
        """Execute *cmd* without pushing undo (continuation of prior op).

        Used for operations that are part of a larger gesture (e.g.
        continuous paint while dragging).  The initial click already
        pushed an undo snapshot via :meth:`execute`.
        """
        if isinstance(cmd, BatchCommand):
            raise TypeError("BatchCommand not supported for continuations")

        handler = self._handlers.get(type(cmd))
        if handler is None:
            raise TypeError(
                f"No handler registered for {type(cmd).__name__}"
            )

        ed = self._editor
        ed._ensure_face_textures()
        changed = bool(handler(cmd))

        if changed:
            ed.dirty = True

        self._event_bus.emit(StateChanged(cmd))
        return changed

    # ── Undo / Redo (delegates to editor's snapshot system) ───────

    def undo(self) -> None:
        """Undo the last operation (snapshot-based in Phase 0)."""
        self._editor._undo()

    def redo(self) -> None:
        """Redo the last undone operation."""
        self._editor._redo()
