"""tests/test_typed_objects.py — Tests for _DictBridge mixin and typed zone objects.

Covers:
  - _DictBridge dict-protocol compliance (getitem, setitem, get, contains,
    setdefault, keys, values, items, iter, len, dict() conversion)
  - Quad, Box, Curve, RenderPortal: round-trip from_dict / to_dict, legacy
    format handling
  - EntityDescriptor: extra-dict merging, legacy prefab/position formats,
    pop, setdefault on extra keys
  - serialize_objects helper for mixed typed/dict lists
"""

from __future__ import annotations

import pytest

from core.zones.objects import (
    Box,
    Curve,
    EntityDescriptor,
    Quad,
    RenderPortal,
    serialize_objects,
)


# ── _DictBridge basic protocol (tested via Quad) ─────────────────


class TestDictBridgeProtocol:
    """Verify dict-protocol operations on a _DictBridge subclass."""

    def test_getitem(self):
        q = Quad(uid=7, x=1.5, z=2.5, texture="wood")
        assert q["uid"] == 7
        assert q["x"] == 1.5
        assert q["texture"] == "wood"

    def test_getitem_missing_raises(self):
        q = Quad()
        with pytest.raises(KeyError):
            q["nonexistent"]

    def test_setitem(self):
        q = Quad()
        q["x"] = 3.14
        assert q.x == 3.14
        assert q["x"] == 3.14

    def test_setitem_unknown_raises(self):
        q = Quad()
        with pytest.raises(KeyError):
            q["bad_key"] = 42

    def test_get_existing(self):
        q = Quad(texture="stone")
        assert q.get("texture") == "stone"

    def test_get_missing_returns_default(self):
        q = Quad()
        assert q.get("nonexistent") is None
        assert q.get("nonexistent", 99) == 99

    def test_contains(self):
        q = Quad()
        assert "uid" in q
        assert "x" in q
        assert "texture" in q
        assert "nonexistent" not in q
        assert 42 not in q  # non-string

    def test_setdefault_existing(self):
        q = Quad(texture="metal")
        val = q.setdefault("texture", "fallback")
        assert val == "metal"
        assert q["texture"] == "metal"  # unchanged

    def test_setdefault_unknown_raises(self):
        q = Quad()
        with pytest.raises(KeyError):
            q.setdefault("bad_key", 42)

    def test_keys(self):
        q = Quad()
        k = q.keys()
        assert "uid" in k
        assert "x" in k
        assert "z" in k
        assert "texture" in k

    def test_values(self):
        q = Quad(uid=5, x=1.0)
        vals = q.values()
        assert 5 in vals
        assert 1.0 in vals

    def test_items(self):
        q = Quad(uid=3, texture="rust")
        items = q.items()
        assert ("uid", 3) in items
        assert ("texture", "rust") in items

    def test_iter(self):
        q = Quad()
        keys_from_iter = list(q)
        assert keys_from_iter == q.keys()

    def test_len(self):
        q = Quad()
        # Quad has 11 fields
        assert len(q) == len(q.keys())
        assert len(q) > 0

    def test_dict_conversion(self):
        q = Quad(uid=10, x=2.0, z=3.0, texture="brick")
        d = dict(q)
        assert isinstance(d, dict)
        assert d["uid"] == 10
        assert d["x"] == 2.0
        assert d["texture"] == "brick"

    def test_to_dict_matches_dict_builtin(self):
        q = Quad(uid=1, x=5.0, z=6.0, angle=90.0)
        assert q.to_dict() == dict(q)


# ── Quad ──────────────────────────────────────────────────────────


class TestQuad:
    def test_from_dict_roundtrip(self):
        d = {"uid": 42, "x": 1.5, "z": 3.5, "texture": "wood",
             "angle": 45.0, "width": 2.0, "height": 3.0,
             "collision": True, "two_sided": False, "base_y": 0.5}
        q = Quad.from_dict(d)
        assert q.uid == 42
        assert q.x == 1.5
        assert q.z == 3.5
        assert q.texture == "wood"
        rt = q.to_dict()
        for k, v in d.items():
            assert rt[k] == v

    def test_from_dict_legacy_cell_pos(self):
        d = {"uid": 1, "cell": [3, 5], "pos": [0.5, 0.5], "texture": "old"}
        q = Quad.from_dict(d)
        # x = cell[1] + pos[0] = 5.5, z = cell[0] + pos[1] = 3.5
        assert q.x == 5.5
        assert q.z == 3.5

    def test_defaults(self):
        q = Quad()
        assert q.uid == 0
        assert q.texture == "brick_wall"
        assert q.two_sided is True
        assert q.collision is False


