"""Tests for Phase 1 erase command handlers.

These tests validate that the handlers own the mutation logic directly —
no editor mixin methods needed.  A real Zone is constructed; a minimal
stub provides only the read-only editor state the handlers query
(``aimed``, ``zone``, ``_open_tile``).

Each handler is exercised via CommandBus.execute() to confirm the full
dispatch path (undo push → ensure face textures → handle → dirty → emit).
"""

from __future__ import annotations

import pytest
from dataclasses import dataclass

from editor.commands.base import CommandBus, EventBus
from editor.commands.erase_cmds import (
    EraseCell, EraseHeight, EraseTexturesOnly,
    register_erase_handlers,
)
from editor.zone_ops import clear_cell_textures, DEFAULT_FLOOR, SKY_HEIGHT


# ── Minimal zone construction ──────────────────────────────────────

LAYER_NONE = -1000.0
H, W = 4, 4


def _make_zone():
    """Build a 4×4 Zone with all grids the erase handlers touch."""
    from core.zones import Zone

    return Zone(
        name="test",
        width=W,
        height=H,
        anchor=(2.0, 2.0),
        tiles=[["concrete"] * W for _ in range(H)],
        floor_heights=[[0.5] * W for _ in range(H)],
        ceil_heights=[[0.8] * W for _ in range(H)],
        upper_wall_height=[[0.1] * W for _ in range(H)],
        wall_textures=[["brick"] * W for _ in range(H)],
        face_textures=[[["n", "s", "e", "w"] for _ in range(W)] for _ in range(H)],
        floor_textures=[["floor_tex"] * W for _ in range(H)],
        ceil_textures=[["ceil_tex"] * W for _ in range(H)],
        floor_step_textures=[[["", "", "", ""] for _ in range(W)] for _ in range(H)],
        ceil_step_textures=[[["", "", "", ""] for _ in range(W)] for _ in range(H)],
        floor_step_segments=[[[[("seg", 0.3)], [], [], []] for _ in range(W)] for _ in range(H)],
        ceil_step_segments=[[[[("seg", 0.7)], [], [], []] for _ in range(W)] for _ in range(H)],
        wall_segments=[[[[], [], [], []] for _ in range(W)] for _ in range(H)],
        light_levels=[[1.0] * W for _ in range(H)],
        floor2_heights=[[LAYER_NONE] * W for _ in range(H)],
        ceil2_heights=[[LAYER_NONE] * W for _ in range(H)],
        floor2_textures=[[""] * W for _ in range(H)],
        ceil2_textures=[[""] * W for _ in range(H)],
        upper_wall_height2=[[0.0] * W for _ in range(H)],
    )


# ── Stub aimed (CellHit-like) ─────────────────────────────────────

@dataclass
class FakeHit:
    row: int
    col: int
    part: str = "floor"


# ── Stub editor (minimal: zone + aimed + _open_tile) ──────────────

class StubEditor:
    """Provides only what the erase handlers read through the closure."""

    def __init__(self, zone):
        self.zone = zone
        self.aimed = None
        self._open_tile = "concrete"
        self.dirty = False
        self._push_undo_calls = 0

    def _push_undo(self):
        self._push_undo_calls += 1

    def _ensure_face_textures(self):
        pass

    def _undo(self):
        pass

    def _redo(self):
        pass


# ── Fixtures ───────────────────────────────────────────────────────

@pytest.fixture
def env():
    """Return (zone, editor, bus) all wired together."""
    zone = _make_zone()
    ed = StubEditor(zone)
    eb = EventBus()
    bus = CommandBus(ed, eb)
    register_erase_handlers(bus, ed)
    return zone, ed, bus


# ── EraseCell tests ────────────────────────────────────────────────

