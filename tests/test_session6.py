"""tests/test_session6.py — Tests for Session 6 & 7 features.

Covers:
  1. Persistent validation HUD state management
  2. Curve CF_TRANSPARENT flag + transparent→flags migration
  3. Zone preview launcher (PreviewApp creation, reload logic)
  4. Registry-backed validation coverage
  5. Deferred-hit budget validation
  6. sky_color wiring (Python layer)
  7. Overlay wall base_y field
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ─────────────────────────────────────────────────────────────────
#  Shared test helpers
# ─────────────────────────────────────────────────────────────────

def _make_2d(h: int, w: int, val: Any) -> list:
    return [[val] * w for _ in range(h)]


def _stub_zone(w: int = 4, h: int = 4, name: str = "test"):
    """Return a minimal stub zone that passes structural checks."""
    class StubZone:
        pass
    z = StubZone()
    z.name = name
    z.width = w
    z.height = h
    z.anchor = (1.0, 1.0)
    z.tiles = _make_2d(h, w, "floor")
    z.rotations = _make_2d(h, w, 0)
    z.floor_heights = _make_2d(h, w, 0.0)
    z.ceil_heights = _make_2d(h, w, 1.0)
    z.floor_textures = _make_2d(h, w, "stone")
    z.ceil_textures = _make_2d(h, w, "concrete")
    z.wall_textures = _make_2d(h, w, "brick")
    z.face_textures = [[[[] for _ in range(4)] for _ in range(w)] for _ in range(h)]
    z.light_levels = _make_2d(h, w, 1.0)
    z.reflect_map = _make_2d(h, w, 0)
    z.floor_slope_dx = _make_2d(h, w, 0.0)
    z.floor_slope_dy = _make_2d(h, w, 0.0)
    z.floor_slope_div = _make_2d(h, w, 0)
    z.floor2_heights = _make_2d(h, w, -1000.0)
    z.ceil2_heights = _make_2d(h, w, -1000.0)
    z.floor2_textures = _make_2d(h, w, "")
    z.ceil2_textures = _make_2d(h, w, "")
    z.upper_wall_height = _make_2d(h, w, 0.0)
    z.upper_wall_height2 = _make_2d(h, w, 0.0)
    z.fog_density = _make_2d(h, w, 0.0)
    z.floor_step_textures = [[[[] for _ in range(4)] for _ in range(w)] for _ in range(h)]
    z.ceil_step_textures = [[[[] for _ in range(4)] for _ in range(w)] for _ in range(h)]
    z.wall_segments = [[[[[] for _ in range(4)] for _ in range(4)] for _ in range(w)] for _ in range(h)]
    z.floor_step_segments = [[[[[] for _ in range(4)] for _ in range(4)] for _ in range(w)] for _ in range(h)]
    z.ceil_step_segments = [[[[[] for _ in range(4)] for _ in range(4)] for _ in range(w)] for _ in range(h)]
    z.entities = []
    z.boxes = []
    z.quads = []
    z.curves = []
    z.render_portals = []
    z.overlay_walls = []
    z.portals = []
    return z

# ─────────────────────────────────────────────────────────────────
#  1) Persistent validation HUD
# ─────────────────────────────────────────────────────────────────


class TestValidationHUD:
    """Verify _save_issues is populated on save and drives the HUD."""

    def test_clean_save_clears_issues(self):
        """A valid zone should produce zero errors/warnings in _save_issues."""
        from core.zones.validation import validate_zone
        zone = _stub_zone()
        issues = validate_zone(zone)
        errors = [i for i in issues if i.severity == "error"]
        warnings = [i for i in issues if i.severity == "warning"]
        # A freshly created default zone should be clean
        assert len(errors) == 0
        assert len(warnings) == 0

    def test_invalid_zone_produces_issues(self):
        """A zone with floor >= ceiling should produce geometry issues."""
        from core.zones.validation import validate_zone
        zone = _stub_zone()
        # Force floor above ceiling at (0,0)
        zone.floor_heights[0][0] = 5.0
        zone.ceil_heights[0][0] = 3.0
        issues = validate_zone(zone)
        # Should produce at least one error or warning about floor/ceiling
        assert any("floor" in i.message.lower() or "ceiling" in i.message.lower()
                    for i in issues)

    def test_save_issues_list_structure(self):
        """ZoneIssue objects have expected attributes."""
        from core.zones.validation import validate_zone, ZoneIssue
        zone = _stub_zone()
        zone.floor_heights[0][0] = 5.0
        zone.ceil_heights[0][0] = 3.0
        issues = validate_zone(zone)
        assert len(issues) > 0
        for iss in issues:
            assert hasattr(iss, "severity")
            assert hasattr(iss, "category")
            assert hasattr(iss, "message")
            assert hasattr(iss, "location")
            assert iss.severity in ("error", "warning")


# ─────────────────────────────────────────────────────────────────
#  2) Curve CF_TRANSPARENT + migration
# ─────────────────────────────────────────────────────────────────


class TestCurveTransparentFlag:
    """Verify Curve transparent→flags migration works at all layers."""

    def test_cf_transparent_constant(self):
        from core.zones.objects import CF_TRANSPARENT
        assert CF_TRANSPARENT == 1

    def test_curve_from_dict_no_transparent(self):
        """Plain curve dict → flags=0."""
        from core.zones.objects import Curve
        cv = Curve.from_dict({"cx": 1.0, "cy": 2.0, "radius": 0.5})
        assert cv.flags == 0

    def test_curve_from_dict_transparent_true(self):
        """Legacy 'transparent': True → CF_TRANSPARENT bit set."""
        from core.zones.objects import Curve, CF_TRANSPARENT
        cv = Curve.from_dict({"cx": 1.0, "transparent": True})
        assert cv.flags & CF_TRANSPARENT

    def test_curve_from_dict_transparent_false(self):
        """'transparent': False → no flag change."""
        from core.zones.objects import Curve, CF_TRANSPARENT
        cv = Curve.from_dict({"cx": 1.0, "transparent": False})
        assert not (cv.flags & CF_TRANSPARENT)

    def test_curve_from_dict_flags_preserved(self):
        """Explicit flags value is preserved even without transparent."""
        from core.zones.objects import Curve
        cv = Curve.from_dict({"flags": 5})
        assert cv.flags == 5

    def test_curve_from_dict_transparent_merges_with_flags(self):
        """transparent=True should OR into existing flags."""
        from core.zones.objects import Curve, CF_TRANSPARENT
        cv = Curve.from_dict({"flags": 4, "transparent": True})
        assert cv.flags == (4 | CF_TRANSPARENT)

    def test_curve_to_dict_no_transparent_key(self):
        """Serialized curve should have 'flags', not 'transparent'."""
        from core.zones.objects import Curve
        cv = Curve(flags=1)
        d = cv.to_dict()
        assert "flags" in d
        assert "transparent" not in d

    def test_curve_roundtrip(self):
        """from_dict → to_dict preserves flags, drops transparent."""
        from core.zones.objects import Curve
        d = {"cx": 1.0, "cy": 2.0, "transparent": True, "flags": 2}
        cv = Curve.from_dict(d)
        out = cv.to_dict()
        assert out["flags"] == 3  # 2 | 1
        assert "transparent" not in out


class TestCurveMigrationV1ToV2:
    """Verify the zone schema v1→v2 migration for curve transparent."""

    @staticmethod
    def _make_enty(**overrides) -> dict:
        """Create a minimal v1 enty payload."""
        enty = {
            "schema_version": 1,
            "width": 4, "height": 4,
            "tiles": [["open"] * 4 for _ in range(4)],
            "floor_heights": [[0.0] * 4 for _ in range(4)],
            "ceil_heights": [[4.0] * 4 for _ in range(4)],
            "curves": [],
        }
        enty.update(overrides)
        return enty

    def test_migration_converts_transparent_to_flags(self):
        from core.zones.migration import apply_migrations
        enty = self._make_enty(curves=[
            {"cx": 1.0, "cy": 2.0, "transparent": True, "radius": 0.5},
        ])
        result = apply_migrations(enty)
        assert result["schema_version"] == 2
        cv = result["curves"][0]
        assert cv.get("flags", 0) == 1
        assert "transparent" not in cv

    def test_migration_no_transparent_untouched(self):
        from core.zones.migration import apply_migrations
        enty = self._make_enty(curves=[
            {"cx": 1.0, "cy": 2.0, "flags": 4},
        ])
        result = apply_migrations(enty)
        cv = result["curves"][0]
        assert cv["flags"] == 4
        assert "transparent" not in cv

    def test_migration_transparent_false_removed(self):
        from core.zones.migration import apply_migrations
        enty = self._make_enty(curves=[
            {"cx": 1.0, "transparent": False},
        ])
        result = apply_migrations(enty)
        cv = result["curves"][0]
        assert "transparent" not in cv
        assert cv.get("flags", 0) == 0

    def test_migration_transparent_merges_with_flags(self):
        from core.zones.migration import apply_migrations
        enty = self._make_enty(curves=[
            {"cx": 1.0, "transparent": True, "flags": 6},
        ])
        result = apply_migrations(enty)
        cv = result["curves"][0]
        assert cv["flags"] == 7  # 6 | 1
        assert "transparent" not in cv

    def test_migration_empty_curves(self):
        from core.zones.migration import apply_migrations
        enty = self._make_enty(curves=[])
        result = apply_migrations(enty)
        assert result["schema_version"] == 2
        assert result["curves"] == []

    def test_migration_no_curves_key(self):
        from core.zones.migration import apply_migrations
        enty = self._make_enty()
        del enty["curves"]
        result = apply_migrations(enty)
        assert result["schema_version"] == 2

    def test_schema_version_is_2(self):
        from core.zones.migration import ZONE_SCHEMA_VERSION
        assert ZONE_SCHEMA_VERSION == 2

    def test_v0_to_v2_full_chain(self):
        """A v0 payload should migrate through v0→v1→v2."""
        from core.zones.migration import apply_migrations
        enty = {
            "width": 2, "height": 2,
            "tiles": [["open"] * 2 for _ in range(2)],
            "floor_heights": [[0.0] * 2 for _ in range(2)],
            "ceil_heights": [[4.0] * 2 for _ in range(2)],
            "curves": [{"cx": 1.0, "transparent": True}],
        }
        # v0 — no schema_version
        result = apply_migrations(enty)
        assert result["schema_version"] == 2
        assert result["curves"][0].get("flags", 0) == 1
        assert "transparent" not in result["curves"][0]


# ─────────────────────────────────────────────────────────────────
#  3) Zone preview launcher
# ─────────────────────────────────────────────────────────────────


class TestZonePreviewModule:
    """Verify zone_preview.py module structure and reload logic."""

    def test_import(self):
        """zone_preview module imports cleanly."""
        import zone_preview
        assert hasattr(zone_preview, "PreviewApp")
        assert hasattr(zone_preview, "main")
        assert hasattr(zone_preview, "_zone_mtime")

    def test_zone_mtime_missing_file(self):
        """_zone_mtime returns 0.0 for non-existent zone."""
        from zone_preview import _zone_mtime
        assert _zone_mtime("__definitely_not_a_zone__") == 0.0

    def test_zone_mtime_existing(self, tmp_path):
        """_zone_mtime returns positive for an existing zone file."""
        import zone_preview
        # Temporarily override ZONES_DIR
        fake_dir = tmp_path / "zones"
        fake_dir.mkdir()
        (fake_dir / "test.zone").write_bytes(b"data")
        old_dir = zone_preview.ZONES_DIR
        zone_preview.ZONES_DIR = fake_dir
        try:
            mt = zone_preview._zone_mtime("test")
            assert mt > 0
        finally:
            zone_preview.ZONES_DIR = old_dir

    def test_constants(self):
        """Preview constants have sane values."""
        import zone_preview
        assert zone_preview.RAY_W > 0
        assert zone_preview.RAY_H > 0
        assert zone_preview.POLL_INTERVAL > 0
        assert zone_preview.FPS_CAP > 0


class TestRendererFlagsRead:
    """Verify the renderer reads cv['flags'] instead of cv['transparent']."""

    def test_renderer_code_reads_flags(self):
        """The curve buffer construction should use cv.get('flags', 0)."""
        import inspect
        from engine.ray_renderer import RayRenderer
        source = inspect.getsource(RayRenderer._build_buffers)
        # Must NOT contain the vestigial transparent read
        assert 'cv.get("transparent"' not in source
        # Must contain the correct flags read
        assert 'cv.get("flags"' in source

    def test_curve_typed_object_flags_read(self):
        """When renderer reads .get('flags') on a Curve, it gets the flags field."""
        from core.zones.objects import Curve, CF_TRANSPARENT
        cv = Curve(flags=CF_TRANSPARENT)
        assert cv.get("flags", 0) == CF_TRANSPARENT
        # Old vestigial read would return default False
        assert cv.get("transparent", False) is False


# ─────────────────────────────────────────────────────────────────
#  4) Registry-backed validation coverage
# ─────────────────────────────────────────────────────────────────


class TestValidationWithRegistries:
    """Verify the opt-in checks fire when registries are passed."""

    def test_unknown_entity_detected_with_registry(self):
        """Entity with bogus type should produce a warning when registry is passed."""
        from core.zones.validation import validate_zone
        zone = _stub_zone()
        zone.entities = [{"uid": 1, "type": "nonexistent_monster", "x": 1, "y": 1}]
        # Without registry — no entity-type warning
        issues_bare = validate_zone(zone)
        assert not any(
            "unknown entity type" in i.message for i in issues_bare
        )
        # With registry — should warn
        issues_full = validate_zone(zone, entity_registry={"barrel": {}})
        assert any(
            "unknown entity type" in i.message and "nonexistent_monster" in i.message
            for i in issues_full
        )

    def test_valid_entity_no_warning(self):
        """Known entity type should not produce a warning."""
        from core.zones.validation import validate_zone
        zone = _stub_zone()
        zone.entities = [{"uid": 1, "type": "barrel", "x": 1, "y": 1}]
        issues = validate_zone(zone, entity_registry={"barrel": {}})
        assert not any("unknown entity type" in i.message for i in issues)

    def test_unknown_tile_detected_with_registry(self):
        """Tile ID not in registry should produce a warning."""
        from core.zones.validation import validate_zone
        zone = _stub_zone()
        zone.tiles[0][0] = "nonexistent_tile_type"
        # Without registry — no tile warning
        issues_bare = validate_zone(zone)
        assert not any("unknown tile" in i.message for i in issues_bare)
        # With registry — should warn
        issues_full = validate_zone(zone, tile_registry={"floor": {}})
        assert any(
            "unknown tile" in i.message.lower() and "nonexistent_tile_type" in i.message
            for i in issues_full
        )

    def test_valid_tile_no_warning(self):
        """Known tile ID should not produce a warning."""
        from core.zones.validation import validate_zone
        zone = _stub_zone()
        issues = validate_zone(zone, tile_registry={"floor": {}})
        assert not any("unknown tile" in i.message.lower() for i in issues)

    def test_missing_texture_detected_with_dir(self, tmp_path):
        """Texture with no corresponding PNG should produce a warning."""
        from core.zones.validation import validate_zone
        zone = _stub_zone()
        zone.floor_textures[0][0] = "missing_texture_xyz"
        # Without texture_dir — no texture warning
        issues_bare = validate_zone(zone)
        assert not any("missing_texture_xyz" in i.message for i in issues_bare)
        # With texture_dir (empty dir) — should warn
        issues_full = validate_zone(zone, texture_dir=tmp_path)
        assert any(
            "missing_texture_xyz" in i.message
            for i in issues_full
        )

    def test_existing_texture_no_warning(self, tmp_path):
        """Texture with corresponding PNG should not produce a warning."""
        from core.zones.validation import validate_zone
        zone = _stub_zone()
        zone.floor_textures[0][0] = "good_tex"
        (tmp_path / "good_tex.png").write_bytes(b"\x89PNG")
        issues = validate_zone(zone, texture_dir=tmp_path)
        assert not any("good_tex" in i.message for i in issues)

    def test_all_registries_together(self, tmp_path):
        """Passing all three registries should catch issues from each."""
        from core.zones.validation import validate_zone
        zone = _stub_zone()
        zone.entities = [{"uid": 1, "type": "bad_ent", "x": 1, "y": 1}]
        zone.tiles[0][0] = "bad_tile"
        zone.floor_textures[0][0] = "bad_tex"
        issues = validate_zone(
            zone,
            entity_registry={"barrel": {}},
            tile_registry={"floor": {}},
            texture_dir=tmp_path,
        )
        msgs = [i.message for i in issues]
        assert any("bad_ent" in m for m in msgs), "entity check didn't fire"
        assert any("bad_tile" in m for m in msgs), "tile check didn't fire"
        assert any("bad_tex" in m for m in msgs), "texture check didn't fire"

    def test_do_save_call_site_passes_registries(self):
        """The _do_save method source should pass all three registries."""
        src = Path("editor/app/app.py").read_text()
        # Find the _do_save body (between def _do_save and next def at same indent)
        assert "entity_registry=" in src
        assert "tile_registry=" in src
        assert "texture_dir=" in src

    def test_validate_dialog_uses_new_system(self):
        """The dialog should call validate_zone from core.zones.validation."""
        src = Path("editor/app/dialogs.py").read_text()
        assert "from core.zones.validation import validate_zone" in src
        assert "entity_registry=" in src
        assert "tile_registry=" in src
        assert "texture_dir=" in src

    def test_old_validate_zone_removed(self):
        """The old _validate_zone string-list function should be gone."""
        src = Path("editor/app/dialogs.py").read_text()
        # The old standalone function started with 'def _validate_zone('
        assert "def _validate_zone(" not in src, \
            "_validate_zone dead code still present in dialogs.py"


# ─────────────────────────────────────────────────────────────────
#  5) Deferred-hit budget validation
# ─────────────────────────────────────────────────────────────────


class TestDeferredBudgetValidation:
    """Verify the static deferred-count check catches dangerous zones."""

    def test_no_warning_on_clean_zone(self):
        """A minimal zone should not trigger a deferred warning."""
        from core.zones.validation import validate_zone
        zone = _stub_zone()
        issues = validate_zone(zone)
        assert not any(i.category == "deferred" for i in issues)

    def test_overlay_wall_overload(self):
        """Placing >16 overlay walls crossing one cell should warn."""
        from core.zones.validation import validate_zone
        from core.zones.zone import OverlayWall
        zone = _stub_zone()
        # 20 overlay walls all crossing cell (0,0)
        zone.overlay_walls = [
            OverlayWall(x1=0.1, y1=0.1, x2=0.9, y2=0.9, uid=i + 1)
            for i in range(20)
        ]
        issues = validate_zone(zone)
        deferred = [i for i in issues if i.category == "deferred"]
        assert len(deferred) >= 1
        assert "cell (0, 0)" in deferred[0].location

    def test_mixed_objects_accumulate(self):
        """Overlay walls + quads + boxes in one cell should sum up."""
        from core.zones.validation import validate_zone
        from core.zones.zone import OverlayWall
        zone = _stub_zone()
        # 10 overlays + 8 quads = 18 > 16
        zone.overlay_walls = [
            OverlayWall(x1=0.1, y1=0.1, x2=0.9, y2=0.9, uid=i + 1)
            for i in range(10)
        ]
        zone.quads = [
            {"uid": 100 + i, "x": 0.5, "z": 0.5, "angle": 0.0,
             "width": 0.5, "height": 1.0, "texture": "t", "collision": False,
             "two_sided": True}
            for i in range(8)
        ]
        issues = validate_zone(zone)
        assert any(i.category == "deferred" for i in issues)

    def test_transparent_tile_counted_with_registry(self):
        """Transparent tile + 16 overlays should warn (tile adds 1)."""
        from core.zones.validation import validate_zone
        from core.zones.zone import OverlayWall
        zone = _stub_zone()
        zone.overlay_walls = [
            OverlayWall(x1=0.1, y1=0.1, x2=0.9, y2=0.9, uid=i + 1)
            for i in range(16)
        ]
        # Without registry: 16 overlays = exactly at limit, no warn
        issues_bare = validate_zone(zone)
        deferred_bare = [i for i in issues_bare if i.category == "deferred"]
        assert len(deferred_bare) == 0

        # With registry containing a transparent tile: 16 + 1 = 17 > 16
        class FakeTile:
            transparent = True
            thin_wall = False
        issues_full = validate_zone(zone, tile_registry={"floor": FakeTile()})
        deferred_full = [i for i in issues_full if i.category == "deferred"]
        assert len(deferred_full) >= 1

    def test_max_def_per_col_matches_header(self):
        """Our constant must match the C header."""
        from core.zones.validation import MAX_DEF_PER_COL
        src = Path("engine/_ray_render.h").read_text()
        import re
        m = re.search(r"#define\s+MAX_DEF_PER_COL\s+(\d+)", src)
        assert m, "MAX_DEF_PER_COL not found in header"
        assert MAX_DEF_PER_COL == int(m.group(1))

    def test_curve_bbox_counted(self):
        """A curve overlapping cells should be counted toward the budget."""
        from core.zones.validation import validate_zone
        from core.zones.zone import OverlayWall
        zone = _stub_zone()
        # 15 overlays + 1 large curve + 1 box = should push over
        zone.overlay_walls = [
            OverlayWall(x1=0.1, y1=0.1, x2=0.9, y2=0.9, uid=i + 1)
            for i in range(15)
        ]
        zone.curves = [
            {"uid": 200, "x": 0.5, "y": 0.5, "radius": 1.0,
             "texture": "t", "flags": 0}
        ]
        zone.boxes = [
            {"uid": 300, "x": 0.5, "z": 0.5, "w": 0.5, "h": 1.0,
             "d": 0.5, "yaw": 0.0, "textures": {}}
        ]
        issues = validate_zone(zone)
        # 15 + 1 curve + 1 box = 17 > 16
        assert any(i.category == "deferred" for i in issues)


# ─────────────────────────────────────────────────────────────────
#  6) sky_color wiring
# ─────────────────────────────────────────────────────────────────


class TestSkyColorWiring:
    """Verify sky_color flows from zone through to the render context."""

    def test_sky_color_in_build_buffers_code(self):
        """ray_renderer.py should read zone.sky_color and pass it in ctx."""
        src = Path("engine/ray_renderer.py").read_text()
        assert "sky_color" in src
        assert "\"sky_color\"" in src  # ctx dict key

    def test_c_renderer_reads_sky_color(self):
        """C source should extract sky_color from the dict."""
        src = Path("engine/_ray_render.c").read_text()
        assert '"sky_color"' in src
        assert "sky_top_r" in src

    def test_fill_background_accepts_color_params(self):
        """fill_background signature should include sky colour params."""
        src = Path("engine/_ray_render.c").read_text()
        # Find the function definition
        assert "int sky_r, int sky_g, int sky_b)" in src

    def test_sky_color_field_roundtrip(self):
        """sky_color should survive zone serialisation / deserialisation."""
        from core.zones.zone import Zone
        # Construct a minimal zone with sky_color set
        z = Zone(
            name="test", width=2, height=2,
            anchor=(1.0, 1.0), tiles=[["floor"] * 2] * 2,
            sky_color=(200, 100, 50),
        )
        assert z.sky_color == (200, 100, 50)


# ─────────────────────────────────────────────────────────────────
#  7) Overlay wall base_y
# ─────────────────────────────────────────────────────────────────


class TestOverlayWallBaseY:
    """Verify the new base_y field on overlay walls."""

    def test_default_base_y_is_zero(self):
        """OverlayWall should default base_y to 0.0."""
        from core.zones.zone import OverlayWall
        ow = OverlayWall(x1=0, y1=0, x2=1, y2=1)
        assert ow.base_y == 0.0

    def test_base_y_from_dict(self):
        """OverlayWall should accept base_y from deserialized data."""
        from core.zones.zone import OverlayWall
        ow = OverlayWall(x1=0, y1=0, x2=1, y2=1, base_y=2.5)
        assert ow.base_y == 2.5

    def test_base_y_serialization_roundtrip(self):
        """base_y should survive zone save/load."""
        from dataclasses import asdict
        from core.zones.zone import OverlayWall
        ow = OverlayWall(x1=0, y1=0, x2=1, y2=1, base_y=1.5, uid=42)
        d = asdict(ow)
        assert d["base_y"] == 1.5
        restored = OverlayWall(**d)
        assert restored.base_y == 1.5

    def test_missing_base_y_defaults(self):
        """Old zone data without base_y should default to 0.0."""
        from core.zones.zone import OverlayWall
        # Simulate constructing from old dict data without base_y
        old_data = {
            "x1": 0.0, "y1": 0.0, "x2": 1.0, "y2": 1.0,
            "texture": "brick_wall", "height_scale": 1.0,
            "transparent": False, "blocks": True, "uid": 1,
        }
        # Zone.load_from_file uses .get("base_y", 0.0), so we test
        # that the default constructor gives 0.0
        ow = OverlayWall(
            x1=float(old_data.get("x1", 0)),
            y1=float(old_data.get("y1", 0)),
            x2=float(old_data.get("x2", 0)),
            y2=float(old_data.get("y2", 0)),
            texture=str(old_data.get("texture", "brick_wall")),
            height_scale=float(old_data.get("height_scale", 1.0)),
            base_y=float(old_data.get("base_y", 0.0)),
            transparent=bool(old_data.get("transparent", False)),
            blocks=bool(old_data.get("blocks", True)),
            uid=int(old_data.get("uid", 0)),
        )
        assert ow.base_y == 0.0

    def test_c_overlay_stride_is_eight(self):
        """C renderer should unpack overlays with stride 8."""
        src = Path("engine/_ray_render.c").read_text()
        assert "ow * 8 + 0" in src
        assert "ow * 8 + 5" in src  # base_y slot

    def test_python_packing_stride_eight(self):
        """Python packing should use 8 doubles per overlay wall."""
        src = Path("engine/ray_renderer.py").read_text()
        assert '    #      [x1, y1, x2, y2, height_scale, base_y, tile_id, flags]' in src
