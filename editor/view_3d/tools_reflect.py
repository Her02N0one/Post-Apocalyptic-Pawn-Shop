"""editor/view_3d/tools_reflect.py — Per-cell reflectivity painting for Zone3DEditor.

Paint floor reflectivity (0–255) on individual cells.

Actions (when tool == "reflect"):
  LMB          Increase reflectivity at aimed cell
  RMB          Decrease reflectivity at aimed cell
  Shift+LMB    Set to full mirror (255)
  Shift+RMB    Set to no reflection (0)
  Scroll       Adjust paint step
  MMB          Eyedropper — pick reflectivity from aimed cell
"""

from __future__ import annotations


class ReflectMixin:
    """Per-cell floor reflectivity painting."""

    _reflect_step: int = 128

    def _reflect_ensure_grid(self) -> None:
        """Ensure zone.reflect_map is correctly sized."""
        z = self.zone
        H, W = z.height, z.width
        if not z.reflect_map or len(z.reflect_map) != H:
            z.reflect_map = [[0] * W for _ in range(H)]
        for r in range(H):
            if len(z.reflect_map[r]) != W:
                z.reflect_map[r] = [0] * W

    def _reflect_increase(self, shift: bool = False) -> None:
        """LMB: increase reflectivity at aimed cell."""
        hit = self.aimed
        if not hit:
            return
        self._reflect_ensure_grid()
        zone = self.zone
        r, c = hit.row, hit.col
        old = zone.reflect_map[r][c]
        new = 255 if shift else min(255, old + self._reflect_step)
        if new == old:
            return
        self._push_undo()
        zone.reflect_map[r][c] = new
        self.dirty = True

    def _reflect_decrease(self, shift: bool = False) -> None:
        """RMB: decrease reflectivity at aimed cell."""
        hit = self.aimed
        if not hit:
            return
        self._reflect_ensure_grid()
        zone = self.zone
        r, c = hit.row, hit.col
        old = zone.reflect_map[r][c]
        new = 0 if shift else max(0, old - self._reflect_step)
        if new == old:
            return
        self._push_undo()
        zone.reflect_map[r][c] = new
        self.dirty = True

    def _reflect_pick(self) -> None:
        """MMB: pick reflectivity from aimed cell."""
        hit = self.aimed
        if not hit:
            return
        self._reflect_ensure_grid()
        val = self.zone.reflect_map[hit.row][hit.col]
        self._reflect_step = max(1, val)

    def _reflect_adjust_step(self, direction: int) -> None:
        """Scroll: adjust reflect paint step."""
        self._reflect_step = max(1, min(128, self._reflect_step + direction * 8))
