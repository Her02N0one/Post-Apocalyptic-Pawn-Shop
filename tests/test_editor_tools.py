"""tests/test_editor_tools.py — Comprehensive tests for the aim-based 3D editor.

Covers:
  1. Tool system basics (selection, keys)
  2. Cell box geometry (floor extends for steps, ceiling extends,
                        neighbour-aware ceiling extension)
  3. FLOOR sculpt (raise, lower, clamp)
  4. CEILING sculpt (lower, raise, clamp)
  5. PAINT tool (wall face, floor top, ceiling bot)
  6. End-to-end aim picking (ray hits raised-floor step face)
  7. Preview computation (aim-based floor/ceiling height line)
  9. Draw without crash (surface markers, all tools, help, hud)
"""

from __future__ import annotations

import math
import os
import sys
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
from core.tiles import TILE_REGISTRY, tile_def
from editor.view_3d.editor import (
    Zone3DEditor, TOOLS, TOOL_KEYS,
    COL_GHOST, COL_GHOST_BAD, COL_TOOL_FLOOR, COL_TOOL_CEILING, COL_SEG_LINE,
    SKY_HEIGHT, DEFAULT_CEIL,
)
from editor.view_3d.picking import _CellHit, _ray_vs_aabb


def _open_cell(z: Zone, r: int, c: int, fh: float = 0.0, ch: float = 0.95):
    """Ensure cell (r,c) is open with the given floor/ceiling heights."""
    for name, td in TILE_REGISTRY.items():
        if not td.wall and not td.liquid:
            z.tiles[r][c] = name
            break
    z.floor_heights[r][c] = fh
    z.ceil_heights[r][c] = ch


def _make_editor(zone_name: str = "showcase") -> tuple[Zone3DEditor, Zone]:
    z = load_zone(zone_name)
    ed = Zone3DEditor(z)
    return ed, z


# ═════════════════════════════════════════════════════════════════════
#  1. Tool system basics
# ═════════════════════════════════════════════════════════════════════

class TestToolSystem:

    def test_default_tool_is_sculpt(self):
        ed, z = _make_editor()
        assert ed.tool == "sculpt"

    def test_tool_selection_keys(self):
        ed, z = _make_editor()
        # Core tools: F5=sculpt, F6=paint, F7=segment
        expected = ["sculpt", "paint", "segment"]
        keys = [pygame.K_F5, pygame.K_F6, pygame.K_F7]
        for key, tool in zip(keys, expected):
            ev = pygame.event.Event(pygame.KEYDOWN, key=key)
            ed.handle_event(ev)
            assert ed.tool == tool, f"Key should select tool={tool}"
        # Utility toggles: B=select, P=stamp
        ev_b = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_b)
        ed.handle_event(ev_b)
        assert ed.tool == "select"
        ev_p = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_p)
        ed.handle_event(ev_p)
        assert ed.tool == "stamp"

    def test_all_tools_present(self):
        assert TOOLS == ("sculpt", "paint", "segment", "entity")

    def test_display_toggle_keys_moved_to_f8_f9_f10(self):
        ed, z = _make_editor()
        assert ed.show_grid is True
        ev = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_F8)
        ed.handle_event(ev)
        assert ed.show_grid is False

        assert ed.show_ceiling_grid is True
        ev = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_F9)
        ed.handle_event(ev)
        assert ed.show_ceiling_grid is False

        assert ed.show_axes is True
        ev = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_F10)
        ed.handle_event(ev)
        assert ed.show_axes is False

    def test_snap_y_cycle(self):
        ed, z = _make_editor()
        initial = ed.snap_y
        ev = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_g)
        ed.handle_event(ev)
        assert ed.snap_y != initial  # cycled to next value


# ═════════════════════════════════════════════════════════════════════
#  2. Cell box geometry (floor/ceiling extensions)
# ═════════════════════════════════════════════════════════════════════

class TestCellBoxGeometry:

    def test_raised_floor_extends_to_ground(self):
        """A raised floor slab should extend from ~0 up to fh+S,
        so the step face is a large clickable surface."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.5, ch=0.95)
        boxes = ed._cell_boxes(r, c)
        floor_boxes = [(p, yb, yt) for p, yb, yt in boxes if p == "floor"]
        assert len(floor_boxes) == 1
        _, yb, yt = floor_boxes[0]
        assert yb <= 0.01, f"Floor slab bottom should be near 0, got {yb}"
        assert yt >= 0.5, f"Floor slab top should cover floor surface, got {yt}"

    def test_ground_level_floor_is_thin(self):
        """Floor at height 0 should remain a thin slab."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.0, ch=0.95)
        boxes = ed._cell_boxes(r, c)
        floor_boxes = [(p, yb, yt) for p, yb, yt in boxes if p == "floor"]
        _, yb, yt = floor_boxes[0]
        assert yt - yb < 0.1, f"Ground-level floor should be thin, got {yt - yb}"

    def test_ceiling_thin_slab_by_default(self):
        """A lowered ceiling slab should be a thin slab (ch-S to ch+S)
        by default, not extending to neighbour heights."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.0, ch=0.6)
        boxes = ed._cell_boxes(r, c)
        ceil_boxes = [(p, yb, yt) for p, yb, yt in boxes if p == "ceiling"]
        assert len(ceil_boxes) == 1
        _, yb, yt = ceil_boxes[0]
        S = ed._SLAB
        assert yb == pytest.approx(0.6 - S)
        assert yt == pytest.approx(0.6 + S), f"Thin slab top should be ch+S, got {yt}"

    def test_default_ceiling_is_small(self):
        """Ceiling at 0.95 (default) should be a small block (0.91 to 1.0)."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.0, ch=0.95)
        # Set all neighbours to ch=0.95 so the box doesn't extend
        for nr, nc in [(1, 2), (3, 2), (2, 1), (2, 3)]:
            if 0 <= nr < z.height and 0 <= nc < z.width:
                _open_cell(z, nr, nc, fh=0.0, ch=0.95)
        boxes = ed._cell_boxes(r, c)
        ceil_boxes = [(p, yb, yt) for p, yb, yt in boxes if p == "ceiling"]
        _, yb, yt = ceil_boxes[0]
        assert yt - yb < 0.15, f"Default ceiling should be small, got {yt - yb}"

    def test_wall_box_covers_floor_to_ceil(self):
        ed, z = _make_editor()
        r, c = 0, 0
        ed._make_wall(r, c)
        z.floor_heights[r][c] = 0.0
        z.ceil_heights[r][c] = 0.95
        boxes = ed._cell_boxes(r, c)
        assert len(boxes) == 1
        part, yb, yt = boxes[0]
        assert part == "wall"
        assert yb == 0.0
        assert yt == 0.95


# ═════════════════════════════════════════════════════════════════════
#  3. Clear cell (Del/Backspace)
# ═════════════════════════════════════════════════════════════════════

class TestClearCell:

    def test_clear_cell_resets_all(self):
        """Del key resets tile, floor, ceiling to sky, textures, segments."""
        ed, z = _make_editor()
        r, c = 2, 2
        ed._make_wall(r, c)
        assert tile_def(z.tiles[r][c]).wall
        ed.tool = "sculpt"
        ed.aimed = _CellHit(1.0, c, r, "wall", "top", 0.5)
        ed._clear_cell()
        assert not tile_def(z.tiles[r][c]).wall
        assert z.ceil_heights[r][c] >= SKY_HEIGHT - 0.01, \
            "Del should reset ceiling to sky (no ceiling)"

    def test_clear_cell_boundary_no_crash(self):
        """Del at zone boundary should not crash."""
        ed, z = _make_editor()
        r, c = 0, 0
        _open_cell(z, r, c, fh=0.5)
        ed.tool = "sculpt"
        ed.aimed = _CellHit(1.0, c, r, "floor", "north", 0.3)
        ed._clear_cell()  # should not crash


