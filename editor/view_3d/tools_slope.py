"""editor/view_3d/tools_slope.py — Per-cell floor slope editing for Zone3DEditor.

Create stair-ramps naturally by facing the direction you want the
slope to rise toward, then clicking.

Actions (when tool == "slope"):
  LMB          Create stair rising toward camera look direction
  RMB          Flatten slope (reset to 0)
  Shift+LMB    Steepen existing slope (increase magnitude)
  Shift+RMB    Reduce existing slope (decrease magnitude)
  Scroll       Adjust number of stair divisions (2–16)
"""

from __future__ import annotations

import math

# Default number of stair steps for new slope cells
_DEFAULT_SLOPE_DIV = 4


class SlopeMixin:
    """Per-cell floor slope editing — direction-based with stair divisions."""

    _slope_step: float = 0.5
    _slope_div: int = _DEFAULT_SLOPE_DIV

    def _slope_ensure_grids(self) -> None:
        """Ensure floor_slope_dx, floor_slope_dy, floor_slope_div are sized."""
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
        if not z.floor_slope_div or len(z.floor_slope_div) != H:
            z.floor_slope_div = [[0] * W for _ in range(H)]
        for r in range(H):
            if len(z.floor_slope_div[r]) != W:
                z.floor_slope_div[r] = [0] * W

    def _slope_cardinal(self) -> tuple[float, float]:
        """Return (dx, dy) unit vector for the dominant cardinal
        direction the camera faces."""
        yaw = getattr(self, 'yaw', 0.0)
        fx = math.sin(yaw)
        fy = math.cos(yaw)
        if abs(fx) >= abs(fy):
            return (1.0 if fx > 0 else -1.0, 0.0)
        else:
            return (0.0, 1.0 if fy > 0 else -1.0)

    def _slope_increase(self, shift: bool = False) -> None:
        """LMB: create stair-ramp in camera direction (or steepen if shift)."""
        hit = self.aimed
        if not hit:
            return
        self._slope_ensure_grids()
        zone = self.zone
        r, c = hit.row, hit.col
        step = self._slope_step

        dx_old = zone.floor_slope_dx[r][c]
        dy_old = zone.floor_slope_dy[r][c]

        if shift:
            mag = math.hypot(dx_old, dy_old)
            if mag < 0.01:
                return
            new_mag = min(2.0, mag + step)
            scale = new_mag / mag
            new_dx = round(dx_old * scale, 3)
            new_dy = round(dy_old * scale, 3)
        else:
            cdx, cdy = self._slope_cardinal()
            new_dx = round(cdx * step, 3)
            new_dy = round(cdy * step, 3)

        if abs(new_dx - dx_old) < 0.001 and abs(new_dy - dy_old) < 0.001:
            return
        self._push_undo()
        zone.floor_slope_dx[r][c] = new_dx
        zone.floor_slope_dy[r][c] = new_dy
        zone.floor_slope_div[r][c] = self._slope_div
        self.dirty = True

    def _slope_decrease(self, shift: bool = False) -> None:
        """RMB: flatten (or reduce magnitude if shift)."""
        hit = self.aimed
        if not hit:
            return
        self._slope_ensure_grids()
        zone = self.zone
        r, c = hit.row, hit.col

        dx_old = zone.floor_slope_dx[r][c]
        dy_old = zone.floor_slope_dy[r][c]

        if shift:
            mag = math.hypot(dx_old, dy_old)
            if mag < 0.01:
                return
            new_mag = max(0.0, mag - self._slope_step)
            if new_mag < 0.01:
                new_dx, new_dy = 0.0, 0.0
            else:
                scale = new_mag / mag
                new_dx = round(dx_old * scale, 3)
                new_dy = round(dy_old * scale, 3)
        else:
            new_dx, new_dy = 0.0, 0.0

        if abs(new_dx - dx_old) < 0.001 and abs(new_dy - dy_old) < 0.001:
            return
        self._push_undo()
        zone.floor_slope_dx[r][c] = new_dx
        zone.floor_slope_dy[r][c] = new_dy
        if new_dx == 0.0 and new_dy == 0.0:
            zone.floor_slope_div[r][c] = 0
        self.dirty = True

    def _slope_adjust_step(self, direction: int) -> None:
        """Scroll: adjust number of stair divisions (2–16)."""
        self._slope_div = max(2, min(16, self._slope_div + direction))
