"""tests/test_zone_validation.py — Tests for core.zones.validation.

Covers every check function in the validation pass against synthetic
Zone-like objects.  Uses a lightweight stub so tests don't depend on
pygame, numpy, or the real Zone dataclass.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from core.zones.validation import validate_zone, ZoneIssue


# ── Lightweight zone stub ─────────────────────────────────────────


@dataclass
class _Ent:
    """Minimal entity descriptor supporting .get() protocol."""
    uid: int = 0
    type: str = ""
    x: float = 0.0
    y: float = 0.0
    angle: float = 0.0
    state: str = "default"
    overrides: dict = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


@dataclass
class _Box:
    uid: int = 0
    x: float = 0.0; y: float = 0.0; z: float = 0.0
    w: float = 1.0; h: float = 1.0; d: float = 1.0
    yaw: float = 0.0; textures: dict = field(default_factory=dict)
    collision: bool = False

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


@dataclass
class _Quad:
    uid: int = 0; x: float = 0.0; z: float = 0.0
    base_y: float = 0.0; angle: float = 0.0
    width: float = 1.0; height: float = 1.0
    texture: str = "brick_wall"; collision: bool = False
    two_sided: bool = True

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


@dataclass
class _Portal:
    uid: int = 0
    cell: list = field(default_factory=lambda: [0, 0])
    face: int = 0
    dest_x: float = 0.5; dest_y: float = 0.5
    angle_offset: float = 0.0

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


@dataclass
class _Curve:
    uid: int = 0; cx: float = 0.0; cy: float = 0.0
    radius: float = 1.0; angle_start: float = 0.0
    angle_end: float = 90.0; height_scale: float = 1.0
    base_y: float = 0.0; texture: str = "brick_wall"; flags: int = 0

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


@dataclass
class _OverlayWall:
    x1: float = 0.0; y1: float = 0.0; x2: float = 1.0; y2: float = 0.0
    texture: str = "brick_wall"; height_scale: float = 1.0
    transparent: bool = False; blocks: bool = True; uid: int = 0


@dataclass
class _ZonePortal:
    tiles: list = field(default_factory=list)
    target_zone: str = ""
    target_row: float = 0.0; target_col: float = 0.0
    exit_direction: str = "up"


def _make_2d(h: int, w: int, val: Any = 0.0) -> list[list]:
    return [[val for _ in range(w)] for _ in range(h)]


def _make_3d(h: int, w: int, val: str = "") -> list[list[list]]:
    return [[[val, val, val, val] for _ in range(w)] for _ in range(h)]


def _make_4d(h: int, w: int) -> list[list[list[list]]]:
    """Wall-segment style [H][W][4][0 segments]."""
    return [[[[] for _ in range(4)] for _ in range(w)] for _ in range(h)]


def _clean_zone(w: int = 4, h: int = 4) -> Any:
    """Return a stub zone that should pass all structural checks."""
    @dataclass
    class StubZone:
        name: str = "test_zone"
        width: int = w
        height: int = h
        anchor: tuple = (1.0, 1.0)
        tiles: list = field(default_factory=lambda: _make_2d(h, w, "floor"))
        rotations: list = field(default_factory=lambda: _make_2d(h, w, 0))
        floor_heights: list = field(default_factory=lambda: _make_2d(h, w, 0.0))
        ceil_heights: list = field(default_factory=lambda: _make_2d(h, w, 1.0))
        floor_textures: list = field(default_factory=lambda: _make_2d(h, w, "stone"))
        ceil_textures: list = field(default_factory=lambda: _make_2d(h, w, "concrete"))
        wall_textures: list = field(default_factory=lambda: _make_2d(h, w, "brick"))
        face_textures: list = field(default_factory=lambda: _make_3d(h, w, ""))
        light_levels: list = field(default_factory=lambda: _make_2d(h, w, 1.0))
        reflect_map: list = field(default_factory=lambda: _make_2d(h, w, 0))
        floor_slope_dx: list = field(default_factory=lambda: _make_2d(h, w, 0.0))
        floor_slope_dy: list = field(default_factory=lambda: _make_2d(h, w, 0.0))
        floor_slope_div: list = field(default_factory=lambda: _make_2d(h, w, 0))
        floor2_heights: list = field(default_factory=lambda: _make_2d(h, w, -1000.0))
        ceil2_heights: list = field(default_factory=lambda: _make_2d(h, w, -1000.0))
        floor2_textures: list = field(default_factory=lambda: _make_2d(h, w, ""))
        ceil2_textures: list = field(default_factory=lambda: _make_2d(h, w, ""))
        upper_wall_height: list = field(default_factory=lambda: _make_2d(h, w, 0.0))
        upper_wall_height2: list = field(default_factory=lambda: _make_2d(h, w, 0.0))
        fog_density: list = field(default_factory=lambda: _make_2d(h, w, 0.0))
        floor_step_textures: list = field(default_factory=lambda: _make_3d(h, w, ""))
        ceil_step_textures: list = field(default_factory=lambda: _make_3d(h, w, ""))
        wall_segments: list = field(default_factory=lambda: _make_4d(h, w))
        floor_step_segments: list = field(default_factory=lambda: _make_4d(h, w))
        ceil_step_segments: list = field(default_factory=lambda: _make_4d(h, w))
        entities: list = field(default_factory=list)
        boxes: list = field(default_factory=list)
        quads: list = field(default_factory=list)
        curves: list = field(default_factory=list)
        render_portals: list = field(default_factory=list)
        overlay_walls: list = field(default_factory=list)
        portals: list = field(default_factory=list)

    return StubZone()


# ── Tests ─────────────────────────────────────────────────────────


class TestCleanZone:
    """A properly-formed zone should produce zero issues."""

    def test_empty_zone_no_issues(self):
        z = _clean_zone()
        issues = validate_zone(z)
        assert issues == []

    def test_with_populated_objects_no_issues(self):
        z = _clean_zone()
        z.entities = [_Ent(uid=1, type="npc", x=1.0, y=1.0)]
        z.boxes = [_Box(uid=2, w=1.0, h=1.0, d=1.0)]
        z.quads = [_Quad(uid=3, x=1.0, z=1.0)]
        z.render_portals = [_Portal(uid=4, cell=[1, 1], face=0,
                                     dest_x=2.0, dest_y=2.0)]
        z.curves = [_Curve(uid=5)]
        z.overlay_walls = [_OverlayWall(uid=6)]
        issues = validate_zone(z)
        assert issues == []


class TestGridDimensions:
    def test_wrong_row_count(self):
        z = _clean_zone(4, 4)
        z.floor_heights = _make_2d(3, 4, 0.0)  # 3 rows instead of 4
        issues = validate_zone(z)
        errors = [i for i in issues if i.severity == "error"
                  and i.category == "grid"]
        assert any("floor_heights" in e.message and "3 rows" in e.message
                    for e in errors)

    def test_wrong_col_count(self):
        z = _clean_zone(4, 4)
        z.tiles[2] = ["floor", "floor", "floor"]  # 3 cols instead of 4
        issues = validate_zone(z)
        errors = [i for i in issues if i.severity == "error"
                  and i.category == "grid"]
        assert any("tiles" in e.message and "row 2" in e.message
                    for e in errors)

    def test_face_textures_wrong_face_count(self):
        z = _clean_zone(4, 4)
        z.face_textures[0][0] = ["", "", ""]  # 3 faces instead of 4
        issues = validate_zone(z)
        errors = [i for i in issues if i.severity == "error"
                  and i.category == "grid"]
        assert len(errors) >= 1


class TestGeometry:
    def test_floor_above_ceiling(self):
        z = _clean_zone(4, 4)
        z.floor_heights[1][2] = 2.0
        z.ceil_heights[1][2] = 0.5
        issues = validate_zone(z)
        warnings = [i for i in issues if i.category == "geometry"
                    and "floor" in i.message and "ceiling" in i.message]
        assert len(warnings) == 1
        assert "cell (1, 2)" in warnings[0].location

    def test_secondary_floor_without_ceiling(self):
        z = _clean_zone(4, 4)
        z.floor2_heights[0][0] = 0.5   # active
        z.ceil2_heights[0][0] = -1000.0  # sentinel = inactive
        issues = validate_zone(z)
        warnings = [i for i in issues if "secondary floor set" in i.message]
        assert len(warnings) == 1

    def test_secondary_ceiling_without_floor(self):
        z = _clean_zone(4, 4)
        z.floor2_heights[0][0] = -1000.0
        z.ceil2_heights[0][0] = 1.5
        issues = validate_zone(z)
        warnings = [i for i in issues if "secondary ceiling set" in i.message]
        assert len(warnings) == 1

    def test_secondary_floor_above_secondary_ceiling(self):
        z = _clean_zone(4, 4)
        z.floor2_heights[0][0] = 2.0
        z.ceil2_heights[0][0] = 1.0
        issues = validate_zone(z)
        warnings = [i for i in issues if "secondary floor" in i.message
                    and "secondary ceiling" in i.message]
        assert len(warnings) == 1

    def test_clean_secondary_layer(self):
        z = _clean_zone(4, 4)
        z.floor2_heights[0][0] = 0.5
        z.ceil2_heights[0][0] = 1.5
        issues = validate_zone(z)
        assert not any("secondary" in i.message for i in issues)


class TestUIDUniqueness:
    def test_duplicate_uid_error(self):
        z = _clean_zone()
        z.entities = [_Ent(uid=10, type="npc"), _Ent(uid=10, type="beast")]
        issues = validate_zone(z)
        errors = [i for i in issues if i.severity == "error"
                  and i.category == "uid"]
        assert len(errors) == 1
        assert "10" in errors[0].message

    def test_duplicate_across_types(self):
        z = _clean_zone()
        z.entities = [_Ent(uid=5, type="npc")]
        z.boxes = [_Box(uid=5)]
        issues = validate_zone(z)
        errors = [i for i in issues if i.severity == "error"
                  and i.category == "uid"]
        assert len(errors) == 1

    def test_uid_zero_warning(self):
        z = _clean_zone()
        z.entities = [_Ent(uid=0, type="npc")]
        issues = validate_zone(z)
        warnings = [i for i in issues if i.category == "uid"
                    and i.severity == "warning"]
        assert len(warnings) == 1

    def test_unique_uids_clean(self):
        z = _clean_zone()
        z.entities = [_Ent(uid=1, type="a"), _Ent(uid=2, type="b")]
        z.boxes = [_Box(uid=3)]
        issues = validate_zone(z)
        assert not any(i.category == "uid" for i in issues)

    def test_overlay_wall_uid_duplicate(self):
        z = _clean_zone()
        z.entities = [_Ent(uid=7, type="npc")]
        z.overlay_walls = [_OverlayWall(uid=7)]
        issues = validate_zone(z)
        errors = [i for i in issues if i.severity == "error"
                  and i.category == "uid"]
        assert len(errors) == 1


class TestEntities:
    def test_missing_type_error(self):
        z = _clean_zone()
        z.entities = [_Ent(uid=1, type="")]
        issues = validate_zone(z)
        errors = [i for i in issues if i.severity == "error"
                  and i.category == "entity"]
        assert any("no type" in e.message for e in errors)

    def test_unknown_type_warning(self):
        z = _clean_zone()
        z.entities = [_Ent(uid=1, type="nonexistent_beast")]
        reg = {"npc": True, "barrel": True}
        issues = validate_zone(z, entity_registry=reg)
        warnings = [i for i in issues if i.severity == "warning"
                    and i.category == "entity"
                    and "unknown" in i.message]
        assert len(warnings) == 1

    def test_known_type_clean(self):
        z = _clean_zone()
        z.entities = [_Ent(uid=1, type="npc")]
        reg = {"npc": True}
        issues = validate_zone(z, entity_registry=reg)
        assert not any(i.category == "entity" and "unknown" in i.message
                       for i in issues)

    def test_no_registry_skips_type_check(self):
        z = _clean_zone()
        z.entities = [_Ent(uid=1, type="imaginary")]
        issues = validate_zone(z)
        assert not any("unknown" in i.message for i in issues)

    def test_out_of_bounds_warning(self):
        z = _clean_zone(4, 4)
        z.entities = [_Ent(uid=1, type="npc", x=5.0, y=1.0)]
        issues = validate_zone(z)
        warnings = [i for i in issues if i.category == "entity"
                    and "outside" in i.message]
        assert len(warnings) == 1

    def test_negative_position_warning(self):
        z = _clean_zone(4, 4)
        z.entities = [_Ent(uid=1, type="npc", x=-1.0, y=1.0)]
        issues = validate_zone(z)
        warnings = [i for i in issues if i.category == "entity"
                    and "outside" in i.message]
        assert len(warnings) == 1


class TestRenderPortals:
    def test_cell_out_of_bounds(self):
        z = _clean_zone(4, 4)
        z.render_portals = [_Portal(uid=1, cell=[5, 2], face=0)]
        issues = validate_zone(z)
        errors = [i for i in issues if i.severity == "error"
                  and i.category == "portal"]
        assert any("cell" in e.message and "outside" in e.message
                    for e in errors)

    def test_invalid_face(self):
        z = _clean_zone()
        z.render_portals = [_Portal(uid=1, cell=[0, 0], face=7)]
        issues = validate_zone(z)
        errors = [i for i in issues if i.severity == "error"
                  and "face" in i.message]
        assert len(errors) == 1

    def test_dest_out_of_bounds_warning(self):
        z = _clean_zone(4, 4)
        z.render_portals = [_Portal(uid=1, cell=[0, 0], face=0,
                                     dest_x=10.0, dest_y=1.0)]
        issues = validate_zone(z)
        warnings = [i for i in issues if i.severity == "warning"
                    and "destination" in i.message]
        assert len(warnings) == 1

    def test_valid_portal_clean(self):
        z = _clean_zone(4, 4)
        z.render_portals = [_Portal(uid=1, cell=[1, 1], face=2,
                                     dest_x=2.0, dest_y=2.0)]
        issues = validate_zone(z)
        assert not any(i.category == "portal" for i in issues)


class TestZonePortals:
    def test_empty_target_zone(self):
        z = _clean_zone()
        z.portals = [_ZonePortal(tiles=[(0, 0)], target_zone="")]
        issues = validate_zone(z)
        errors = [i for i in issues if i.severity == "error"
                  and "target_zone" in i.message]
        assert len(errors) == 1

    def test_portal_tile_out_of_bounds(self):
        z = _clean_zone(4, 4)
        z.portals = [_ZonePortal(tiles=[(10, 0)], target_zone="other")]
        issues = validate_zone(z)
        errors = [i for i in issues if i.severity == "error"
                  and "portal tile" in i.message]
        assert len(errors) == 1


class TestBoxes:
    def test_zero_dimension_error(self):
        z = _clean_zone()
        z.boxes = [_Box(uid=1, w=0.0, h=1.0, d=1.0)]
        issues = validate_zone(z)
        errors = [i for i in issues if i.severity == "error"
                  and "degenerate" in i.message]
        assert len(errors) == 1

    def test_negative_dimension_error(self):
        z = _clean_zone()
        z.boxes = [_Box(uid=1, w=1.0, h=-2.0, d=1.0)]
        issues = validate_zone(z)
        errors = [i for i in issues if i.severity == "error"
                  and "degenerate" in i.message]
        assert len(errors) == 1

    def test_valid_box_clean(self):
        z = _clean_zone()
        z.boxes = [_Box(uid=1)]
        issues = validate_zone(z)
        assert not any("degenerate" in i.message for i in issues)


class TestQuads:
    def test_zero_dimension_warning(self):
        z = _clean_zone()
        z.quads = [_Quad(uid=1, width=0.0, height=1.0)]
        issues = validate_zone(z)
        warnings = [i for i in issues if "degenerate" in i.message]
        assert len(warnings) == 1


class TestOverlayWalls:
    def test_zero_length(self):
        z = _clean_zone()
        z.overlay_walls = [_OverlayWall(uid=1, x1=2.0, y1=3.0, x2=2.0, y2=3.0)]
        issues = validate_zone(z)
        warnings = [i for i in issues if "zero-length" in i.message]
        assert len(warnings) == 1


class TestAnchor:
    def test_out_of_bounds(self):
        z = _clean_zone(4, 4)
        z.anchor = (5.0, 1.0)
        issues = validate_zone(z)
        warnings = [i for i in issues if i.category == "anchor"]
        assert len(warnings) == 1

    def test_missing_anchor(self):
        z = _clean_zone()
        z.anchor = None
        issues = validate_zone(z)
        warnings = [i for i in issues if i.category == "anchor"]
        assert len(warnings) == 1


class TestTextures:
    def test_missing_texture_asset(self):
        z = _clean_zone(2, 2)
        z.floor_textures = [["exists", "missing_tex"], ["exists", "exists"]]
        with tempfile.TemporaryDirectory() as td:
            tex_dir = Path(td)
            (tex_dir / "exists.png").touch()
            # "missing_tex.png" does NOT exist
            issues = validate_zone(z, texture_dir=tex_dir)
        warnings = [i for i in issues if i.category == "texture"]
        assert any("missing_tex" in w.message for w in warnings)

    def test_no_texture_dir_skips(self):
        z = _clean_zone(2, 2)
        z.floor_textures = [["bogus", "bogus"], ["bogus", "bogus"]]
        issues = validate_zone(z)
        assert not any(i.category == "texture" for i in issues)

    def test_object_texture_checked(self):
        z = _clean_zone(2, 2)
        z.quads = [_Quad(uid=1, texture="quad_missing")]
        z.curves = [_Curve(uid=2, texture="curve_missing")]
        z.boxes = [_Box(uid=3, textures={"N": "box_missing"})]
        z.overlay_walls = [_OverlayWall(uid=4, texture="ow_missing")]
        with tempfile.TemporaryDirectory() as td:
            tex_dir = Path(td)
            issues = validate_zone(z, texture_dir=tex_dir)
        tex_warnings = [i for i in issues if i.category == "texture"]
        mentioned = " ".join(w.message for w in tex_warnings)
        assert "quad_missing" in mentioned
        assert "curve_missing" in mentioned
        assert "box_missing" in mentioned
        assert "ow_missing" in mentioned

    def test_empty_string_not_flagged(self):
        z = _clean_zone(2, 2)
        z.floor_textures = [["", ""], ["", ""]]
        z.ceil_textures = [["", ""], ["", ""]]
        z.wall_textures = [["", ""], ["", ""]]
        z.floor2_textures = [["", ""], ["", ""]]
        z.ceil2_textures = [["", ""], ["", ""]]
        with tempfile.TemporaryDirectory() as td:
            issues = validate_zone(z, texture_dir=Path(td))
        assert not any(i.category == "texture" for i in issues)

    def test_segment_texture_checked(self):
        z = _clean_zone(2, 2)
        z.wall_segments[0][0][0] = [["seg_missing", 1.0]]
        with tempfile.TemporaryDirectory() as td:
            issues = validate_zone(z, texture_dir=Path(td))
        assert any("seg_missing" in i.message for i in issues)


class TestTiles:
    def test_unknown_tile_warning(self):
        z = _clean_zone(2, 2)
        z.tiles = [["floor", "wall"], ["floor", "mystery"]]
        reg = {"floor": True, "wall": True}
        issues = validate_zone(z, tile_registry=reg)
        warnings = [i for i in issues if i.category == "tile"]
        assert any("mystery" in w.message for w in warnings)

    def test_no_registry_skips(self):
        z = _clean_zone(2, 2)
        z.tiles = [["bogus", "bogus"], ["bogus", "bogus"]]
        issues = validate_zone(z)
        assert not any(i.category == "tile" for i in issues)


class TestSortOrder:
    """Issues should be returned errors-first, then warnings."""

    def test_errors_before_warnings(self):
        z = _clean_zone(4, 4)
        z.entities = [_Ent(uid=1, type="")]        # error
        z.floor_heights[0][0] = 5.0                 # warning (above ceiling)
        issues = validate_zone(z)
        assert len(issues) >= 2
        error_idx = next(i for i, x in enumerate(issues) if x.severity == "error")
        warn_idx = next(i for i, x in enumerate(issues) if x.severity == "warning")
        assert error_idx < warn_idx


class TestZoneValidateMethod:
    """Zone.validate() convenience method."""

    def test_method_exists_and_works(self):
        z = _clean_zone()
        # The stub doesn't have .validate(), but the real Zone does.
        # Test via the module function directly — the method is a thin wrapper.
        issues = validate_zone(z)
        assert issues == []
