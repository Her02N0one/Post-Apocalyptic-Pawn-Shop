"""Tests for the RenderMode pipeline — spawn → component → pack.

Verifies that the RenderMode enum travels correctly from entity
descriptor through the spawner, into the Sprite component, and
down to the packed entity buffer consumed by the C renderer.
"""

from __future__ import annotations

import math
import struct
import unittest

from components import Position, Sprite
from core.ecs import World
from core.entity_defs import entity_registry, get_entity_def
from core.types import RenderMode
from systems.spawner import spawn_from_descriptor


# ── Helpers ──────────────────────────────────────────────────────


def _find_billboard_type() -> str | None:
    """Return the first non-directional billboard entity type, or None."""
    for k, edef in entity_registry().items():
        if edef.render_type == "billboard" and not edef.directional:
            return k
    return None


def _find_directional_type() -> str | None:
    """Return the first directional billboard entity type, or None."""
    for k, edef in entity_registry().items():
        if edef.render_type == "billboard" and edef.directional:
            return k
    return None


# ═════════════════════════════════════════════════════════════════
#  Spawn → Sprite.render_mode
# ═════════════════════════════════════════════════════════════════


class TestSpawnRenderMode(unittest.TestCase):
    """spawn_from_descriptor sets render_mode correctly."""

    def test_billboard_no_wall_face(self):
        """Billboard entity without wall_face → BILLBOARD."""
        type_id = _find_billboard_type()
        if type_id is None:
            self.skipTest("No non-directional billboard entity type")
        w = World()
        desc = {"id": "t1", "type": type_id,
                "x": 5.0, "y": 5.0, "overrides": {}}
        eid = spawn_from_descriptor(w, desc, "test_zone")
        spr = w.get(eid, Sprite)
        self.assertIsNotNone(spr)
        self.assertEqual(spr.render_mode, RenderMode.BILLBOARD)

    def test_directional_billboard(self):
        """Directional billboard → BILLBOARD_8WAY."""
        type_id = _find_directional_type()
        if type_id is None:
            self.skipTest("No directional billboard entity type")
        w = World()
        desc = {"id": "t2", "type": type_id,
                "x": 5.0, "y": 5.0, "overrides": {}}
        eid = spawn_from_descriptor(w, desc, "test_zone")
        spr = w.get(eid, Sprite)
        self.assertIsNotNone(spr)
        self.assertEqual(spr.render_mode, RenderMode.BILLBOARD_8WAY)

    def test_wall_face_sets_wall_anchored(self):
        """Billboard entity with wall_face → WALL_ANCHORED."""
        type_id = _find_billboard_type()
        if type_id is None:
            self.skipTest("No non-directional billboard entity type")
        w = World()
        desc = {"id": "t3", "type": type_id,
                "x": 5.0, "y": 5.0,
                "wall_height": 1.5, "wall_face": "north",
                "overrides": {}}
        eid = spawn_from_descriptor(w, desc, "test_zone")
        spr = w.get(eid, Sprite)
        self.assertIsNotNone(spr)
        self.assertEqual(spr.render_mode, RenderMode.WALL_ANCHORED)
        self.assertEqual(spr.wall_face, "north")

    def test_wall_face_south(self):
        """wall_face='south' also sets WALL_ANCHORED."""
        type_id = _find_billboard_type()
        if type_id is None:
            self.skipTest("No non-directional billboard entity type")
        w = World()
        desc = {"id": "t4", "type": type_id,
                "x": 5.0, "y": 5.0,
                "wall_height": 1.0, "wall_face": "south",
                "overrides": {}}
        eid = spawn_from_descriptor(w, desc, "test_zone")
        spr = w.get(eid, Sprite)
        self.assertEqual(spr.render_mode, RenderMode.WALL_ANCHORED)
        self.assertEqual(spr.wall_face, "south")


# ═════════════════════════════════════════════════════════════════
#  Packed buffer round-trip
# ═════════════════════════════════════════════════════════════════


