"""editor/view_3d/tools_sculpt.py — Sculpt tool methods for Zone3DEditor."""

from __future__ import annotations

import pygame

from core.tiles import TILE_REGISTRY, tile_def
from editor.view_3d.constants import (
    FLOOR_MIN, FLOOR_MAX, CEIL_MIN, CEIL_MAX,
    SKY_HEIGHT, DEFAULT_FLOOR, DEFAULT_CEIL,
)


class SculptMixin:
    """Floor/ceiling sculpting, cell conversion, and upper-wall adjustment."""

    # ── Floor raise / lower ───────────────────────────────────────

    def _tool_floor_raise(self) -> None:
        """Raise floor height (pure shape change, no segmenting)."""
        hit = self.aimed
        if not hit:
            return
        zone = self.zone
        r, c = hit.row, hit.col
        fh = zone.floor_heights[r][c]
        ch = zone.ceil_heights[r][c]
        max_fh = min(FLOOR_MAX, ch - 0.05) if ch < SKY_HEIGHT else FLOOR_MAX
        new_fh = min(fh + self.snap_y, max_fh)
        if abs(new_fh - fh) < 0.001:
            return
        self._push_undo()
        self._ensure_face_textures()
        zone.floor_heights[r][c] = new_fh
        # Keep existing segment top-edges in sync with new height
        for fi in range(4):
            segs = zone.floor_step_segments[r][c][fi]
            if segs:
                segs[-1][1] = max(0.0, new_fh)
        self.dirty = True

    def _tool_floor_lower(self) -> None:
        """Lower floor height (pure shape change, no segmenting)."""
        hit = self.aimed
        if not hit:
            return
        zone = self.zone
        r, c = hit.row, hit.col
        fh = zone.floor_heights[r][c]
        new_fh = max(FLOOR_MIN, fh - self.snap_y)
        if abs(new_fh - fh) < 0.001:
            return
        self._push_undo()
        self._ensure_face_textures()
        zone.floor_heights[r][c] = new_fh
        # Keep existing segment top-edges in sync with new height
        for fi in range(4):
            segs = zone.floor_step_segments[r][c][fi]
            if segs:
                segs[-1][1] = max(0.0, new_fh)
        self.dirty = True

    # ── Ceiling lower / raise / delete ────────────────────────────

    def _tool_ceiling_lower(self) -> None:
        """Lower ceiling (pure shape change, no segmenting).  If sky, bring in default."""
        hit = self.aimed
        if not hit:
            return
        zone = self.zone
        r, c = hit.row, hit.col
        ch = zone.ceil_heights[r][c]
        fh = zone.floor_heights[r][c]
        if ch >= SKY_HEIGHT:
            new_ch = DEFAULT_CEIL
        else:
            min_ch = max(CEIL_MIN, fh + 0.05)
            new_ch = max(ch - self.snap_y, min_ch)
        if abs(new_ch - ch) < 0.001:
            return
        self._push_undo()
        self._ensure_face_textures()
        zone.ceil_heights[r][c] = new_ch
        self.dirty = True

    def _tool_ceiling_raise(self) -> None:
        """Raise ceiling (clamped to SKY_HEIGHT)."""
        hit = self.aimed
        if not hit:
            return
        zone = self.zone
        r, c = hit.row, hit.col
        ch = zone.ceil_heights[r][c]
        if ch >= SKY_HEIGHT:
            return
        new_ch = min(ch + self.snap_y, SKY_HEIGHT)
        if abs(new_ch - ch) < 0.001:
            return
        self._push_undo()
        zone.ceil_heights[r][c] = new_ch
        self.dirty = True

    def _tool_ceiling_delete(self) -> None:
        """Delete ceiling (set to open sky)."""
        hit = self.aimed
        if not hit:
            return
        zone = self.zone
        r, c = hit.row, hit.col
        ch = zone.ceil_heights[r][c]
        if ch >= SKY_HEIGHT - 0.01:
            return
        self._push_undo()
        zone.ceil_heights[r][c] = SKY_HEIGHT
        self.dirty = True

    # ── Toggle ceiling (T key) ────────────────────────────────────

    def _toggle_ceiling(self) -> bool:
        """T key: toggle ceiling on/off for the aimed cell."""
        hit = self.aimed
        if not hit:
            return False
        zone = self.zone
        r, c = hit.row, hit.col
        ch = zone.ceil_heights[r][c]
        self._push_undo()
        if ch >= SKY_HEIGHT - 0.01:
            zone.ceil_heights[r][c] = DEFAULT_CEIL
        else:
            zone.ceil_heights[r][c] = SKY_HEIGHT
            if hasattr(zone, 'upper_wall_height') and zone.upper_wall_height:
                if len(zone.upper_wall_height) > r:
                    zone.upper_wall_height[r][c] = 0.0
        self.dirty = True
        return True

    # ── Reset (R key) ─────────────────────────────────────────────

    def _reset_ceiling(self) -> bool:
        """R on ceiling: reset ceiling + upper wall to defaults."""
        hit = self.aimed
        if not hit:
            return False
        zone = self.zone
        r, c = hit.row, hit.col
        self._push_undo()
        zone.ceil_heights[r][c] = DEFAULT_CEIL
        if hasattr(zone, 'upper_wall_height') and zone.upper_wall_height:
            if len(zone.upper_wall_height) > r:
                zone.upper_wall_height[r][c] = 0.0
        self.dirty = True
        return True

    def _reset_floor(self) -> bool:
        """R in floor tool: reset floor to DEFAULT_FLOOR."""
        hit = self.aimed
        if not hit:
            return False
        zone = self.zone
        r, c = hit.row, hit.col
        self._push_undo()
        zone.floor_heights[r][c] = DEFAULT_FLOOR
        self.dirty = True
        return True

    # ── Clear cell (Delete/Backspace) ─────────────────────────────

    def _clear_cell(self) -> bool:
        """Full cell reset -- flat ground, default ceiling, clear textures."""
        hit = self.aimed
        if not hit:
            return False
        zone = self.zone
        r, c = hit.row, hit.col
        self._push_undo()
        td = tile_def(zone.tiles[r][c])
        if td and td.wall:
            zone.tiles[r][c] = self._open_tile
        zone.floor_heights[r][c] = DEFAULT_FLOOR
        zone.ceil_heights[r][c] = SKY_HEIGHT
        if zone.upper_wall_height and len(zone.upper_wall_height) > r:
            zone.upper_wall_height[r][c] = 0.0
        if zone.face_textures and len(zone.face_textures) > r:
            zone.face_textures[r][c] = ["", "", "", ""]
        if zone.wall_textures and len(zone.wall_textures) > r:
            zone.wall_textures[r][c] = ""
        if zone.wall_segments and len(zone.wall_segments) > r:
            zone.wall_segments[r][c] = [[], [], [], []]
        if zone.floor_textures and len(zone.floor_textures) > r:
            zone.floor_textures[r][c] = ""
        if zone.ceil_textures and len(zone.ceil_textures) > r:
            zone.ceil_textures[r][c] = ""
        if zone.floor_step_textures and len(zone.floor_step_textures) > r:
            zone.floor_step_textures[r][c] = ["", "", "", ""]
        if zone.ceil_step_textures and len(zone.ceil_step_textures) > r:
            zone.ceil_step_textures[r][c] = ["", "", "", ""]
        self.dirty = True
        return True

    # ── Upper-wall height adjustment ──────────────────────────────

    def _adjust_upper_wall_height(self, mod: int) -> bool:
        """U key: raise upper-wall.  Shift+U: lower.  Ctrl+U: reset."""
        hit = self.aimed
        if not hit or hit.part != "ceiling":
            return False
        zone = self.zone
        r, c = hit.row, hit.col
        td = tile_def(zone.tiles[r][c])
        if td and td.wall:
            return False
        self._ensure_face_textures()
        ch = zone.ceil_heights[r][c]
        uwh = zone.upper_wall_height[r][c]

        self._push_undo()
        if mod & pygame.KMOD_CTRL:
            zone.upper_wall_height[r][c] = 0.0
            self.dirty = True
            return True

        if mod & pygame.KMOD_SHIFT:
            if uwh <= ch:
                return True
            new = uwh - self.snap_y
            zone.upper_wall_height[r][c] = new if new > ch + 0.01 else 0.0
        else:
            if uwh <= ch:
                uwh = self._ceil_mass_top(r, c)
            new = uwh + self.snap_y
            zone.upper_wall_height[r][c] = min(CEIL_MAX, new)
        self.dirty = True
        return True

    def _scroll_upper_wall(self, direction: int) -> None:
        """Scroll while aimed at ceiling: raise/lower upper wall height (pure shape)."""
        hit = self.aimed
        if not hit or hit.part != "ceiling":
            return
        zone = self.zone
        r, c = hit.row, hit.col
        td = tile_def(zone.tiles[r][c])
        if td and td.wall:
            return
        self._ensure_face_textures()
        ch = zone.ceil_heights[r][c]
        uwh = zone.upper_wall_height[r][c]

        self._push_undo()
        if direction > 0:
            if uwh <= ch:
                uwh = ch
            new = uwh + self.snap_y
            zone.upper_wall_height[r][c] = min(CEIL_MAX, new)
            # Keep existing segment top-edges in sync
            for fi in range(4):
                segs = zone.ceil_step_segments[r][c][fi]
                if segs:
                    segs[-1][1] = zone.upper_wall_height[r][c]
        else:
            if uwh <= ch:
                return
            new = uwh - self.snap_y
            zone.upper_wall_height[r][c] = new if new > ch + 0.01 else 0.0
        self.dirty = True

    # ── Scroll-extend floor ───────────────────────────────────────

    def _extend_floor(self, r: int, c: int, direction: int) -> None:
        """Scroll-extend: raise/lower floor WITHOUT auto-segmenting."""
        zone = self.zone
        fh = zone.floor_heights[r][c]
        ch = zone.ceil_heights[r][c]
        if direction > 0:
            max_fh = min(FLOOR_MAX, ch - 0.05) if ch < SKY_HEIGHT else FLOOR_MAX
            new_fh = min(fh + self.snap_y, max_fh)
        else:
            new_fh = max(FLOOR_MIN, fh - self.snap_y)
        if abs(new_fh - fh) < 0.001:
            return
        self._push_undo()
        self._ensure_face_textures()
        zone.floor_heights[r][c] = new_fh
        for fi in range(4):
            segs = zone.floor_step_segments[r][c][fi]
            if segs:
                segs[-1][1] = max(0.0, new_fh)
        self.dirty = True

    # ── Cell type conversion ──────────────────────────────────────

    def _make_wall(self, r: int, c: int) -> None:
        zone = self.zone
        td = tile_def(zone.tiles[r][c])
        if td and td.wall:
            return
        zone.tiles[r][c] = self._wall_tile
        if zone.floor_step_textures and len(zone.floor_step_textures) > r:
            zone.floor_step_textures[r][c] = ["", "", "", ""]
        if zone.ceil_step_textures and len(zone.ceil_step_textures) > r:
            zone.ceil_step_textures[r][c] = ["", "", "", ""]
        if zone.floor_step_segments and len(zone.floor_step_segments) > r:
            zone.floor_step_segments[r][c] = [[], [], [], []]
        if zone.ceil_step_segments and len(zone.ceil_step_segments) > r:
            zone.ceil_step_segments[r][c] = [[], [], [], []]

    def _make_open(self, r: int, c: int) -> None:
        zone = self.zone
        td = tile_def(zone.tiles[r][c])
        if td and not td.wall:
            return
        zone.tiles[r][c] = self._open_tile
        fh = zone.floor_heights[r][c]
        ch = zone.ceil_heights[r][c]
        if fh >= ch - 0.01:
            zone.floor_heights[r][c] = DEFAULT_FLOOR
            zone.ceil_heights[r][c] = SKY_HEIGHT
        if zone.face_textures and len(zone.face_textures) > r:
            zone.face_textures[r][c] = ["", "", "", ""]
        if zone.wall_textures and len(zone.wall_textures) > r:
            zone.wall_textures[r][c] = ""
        if zone.wall_segments and len(zone.wall_segments) > r:
            zone.wall_segments[r][c] = [[], [], [], []]
