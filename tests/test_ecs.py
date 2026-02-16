"""tests/test_ecs.py — Core ECS tests."""

import pytest
from core.ecs import World, Component
from components import Position, Velocity, Health, Player, Sprite, Identity, Facing, Collider
from core.types import Direction, EntityKind


class TestComponent:
    def test_rejects_non_component(self):
        w = World()
        e = w.spawn()
        with pytest.raises(TypeError):
            w.add(e, "not a component")

    def test_rejects_plain_dict(self):
        w = World()
        e = w.spawn()
        with pytest.raises(TypeError):
            w.add(e, {"x": 1})

    def test_add_get(self):
        w = World()
        e = w.spawn()
        w.add(e, Position(x=3.0, y=4.0))
        pos = w.get(e, Position)
        assert pos is not None
        assert pos.x == 3.0
        assert pos.y == 4.0

    def test_get_missing_returns_none(self):
        w = World()
        e = w.spawn()
        assert w.get(e, Position) is None

    def test_has(self):
        w = World()
        e = w.spawn()
        w.add(e, Health())
        assert w.has(e, Health)
        assert not w.has(e, Position)

    def test_remove(self):
        w = World()
        e = w.spawn()
        w.add(e, Health())
        w.remove(e, Health)
        assert not w.has(e, Health)


class TestQuery:
    def test_single(self):
        w = World()
        e = w.spawn()
        w.add(e, Position(x=1.0, y=2.0))
        results = list(w.query(Position))
        assert len(results) == 1
        assert results[0][0] == e

    def test_two_components(self):
        w = World()
        e1 = w.spawn()
        w.add(e1, Position())
        w.add(e1, Velocity())

        e2 = w.spawn()
        w.add(e2, Position())  # No Velocity

        results = list(w.query(Position, Velocity))
        assert len(results) == 1
        assert results[0][0] == e1

    def test_query_one(self):
        w = World()
        e = w.spawn()
        w.add(e, Player())
        w.add(e, Position(x=5.0, y=5.0))
        result = w.query_one(Player, Position)
        assert result is not None
        assert result[0] == e

    def test_query_one_empty(self):
        w = World()
        assert w.query_one(Player) is None

    def test_dead_entities_excluded(self):
        w = World()
        e = w.spawn()
        w.add(e, Position())
        w.kill(e)
        assert list(w.query(Position)) == []


class TestZoneIndex:
    def test_auto_index_on_add(self):
        w = World()
        e = w.spawn()
        w.add(e, Position(x=1.0, y=1.0, zone="test"))
        assert e in w.zone_entities("test")

    def test_set_zone(self):
        w = World()
        e = w.spawn()
        w.add(e, Position(x=1.0, y=1.0, zone="a"))
        w.set_zone(e, "b")
        assert e not in w.zone_entities("a")
        assert e in w.zone_entities("b")
        assert w.get(e, Position).zone == "b"

    def test_zone_entities_excludes_dead(self):
        w = World()
        e = w.spawn()
        w.add(e, Position(zone="x"))
        w.kill(e)
        assert e not in w.zone_entities("x")


class TestResources:
    def test_set_get(self):
        from components import Camera
        w = World()
        w.resources.set(Camera(x=10.0))
        cam = w.resources.get(Camera)
        assert cam.x == 10.0

    def test_missing_raises(self):
        from components import Camera
        w = World()
        with pytest.raises(KeyError):
            w.resources.get(Camera)

    def test_try_get(self):
        from components import Camera
        w = World()
        assert w.resources.try_get(Camera) is None
        w.resources.set(Camera())
        assert w.resources.try_get(Camera) is not None


class TestPurge:
    def test_purge_clears_dead(self):
        w = World()
        e = w.spawn()
        w.add(e, Position())
        w.add(e, Health())
        w.kill(e)
        w.purge()
        assert list(w.query(Position)) == []
        assert list(w.query(Health)) == []

    def test_purge_clears_zone_index(self):
        w = World()
        e = w.spawn()
        w.add(e, Position(zone="z"))
        w.kill(e)
        w.purge()
        assert len(w.zone_entities("z")) == 0


class TestPersistFlags:
    def test_position_persists(self):
        assert Position._persist is True

    def test_health_persists(self):
        assert Health._persist is True

    def test_velocity_transient(self):
        assert Velocity._persist is False

    def test_sprite_transient(self):
        assert Sprite._persist is False

    def test_player_transient(self):
        assert Player._persist is False
