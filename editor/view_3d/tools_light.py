"""editor/view_3d/tools_light.py — Per-cell light-level painting for Zone3DEditor.

Paint light levels on individual cells.  Since cells default to full
bright (1.0), LMB *decreases* light (paints shadow) and RMB *increases*.

Actions (when tool == "light"):
  LMB          Decrease light level at aimed cell (paint shadow)
  RMB          Increase light level at aimed cell (brighten)
  Shift+LMB    Set to dark (0.0)
  Shift+RMB    Set to full bright (1.0)
  Scroll       Adjust light_step (0.05 increments, range 0.05–0.5)
  MMB          Eyedropper — pick current light level from aimed cell
"""

from __future__ import annotations


class LightMixin:
    """Per-cell ambient light level painting."""

    _light_step: float = 0.25

    def _light_ensure_grid(self) -> None:
        """Ensure zone.light_levels is correctly sized."""
        z = self.zone
        H, W = z.height, z.width
        if not z.light_levels or len(z.light_levels) != H:
            z.light_levels = [[1.0] * W for _ in range(H)]
        for r in range(H):
            if len(z.light_levels[r]) != W:
                z.light_levels[r] = [1.0] * W

    def _light_increase(self, shift: bool = False) -> None:
        """LMB: *decrease* light (paint shadow).  Shift = full dark."""
        hit = self.aimed
        if not hit:
            return
        self._light_ensure_grid()
        zone = self.zone
        r, c = hit.row, hit.col
        old = zone.light_levels[r][c]
        new = 0.0 if shift else max(0.0, old - self._light_step)
        if abs(new - old) < 0.001:
            return
        self._push_undo()
        zone.light_levels[r][c] = round(new, 3)
        self.dirty = True

    def _light_decrease(self, shift: bool = False) -> None:
        """RMB: *increase* light (brighten).  Shift = full bright."""
        hit = self.aimed
        if not hit:
            return
        self._light_ensure_grid()
        zone = self.zone
        r, c = hit.row, hit.col
        old = zone.light_levels[r][c]
        new = 1.0 if shift else min(1.0, old + self._light_step)
        if abs(new - old) < 0.001:
            return
        self._push_undo()
        zone.light_levels[r][c] = round(new, 3)
        self.dirty = True

    def _light_pick(self) -> None:
        """MMB: eyedropper — pick light level from aimed cell."""
        hit = self.aimed
        if not hit:
            return
        self._light_ensure_grid()
        self._light_step = self.zone.light_levels[hit.row][hit.col]

    def _light_adjust_step(self, direction: int) -> None:
        """Scroll: adjust the light paint step."""
        self._light_step = round(
            max(0.05, min(0.5, self._light_step + direction * 0.05)), 2)
