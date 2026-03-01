"""editor/view_3d/tools_box.py — Rectangular prism tool for Zone3DEditor.

Place, select, move, resize, delete, and rotate freeform prisms in 3D.
Supports grid-snap and auto-stacking on top of existing geometry.

Actions (nothing selected):
  LMB on ground       Place prism (auto-stacks on geometry)
  LMB on prism         Select it
  RMB on prism         Delete it
  Scroll              Adjust width  (W axis)
  Shift+Scroll        Adjust depth  (D axis)
  Ctrl+Scroll         Adjust height (H axis)
  R                   Rotate placement yaw by 90°
  G                   Toggle grid-snap

Actions (prism selected):
  LMB on ground       Move selected prism (auto-stacks)
  RMB                 Deselect
  Scroll              Move up / down (Z axis)
  Shift+Scroll        Rotate 15° increments
  Ctrl+Scroll         Adjust height
  R                   Rotate 90°
  Delete / Backspace  Delete selected prism
  Escape              Deselect
"""

from __future__ import annotations

import math

from editor.view_3d.picking import _ray_vs_obb

# Size presets — step in 0.25 increments
_SIZE_STEP = 0.25
_SIZE_MIN  = 0.25
_SIZE_MAX  = 8.0
_YAW_SNAP  = math.pi / 12.0  # 15° increments
_YAW_90    = math.pi / 2.0


