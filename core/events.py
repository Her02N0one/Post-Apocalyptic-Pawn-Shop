"""core/events.py — Lightweight event bus.

Decouples systems that need to *signal* something from systems that
*react* to it.  The bus lives as an ECS resource::

    from core.events import EventBus
    bus = world.res(EventBus)
    bus.emit(EntityDied(eid=42, killer_eid=7))

Consumers subscribe with a callable::

    bus.subscribe("EntityDied", my_handler)

And the orchestrator drains once per frame::

    bus.drain()          # calls all handlers for pending events

Design rules:
  - Events are plain dataclasses — no behaviour.
  - ``emit()`` is O(1) (just appends).
  - ``drain()`` processes all queued events in FIFO order.
  - Handlers may emit new events; those are processed next drain.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable
from collections import defaultdict


# ═══════════════════════════════════════════════════════════════════
#  Event definitions
# ═══════════════════════════════════════════════════════════════════

@dataclass
class EntityDied:
    """An entity's HP dropped to zero."""
    eid: int
    killer_eid: int | None = None
    zone: str = ""


@dataclass
class FactionAlert:
    """Notify nearby allies that combat started."""
    group: str = ""
    x: float = 0.0
    y: float = 0.0
    zone: str = ""
    threat_eid: int | None = None


@dataclass
class AttackIntent:
    """An NPC wants to attack a target — lets combat system handle it."""
    attacker_eid: int = 0
    target_eid: int = 0
    attack_type: str = "melee"     # "melee" or "ranged"


@dataclass
class CrimeWitnessed:
    """A crime was observed by an NPC."""
    criminal_eid: int = 0
    witness_eid: int = 0
    crime_type: str = ""
    x: float = 0.0
    y: float = 0.0
    zone: str = ""


# ═══════════════════════════════════════════════════════════════════
#  Event Bus
# ═══════════════════════════════════════════════════════════════════

class EventBus:
    """Fire-and-forget event bus stored as an ECS resource."""

    def __init__(self):
        self._queue: list[Any] = []
        self._subs: dict[str, list[Callable]] = defaultdict(list)
        self._stats: dict[str, int] = defaultdict(int)

    # ── Public API ───────────────────────────────────────────────────

    def emit(self, event) -> None:
        """Queue an event for processing on next ``drain()``."""
        self._queue.append(event)

    def subscribe(self, event_type: str, handler: Callable) -> None:
        """Register *handler* to receive events of *event_type*.

        *event_type* is the class name, e.g. ``"EntityDied"``.
        """
        self._subs[event_type].append(handler)

    def drain(self) -> int:
        """Process all queued events.  Returns number processed.

        Handlers may emit new events — those are processed in the
        same drain pass (breadth-first).
        """
        processed = 0
        safety = 1000  # prevent infinite loops
        while self._queue and safety > 0:
            batch = self._queue[:]
            self._queue.clear()
            for event in batch:
                name = type(event).__name__
                self._stats[name] += 1
                for handler in self._subs.get(name, []):
                    try:
                        handler(event)
                    except Exception as exc:
                        print(f"[EVENT] handler error for {name}: {exc}")
                        import traceback; traceback.print_exc()
                processed += len(batch)
            safety -= 1
        return processed

    def clear(self) -> None:
        """Discard all pending events."""
        self._queue.clear()

    def stats(self) -> dict[str, int]:
        """Return cumulative event counts by type."""
        return dict(self._stats)

    def pending_count(self) -> int:
        """Number of events waiting to be drained."""
        return len(self._queue)

    def __repr__(self) -> str:
        return f"EventBus(pending={len(self._queue)}, subs={len(self._subs)})"
