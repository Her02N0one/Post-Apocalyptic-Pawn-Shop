"""tests/test_save.py — Save/load round-trip tests."""

import pytest
from core.ecs import World
from core.save import save_game, load_game, restore_entity, has_save, delete_save
from components import (
    Position, Velocity, Health, Inventory, Player, Sprite,
    Identity, Facing, GameClock,
)
from core.types import Direction, EntityKind

TEST_SLOT = 98  # Use a dedicated slot so tests don't interfere


@pytest.fixture(autouse=True)
def cleanup():
    """Delete test save before and after each test."""
    delete_save(TEST_SLOT)
    yield
    delete_save(TEST_SLOT)


class TestSaveLoad:
    def test_round_trip_position(self):
        w = World()
        e = w.spawn()
        w.add(e, Position(x=3.5, y=7.2, zone="ruins"))
        save_game(w, "ruins", slot=TEST_SLOT)
        data = load_game(TEST_SLOT)
        assert data is not None
        assert data["entities"][0]["Position"]["x"] == 3.5
        assert data["entities"][0]["Position"]["zone"] == "ruins"

    def test_round_trip_health(self):
        w = World()
        e = w.spawn()
        w.add(e, Position())
        w.add(e, Health(current=42.0, maximum=80.0))
        save_game(w, "test", slot=TEST_SLOT)
        data = load_game(TEST_SLOT)
        hp = data["entities"][0]["Health"]
        assert hp["current"] == 42.0
        assert hp["maximum"] == 80.0

    def test_round_trip_inventory(self):
        w = World()
        e = w.spawn()
        w.add(e, Position())
        w.add(e, Inventory(items={"arrow": 20, "potion": 3}))
        save_game(w, "test", slot=TEST_SLOT)
        data = load_game(TEST_SLOT)
        inv = data["entities"][0]["Inventory"]["items"]
        assert inv == {"arrow": 20, "potion": 3}


class TestPersistFiltering:
    def test_transient_components_excluded(self):
        w = World()
        e = w.spawn()
        w.add(e, Position())         # persist
        w.add(e, Health())           # persist
        w.add(e, Velocity())         # transient
        w.add(e, Sprite())           # transient
        w.add(e, Player())           # transient
        w.add(e, Identity())         # transient
        w.add(e, Facing())           # transient
        save_game(w, "test", slot=TEST_SLOT)
        data = load_game(TEST_SLOT)
        ent = data["entities"][0]
        assert "Position" in ent
        assert "Health" in ent
        assert "Velocity" not in ent
        assert "Sprite" not in ent
        assert "Player" not in ent

    def test_entity_without_persist_not_saved(self):
        w = World()
        e = w.spawn()
        w.add(e, Sprite())       # transient only
        w.add(e, Velocity())     # transient only
        save_game(w, "test", slot=TEST_SLOT)
        data = load_game(TEST_SLOT)
        assert len(data["entities"]) == 0


class TestRestore:
    def test_restore_creates_entity(self):
        entry = {
            "eid": 1,
            "Position": {"x": 10.0, "y": 20.0, "zone": "town"},
            "Health": {"current": 50.0, "maximum": 100.0},
        }
        w = World()
        eid = restore_entity(w, entry)
        pos = w.get(eid, Position)
        hp = w.get(eid, Health)
        assert pos is not None
        assert pos.x == 10.0
        assert pos.zone == "town"
        assert hp is not None
        assert hp.current == 50.0


class TestClockPersistence:
    def test_clock_saved(self):
        w = World()
        w.resources.set(GameClock(time=123.456))
        e = w.spawn()
        w.add(e, Position())
        save_game(w, "test", slot=TEST_SLOT)
        data = load_game(TEST_SLOT)
        assert abs(data["clock"] - 123.456) < 0.001

    def test_clock_zero_default(self):
        w = World()
        e = w.spawn()
        w.add(e, Position())
        save_game(w, "test", slot=TEST_SLOT)
        data = load_game(TEST_SLOT)
        assert data["clock"] == 0.0


class TestSlotManagement:
    def test_has_save(self):
        assert not has_save(TEST_SLOT)
        w = World()
        e = w.spawn()
        w.add(e, Position())
        save_game(w, "test", slot=TEST_SLOT)
        assert has_save(TEST_SLOT)

    def test_delete_save(self):
        w = World()
        e = w.spawn()
        w.add(e, Position())
        save_game(w, "test", slot=TEST_SLOT)
        delete_save(TEST_SLOT)
        assert not has_save(TEST_SLOT)

    def test_load_missing_returns_none(self):
        assert load_game(TEST_SLOT) is None
