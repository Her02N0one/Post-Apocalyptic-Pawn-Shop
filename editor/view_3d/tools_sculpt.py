"""editor/view_3d/tools_sculpt.py — Sculpt tool methods for Zone3DEditor."""

from __future__ import annotations

import pygame

from core.tiles import TILE_REGISTRY, tile_def
from editor.view_3d.constants import (
    FLOOR_MIN, FLOOR_MAX, CEIL_MIN, CEIL_MAX,
    SKY_HEIGHT, DEFAULT_FLOOR, DEFAULT_CEIL,
)
from editor.view_3d.cell_ops import reset_cell


class SculptMixin:
    """Floor/ceiling sculpting, cell conversion, and upper-wall adjustment."""

    # ── Tile-type sync ─────────────────────────────────────────────

    def _sync_tile_type(self, r: int, c: int) -> None:
        """Re-derive tile type from geometry after a height change.

        When the floor/ceiling gap opens (>= 0.1) a wall cell becomes
        open; when it closes (< 0.1) an open cell becomes a wall.
        This keeps rendering consistent with the sculpted geometry
        without requiring a manual reset.
        """
        zone = self.zone
        fh = zone.floor_heights[r][c]
        ch = zone.ceil_heights[r][c]
        td = tile_def(zone.tiles[r][c])
        is_wall = td and td.wall
        gap = ch - fh

        if gap < 0.1 and not is_wall:
            self._make_wall(r, c)
        elif gap >= 0.1 and is_wall:
            # Convert to open without resetting heights —
            # only change the tile string and clear wall data.
            zone.tiles[r][c] = self._open_tile
            if zone.face_textures and len(zone.face_textures) > r:
                zone.face_textures[r][c] = ["", "", "", ""]
            if zone.wall_textures and len(zone.wall_textures) > r:
                zone.wall_textures[r][c] = ""
            if zone.wall_segments and len(zone.wall_segments) > r:
                zone.wall_segments[r][c] = [[], [], [], []]

    # ── Floor raise / lower ───────────────────────────────────────

    def _tool_floor_raise(self) -> None:
        """Raise floor height (pure shape change, no segmenting).

        When the cell has a ceiling (below SKY_HEIGHT), the floor is
        clamped so that a 0.05 gap remains.  When the cell has no
        ceiling (sky), the ceiling is pushed up together with the
        floor so they stay the same distance apart.
        """
        hit = self.aimed
        if not hit:
            return
        zone = self.zone
        r, c = hit.row, hit.col
        fh = zone.floor_heights[r][c]
        ch = zone.ceil_heights[r][c]
        is_sky = ch >= SKY_HEIGHT
        max_fh = FLOOR_MAX if is_sky else min(FLOOR_MAX, ch - 0.05)
        new_fh = min(fh + self.snap_y, max_fh)
        if abs(new_fh - fh) < 0.001:
            return
        self._push_undo()
        self._ensure_face_textures()
        delta = new_fh - fh
        zone.floor_heights[r][c] = new_fh
        # Push ceiling up with floor so the gap is preserved
        if not is_sky:
            zone.ceil_heights[r][c] = min(CEIL_MAX, ch + delta)
        # Keep existing segment top-edges in sync with new height
        for fi in range(4):
            segs = zone.floor_step_segments[r][c][fi]
            if segs:
                segs[-1][1] = max(0.0, new_fh)
        self._sync_tile_type(r, c)
        self.dirty = True

    def _tool_floor_lower(self) -> None:
        """Lower floor height.  Cleans up floor step segments when they
        become invalid (floor returns to ground level or segments
        extend beyond the new height)."""
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
        # Trim / clear floor step segments
        self._trim_floor_segments(r, c, new_fh)
        self._sync_tile_type(r, c)
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
            new_ch = fh + DEFAULT_CEIL
        else:
            min_ch = max(CEIL_MIN, fh + 0.05)
            new_ch = max(ch - self.snap_y, min_ch)
        if abs(new_ch - ch) < 0.001:
            return
        self._push_undo()
        self._ensure_face_textures()
        zone.ceil_heights[r][c] = new_ch
        self._sync_tile_type(r, c)
        self.dirty = True

    def _tool_ceiling_raise(self) -> None:
        """Raise ceiling (clamped to SKY_HEIGHT).  Clears ceiling step
        segments when the ceiling reaches open sky."""
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
        # Sky = no ceiling mass = no ceiling step segments
        if new_ch >= SKY_HEIGHT - 0.01:
            self._clear_ceil_segments(r, c)
        self._sync_tile_type(r, c)
        self.dirty = True

    def _tool_ceiling_delete(self) -> None:
        """Delete ceiling (set to open sky).  Clears ceiling step segments."""
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
        self._clear_ceil_segments(r, c)
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
        fh = zone.floor_heights[r][c]
        self._push_undo()
        if ch >= SKY_HEIGHT - 0.01:
            zone.ceil_heights[r][c] = fh + DEFAULT_CEIL
        else:
            zone.ceil_heights[r][c] = SKY_HEIGHT
            self._clear_ceil_segments(r, c)
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
        self._push_undo()
        reset_cell(self.zone, hit.row, hit.col, self._open_tile)
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

    def _extend_wall_ceiling(self, r: int, c: int, direction: int) -> None:
        """Scroll on a wall cell: raise/lower ceiling to open or close it.

        Scroll-up raises the ceiling (creating a gap → opens the wall).
        Scroll-down lowers the ceiling back toward the floor.
        Tile type is automatically re-derived after the change.
        """
        zone = self.zone
        fh = zone.floor_heights[r][c]
        ch = zone.ceil_heights[r][c]

        if direction > 0:
            # Raise ceiling to open the wall
            new_ch = min(ch + self.snap_y, SKY_HEIGHT)
        else:
            # Lower ceiling toward floor
            min_ch = fh
            new_ch = max(ch - self.snap_y, min_ch)

        if abs(new_ch - ch) < 0.001:
            return
        self._push_undo()
        self._ensure_face_textures()
        zone.ceil_heights[r][c] = new_ch
        if new_ch >= SKY_HEIGHT - 0.01:
            self._clear_ceil_segments(r, c)
        self._sync_tile_type(r, c)
        self.dirty = True

    def _extend_floor(self, r: int, c: int, direction: int) -> None:
        """Scroll-extend: raise/lower floor WITHOUT auto-segmenting.

        When raising the floor on a cell with a ceiling, the ceiling
        is pushed up together to preserve the gap.
        When lowering, floor step segments are trimmed/cleared.
        """
        zone = self.zone
        fh = zone.floor_heights[r][c]
        ch = zone.ceil_heights[r][c]
        is_sky = ch >= SKY_HEIGHT
        if direction > 0:
            max_fh = FLOOR_MAX if is_sky else min(FLOOR_MAX, ch - 0.05)
            new_fh = min(fh + self.snap_y, max_fh)
        else:
            new_fh = max(FLOOR_MIN, fh - self.snap_y)
        if abs(new_fh - fh) < 0.001:
            return
        self._push_undo()
        self._ensure_face_textures()
        delta = new_fh - fh
        zone.floor_heights[r][c] = new_fh
        # Push ceiling up with floor so the gap is preserved
        if not is_sky and delta > 0:
            zone.ceil_heights[r][c] = min(CEIL_MAX, ch + delta)
        # Sync or trim floor step segments
        if direction > 0:
            for fi in range(4):
                segs = zone.floor_step_segments[r][c][fi]
                if segs:
                    segs[-1][1] = max(0.0, new_fh)
        else:
            self._trim_floor_segments(r, c, new_fh)
        self._sync_tile_type(r, c)
        self.dirty = True

    # ── Floor segment cleanup ───────────────────────────────────────

    def _trim_floor_segments(self, r: int, c: int, new_fh: float) -> None:
        """Trim or clear floor step segments after lowering the floor.

        When ``new_fh`` drops back to ground level (\u2248 0.0), all floor
        step segments AND floor step textures are cleared entirely.
        Otherwise, segments whose boundaries extend above the new
        floor mass height are popped or clamped.
        """
        zone = self.zone
        hi = max(0.0, new_fh)

        # Floor at ground level \u2192 no step mass \u2192 no segments.
        if hi < 0.02:
            for fi in range(4):
                if zone.floor_step_segments and len(zone.floor_step_segments) > r:
                    zone.floor_step_segments[r][c][fi] = []
                if zone.floor_step_textures and len(zone.floor_step_textures) > r:
                    zone.floor_step_textures[r][c][fi] = ""
            return

        # Non-zero floor: trim segments from top that exceed new height.
        for fi in range(4):
            if not (zone.floor_step_segments and len(zone.floor_step_segments) > r):
                continue
            segs = zone.floor_step_segments[r][c][fi]
            if not segs:
                continue
            # Pop segments whose bottom boundary exceeds new height
            while len(segs) > 1 and segs[-1][1] > hi + 0.02:
                segs.pop()
            # Clamp the surviving top segment
            if segs:
                segs[-1][1] = hi
            # If only one segment left, collapse to flat texture
            if len(segs) <= 1:
                if segs and zone.floor_step_textures and len(zone.floor_step_textures) > r:
                    zone.floor_step_textures[r][c][fi] = segs[0][0]
                zone.floor_step_segments[r][c][fi] = []

    # ── Ceiling segment cleanup ───────────────────────────────────

    def _clear_ceil_segments(self, r: int, c: int) -> None:
        """Clear all ceiling step segments and textures for cell (r, c).

        Called when the ceiling is removed (raised to sky) or when
        converting a wall back to open space.
        """
        zone = self.zone
        for fi in range(4):
            if zone.ceil_step_segments and len(zone.ceil_step_segments) > r:
                zone.ceil_step_segments[r][c][fi] = []
            if zone.ceil_step_textures and len(zone.ceil_step_textures) > r:
                zone.ceil_step_textures[r][c][fi] = ""
        # Also clear upper_wall_height since there's no ceiling mass
        if zone.upper_wall_height and len(zone.upper_wall_height) > r:
            zone.upper_wall_height[r][c] = 0.0

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