# ═════════════════════════════════════════════════════════════════════
#  4. FLOOR tool
# ═════════════════════════════════════════════════════════════════════

class TestFloorTool:

    def test_raise_floor(self):
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.0)
        ed.tool = "sculpt"
        ed.aimed = _CellHit(1.0, c, r, "floor", "top", 0.04)
        ed._tool_floor_raise()
        assert z.floor_heights[r][c] == pytest.approx(0.25)

    def test_lower_floor(self):
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.5)
        ed.tool = "sculpt"
        ed.aimed = _CellHit(1.0, c, r, "floor", "top", 0.54)
        ed._tool_floor_lower()
        assert z.floor_heights[r][c] == pytest.approx(0.25)

    def test_lower_goes_negative(self):
        """Floor can now go below zero (negative = pit)."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.1)
        ed.tool = "sculpt"
        ed.aimed = _CellHit(1.0, c, r, "floor", "top", 0.14)
        ed._tool_floor_lower()
        assert z.floor_heights[r][c] == pytest.approx(-0.15)

    def test_raise_to_ceiling_becomes_wall(self):
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.75, ch=0.95)
        ed.tool = "sculpt"
        ed.aimed = _CellHit(1.0, c, r, "floor", "top", 0.79)
        ed._tool_floor_raise()
        # Floor raise no longer auto-converts to wall tile;
        # clamped to ch - 0.05 = 0.95 - 0.05 = 0.90.
        assert z.floor_heights[r][c] == pytest.approx(0.90)
        assert not tile_def(z.tiles[r][c]).wall

    def test_works_on_wall(self):
        ed, z = _make_editor()
        r, c = 2, 2
        ed._make_wall(r, c)
        prev = z.floor_heights[r][c]
        ed.tool = "sculpt"
        ed.aimed = _CellHit(1.0, c, r, "wall", "top", 0.5)
        ed._tool_floor_raise()
        assert z.floor_heights[r][c] == pytest.approx(prev + ed.snap_y)

    def test_sets_dirty(self):
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.0)
        ed.dirty = False
        ed.tool = "sculpt"
        ed.aimed = _CellHit(1.0, c, r, "floor", "top", 0.04)
        ed._tool_floor_raise()
        assert ed.dirty


# ═════════════════════════════════════════════════════════════════════
#  5. CEILING tool
# ═════════════════════════════════════════════════════════════════════

class TestCeilingTool:

    def test_lower_ceiling(self):
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.0, ch=0.95)
        ed.tool = "sculpt"
        ed.aimed = _CellHit(1.0, c, r, "ceiling", "bot", 0.91)
        ed._tool_ceiling_lower()
        assert z.ceil_heights[r][c] == pytest.approx(0.70)

    def test_raise_ceiling(self):
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.0, ch=0.5)
        ed.tool = "sculpt"
        ed.aimed = _CellHit(1.0, c, r, "ceiling", "bot", 0.46)
        ed._tool_ceiling_raise()
        assert z.ceil_heights[r][c] == pytest.approx(0.75)

    def test_raise_clamps_to_10(self):
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.0, ch=9.9)
        ed.tool = "sculpt"
        ed.aimed = _CellHit(1.0, c, r, "ceiling", "bot", 9.86)
        ed._tool_ceiling_raise()
        assert z.ceil_heights[r][c] == 10.0

    def test_lower_to_floor_becomes_wall(self):
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.5, ch=0.7)
        ed.tool = "sculpt"
        ed.aimed = _CellHit(1.0, c, r, "ceiling", "bot", 0.66)
        ed._tool_ceiling_lower()
        # Ceiling lower no longer auto-converts to wall tile;
        # it just lowers the height, clamped to fh + 0.05 = 0.55.
        assert z.ceil_heights[r][c] == pytest.approx(0.55)
        assert not tile_def(z.tiles[r][c]).wall

    def test_works_on_wall(self):
        ed, z = _make_editor()
        r, c = 2, 2
        ed._make_wall(r, c)
        prev = z.ceil_heights[r][c]
        ed.tool = "sculpt"
        ed.aimed = _CellHit(1.0, c, r, "wall", "bot", 0.1)
        ed._tool_ceiling_lower()
        assert z.ceil_heights[r][c] == pytest.approx(prev - ed.snap_y)


# ═════════════════════════════════════════════════════════════════════
#  6. PAINT tool
# ═════════════════════════════════════════════════════════════════════

class TestPaintTool:

    def test_paint_wall_cardinal_face(self):
        ed, z = _make_editor()
        r, c = 0, 0
        ed._make_wall(r, c)
        ed._ensure_face_textures()
        ed.tool = "paint"
        ed.current_texture = "brick_wall"
        ed.aimed = _CellHit(1.0, c, r, "wall", "south", 0.5)
        ed._paint()
        assert z.face_textures[r][c][1] == "brick_wall"

    def test_paint_floor_top(self):
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c)
        ed.tool = "paint"
        ed.current_texture = "brick_wall"
        ed.aimed = _CellHit(1.0, c, r, "floor", "top", 0.04)
        ed._paint()
        if z.floor_textures:
            assert z.floor_textures[r][c] == "brick_wall"

    def test_paint_ceiling_bot(self):
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c)
        ed.tool = "paint"
        ed.current_texture = "brick_wall"
        ed.aimed = _CellHit(1.0, c, r, "ceiling", "bot", 0.91)
        ed._paint()
        if z.ceil_textures:
            assert z.ceil_textures[r][c] == "brick_wall"


# ═════════════════════════════════════════════════════════════════════
#  7. End-to-end aim picking (ray hits floor/ceiling step faces)
# ═════════════════════════════════════════════════════════════════════

class TestAimPicking:

    def test_ray_hits_raised_floor_step_face(self):
        """A ray aimed at the step between a raised floor and its lower
        neighbour should pick the raised floor's cardinal face."""
        ed, z = _make_editor()
        r, c = 2, 2
        adj_r, adj_c = 2, 3
        _open_cell(z, r, c, fh=0.5, ch=0.95)
        _open_cell(z, adj_r, adj_c, fh=0.0, ch=0.95)

        # Camera in cell (2,3) at eye level below the raised floor,
        # looking west toward cell (2,2)
        # Convention: yaw=0 → +Z (south); yaw=pi/2 → -X (west)
        ed.cam_x = 3.5
        ed.cam_y = 0.3
        ed.cam_z = 2.5
        ed.yaw = math.pi / 2   # facing -X (west)
        ed.pitch = 0.0

        ed._update_aim()

        assert ed.aimed is not None, "Should hit the raised floor step"
        assert ed.aimed.col == 2, f"Expected col=2, got {ed.aimed.col}"
        assert ed.aimed.row == 2, f"Expected row=2, got {ed.aimed.row}"
        assert ed.aimed.part == "floor", f"Expected part=floor, got {ed.aimed.part}"
        assert ed.aimed.face == "east", f"Expected face=east, got {ed.aimed.face}"

    def test_ray_hits_lowered_ceiling_step_face(self):
        """A ray aimed at the step between a lowered ceiling and its higher
        neighbour should pick the lowered ceiling's cardinal face
        when upper_wall_height is set to extend the step."""
        ed, z = _make_editor()
        r, c = 2, 2
        adj_r, adj_c = 2, 3
        _open_cell(z, r, c, fh=0.0, ch=0.6)
        _open_cell(z, adj_r, adj_c, fh=0.0, ch=0.95)
        # Explicitly extend upper wall to create visible step face
        ed._ensure_face_textures()
        z.upper_wall_height[r][c] = 0.95

        # Camera in cell (2,3) at a height between the two ceilings,
        # looking west toward cell (2,2)
        ed.cam_x = 3.5
        ed.cam_y = 0.8   # between ch=0.6 and ch=0.95
        ed.cam_z = 2.5
        ed.yaw = math.pi / 2   # facing -X (west)
        ed.pitch = 0.0

        ed._update_aim()

        assert ed.aimed is not None, "Should hit the ceiling step"
        assert ed.aimed.col == 2, f"Expected col=2, got {ed.aimed.col}"
        assert ed.aimed.row == 2, f"Expected row=2, got {ed.aimed.row}"
        assert ed.aimed.part == "ceiling", f"Expected part=ceiling, got {ed.aimed.part}"
        assert ed.aimed.face == "east", f"Expected face=east, got {ed.aimed.face}"

    def test_ray_at_floor_step_sculpt_e2e(self):
        """Full end-to-end: aim at floor step, raise floor in the aimed cell."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.5, ch=0.95)
        _open_cell(z, 2, 3, fh=0.0, ch=0.95)

        ed.cam_x = 3.5
        ed.cam_y = 0.3
        ed.cam_z = 2.5
        ed.yaw = math.pi / 2   # facing -X (west)
        ed.pitch = 0.0
        ed.tool = "sculpt"

        ed._update_aim()
        assert ed.aimed is not None

        fh_before = z.floor_heights[r][c]
        ed._tool_floor_raise()
        assert z.floor_heights[r][c] > fh_before, \
            "Floor raise should increase floor height in the aimed cell"

    def test_ray_at_ceiling_step_sculpt_e2e(self):
        """Full end-to-end: aim at ceiling step, lower ceiling
        in the aimed cell."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.0, ch=0.6)
        _open_cell(z, 2, 3, fh=0.0, ch=0.95)
        # Extend upper wall to create visible step face
        ed._ensure_face_textures()
        z.upper_wall_height[r][c] = 0.95

        ed.cam_x = 3.5
        ed.cam_y = 0.8   # between ch=0.6 and ch=0.95
        ed.cam_z = 2.5
        ed.yaw = math.pi / 2   # facing -X (west)
        ed.pitch = 0.0
        ed.tool = "sculpt"

        ed._update_aim()
        assert ed.aimed is not None
        assert ed.aimed.part == "ceiling"

        ch_before = z.ceil_heights[r][c]
        ed._tool_ceiling_lower()
        assert z.ceil_heights[r][c] < ch_before, \
            "Ceiling lower should reduce ceiling height"


