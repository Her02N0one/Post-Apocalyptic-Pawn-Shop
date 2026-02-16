"""tests/test_interaction.py — Interaction system tests."""

import pytest
from core.ecs import World
from core.events import InteractionEvent
from components import Position, Player, Facing, Identity
from core.types import Direction, EntityKind
from systems.interaction import nearest_interactable, try_interact, INTERACT_RANGE


def _make_player_world(px=5.0, py=5.0, facing=Direction.RIGHT):
    """Create a World with a player and return (world, player_eid)."""
    w = World()
    p = w.spawn()
    w.add(p, Position(x=px, y=py, zone="test"))
    w.add(p, Player(speed=6.0))
    w.add(p, Facing(direction=facing))
    return w, p


class TestNearestInteractable:
    def test_finds_npc_in_front(self):
        w, p = _make_player_world(facing=Direction.RIGHT)
        npc = w.spawn()
        w.add(npc, Position(x=6.0, y=5.0, zone="test"))
        w.add(npc, Identity(name="Bob"))
        result = nearest_interactable(w)
        assert result is not None
        assert result[0] == npc

    def test_prefers_entity_in_facing_direction(self):
        w, p = _make_player_world(facing=Direction.RIGHT)
        # NPC to the right (facing direction)
        right = w.spawn()
        w.add(right, Position(x=6.5, y=5.0, zone="test"))
        w.add(right, Identity(name="Right"))
        # NPC to the left (behind)
        left = w.spawn()
        w.add(left, Position(x=4.0, y=5.0, zone="test"))
        w.add(left, Identity(name="Left"))
        result = nearest_interactable(w)
        assert result is not None
        assert result[0] == right

    def test_nothing_in_range(self):
        w, p = _make_player_world()
        far = w.spawn()
        w.add(far, Position(x=50.0, y=50.0, zone="test"))
        w.add(far, Identity(name="Far"))
        assert nearest_interactable(w) is None

    def test_different_zone_ignored(self):
        w, p = _make_player_world()
        npc = w.spawn()
        w.add(npc, Position(x=6.0, y=5.0, zone="other_zone"))
        w.add(npc, Identity(name="Cross-zone"))
        assert nearest_interactable(w) is None

    def test_no_player_returns_none(self):
        w = World()
        npc = w.spawn()
        w.add(npc, Position(x=5.0, y=5.0, zone="test"))
        w.add(npc, Identity(name="Lonely"))
        assert nearest_interactable(w) is None

    def test_player_not_interactable_with_self(self):
        w, p = _make_player_world()
        # Only entity is the player — should find nothing
        w.add(p, Identity(name="Self"))
        assert nearest_interactable(w) is None


class TestTryInteract:
    def test_emits_event(self):
        w, p = _make_player_world()
        npc = w.spawn()
        w.add(npc, Position(x=6.0, y=5.0, zone="test"))
        w.add(npc, Identity(name="Bob"))

        received = []
        w.events.subscribe(InteractionEvent, lambda e: received.append(e))

        ok = try_interact(w, w.events)
        assert ok
        w.events.flush()
        assert len(received) == 1
        assert received[0].player == p
        assert received[0].target == npc

    def test_returns_false_when_nothing_nearby(self):
        w, p = _make_player_world()
        assert try_interact(w, w.events) is False

    def test_returns_false_when_no_player(self):
        w = World()
        assert try_interact(w, w.events) is False
