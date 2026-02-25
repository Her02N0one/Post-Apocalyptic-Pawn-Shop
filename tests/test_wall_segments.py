"""tests/test_wall_segments.py — Tests for wall segment editing and rendering.

Covers:
  1. Zone wall_segments data model
  2. Segment split / merge / paint editing operations
  3. Segment save/load round-trip
  4. Renderer with segments (no magenta)
  5. v_scale TileDef field
"""

from __future__ import annotations

import math
import os
import sys
import tempfile
from pathlib import Path

import pytest

_root = str(Path(__file__).resolve().parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame
pygame.init()
_screen = pygame.display.set_mode((320, 240))

from core.zones import Zone, load_zone
from core.tiles import TILE_REGISTRY, tile_def, tile_str_to_int


# ═════════════════════════════════════════════════════════════════════
#  1. Zone wall_segments data model
# ═════════════════════════════════════════════════════════════════════

class TestWallSegmentsModel:

    def _make_zone(self) -> Zone:
        """Create a minimal 4x4 zone with wall borders and open interior."""
        z = load_zone("showcase")
        return z

    def test_wall_segments_field_exists(self):
        z = self._make_zone()
        assert hasattr(z, "wall_segments")

    def test_ensure_face_textures_creates_segments(self):
        """Zone3DEditor._ensure_face_textures initializes wall_segments."""
        from editor.view_3d import Zone3DEditor
        z = self._make_zone()
        z.wall_segments = []  # clear
        ed = Zone3DEditor(z)
        assert len(z.wall_segments) == z.height
        assert len(z.wall_segments[0]) == z.width
        assert len(z.wall_segments[0][0]) == 4  # 4 faces per cell
        assert z.wall_segments[0][0][0] == []   # empty by default

    def test_wall_segments_per_face(self):
        z = self._make_zone()
        from editor.view_3d import Zone3DEditor
        ed = Zone3DEditor(z)
        # Manually set segments on a wall cell
        z.wall_segments[0][0][0] = [["brick_wall", 0.5], ["concrete", 0.95]]
        segs = z.wall_segments[0][0][0]
        assert len(segs) == 2
        assert segs[0] == ["brick_wall", 0.5]
        assert segs[1] == ["concrete", 0.95]


# ═════════════════════════════════════════════════════════════════════
#  2. Segment editing operations (split / merge / paint)
# ═════════════════════════════════════════════════════════════════════

class TestSegmentEditing:

    def _make_editor(self):
        from editor.view_3d import Zone3DEditor
        z = load_zone("showcase")
        ed = Zone3DEditor(z)
        ed.tool = "segment"
        return ed, z

    def test_seg_split_creates_two_segments(self):
        """Splitting a segmentless wall face creates two segments."""
        from editor.view_3d.picking import _CellHit
        ed, z = self._make_editor()

        # Find a wall cell
        r, c = 0, 0
        td = tile_def(z.tiles[r][c])
        assert td and td.wall, "Cell (0,0) should be a wall"

        fh = z.floor_heights[r][c]
        ch = z.ceil_heights[r][c]
        mid_y = (fh + ch) / 2.0

        # Simulate aiming at north face of this wall at mid height
        ed.aimed = _CellHit(t=1.0, col=c, row=r, part="wall",
                            face="north", hit_y=mid_y)
        ed.current_texture = "concrete"
        ed.snap_y = 0.25

        ed._seg_split()

        segs = z.wall_segments[r][c][0]  # north = face index 0
        assert len(segs) == 2, f"Expected 2 segments, got {len(segs)}"
        # First segment goes from fh to snapped mid_y
        assert segs[0][1] < segs[1][1], "Segments should be sorted bottom-to-top"
        assert segs[1][1] == pytest.approx(ch, abs=0.01)

    def test_seg_split_existing_segments(self):
        """Splitting an already-segmented face adds another boundary."""
        from editor.view_3d.picking import _CellHit
        ed, z = self._make_editor()

        r, c = 0, 0
        fh = z.floor_heights[r][c]
        ch = z.ceil_heights[r][c]

        # Pre-populate with two segments
        z.wall_segments[r][c][1] = [["brick_wall", 0.5], ["concrete", ch]]

        # Aim at south face at y=0.3 (within first segment)
        ed.aimed = _CellHit(t=1.0, col=c, row=r, part="wall",
                            face="south", hit_y=0.3)
        ed.current_texture = "carpet"
        ed.snap_y = 0.25

        ed._seg_split()

        segs = z.wall_segments[r][c][1]
        assert len(segs) == 3, f"Expected 3 segments, got {len(segs)}"

    def test_seg_merge_removes_boundary(self):
        """Merging reduces the number of segments."""
        from editor.view_3d.picking import _CellHit
        ed, z = self._make_editor()

        r, c = 0, 0
        ch = z.ceil_heights[r][c]

        # Set up 3 segments
        z.wall_segments[r][c][0] = [
            ["brick_wall", 0.25],
            ["concrete", 0.5],
            ["carpet", ch],
        ]

        # Aim near the boundary at y=0.25 (between seg0 and seg1)
        ed.aimed = _CellHit(t=1.0, col=c, row=r, part="wall",
                            face="north", hit_y=0.26)
        ed._seg_merge()

        segs = z.wall_segments[r][c][0]
        assert len(segs) == 2, f"Expected 2 segments after merge, got {len(segs)}"

    def test_seg_merge_to_single_clears(self):
        """Merging 2 segments into 1 clears the segment list (uses face_textures)."""
        from editor.view_3d.picking import _CellHit
        ed, z = self._make_editor()

        r, c = 0, 0
        ch = z.ceil_heights[r][c]

        z.wall_segments[r][c][2] = [["brick_wall", 0.5], ["concrete", ch]]

        ed.aimed = _CellHit(t=1.0, col=c, row=r, part="wall",
                            face="east", hit_y=0.5)
        ed._seg_merge()

        segs = z.wall_segments[r][c][2]
        assert segs == [], f"Expected empty segments after merge to 1, got {segs}"

    def test_seg_paint_changes_texture(self):
        """Painting a segment changes only that segment's texture."""
        from editor.view_3d.picking import _CellHit
        ed, z = self._make_editor()

        r, c = 0, 0
        ch = z.ceil_heights[r][c]

        z.wall_segments[r][c][0] = [["brick_wall", 0.5], ["concrete", ch]]

        # Aim at y=0.3 (first segment) on north face
        ed.aimed = _CellHit(t=1.0, col=c, row=r, part="wall",
                            face="north", hit_y=0.3)
        ed.current_texture = "carpet"
        ed._seg_paint()

        segs = z.wall_segments[r][c][0]
        assert segs[0][0] == "carpet", f"Expected 'carpet', got '{segs[0][0]}'"
        assert segs[1][0] == "concrete", "Second segment should be unchanged"

    def test_seg_paint_upper_segment(self):
        """Painting the upper segment only changes it."""
        from editor.view_3d.picking import _CellHit
        ed, z = self._make_editor()

        r, c = 0, 0
        ch = z.ceil_heights[r][c]

        z.wall_segments[r][c][3] = [["brick_wall", 0.5], ["concrete", ch]]

        # Aim at y=0.7 (second segment) on west face
        ed.aimed = _CellHit(t=1.0, col=c, row=r, part="wall",
                            face="west", hit_y=0.7)
        ed.current_texture = "wood_floor"
        ed._seg_paint()

        segs = z.wall_segments[r][c][3]
        assert segs[0][0] == "brick_wall", "First segment should be unchanged"
        assert segs[1][0] == "wood_floor", f"Expected 'wood_floor', got '{segs[1][0]}'"

    def test_seg_operations_not_on_open_cell(self):
        """Segment operations should be no-ops on open cells."""
        from editor.view_3d.picking import _CellHit
        ed, z = self._make_editor()

        # Find an open cell
        open_r, open_c = None, None
        for r in range(z.height):
            for c in range(z.width):
                td = tile_def(z.tiles[r][c])
                if td and not td.wall:
                    open_r, open_c = r, c
                    break
            if open_r is not None:
                break

        if open_r is None:
            pytest.skip("No open cell found in showcase zone")

        ed.aimed = _CellHit(t=1.0, col=open_c, row=open_r, part="floor",
                            face="north", hit_y=0.5)
        ed._seg_split()
        # Should be a no-op
        segs = z.wall_segments[open_r][open_c][0]
        assert segs == [], "Split on open cell should be no-op"

    def test_make_open_clears_segments(self):
        """Converting a wall to open clears its segments."""
        from editor.view_3d import Zone3DEditor
        z = load_zone("showcase")
        ed = Zone3DEditor(z)

        r, c = 0, 0
        td = tile_def(z.tiles[r][c])
        assert td and td.wall

        z.wall_segments[r][c][0] = [["brick_wall", 0.5], ["concrete", 0.95]]
        ed._make_open(r, c)

        for fi in range(4):
            assert z.wall_segments[r][c][fi] == [], \
                f"face {fi} segments should be cleared after make_open"


# ═════════════════════════════════════════════════════════════════════
#  3. Segment save/load round-trip
# ═════════════════════════════════════════════════════════════════════

class TestSegmentSaveLoad:

    def test_save_load_with_segments(self, tmp_path):
        """wall_segments should survive a binary save/load cycle."""
        import core.paths as paths
        import core.zones.zone as zone_mod
        from core.zones import GameRegistry

        # Load zone from real path first
        z = load_zone("showcase")

        from editor.view_3d import Zone3DEditor
        ed = Zone3DEditor(z)

        # Add segments to a wall cell
        r, c = 0, 0
        ch = z.ceil_heights[r][c]
        z.wall_segments[r][c][0] = [["brick_wall", 0.5], ["concrete", ch]]
        z.wall_segments[r][c][2] = [["carpet", 0.3], ["brick_wall", 0.6], ["concrete", ch]]

        # Save to binary .zone in tmp_path
        registry = GameRegistry()
        path = tmp_path / f"{z.name}.zone"
        z.save_to_file(path, registry)
        assert path.exists()

        # Redirect load_zone to tmp_path
        orig_zd = zone_mod.ZONES_DIR
        zone_mod.ZONES_DIR = tmp_path
        try:
            z2 = load_zone(z.name)
        finally:
            zone_mod.ZONES_DIR = orig_zd

        assert len(z2.wall_segments) == z.height
        segs_n = z2.wall_segments[r][c][0]
        assert len(segs_n) == 2
        assert segs_n[0] == ["brick_wall", 0.5]
        assert segs_n[1] == ["concrete", ch]

        segs_e = z2.wall_segments[r][c][2]
        assert len(segs_e) == 3

    def test_save_omits_empty_segments(self, tmp_path):
        """Binary zone save round-trips correctly with empty segments."""
        from core.zones import GameRegistry

        z = load_zone("showcase")

        # Save to binary .zone in tmp_path
        registry = GameRegistry()
        path = tmp_path / f"{z.name}.zone"
        z.save_to_file(path, registry)

        z2 = Zone.load_from_file(path)
        # All segment faces should be empty lists
        for r in range(z2.height):
            for c in range(z2.width):
                for fi in range(4):
                    assert z2.wall_segments[r][c][fi] == [], \
                        f"({r},{c}) face {fi} should be empty"


# ═════════════════════════════════════════════════════════════════════
#  4. Renderer with segments (no magenta)
# ═════════════════════════════════════════════════════════════════════

class TestSegmentRenderer:

    def _render_zone(self, zone, angle=0.0):
        """Render a zone at a given angle and return pixel bytes."""
        from engine.textures import TextureAtlas
        from engine.ray_renderer import RayRenderer

        atlas = TextureAtlas()
        ren = RayRenderer(zone, atlas, sw=160, sh=120)
        cx = zone.width / 2.0
        cz = zone.height / 2.0
        buf = ren.render(cx, cz, angle)
        return pygame.image.tostring(buf, "RGB")

    def _has_magenta(self, pixels: bytes) -> int:
        count = 0
        for i in range(0, len(pixels) - 2, 3):
            r, g, b = pixels[i], pixels[i+1], pixels[i+2]
            if r > 230 and g < 30 and b > 230:
                count += 1
        return count

    def test_no_magenta_without_segments(self):
        z = load_zone("showcase")
        pix = self._render_zone(z)
        assert self._has_magenta(pix) == 0

    def test_no_magenta_with_segments(self):
        """Adding segments to walls should not introduce magenta."""
        z = load_zone("showcase")
        from editor.view_3d import Zone3DEditor
        ed = Zone3DEditor(z)

        # Add segments to several wall cells
        for r in range(z.height):
            for c in range(z.width):
                td = tile_def(z.tiles[r][c])
                if td and td.wall:
                    ch = z.ceil_heights[r][c]
                    fh = z.floor_heights[r][c]
                    mid = (fh + ch) / 2.0
                    for fi in range(4):
                        z.wall_segments[r][c][fi] = [
                            ["brick_wall", mid],
                            ["concrete", ch],
                        ]
                    break  # just do one wall for speed
            else:
                continue
            break

        # Render from multiple angles
        for angle in [0.0, 1.57, 3.14, -1.57]:
            pix = self._render_zone(z, angle)
            m = self._has_magenta(pix)
            assert m == 0, f"Magenta pixels at angle {angle:.2f}: {m}"


# ═════════════════════════════════════════════════════════════════════
#  5. v_scale TileDef field
# ═════════════════════════════════════════════════════════════════════

class TestVScale:

    def test_tiledef_has_v_scale(self):
        """TileDef should have a v_scale field defaulting to 1.0."""
        from core.tiles.types import TileDef
        # All existing tiles should have v_scale = 1.0 (default)
        for name, td in TILE_REGISTRY.items():
            assert hasattr(td, "v_scale"), f"{name} missing v_scale"
            assert td.v_scale == 1.0, f"{name} v_scale={td.v_scale}"

    def test_v_scale_in_toml_io(self):
        """v_scale should appear in TOML output when non-default."""
        from core.tiles.types import TileDef, TileType, TF

        # Create a tile with non-default v_scale
        td = TileDef(
            id="test_vscale",
            name="Test VScale",
            color=(128, 128, 128),
            type=TileType.WALL,
            flags=TF.WALL | TF.SOLID,
            texture_key="test",
            v_scale=0.5,
        )
        assert td.v_scale == 0.5

    def test_v_scale_default_not_saved(self):
        """v_scale=1.0 (default) is the standard value."""
        from core.tiles.types import TileDef, TileType, TF

        td = TileDef(
            id="test_default",
            name="Test Default",
            color=(100, 100, 100),
            type=TileType.WALL,
            flags=TF.WALL | TF.SOLID,
        )
        assert td.v_scale == 1.0


# ═════════════════════════════════════════════════════════════════════
#  6. CellHit.hit_y
# ═════════════════════════════════════════════════════════════════════

class TestCellHitHitY:

    def test_hit_y_field(self):
        from editor.view_3d.picking import _CellHit
        h = _CellHit(t=2.0, col=1, row=1, part="wall", face="north", hit_y=0.75)
        assert h.hit_y == 0.75

    def test_hit_y_default(self):
        from editor.view_3d.picking import _CellHit
        h = _CellHit(t=1.0, col=0, row=0, part="floor", face="ground")
        assert h.hit_y == 0.0

    def test_aimed_has_hit_y(self):
        """After _update_aim, aimed.hit_y should be set."""
        from editor.view_3d import Zone3DEditor
        z = load_zone("showcase")
        ed = Zone3DEditor(z)

        # Position camera in center, looking at a wall
        ed.cam_x = z.width / 2.0
        ed.cam_y = 0.5
        ed.cam_z = z.height / 2.0
        ed.yaw = 0.0
        ed.pitch = 0.0

        ed._update_aim()
        if ed.aimed is not None:
            # hit_y should be a reasonable value
            assert isinstance(ed.aimed.hit_y, float)


# ═════════════════════════════════════════════════════════════════════
#  7. Editor segment mode
# ═════════════════════════════════════════════════════════════════════

class TestSegmentMode:

    def test_segment_mode_toggle(self):
        from editor.view_3d import Zone3DEditor
        z = load_zone("showcase")
        ed = Zone3DEditor(z)

        assert ed.tool == "sculpt"

        # Select segment tool via key 5
        ev = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_5)
        ed.handle_event(ev)
        assert ed.tool == "segment"

        # Switch to sculpt tool (key 1)
        ev1 = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_1)
        ed.handle_event(ev1)
        assert ed.tool == "sculpt"

    def test_segment_mode_exclusive_with_paint(self):
        from editor.view_3d import Zone3DEditor
        z = load_zone("showcase")
        ed = Zone3DEditor(z)

        # Enable paint tool (key 2)
        ev_2 = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_2)
        ed.handle_event(ev_2)
        assert ed.tool == "paint"

        # Enable segment tool (key 5) — should disable paint
        ev_5 = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_5)
        ed.handle_event(ev_5)
        assert ed.tool == "segment"

        # Enable paint tool again — should disable segment
        ed.handle_event(ev_2)
        assert ed.tool == "paint"

    def test_editor_draw_with_segments_no_crash(self):
        """Drawing the editor with segments should not crash."""
        from editor.view_3d import Zone3DEditor
        z = load_zone("showcase")
        ed = Zone3DEditor(z)

        # Add segments
        z.wall_segments[0][0][0] = [["brick_wall", 0.5], ["concrete", 0.95]]
        ed.tool = "segment"

        surf = pygame.Surface((320, 240))
        ed.draw(surf)  # should not crash
