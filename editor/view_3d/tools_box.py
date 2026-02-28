"""editor/view_3d/tools_box.py — Freeform box tool for Zone3DEditor.

Place, select, move, resize, delete, and rotate freeform boxes in 3D.

Actions:
  LMB on ground       Place box of current size at aimed position
  LMB on box          Select it
  LMB (w/ selected)   Move selected box to aimed position
  RMB on box          Delete it
  RMB on ground       Deselect current box
  Scroll              Cycle texture palette
  Shift+Scroll        Rotate selected box (15° snap)
  R + Scroll          Resize width/depth (with R held)
  Ctrl+Scroll         Adjust height of next box
  Delete / Backspace  Delete selected box
  Escape              Deselect
"""

from __future__ import annotations

import math

from editor.view_3d.picking import _ray_vs_obb

# Default box dimensions for new placements
_DEFAULT_W = 1.0
_DEFAULT_H = 1.0
_DEFAULT_D = 1.0
_YAW_SNAP = math.pi / 12.0  # 15° increments


class BoxMixin:
    """Freeform box placement, selection, and manipulation."""

    # Current box dimensions for placement
    _box_w: float = _DEFAULT_W
    _box_h: float = _DEFAULT_H
    _box_d: float = _DEFAULT_D
    _box_yaw: float = 0.0

    # Selected box index (into zone.boxes), or None
    _box_selected: int | None = None

    # ── Box picking ───────────────────────────────────────────────

    def _box_find_aimed(self) -> int | None:
        """Return index of box under crosshair, or None."""
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

        # Only pick box if closer than aimed cell
        if best_idx is not None:
            aimed = self.aimed
            if aimed is None or best_t < aimed.t:
                return best_idx

        return None

    # ── Placement ─────────────────────────────────────────────────

    def _box_place(self) -> None:
        """Place a new box at the aimed ground position."""
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

        # Floor height at landing cell
        ci = max(0, min(zone.width - 1, int(wx)))
        ri = max(0, min(zone.height - 1, int(wz)))
        fh = zone.floor_heights[ri][ci] if zone.floor_heights else 0.0

        self._push_undo()
        bx: dict = {
            "x": round(wx, 3),
            "y": round(wz, 3),
            "z": round(fh, 3),
            "w": round(self._box_w, 3),
            "h": round(self._box_h, 3),
            "d": round(self._box_d, 3),
            "yaw": round(self._box_yaw, 4),
            "textures": {"N": self.current_texture,
                         "S": self.current_texture,
                         "E": self.current_texture,
                         "W": self.current_texture,
                         "top": self.current_texture,
                         "bot": self.current_texture},
            "collision": False,
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
        """Delete box at *idx* (or the selected box)."""
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
        """Move the selected box to the aimed position."""
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

        self._push_undo()
        zone.boxes[idx]["x"] = round(wx, 3)
        zone.boxes[idx]["y"] = round(wz, 3)
        self.dirty = True

    # ── Rotation ──────────────────────────────────────────────────

    def _box_rotate(self, direction: int) -> None:
        """Rotate the selected box by 15° increments."""
        if self._box_selected is None:
            return
        zone = self.zone
        if not zone or not zone.boxes:
            return
        idx = self._box_selected
        if idx < 0 or idx >= len(zone.boxes):
            return

        b = zone.boxes[idx]
        yaw = float(b.get("yaw", 0.0))
        yaw += direction * _YAW_SNAP
        # Normalise to [0, 2π)
        yaw = yaw % (2.0 * math.pi)
        b["yaw"] = round(yaw, 4)
        self.dirty = True

    # ── Resize ────────────────────────────────────────────────────

    def _box_adjust_size(self, direction: int, axis: str = "w") -> None:
        """Adjust box dimension for next placement (or selected box).

        *axis* -- 'w' (width), 'd' (depth), 'h' (height).
        """
        step = 0.25 * direction
        if self._box_selected is not None:
            zone = self.zone
            if not zone or not zone.boxes:
                return
            idx = self._box_selected
            if idx < 0 or idx >= len(zone.boxes):
                return
            b = zone.boxes[idx]
            val = max(0.25, float(b.get(axis, 1.0)) + step)
            b[axis] = round(val, 3)
            self.dirty = True
        else:
            if axis == "w":
                self._box_w = max(0.25, self._box_w + step)
            elif axis == "d":
                self._box_d = max(0.25, self._box_d + step)
            elif axis == "h":
                self._box_h = max(0.25, self._box_h + step)

    # ── Stack on top ──────────────────────────────────────────────

    def _box_stack_scroll(self, direction: int) -> None:
        """Shift+Scroll: move selected box up/down."""
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
        z += direction * 0.25
        b["z"] = round(z, 3)
        self.dirty = True

    # ── Paint face (reuses current_texture) ───────────────────────

    def _box_paint_face(self, face: str | None = None) -> None:
        """Apply current texture to the selected box (all faces, or
        a specific face if *face* is given)."""
        if self._box_selected is None:
            return
        zone = self.zone
        if not zone or not zone.boxes:
            return
        idx = self._box_selected
        if idx < 0 or idx >= len(zone.boxes):
            return

        self._push_undo()
        tex = zone.boxes[idx].setdefault("textures", {})
        if face:
            tex[face] = self.current_texture
        else:
            for f in ("N", "S", "E", "W", "top", "bot"):
                tex[f] = self.current_texture
        self.dirty = True
