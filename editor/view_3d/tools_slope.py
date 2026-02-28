"""editor/view_3d/tools_slope.py — Per-cell floor slope editing for Zone3DEditor.

Adjust floor slope gradients (dx, dy) per cell.

Actions (when tool == "slope"):
  LMB          Increase slope in current axis (+step)
  RMB          Decrease slope in current axis (-step)
  Shift+LMB    Reset slope to flat (0, 0)
  X            Toggle axis: dx ↔ dy
  Scroll       Adjust step size
"""

from __future__ import annotations


class SlopeMixin:
    """Per-cell floor slope editing."""

    _slope_axis: str = "dx"    # "dx" or "dy"
    _slope_step: float = 0.25

    def _slope_ensure_grids(self) -> None:
        """Ensure floor_slope_dx and floor_slope_dy are correctly sized."""
        z = self.zone
        H, W = z.height, z.width
        if not z.floor_slope_dx or len(z.floor_slope_dx) != H:
            z.floor_slope_dx = [[0.0] * W for _ in range(H)]
        for r in range(H):
            if len(z.floor_slope_dx[r]) != W:
                z.floor_slope_dx[r] = [0.0] * W
        if not z.floor_slope_dy or len(z.floor_slope_dy) != H:
            z.floor_slope_dy = [[0.0] * W for _ in range(H)]
        for r in range(H):
            if len(z.floor_slope_dy[r]) != W:
                z.floor_slope_dy[r] = [0.0] * W

    def _slope_increase(self, shift: bool = False) -> None:
        """LMB: increase slope in current axis (or reset if shift)."""
        hit = self.aimed
        if not hit:
            return
        self._slope_ensure_grids()
        zone = self.zone
        r, c = hit.row, hit.col

        if shift:
            # Reset both axes to flat
            self._push_undo()
            zone.floor_slope_dx[r][c] = 0.0
            zone.floor_slope_dy[r][c] = 0.0
            self.dirty = True
            return

        grid = zone.floor_slope_dx if self._slope_axis == "dx" else zone.floor_slope_dy
        old = grid[r][c]
        new = round(min(2.0, old + self._slope_step), 3)
        if abs(new - old) < 0.001:
            return
        self._push_undo()
        grid[r][c] = new
        self.dirty = True

    def _slope_decrease(self) -> None:
        """RMB: decrease slope in current axis."""
        hit = self.aimed
        if not hit:
            return
        self._slope_ensure_grids()
        zone = self.zone
        r, c = hit.row, hit.col
        grid = zone.floor_slope_dx if self._slope_axis == "dx" else zone.floor_slope_dy
        old = grid[r][c]
        new = round(max(-2.0, old - self._slope_step), 3)
        if abs(new - old) < 0.001:
            return
        self._push_undo()
        grid[r][c] = new
        self.dirty = True

    def _slope_toggle_axis(self) -> None:
        """X key: toggle between dx and dy."""
        self._slope_axis = "dy" if self._slope_axis == "dx" else "dx"

    def _slope_adjust_step(self, direction: int) -> None:
        """Scroll: adjust slope step size."""
        self._slope_step = round(
            max(0.05, min(1.0, self._slope_step + direction * 0.05)), 2)
