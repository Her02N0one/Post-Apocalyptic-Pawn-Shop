"""Tests for Phase 3 — PrismShape component + entity prism rendering bridge.

Covers:
- PrismShape component creation and field defaults
- Entity face texture registration into tile int map
- _collect_entity_prisms producing correct box_data layout
- Spawner creates PrismShape for prism-type entities
- face_to_box_index N↔S swap correctness
"""

from __future__ import annotations

import math
import unittest
from unittest.mock import patch

from components import PrismShape
from core.entity_defs import (
    EntityDef, face_to_box_index, entity_texture_keys,
    entity_registry, get_entity_def, reload_registry,
)
from core.tiles.registry import (
    register_extra_texture_keys, extra_texture_keys,
    total_texture_count, tile_str_to_int, _INT_MAP, _INT_REV,
    _EXTRA_KEYS, _rebuild_int_map, TILE_REGISTRY, rebuild_derived,
)


class TestPrismShapeComponent(unittest.TestCase):
    """PrismShape dataclass basics."""

    def test_default_values(self):
        p = PrismShape()
        self.assertEqual(p.width, 1.0)
        self.assertEqual(p.depth, 1.0)
        self.assertEqual(p.height, 1.0)
        self.assertEqual(p.elevation, 0.0)
        self.assertEqual(p.yaw, 0.0)
        self.assertEqual(p.textures, {})
        self.assertFalse(p.movable)

    def test_custom_values(self):
        p = PrismShape(
            width=0.8, depth=0.5, height=1.2,
            elevation=0.1, yaw=1.57,
            textures={"north": "vend_front", "south": "vend_back"},
            movable=True,
        )
        self.assertAlmostEqual(p.width, 0.8)
        self.assertAlmostEqual(p.depth, 0.5)
        self.assertAlmostEqual(p.height, 1.2)
        self.assertAlmostEqual(p.elevation, 0.1)
        self.assertAlmostEqual(p.yaw, 1.57)
        self.assertEqual(p.textures["north"], "vend_front")
        self.assertTrue(p.movable)

    def test_not_persisted(self):
        """PrismShape should NOT be persisted (rebuilt on load)."""
        self.assertFalse(getattr(PrismShape, "_persist", False))


class TestFaceToBoxIndex(unittest.TestCase):
    """face_to_box_index N↔S swap helper."""

    def test_north_maps_to_bx_tex_s(self):
        # BX_TEX_S is offset 8
        self.assertEqual(face_to_box_index("north"), 8)

    def test_south_maps_to_bx_tex_n(self):
        # BX_TEX_N is offset 7
        self.assertEqual(face_to_box_index("south"), 7)

    def test_east_west_top_bottom(self):
        self.assertEqual(face_to_box_index("east"), 9)
        self.assertEqual(face_to_box_index("west"), 10)
        self.assertEqual(face_to_box_index("top"), 11)
        self.assertEqual(face_to_box_index("bottom"), 12)

    def test_unknown_face_raises(self):
        with self.assertRaises(KeyError):
            face_to_box_index("front")


class TestExtraTextureRegistration(unittest.TestCase):
    """register_extra_texture_keys extends the int map."""

    def setUp(self):
        # Save original state
        self._orig_map = dict(_INT_MAP)
        self._orig_rev = dict(_INT_REV)
        self._orig_extra = list(_EXTRA_KEYS)

    def tearDown(self):
        # Restore original state
        _INT_MAP.clear()
        _INT_MAP.update(self._orig_map)
        _INT_REV.clear()
        _INT_REV.update(self._orig_rev)
        _EXTRA_KEYS.clear()
        _EXTRA_KEYS.extend(self._orig_extra)

    def test_registers_new_keys(self):
        old_count = len(_INT_MAP)
        register_extra_texture_keys(["test_tex_a", "test_tex_b"])
        self.assertEqual(len(_INT_MAP), old_count + 2)
        # Both should be resolvable
        a_id = tile_str_to_int("test_tex_a")
        b_id = tile_str_to_int("test_tex_b")
        self.assertGreater(a_id, 0)
        self.assertGreater(b_id, 0)
        self.assertNotEqual(a_id, b_id)

    def test_idempotent_registration(self):
        register_extra_texture_keys(["test_tex_c"])
        count_after_first = len(_INT_MAP)
        register_extra_texture_keys(["test_tex_c"])  # duplicate
        self.assertEqual(len(_INT_MAP), count_after_first)

    def test_empty_string_skipped(self):
        old_count = len(_INT_MAP)
        register_extra_texture_keys(["", "test_tex_d"])
        self.assertEqual(len(_INT_MAP), old_count + 1)

    def test_extra_texture_keys_returns_registered(self):
        register_extra_texture_keys(["test_tex_e"])
        self.assertIn("test_tex_e", extra_texture_keys())

    def test_total_count_includes_extras(self):
        old_total = total_texture_count()
        register_extra_texture_keys(["test_tex_f"])
        self.assertEqual(total_texture_count(), old_total + 1)


class TestEntityTextureKeys(unittest.TestCase):
    """entity_texture_keys() collects face texture keys from registry."""

    def test_returns_unique_nonempty_list(self):
        keys = entity_texture_keys()
        self.assertIsInstance(keys, list)
        self.assertTrue(len(keys) > 0, "expected at least one texture key")
        self.assertEqual(len(keys), len(set(keys)), "duplicate texture keys")

    def test_no_empty_keys(self):
        keys = entity_texture_keys()
        for k in keys:
            self.assertTrue(k, "empty texture key found")