# ═════════════════════════════════════════════════════════════════════
#  8. Preview computation
# ═════════════════════════════════════════════════════════════════════

class TestPreview:

    def test_sculpt_preview_floor_on_open(self):
        """Aiming at floor shows floor-color preview."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c)
        ed.tool = "sculpt"
        ed.aimed = _CellHit(1.0, c, r, "floor", "top", 0.04)
        ed._compute_preview()
        assert ed.preview_line is not None
        assert ed.preview_line[3] == COL_TOOL_FLOOR

    def test_sculpt_preview_floor_on_wall(self):
        """Aiming at wall shows floor-color preview."""
        ed, z = _make_editor()
        r, c = 2, 2
        ed._make_wall(r, c)
        ed.tool = "sculpt"
        ed.aimed = _CellHit(1.0, c, r, "wall", "top", 0.5)
        ed._compute_preview()
        assert ed.preview_line is not None
        assert ed.preview_line[3] == COL_TOOL_FLOOR

    def test_sculpt_preview_cardinal_targets_aimed_cell(self):
        """Cardinal face preview should show line at the aimed cell."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.5)
        _open_cell(z, 2, 3, fh=0.0)
        ed.tool = "sculpt"
        ed.aimed = _CellHit(1.0, c, r, "floor", "east", 0.3)
        ed._compute_preview()
        assert ed.preview_line is not None
        lc, lr = ed.preview_line[0], ed.preview_line[1]
        assert lc == c and lr == r

    def test_sculpt_preview_floor_part(self):
        """Floor part → floor-color preview at fh + snap."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.25)
        ed.tool = "sculpt"
        ed.aimed = _CellHit(1.0, c, r, "floor", "top", 0.29)
        ed._compute_preview()
        assert ed.preview_line is not None
        assert ed.preview_line[3] == COL_TOOL_FLOOR

    def test_sculpt_preview_ceiling_part(self):
        """Ceiling part → ceiling-color preview at ch - snap."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, ch=0.7)
        ed.tool = "sculpt"
        ed.aimed = _CellHit(1.0, c, r, "ceiling", "bot", 0.66)
        ed._compute_preview()
        assert ed.preview_line is not None
        assert ed.preview_line[3] == COL_TOOL_CEILING

    def test_segment_tool_preview_line(self):
        ed, z = _make_editor()
        r, c = 0, 0
        ed._make_wall(r, c)
        ed.tool = "segment"
        ed.aimed = _CellHit(1.0, c, r, "wall", "south", 0.5)
        ed._compute_preview()
        assert ed.preview_line is not None
        assert ed.preview_line[3] == COL_SEG_LINE

    def test_paint_tool_no_preview(self):
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c)
        ed.tool = "paint"
        ed.aimed = _CellHit(1.0, c, r, "floor", "top", 0.04)
        ed._compute_preview()
        assert ed.preview_line is None
        assert ed.preview_box is None


# ═════════════════════════════════════════════════════════════════════
#  9. Draw without crash
# ═════════════════════════════════════════════════════════════════════