class TestPackedBufferRenderMode(unittest.TestCase):
    """Verify the packed C entity buffer carries correct render_mode.

    Uses the same packing logic as RayRenderer.render_entities but
    extracted into a minimal helper to avoid needing a full renderer.
    """

    # Wall face → tangent angle map (must match ray_renderer._WALL_TAN_ANGLE)
    _WALL_TAN = {
        "north": 0.0, "south": 0.0,
        "east": math.pi / 2.0, "west": math.pi / 2.0,
    }

    def _pack_entity(self, desc: dict) -> list[float]:
        """Minimal repacking following ray_renderer.render_entities logic."""
        from core.entity_defs import get_entity_def
        edef = get_entity_def(desc["type"])
        if edef:
            n_facings = 8.0 if edef.directional else 1.0
        else:
            n_facings = 1.0

        wf = desc.get("wall_face")
        if wf and wf in self._WALL_TAN:
            facing_angle = self._WALL_TAN[wf]
            render_mode = float(RenderMode.WALL_ANCHORED.value)
        else:
            facing_angle = float(desc.get("angle", 0.0))
            render_mode = n_facings  # 1.0 or 8.0

        return [
            float(desc["x"]), float(desc["y"]),
            200.0, 200.0, 200.0,         # r, g, b
            0.6, 0.4,                     # h_scale, w_scale
            -1.0,                         # base_tex
            facing_angle,                 # field 8
            render_mode,                  # field 9
            0.0,                          # anim_offset
            0.0,                          # elevation
        ]

    def test_billboard_packed_mode(self):
        """Billboard entity packs render_mode = 1.0."""
        type_id = _find_billboard_type()
        if type_id is None:
            self.skipTest("No non-directional billboard entity type")
        buf = self._pack_entity({"type": type_id, "x": 5.0, "y": 5.0})
        self.assertAlmostEqual(buf[9], float(RenderMode.BILLBOARD.value))

    def test_wall_anchored_packed_mode(self):
        """Wall-anchored entity packs render_mode = -1.0."""
        type_id = _find_billboard_type()
        if type_id is None:
            self.skipTest("No non-directional billboard entity type")
        buf = self._pack_entity({
            "type": type_id, "x": 5.0, "y": 5.0,
            "wall_face": "north", "wall_height": 1.5,
        })
        self.assertAlmostEqual(buf[9], float(RenderMode.WALL_ANCHORED.value))

    def test_wall_anchored_tangent_differs(self):
        """Wall-anchored facing_angle is wall tangent, not entity angle."""
        type_id = _find_billboard_type()
        if type_id is None:
            self.skipTest("No non-directional billboard entity type")
        bb_buf = self._pack_entity(
            {"type": type_id, "x": 5.0, "y": 5.0, "angle": 1.23})
        wa_buf = self._pack_entity({
            "type": type_id, "x": 5.0, "y": 5.0,
            "wall_face": "east", "wall_height": 1.0,
        })
        # field 8: billboard stores entity angle, wall stores tangent
        self.assertAlmostEqual(bb_buf[8], 1.23)
        self.assertAlmostEqual(wa_buf[8], math.pi / 2.0)

    def test_directional_packed_mode(self):
        """Directional billboard packs render_mode = 8.0."""
        type_id = _find_directional_type()
        if type_id is None:
            self.skipTest("No directional billboard entity type")
        buf = self._pack_entity({"type": type_id, "x": 5.0, "y": 5.0})
        self.assertAlmostEqual(buf[9], float(RenderMode.BILLBOARD_8WAY.value))


# ═════════════════════════════════════════════════════════════════
#  Full pipeline: spawn → component → pack consistency
# ═════════════════════════════════════════════════════════════════


class TestFullPipeline(unittest.TestCase):
    """End-to-end: spawn from descriptor, check component, check buffer."""

    _WALL_TAN = {
        "north": 0.0, "south": 0.0,
        "east": math.pi / 2.0, "west": math.pi / 2.0,
    }

    def test_wall_anchored_full_pipeline(self):
        """Spawn wall-mounted entity, verify Sprite, verify packed buffer."""
        type_id = _find_billboard_type()
        if type_id is None:
            self.skipTest("No non-directional billboard entity type")

        # 1. Spawn
        w = World()
        desc = {
            "id": "pipe_test_1", "type": type_id,
            "x": 3.0, "y": 4.0,
            "wall_height": 1.2, "wall_face": "west",
            "overrides": {},
        }
        eid = spawn_from_descriptor(w, desc, "test_zone")

        # 2. Verify component
        spr = w.get(eid, Sprite)
        self.assertIsNotNone(spr)
        self.assertEqual(spr.render_mode, RenderMode.WALL_ANCHORED)
        self.assertEqual(spr.wall_face, "west")
        self.assertAlmostEqual(spr.wall_height, 1.2)

        # 3. Pack (minimal — mirrors ray_renderer logic)
        wf = desc.get("wall_face")
        if wf and wf in self._WALL_TAN:
            facing_angle = self._WALL_TAN[wf]
            render_mode = float(RenderMode.WALL_ANCHORED.value)
        else:
            self.fail("wall_face should be present")

        # 4. Verify packed values match component state
        self.assertAlmostEqual(render_mode, -1.0)
        self.assertAlmostEqual(facing_angle, math.pi / 2.0)  # west tangent

    def test_billboard_full_pipeline(self):
        """Spawn billboard entity, verify it does NOT get wall-anchored."""
        type_id = _find_billboard_type()
        if type_id is None:
            self.skipTest("No non-directional billboard entity type")

        w = World()
        desc = {
            "id": "pipe_test_2", "type": type_id,
            "x": 6.0, "y": 7.0,
            "overrides": {},
        }
        eid = spawn_from_descriptor(w, desc, "test_zone")

        spr = w.get(eid, Sprite)
        self.assertIsNotNone(spr)
        self.assertEqual(spr.render_mode, RenderMode.BILLBOARD)
        self.assertEqual(spr.wall_face, "")

    def test_prism_entity_render_mode(self):
        """Prism entity with a Sprite gets render_mode = PRISM."""
        from components import PrismShape
        reg = entity_registry()
        prism_types = [k for k, edef in reg.items()
                       if edef.render_type == "prism"]
        if not prism_types:
            self.skipTest("No prism entity types in registry")

        type_id = prism_types[0]
        w = World()
        desc = {"id": "pipe_prism_1", "type": type_id,
                "x": 5.0, "y": 5.0, "angle": 0.0, "overrides": {}}
        eid = spawn_from_descriptor(w, desc, "test_zone")
        self.assertTrue(w.has(eid, PrismShape))
        spr = w.get(eid, Sprite)
        if spr is not None:
            self.assertEqual(spr.render_mode, RenderMode.PRISM)


if __name__ == "__main__":
    unittest.main()
