"""tests/test_session.py — Session lifecycle tests."""

import pytest
from core.ecs import World
from core.session import Session
from core.save import delete_save
from components import (
    Position, Velocity, Sprite, Player, Facing, Identity,
    Health, Inventory, Collider, PrefabRef, Camera, GameClock,
)
from core.types import EntityKind

TEST_SLOT = 97  # Dedicated slot — won't collide with test_save.py's slot 98


@pytest.fixture(autouse=True)
def cleanup():
    """Delete test save before and after each test."""
    delete_save(TEST_SLOT)
    yield
    delete_save(TEST_SLOT)


class TestNewGame:
    def test_tiles_loaded(self):
        s = Session(World())
        s.new_game("playground")
        assert len(s.tiles) > 0
        assert s.map_h > 0
        assert s.map_w > 0

    def test_zone_name_set(self):
        s = Session(World())
        s.new_game("playground")
        assert s.zone_name == "playground"

    def test_visited_zones(self):
        s = Session(World())
        s.new_game("playground")
        assert "playground" in s.visited_zones

    def test_player_spawned(self):
        w = World()
        s = Session(w)
        s.new_game("playground")
        result = w.query_one(Player, Position)
        assert result is not None
        _, _, pos = result
        assert pos.zone == "playground"

    def test_player_has_all_components(self):
        w = World()
        s = Session(w)
        s.new_game("playground")
        result = w.query_one(Player, Position)
        assert result is not None
        eid = result[0]
        assert w.has(eid, Velocity)
        assert w.has(eid, Sprite)
        assert w.has(eid, Identity)
        assert w.has(eid, Health)
        assert w.has(eid, Collider)
        assert w.has(eid, Facing)
        assert w.has(eid, PrefabRef)

    def test_player_prefab_ref(self):
        w = World()
        s = Session(w)
        s.new_game("playground")
        result = w.query_one(Player, Position)
        eid = result[0]
        ref = w.get(eid, PrefabRef)
        assert ref is not None
        assert ref.uid == "player"
        assert ref.prefab == "player"

    def test_zone_entities_spawned(self):
        w = World()
        s = Session(w)
        s.new_game("playground")
        # playground.json has 5 dummy entities + the player = 6 total
        zone_ents = w.zone_entities("playground")
        assert len(zone_ents) >= 6

    def test_camera_resource_set(self):
        w = World()
        s = Session(w)
        s.new_game("playground")
        cam = w.resources.try_get(Camera)
        assert cam is not None

    def test_clock_resource_set(self):
        w = World()
        s = Session(w)
        s.new_game("playground")
        clock = w.resources.try_get(GameClock)
        assert clock is not None
        assert clock.time == 0.0


class TestSaveLoad:
    def test_save_creates_file(self):
        w = World()
        s = Session(w)
        s.new_game("playground")
        path = s.save(slot=TEST_SLOT)
        assert path.exists()

    def test_save_sets_status(self):
        w = World()
        s = Session(w)
        s.new_game("playground")
        s.save(slot=TEST_SLOT)
        assert "Saved" in s.status
        assert s.status_timer > 0

    def test_load_no_save_returns_false(self):
        w = World()
        s = Session(w)
        s.new_game("playground")
        assert s.load(slot=TEST_SLOT) is False
        assert "No save" in s.status

    def test_round_trip(self):
        """Save → load preserves player position."""
        w = World()
        s = Session(w)
        s.new_game("playground")

        # Move player
        result = w.query_one(Player, Position)
        _, _, pos = result
        pos.x, pos.y = 7.5, 3.2

        s.save(slot=TEST_SLOT)

        # Reset — start a fresh world for load
        w2 = World()
        s2 = Session(w2)
        s2.new_game("playground")  # need initial state before load

        assert s2.load(slot=TEST_SLOT) is True

        # Player should be at saved position
        result2 = w2.query_one(Player, Position)
        assert result2 is not None
        _, _, pos2 = result2
        assert abs(pos2.x - 7.5) < 0.01
        assert abs(pos2.y - 3.2) < 0.01

    def test_load_rebuilds_transients(self):
        """After load, transient components are rebuilt from prefabs."""
        w = World()
        s = Session(w)
        s.new_game("playground")
        s.save(slot=TEST_SLOT)

        # Fresh load
        w2 = World()
        s2 = Session(w2)
        s2.new_game("playground")
        s2.load(slot=TEST_SLOT)

        # Player should have transient components
        result = w2.query_one(Player, Position)
        assert result is not None
        eid = result[0]
        assert w2.has(eid, Sprite)
        assert w2.has(eid, Identity)
        assert w2.has(eid, Collider)
        assert w2.has(eid, Facing)
        assert w2.has(eid, Velocity)

    def test_load_restores_zone_name(self):
        w = World()
        s = Session(w)
        s.new_game("playground")
        s.save(slot=TEST_SLOT)

        w2 = World()
        s2 = Session(w2)
        s2.load(slot=TEST_SLOT)
        assert s2.zone_name == "playground"

    def test_load_restores_visited_zones(self):
        w = World()
        s = Session(w)
        s.new_game("playground")
        s.save(slot=TEST_SLOT)

        w2 = World()
        s2 = Session(w2)
        s2.load(slot=TEST_SLOT)
        assert "playground" in s2.visited_zones

    def test_load_restores_clock(self):
        w = World()
        s = Session(w)
        s.new_game("playground")
        clock = w.resources.get(GameClock)
        clock.time = 42.5
        s.save(slot=TEST_SLOT)

        w2 = World()
        s2 = Session(w2)
        s2.new_game("playground")
        s2.load(slot=TEST_SLOT)
        clock2 = w2.resources.try_get(GameClock)
        assert clock2 is not None
        assert abs(clock2.time - 42.5) < 0.01


