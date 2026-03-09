"""editor/commands — Command bus, event bus, and command definitions.

Phase 0 of the editor refactor: every user-initiated state mutation
is represented as a first-class Command object, dispatched through a
central CommandBus that manages undo/redo and emits events.

Usage::

    from editor.commands import CommandBus, EventBus
    from editor.commands.sculpt_cmds import SculptFloorRaise

    bus = CommandBus(editor, event_bus)
    bus.execute(SculptFloorRaise(cell=(3, 5)))
"""

from editor.commands.base import (  # noqa: F401
    Command,
    BatchCommand,
    CommandBus,
    EventBus,
)
from editor.commands.events import (  # noqa: F401
    StateChanged,
    SelectionChanged,
    ToolChanged,
    ViewDirtied,
)