class BoxMixin:
    """Freeform rectangular prism placement, selection, and manipulation."""

    # Current prism dimensions for placement
    _box_w: float = 1.0
    _box_h: float = 1.0
    _box_d: float = 1.0
    _box_yaw: float = 0.0

    # Grid snap mode (prisms snap to quarter-cell grid)
    _box_snap: bool = True

    # Selected prism index (into zone.boxes), or None
    _box_selected: int | None = None

    # ── Prism picking ─────────────────────────────────────────────

    def _box_find_aimed(self) -> int | None:
        """Return index of prism under crosshair, or None."""
        zone = self.zone
        if not zone or not zone.boxes:
            return None

        fx, fy, fz = self._forward()
        ox, oy, oz = self.cam_x, self.cam_y, self.cam_z

        best_t = float("inf")
        best_idx: int | None = None

        for i, b in enumerate(zone.boxes):
            result = _ray_vs_obb(
                ox, oy, oz, fx, fy, fz,
                float(b.get("x", 0)),
                float(b.get("y", 0)),
                float(b.get("z", 0)),
                float(b.get("w", 1)),
                float(b.get("h", 1)),
                float(b.get("d", 1)),
                float(b.get("yaw", 0)),
            )
            if result is not None and result[0] < best_t:
                best_t = result[0]
                best_idx = i

        # Only pick prism if closer than aimed cell
        if best_idx is not None:
            aimed = self.aimed
            if aimed is None or best_t < aimed.t:
                return best_idx

        return None

    # ── Snap helper ───────────────────────────────────────────────

    def _box_snap_pos(self, wx: float, wz: float) -> tuple[float, float]:
        """Snap world coords to quarter-cell grid if snap is on."""
        if not self._box_snap:
            return (round(wx, 3), round(wz, 3))
        sx = round(wx * 4.0) / 4.0
        sz = round(wz * 4.0) / 4.0
        return (round(sx, 3), round(sz, 3))

    # ── Stack height ──────────────────────────────────────────────

    def _box_stack_height(self, wx: float, wz: float,
                          w: float, d: float,
                          exclude_idx: int | None = None) -> float:
        """Determine the Z base for a new prism at (wx, wz).

        Starts from the floor height at that cell, then checks all
        existing prisms for overlaps and stacks on top of the tallest.
        *exclude_idx* skips that box (used when moving a selected box).
        """
        zone = self.zone
        ci = max(0, min(zone.width - 1, int(wx)))
        ri = max(0, min(zone.height - 1, int(wz)))
        base = zone.floor_heights[ri][ci] if zone.floor_heights else 0.0

        # Check AABB overlap with existing prisms (ignoring yaw for stacking)
        hw, hd = w * 0.5, d * 0.5
        for i, b in enumerate(zone.boxes or []):
            if i == exclude_idx:
                continue
            bx = float(b.get("x", 0))
            bz = float(b.get("y", 0))
            bw = float(b.get("w", 1)) * 0.5
            bd = float(b.get("d", 1)) * 0.5
            btop = float(b.get("z", 0)) + float(b.get("h", 1))

            if (abs(wx - bx) < hw + bw - 0.01 and
                    abs(wz - bz) < hd + bd - 0.01):
                base = max(base, btop)

        return round(base, 3)

    # ── Placement ─────────────────────────────────────────────────

    def _box_place(self) -> None:
        """Place a new prism at the aimed position with auto-stacking."""
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

        w, d, h = self._box_w, self._box_d, self._box_h
        wx, wz = self._box_snap_pos(wx, wz)
        base_z = self._box_stack_height(wx, wz, w, d)

        self._push_undo()
        bx: dict = {
            "x": wx,
            "y": wz,
            "z": base_z,
            "w": round(w, 3),
            "h": round(h, 3),
            "d": round(d, 3),
            "yaw": round(self._box_yaw, 4),
            "textures": {"N": self.current_texture,
                         "S": self.current_texture,
                         "E": self.current_texture,
                         "W": self.current_texture,
                         "top": self.current_texture,
                         "bot": self.current_texture},
            "collision": True,
        }
        zone.boxes.append(bx)
        self._box_selected = None
        self.dirty = True

    # ── Selection ─────────────────────────────────────────────────

    def _box_select(self, idx: int) -> None:
        self._box_selected = idx

    def _box_deselect(self) -> None:
        self._box_selected = None

    # ── Deletion ──────────────────────────────────────────────────

    def _box_delete(self, idx: int | None = None) -> None:
        """Delete prism at *idx* (or the selected prism)."""
        zone = self.zone
        if not zone or not zone.boxes:
            return
        if idx is None:
            idx = self._box_selected
        if idx is None or idx < 0 or idx >= len(zone.boxes):
            return

        self._push_undo()
        zone.boxes.pop(idx)

        if self._box_selected is not None:
            if self._box_selected == idx:
                self._box_selected = None
            elif self._box_selected > idx:
                self._box_selected -= 1
        self.dirty = True

    # ── Move ──────────────────────────────────────────────────────

    def _box_move_to_aimed(self) -> None:
        """Move the selected prism to the aimed position (auto-stacks)."""
        hit = self.aimed
        if hit is None or self._box_selected is None:
            return
        zone = self.zone
        if not zone or not zone.boxes:
            return
        idx = self._box_selected
        if idx < 0 or idx >= len(zone.boxes):
            return

        fx, fy, fz = self._forward()
        ox, oy, oz = self.cam_x, self.cam_y, self.cam_z
        wx = ox + fx * hit.t
        wz = oz + fz * hit.t
        wx = max(0.1, min(zone.width - 0.1, wx))
        wz = max(0.1, min(zone.height - 0.1, wz))

        b = zone.boxes[idx]
        w = float(b.get("w", 1))
        d = float(b.get("d", 1))

        wx, wz = self._box_snap_pos(wx, wz)
        base_z = self._box_stack_height(wx, wz, w, d, exclude_idx=idx)

        self._push_undo()
        zone.boxes[idx]["x"] = wx
        zone.boxes[idx]["y"] = wz
        zone.boxes[idx]["z"] = base_z
        self.dirty = True

    # ── Rotation ──────────────────────────────────────────────────

    def _box_rotate_90(self) -> None:
        """Rotate by 90° (placement yaw, or selected prism)."""
        if self._box_selected is not None:
            zone = self.zone
            if not zone or not zone.boxes:
                return
            idx = self._box_selected
            if idx < 0 or idx >= len(zone.boxes):
                return
            b = zone.boxes[idx]
            b["yaw"] = round((float(b.get("yaw", 0)) + _YAW_90)
                             % (2.0 * math.pi), 4)
            self.dirty = True
        else:
            self._box_yaw = (self._box_yaw + _YAW_90) % (2.0 * math.pi)

    def _box_rotate_fine(self, direction: int) -> None:
        """Rotate selected prism by 15° increments."""
        if self._box_selected is None:
            return
        zone = self.zone
        if not zone or not zone.boxes:
            return
        idx = self._box_selected
        if idx < 0 or idx >= len(zone.boxes):
            return
        b = zone.boxes[idx]
        yaw = float(b.get("yaw", 0.0)) + direction * _YAW_SNAP
        b["yaw"] = round(yaw % (2.0 * math.pi), 4)
        self.dirty = True

    # ── Resize ────────────────────────────────────────────────────

    def _box_adjust_size(self, direction: int, axis: str = "w") -> None:
        """Adjust prism dimension for next placement (or selected prism).

        *axis* -- 'w' (width), 'd' (depth), 'h' (height).
        """
        step = _SIZE_STEP * direction
        if self._box_selected is not None:
            zone = self.zone
            if not zone or not zone.boxes:
                return
            idx = self._box_selected
            if idx < 0 or idx >= len(zone.boxes):
                return
            b = zone.boxes[idx]
            val = max(_SIZE_MIN, min(_SIZE_MAX, float(b.get(axis, 1.0)) + step))
            b[axis] = round(val, 3)
            self.dirty = True
        else:
            if axis == "w":
                self._box_w = max(_SIZE_MIN, min(_SIZE_MAX, self._box_w + step))
            elif axis == "d":
                self._box_d = max(_SIZE_MIN, min(_SIZE_MAX, self._box_d + step))
            elif axis == "h":
                self._box_h = max(_SIZE_MIN, min(_SIZE_MAX, self._box_h + step))

    # ── Vertical shift (selected prism) ──────────────────────────

    def _box_shift_z(self, direction: int) -> None:
        """Move selected prism up/down by snap_y."""
        if self._box_selected is None:
            return
        zone = self.zone
        if not zone or not zone.boxes:
            return
        idx = self._box_selected
        if idx < 0 or idx >= len(zone.boxes):
            return
        b = zone.boxes[idx]
        z = float(b.get("z", 0.0))
        z += direction * self.snap_y
        b["z"] = round(z, 3)
        self.dirty = True

    # ── Snap toggle ───────────────────────────────────────────────

    def _box_toggle_snap(self) -> None:
        """Toggle grid-snap mode on/off."""
        self._box_snap = not self._box_snap