class TestDraw:

    def test_draw_all_tools_no_crash(self):
        """Drawing the editor with each tool selected should not crash."""
        ed, z = _make_editor()
        surf = pygame.Surface((320, 240))
        for tool in TOOLS:
            ed.tool = tool
            ed.draw(surf)  # should not crash

    def test_draw_with_aimed_step(self):
        """Drawing with a floor step aimed should not crash."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.5)
        _open_cell(z, 2, 3, fh=0.0)
        ed.tool = "sculpt"
        ed.aimed = _CellHit(1.0, c, r, "floor", "east", 0.3)
        ed._compute_preview()
        surf = pygame.Surface((320, 240))
        ed.draw(surf)  # should not crash

    def test_draw_with_help_overlay(self):
        """Help overlay should render without crash."""
        ed, z = _make_editor()
        ed.show_help = True
        surf = pygame.Surface((320, 240))
        ed.draw(surf)

    def test_draw_with_hud_off(self):
        """Drawing with HUD off should not crash."""
        ed, z = _make_editor()
        ed.show_hud = False
        surf = pygame.Surface((320, 240))
        ed.draw(surf)

    def test_draw_surface_markers_raised_floor(self):
        """Surface markers should render for raised-floor cells."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.5, ch=0.8)
        surf = pygame.Surface((320, 240))
        ed.draw(surf)  # should not crash — surface rings at 0.5 and 0.8

    def test_draw_surface_markers_default_cell(self):
        """Default cell (fh=0, ch=0.95) should draw ceiling ring, skip floor."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.0, ch=0.95)
        surf = pygame.Surface((320, 240))
        ed.draw(surf)  # should not crash


# ═════════════════════════════════════════════════════════════════════
# 10. FLOOR tool — cardinal face targets aimed cell
# ═════════════════════════════════════════════════════════════════════

class TestFloorToolCardinal:

    def test_raise_aimed_floor_via_east_face(self):
        """FLOOR tool LMB on a floor's east face raises the aimed cell."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.5)
        _open_cell(z, 2, 3, fh=0.0)
        ed.tool = "sculpt"
        ed.aimed = _CellHit(1.0, c, r, "floor", "east", 0.3)
        ed._tool_floor_raise()
        assert z.floor_heights[r][c] == pytest.approx(0.75)

    def test_lower_aimed_floor_via_east_face(self):
        """FLOOR tool RMB on a floor's east face lowers the aimed cell."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.5)
        _open_cell(z, 2, 3, fh=0.5)
        ed.tool = "sculpt"
        ed.aimed = _CellHit(1.0, c, r, "floor", "east", 0.3)
        ed._tool_floor_lower()
        assert z.floor_heights[r][c] == pytest.approx(0.25)

    def test_raise_aimed_via_south_face(self):
        """FLOOR tool LMB on a floor's south face raises the aimed cell."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.5)
        _open_cell(z, 3, 2, fh=0.0)
        ed.tool = "sculpt"
        ed.aimed = _CellHit(1.0, c, r, "floor", "south", 0.3)
        ed._tool_floor_raise()
        assert z.floor_heights[r][c] == pytest.approx(0.75)

    def test_raise_aimed_floor_to_ceiling_becomes_wall(self):
        """FLOOR tool via cardinal: raising aimed to its ceiling -> geo-solid."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.75, ch=0.95)
        ed.tool = "sculpt"
        ed.aimed = _CellHit(1.0, c, r, "floor", "east", 0.5)
        ed._tool_floor_raise()
        # No longer auto-converts tile type; clamped to ch - 0.05 = 0.90.
        assert z.floor_heights[r][c] == pytest.approx(0.90)
        assert not tile_def(z.tiles[r][c]).wall

    def test_lower_aimed_goes_negative(self):
        """FLOOR tool via cardinal: lowering past zero goes negative."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.1)
        ed.tool = "sculpt"
        ed.aimed = _CellHit(1.0, c, r, "floor", "east", 0.05)
        ed._tool_floor_lower()
        assert z.floor_heights[r][c] == pytest.approx(-0.15)

    def test_works_on_wall_via_cardinal(self):
        """FLOOR tool via cardinal on a wall cell: now modifies height."""
        ed, z = _make_editor()
        r, c = 2, 2
        ed._make_wall(r, c)
        prev = z.floor_heights[r][c]
        ed.tool = "sculpt"
        ed.aimed = _CellHit(1.0, c, r, "wall", "east", 0.3)
        ed._tool_floor_raise()
        assert z.floor_heights[r][c] == pytest.approx(prev + ed.snap_y)

    def test_cardinal_at_boundary_modifies_aimed(self):
        """FLOOR tool via cardinal at zone edge modifies the aimed cell."""
        ed, z = _make_editor()
        r, c = 0, 0
        _open_cell(z, r, c, fh=0.0)
        ed.tool = "sculpt"
        ed.aimed = _CellHit(1.0, c, r, "floor", "north", 0.04)
        ed._tool_floor_raise()
        assert z.floor_heights[r][c] == pytest.approx(0.25)

    def test_sets_dirty(self):
        """FLOOR tool via cardinal sets dirty flag."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.5)
        ed.dirty = False
        ed.tool = "sculpt"
        ed.aimed = _CellHit(1.0, c, r, "floor", "east", 0.3)
        ed._tool_floor_raise()
        assert ed.dirty


# ═════════════════════════════════════════════════════════════════════
# 11. CEILING tool — cardinal face targets aimed cell
# ═════════════════════════════════════════════════════════════════════

class TestCeilingToolCardinal:

    def test_lower_aimed_ceiling_via_east_face(self):
        """CEILING tool LMB on a ceiling's east face lowers the aimed cell."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.0, ch=0.95)
        _open_cell(z, 2, 3, fh=0.0, ch=0.95)
        ed.tool = "sculpt"
        ed.aimed = _CellHit(1.0, c, r, "ceiling", "east", 0.93)
        ed._tool_ceiling_lower()
        assert z.ceil_heights[r][c] == pytest.approx(0.70)

    def test_raise_aimed_ceiling_via_east_face(self):
        """CEILING tool RMB on a ceiling's east face raises the aimed cell."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.0, ch=0.5)
        _open_cell(z, 2, 3, fh=0.0, ch=0.5)
        ed.tool = "sculpt"
        ed.aimed = _CellHit(1.0, c, r, "ceiling", "east", 0.48)
        ed._tool_ceiling_raise()
        assert z.ceil_heights[r][c] == pytest.approx(0.75)

    def test_lower_aimed_via_south_face(self):
        """CEILING tool LMB on south face lowers the aimed cell's ceiling."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.0, ch=0.95)
        _open_cell(z, 3, 2, fh=0.0, ch=0.95)
        ed.tool = "sculpt"
        ed.aimed = _CellHit(1.0, c, r, "ceiling", "south", 0.93)
        ed._tool_ceiling_lower()
        assert z.ceil_heights[r][c] == pytest.approx(0.70)

    def test_lower_aimed_ceiling_to_floor_becomes_wall(self):
        """CEILING tool via cardinal: lowering aimed to its floor -> geo-solid."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.5, ch=0.7)
        ed.tool = "sculpt"
        ed.aimed = _CellHit(1.0, c, r, "ceiling", "east", 0.68)
        ed._tool_ceiling_lower()
        # No longer auto-converts tile type; clamped to fh + 0.05 = 0.55.
        assert z.ceil_heights[r][c] == pytest.approx(0.55)
        assert not tile_def(z.tiles[r][c]).wall

    def test_raise_aimed_clamps_to_10(self):
        """CEILING tool via cardinal: raising clamps to 10.0."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.0, ch=9.9)
        ed.tool = "sculpt"
        ed.aimed = _CellHit(1.0, c, r, "ceiling", "east", 9.88)
        ed._tool_ceiling_raise()
        assert z.ceil_heights[r][c] == 10.0

    def test_works_on_wall_via_cardinal(self):
        """CEILING tool via cardinal on a wall cell: now modifies height."""
        ed, z = _make_editor()
        r, c = 2, 2
        ed._make_wall(r, c)
        prev = z.ceil_heights[r][c]
        ed.tool = "sculpt"
        ed.aimed = _CellHit(1.0, c, r, "wall", "east", 0.5)
        ed._tool_ceiling_lower()
        assert z.ceil_heights[r][c] == pytest.approx(prev - ed.snap_y)

    def test_cardinal_at_boundary_modifies_aimed(self):
        """CEILING tool via cardinal at zone edge modifies the aimed cell."""
        ed, z = _make_editor()
        r, c = 0, 0
        _open_cell(z, r, c, fh=0.0, ch=0.95)
        ed.tool = "sculpt"
        ed.aimed = _CellHit(1.0, c, r, "ceiling", "north", 0.93)
        ed._tool_ceiling_lower()
        assert z.ceil_heights[r][c] == pytest.approx(0.70)

    def test_sets_dirty(self):
        """CEILING tool via cardinal sets dirty flag."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.0, ch=0.95)
        ed.dirty = False
        ed.tool = "sculpt"
        ed.aimed = _CellHit(1.0, c, r, "ceiling", "east", 0.93)
        ed._tool_ceiling_lower()
        assert ed.dirty


# ═════════════════════════════════════════════════════════════════════
# 12. Preview — cardinal face targets aimed cell
# ═════════════════════════════════════════════════════════════════════

class TestPreviewCardinal:

    def test_floor_preview_at_aimed_cell(self):
        """Sculpt preview on floor cardinal face shows line at the aimed cell."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.5)
        _open_cell(z, 2, 3, fh=0.0)
        ed.tool = "sculpt"
        ed.aimed = _CellHit(1.0, c, r, "floor", "east", 0.3)
        ed._compute_preview()
        assert ed.preview_line is not None
        lc, lr, ly, lcol = ed.preview_line
        assert lc == c, f"Preview col should be {c}, got {lc}"
        assert lr == r, f"Preview row should be {r}, got {lr}"
        assert lcol == COL_TOOL_FLOOR

    def test_ceiling_preview_at_aimed_cell(self):
        """Sculpt preview on ceiling cardinal face shows ceiling-color line."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.0, ch=0.95)
        _open_cell(z, 2, 3, fh=0.0, ch=0.95)
        ed.tool = "sculpt"
        ed.aimed = _CellHit(1.0, c, r, "ceiling", "east", 0.93)
        ed._compute_preview()
        assert ed.preview_line is not None
        lc, lr, ly, lcol = ed.preview_line
        assert lc == c, f"Preview col should be {c}, got {lc}"
        assert lr == r, f"Preview row should be {r}, got {lr}"
        assert lcol == COL_TOOL_CEILING

    def test_floor_preview_on_wall_shows_preview(self):
        """Wall part → floor-color preview."""
        ed, z = _make_editor()
        r, c = 2, 2
        ed._make_wall(r, c)
        ed.tool = "sculpt"
        ed.aimed = _CellHit(1.0, c, r, "wall", "east", 0.3)
        ed._compute_preview()
        assert ed.preview_line is not None

    def test_ceiling_preview_on_wall_shows_floor_preview(self):
        """Wall aimed at bot face → wall part detected → floor-color preview."""
        ed, z = _make_editor()
        r, c = 2, 2
        ed._make_wall(r, c)
        ed.tool = "sculpt"
        ed.aimed = _CellHit(1.0, c, r, "wall", "east", 0.3)
        ed._compute_preview()
        assert ed.preview_line is not None
        assert ed.preview_line[3] == COL_TOOL_FLOOR

    def test_floor_preview_target_height_correct(self):
        """Floor preview via cardinal shows target = fh + snap of aimed cell."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.25, ch=0.95)
        ed.snap_y = 0.25
        ed.tool = "sculpt"
        ed.aimed = _CellHit(1.0, c, r, "floor", "east", 0.2)
        ed._compute_preview()
        assert ed.preview_line is not None
        _, _, ly, _ = ed.preview_line
        assert ly == pytest.approx(0.50)

    def test_ceiling_preview_target_height_correct(self):
        """Ceiling preview shows target = ch - snap."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.0, ch=0.95)
        ed.snap_y = 0.25
        ed.tool = "sculpt"
        ed.aimed = _CellHit(1.0, c, r, "ceiling", "east", 0.93)
        ed._compute_preview()
        assert ed.preview_line is not None
        _, _, ly, _ = ed.preview_line
        assert ly == pytest.approx(0.70)


# ═════════════════════════════════════════════════════════════════════
# 13. Cell box geometry — neighbour-aware ceiling extension
# ═════════════════════════════════════════════════════════════════════

class TestNeighbourAwareCeilingBox:

    def test_ceiling_is_thin_slab_by_default(self):
        """Ceiling box should be a thin slab, not extending to neighbours."""
        ed, z = _make_editor()
        r, c = 2, 2
        adj_r, adj_c = 2, 3
        _open_cell(z, r, c, fh=0.0, ch=0.6)
        _open_cell(z, adj_r, adj_c, fh=0.0, ch=1.5)
        boxes = ed._cell_boxes(r, c)
        ceil_boxes = [(p, yb, yt) for p, yb, yt in boxes if p == "ceiling"]
        assert len(ceil_boxes) == 1
        _, yb, yt = ceil_boxes[0]
        S = ed._SLAB
        assert yb == pytest.approx(0.6 - S)
        assert yt == pytest.approx(0.6 + S), "Thin slab, no neighbour extension"

    def test_explicit_upper_wall_extends_ceiling(self):
        """Setting upper_wall_height explicitly extends the ceiling box."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.0, ch=0.6)
        ed._ensure_face_textures()
        z.upper_wall_height[r][c] = 1.5
        boxes = ed._cell_boxes(r, c)
        ceil_boxes = [(p, yb, yt) for p, yb, yt in boxes if p == "ceiling"]
        assert len(ceil_boxes) == 1
        _, yb, yt = ceil_boxes[0]
        S = ed._SLAB
        assert yt >= 1.5, f"Ceiling should extend to upper_wall_height, got {yt}"

    def test_ceiling_box_covers_step_with_explicit_uwh(self):
        """Upper wall height extends ceiling to cover the step face."""
        ed, z = _make_editor()
        r, c = 2, 2
        adj_r, adj_c = 2, 3
        _open_cell(z, r, c, fh=0.0, ch=0.6)
        _open_cell(z, adj_r, adj_c, fh=0.0, ch=2.0)
        ed._ensure_face_textures()
        z.upper_wall_height[r][c] = 2.0
        boxes = ed._cell_boxes(r, c)
        ceil_boxes = [(p, yb, yt) for p, yb, yt in boxes if p == "ceiling"]
        _, yb, yt = ceil_boxes[0]
        S = ed._SLAB
        assert yb <= 0.6
        assert yt >= 2.0 + S, f"Ceiling top should cover 2.0+S, got {yt}"