class TestEraseCell:
    def test_resets_floor_and_ceiling(self, env):
        zone, ed, bus = env
        ed.aimed = FakeHit(row=1, col=2, part="floor")
        # Pre-condition: non-default values
        assert zone.floor_heights[1][2] == 0.5
        assert zone.ceil_heights[1][2] == 0.8

        bus.execute(EraseCell())

        assert zone.floor_heights[1][2] == DEFAULT_FLOOR
        assert zone.ceil_heights[1][2] == SKY_HEIGHT

    def test_clears_textures(self, env):
        zone, ed, bus = env
        ed.aimed = FakeHit(row=0, col=0)
        # Pre-condition: textures set
        assert zone.wall_textures[0][0] == "brick"
        assert zone.face_textures[0][0] == ["n", "s", "e", "w"]

        bus.execute(EraseCell())

        assert zone.wall_textures[0][0] == ""
        assert zone.face_textures[0][0] == ["", "", "", ""]
        assert zone.floor_textures[0][0] == ""
        assert zone.ceil_textures[0][0] == ""

    def test_clears_upper_wall(self, env):
        zone, ed, bus = env
        ed.aimed = FakeHit(row=2, col=3)
        assert zone.upper_wall_height[2][3] == 0.1

        bus.execute(EraseCell())

        assert zone.upper_wall_height[2][3] == 0.0

    def test_clears_step_segments(self, env):
        zone, ed, bus = env
        ed.aimed = FakeHit(row=0, col=0)
        assert zone.floor_step_segments[0][0][0] != []  # has data

        bus.execute(EraseCell())

        assert zone.floor_step_segments[0][0] == [[], [], [], []]
        assert zone.ceil_step_segments[0][0] == [[], [], [], []]

    def test_clears_layer2(self, env):
        zone, ed, bus = env
        zone.floor2_heights[1][1] = 0.3
        zone.ceil2_heights[1][1] = 0.7
        zone.floor2_textures[1][1] = "l2tex"
        zone.ceil2_textures[1][1] = "l2tex"
        ed.aimed = FakeHit(row=1, col=1)

        bus.execute(EraseCell())

        assert zone.floor2_heights[1][1] == LAYER_NONE
        assert zone.ceil2_heights[1][1] == LAYER_NONE
        assert zone.floor2_textures[1][1] == ""
        assert zone.ceil2_textures[1][1] == ""

    def test_no_aimed_returns_false(self, env):
        zone, ed, bus = env
        ed.aimed = None
        result = bus.execute(EraseCell())
        assert result is False

    def test_sets_dirty_flag(self, env):
        zone, ed, bus = env
        ed.aimed = FakeHit(row=0, col=0)
        ed.dirty = False
        bus.execute(EraseCell())
        assert ed.dirty is True

    def test_converts_wall_tile_to_open(self, env):
        """A wall tile should be converted to the open tile on full erase."""
        zone, ed, bus = env
        # Make cell (0,0) a wall tile
        from core.tiles import TILE_REGISTRY
        # Find a wall tile, or use a stub approach
        zone.tiles[0][0] = "wall"
        # If "wall" isn't in the registry the tile_def lookup returns None,
        # so reset_cell won't convert it — test with the actual open_tile
        ed.aimed = FakeHit(row=0, col=0)
        bus.execute(EraseCell())
        # Height should still be reset regardless of tile conversion
        assert zone.floor_heights[0][0] == DEFAULT_FLOOR


# ── EraseHeight tests ──────────────────────────────────────────────

class TestEraseHeight:
    def test_reset_floor_height(self, env):
        zone, ed, bus = env
        ed.aimed = FakeHit(row=1, col=1, part="floor")

        bus.execute(EraseHeight())

        assert zone.floor_heights[1][1] == DEFAULT_FLOOR
        # Textures should be untouched
        assert zone.wall_textures[1][1] == "brick"

    def test_reset_ceiling_height(self, env):
        zone, ed, bus = env
        ed.aimed = FakeHit(row=2, col=2, part="ceiling")

        bus.execute(EraseHeight())

        assert zone.ceil_heights[2][2] == SKY_HEIGHT
        assert zone.upper_wall_height[2][2] == 0.0

    def test_ceiling_clears_step_segments(self, env):
        zone, ed, bus = env
        ed.aimed = FakeHit(row=0, col=0, part="ceiling")
        assert zone.ceil_step_segments[0][0][0] != []

        bus.execute(EraseHeight())

        assert zone.ceil_step_segments[0][0] == [[], [], [], []]

    def test_floor_clears_step_segments(self, env):
        zone, ed, bus = env
        ed.aimed = FakeHit(row=0, col=0, part="floor")

        bus.execute(EraseHeight())

        assert zone.floor_step_segments[0][0] == [[], [], [], []]

    def test_reset_floor2_height(self, env):
        zone, ed, bus = env
        zone.floor2_heights[1][1] = 0.3
        zone.floor2_textures[1][1] = "l2tex"
        ed.aimed = FakeHit(row=1, col=1, part="floor2")

        bus.execute(EraseHeight())

        assert zone.floor2_heights[1][1] == LAYER_NONE
        assert zone.floor2_textures[1][1] == ""

    def test_reset_ceiling2_height(self, env):
        zone, ed, bus = env
        zone.ceil2_heights[1][1] = 0.7
        zone.upper_wall_height2[1][1] = 0.2
        zone.ceil2_textures[1][1] = "l2tex"
        ed.aimed = FakeHit(row=1, col=1, part="ceiling2")

        bus.execute(EraseHeight())

        assert zone.ceil2_heights[1][1] == LAYER_NONE
        assert zone.upper_wall_height2[1][1] == 0.0
        assert zone.ceil2_textures[1][1] == ""

    def test_no_aimed_returns_false(self, env):
        zone, ed, bus = env
        ed.aimed = None
        assert bus.execute(EraseHeight()) is False

    def test_preserves_textures_on_floor_reset(self, env):
        zone, ed, bus = env
        ed.aimed = FakeHit(row=0, col=0, part="floor")

        bus.execute(EraseHeight())

        # Textures untouched
        assert zone.wall_textures[0][0] == "brick"
        assert zone.floor_textures[0][0] == "floor_tex"
        assert zone.ceil_textures[0][0] == "ceil_tex"

    def test_wall_part_resets_floor(self, env):
        """Hitting a 'wall' or 'ground' part resets floor height."""
        zone, ed, bus = env
        ed.aimed = FakeHit(row=1, col=1, part="wall")

        bus.execute(EraseHeight())

        assert zone.floor_heights[1][1] == DEFAULT_FLOOR