class TestPrefabRef:
    def test_prefab_ref_persists(self):
        assert PrefabRef._persist is True

    def test_prefab_ref_saved(self):
        """PrefabRef should appear in save data."""
        from core.save import save_game, load_game
        w = World()
        e = w.spawn()
        w.add(e, Position())
        w.add(e, PrefabRef(uid="test_npc", prefab="dummy"))
        save_game(w, "test", slot=TEST_SLOT)
        data = load_game(TEST_SLOT)
        ent = data["entities"][0]
        assert "PrefabRef" in ent
        assert ent["PrefabRef"]["uid"] == "test_npc"
        assert ent["PrefabRef"]["prefab"] == "dummy"

    def test_visited_zones_in_save(self):
        """Save file should include visited_zones."""
        from core.save import save_game, load_game
        w = World()
        e = w.spawn()
        w.add(e, Position())
        save_game(w, "test", slot=TEST_SLOT,
                  visited_zones={"zone_a", "zone_b"})
        data = load_game(TEST_SLOT)
        assert "visited_zones" in data
        assert set(data["visited_zones"]) == {"zone_a", "zone_b"}


class TestFirstPersonFlag:
    """Zone.first_person propagates through Session."""

    def test_playground_no_first_person(self):
        s = Session(World())
        s.new_game("playground")
        assert s.first_person is False

    def test_pawn_shop_first_person(self):
        from core.zones import load_zone
        z = load_zone("pawn_shop")
        assert z.first_person is True

    def test_session_first_person_from_zone(self):
        """Session.first_person reflects loaded zone's flag."""
        s = Session(World())
        s.new_game("playground")
        assert s.first_person is False
        # Manually load an interior zone template
        s._load_zone_template("pawn_shop")
        assert s.first_person is True

    def test_interior_implies_first_person(self):
        """Zones with 'interior: true' auto-set first_person."""
        from core.zones import load_zone
        z = load_zone("pawn_shop")
        assert z.first_person is True

    def test_window_tile_is_solid(self):
        """Physics should treat TILE_WINDOW as solid."""
        from systems.physics import _hits_wall
        from core.constants import TILE_WINDOW, TILE_WOOD_FLOOR
        # 3×3 grid: floor except centre = window
        tiles = [
            [TILE_WOOD_FLOOR, TILE_WOOD_FLOOR, TILE_WOOD_FLOOR],
            [TILE_WOOD_FLOOR, TILE_WINDOW,     TILE_WOOD_FLOOR],
            [TILE_WOOD_FLOOR, TILE_WOOD_FLOOR, TILE_WOOD_FLOOR],
        ]
        assert _hits_wall(1.5, 1.5, 0.5, 0.5, 3, 3, tiles) is True
        assert _hits_wall(0.5, 0.5, 0.5, 0.5, 3, 3, tiles) is False


class TestPortals:
    """Session.check_portals teleports the player between zones."""

    def test_portal_changes_zone(self):
        """Walking onto a portal tile switches the zone."""
        w = World()
        s = Session(w)
        s.new_game("playground")
        assert s.zone_name == "playground"
        # Move player onto the house door tile (row=6, col=24)
        result = w.query_one(Player, Position)
        _, eid, pos = result[0], result[0], result[2]
        pos.x = 24.0
        pos.y = 6.0
        changed = s.check_portals()
        assert changed is True
        assert s.zone_name == "house_interior"
        assert s.first_person is True

    def test_portal_round_trip(self):
        """Can go into house_interior and come back."""
        w = World()
        s = Session(w)
        s.new_game("playground")
        result = w.query_one(Player, Position)
        _, _, pos = result
        # Enter house
        pos.x, pos.y = 24.0, 6.0
        s.check_portals()
        assert s.zone_name == "house_interior"
        # Exit house (portal at row=8, col=5)
        pos.x, pos.y = 5.0, 8.0
        s.check_portals()
        assert s.zone_name == "playground"

    def test_no_portal_no_change(self):
        """Standing on a non-portal tile does nothing."""
        w = World()
        s = Session(w)
        s.new_game("playground")
        result = w.query_one(Player, Position)
        _, _, pos = result
        pos.x, pos.y = 10.0, 10.0
        assert s.check_portals() is False
        assert s.zone_name == "playground"