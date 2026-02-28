"""editor/view_3d/tools_curve.py — Curved wall segment placement for Zone3DEditor.

Place, select, edit, and delete curved (cylindrical) wall segments.

Actions (when tool == "curve"):
  LMB on ground       Place a new curve centred at aimed position
  LMB on curve         Select it
  LMB (w/ selected)    Move selected curve to aimed position
  RMB on ground        Deselect current curve
  RMB on curve          Delete it
  Scroll               Adjust radius
  Shift+Scroll         Adjust arc angle start
  Ctrl+Scroll          Adjust arc angle end
  Delete               Delete selected curve
  Escape               Deselect
"""

from __future__ import annotations

import math

from editor.view_3d.picking import _ray_vs_aabb

_ARC_SNAP = math.pi / 12.0   # 15° arc increments
_DEFAULT_RADIUS = 1.0
_DEFAULT_HEIGHT = 1.0


class CurveMixin:
    """Curved/cylindrical wall segment placement and manipulation."""

    _curve_radius: float = _DEFAULT_RADIUS
    _curve_selected: int | None = None

    # ── Picking ───────────────────────────────────────────────────

    def _curve_find_aimed(self) -> int | None:
        """Return index of curve under crosshair, or None.

        Uses bounding-box approximation (square around circle).
        """
        zone = self.zone
        if not zone or not zone.curves:
            return None

        fx, fy, fz = self._forward()
        ox, oy, oz = self.cam_x, self.cam_y, self.cam_z

        best_t = float("inf")
        best_idx: int | None = None

        for i, cv in enumerate(zone.curves):
            cx = float(cv.get("cx", 0.0))
            cy = float(cv.get("cy", 0.0))
            rad = float(cv.get("radius", 1.0))
            by = float(cv.get("base_y", 0.0))
            h = float(cv.get("height_scale", 1.0))

            result = _ray_vs_aabb(
                ox, oy, oz, fx, fy, fz,
                cx - rad, by, cy - rad,
                cx + rad, by + h, cy + rad,
            )
            if result is not None and result[0] < best_t:
                aimed = self.aimed
                if aimed is None or result[0] < aimed.t:
                    best_t = result[0]
                    best_idx = i

        return best_idx

    # ── Placement ─────────────────────────────────────────────────

    def _curve_place(self) -> None:
        hit = self.aimed
        if hit is None:
            return
        zone = self.zone
        if not zone:
            return

        fx, fy, fz = self._forward()
        ox, oy, oz = self.cam_x, self.cam_y, self.cam_z
        wx = ox + fx * hit.t
        wz = oz + fz * hit.t
        wx = max(0.1, min(zone.width - 0.1, wx))
        wz = max(0.1, min(zone.height - 0.1, wz))

        ri = max(0, min(zone.height - 1, int(wz)))
        ci = max(0, min(zone.width - 1, int(wx)))
        fh = zone.floor_heights[ri][ci] if zone.floor_heights else 0.0

        self._push_undo()
        cv: dict = {
            "cx": round(wx, 3),
            "cy": round(wz, 3),
            "radius": round(self._curve_radius, 3),
            "angle_start": 0.0,
            "angle_end": round(math.pi, 4),  # 180° half-circle default
            "height_scale": 1.0,
            "base_y": round(fh, 3),
            "texture": self.current_texture,
            "flags": 0,
        }
        zone.curves.append(cv)
        self._curve_selected = None
        self.dirty = True

    # ── Selection ─────────────────────────────────────────────────

    def _curve_select(self, idx: int) -> None:
        self._curve_selected = idx

    def _curve_deselect(self) -> None:
        self._curve_selected = None

    # ── Deletion ──────────────────────────────────────────────────

    def _curve_delete(self, idx: int | None = None) -> None:
        zone = self.zone
        if not zone or not zone.curves:
            return
        if idx is None:
            idx = self._curve_selected
        if idx is None or idx < 0 or idx >= len(zone.curves):
            return
        self._push_undo()
        zone.curves.pop(idx)
        if self._curve_selected is not None:
            if self._curve_selected == idx:
                self._curve_selected = None
            elif self._curve_selected > idx:
                self._curve_selected -= 1
        self.dirty = True

    # ── Move ──────────────────────────────────────────────────────

    def _curve_move_to_aimed(self) -> None:
        hit = self.aimed
        if hit is None or self._curve_selected is None:
            return
        zone = self.zone
        if not zone or not zone.curves:
            return
        idx = self._curve_selected
        if idx < 0 or idx >= len(zone.curves):
            return

        fx, fy, fz = self._forward()
        ox, oy, oz = self.cam_x, self.cam_y, self.cam_z
        wx = ox + fx * hit.t
        wz = oz + fz * hit.t

        self._push_undo()
        zone.curves[idx]["cx"] = round(wx, 3)
        zone.curves[idx]["cy"] = round(wz, 3)
        self.dirty = True

    # ── Adjust radius ─────────────────────────────────────────────

    def _curve_adjust_radius(self, direction: int) -> None:
        step = 0.25 * direction
        if self._curve_selected is not None:
            zone = self.zone
            if not zone or not zone.curves:
                return
            idx = self._curve_selected
            if idx < 0 or idx >= len(zone.curves):
                return
            cv = zone.curves[idx]
            cv["radius"] = round(max(0.25, float(cv.get("radius", 1.0)) + step), 3)
            self.dirty = True
        else:
            self._curve_radius = max(0.25, self._curve_radius + step)

    # ── Adjust arc angles ─────────────────────────────────────────

    def _curve_adjust_angle_start(self, direction: int) -> None:
        if self._curve_selected is None:
            return
        zone = self.zone
        if not zone or not zone.curves:
            return
        idx = self._curve_selected
        if idx < 0 or idx >= len(zone.curves):
            return
        cv = zone.curves[idx]
        a = float(cv.get("angle_start", 0.0))
        cv["angle_start"] = round((a + direction * _ARC_SNAP) % (2.0 * math.pi), 4)
        self.dirty = True

    def _curve_adjust_angle_end(self, direction: int) -> None:
        if self._curve_selected is None:
            return
        zone = self.zone
        if not zone or not zone.curves:
            return
        idx = self._curve_selected
        if idx < 0 or idx >= len(zone.curves):
            return
        cv = zone.curves[idx]
        a = float(cv.get("angle_end", math.pi))
        cv["angle_end"] = round((a + direction * _ARC_SNAP) % (2.0 * math.pi), 4)
        self.dirty = True

    # ── Paint texture ─────────────────────────────────────────────

    def _curve_paint(self) -> None:
        if self._curve_selected is None:
            return
        zone = self.zone
        if not zone or not zone.curves:
            return
        idx = self._curve_selected
        if idx < 0 or idx >= len(zone.curves):
            return
        self._push_undo()
        zone.curves[idx]["texture"] = self.current_texture
        self.dirty = True