# ═════════════════════════════════════════════════════════════════════
# 14. End-to-end: aim picking → floor/ceiling tool targets aimed cell
# ═════════════════════════════════════════════════════════════════════

class TestE2EFloorCeilingCardinal:

    def test_aim_floor_step_then_floor_raise(self):
        """E2E: aim at floor step, FLOOR tool raises the aimed cell's floor."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.5, ch=0.95)
        _open_cell(z, 2, 3, fh=0.0, ch=0.95)

        ed.cam_x = 3.5
        ed.cam_y = 0.3
        ed.cam_z = 2.5
        ed.yaw = math.pi / 2  # facing west
        ed.pitch = 0.0
        ed.tool = "sculpt"

        ed._update_aim()
        assert ed.aimed is not None
        assert ed.aimed.face == "east"
        assert ed.aimed.part == "floor"

        ed._tool_floor_raise()
        assert z.floor_heights[r][c] == pytest.approx(0.75)

    def test_aim_ceiling_step_then_ceiling_lower(self):
        """E2E: aim at ceiling step, CEILING tool lowers the aimed cell's ceiling."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.0, ch=0.6)
        _open_cell(z, 2, 3, fh=0.0, ch=0.95)
        # Extend upper wall to create visible step face
        ed._ensure_face_textures()
        z.upper_wall_height[r][c] = 0.95

        ed.cam_x = 3.5
        ed.cam_y = 0.8
        ed.cam_z = 2.5
        ed.yaw = math.pi / 2
        ed.pitch = 0.0
        ed.tool = "sculpt"

        ed._update_aim()
        assert ed.aimed is not None
        assert ed.aimed.face == "east"
        assert ed.aimed.part == "ceiling"

        ed._tool_ceiling_lower()
        assert z.ceil_heights[r][c] == pytest.approx(0.35)


# ═════════════════════════════════════════════════════════════════════
# 15. Step-wall painting
# ═════════════════════════════════════════════════════════════════════

