"""Test that every Command subclass has a handler registered on the bus.

This catches registration gaps mechanically.  Instead of constructing a
real Zone3DEditor (which needs pygame + GL), we use the same StubEditor
from test_command_bus and call every ``register_*_handlers`` factory.
If a Command class is defined but never registered, this test fails.
"""

from __future__ import annotations

import inspect
import importlib
import pkgutil
from dataclasses import dataclass

import pytest

from editor.commands.base import Command, BatchCommand, CommandBus, EventBus

# ── Stub editor (only needs attributes that register_* factories touch) ──

class StubEditor:
    """Minimal stub satisfying handler-factory attribute access."""
    def __init__(self):
        self.dirty = False
        self._undo_stack = []
        self._redo_stack = []
        self.aimed = None
        self.zone = None
        self.current_texture = ""
        self.selection = type("sel", (), {"cells": set()})()
        self.tool = "sculpt"
        self.mode = "sculpt"

    def _push_undo(self):
        pass

    def _ensure_face_textures(self):
        pass

    def _undo(self):
        pass

    def _redo(self):
        pass

    def _has_selection(self):
        return False

    def __getattr__(self, name):
        # Swallow any method call that handler factories capture closures of.
        # This lets register_*_handlers complete without AttributeError.
        return lambda *a, **kw: None


# ── Discover all Command subclasses across the commands package ──

_CMD_MODULES = [
    "editor.commands.sculpt_cmds",
    "editor.commands.paint_cmds",
    "editor.commands.l2_cmds",
    "editor.commands.erase_cmds",
    "editor.commands.misc_cmds",
    "editor.commands.object_cmds",
    "editor.commands.segment_cmds",
    "editor.commands.select_cmds",
    "editor.commands.stamp_cmds",
]


def _collect_command_classes() -> list[tuple[str, type]]:
    """Return [(module_name, cls), ...] for every concrete Command subclass."""
    results = []
    for mod_name in _CMD_MODULES:
        mod = importlib.import_module(mod_name)
        for name, obj in inspect.getmembers(mod, inspect.isclass):
            if (
                issubclass(obj, Command)
                and obj is not Command
                and obj is not BatchCommand
                and obj.__module__ == mod_name
            ):
                results.append((mod_name, obj))
    return results


ALL_COMMANDS = _collect_command_classes()

# ── Discover all register_* functions ──

_REGISTER_FUNCTIONS = [
    "editor.commands.sculpt_cmds.register_sculpt_handlers",
    "editor.commands.paint_cmds.register_paint_handlers",
    "editor.commands.l2_cmds.register_l2_handlers",
    "editor.commands.erase_cmds.register_erase_handlers",
    "editor.commands.misc_cmds.register_misc_handlers",
    "editor.commands.object_cmds.register_object_handlers",
    "editor.commands.segment_cmds.register_segment_handlers",
    "editor.commands.select_cmds.register_select_handlers",
    "editor.commands.stamp_cmds.register_stamp_handlers",
]


def _build_bus_with_all_handlers() -> CommandBus:
    """Create a CommandBus with every handler registered."""
    stub = StubEditor()
    event_bus = EventBus()
    bus = CommandBus(stub, event_bus)

    for func_path in _REGISTER_FUNCTIONS:
        mod_path, func_name = func_path.rsplit(".", 1)
        mod = importlib.import_module(mod_path)
        register_fn = getattr(mod, func_name)
        register_fn(bus, stub)

    return bus


# ── Tests ──

class TestHandlerRegistration:
    """Every concrete Command subclass must have a handler in the bus."""

    @pytest.fixture(scope="class")
    def bus(self) -> CommandBus:
        return _build_bus_with_all_handlers()

    @pytest.mark.parametrize(
        "mod_name,cmd_cls",
        [(m, c) for m, c in ALL_COMMANDS],
        ids=[f"{c.__name__}" for _, c in ALL_COMMANDS],
    )
    def test_handler_registered(self, bus, mod_name, cmd_cls):
        """Verify *cmd_cls* has a handler in the bus registry."""
        assert cmd_cls in bus._handlers, (
            f"{cmd_cls.__name__} (from {mod_name}) has no registered handler"
        )


class TestCommandCount:
    """Sanity check: we discovered a reasonable number of commands."""

    def test_at_least_80_commands(self):
        # As of Phase 0 completion there are ~88 command types.
        # This guard catches accidental import failures.
        assert len(ALL_COMMANDS) >= 80, (
            f"Only found {len(ALL_COMMANDS)} commands — "
            f"expected ≥80. Check _CMD_MODULES list."
        )

    def test_all_modules_contributed(self):
        """Every module in _CMD_MODULES defines at least one command."""
        mods_seen = {m for m, _ in ALL_COMMANDS}
        for mod_name in _CMD_MODULES:
            assert mod_name in mods_seen, (
                f"{mod_name} contributed zero Command classes"
            )
