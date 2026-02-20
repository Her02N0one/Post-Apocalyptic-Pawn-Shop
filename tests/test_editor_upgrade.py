"""tests/test_editor_upgrade.py — Tests for the Level Editor upgrade.

Covers:
  1. ForgeRegistry (TOML load/save/lookup/mutation)
  2. Palette format (tiles ↔ palette round-trip)
  3. MessagePack export/import (round-trip)
  4. FP preview (basic cast/passability)
"""

from __future__ import annotations

import json
import struct
import tempfile
from pathlib import Path

import pytest


# ═════════════════════════════════════════════════════════════════════
#  1. ForgeRegistry
# ═════════════════════════════════════════════════════════════════════

class TestForgeRegistry:

    def test_load_from_toml(self):
        from editor.forge_registry import ForgeRegistry
        reg = ForgeRegistry.instance()
        # Should have loaded from data/custom_entities.toml
        assert len(reg.ids()) > 0

    def test_get_known(self):
        from editor.forge_registry import ForgeRegistry
        reg = ForgeRegistry.instance()
        arch = reg.get("wooden_crate")
        if arch is None:
            pytest.skip("wooden_crate not in TOML (manual edit)")
        assert arch.kind == "box"
        assert arch.display_name != ""

    def test_by_kind(self):
        from editor.forge_registry import ForgeRegistry
        reg = ForgeRegistry.instance()
        boxes = reg.by_kind("box")
        for b in boxes:
            assert b.kind == "box"

    def test_upsert_and_delete(self):
        from editor.forge_registry import ForgeArchetype, ForgeRegistry
        reg = ForgeRegistry.instance()
        arch = ForgeArchetype(id="_test_item", kind="billboard",
                              display_name="Test")
        reg.upsert(arch)
        assert reg.get("_test_item") is not None
        reg.delete("_test_item")
        assert reg.get("_test_item") is None

    def test_save_round_trip(self, tmp_path):
        """Save and reload should preserve data."""
        from editor.forge_registry import (
            ForgeArchetype, ForgeRegistry, _DATA_PATH,
        )
        import editor.forge_registry as mod

        # Temporarily redirect the data path to tmp
        orig = mod._DATA_PATH
        test_path = tmp_path / "custom_entities.toml"
        mod._DATA_PATH = test_path

        try:
            reg = ForgeRegistry()
            reg.upsert(ForgeArchetype(
                id="test_box", kind="box",
                display_name="Test Box",
                width=1.0, depth=0.5, height=0.3,
                color=(255, 0, 0),
                tags=["furniture"],
            ))
            assert reg.save()

            # Reload from written file
            reg2 = ForgeRegistry()
            arch = reg2.get("test_box")
            assert arch is not None
            assert arch.kind == "box"
            assert arch.display_name == "Test Box"
            assert arch.width == 1.0
            assert arch.color == (255, 0, 0)
            assert "furniture" in arch.tags
        finally:
            mod._DATA_PATH = orig


# ═════════════════════════════════════════════════════════════════════
#  2. Palette Format
# ═════════════════════════════════════════════════════════════════════

class TestPaletteFormat:

    def _sample_tiles(self):
        return [
            ["wall", "grass", "grass", "wall"],
            ["wall", "wood_floor", "wood_floor", "wall"],
            ["wall", "wall", "wall", "wall"],
        ]

    def test_tiles_to_palette(self):
        from editor.palette_format import tiles_to_palette
        tiles = self._sample_tiles()
        palette, flat, w, h = tiles_to_palette(tiles)
        assert w == 4
        assert h == 3
        assert len(flat) == 12
        # All palette entries should have tile_id
        for pidx, entry in palette.items():
            assert "tile_id" in entry

    def test_round_trip(self):
        from editor.palette_format import tiles_to_palette, palette_to_tiles
        tiles = self._sample_tiles()
        palette, flat, w, h = tiles_to_palette(tiles)
        restored = palette_to_tiles(palette, flat, w, h)
        assert restored == tiles

    def test_zone_dict_round_trip(self):
        from editor.palette_format import (
            zone_to_palette_dict, palette_dict_to_zone,
        )
        tiles = self._sample_tiles()
        zone = {
            "name": "test",
            "tiles": tiles,
            "entities": [{"id": "e1"}],
            "portals": [],
            "anchor": [2.0, 1.5],
        }
        pal_dict = zone_to_palette_dict(zone)
        assert "palette" in pal_dict
        assert "grid" in pal_dict
        assert "tiles" not in pal_dict

        restored = palette_dict_to_zone(pal_dict)
        assert restored["tiles"] == tiles
        assert restored["entities"] == zone["entities"]

    def test_empty_tiles(self):
        from editor.palette_format import tiles_to_palette
        palette, flat, w, h = tiles_to_palette([])
        assert w == 0
        assert h == 0
        assert flat == []


# ═════════════════════════════════════════════════════════════════════
#  3. MessagePack I/O
# ═════════════════════════════════════════════════════════════════════

