"""editor/commands/erase_cmds.py — Eraser tool command definitions + handlers.

Phase 1: handlers own the mutation logic directly.  No delegation to
editor mixin methods, no ``suppress_undo`` wrappers.  Each handler
reads zone/editor state through the closure-captured *editor* reference
and mutates ``editor.zone`` grids in place.

Commands
~~~~~~~~
* ``EraseCell``          — full cell reset (LMB on eraser)
* ``EraseHeight``        — reset height only (RMB on eraser)
* ``EraseTexturesOnly``  — clear textures, keep geometry (Shift+LMB)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from editor.commands.base import Command, CommandBus
from editor.zone_ops import reset_cell, clear_cell_textures, DEFAULT_FLOOR, SKY_HEIGHT


# ── Command definitions ───────────────────────────────────────────

@dataclass(frozen=True)
class EraseCell(Command):
    """Full cell reset (flat ground, open sky, clear all)."""
    pass


@dataclass(frozen=True)
class EraseHeight(Command):
    """Reset height only (keep tile/textures)."""
    pass


@dataclass(frozen=True)
class EraseTexturesOnly(Command):
    """Clear textures, keep geometry."""
    pass


# ── Handler factories ─────────────────────────────────────────────

LAYER_NONE = -1000.0


def _make_erase_cell_handler(editor: Any):
    def handle(cmd: EraseCell) -> bool:
        hit = editor.aimed
        if not hit:
            return False
        reset_cell(editor.zone, hit.row, hit.col, editor._open_tile)
        return True
    return handle


def _make_erase_height_handler(editor: Any):
    def handle(cmd: EraseHeight) -> bool:
        hit = editor.aimed
        if not hit:
            return False
        zone = editor.zone
        r, c = hit.row, hit.col

        if hit.part == "ceiling":
            zone.ceil_heights[r][c] = SKY_HEIGHT
            if zone.upper_wall_height and len(zone.upper_wall_height) > r:
                zone.upper_wall_height[r][c] = 0.0
            # Clear orphaned ceiling step segments
            if zone.ceil_step_segments and len(zone.ceil_step_segments) > r:
                zone.ceil_step_segments[r][c] = [[], [], [], []]
        elif hit.part == "ceiling2":
            c2 = getattr(zone, 'ceil2_heights', None)
            if c2 and len(c2) > r:
                c2[r][c] = LAYER_NONE
            uwh2 = getattr(zone, 'upper_wall_height2', None)
            if uwh2 and len(uwh2) > r:
                uwh2[r][c] = 0.0
            ct2 = getattr(zone, 'ceil2_textures', None)
            if ct2 and len(ct2) > r:
                ct2[r][c] = ""
        elif hit.part == "floor2":
            f2 = getattr(zone, 'floor2_heights', None)
            if f2 and len(f2) > r:
                f2[r][c] = LAYER_NONE
            ft2 = getattr(zone, 'floor2_textures', None)
            if ft2 and len(ft2) > r:
                ft2[r][c] = ""
        else:
            zone.floor_heights[r][c] = DEFAULT_FLOOR
            # Clear orphaned floor step segments
            if zone.floor_step_segments and len(zone.floor_step_segments) > r:
                zone.floor_step_segments[r][c] = [[], [], [], []]

        return True
    return handle


def _make_erase_textures_handler(editor: Any):
    def handle(cmd: EraseTexturesOnly) -> bool:
        hit = editor.aimed
        if not hit:
            return False
        clear_cell_textures(editor.zone, hit.row, hit.col)
        return True
    return handle


# ── Bulk registration ─────────────────────────────────────────────

def register_erase_handlers(bus: CommandBus, editor: Any) -> None:
    """Register all erase command handlers on *bus*."""
    bus.register(EraseCell,         _make_erase_cell_handler(editor))
    bus.register(EraseHeight,       _make_erase_height_handler(editor))
    bus.register(EraseTexturesOnly, _make_erase_textures_handler(editor))