class TestSpawnerPrismShape(unittest.TestCase):
    """Spawner creates PrismShape for prism-type entity defs."""

    def test_prism_entity_gets_prism_shape(self):
        """A descriptor for a prism-type entity should produce PrismShape."""
        from core.ecs import World
        from systems.spawner import spawn_from_descriptor

        # Find a prism entity in the registry (if any exist)
        reg = entity_registry()
        prism_types = [k for k, edef in reg.items()
                       if edef.render_type == "prism"]
        if not prism_types:
            self.skipTest("No prism entity types in registry yet")

        type_id = prism_types[0]
        edef = get_entity_def(type_id)
        w = World()
        desc = {
            "id": "test_prism_1",
            "type": type_id,
            "x": 5.0, "y": 5.0,
            "angle": 1.57,
            "overrides": {},
        }
        eid = spawn_from_descriptor(w, desc, "test_zone")
        self.assertTrue(w.has(eid, PrismShape))
        prism = w.get(eid, PrismShape)
        self.assertAlmostEqual(prism.width, edef.width)
        self.assertAlmostEqual(prism.depth, edef.depth)
        self.assertAlmostEqual(prism.height, edef.height)
        self.assertAlmostEqual(prism.yaw, 1.57)

    def test_billboard_entity_no_prism_shape(self):
        """A billboard entity should NOT get a PrismShape component."""
        from core.ecs import World
        from systems.spawner import spawn_from_descriptor

        reg = entity_registry()
        billboard_types = [k for k, edef in reg.items()
                           if edef.render_type == "billboard"]
        if not billboard_types:
            self.skipTest("No billboard entity types in registry")

        type_id = billboard_types[0]
        w = World()
        desc = {
            "id": "test_bb_1",
            "type": type_id,
            "x": 5.0, "y": 5.0,
            "overrides": {},
        }
        eid = spawn_from_descriptor(w, desc, "test_zone")
        self.assertFalse(w.has(eid, PrismShape))


class TestCollectEntityPrisms(unittest.TestCase):
    """_collect_entity_prisms produces correct box_data layout."""

    def _make_zone_stub(self, entities, width=10, height=10):
        """Create a minimal zone-like object."""
        class ZoneStub:
            pass
        z = ZoneStub()
        z.width = width
        z.height = height
        z.entities = entities
        z.boxes = []
        z.floor_heights = [[0.0] * width for _ in range(height)]
        return z

    def test_non_prism_entities_skipped(self):
        """Billboard entities produce no box_data."""
        from engine.ray_renderer import RayRenderer

        reg = entity_registry()
        billboard_types = [k for k, edef in reg.items()
                           if edef.render_type == "billboard"]
        if not billboard_types:
            self.skipTest("No billboard entity types in registry")

        zone = self._make_zone_stub([
            {"type": billboard_types[0], "x": 3.0, "y": 3.0, "angle": 0.0},
        ])
        # _collect_entity_prisms is a method on RayRenderer, but we can
        # call it as an unbound method passing zone
        data = RayRenderer._collect_entity_prisms(None, zone)
        self.assertEqual(len(data), 0)

    def test_prism_entity_produces_14_doubles(self):
        """A prism entity emits exactly 14 doubles (BX_STRIDE)."""
        from engine.ray_renderer import RayRenderer

        reg = entity_registry()
        prism_types = [k for k, edef in reg.items()
                       if edef.render_type == "prism"]
        if not prism_types:
            self.skipTest("No prism entity types in registry")

        type_id = prism_types[0]
        edef = get_entity_def(type_id)
        zone = self._make_zone_stub([
            {"type": type_id, "x": 5.0, "y": 5.0, "angle": 0.5, "overrides": {}},
        ])
        data = RayRenderer._collect_entity_prisms(None, zone)
        self.assertEqual(len(data), 14)
        # Check position
        self.assertAlmostEqual(data[0], 5.0)  # x
        self.assertAlmostEqual(data[1], 5.0)  # y
        # Check geometry from entity def
        self.assertAlmostEqual(data[3], edef.width)  # w
        self.assertAlmostEqual(data[4], edef.height)  # h
        self.assertAlmostEqual(data[5], edef.depth)   # d
        self.assertAlmostEqual(data[6], 0.5)  # yaw

    def test_floor_height_offset(self):
        """Prism elevation includes floor height at entity cell."""
        from engine.ray_renderer import RayRenderer

        reg = entity_registry()
        prism_types = [k for k, edef in reg.items()
                       if edef.render_type == "prism"]
        if not prism_types:
            self.skipTest("No prism entity types in registry")

        type_id = prism_types[0]
        edef = get_entity_def(type_id)
        zone = self._make_zone_stub([
            {"type": type_id, "x": 3.0, "y": 4.0, "angle": 0.0, "overrides": {}},
        ])
        # Set floor height at cell (3, 4)
        zone.floor_heights[4][3] = 0.5
        data = RayRenderer._collect_entity_prisms(None, zone)
        # BX_Z = floor_height + elevation
        expected_z = 0.5 + edef.elevation
        self.assertAlmostEqual(data[2], expected_z)


if __name__ == "__main__":
    unittest.main()