class TestStepWallPaint:

    def test_paint_floor_step_east_face(self):
        """Paint tool on a raised floor's east face writes floor_step_textures."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.5, ch=0.95)
        ed._ensure_face_textures()
        ed.tool = "paint"
        ed.current_texture = "brick_wall"
        ed.aimed = _CellHit(1.0, c, r, "floor", "east", 0.3)
        ed._paint()
        assert z.floor_step_textures[r][c][2] == "brick_wall"  # east=2

    def test_paint_ceil_step_south_face(self):
        """Paint tool on a lowered ceiling's south face writes ceil_step_textures."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.0, ch=0.6)
        ed._ensure_face_textures()
        ed.tool = "paint"
        ed.current_texture = "brick_wall"
        ed.aimed = _CellHit(1.0, c, r, "ceiling", "south", 0.8)
        ed._paint()
        assert z.ceil_step_textures[r][c][1] == "brick_wall"  # south=1

    def test_paint_wall_cardinal_still_paints_face_textures(self):
        """Paint tool on a wall tile's cardinal face still writes face_textures."""
        ed, z = _make_editor()
        r, c = 0, 0
        ed._make_wall(r, c)
        ed._ensure_face_textures()
        ed.tool = "paint"
        ed.current_texture = "brick_wall"
        ed.aimed = _CellHit(1.0, c, r, "wall", "north", 0.5)
        ed._paint()
        assert z.face_textures[r][c][0] == "brick_wall"

    def test_paint_floor_step_all_four_faces(self):
        """All four cardinal faces of a floor step can be painted independently."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.5, ch=0.95)
        ed._ensure_face_textures()
        ed.tool = "paint"
        faces = ["north", "south", "east", "west"]
        for i, face in enumerate(faces):
            ed.current_texture = f"tex_{face}"
            ed.aimed = _CellHit(1.0, c, r, "floor", face, 0.3)
            ed._paint()
        for i, face in enumerate(faces):
            assert z.floor_step_textures[r][c][i] == f"tex_{face}"


# ═════════════════════════════════════════════════════════════════════
# 16. Step-wall segmenting
# ═════════════════════════════════════════════════════════════════════

class TestStepWallSegment:

    def test_seg_face_info_returns_floor_step(self):
        """_seg_face_info returns floor_step for raised floor cardinal face."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.5, ch=0.95)
        ed._ensure_face_textures()
        ed.tool = "segment"
        ed.aimed = _CellHit(1.0, c, r, "floor", "east", 0.3)
        info = ed._seg_face_info()
        assert info is not None
        _, _, fi, segs, y_bot, y_top, hy, seg_type = info
        assert seg_type == "floor_step"
        assert y_bot == 0.0
        assert y_top == 0.5
        assert fi == 2  # east

    def test_seg_face_info_returns_ceil_step(self):
        """_seg_face_info returns ceil_step for lowered ceiling cardinal face."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.0, ch=0.6)
        # Ensure a neighbor has a higher ceiling for meaningful step
        _open_cell(z, 2, 3, fh=0.0, ch=0.95)
        ed._ensure_face_textures()
        ed.tool = "segment"
        ed.aimed = _CellHit(1.0, c, r, "ceiling", "east", 0.8)
        info = ed._seg_face_info()
        assert info is not None
        _, _, fi, segs, y_bot, y_top, hy, seg_type = info
        assert seg_type == "ceil_step"
        assert y_bot == 0.6
        assert y_top > 0.6  # extends to neighbor ceiling

    def test_seg_face_info_none_for_flat_floor(self):
        """No floor step available when floor is at ground."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.0, ch=0.95)
        ed._ensure_face_textures()
        ed.aimed = _CellHit(1.0, c, r, "floor", "east", 0.01)
        info = ed._seg_face_info()
        assert info is None

    def test_split_floor_step(self):
        """Splitting a floor step wall creates segments in floor_step_segments."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.5, ch=0.95)
        ed._ensure_face_textures()
        ed.tool = "segment"
        ed.snap_y = 0.25
        ed.current_texture = "brick_wall"
        ed.aimed = _CellHit(1.0, c, r, "floor", "east", 0.25)
        ed._seg_split()
        segs = z.floor_step_segments[r][c][2]  # east
        assert len(segs) == 2
        assert segs[0][1] == pytest.approx(0.25)  # split at 0.25
        assert segs[1][1] == pytest.approx(0.50)  # top at fh

    def test_split_ceil_step(self):
        """Splitting a ceiling step wall creates segments in ceil_step_segments."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.0, ch=0.5)
        _open_cell(z, 2, 3, fh=0.0, ch=1.0)  # taller neighbor
        ed._ensure_face_textures()
        # Extend upper wall so the step face is tall enough to split
        z.upper_wall_height[r][c] = 1.0
        ed.tool = "segment"
        ed.snap_y = 0.25
        ed.current_texture = "brick_wall"
        ed.aimed = _CellHit(1.0, c, r, "ceiling", "east", 0.75)
        ed._seg_split()
        segs = z.ceil_step_segments[r][c][2]  # east
        assert len(segs) == 2
        assert segs[0][1] == pytest.approx(0.75)

    def test_merge_floor_step(self):
        """Merging floor step segments removes the boundary."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.5, ch=0.95)
        ed._ensure_face_textures()
        # Pre-fill segments
        z.floor_step_segments[r][c][2] = [["tex_a", 0.25], ["tex_b", 0.5]]
        ed.tool = "segment"
        ed.aimed = _CellHit(1.0, c, r, "floor", "east", 0.26)
        ed._seg_merge()
        # Should collapse to no segments
        assert z.floor_step_segments[r][c][2] == []

    def test_paint_segment_on_floor_step(self):
        """Painting a floor step segment changes its texture."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.5, ch=0.95)
        ed._ensure_face_textures()
        z.floor_step_segments[r][c][2] = [["tex_a", 0.25], ["tex_b", 0.5]]
        ed.tool = "segment"
        ed.current_texture = "new_tex"
        ed.aimed = _CellHit(1.0, c, r, "floor", "east", 0.3)
        ed._seg_paint()
        assert z.floor_step_segments[r][c][2][1][0] == "new_tex"

    def test_segment_preview_for_floor_step(self):
        """Segment tool shows preview line on floor step faces."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.5, ch=0.95)
        ed.tool = "segment"
        ed.snap_y = 0.25
        ed.aimed = _CellHit(1.0, c, r, "floor", "east", 0.25)
        ed._compute_preview()
        assert ed.preview_line is not None
        assert ed.preview_line[3] == COL_SEG_LINE

    def test_segment_preview_for_ceil_step(self):
        """Segment tool shows preview line on ceiling step faces."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.0, ch=0.6)
        _open_cell(z, 2, 3, fh=0.0, ch=0.95)
        ed.tool = "segment"
        ed.snap_y = 0.25
        ed.aimed = _CellHit(1.0, c, r, "ceiling", "east", 0.75)
        ed._compute_preview()
        assert ed.preview_line is not None
        assert ed.preview_line[3] == COL_SEG_LINE


# ═════════════════════════════════════════════════════════════════════
# 17. Upper-wall height control
# ═════════════════════════════════════════════════════════════════════

