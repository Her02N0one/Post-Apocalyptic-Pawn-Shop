"""editor/view_3d/tools_layer2.py — Secondary floor/ceiling layer editing for Zone3DEditor.

Edit the second layer of floor/ceiling surfaces (catwalks, bridges, pits).

When active_layer == 2, these operations mirror L1 behavior:

  LMB          Raise secondary floor at aimed cell (creates it if absent)
  RMB          Lower secondary floor at aimed cell
  Shift+LMB    Raise secondary ceiling
  Shift+RMB    Lower secondary ceiling
  Ctrl+LMB     Remove secondary layer entirely (reset to sentinel)
  Scroll       Raise/lower L2 height (Shift+Scroll = cycle texture)
  X            Toggle floor2 ↔ ceil2 target
  T            Toggle ceil2 on/off
  R            Reset L2 at aimed cell
  Del          Clear L2 at aimed cell
  L / Shift+L  Flatten L2 floors/ceilings to aimed cell
"""

from __future__ import annotations

from editor.view_3d.constants import (
    FLOOR_MIN, FLOOR_MAX, CEIL_MIN, CEIL_MAX, SKY_HEIGHT,
)

LAYER_NONE = -1000.0


class Layer2Mixin:
    """Secondary (layer 2) floor/ceiling surface editing."""

    _layer2_target: str = "floor2"   # "floor2" or "ceil2"

    @property
    def _layer2_effective_target(self) -> str:
        """Resolve effective L2 target from aimed part, falling back to toggle."""
        hit = getattr(self, 'aimed', None)
        if hit is not None:
            if hit.part == "ceiling2":
                return "ceil2"
            if hit.part == "floor2":
                return "floor2"
        return self._layer2_target

    def _layer2_ensure_grids(self) -> None:
        """Ensure floor2/ceil2 height and texture grids are correctly sized."""
        z = self.zone
        H, W = z.height, z.width
        for attr, default in [
            ("floor2_heights", LAYER_NONE),
            ("ceil2_heights", LAYER_NONE),
        ]:
            g = getattr(z, attr)
            if not g or len(g) != H:
                g = [[default] * W for _ in range(H)]
                setattr(z, attr, g)
            for r in range(H):
                if len(g[r]) != W:
                    g[r] = [default] * W
        for attr in ("floor2_textures", "ceil2_textures"):
            g = getattr(z, attr)
            if not g or len(g) != H:
                g = [[""] * W for _ in range(H)]
                setattr(z, attr, g)
            for r in range(H):
                if len(g[r]) != W:
                    g[r] = [""] * W
        # Upper wall height for ceiling2
        uwh2 = getattr(z, 'upper_wall_height2', None)
        if not uwh2 or len(uwh2) != H:
            uwh2 = [[0.0] * W for _ in range(H)]
            z.upper_wall_height2 = uwh2
        for r in range(H):
            if len(uwh2[r]) != W:
                uwh2[r] = [0.0] * W

    def _layer2_raise_at(self, r: int, c: int,
                         shift: bool = False, ctrl: bool = False) -> bool:
        """Raise layer-2 surface at *(r, c)*.  Returns True if changed."""
        zone = self.zone
        if ctrl:
            zone.floor2_heights[r][c] = LAYER_NONE
            zone.ceil2_heights[r][c] = LAYER_NONE
            zone.floor2_textures[r][c] = ""
            zone.ceil2_textures[r][c] = ""
            return True
        if shift or self._layer2_effective_target == "ceil2":
            old = zone.ceil2_heights[r][c]
            if old <= LAYER_NONE + 1.0:
                old = zone.ceil_heights[r][c] if zone.ceil_heights else 1.0
            new = min(CEIL_MAX, old + self.snap_y)
            if abs(new - old) < 0.001:
                return False
            zone.ceil2_heights[r][c] = round(new, 3)
            if not zone.ceil2_textures[r][c]:
                zone.ceil2_textures[r][c] = self.current_texture
            return True
        else:
            old = zone.floor2_heights[r][c]
            if old <= LAYER_NONE + 1.0:
                base = zone.floor_heights[r][c] if zone.floor_heights else 0.0
                old = base + 0.5
            new = min(FLOOR_MAX, old + self.snap_y)
            if abs(new - old) < 0.001:
                return False
            zone.floor2_heights[r][c] = round(new, 3)
            if not zone.floor2_textures[r][c]:
                zone.floor2_textures[r][c] = self.current_texture
            return True

    def _layer2_raise(self, shift: bool = False, ctrl: bool = False) -> None:
        """LMB: raise secondary floor (or ceiling if shift).  Ctrl = remove.

        Selection-aware: batch-applies to all selected cells.
        """
        self._layer2_ensure_grids()
        if self._has_selection():
            self._push_undo()
            if self._apply_to_selection(
                lambda r, c: self._layer2_raise_at(r, c, shift, ctrl)
            ):
                self.dirty = True
            return
        hit = self.aimed
        if not hit:
            return
        self._push_undo()
        if self._layer2_raise_at(hit.row, hit.col, shift, ctrl):
            self.dirty = True

    def _layer2_lower_at(self, r: int, c: int, shift: bool = False) -> bool:
        """Lower layer-2 surface at *(r, c)*.  Returns True if changed."""
        zone = self.zone
        if shift or self._layer2_effective_target == "ceil2":
            old = zone.ceil2_heights[r][c]
            if old <= LAYER_NONE + 1.0:
                return False
            new = max(CEIL_MIN, old - self.snap_y)
            zone.ceil2_heights[r][c] = round(new, 3)
            return True
        else:
            old = zone.floor2_heights[r][c]
            if old <= LAYER_NONE + 1.0:
                return False
            new = max(FLOOR_MIN, old - self.snap_y)
            zone.floor2_heights[r][c] = round(new, 3)
            return True

    def _layer2_lower(self, shift: bool = False) -> None:
        """RMB: lower secondary floor (or ceiling if shift).

        Selection-aware: batch-applies to all selected cells.
        """
        self._layer2_ensure_grids()
        if self._has_selection():
            self._push_undo()
            if self._apply_to_selection(
                lambda r, c: self._layer2_lower_at(r, c, shift)
            ):
                self.dirty = True
            return
        hit = self.aimed
        if not hit:
            return
        self._push_undo()
        if self._layer2_lower_at(hit.row, hit.col, shift):
            self.dirty = True

    def _layer2_paint(self) -> None:
        """Apply current_texture to the aimed cell's secondary layer."""
        hit = self.aimed
        if not hit:
            return
        self._layer2_ensure_grids()
        zone = self.zone
        r, c = hit.row, hit.col
        if self._layer2_effective_target == "ceil2":
            if zone.ceil2_heights[r][c] <= LAYER_NONE + 1.0:
                return
            old = zone.ceil2_textures[r][c]
            if old == self.current_texture:
                return
            self._push_undo()
            zone.ceil2_textures[r][c] = self.current_texture
        else:
            if zone.floor2_heights[r][c] <= LAYER_NONE + 1.0:
                return
            old = zone.floor2_textures[r][c]
            if old == self.current_texture:
                return
            self._push_undo()
            zone.floor2_textures[r][c] = self.current_texture
        self.dirty = True

    def _layer2_toggle_target(self) -> None:
        """X key: toggle floor2 ↔ ceil2."""
        self._layer2_target = "ceil2" if self._layer2_target == "floor2" else "floor2"

    # ── Scroll-extend for L2 (mirrors L1 _extend_floor / _scroll_ceiling_height) ──

    def _layer2_scroll(self, direction: int) -> None:
        """Scroll while on layer 2: raise/lower L2 surface at aimed cell.

        When aimed at floor2, scrolls floor2.  When aimed at ceiling2,
        scrolls floor2 (the complementary surface) — mirroring how L1
        scroll on ceiling adjusts the upper wall instead of the ceiling
        itself.  Falls back to ``_layer2_target`` for non-L2 surfaces.
        """
        hit = self.aimed
        if not hit:
            return
        self._layer2_ensure_grids()
        zone = self.zone
        r, c = hit.row, hit.col
        snap = self.snap_y

        # Scroll on ceiling2 → extend wall above (like L1 ceiling scroll
        # extends upper_wall_height).  Scroll on floor2 → adjust floor2.
        if hit.part == "ceiling2":
            self._scroll_upper_wall2(direction)
            return
        elif hit.part == "floor2":
            target = "floor2"
        else:
            target = self._layer2_target

        if target == "ceil2":
            # Fallback for X-toggle when not aimed at an L2 surface
            self._scroll_upper_wall2(direction)
            return

        # floor2 scroll
        old = zone.floor2_heights[r][c]
        if old <= LAYER_NONE + 1.0:
            if direction < 0:
                return
            base = zone.floor_heights[r][c] if zone.floor_heights else 0.0
            old = base + 0.5
        new = old + snap * direction
        new = max(FLOOR_MIN, min(FLOOR_MAX, new))
        if abs(new - old) < 0.001:
            return
        self._push_undo()
        zone.floor2_heights[r][c] = round(new, 3)
        if not zone.floor2_textures[r][c]:
            zone.floor2_textures[r][c] = self.current_texture
        self.dirty = True

    def _scroll_upper_wall2(self, direction: int) -> None:
        """Scroll on ceiling2: raise/lower wall above the L2 ceiling.

        Mirrors ``_scroll_upper_wall`` for L1 ceilings.
        """
        hit = self.aimed
        if not hit:
            return
        self._layer2_ensure_grids()
        zone = self.zone
        r, c = hit.row, hit.col
        c2 = zone.ceil2_heights[r][c]
        if c2 <= LAYER_NONE + 1.0:
            return
        uwh2 = zone.upper_wall_height2[r][c]
        self._push_undo()
        if direction > 0:
            if uwh2 <= c2:
                uwh2 = c2
            new = uwh2 + self.snap_y
            zone.upper_wall_height2[r][c] = min(CEIL_MAX, new)
        else:
            if uwh2 <= c2:
                return
            new = uwh2 - self.snap_y
            zone.upper_wall_height2[r][c] = new if new > c2 + 0.01 else 0.0
        self.dirty = True

    # ── Reset L2 surface ──────────────────────────────────────────

    def _layer2_reset_at(self, r: int, c: int) -> bool:
        """Reset L2 data at *(r, c)* to sentinel.  Returns True if changed."""
        zone = self.zone
        self._layer2_ensure_grids()
        changed = False
        if zone.floor2_heights[r][c] > LAYER_NONE + 1.0:
            zone.floor2_heights[r][c] = LAYER_NONE
            zone.floor2_textures[r][c] = ""
            changed = True
        if zone.ceil2_heights[r][c] > LAYER_NONE + 1.0:
            zone.ceil2_heights[r][c] = LAYER_NONE
            zone.ceil2_textures[r][c] = ""
            changed = True
        if zone.upper_wall_height2[r][c] != 0.0:
            zone.upper_wall_height2[r][c] = 0.0
            changed = True
        return changed

    def _layer2_reset(self) -> bool:
        """R key on L2: reset L2 surface.  Selection-aware."""
        if self._has_selection():
            self._push_undo()
            if self._apply_to_selection(self._layer2_reset_at):
                self.dirty = True
            return True
        hit = self.aimed
        if not hit:
            return False
        self._push_undo()
        if self._layer2_reset_at(hit.row, hit.col):
            self.dirty = True
        return True

    # ── Selection-aware L2 scroll ─────────────────────────────────

    def _layer2_sel_scroll(self, direction: int) -> bool:
        """Scroll raise/lower for L2 across the selection."""
        if not self._has_selection():
            return False
        self._layer2_ensure_grids()
        zone = self.zone
        snap = self.snap_y
        self._push_undo()
        changed = False

        target = self._layer2_effective_target
        for r, c in self.selection.iter_cells():
            if target == "ceil2":
                old = zone.ceil2_heights[r][c]
                if old <= LAYER_NONE + 1.0:
                    if direction < 0:
                        continue
                    old = zone.ceil_heights[r][c] if zone.ceil_heights else 1.0
                new = max(CEIL_MIN, min(CEIL_MAX, old + snap * direction))
                if abs(new - old) < 0.001:
                    continue
                zone.ceil2_heights[r][c] = round(new, 3)
                if not zone.ceil2_textures[r][c]:
                    zone.ceil2_textures[r][c] = self.current_texture
                changed = True
            else:
                old = zone.floor2_heights[r][c]
                if old <= LAYER_NONE + 1.0:
                    if direction < 0:
                        continue
                    base = zone.floor_heights[r][c] if zone.floor_heights else 0.0
                    old = base + 0.5
                new = max(FLOOR_MIN, min(FLOOR_MAX, old + snap * direction))
                if abs(new - old) < 0.001:
                    continue
                zone.floor2_heights[r][c] = round(new, 3)
                if not zone.floor2_textures[r][c]:
                    zone.floor2_textures[r][c] = self.current_texture
                changed = True

        if changed:
            self.dirty = True
        return changed

    # ── L2 paint (selection-aware) ────────────────────────────────

    def _layer2_paint_at(self, r: int, c: int) -> bool:
        """Paint current_texture on L2 surface at *(r, c)*.  Returns True if changed."""
        self._layer2_ensure_grids()
        zone = self.zone
        tex = self.current_texture
        if self._layer2_effective_target == "ceil2":
            if zone.ceil2_heights[r][c] <= LAYER_NONE + 1.0:
                return False
            if zone.ceil2_textures[r][c] == tex:
                return False
            zone.ceil2_textures[r][c] = tex
            return True
        else:
            if zone.floor2_heights[r][c] <= LAYER_NONE + 1.0:
                return False
            if zone.floor2_textures[r][c] == tex:
                return False
            zone.floor2_textures[r][c] = tex
            return True

    def _layer2_erase_at(self, r: int, c: int) -> bool:
        """Erase texture on L2 surface at *(r, c)*.  Returns True if changed."""
        self._layer2_ensure_grids()
        zone = self.zone
        if self._layer2_effective_target == "ceil2":
            if not zone.ceil2_textures[r][c]:
                return False
            zone.ceil2_textures[r][c] = ""
            return True
        else:
            if not zone.floor2_textures[r][c]:
                return False
            zone.floor2_textures[r][c] = ""
            return True

    def _layer2_pick_texture(self) -> None:
        """Eyedropper for L2: pick texture from aimed L2 surface."""
        hit = self.aimed
        if not hit:
            return
        self._layer2_ensure_grids()
        zone = self.zone
        r, c = hit.row, hit.col
        if self._layer2_effective_target == "ceil2":
            picked = zone.ceil2_textures[r][c]
        else:
            picked = zone.floor2_textures[r][c]
        if not picked:
            return
        from editor.view_3d.constants import _ensure_palette
        palette = _ensure_palette()
        if picked in palette:
            self.tex_idx = palette.index(picked)
            self.current_texture = picked

    # ── L2 flatten (L / Shift+L with selection) ───────────────────

    def _layer2_flatten_floors(self) -> bool:
        """L key on L2 with selection: flatten all selected floor2 to aimed cell's floor2."""
        hit = self.aimed
        if not hit or not self._has_selection():
            return False
        self._layer2_ensure_grids()
        target = self.zone.floor2_heights[hit.row][hit.col]
        if target <= LAYER_NONE + 1.0:
            return False

        def _set(r: int, c: int) -> bool:
            if abs(self.zone.floor2_heights[r][c] - target) < 0.001:
                return False
            self.zone.floor2_heights[r][c] = target
            return True

        self._push_undo()
        self._apply_to_selection(_set)
        self.dirty = True
        return True

    def _layer2_flatten_ceilings(self) -> bool:
        """Shift+L on L2 with selection: flatten all selected ceil2 to aimed cell's ceil2."""
        hit = self.aimed
        if not hit or not self._has_selection():
            return False
        self._layer2_ensure_grids()
        target = self.zone.ceil2_heights[hit.row][hit.col]
        if target <= LAYER_NONE + 1.0:
            return False

        def _set(r: int, c: int) -> bool:
            if abs(self.zone.ceil2_heights[r][c] - target) < 0.001:
                return False
            self.zone.ceil2_heights[r][c] = target
            return True

        self._push_undo()
        self._apply_to_selection(_set)
        self.dirty = True
        return True

    # ── L2 toggle ceil2 (T key) ──────────────────────────────────

    def _layer2_toggle_ceil_at(self, r: int, c: int) -> bool:
        """Toggle ceil2 on/off at *(r, c)*.  Returns True if changed."""
        self._layer2_ensure_grids()
        zone = self.zone
        if zone.ceil2_heights[r][c] > LAYER_NONE + 1.0:
            zone.ceil2_heights[r][c] = LAYER_NONE
            zone.ceil2_textures[r][c] = ""
        else:
            base = zone.floor2_heights[r][c]
            if base <= LAYER_NONE + 1.0:
                base = zone.floor_heights[r][c] if zone.floor_heights else 0.0
            from editor.view_3d.constants import DEFAULT_CEIL
            zone.ceil2_heights[r][c] = round(base + DEFAULT_CEIL, 3)
            if not zone.ceil2_textures[r][c]:
                zone.ceil2_textures[r][c] = self.current_texture
        return True

    def _layer2_toggle_ceil(self) -> bool:
        """T key on L2: toggle ceil2.  Selection-aware."""
        self._layer2_ensure_grids()
        if self._has_selection():
            self._push_undo()
            self._apply_to_selection(self._layer2_toggle_ceil_at)
            self.dirty = True
            return True
        hit = self.aimed
        if not hit:
            return False
        self._push_undo()
        self._layer2_toggle_ceil_at(hit.row, hit.col)
        self.dirty = True
        return True
