"""editor/commands/stamp_cmds.py — Stamp tool command definitions + handlers.

Phase 0: wraps existing stamp methods.

Commands
~~~~~~~~
* ``StampApply``  — apply current preset onto aimed cell (LMB)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from editor.commands.base import Command, CommandBus, suppress_and_detect


# ── Command definitions ───────────────────────────────────────────

@dataclass(frozen=True)
class StampApply(Command):
    """Stamp the current preset onto the aimed cell."""
    pass


# ── Handler factories ─────────────────────────────────────────────

def _make_stamp_apply_handler(editor: Any):
    def handle(cmd: StampApply) -> bool:
        return suppress_and_detect(editor, editor._stamp_apply)
    return handle


# ── Bulk registration ─────────────────────────────────────────────

def register_stamp_handlers(bus: CommandBus, editor: Any) -> None:
    """Register all stamp command handlers on *bus*."""
    bus.register(StampApply, _make_stamp_apply_handler(editor))
