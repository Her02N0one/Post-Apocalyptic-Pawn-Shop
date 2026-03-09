"""Tests for the Phase 0 Command Bus & Event Bus infrastructure.

These tests use lightweight stubs — no pygame / renderer / real zone
required.  They verify:

1. CommandBus dispatches to registered handlers
2. Undo is pushed before handler runs
3. BatchCommand groups under a single undo entry
4. EventBus pub/sub works
5. Handler return value controls dirty flag
6. Monkey-patch suppression of internal _push_undo works
7. Unregistered commands raise TypeError
"""

from __future__ import annotations

import pytest
from dataclasses import dataclass

from editor.commands.base import Command, BatchCommand, CommandBus, EventBus
from editor.commands.events import StateChanged, ViewDirtied


# ── Stubs ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class FakeRaise(Command):
    cell: tuple[int, int]


@dataclass(frozen=True)
class FakeLower(Command):
    cell: tuple[int, int]


@dataclass(frozen=True)
class FakeNoOp(Command):
    """A command whose handler returns False (nothing changed)."""
    pass


class StubEditor:
    """Mimics the interface that CommandBus uses on Zone3DEditor."""

    def __init__(self):
        self.dirty = False
        self._undo_stack: list[str] = []
        self._redo_stack: list[str] = []
        self._push_undo_calls = 0
        self._ensure_calls = 0
        self.calls: list[str] = []

    def _push_undo(self):
        self._push_undo_calls += 1
        self._undo_stack.append("snapshot")
        self._redo_stack.clear()

    def _ensure_face_textures(self):
        self._ensure_calls += 1

    def _undo(self):
        if self._undo_stack:
            self._redo_stack.append(self._undo_stack.pop())

    def _redo(self):
        if self._redo_stack:
            self._undo_stack.append(self._redo_stack.pop())


# ── EventBus tests ─────────────────────────────────────────────────

class TestEventBus:
    def test_subscribe_and_emit(self):
        eb = EventBus()
        received = []
        eb.subscribe(StateChanged, received.append)
        cmd = FakeRaise(cell=(0, 0))
        eb.emit(StateChanged(source_command=cmd))
        assert len(received) == 1
        assert received[0].source_command is cmd

    def test_unsubscribe(self):
        eb = EventBus()
        received = []
        cb = received.append
        eb.subscribe(StateChanged, cb)
        eb.unsubscribe(StateChanged, cb)
        eb.emit(StateChanged(source_command=FakeRaise(cell=(0, 0))))
        assert len(received) == 0

    def test_multiple_subscribers(self):
        eb = EventBus()
        a, b = [], []
        eb.subscribe(StateChanged, a.append)
        eb.subscribe(StateChanged, b.append)
        eb.emit(StateChanged(source_command=FakeRaise(cell=(0, 0))))
        assert len(a) == 1 and len(b) == 1

    def test_different_event_types(self):
        eb = EventBus()
        sc, vd = [], []
        eb.subscribe(StateChanged, sc.append)
        eb.subscribe(ViewDirtied, vd.append)
        eb.emit(StateChanged(source_command=FakeRaise(cell=(0, 0))))
        eb.emit(ViewDirtied())
        assert len(sc) == 1 and len(vd) == 1

    def test_emit_with_no_subscribers(self):
        """Emitting to no subscribers should not raise."""
        eb = EventBus()
        eb.emit(ViewDirtied())


# ── CommandBus tests ───────────────────────────────────────────────

class TestCommandBus:
    def _make_bus(self):
        ed = StubEditor()
        eb = EventBus()
        bus = CommandBus(ed, eb)
        return bus, ed, eb

    def test_register_and_execute(self):
        bus, ed, eb = self._make_bus()
        calls = []
        bus.register(FakeRaise, lambda cmd: (calls.append(cmd), True)[1])

        cmd = FakeRaise(cell=(3, 5))
        result = bus.execute(cmd)

        assert result is True
        assert len(calls) == 1
        assert calls[0] is cmd

    def test_undo_pushed_before_handler(self):
        bus, ed, eb = self._make_bus()
        undo_at_handler_time = []

        def handler(cmd):
            undo_at_handler_time.append(ed._push_undo_calls)
            return True

        bus.register(FakeRaise, handler)
        bus.execute(FakeRaise(cell=(0, 0)))

        # Undo was pushed before handler ran
        assert undo_at_handler_time[0] == 1
        assert len(ed._undo_stack) == 1

    def test_ensure_face_textures_called(self):
        bus, ed, eb = self._make_bus()
        bus.register(FakeRaise, lambda cmd: True)
        bus.execute(FakeRaise(cell=(0, 0)))
        assert ed._ensure_calls == 1

    def test_dirty_set_on_change(self):
        bus, ed, eb = self._make_bus()
        bus.register(FakeRaise, lambda cmd: True)
        bus.execute(FakeRaise(cell=(0, 0)))
        assert ed.dirty is True

    def test_dirty_not_set_on_no_change(self):
        bus, ed, eb = self._make_bus()
        bus.register(FakeNoOp, lambda cmd: False)
        bus.execute(FakeNoOp())
        assert ed.dirty is False

    def test_state_changed_emitted(self):
        """StateChanged is always emitted regardless of changed flag."""
        bus, ed, eb = self._make_bus()
        events = []
        eb.subscribe(StateChanged, events.append)
        bus.register(FakeRaise, lambda cmd: True)
        bus.execute(FakeRaise(cell=(0, 0)))
        assert len(events) == 1

    def test_state_changed_emitted_on_no_change(self):
        bus, ed, eb = self._make_bus()
        events = []
        eb.subscribe(StateChanged, events.append)
        bus.register(FakeNoOp, lambda cmd: False)
        bus.execute(FakeNoOp())
        assert len(events) == 1

    def test_unregistered_command_raises(self):
        bus, ed, eb = self._make_bus()
        with pytest.raises(TypeError, match="No handler"):
            bus.execute(FakeRaise(cell=(0, 0)))

    def test_undo_redo_delegation(self):
        bus, ed, eb = self._make_bus()
        bus.register(FakeRaise, lambda cmd: True)
        bus.execute(FakeRaise(cell=(0, 0)))
        assert len(ed._undo_stack) == 1

        bus.undo()
        assert len(ed._undo_stack) == 0
        assert len(ed._redo_stack) == 1

        bus.redo()
        assert len(ed._undo_stack) == 1
        assert len(ed._redo_stack) == 0