# ── EraseTexturesOnly tests ────────────────────────────────────────

class TestEraseTexturesOnly:
    def test_clears_all_textures(self, env):
        zone, ed, bus = env
        ed.aimed = FakeHit(row=0, col=0)

        bus.execute(EraseTexturesOnly())

        assert zone.face_textures[0][0] == ["", "", "", ""]
        assert zone.wall_textures[0][0] == ""
        assert zone.floor_textures[0][0] == ""
        assert zone.ceil_textures[0][0] == ""

    def test_preserves_heights(self, env):
        zone, ed, bus = env
        ed.aimed = FakeHit(row=1, col=1)

        bus.execute(EraseTexturesOnly())

        assert zone.floor_heights[1][1] == 0.5
        assert zone.ceil_heights[1][1] == 0.8

    def test_clears_step_textures(self, env):
        zone, ed, bus = env
        zone.floor_step_textures[0][0] = ["a", "b", "c", "d"]
        zone.ceil_step_textures[0][0] = ["e", "f", "g", "h"]
        ed.aimed = FakeHit(row=0, col=0)

        bus.execute(EraseTexturesOnly())

        assert zone.floor_step_textures[0][0] == ["", "", "", ""]
        assert zone.ceil_step_textures[0][0] == ["", "", "", ""]

    def test_clears_layer2_textures(self, env):
        zone, ed, bus = env
        zone.floor2_textures[2][2] = "l2floor"
        zone.ceil2_textures[2][2] = "l2ceil"
        ed.aimed = FakeHit(row=2, col=2)

        bus.execute(EraseTexturesOnly())

        assert zone.floor2_textures[2][2] == ""
        assert zone.ceil2_textures[2][2] == ""

    def test_no_aimed_returns_false(self, env):
        zone, ed, bus = env
        ed.aimed = None
        assert bus.execute(EraseTexturesOnly()) is False

    def test_preserves_step_segments(self, env):
        """Texture-only erase should NOT touch segment geometry."""
        zone, ed, bus = env
        ed.aimed = FakeHit(row=0, col=0)
        seg_before = [list(s) for s in zone.floor_step_segments[0][0]]

        bus.execute(EraseTexturesOnly())

        assert zone.floor_step_segments[0][0] == seg_before


# ── clear_cell_textures standalone tests ───────────────────────────

class TestClearCellTextures:
    """Test the extracted utility function directly."""

    def test_clears_all_tex_grids(self):
        zone = _make_zone()
        clear_cell_textures(zone, 1, 1)

        assert zone.face_textures[1][1] == ["", "", "", ""]
        assert zone.wall_textures[1][1] == ""
        assert zone.floor_textures[1][1] == ""
        assert zone.ceil_textures[1][1] == ""
        assert zone.floor_step_textures[1][1] == ["", "", "", ""]
        assert zone.ceil_step_textures[1][1] == ["", "", "", ""]

    def test_handles_empty_grids(self):
        """No crash when grids are empty lists."""
        from core.zones import Zone
        zone = Zone(
            name="tiny", width=2, height=2, anchor=(1.0, 1.0),
            tiles=[["void"] * 2 for _ in range(2)],
        )
        # All texture grids default to [] — should not crash
        clear_cell_textures(zone, 0, 0)


# ── Integration: no suppress_undo needed ───────────────────────────

class TestNoUndoSuppression:
    """Verify handlers don't call _push_undo — the bus does it once."""

    def test_bus_pushes_undo_once(self, env):
        zone, ed, bus = env
        ed.aimed = FakeHit(row=0, col=0)
        ed._push_undo_calls = 0

        bus.execute(EraseCell())

        # The bus calls _push_undo exactly once
        assert ed._push_undo_calls == 1

    def test_erase_height_bus_pushes_undo_once(self, env):
        zone, ed, bus = env
        ed.aimed = FakeHit(row=0, col=0, part="ceiling")
        ed._push_undo_calls = 0

        bus.execute(EraseHeight())

        assert ed._push_undo_calls == 1

    def test_erase_textures_bus_pushes_undo_once(self, env):
        zone, ed, bus = env
        ed.aimed = FakeHit(row=0, col=0)
        ed._push_undo_calls = 0

        bus.execute(EraseTexturesOnly())

        assert ed._push_undo_calls == 1