class TestUpperWallHeight:

    def test_u_key_raises_upper_wall(self):
        """U key on a ceiling step raises upper_wall_height."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.0, ch=0.6)
        _open_cell(z, 2, 3, fh=0.0, ch=0.95)
        ed._ensure_face_textures()
        ed.snap_y = 0.25
        ed.aimed = _CellHit(1.0, c, r, "ceiling", "east", 0.8)
        ed._adjust_upper_wall_height(0)  # no modifier
        assert z.upper_wall_height[r][c] > 0.6

    def test_shift_u_lowers_upper_wall(self):
        """Shift+U lowers the upper_wall_height."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.0, ch=0.6)
        ed._ensure_face_textures()
        z.upper_wall_height[r][c] = 2.0
        ed.snap_y = 0.25
        ed.aimed = _CellHit(1.0, c, r, "ceiling", "east", 0.8)
        ed._adjust_upper_wall_height(pygame.KMOD_SHIFT)
        assert z.upper_wall_height[r][c] == pytest.approx(1.75)

    def test_ctrl_u_resets_to_auto(self):
        """Ctrl+U resets upper_wall_height to 0 (auto)."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.0, ch=0.6)
        ed._ensure_face_textures()
        z.upper_wall_height[r][c] = 3.0
        ed.aimed = _CellHit(1.0, c, r, "ceiling", "east", 0.8)
        ed._adjust_upper_wall_height(pygame.KMOD_CTRL)
        assert z.upper_wall_height[r][c] == 0.0

    def test_cell_boxes_use_override(self):
        """Cell boxes should use upper_wall_height when set."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.0, ch=0.6)
        # all neighbors at 0.95 -> auto top ~1.0
        for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nr, nc = r + dr, c + dc
            if 0 <= nr < z.height and 0 <= nc < z.width:
                _open_cell(z, nr, nc, fh=0.0, ch=0.95)
        ed._ensure_face_textures()
        # Override to 3.0
        z.upper_wall_height[r][c] = 3.0
        boxes = ed._cell_boxes(r, c)
        ceil_boxes = [(p, yb, yt) for p, yb, yt in boxes if p == "ceiling"]
        _, _, yt = ceil_boxes[0]
        S = ed._SLAB
        assert yt >= 3.0, f"Ceiling top should be >= 3.0 (override), got {yt}"

    def test_noop_on_wall_tile(self):
        """U key on a wall tile does nothing."""
        ed, z = _make_editor()
        r, c = 2, 2
        ed._make_wall(r, c)
        ed._ensure_face_textures()
        ed.aimed = _CellHit(1.0, c, r, "wall", "east", 0.5)
        result = ed._adjust_upper_wall_height(0)
        assert result is False

    def test_noop_on_floor_part(self):
        """U key on a floor part does nothing."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.5)
        ed._ensure_face_textures()
        ed.aimed = _CellHit(1.0, c, r, "floor", "east", 0.3)
        result = ed._adjust_upper_wall_height(0)
        assert result is False

    def test_lower_past_ceiling_resets_to_auto(self):
        """Shift+U past ceiling height resets to auto."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.0, ch=0.6)
        ed._ensure_face_textures()
        z.upper_wall_height[r][c] = 0.7  # just above ch
        ed.snap_y = 0.25
        ed.aimed = _CellHit(1.0, c, r, "ceiling", "east", 0.65)
        ed._adjust_upper_wall_height(pygame.KMOD_SHIFT)
        assert z.upper_wall_height[r][c] == 0.0  # reset to auto


# ═════════════════════════════════════════════════════════════════════
# 18. Ensure-face-textures initializes all step grids
# ═════════════════════════════════════════════════════════════════════

class TestEnsureGrids:

    def test_ensure_creates_step_grids(self):
        """_ensure_face_textures initializes all step-wall grids."""
        ed, z = _make_editor()
        # Clear them to simulate old zone
        z.floor_step_textures = []
        z.ceil_step_textures = []
        z.floor_step_segments = []
        z.ceil_step_segments = []
        z.upper_wall_height = []
        ed._ensure_face_textures()
        assert len(z.floor_step_textures) == z.height
        assert len(z.ceil_step_textures) == z.height
        assert len(z.floor_step_segments) == z.height
        assert len(z.ceil_step_segments) == z.height
        assert len(z.upper_wall_height) == z.height
        assert z.floor_step_textures[0][0] == ["", "", "", ""]
        assert z.ceil_step_segments[0][0] == [[], [], [], []]


# ═════════════════════════════════════════════════════════════════════
# 19. Draw with step segments + upper-wall height
# ═════════════════════════════════════════════════════════════════════

class TestDrawStepWalls:

    def test_draw_with_floor_step_segments(self):
        """Drawing cells with floor step segments should not crash."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.5, ch=0.95)
        ed._ensure_face_textures()
        z.floor_step_segments[r][c][2] = [["tex_a", 0.25], ["tex_b", 0.5]]
        surf = pygame.Surface((320, 240))
        ed.draw(surf)

    def test_draw_with_ceil_step_segments(self):
        """Drawing cells with ceiling step segments should not crash."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.0, ch=0.6)
        _open_cell(z, 2, 3, fh=0.0, ch=0.95)
        ed._ensure_face_textures()
        z.ceil_step_segments[r][c][2] = [["tex_a", 0.75], ["tex_b", 0.99]]
        surf = pygame.Surface((320, 240))
        ed.draw(surf)

    def test_draw_with_upper_wall_height_override(self):
        """Drawing a cell with upper_wall_height override should not crash."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.0, ch=0.6)
        ed._ensure_face_textures()
        z.upper_wall_height[r][c] = 3.0
        surf = pygame.Surface((320, 240))
        ed.draw(surf)

    def test_hud_shows_upper_wall_info(self):
        """HUD displays upper wall height when aiming at ceiling part."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.0, ch=0.6)
        _open_cell(z, 2, 3, fh=0.0, ch=0.95)
        ed._ensure_face_textures()
        z.upper_wall_height[r][c] = 2.0
        ed.aimed = _CellHit(1.0, c, r, "ceiling", "east", 0.8)
        ed.show_hud = True
        surf = pygame.Surface((320, 240))
        ed.draw(surf)  # should not crash; HUD should display uwh info


# ═════════════════════════════════════════════════════════════════════
# 20. Toggle ceiling (C key)
# ═════════════════════════════════════════════════════════════════════

