"""editor/view_3d/tools_erase.py — Eraser tool for Zone3DEditor.

Provides quick cell-reset operations:
  LMB        Reset cell to flat ground + open sky + default textures
  RMB        Reset height only (keep tile type and textures)
  Shift+LMB  Reset all textures on cell (keep geometry)
"""

from __future__ import annotations

from core.tiles import tile_def
from editor.view_3d.constants import (
    DEFAULT_FLOOR, SKY_HEIGHT,
)
from editor.view_3d.cell_ops import reset_cell


class EraseMixin:
    """Eraser tool — quick cell/height/texture resets."""

    def _erase_cell(self) -> bool:
        """LMB on eraser: full cell reset (flat ground, open sky, clear all)."""
        hit = self.aimed
        if not hit:
            return False
        self._push_undo()
        reset_cell(self.zone, hit.row, hit.col, self._open_tile)
        self.dirty = True
        return True

    def _erase_height(self) -> bool:
        """RMB on eraser: reset height only (keep tile/textures).

        Also clears orphaned step segments whose heights no longer
        match the reset surface.
        """
        hit = self.aimed
        if not hit:
            return False
        zone = self.zone
        r, c = hit.row, hit.col

        self._push_undo()

        if hit.part == "ceiling":
            zone.ceil_heights[r][c] = SKY_HEIGHT
            if zone.upper_wall_height and len(zone.upper_wall_height) > r:
                zone.upper_wall_height[r][c] = 0.0
            # Clear orphaned ceiling step segments
            if zone.ceil_step_segments and len(zone.ceil_step_segments) > r:
                zone.ceil_step_segments[r][c] = [[], [], [], []]
        else:
            zone.floor_heights[r][c] = DEFAULT_FLOOR
            # Clear orphaned floor step segments
            if zone.floor_step_segments and len(zone.floor_step_segments) > r:
                zone.floor_step_segments[r][c] = [[], [], [], []]

        self.dirty = True
        return True

    def _erase_cell_textures(self, r: int, c: int) -> None:
        """Clear all texture overrides on a cell."""
        zone = self.zone
        if zone.face_textures and len(zone.face_textures) > r:
            zone.face_textures[r][c] = ["", "", "", ""]
        if zone.wall_textures and len(zone.wall_textures) > r:
            zone.wall_textures[r][c] = ""
        if zone.floor_textures and len(zone.floor_textures) > r:
            zone.floor_textures[r][c] = ""
        if zone.ceil_textures and len(zone.ceil_textures) > r:
            zone.ceil_textures[r][c] = ""
        if zone.floor_step_textures and len(zone.floor_step_textures) > r:
            zone.floor_step_textures[r][c] = ["", "", "", ""]
        if zone.ceil_step_textures and len(zone.ceil_step_textures) > r:
            zone.ceil_step_textures[r][c] = ["", "", "", ""]

    def _erase_textures_only(self) -> bool:
        """Shift+LMB on eraser: clear textures, keep geometry."""
        hit = self.aimed
        if not hit:
            return False
        zone = self.zone
        r, c = hit.row, hit.col

        self._push_undo()
        self._erase_cell_textures(r, c)
        self.dirty = True
        return True
