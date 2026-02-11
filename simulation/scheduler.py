"""simulation/scheduler.py — Event-driven world scheduler.

The core loop for off-screen simulation.  Each entity posts their next
meaningful state change to a priority queue ordered by game time.
Between events the entity costs zero CPU.

    scheduler = WorldScheduler()
    scheduler.post(game_time=350.0, eid=12, event_type="ARRIVE_NODE",
                   data={"node": "warehouse"})
    ...
    scheduler.tick(world, current_game_time=355.0)
"""

from __future__ import annotations
import heapq
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(order=True)
class ScheduledEvent:
    """A single event in the world scheduler priority queue.

    Ordered by ``time`` so the heap gives us earliest-first.
    """
    time: float
    # heapq tiebreaker (insertion order) — avoids comparing event_type
    _seq: int = field(compare=True, repr=False)
    eid: int = field(compare=False, default=0)
    event_type: str = field(compare=False, default="")
    data: dict[str, Any] = field(compare=False, default_factory=dict)
    cancelled: bool = field(compare=False, default=False)


class WorldScheduler:
    """Priority-queue event scheduler for the off-screen world simulation.

    Stored as a world resource on the ECS World.
    """

    def __init__(self) -> None:
        self._queue: list[ScheduledEvent] = []
        self._seq: int = 0
        # Dispatcher: event_type → handler function
        self._handlers: dict[str, Callable] = {}
        # Per-entity event tracking for cancellation
        self._entity_events: dict[int, list[ScheduledEvent]] = {}
        # Stats
        self.events_processed: int = 0

    # ── Posting events ───────────────────────────────────────────────

    def post(self, time: float, eid: int, event_type: str,
             data: dict[str, Any] | None = None) -> ScheduledEvent:
        """Schedule an event at ``time`` game-minutes."""
        self._seq += 1
        evt = ScheduledEvent(
            time=time,
            _seq=self._seq,
            eid=eid,
            event_type=event_type,
            data=data or {},
        )
        heapq.heappush(self._queue, evt)
        self._entity_events.setdefault(eid, []).append(evt)
        return evt

    def post_delta(self, current_time: float, delta: float,
                   eid: int, event_type: str,
                   data: dict[str, Any] | None = None) -> ScheduledEvent:
        """Post an event ``delta`` game-minutes from ``current_time``."""
        return self.post(current_time + delta, eid, event_type, data)

    # ── Cancellation ─────────────────────────────────────────────────

    def cancel_entity(self, eid: int) -> int:
        """Cancel all pending events for an entity. Returns count cancelled."""
        events = self._entity_events.pop(eid, [])
        count = 0
        for evt in events:
            if not evt.cancelled:
                evt.cancelled = True
                count += 1
        return count

    def cancel_entity_type(self, eid: int, event_type: str) -> int:
        """Cancel events of a specific type for an entity."""
        events = self._entity_events.get(eid, [])
        count = 0
        for evt in events:
            if not evt.cancelled and evt.event_type == event_type:
                evt.cancelled = True
                count += 1
        return count

    # ── Handler registration ─────────────────────────────────────────

    def register_handler(self, event_type: str,
                         handler: Callable) -> None:
        """Register a handler for an event type.

        Handler signature: ``handler(world, eid, event_type, data, scheduler, game_time)``
        """
        self._handlers[event_type] = handler

    # ── Tick ─────────────────────────────────────────────────────────

    def peek_time(self) -> float:
        """Return the time of the next event, or inf if empty."""
        while self._queue and self._queue[0].cancelled:
            heapq.heappop(self._queue)
        if self._queue:
            return self._queue[0].time
        return float("inf")

    def tick(self, world: Any, current_game_time: float,
             is_high_lod: Callable[[Any, int], bool] | None = None) -> int:
        """Process all events up to ``current_game_time``.

        ``is_high_lod`` is a callback that returns True if the entity
        is currently high-LOD (player nearby → real-time brain handles
        them).  Such events are skipped.

        Returns the number of events processed.
        """
        count = 0

        while self._queue:
            # Skip cancelled events
            if self._queue[0].cancelled:
                heapq.heappop(self._queue)
                continue
            if self._queue[0].time > current_game_time:
                break

            evt = heapq.heappop(self._queue)
            if evt.cancelled:
                continue

            # Skip if entity is now high-LOD
            if is_high_lod and is_high_lod(world, evt.eid):
                continue

            # Skip if entity is dead
            if not world.alive(evt.eid):
                continue

            # Dispatch
            handler = self._handlers.get(evt.event_type)
            if handler:
                handler(world, evt.eid, evt.event_type, evt.data,
                        self, current_game_time)
                count += 1

            # Clean up entity event tracking
            ent_events = self._entity_events.get(evt.eid)
            if ent_events:
                try:
                    ent_events.remove(evt)
                except ValueError:
                    pass

        self.events_processed += count
        return count

    # ── Queries ──────────────────────────────────────────────────────

    def pending_count(self) -> int:
        """Number of non-cancelled events in the queue."""
        return sum(1 for e in self._queue if not e.cancelled)

    def entity_pending(self, eid: int) -> list[ScheduledEvent]:
        """Return non-cancelled pending events for an entity."""
        return [e for e in self._entity_events.get(eid, [])
                if not e.cancelled]

    def has_pending(self, eid: int, event_type: str | None = None) -> bool:
        """Check if entity has any pending events (optionally filtered)."""
        for e in self._entity_events.get(eid, []):
            if e.cancelled:
                continue
            if event_type is None or e.event_type == event_type:
                return True
        return False

    # ── Serialization ────────────────────────────────────────────────

    def to_list(self) -> list[dict]:
        """Serialize pending events for save files."""
        return [
            {
                "time": e.time,
                "eid": e.eid,
                "event_type": e.event_type,
                "data": e.data,
            }
            for e in self._queue
            if not e.cancelled
        ]

    def load_list(self, events: list[dict]) -> None:
        """Restore events from a save file."""
        for edata in events:
            self.post(
                time=edata["time"],
                eid=edata["eid"],
                event_type=edata["event_type"],
                data=edata.get("data", {}),
            )

    # ── Debug ────────────────────────────────────────────────────────

    def debug_dump(self, limit: int = 20) -> list[str]:
        """Return a human-readable list of the next N events."""
        events = sorted(
            (e for e in self._queue if not e.cancelled),
            key=lambda e: (e.time, e._seq),
        )[:limit]
        return [
            f"{e.time:.1f}  eid={e.eid}  {e.event_type}  {e.data}"
            for e in events
        ]
