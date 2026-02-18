"""core/events.py — Typed event bus.

Events are dataclass instances.  Handlers are registered by event type.
No more magic strings — a typo in the event class name is a NameError.

    from core.events import EventBus

    @dataclass
    class DamageEvent:
        target: int
        amount: float
        source: int | None = None

    bus = EventBus()
    bus.subscribe(DamageEvent, handle_damage)
    bus.emit(DamageEvent(target=1, amount=10.0))

The bus also supports one-shot listeners (auto-unsubscribe after first call)
and ``emit_immediate()`` which calls handlers synchronously.  The default
``emit()`` queues events and ``flush()`` delivers them — call ``flush()``
once per frame so handlers run at a predictable point in the loop.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Callable, TypeVar

E = TypeVar("E")


class EventBus:
    """Typed publish/subscribe event bus."""

    def __init__(self) -> None:
        self._handlers: dict[type, list[Callable]] = defaultdict(list)
        self._once: dict[type, list[Callable]] = defaultdict(list)
        self._queue: list[Any] = []

    # ── Subscribe ─────────────────────────────────────────────────

    def subscribe(self, event_type: type[E], handler: Callable[[E], None]) -> None:
        """Register a handler for *event_type*.  Called on every emit."""
        self._handlers[event_type].append(handler)

    def subscribe_once(self, event_type: type[E], handler: Callable[[E], None]) -> None:
        """Register a one-shot handler — auto-removed after first call."""
        self._once[event_type].append(handler)

    def unsubscribe(self, event_type: type[E], handler: Callable[[E], None]) -> None:
        """Remove a previously registered handler."""
        handlers = self._handlers.get(event_type)
        if handlers and handler in handlers:
            handlers.remove(handler)
        once = self._once.get(event_type)
        if once and handler in once:
            once.remove(handler)

    # ── Emit ──────────────────────────────────────────────────────

    def emit(self, event: Any) -> None:
        """Queue an event for delivery on the next ``flush()``."""
        self._queue.append(event)

    def emit_immediate(self, event: Any) -> None:
        """Deliver an event to all handlers *right now* (synchronous)."""
        self._deliver(event)

    def flush(self) -> None:
        """Deliver all queued events.  Call once per frame."""
        # Snapshot the queue so handlers that emit don't infinite-loop
        pending = self._queue
        self._queue = []
        for event in pending:
            self._deliver(event)

    # ── Internal ──────────────────────────────────────────────────

    def _deliver(self, event: Any) -> None:
        """Call all handlers for *event*'s type."""
        et = type(event)
        for h in self._handlers.get(et, []):
            try:
                h(event)
            except Exception as exc:
                print(f"[EVENTS] Handler {h!r} raised {exc!r}")
        once_list = self._once.pop(et, [])
        for h in once_list:
            try:
                h(event)
            except Exception as exc:
                print(f"[EVENTS] Once-handler {h!r} raised {exc!r}")

    def clear(self) -> None:
        """Remove all handlers and queued events."""
        self._handlers.clear()
        self._once.clear()
        self._queue.clear()

    @property
    def pending(self) -> int:
        """Number of events waiting in the queue."""
        return len(self._queue)


# ═════════════════════════════════════════════════════════════════════
#  Common game events
# ═════════════════════════════════════════════════════════════════════

@dataclass
class EntityDied:
    """Fired when an entity's health reaches zero."""
    entity: int
    killer: int | None = None


@dataclass
class DamageDealt:
    """Fired after damage is applied."""
    target: int
    amount: float
    source: int | None = None


@dataclass
class ZoneTransition:
    """Fired when an entity should move to another zone."""
    entity: int
    target_zone: str
    target_x: float
    target_y: float


@dataclass
class ItemPickedUp:
    """Fired when an entity picks up an item."""
    entity: int
    item_name: str
    quantity: int = 1


@dataclass
class InteractionEvent:
    """Fired when the player interacts with a nearby entity."""
    player: int
    target: int