# ── Box ───────────────────────────────────────────────────────────


class TestBox:
    def test_from_dict_roundtrip(self):
        d = {"uid": 5, "x": 1.0, "y": 2.0, "z": 3.0,
             "w": 4.0, "h": 5.0, "d": 6.0, "yaw": 90.0,
             "textures": {"top": "wood", "side": "brick"},
             "collision": True}
        b = Box.from_dict(d)
        assert b.uid == 5
        assert b.textures == {"top": "wood", "side": "brick"}
        rt = b.to_dict()
        assert rt["textures"] == d["textures"]
        assert rt["collision"] is True

    def test_defaults(self):
        b = Box()
        assert b.w == 1.0
        assert b.textures == {}

    def test_dict_protocol(self):
        b = Box(uid=10, w=2.0)
        assert b["uid"] == 10
        assert b.get("w") == 2.0
        assert "textures" in b


# ── Curve ─────────────────────────────────────────────────────────


class TestCurve:
    def test_from_dict_roundtrip(self):
        d = {"uid": 9, "cx": 5.0, "cy": 6.0, "radius": 3.0,
             "angle_start": 0.0, "angle_end": 180.0,
             "height_scale": 2.0, "base_y": 1.0,
             "texture": "concrete", "flags": 1}
        c = Curve.from_dict(d)
        assert c.radius == 3.0
        assert c.flags == 1
        rt = c.to_dict()
        for k, v in d.items():
            assert rt[k] == v

    def test_defaults(self):
        c = Curve()
        assert c.radius == 1.0
        assert c.angle_end == 90.0


# ── RenderPortal ──────────────────────────────────────────────────


class TestRenderPortal:
    def test_from_dict_roundtrip(self):
        d = {"uid": 20, "cell": [2, 3], "face": 1,
             "dest_x": 10.0, "dest_y": 11.0, "angle_offset": 90.0}
        p = RenderPortal.from_dict(d)
        assert p.cell == [2, 3]
        assert p.face == 1
        rt = p.to_dict()
        assert rt["dest_x"] == 10.0


# ── EntityDescriptor ─────────────────────────────────────────────


