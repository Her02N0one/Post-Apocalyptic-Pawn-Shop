"""editor/commands/segment_cmds.py — Segment tool command definitions + handlers.

Phase 0: wraps existing segment methods.

Commands
~~~~~~~~
* ``SegmentSplit``  — split the aimed face at crosshair Y (LMB)
* ``SegmentMerge``  — remove nearest segment boundary (RMB)
* ``SegmentPaint``  — paint the aimed segment (MMB)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from editor.commands.base import Command, CommandBus, suppress_and_detect


# ── Command definitions ───────────────────────────────────────────

@dataclass(frozen=True)
class SegmentSplit(Command):
    """Split the aimed face at the crosshair Y."""
    pass


@dataclass(frozen=True)
class SegmentMerge(Command):
    """Remove the nearest segment boundary to the crosshair Y."""
    pass


@dataclass(frozen=True)
class SegmentPaint(Command):
    """Paint the aimed segment with the current texture."""
    pass


# ── Handler factories ─────────────────────────────────────────────

def _make_segment_split_handler(editor: Any):
    def handle(cmd: SegmentSplit) -> bool:
        return suppress_and_detect(editor, editor._seg_split)
    return handle


def _make_segment_merge_handler(editor: Any):
    def handle(cmd: SegmentMerge) -> bool:
        return suppress_and_detect(editor, editor._seg_merge)
    return handle


def _make_segment_paint_handler(editor: Any):
    def handle(cmd: SegmentPaint) -> bool:
        return suppress_and_detect(editor, editor._seg_paint)
    return handle


# ── Bulk registration ─────────────────────────────────────────────

def register_segment_handlers(bus: CommandBus, editor: Any) -> None:
    """Register all segment command handlers on *bus*."""
    bus.register(SegmentSplit, _make_segment_split_handler(editor))
    bus.register(SegmentMerge, _make_segment_merge_handler(editor))
    bus.register(SegmentPaint, _make_segment_paint_handler(editor))