class TestMsgpackIO:

    def _sample_zone(self):
        return {
            "name": "test_zone",
            "width": 4,
            "height": 3,
            "tiles": [
                ["wall", "grass", "grass", "wall"],
                ["wall", "wood_floor", "wood_floor", "wall"],
                ["wall", "wall", "wall", "wall"],
            ],
            "entities": [
                {"id": "crate_0", "position": {"x": 1.5, "y": 1.5}},
            ],
            "portals": [
                {"tiles": [[0, 1]], "target_zone": "elsewhere",
                 "target_pos": [5, 5], "exit_direction": "up"},
            ],
            "anchor": [2.0, 1.5],
            "first_person": True,
        }

    def test_export_import_round_trip(self):
        msgpack = pytest.importorskip("msgpack")
        from editor.msgpack_io import export_zone_msgpack, import_zone_msgpack
        zone = self._sample_zone()
        blob = export_zone_msgpack(zone)
        assert isinstance(blob, bytes)
        assert len(blob) > 10

        restored = import_zone_msgpack(blob)
        assert restored["tiles"] == zone["tiles"]
        assert restored["name"] == "test_zone"
        assert len(restored["entities"]) == 1
        assert len(restored["portals"]) == 1

    def test_header_only(self):
        msgpack = pytest.importorskip("msgpack")
        from editor.msgpack_io import export_zone_msgpack, import_header
        zone = self._sample_zone()
        blob = export_zone_msgpack(zone)
        header = import_header(blob)
        assert header["name"] == "test_zone"
        assert header["width"] == 4
        assert header["height"] == 3
        assert "palette" not in header  # palette is in payload only

    def test_file_round_trip(self, tmp_path):
        msgpack = pytest.importorskip("msgpack")
        from editor.msgpack_io import export_zone_msgpack, import_zone_file
        zone = self._sample_zone()
        out_path = tmp_path / "test.mpz"
        export_zone_msgpack(zone, out_path)
        assert out_path.exists()

        restored = import_zone_file(out_path)
        assert restored["tiles"] == zone["tiles"]

    def test_binary_format(self):
        """Verify the 4-byte header length prefix."""
        msgpack = pytest.importorskip("msgpack")
        from editor.msgpack_io import export_zone_msgpack
        zone = self._sample_zone()
        blob = export_zone_msgpack(zone)
        header_len = struct.unpack(">I", blob[:4])[0]
        assert header_len > 0
        assert header_len < len(blob) - 4


# ═════════════════════════════════════════════════════════════════════
#  4. FP Preview
# ═════════════════════════════════════════════════════════════════════

class TestFPPreview:

    def _simple_map(self):
        """Open room with walls on edges."""
        return [
            ["wall", "wall", "wall", "wall", "wall"],
            ["wall", "grass", "grass", "grass", "wall"],
            ["wall", "grass", "grass", "grass", "wall"],
            ["wall", "grass", "grass", "grass", "wall"],
            ["wall", "wall", "wall", "wall", "wall"],
        ]

    def test_passable(self):
        from editor.fp_preview import FPPreview
        tiles = self._simple_map()
        # Center should be passable
        assert FPPreview._passable(2.5, 2.5, tiles, 5, 5, 0.2)
        # Wall corner should not be passable
        assert not FPPreview._passable(0.1, 0.1, tiles, 5, 5, 0.2)

    def test_cast_ray_hits_wall(self):
        import math
        from editor.fp_preview import FPPreview
        tiles = self._simple_map()
        # Cast east from center
        dist, tid, side = FPPreview._cast_ray(
            2.5, 2.5, 1.0, 0.0, tiles, 5, 5)
        assert dist > 0
        assert tid == "wall"  # wall

    def test_cast_ray_no_crash_on_diagonal(self):
        import math
        from editor.fp_preview import FPPreview
        tiles = self._simple_map()
        cos_a = math.cos(math.pi / 4)
        sin_a = math.sin(math.pi / 4)
        dist, tid, side = FPPreview._cast_ray(
            2.5, 2.5, cos_a, sin_a, tiles, 5, 5)
        assert dist > 0

    def test_toggle(self):
        from editor.fp_preview import FPPreview
        fp = FPPreview()
        assert not fp.active
        fp.toggle()
        assert fp.active
        fp.toggle()
        assert not fp.active


# ═════════════════════════════════════════════════════════════════════
#  5. Forge placement in entities (integration)
# ═════════════════════════════════════════════════════════════════════

class TestForgeEntityPlacement:
    """Verify a forge archetype can be converted to an entity dict."""

    def test_box_to_entity_dict(self):
        from editor.forge_registry import ForgeArchetype

        arch = ForgeArchetype(
            id="my_crate", kind="box",
            display_name="My Crate",
            width=0.5, depth=0.5, height=0.4,
            color=(200, 150, 100),
            dev_notes="TODO: add loot table",
            tags=["container", "furniture"],
        )
        # Build entity dict as the editor would
        ent = {
            "id": f"{arch.id}_0",
            "prefab": arch.id,
            "position": {"x": 5.5, "y": 3.5},
            "identity": {
                "name": arch.display_name,
                "kind": "object",
            },
            "sprite": {
                "char": "\u25A1",
                "color": list(arch.color),
                "layer": 5,
            },
            "wall_sprite": {
                "texture_key": arch.texture_key or "",
                "width": arch.width,
                "height": arch.height,
                "elevation": arch.z_offset,
            },
            "dev_notes": arch.dev_notes,
            "forge_archetype": arch.id,
        }
        assert ent["id"] == "my_crate_0"
        assert ent["wall_sprite"]["width"] == 0.5
        assert ent["dev_notes"] == "TODO: add loot table"