class TestEntityDescriptor:
    """EntityDescriptor has extra-dict merging on top of _DictBridge."""

    def test_basic_fields(self):
        e = EntityDescriptor(uid=1, type="npc", x=3.0, y=4.0)
        assert e["uid"] == 1
        assert e["type"] == "npc"
        assert e["x"] == 3.0

    def test_extra_transparent_read(self):
        e = EntityDescriptor(extra={"sprite": "guard.png", "hp": 100})
        assert e["sprite"] == "guard.png"
        assert e.get("hp") == 100
        assert "sprite" in e

    def test_extra_transparent_write(self):
        e = EntityDescriptor()
        e["sprite"] = "merchant.png"
        assert e.extra["sprite"] == "merchant.png"
        assert e["sprite"] == "merchant.png"

    def test_extra_key_not_in_dataclass_fields(self):
        """Writes to unknown keys go to extra, not the dataclass."""
        e = EntityDescriptor()
        e["custom_prop"] = 42
        assert "custom_prop" in e
        assert e["custom_prop"] == 42
        assert "custom_prop" in e.extra

    def test_getitem_missing_raises(self):
        e = EntityDescriptor()
        with pytest.raises(KeyError):
            e["totally_absent"]

    def test_get_missing_default(self):
        e = EntityDescriptor()
        assert e.get("absent") is None
        assert e.get("absent", "fallback") == "fallback"

    def test_contains_base_and_extra(self):
        e = EntityDescriptor(extra={"ai": "patrol"})
        assert "uid" in e
        assert "type" in e
        assert "ai" in e
        assert "extra" not in e  # "extra" itself is hidden
        assert "missing" not in e

    def test_setdefault_base_field(self):
        e = EntityDescriptor(state="alert")
        val = e.setdefault("state", "idle")
        assert val == "alert"

    def test_setdefault_extra_absent(self):
        e = EntityDescriptor()
        val = e.setdefault("faction", "neutral")
        assert val == "neutral"
        assert e.extra["faction"] == "neutral"

    def test_setdefault_extra_present(self):
        e = EntityDescriptor(extra={"faction": "hostile"})
        val = e.setdefault("faction", "neutral")
        assert val == "hostile"

    def test_pop_extra_key(self):
        e = EntityDescriptor(extra={"tmp": "value"})
        val = e.pop("tmp")
        assert val == "value"
        assert "tmp" not in e

    def test_pop_missing_with_default(self):
        e = EntityDescriptor()
        assert e.pop("absent", None) is None

    def test_pop_missing_raises(self):
        e = EntityDescriptor()
        with pytest.raises(KeyError):
            e.pop("absent")

    def test_keys_include_extra(self):
        e = EntityDescriptor(extra={"sprite": "x.png"})
        k = e.keys()
        assert "uid" in k
        assert "type" in k
        assert "sprite" in k
        assert "extra" not in k

    def test_items_include_extra(self):
        e = EntityDescriptor(uid=5, extra={"sprite": "y.png"})
        items = dict(e.items())
        assert items["uid"] == 5
        assert items["sprite"] == "y.png"

    def test_len_includes_extra(self):
        e = EntityDescriptor()
        base_len = len(e)
        e["new_key"] = True
        assert len(e) == base_len + 1

    def test_iter_includes_extra(self):
        e = EntityDescriptor(extra={"ai": "wander"})
        all_keys = list(e)
        assert "uid" in all_keys
        assert "ai" in all_keys
        assert "extra" not in all_keys

    def test_dict_conversion_flattens_extra(self):
        e = EntityDescriptor(uid=3, type="npc", extra={"sprite": "s.png"})
        d = dict(e)
        assert d["uid"] == 3
        assert d["sprite"] == "s.png"
        assert "extra" not in d

    def test_to_dict_matches_dict_builtin(self):
        e = EntityDescriptor(uid=7, type="beast", x=1.0, y=2.0,
                             extra={"ai": "patrol"})
        assert e.to_dict() == dict(e)

    def test_from_dict_standard_format(self):
        d = {"uid": 10, "id": "guard_01", "type": "npc_guard",
             "x": 5.0, "y": 6.0, "angle": 90.0, "state": "idle",
             "overrides": {"hp": 200}}
        e = EntityDescriptor.from_dict(d)
        assert e.uid == 10
        assert e.type == "npc_guard"
        assert e.x == 5.0
        assert e.overrides == {"hp": 200}

    def test_from_dict_legacy_prefab_format(self):
        """Legacy entities with 'prefab' key should map to 'type'."""
        d = {"uid": 1, "prefab": "npc_trader", "x": 3.0, "y": 4.0}
        e = EntityDescriptor.from_dict(d)
        assert e.type == "npc_trader"

    def test_from_dict_legacy_position_dict(self):
        """Legacy entities with 'position' dict should flatten to x/y."""
        d = {"uid": 2, "type": "beast", "position": {"x": 7.0, "y": 8.0}}
        e = EntityDescriptor.from_dict(d)
        assert e.x == 7.0
        assert e.y == 8.0
        # position is preserved in extra for legacy compat
        assert "position" in e

    def test_from_dict_extra_keys_preserved(self):
        d = {"uid": 3, "type": "npc", "x": 0.0, "y": 0.0,
             "sprite": "guard.png", "tile_entity": True, "facing": "north"}
        e = EntityDescriptor.from_dict(d)
        assert e["sprite"] == "guard.png"
        assert e["tile_entity"] is True
        assert e["facing"] == "north"

    def test_roundtrip_preserves_all_keys(self):
        original = {"uid": 50, "id": "test", "type": "mob", "x": 1.0,
                     "y": 2.0, "angle": 45.0, "state": "alert",
                     "overrides": {"speed": 2}, "sprite": "mob.png",
                     "custom": 42}
        e = EntityDescriptor.from_dict(original)
        rt = e.to_dict()
        assert rt["uid"] == 50
        assert rt["type"] == "mob"
        assert rt["sprite"] == "mob.png"
        assert rt["custom"] == 42
        assert rt["overrides"] == {"speed": 2}


# ── serialize_objects ─────────────────────────────────────────────


class TestSerializeObjects:
    def test_typed_objects_become_dicts(self):
        objs = [
            Quad(uid=1, x=1.0, z=2.0),
            Box(uid=2, w=3.0),
        ]
        result = serialize_objects(objs)
        assert all(isinstance(d, dict) for d in result)
        assert result[0]["uid"] == 1
        assert result[1]["w"] == 3.0

    def test_plain_dicts_pass_through(self):
        objs = [{"uid": 5, "x": 1.0}]
        result = serialize_objects(objs)
        assert result[0]["uid"] == 5

    def test_mixed_list(self):
        objs = [
            Quad(uid=1),
            {"uid": 2, "x": 0.0},
            EntityDescriptor(uid=3, type="npc", extra={"sprite": "s.png"}),
        ]
        result = serialize_objects(objs)
        assert len(result) == 3
        assert all(isinstance(d, dict) for d in result)
        # EntityDescriptor extra should be flattened
        assert result[2]["sprite"] == "s.png"
        assert "extra" not in result[2]

    def test_empty_list(self):
        assert serialize_objects([]) == []