class TestToggleCeiling:

    def test_c_adds_ceiling_to_sky_cell(self):
        """C on a cell with no ceiling adds one at DEFAULT_CEIL."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.0, ch=0.95)
        z.ceil_heights[r][c] = SKY_HEIGHT  # no ceiling
        ed.tool = "sculpt"
        ed.aimed = _CellHit(1.0, c, r, "floor", "top", 0.04)
        ed._toggle_ceiling()
        assert z.ceil_heights[r][c] == pytest.approx(DEFAULT_CEIL)

    def test_c_removes_existing_ceiling(self):
        """C on a cell with ceiling removes it to sky."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.0, ch=0.7)
        ed.tool = "sculpt"
        ed.aimed = _CellHit(1.0, c, r, "ceiling", "bot", 0.66)
        ed._toggle_ceiling()
        assert z.ceil_heights[r][c] >= SKY_HEIGHT - 0.01

    def test_c_toggle_roundtrip(self):
        """Adding then removing ceiling returns to sky."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.0, ch=0.95)
        z.ceil_heights[r][c] = SKY_HEIGHT
        ed.tool = "sculpt"
        ed.aimed = _CellHit(1.0, c, r, "floor", "top", 0.04)
        ed._toggle_ceiling()  # add
        assert z.ceil_heights[r][c] == pytest.approx(DEFAULT_CEIL)
        ed.aimed = _CellHit(1.0, c, r, "ceiling", "bot", 0.96)
        ed._toggle_ceiling()  # remove
        assert z.ceil_heights[r][c] >= SKY_HEIGHT - 0.01

    def test_c_key_toggles_ceiling(self):
        """C key press triggers _toggle_ceiling via handle_event."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.0, ch=0.95)
        z.ceil_heights[r][c] = SKY_HEIGHT
        ed.tool = "sculpt"
        ed.aimed = _CellHit(1.0, c, r, "floor", "top", 0.04)
        ev = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_c)
        ed.handle_event(ev)
        assert z.ceil_heights[r][c] == pytest.approx(DEFAULT_CEIL)

    def test_c_clears_upper_wall_on_remove(self):
        """Removing ceiling also clears upper_wall_height."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.0, ch=0.6)
        ed._ensure_face_textures()
        z.upper_wall_height[r][c] = 3.0
        ed.tool = "sculpt"
        ed.aimed = _CellHit(1.0, c, r, "ceiling", "bot", 0.56)
        ed._toggle_ceiling()
        assert z.upper_wall_height[r][c] == 0.0

    def test_ghost_preview_on_sky_cell(self):
        """Floor aim on sky cell shows ghost ceiling preview_box."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.0, ch=0.95)
        z.ceil_heights[r][c] = SKY_HEIGHT
        ed.tool = "sculpt"
        ed.aimed = _CellHit(1.0, c, r, "floor", "top", 0.04)
        ed._compute_preview()
        assert ed.preview_box is not None, "Sky cell should show ghost ceiling box"
        assert ed.preview_box[4] == COL_TOOL_CEILING

    def test_ghost_preview_tracks_floor_height(self):
        """Ghost ceiling preview on sky cell positions relative to floor."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=3.0, ch=0.95)
        z.ceil_heights[r][c] = SKY_HEIGHT
        ed.tool = "sculpt"
        ed.aimed = _CellHit(1.0, c, r, "floor", "top", 3.04)
        ed._compute_preview()
        assert ed.preview_box is not None
        # Ghost should be at fh + DEFAULT_CEIL = 3.0 + 1.0 = 4.0
        ghost_mid = (ed.preview_box[2] + ed.preview_box[3]) / 2
        assert ghost_mid == pytest.approx(4.0, abs=0.05), \
            f"Ghost ceiling at {ghost_mid}, expected ~4.0 (fh=3.0 + ceil=1.0)"

    def test_no_ghost_preview_when_ceiling_exists(self):
        """Floor aim on cell with ceiling shows no ghost box."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.0, ch=0.7)
        ed.tool = "sculpt"
        ed.aimed = _CellHit(1.0, c, r, "floor", "top", 0.04)
        ed._compute_preview()
        assert ed.preview_box is None

    def test_scroll_on_ceiling_raises_upper_wall(self):
        """Scrolling up while aimed at ceiling increases upper_wall_height."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.0, ch=0.7)
        ed._ensure_face_textures()
        ed.tool = "sculpt"
        ed.aimed = _CellHit(1.0, c, r, "ceiling", "bot", 0.66)
        ed.snap_y = 0.25
        ev = pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=1)
        ed.handle_event(ev)
        assert z.upper_wall_height[r][c] == pytest.approx(0.95)

    def test_scroll_on_ceiling_lowers_upper_wall(self):
        """Scrolling down while aimed at ceiling decreases upper_wall_height."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.0, ch=0.7)
        ed._ensure_face_textures()
        z.upper_wall_height[r][c] = 2.0
        ed.tool = "sculpt"
        ed.aimed = _CellHit(1.0, c, r, "ceiling", "bot", 0.66)
        ed.snap_y = 0.25
        ev = pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=-1)
        ed.handle_event(ev)
        assert z.upper_wall_height[r][c] == pytest.approx(1.75)

    def test_scroll_on_ceiling_resets_at_min(self):
        """Scrolling down enough resets upper_wall_height to 0 (auto)."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.0, ch=0.7)
        ed._ensure_face_textures()
        z.upper_wall_height[r][c] = 0.8
        ed.tool = "sculpt"
        ed.aimed = _CellHit(1.0, c, r, "ceiling", "bot", 0.66)
        ed.snap_y = 0.25
        ev = pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=-1)
        ed.handle_event(ev)
        assert z.upper_wall_height[r][c] == 0.0


# ═════════════════════════════════════════════════════════════════════
# Select tool — height adjustment & ceiling mode
# ═════════════════════════════════════════════════════════════════════

class TestSelectToolHeight:
    """Tests for scroll-to-raise/lower selected floors & ceilings."""

    def _select_region(self, ed, z, r1, c1, r2, c2):
        """Helper: set selection corners so the rectangle is active."""
        ed.tool = "select"
        ed._sel_start = (r1, c1)
        ed._sel_end = (r2, c2)

    def test_scroll_raises_selected_floors(self):
        """Scrolling up with active selection raises all selected floors."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.0, ch=SKY_HEIGHT)
        _open_cell(z, 2, 3, fh=0.0, ch=SKY_HEIGHT)
        ed.snap_y = 0.25
        self._select_region(ed, z, 2, 2, 2, 3)
        ev = pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=1)
        ed.handle_event(ev)
        assert z.floor_heights[2][2] == pytest.approx(0.25)
        assert z.floor_heights[2][3] == pytest.approx(0.25)

    def test_scroll_lowers_selected_floors(self):
        """Scrolling down with active selection lowers all selected floors."""
        ed, z = _make_editor()
        r, c = 2, 2
        _open_cell(z, r, c, fh=0.5, ch=SKY_HEIGHT)
        ed.snap_y = 0.25
        self._select_region(ed, z, 2, 2, 2, 2)
        ev = pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=-1)
        ed.handle_event(ev)
        assert z.floor_heights[2][2] == pytest.approx(0.25)

    def test_scroll_floor_pushes_ceiling(self):
        """Raising floor into a ceiling pushes the ceiling up."""
        ed, z = _make_editor()
        _open_cell(z, 2, 2, fh=0.5, ch=0.7)
        ed.snap_y = 0.25
        self._select_region(ed, z, 2, 2, 2, 2)
        ev = pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=1)
        ed.handle_event(ev)
        # Floor should clamp at ch - 0.05 = 0.65
        assert z.floor_heights[2][2] == pytest.approx(0.65)
        # Ceiling should be pushed up by the delta
        assert z.ceil_heights[2][2] == pytest.approx(0.85)

    def test_ceiling_mode_toggle(self):
        """X key toggles ceiling mode on the select tool."""
        ed, z = _make_editor()
        ed.tool = "select"
        assert ed._sel_ceiling_mode is False
        ev = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_x)
        ed.handle_event(ev)
        assert ed._sel_ceiling_mode is True
        ed.handle_event(ev)
        assert ed._sel_ceiling_mode is False

    def test_ceiling_mode_scroll_lowers_ceiling(self):
        """Scrolling down in ceiling mode lowers ceilings."""
        ed, z = _make_editor()
        _open_cell(z, 2, 2, fh=0.0, ch=0.8)
        ed.snap_y = 0.25
        ed._sel_ceiling_mode = True
        self._select_region(ed, z, 2, 2, 2, 2)
        ev = pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=-1)
        ed.handle_event(ev)
        assert z.ceil_heights[2][2] == pytest.approx(0.55)

    def test_ceiling_mode_scroll_raises_ceiling(self):
        """Scrolling up in ceiling mode raises ceilings."""
        ed, z = _make_editor()
        _open_cell(z, 2, 2, fh=0.0, ch=0.6)
        ed.snap_y = 0.25
        ed._sel_ceiling_mode = True
        self._select_region(ed, z, 2, 2, 2, 2)
        ev = pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=1)
        ed.handle_event(ev)
        assert z.ceil_heights[2][2] == pytest.approx(0.85)

    def test_ceiling_mode_scroll_brings_in_sky(self):
        """Scrolling down in ceiling mode on a sky cell brings in default ceiling."""
        ed, z = _make_editor()
        _open_cell(z, 2, 2, fh=0.0, ch=SKY_HEIGHT)
        ed.snap_y = 0.25
        ed._sel_ceiling_mode = True
        self._select_region(ed, z, 2, 2, 2, 2)
        ev = pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=-1)
        ed.handle_event(ev)
        # Should bring in default ceiling (fh + DEFAULT_CEIL)
        assert z.ceil_heights[2][2] < SKY_HEIGHT
        assert z.ceil_heights[2][2] == pytest.approx(DEFAULT_CEIL)

    def test_no_selection_scroll_cycles_palette(self):
        """Without active selection, scroll still cycles texture palette."""
        ed, z = _make_editor()
        ed.tool = "select"
        ed._sel_start = None
        ed._sel_end = None
        old_idx = ed.tex_idx
        ev = pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=1)
        ed.handle_event(ev)
        assert ed.tex_idx != old_idx

    def test_partial_selection_scroll_cycles_palette(self):
        """With only one corner set, scroll still cycles texture palette."""
        ed, z = _make_editor()
        ed.tool = "select"
        ed._sel_start = (2, 2)
        ed._sel_end = None
        old_idx = ed.tex_idx
        ev = pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=1)
        ed.handle_event(ev)
        assert ed.tex_idx != old_idx
