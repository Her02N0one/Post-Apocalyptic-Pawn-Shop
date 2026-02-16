"""tests/test_events.py — EventBus tests."""

import pytest
from dataclasses import dataclass
from core.events import (
    EventBus, DamageDealt, EntityDied, InteractionEvent,
    ZoneTransition, ItemPickedUp,
)


class TestSubscribeEmit:
    def test_emit_queues(self):
        bus = EventBus()
        bus.emit(DamageDealt(target=1, amount=10.0))
        assert bus.pending == 1

    def test_flush_delivers(self):
        bus = EventBus()
        received = []
        bus.subscribe(DamageDealt, lambda e: received.append(e))
        bus.emit(DamageDealt(target=1, amount=5.0))
        bus.flush()
        assert len(received) == 1
        assert received[0].amount == 5.0

    def test_emit_immediate(self):
        bus = EventBus()
        received = []
        bus.subscribe(EntityDied, lambda e: received.append(e.entity))
        bus.emit_immediate(EntityDied(entity=42))
        assert received == [42]

    def test_subscribe_once(self):
        bus = EventBus()
        results = []
        bus.subscribe_once(DamageDealt, lambda e: results.append(e.amount))
        bus.emit_immediate(DamageDealt(target=1, amount=1.0))
        bus.emit_immediate(DamageDealt(target=1, amount=2.0))
        assert results == [1.0]  # Only first call

    def test_unsubscribe(self):
        bus = EventBus()
        results = []
        handler = lambda e: results.append(e)
        bus.subscribe(DamageDealt, handler)
        bus.unsubscribe(DamageDealt, handler)
        bus.emit_immediate(DamageDealt(target=1, amount=1.0))
        assert results == []


class TestTypeSafety:
    def test_different_types_independent(self):
        bus = EventBus()
        damage_count = []
        death_count = []
        bus.subscribe(DamageDealt, lambda e: damage_count.append(1))
        bus.subscribe(EntityDied, lambda e: death_count.append(1))
        bus.emit_immediate(DamageDealt(target=1, amount=10.0))
        assert len(damage_count) == 1
        assert len(death_count) == 0

    def test_custom_event_type(self):
        @dataclass
        class MyEvent:
            value: int
        bus = EventBus()
        received = []
        bus.subscribe(MyEvent, lambda e: received.append(e.value))
        bus.emit_immediate(MyEvent(value=99))
        assert received == [99]


class TestClear:
    def test_clear_removes_all(self):
        bus = EventBus()
        bus.subscribe(DamageDealt, lambda e: None)
        bus.emit(DamageDealt(target=1, amount=1.0))
        bus.clear()
        assert bus.pending == 0

    def test_flush_after_clear_is_noop(self):
        bus = EventBus()
        results = []
        bus.subscribe(DamageDealt, lambda e: results.append(1))
        bus.emit(DamageDealt(target=1, amount=1.0))
        bus.clear()
        bus.flush()
        assert results == []


class TestGameEvents:
    def test_zone_transition(self):
        bus = EventBus()
        received = []
        bus.subscribe(ZoneTransition, lambda e: received.append(e.target_zone))
        bus.emit_immediate(ZoneTransition(entity=1, target_zone="ruins",
                                          target_x=5.0, target_y=3.0))
        assert received == ["ruins"]

    def test_item_picked_up(self):
        bus = EventBus()
        received = []
        bus.subscribe(ItemPickedUp, lambda e: received.append((e.item_name, e.quantity)))
        bus.emit_immediate(ItemPickedUp(entity=1, item_name="sword", quantity=1))
        assert received == [("sword", 1)]
