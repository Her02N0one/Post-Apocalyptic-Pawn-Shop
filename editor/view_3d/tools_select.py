"""editor/view_3d/tools_select.py — Rectangular area selection for Zone3DEditor.

First click  — set selection start corner
Second click — set selection end corner (rectangle is now active)
Then:
  LMB     Fill selection with current texture (top surface)
  RMB     Clear textures in selection
  Delete  Reset all cells in selection
  Escape  Clear selection

The selection is a grid-aligned rectangle of (row, col) cells.
"""

from __future__ import annotations

from core.tiles import tile_def
from editor.view_3d.constants import (
    DEFAULT_CEIL, DEFAULT_FLOOR, SKY_HEIGHT,
    FLOOR_MIN, FLOOR_MAX, CEIL_MIN, CEIL_MAX,
)
from editor.view_3d.cell_ops import reset_cell


class SelectMixin:
    """Rectangular area selection and batch operations."""

    # Selection state lives on the editor instance:
    #   self._sel_start: tuple[int, int] | None  — (row, col) of first corner
    #   self._sel_end:   tuple[int, int] | None  — (row, col) of second corner

    def _sel_click(self) -> bool:
        """Handle LMB in select tool mode.

        Plain click:  rectangle selection (two-click).
        Shift+click:  line selection from first corner to clicked cell.
        Ctrl+click:   toggle individual cell in/out of selection.
        """
        import pygame
        hit = self.aimed
        if not hit:
            return False
        r, c = hit.row, hit.col
        mod = pygame.key.get_mods()
        shift = bool(mod & pygame.KMOD_SHIFT)
        ctrl = bool(mod & pygame.KMOD_CTRL)

        # Ctrl+click: toggle individual cell
        if ctrl and hasattr(self, 'selection'):
            self.selection.toggle_cell(r, c)
            # Keep legacy in sync — set start/end if selection now has cells
            if self.selection.has_cells():
                bounds = self.selection.bounds()
                if bounds:
                    self._sel_start = (bounds[0], bounds[1])
                    self._sel_end = (bounds[2], bounds[3])
            else:
                self._sel_start = None
                self._sel_end = None
            return True

        # Shift+click: line selection from anchor to here
        if shift and self._sel_start is not None and hasattr(self, 'selection'):
            r1, c1 = self._sel_start
            self.selection.select_line(r1, c1, r, c)
            self._sel_end = (r, c)
            return True

        if self._sel_start is None:
            # First corner
            self._sel_start = (r, c)
            self._sel_end = None
            if hasattr(self, 'selection'):
                self.selection.begin_rect(r, c)
            return True

        if self._sel_end is None:
            # Second corner — complete the rectangle
            self._sel_end = (r, c)
            # Sync to universal selection
            if hasattr(self, 'selection'):
                r1, c1 = self._sel_start
                self.selection.select_rect(r1, c1, r, c)
            return True

        # Selection is already active — click starts a new selection
        # (clears old one; use Escape to clear without restarting).
        self._sel_cancel()
        self._sel_start = (r, c)
        self._sel_end = None
        if hasattr(self, 'selection'):
            self.selection.begin_rect(r, c)
        return True

    def _sel_rclick(self) -> bool:
        """Handle RMB in select tool mode."""
        if self._sel_start is not None and self._sel_end is not None:
            return self._sel_clear_textures()
        return False

    def _sel_delete(self) -> bool:
        """Handle Delete/Backspace in select tool mode."""
        if self._sel_start is not None and self._sel_end is not None:
            return self._sel_reset_cells()
        return False

    def _sel_cancel(self) -> None:
        """Cancel the current selection (both new and legacy)."""
        self._sel_start = None
        self._sel_end = None
        if hasattr(self, 'selection'):
            self.selection.clear_cells()

    def _sel_toggle_ceiling_mode(self) -> None:
        """Toggle between floor and ceiling selection mode."""
        self._sel_ceiling_mode = not self._sel_ceiling_mode
        if hasattr(self, 'selection'):
            self.selection.ceiling_mode = self._sel_ceiling_mode

    def _sel_scroll(self, direction: int, ceiling: bool | None = None) -> bool:
        """Scroll to raise/lower all selected cells' floors or ceilings.

        *ceiling* explicitly overrides which surface to adjust.
        If None, falls back to ``_sel_ceiling_mode`` (X toggle).

        In floor mode: raises/lowers floor heights (pushes ceiling up to
        preserve gap when raising into a ceiling).
        In ceiling mode: raises/lowers ceiling heights (clamped above floor).
        """
        bounds = self._sel_bounds()
        if bounds is None:
            return False
        r_min, c_min, r_max, c_max = bounds
        zone = self.zone
        snap = self.snap_y
        ceiling_mode = ceiling if ceiling is not None else getattr(self, '_sel_ceiling_mode', False)

        self._push_undo()
        self._ensure_face_textures()
        changed = False

        for r in range(r_min, r_max + 1):
            for c in range(c_min, c_max + 1):
                fh = zone.floor_heights[r][c]
                ch = zone.ceil_heights[r][c]
                is_sky = ch >= SKY_HEIGHT

                if ceiling_mode:
                    # --- Ceiling adjustment ---
                    if direction > 0:
                        # Raise ceiling
                        if ch >= SKY_HEIGHT:
                            continue
                        new_ch = min(ch + snap, SKY_HEIGHT)
                    else:
                        # Lower ceiling — bring in default if sky, else lower
                        if ch >= SKY_HEIGHT:
                            new_ch = fh + DEFAULT_CEIL
                        else:
                            min_ch = max(CEIL_MIN, fh + 0.05)
                            new_ch = max(ch - snap, min_ch)
                    if abs(new_ch - ch) < 0.001:
                        continue
                    zone.ceil_heights[r][c] = new_ch
                    changed = True
                else:
                    # --- Floor adjustment ---
                    if direction > 0:
                        max_fh = FLOOR_MAX if is_sky else min(FLOOR_MAX, ch - 0.05)
                        new_fh = min(fh + snap, max_fh)
                    else:
                        new_fh = max(FLOOR_MIN, fh - snap)
                    if abs(new_fh - fh) < 0.001:
                        continue
                    delta = new_fh - fh
                    zone.floor_heights[r][c] = new_fh
                    # Push ceiling up with floor to preserve gap
                    if not is_sky and delta > 0:
                        zone.ceil_heights[r][c] = min(CEIL_MAX, ch + delta)
                    # Keep segment top-edges in sync
                    for fi in range(4):
                        segs = zone.floor_step_segments[r][c][fi]
                        if segs:
                            segs[-1][1] = max(0.0, new_fh)
                    changed = True

        if changed:
            self.dirty = True
        return changed

    def _sel_bounds(self) -> tuple[int, int, int, int] | None:
        """Return (r_min, c_min, r_max, c_max) or None if no complete selection."""
        # New universal selection
        if hasattr(self, 'selection') and self.selection.has_cells():
            return self.selection.bounds()

        # Legacy rectangle
        if self._sel_start is None or self._sel_end is None:
            return None
        r1, c1 = self._sel_start
        r2, c2 = self._sel_end
        return (min(r1, r2), min(c1, c2), max(r1, r2), max(c1, c2))

    def _sel_fill_texture(self) -> bool:
        """Fill all cells in selection with current texture (floor surface)."""
        zone = self.zone
        tex = self.current_texture
        self._push_undo()
        self._ensure_face_textures()

        def _fill(r, c):
            td = tile_def(zone.tiles[r][c])
            if td and td.wall:
                for fi in range(4):
                    zone.face_textures[r][c][fi] = tex
                zone.wall_textures[r][c] = tex
            else:
                if zone.floor_textures:
                    zone.floor_textures[r][c] = tex

        if hasattr(self, 'selection') and self.selection.has_cells():
            for r, c in self.selection.iter_cells():
                _fill(r, c)
        else:
            bounds = self._sel_bounds()
            if bounds is None:
                return False
            r_min, c_min, r_max, c_max = bounds
            for r in range(r_min, r_max + 1):
                for c in range(c_min, c_max + 1):
                    _fill(r, c)
        self.dirty = True
        return True

    def _sel_clear_textures(self) -> bool:
        """Clear all textures in selection."""
        zone = self.zone
        self._push_undo()
        self._ensure_face_textures()

        def _clear(r, c):
            zone.face_textures[r][c] = ["", "", "", ""]
            if zone.wall_textures:
                zone.wall_textures[r][c] = ""
            if zone.floor_textures:
                zone.floor_textures[r][c] = ""
            if zone.ceil_textures:
                zone.ceil_textures[r][c] = ""
            if zone.floor_step_textures:
                zone.floor_step_textures[r][c] = ["", "", "", ""]
            if zone.ceil_step_textures:
                zone.ceil_step_textures[r][c] = ["", "", "", ""]

        if hasattr(self, 'selection') and self.selection.has_cells():
            for r, c in self.selection.iter_cells():
                _clear(r, c)
        else:
            bounds = self._sel_bounds()
            if bounds is None:
                return False
            r_min, c_min, r_max, c_max = bounds
            for r in range(r_min, r_max + 1):
                for c in range(c_min, c_max + 1):
                    _clear(r, c)
        self.dirty = True
        return True

    def _sel_reset_cells(self) -> bool:
        """Reset all cells in selection to default state."""
        self._push_undo()
        self._ensure_face_textures()

        if hasattr(self, 'selection') and self.selection.has_cells():
            for r, c in self.selection.iter_cells():
                reset_cell(self.zone, r, c, self._open_tile)
        else:
            bounds = self._sel_bounds()
            if bounds is None:
                return False
            r_min, c_min, r_max, c_max = bounds
            for r in range(r_min, r_max + 1):
                for c in range(c_min, c_max + 1):
                    reset_cell(self.zone, r, c, self._open_tile)

        self.dirty = True
        return True

    # ── Selection query helpers ────────────────────────────────────

    def _has_selection(self) -> bool:
        """Return True if any cell selection exists (new or legacy)."""
        if hasattr(self, 'selection') and self.selection.has_cells():
            return True
        return self._sel_start is not None and self._sel_end is not None

    def _apply_to_selection(self, fn) -> bool:
        """Apply *fn(r, c)* to every cell in the selection.

        Prefers the new universal selection if it has cells; falls back
        to the legacy rectangle.
        Returns True if *fn* returned True for at least one cell.
        The caller is responsible for pushing undo and setting dirty.
        """
        # New universal selection
        if hasattr(self, 'selection') and self.selection.has_cells():
            changed = False
            for r, c in self.selection.iter_cells():
                if fn(r, c):
                    changed = True
            return changed

        # Legacy rectangle
        bounds = self._sel_bounds()
        if bounds is None:
            return False
        r_min, c_min, r_max, c_max = bounds
        changed = False
        for r in range(r_min, r_max + 1):
            for c in range(c_min, c_max + 1):
                if fn(r, c):
                    changed = True
        return changed