# ── BatchCommand tests ─────────────────────────────────────────────

class TestBatchCommand:
    def _make_bus(self):
        ed = StubEditor()
        eb = EventBus()
        bus = CommandBus(ed, eb)
        return bus, ed, eb

    def test_batch_single_undo(self):
        """A batch of 3 commands should produce exactly 1 undo entry."""
        bus, ed, eb = self._make_bus()
        bus.register(FakeRaise, lambda cmd: True)
        batch = BatchCommand(children=(
            FakeRaise(cell=(0, 0)),
            FakeRaise(cell=(1, 1)),
            FakeRaise(cell=(2, 2)),
        ))
        bus.execute(batch)
        assert ed._push_undo_calls == 1
        assert len(ed._undo_stack) == 1

    def test_batch_all_handlers_called(self):
        bus, ed, eb = self._make_bus()
        called = []
        bus.register(FakeRaise, lambda cmd: (called.append(cmd.cell), True)[1])
        batch = BatchCommand(children=(
            FakeRaise(cell=(0, 0)),
            FakeRaise(cell=(1, 1)),
        ))
        bus.execute(batch)
        assert len(called) == 2
        assert called[0] == (0, 0) and called[1] == (1, 1)

    def test_batch_dirty_if_any_changed(self):
        bus, ed, eb = self._make_bus()
        counter = [0]

        def handler(cmd):
            counter[0] += 1
            return counter[0] == 2  # Only second call changes

        bus.register(FakeRaise, handler)
        batch = BatchCommand(children=(
            FakeRaise(cell=(0, 0)),
            FakeRaise(cell=(1, 1)),
        ))
        bus.execute(batch)
        assert ed.dirty is True

    def test_batch_not_dirty_if_none_changed(self):
        bus, ed, eb = self._make_bus()
        bus.register(FakeRaise, lambda cmd: False)
        batch = BatchCommand(children=(
            FakeRaise(cell=(0, 0)),
            FakeRaise(cell=(1, 1)),
        ))
        bus.execute(batch)
        assert ed.dirty is False

    def test_empty_batch_returns_false(self):
        bus, ed, eb = self._make_bus()
        batch = BatchCommand(children=())
        result = bus.execute(batch)
        assert result is False
        assert ed._push_undo_calls == 0

    def test_batch_mixed_types(self):
        """Batch can contain different command types."""
        bus, ed, eb = self._make_bus()
        r_calls, l_calls = [], []
        bus.register(FakeRaise, lambda cmd: (r_calls.append(1), True)[1])
        bus.register(FakeLower, lambda cmd: (l_calls.append(1), True)[1])
        batch = BatchCommand(children=(
            FakeRaise(cell=(0, 0)),
            FakeLower(cell=(1, 1)),
        ))
        bus.execute(batch)
        assert len(r_calls) == 1 and len(l_calls) == 1


# ── Monkey-patch undo suppression ──────────────────────────────────

class TestUndoSuppression:
    """Verify that handlers using the _push_undo monkey-patch pattern
    correctly suppress internal undo pushes."""

    def test_suppression_pattern(self):
        """Simulate the pattern used by paint handlers."""
        class FakeEd:
            def __init__(self):
                self.pushes = 0
                self.dirty = False

            def _push_undo(self):
                self.pushes += 1

            def _ensure_face_textures(self):
                pass

            def _undo(self):
                pass

            def _redo(self):
                pass

            def inner_method(self):
                """A method that calls _push_undo internally."""
                self._push_undo()
                return True

        ed = FakeEd()
        eb = EventBus()
        bus = CommandBus(ed, eb)

        def handler(cmd):
            _orig = ed._push_undo
            ed._push_undo = lambda: None
            try:
                return ed.inner_method()
            finally:
                ed._push_undo = _orig

        bus.register(FakeNoOp, handler)
        bus.execute(FakeNoOp())

        # Bus pushed once, inner method's push was suppressed
        assert ed.pushes == 1

    def test_suppression_restores_on_error(self):
        """If the inner method raises, _push_undo is still restored."""
        class FakeEd:
            def __init__(self):
                self.pushes = 0
                self.dirty = False
                self._undo_stack = []
                self._redo_stack = []

            def _push_undo(self):
                self.pushes += 1
                self._undo_stack.append("s")
                self._redo_stack.clear()

            def _ensure_face_textures(self):
                pass

            def _undo(self):
                pass

            def _redo(self):
                pass

            def exploding_method(self):
                self._push_undo()
                raise RuntimeError("boom")

        ed = FakeEd()
        eb = EventBus()
        bus = CommandBus(ed, eb)

        def handler(cmd):
            _orig = ed._push_undo
            ed._push_undo = lambda: None
            try:
                return ed.exploding_method()
            finally:
                ed._push_undo = _orig

        bus.register(FakeNoOp, handler)

        with pytest.raises(RuntimeError, match="boom"):
            bus.execute(FakeNoOp())

        # _push_undo should be restored despite the error
        ed._push_undo()
        assert ed.pushes == 2  # 1 from bus + 1 from restore verification
