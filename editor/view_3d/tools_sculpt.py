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

    # ── Ceiling mass coherence ─────────────────────────────────────

    def _shift_ceil_mass(self, r: int, c: int,
                         old_ch: float, delta: float) -> None:
        """Shift upper_wall_height and ceiling segment Y values by *delta*.

        Called whenever ``ceil_heights`` changes so the rest of the
        ceiling mass (UWH extension + segment boundaries) stays in
        sync with the new ceiling position.
        """
        if abs(delta) < 0.001:
            return
        zone = self.zone
        new_ch = zone.ceil_heights[r][c]

        # Shift UWH if it was explicitly set above the old ceiling
        if zone.upper_wall_height and len(zone.upper_wall_height) > r:
            uwh = zone.upper_wall_height[r][c]
            if uwh > old_ch + 0.01:
                new_uwh = uwh + delta
                if new_uwh > new_ch + 0.01:
                    zone.upper_wall_height[r][c] = min(CEIL_MAX, new_uwh)
                else:
                    zone.upper_wall_height[r][c] = 0.0  # collapsed → reset

        # Shift ceiling segment boundaries so they stay at the same
        # relative position within the mass.
        if zone.ceil_step_segments and len(zone.ceil_step_segments) > r:
            for fi in range(4):
                for seg in zone.ceil_step_segments[r][c][fi]:
                    seg[1] += delta

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

    def _floor_raise_at(self, r: int, c: int) -> bool:
        """Raise floor at *(r, c)* by ``snap_y``.  Returns True if changed."""
        zone = self.zone
        fh = zone.floor_heights[r][c]
        ch = zone.ceil_heights[r][c]
        is_sky = ch >= SKY_HEIGHT
        max_fh = FLOOR_MAX if is_sky else min(FLOOR_MAX, ch - 0.12)
        new_fh = min(fh + self.snap_y, max_fh)
        if abs(new_fh - fh) < 0.001:
            return False
        delta = new_fh - fh
        zone.floor_heights[r][c] = new_fh
        if not is_sky:
            old_ch = ch
            zone.ceil_heights[r][c] = min(CEIL_MAX, ch + delta)
            self._shift_ceil_mass(r, c, old_ch,
                                  zone.ceil_heights[r][c] - old_ch)
        for fi in range(4):
            segs = zone.floor_step_segments[r][c][fi]
            if segs:
                segs[-1][1] = max(0.0, new_fh)
        self._sync_tile_type(r, c)
        return True

    def _tool_floor_raise(self) -> None:
        """Raise floor height.  Selection-aware: batch-raises all selected floors."""
        if self._has_selection():
            self._push_undo()
            self._ensure_face_textures()
            if self._apply_to_selection(self._floor_raise_at):
                self.dirty = True
            return
        hit = self.aimed
        if not hit:
            return
        self._push_undo()
        self._ensure_face_textures()
        if self._floor_raise_at(hit.row, hit.col):
            self.dirty = True

    def _floor_lower_at(self, r: int, c: int) -> bool:
        """Lower floor at *(r, c)* by ``snap_y``.  Returns True if changed."""
        zone = self.zone
        fh = zone.floor_heights[r][c]
        new_fh = max(FLOOR_MIN, fh - self.snap_y)
        if abs(new_fh - fh) < 0.001:
            return False
        zone.floor_heights[r][c] = new_fh
        self._trim_floor_segments(r, c, new_fh)
        self._sync_tile_type(r, c)
        return True

    def _tool_floor_lower(self) -> None:
        """Lower floor height.  Selection-aware: batch-lowers all selected floors."""
        if self._has_selection():
            self._push_undo()
            self._ensure_face_textures()
            if self._apply_to_selection(self._floor_lower_at):
                self.dirty = True
            return
        hit = self.aimed
        if not hit:
            return
        self._push_undo()
        self._ensure_face_textures()
        if self._floor_lower_at(hit.row, hit.col):
            self.dirty = True

    # ── Ceiling lower / raise / delete ────────────────────────────

    def _ceiling_lower_at(self, r: int, c: int) -> bool:
        """Lower ceiling at *(r, c)*.  Returns True if changed."""
        zone = self.zone
        ch = zone.ceil_heights[r][c]
        fh = zone.floor_heights[r][c]
        if ch >= SKY_HEIGHT:
            new_ch = fh + DEFAULT_CEIL
            zone.ceil_heights[r][c] = new_ch
            # Coming from sky → no mass to shift
            self._sync_tile_type(r, c)
            return True
        min_ch = max(CEIL_MIN, fh + 0.12)
        new_ch = max(ch - self.snap_y, min_ch)
        if abs(new_ch - ch) < 0.001:
            return False
        zone.ceil_heights[r][c] = new_ch
        self._shift_ceil_mass(r, c, ch, new_ch - ch)
        self._sync_tile_type(r, c)
        return True

    def _tool_ceiling_lower(self) -> None:
        """Lower ceiling.  Selection-aware."""
        if self._has_selection():
            self._push_undo()
            self._ensure_face_textures()
            if self._apply_to_selection(self._ceiling_lower_at):
                self.dirty = True
            return
        hit = self.aimed
        if not hit:
            return
        self._push_undo()
        self._ensure_face_textures()
        if self._ceiling_lower_at(hit.row, hit.col):
            self.dirty = True

    def _ceiling_raise_at(self, r: int, c: int) -> bool:
        """Raise ceiling at *(r, c)*.  Returns True if changed."""
        zone = self.zone
        ch = zone.ceil_heights[r][c]
        if ch >= SKY_HEIGHT:
            return False
        new_ch = min(ch + self.snap_y, SKY_HEIGHT)
        if abs(new_ch - ch) < 0.001:
            return False
        zone.ceil_heights[r][c] = new_ch
        if new_ch >= SKY_HEIGHT - 0.01:
            self._clear_ceil_segments(r, c)
        else:
            self._shift_ceil_mass(r, c, ch, new_ch - ch)
        self._sync_tile_type(r, c)
        return True

    def _tool_ceiling_raise(self) -> None:
        """Raise ceiling.  Selection-aware."""
        if self._has_selection():
            self._push_undo()
            if self._apply_to_selection(self._ceiling_raise_at):
                self.dirty = True
            return
        hit = self.aimed
        if not hit:
            return
        self._push_undo()
        if self._ceiling_raise_at(hit.row, hit.col):
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

    # ── Toggle / add / remove ceiling (T key) ───────────────────────

    def _toggle_ceiling_at(self, r: int, c: int) -> bool:
        """Toggle ceiling on/off at *(r, c)*.  Returns True (always changes)."""
        zone = self.zone
        ch = zone.ceil_heights[r][c]
        fh = zone.floor_heights[r][c]
        if ch >= SKY_HEIGHT - 0.01:
            zone.ceil_heights[r][c] = fh + DEFAULT_CEIL
        else:
            zone.ceil_heights[r][c] = SKY_HEIGHT
            self._clear_ceil_segments(r, c)
        return True

    def _add_ceiling_at(self, r: int, c: int) -> bool:
        """Add a default ceiling if cell has none.  Returns True if changed."""
        zone = self.zone
        if zone.ceil_heights[r][c] < SKY_HEIGHT - 0.01:
            return False  # already has a ceiling
        fh = zone.floor_heights[r][c]
        zone.ceil_heights[r][c] = fh + DEFAULT_CEIL
        return True

    def _remove_ceiling_at(self, r: int, c: int) -> bool:
        """Remove ceiling (set to sky).  Returns True if changed."""
        zone = self.zone
        if zone.ceil_heights[r][c] >= SKY_HEIGHT - 0.01:
            return False  # already sky
        zone.ceil_heights[r][c] = SKY_HEIGHT
        self._clear_ceil_segments(r, c)
        return True

    def _toggle_ceiling(self, *, add_only: bool = False,
                        remove_only: bool = False) -> bool:
        """T key: toggle ceiling on/off.  Selection-aware.

        With selection:
          *add_only*    — only add ceilings where missing (T)
          *remove_only* — only remove existing ceilings (Shift+T)
          both False    — pure toggle (fallback)
        """
        if self._has_selection():
            self._push_undo()
            if add_only:
                self._apply_to_selection(self._add_ceiling_at)
            elif remove_only:
                self._apply_to_selection(self._remove_ceiling_at)
            else:
                self._apply_to_selection(self._toggle_ceiling_at)
            self.dirty = True
            return True
        hit = self.aimed
        if not hit:
            return False
        self._push_undo()
        self._toggle_ceiling_at(hit.row, hit.col)
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
        self._flash("Cell cleared — Ct+Z to undo", 1.2, (1.0, 0.6, 0.5, 1.0))
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

    def _scroll_ceiling_height(self, direction: int) -> None:
        """Scroll while aimed at ceiling: raise/lower the ceiling itself."""
        hit = self.aimed
        if not hit or hit.part != "ceiling":
            return
        r, c = hit.row, hit.col
        td = tile_def(self.zone.tiles[r][c])
        if td and td.wall:
            return
        self._push_undo()
        self._ensure_face_textures()
        if direction > 0:
            changed = self._ceiling_raise_at(r, c)
        else:
            changed = self._ceiling_lower_at(r, c)
        if changed:
            self.dirty = True

    def _scroll_upper_wall(self, direction: int) -> None:
        """Scroll while aimed at ceiling: raise/lower upper wall height."""
        hit = self.aimed
        if not hit or hit.part not in ("ceiling", "ceiling2"):
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

    # ── Batch upper-wall height (selection-aware) ─────────────────

    def _raise_upper_wall_at(self, r: int, c: int) -> bool:
        """Raise upper wall height at *(r, c)* by ``snap_y``."""
        zone = self.zone
        td = tile_def(zone.tiles[r][c])
        if td and td.wall:
            return False
        ch = zone.ceil_heights[r][c]
        if ch >= SKY_HEIGHT:
            return False  # no ceiling to extend
        uwh = zone.upper_wall_height[r][c]
        if uwh <= ch:
            uwh = self._ceil_mass_top(r, c)
        new = min(CEIL_MAX, uwh + self.snap_y)
        zone.upper_wall_height[r][c] = new
        return True

    def _lower_upper_wall_at(self, r: int, c: int) -> bool:
        """Lower upper wall height at *(r, c)* by ``snap_y``."""
        zone = self.zone
        td = tile_def(zone.tiles[r][c])
        if td and td.wall:
            return False
        ch = zone.ceil_heights[r][c]
        uwh = zone.upper_wall_height[r][c]
        if uwh <= ch:
            return False
        new = uwh - self.snap_y
        zone.upper_wall_height[r][c] = new if new > ch + 0.01 else 0.0
        return True

    def _reset_upper_wall_at(self, r: int, c: int) -> bool:
        """Reset upper wall height at *(r, c)* to auto (0.0)."""
        zone = self.zone
        if zone.upper_wall_height[r][c] == 0.0:
            return False
        zone.upper_wall_height[r][c] = 0.0
        return True

    def _batch_raise_upper_wall(self) -> bool:
        """Raise upper wall height for all selected cells."""
        if not self._has_selection():
            return self._adjust_upper_wall_height(0)
        self._push_undo()
        self._ensure_face_textures()
        if self._apply_to_selection(self._raise_upper_wall_at):
            self.dirty = True
        return True

    def _batch_lower_upper_wall(self) -> bool:
        """Lower upper wall height for all selected cells."""
        if not self._has_selection():
            import pygame
            return self._adjust_upper_wall_height(pygame.KMOD_SHIFT)
        self._push_undo()
        self._ensure_face_textures()
        if self._apply_to_selection(self._lower_upper_wall_at):
            self.dirty = True
        return True

    def _batch_reset_upper_wall(self) -> bool:
        """Reset upper wall height for all selected cells to auto."""
        if not self._has_selection():
            import pygame
            return self._adjust_upper_wall_height(pygame.KMOD_CTRL)
        self._push_undo()
        self._ensure_face_textures()
        if self._apply_to_selection(self._reset_upper_wall_at):
            self.dirty = True
        return True

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
            new_ch = min(ch + self.snap_y, SKY_HEIGHT)
        else:
            min_ch = fh
            new_ch = max(ch - self.snap_y, min_ch)

        if abs(new_ch - ch) < 0.001:
            return
        self._push_undo()
        self._ensure_face_textures()
        zone.ceil_heights[r][c] = new_ch
        if new_ch >= SKY_HEIGHT - 0.01:
            self._clear_ceil_segments(r, c)
        else:
            self._shift_ceil_mass(r, c, ch, new_ch - ch)
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
            max_fh = FLOOR_MAX if is_sky else min(FLOOR_MAX, ch - 0.12)
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
            old_ch = ch
            zone.ceil_heights[r][c] = min(CEIL_MAX, ch + delta)
            self._shift_ceil_mass(r, c, old_ch,
                                  zone.ceil_heights[r][c] - old_ch)
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
        # Clear orphaned L2 data
        LAYER_NONE = -1000.0
        f2h = getattr(zone, 'floor2_heights', None)
        if f2h and len(f2h) > r:
            f2h[r][c] = LAYER_NONE
        c2h = getattr(zone, 'ceil2_heights', None)
        if c2h and len(c2h) > r:
            c2h[r][c] = LAYER_NONE
        f2t = getattr(zone, 'floor2_textures', None)
        if f2t and len(f2t) > r:
            f2t[r][c] = ""
        c2t = getattr(zone, 'ceil2_textures', None)
        if c2t and len(c2t) > r:
            c2t[r][c] = ""
        uwh2 = getattr(zone, 'upper_wall_height2', None)
        if uwh2 and len(uwh2) > r:
            uwh2[r][c] = 0.0

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
        # Clear orphaned L2 data
        LAYER_NONE = -1000.0
        f2h = getattr(zone, 'floor2_heights', None)
        if f2h and len(f2h) > r:
            f2h[r][c] = LAYER_NONE
        c2h = getattr(zone, 'ceil2_heights', None)
        if c2h and len(c2h) > r:
            c2h[r][c] = LAYER_NONE
        f2t = getattr(zone, 'floor2_textures', None)
        if f2t and len(f2t) > r:
            f2t[r][c] = ""
        c2t = getattr(zone, 'ceil2_textures', None)
        if c2t and len(c2t) > r:
            c2t[r][c] = ""
        uwh2 = getattr(zone, 'upper_wall_height2', None)
        if uwh2 and len(uwh2) > r:
            uwh2[r][c] = 0.0

    # ── Batch wall/open conversion (H / Shift+H) ─────────────────

    def _make_wall_at(self, r: int, c: int) -> bool:
        """Convert cell to wall.  Returns True if it was changed."""
        td = tile_def(self.zone.tiles[r][c])
        if td and td.wall:
            return False
        self._make_wall(r, c)
        return True

    def _make_open_at(self, r: int, c: int) -> bool:
        """Convert cell to open.  Returns True if it was changed."""
        td = tile_def(self.zone.tiles[r][c])
        if td and not td.wall:
            return False
        self._make_open(r, c)
        return True

    def _batch_make_wall(self) -> bool:
        """H key: convert to wall.  Selection-aware."""
        if self._has_selection():
            self._push_undo()
            self._ensure_face_textures()
            self._apply_to_selection(self._make_wall_at)
            self.dirty = True
            return True
        hit = self.aimed
        if not hit:
            return False
        self._push_undo()
        self._ensure_face_textures()
        self._make_wall(hit.row, hit.col)
        self.dirty = True
        return True

    def _batch_make_open(self) -> bool:
        """Shift+H: convert to open.  Selection-aware."""
        if self._has_selection():
            self._push_undo()
            self._ensure_face_textures()
            self._apply_to_selection(self._make_open_at)
            self.dirty = True
            return True
        hit = self.aimed
        if not hit:
            return False
        self._push_undo()
        self._ensure_face_textures()
        self._make_open(hit.row, hit.col)
        self.dirty = True
        return True

    # ── Batch flatten (L / Shift+L) ──────────────────────────────

    def _flatten_floors(self) -> bool:
        """L key with selection + aimed: set all selected floors to aimed floor height."""
        hit = self.aimed
        if not hit or not self._has_selection():
            return False
        target_fh = self.zone.floor_heights[hit.row][hit.col]
        def _set_floor(r: int, c: int) -> bool:
            zone = self.zone
            if abs(zone.floor_heights[r][c] - target_fh) < 0.001:
                return False
            zone.floor_heights[r][c] = target_fh
            self._sync_tile_type(r, c)
            return True
        self._push_undo()
        self._apply_to_selection(_set_floor)
        self.dirty = True
        return True

    def _flatten_ceilings(self) -> bool:
        """Shift+L with selection + aimed: set all selected ceilings to aimed ceiling height."""
        hit = self.aimed
        if not hit or not self._has_selection():
            return False
        target_ch = self.zone.ceil_heights[hit.row][hit.col]
        def _set_ceil(r: int, c: int) -> bool:
            zone = self.zone
            if abs(zone.ceil_heights[r][c] - target_ch) < 0.001:
                return False
            zone.ceil_heights[r][c] = target_ch
            self._sync_tile_type(r, c)
            return True
        self._push_undo()
        self._apply_to_selection(_set_ceil)
        self.dirty = True
        return True

    # ── Apply aimed cell properties to selection ─────────────────

    def _apply_cell_to_selection(self) -> bool:
        """Copy aimed cell's heights, tile, and textures to all selected cells."""
        hit = self.aimed
        if not hit or not self._has_selection():
            return False
        zone = self.zone
        src_r, src_c = hit.row, hit.col
        src_fh = zone.floor_heights[src_r][src_c]
        src_ch = zone.ceil_heights[src_r][src_c]
        src_tile = zone.tiles[src_r][src_c]
        src_ft = zone.floor_textures[src_r][src_c] if zone.floor_textures else ""
        src_ct = zone.ceil_textures[src_r][src_c] if zone.ceil_textures else ""
        src_wt = zone.wall_textures[src_r][src_c] if zone.wall_textures else ""
        src_ll = (zone.light_levels[src_r][src_c]
                  if zone.light_levels and len(zone.light_levels) > src_r else 1.0)
        # L2 fields
        _f2h = getattr(zone, 'floor2_heights', None)
        _c2h = getattr(zone, 'ceil2_heights', None)
        _f2t = getattr(zone, 'floor2_textures', None)
        _c2t = getattr(zone, 'ceil2_textures', None)
        _uwh2 = getattr(zone, 'upper_wall_height2', None)
        src_f2h = _f2h[src_r][src_c] if _f2h and len(_f2h) > src_r else -1000.0
        src_c2h = _c2h[src_r][src_c] if _c2h and len(_c2h) > src_r else -1000.0
        src_f2t = _f2t[src_r][src_c] if _f2t and len(_f2t) > src_r else ""
        src_c2t = _c2t[src_r][src_c] if _c2t and len(_c2t) > src_r else ""
        src_uwh2 = _uwh2[src_r][src_c] if _uwh2 and len(_uwh2) > src_r else 0.0

        def _apply(r: int, c: int) -> bool:
            zone.tiles[r][c] = src_tile
            zone.floor_heights[r][c] = src_fh
            zone.ceil_heights[r][c] = src_ch
            if zone.floor_textures:
                zone.floor_textures[r][c] = src_ft
            if zone.ceil_textures:
                zone.ceil_textures[r][c] = src_ct
            if zone.wall_textures and len(zone.wall_textures) > r:
                zone.wall_textures[r][c] = src_wt
            if zone.light_levels and len(zone.light_levels) > r:
                zone.light_levels[r][c] = src_ll
            # L2 fields
            if _f2h and len(_f2h) > r:
                _f2h[r][c] = src_f2h
            if _c2h and len(_c2h) > r:
                _c2h[r][c] = src_c2h
            if _f2t and len(_f2t) > r:
                _f2t[r][c] = src_f2t
            if _c2t and len(_c2t) > r:
                _c2t[r][c] = src_c2t
            if _uwh2 and len(_uwh2) > r:
                _uwh2[r][c] = src_uwh2
            return True

        self._push_undo()
        self._ensure_face_textures()
        self._apply_to_selection(_apply)
        self.dirty = True
        return True
