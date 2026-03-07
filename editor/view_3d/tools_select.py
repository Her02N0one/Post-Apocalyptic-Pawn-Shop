"""editor/view_3d/tools_select.py — Rectangular area selection for Zone3DEditor.

First click  — set selection start corner
Second click — set selection end corner (rectangle is now active)
Then:
  LMB     Fill selection with current texture (top surface)
  RMB     Clear textures in selection
  Delete  Reset all cells in selection
  Escape  Clear selection

The selection is a grid-aligned rectangle of (row, col) cells.
All state lives on ``self.selection`` (:class:`SelectionState`).
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

    # All selection state is on ``self.selection`` (a SelectionState instance).
    # Key fields used by this mixin:
    #   selection.anchor      — (row, col) of first corner (set by begin_rect)
    #   selection.has_cells() — True when rectangle (or arbitrary) selection is active
    #   selection.ceiling_mode — floor/ceiling targeting toggle

    def _sel_click(self) -> bool:
        """Handle LMB in select tool mode.

        Plain click:  rectangle selection (two-click).
        Shift+click:  line selection from anchor to clicked cell.
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
        sel = self.selection

        # Ctrl+click: toggle individual cell
        if ctrl:
            sel.toggle_cell(r, c)
            return True

        # Shift+click: line selection from anchor to here
        if shift:
            anchor = sel.anchor
            if anchor is None and sel.has_cells():
                bounds = sel.bounds()
                if bounds:
                    anchor = (bounds[0], bounds[1])
            if anchor is not None:
                r1, c1 = anchor
                sel.select_line(r1, c1, r, c)
                return True

        # No anchor yet and no completed selection → first corner
        if sel.anchor is None and not sel.has_cells():
            sel.begin_rect(r, c)
            return True

        # First corner placed, waiting for second → complete rectangle
        if sel.anchor is not None and not sel.has_cells():
            sel.finish_rect(r, c)
            return True

        # Selection already complete → start a new one
        self._sel_cancel()
        sel.begin_rect(r, c)
        return True

    def _sel_rclick(self) -> bool:
        """Handle RMB in select tool mode."""
        if self.selection.has_cells():
            return self._sel_clear_textures()
        return False

    def _sel_delete(self) -> bool:
        """Handle Delete/Backspace in select tool mode."""
        if self.selection.has_cells():
            return self._sel_reset_cells()
        return False

    def _sel_cancel(self) -> None:
        """Cancel the current selection."""
        self.selection.clear_cells()

    def _sel_toggle_ceiling_mode(self) -> None:
        """Toggle between floor and ceiling selection mode."""
        self.selection.toggle_ceiling_mode()

    def _sel_scroll(self, direction: int, ceiling: bool | None = None) -> bool:
        """Scroll to raise/lower all selected cells' floors or ceilings.

        *ceiling* explicitly overrides which surface to adjust.
        If None, falls back to ``selection.ceiling_mode`` (X toggle).

        In floor mode: raises/lowers floor heights (pushes ceiling up to
        preserve gap when raising into a ceiling).
        In ceiling mode: raises/lowers ceiling heights (clamped above floor).
        """
        if not self.selection.has_cells():
            return False
        zone = self.zone
        snap = self.snap_y
        ceiling_mode = ceiling if ceiling is not None else self.selection.ceiling_mode

        self._push_undo()
        self._ensure_face_textures()
        changed = False

        for r, c in self.selection.iter_cells():
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
                        min_ch = max(CEIL_MIN, fh + 0.12)
                        new_ch = max(ch - snap, min_ch)
                if abs(new_ch - ch) < 0.001:
                    continue
                zone.ceil_heights[r][c] = new_ch
                if new_ch >= SKY_HEIGHT - 0.01:
                    self._clear_ceil_segments(r, c)
                elif ch < SKY_HEIGHT:
                    self._shift_ceil_mass(r, c, ch, new_ch - ch)
                changed = True
            else:
                # --- Floor adjustment ---
                if direction > 0:
                    max_fh = FLOOR_MAX if is_sky else min(FLOOR_MAX, ch - 0.12)
                    new_fh = min(fh + snap, max_fh)
                else:
                    new_fh = max(FLOOR_MIN, fh - snap)
                if abs(new_fh - fh) < 0.001:
                    continue
                delta = new_fh - fh
                zone.floor_heights[r][c] = new_fh
                # Push ceiling up with floor to preserve gap
                if not is_sky and delta > 0:
                    old_ch = ch
                    zone.ceil_heights[r][c] = min(CEIL_MAX, ch + delta)
                    self._shift_ceil_mass(
                        r, c, old_ch,
                        zone.ceil_heights[r][c] - old_ch)
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
        return self.selection.bounds()

    def _sel_fill_texture(self) -> bool:
        """Fill all cells in selection with current texture (floor surface)."""
        if not self.selection.has_cells():
            return False
        zone = self.zone
        tex = self.current_texture
        self._push_undo()
        self._ensure_face_textures()

        # L2 mode: paint floor2/ceil2 flat textures
        if getattr(self, '_sculpt_layer2', False):
            self._layer2_ensure_grids()
            target = self._layer2_effective_target
            for r, c in self.selection.iter_cells():
                if target == "ceil2":
                    ct2 = getattr(zone, 'ceil2_textures', None)
                    if ct2:
                        ct2[r][c] = tex
                else:
                    ft2 = getattr(zone, 'floor2_textures', None)
                    if ft2:
                        ft2[r][c] = tex
            self.dirty = True
            return True

        for r, c in self.selection.iter_cells():
            td = tile_def(zone.tiles[r][c])
            if td and td.wall:
                for fi in range(4):
                    zone.face_textures[r][c][fi] = tex
                zone.wall_textures[r][c] = tex
            else:
                if zone.floor_textures:
                    zone.floor_textures[r][c] = tex

        self.dirty = True
        return True

    def _sel_clear_textures(self) -> bool:
        """Clear all textures in selection."""
        if not self.selection.has_cells():
            return False
        zone = self.zone
        self._push_undo()
        self._ensure_face_textures()

        for r, c in self.selection.iter_cells():
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
            # L2 textures
            ft2 = getattr(zone, 'floor2_textures', None)
            if ft2:
                ft2[r][c] = ""
            ct2 = getattr(zone, 'ceil2_textures', None)
            if ct2:
                ct2[r][c] = ""

        self.dirty = True
        return True

    def _sel_reset_cells(self) -> bool:
        """Reset all cells in selection to default state."""
        if not self.selection.has_cells():
            return False
        self._push_undo()
        self._ensure_face_textures()

        for r, c in self.selection.iter_cells():
            reset_cell(self.zone, r, c, self._open_tile)

        self.dirty = True
        self._flash("Selection cleared — Ct+Z to undo", 1.2, (1.0, 0.6, 0.5, 1.0))
        return True

    # ── Selection query helpers ────────────────────────────────────

    def _has_selection(self) -> bool:
        """Return True if any cell selection exists."""
        return self.selection.has_cells()

    def _apply_to_selection(self, fn) -> bool:
        """Apply *fn(r, c)* to every cell in the selection.

        Returns True if *fn* returned True for at least one cell.
        The caller is responsible for pushing undo and setting dirty.
        """
        if not self.selection.has_cells():
            return False
        changed = False
        for r, c in self.selection.iter_cells():
            if fn(r, c):
                changed = True
        return changed
