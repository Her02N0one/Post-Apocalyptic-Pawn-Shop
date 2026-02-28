"""editor/view_3d/tools_fog.py — Per-cell fog density/colour painting for Zone3DEditor.

Paint fog volumes (density + colour) on individual cells.

Actions (when tool == "fog"):
  LMB          Increase fog density at aimed cell
  RMB          Decrease fog density at aimed cell
  Shift+LMB    Set to maximum density (1.0)
  Shift+RMB    Clear fog (0.0)
  Scroll       Adjust fog paint step
  MMB          Eyedropper — pick fog density from aimed cell
"""

from __future__ import annotations


class FogMixin:
    """Per-cell fog density painting."""

    _fog_step: float = 0.1

    def _fog_ensure_grids(self) -> None:
        """Ensure fog_density and fog_color grids exist and are sized."""
        z = self.zone
        H, W = z.height, z.width
        if not z.fog_density or len(z.fog_density) != H:
            z.fog_density = [[0.0] * W for _ in range(H)]
        for r in range(H):
            if len(z.fog_density[r]) != W:
                z.fog_density[r] = [0.0] * W
        if not z.fog_color or len(z.fog_color) != H:
            z.fog_color = [[(128, 128, 128)] * W for _ in range(H)]
        for r in range(H):
            if len(z.fog_color[r]) != W:
                z.fog_color[r] = [(128, 128, 128)] * W

    def _fog_increase(self, shift: bool = False) -> None:
        """LMB: increase fog density."""
        hit = self.aimed
        if not hit:
            return
        self._fog_ensure_grids()
        zone = self.zone
        r, c = hit.row, hit.col
        old = zone.fog_density[r][c]
        new = 1.0 if shift else min(1.0, old + self._fog_step)
        if abs(new - old) < 0.001:
            return
        self._push_undo()
        zone.fog_density[r][c] = round(new, 3)
        self.dirty = True

    def _fog_decrease(self, shift: bool = False) -> None:
        """RMB: decrease fog density."""
        hit = self.aimed
        if not hit:
            return
        self._fog_ensure_grids()
        zone = self.zone
        r, c = hit.row, hit.col
        old = zone.fog_density[r][c]
        new = 0.0 if shift else max(0.0, old - self._fog_step)
        if abs(new - old) < 0.001:
            return
        self._push_undo()
        zone.fog_density[r][c] = round(new, 3)
        self.dirty = True

    def _fog_pick(self) -> None:
        """MMB: pick fog density from aimed cell."""
        hit = self.aimed
        if not hit:
            return
        self._fog_ensure_grids()
        self._fog_step = max(0.05, self.zone.fog_density[hit.row][hit.col])

    def _fog_adjust_step(self, direction: int) -> None:
        """Scroll: adjust fog paint step."""
        self._fog_step = round(
            max(0.05, min(0.5, self._fog_step + direction * 0.05)), 2)
