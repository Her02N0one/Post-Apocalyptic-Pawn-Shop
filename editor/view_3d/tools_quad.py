"""editor/view_3d/tools_quad.py — Two-sided quad placement for Zone3DEditor.

Place, select, move, delete, and rotate two-sided quads (fences, decals).

Actions (when tool == "quad"):
  LMB on ground     Place a new quad at aimed position
  LMB on quad       Select it
  LMB (w/ selected) Move selected quad to aimed position
  RMB on ground     Deselect current quad
  RMB on quad       Delete it
  Shift+Scroll      Rotate selected quad (15° snap)
  Ctrl+Scroll       Adjust width/height
  Scroll            Cycle texture palette
  Delete            Delete selected quad
  Escape            Deselect
  MMB               Toggle two_sided flag on selected quad
"""

from __future__ import annotations

import math


_YAW_SNAP = math.pi / 12.0  # 15° increments
_DEFAULT_WIDTH = 1.0
_DEFAULT_HEIGHT = 1.0


class QuadMixin:
    """Two-sided quad (fence/decal) placement, selection, and manipulation."""

    _quad_width: float = _DEFAULT_WIDTH
    _quad_height: float = _DEFAULT_HEIGHT
    _quad_yaw: float = 0.0
    # Selected quad: managed by Zone3DEditor bridge property
    _quad_snap: float = 0.25  # grid snap increment (0 = disabled)

    # ── Picking ───────────────────────────────────────────────────

    def _quad_find_aimed(self) -> int | None:
        """Return index of quad under crosshair, or None."""
        result = self._quad_find_aimed_t()
        return result[0] if result is not None else None

    def _quad_find_aimed_t(self) -> tuple[int, float] | None:
        """Return (index, t) of quad under crosshair, or None.

        Uses a thin-slab AABB approximation for picking.
        *t* is the ray parameter (hit distance) for depth comparison.
        """
        zone = self.zone
        if not zone or not zone.quads:
            return None

        fx, fy, fz = self._forward()
        ox, oy, oz = self.cam_x, self.cam_y, self.cam_z
        from editor.view_3d.picking import _ray_vs_aabb

        best_t = float("inf")
        best_idx: int | None = None
        SLAB = 0.15  # half-thickness for picking

        for i, q in enumerate(zone.quads):
            qx = float(q.get("x", q.get("pos", [0, 0])[0] if isinstance(q.get("pos"), (list, tuple)) else 0))
            qz = float(q.get("z", q.get("pos", [0, 0])[1] if isinstance(q.get("pos"), (list, tuple)) else 0))
            qy = float(q.get("base_y", 0.0))
            w = float(q.get("width", 1.0))
            h = float(q.get("height", 1.0))

            result = _ray_vs_aabb(
                ox, oy, oz, fx, fy, fz,
                qx - w * 0.5 - SLAB, qy, qz - SLAB,
                qx + w * 0.5 + SLAB, qy + h, qz + SLAB,
            )
            if result is not None and result[0] < best_t:
                aimed = self.aimed
                if aimed is None or result[0] < aimed.t:
                    best_t = result[0]
                    best_idx = i

        if best_idx is not None:
            return (best_idx, best_t)
        return None

    # ── Placement ─────────────────────────────────────────────────

    def _quad_place(self) -> None:
        """Place a new quad at the aimed ground position."""
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

        # Apply grid snap
        snap = self._quad_snap
        if snap > 0:
            wx = round(wx / snap) * snap
            wz = round(wz / snap) * snap
            wx = max(0.1, min(zone.width - 0.1, wx))
            wz = max(0.1, min(zone.height - 0.1, wz))

        ri = max(0, min(zone.height - 1, int(wz)))
        ci = max(0, min(zone.width - 1, int(wx)))
        fh = zone.floor_heights[ri][ci] if zone.floor_heights else 0.0

        self._push_undo()
        q: dict = {
            "uid": zone.next_uid(),
            "x": round(wx, 3),
            "z": round(wz, 3),
            "base_y": round(fh, 3),
            "angle": round(self._quad_yaw, 4),
            "width": round(self._quad_width, 3),
            "height": round(self._quad_height, 3),
            "texture": self.current_texture,
            "collision": False,
            "two_sided": True,
        }
        zone.quads.append(q)
        self._quad_selected = None
        self.dirty = True

    # ── Selection ─────────────────────────────────────────────────

    def _quad_select(self, idx: int) -> None:
        self._quad_selected = idx

    def _quad_deselect(self) -> None:
        self._quad_selected = None

    # ── Deletion ──────────────────────────────────────────────────

    def _quad_delete(self, idx: int | None = None) -> None:
        zone = self.zone
        if not zone or not zone.quads:
            return
        if idx is None:
            idx = self._quad_selected
        if idx is None or idx < 0 or idx >= len(zone.quads):
            return
        self._push_undo()
        uid = zone.quads[idx].get("uid", 0)
        zone.quads.pop(idx)
        self._flash("Quad deleted — Ct+Z to undo", 1.5, (1.0, 0.6, 0.5, 1.0))
        if uid:
            self.selection.on_object_deleted(uid)
        self.dirty = True

    # ── Move ──────────────────────────────────────────────────────

    def _quad_move_to_aimed(self) -> None:
        hit = self.aimed
        if hit is None or self._quad_selected is None:
            return
        zone = self.zone
        if not zone or not zone.quads:
            return
        idx = self._quad_selected
        if idx < 0 or idx >= len(zone.quads):
            return

        fx, fy, fz = self._forward()
        ox, oy, oz = self.cam_x, self.cam_y, self.cam_z
        wx = ox + fx * hit.t
        wz = oz + fz * hit.t
        wx = max(0.1, min(zone.width - 0.1, wx))
        wz = max(0.1, min(zone.height - 0.1, wz))

        # Apply grid snap
        snap = self._quad_snap
        if snap > 0:
            wx = round(wx / snap) * snap
            wz = round(wz / snap) * snap
            wx = max(0.1, min(zone.width - 0.1, wx))
            wz = max(0.1, min(zone.height - 0.1, wz))

        self._push_undo()
        zone.quads[idx]["x"] = round(wx, 3)
        zone.quads[idx]["z"] = round(wz, 3)
        self.dirty = True

    # ── Rotation ──────────────────────────────────────────────────

    def _quad_rotate(self, direction: int) -> None:
        if self._quad_selected is None:
            return
        zone = self.zone
        if not zone or not zone.quads:
            return
        idx = self._quad_selected
        if idx < 0 or idx >= len(zone.quads):
            return
        q = zone.quads[idx]
        yaw = float(q.get("angle", 0.0))
        yaw = (yaw + direction * _YAW_SNAP) % (2.0 * math.pi)
        q["angle"] = round(yaw, 4)
        self.dirty = True

    # ── Resize ────────────────────────────────────────────────────

    def _quad_adjust_size(self, direction: int) -> None:
        """Ctrl+Scroll: adjust width (or height with Shift+Ctrl)."""
        step = 0.25 * direction
        if self._quad_selected is not None:
            zone = self.zone
            if not zone or not zone.quads:
                return
            idx = self._quad_selected
            if idx < 0 or idx >= len(zone.quads):
                return
            q = zone.quads[idx]
            q["width"] = round(max(0.25, float(q.get("width", 1.0)) + step), 3)
            self.dirty = True
        else:
            self._quad_width = max(0.25, self._quad_width + step)

    # ── Toggle two-sided ──────────────────────────────────────────

    def _quad_toggle_twosided(self) -> None:
        """MMB: toggle two_sided flag on selected quad."""
        if self._quad_selected is None:
            return
        zone = self.zone
        if not zone or not zone.quads:
            return
        idx = self._quad_selected
        if idx < 0 or idx >= len(zone.quads):
            return
        self._push_undo()
        q = zone.quads[idx]
        q["two_sided"] = not q.get("two_sided", True)
        self.dirty = True

    # ── Paint texture ─────────────────────────────────────────────

    def _quad_paint(self) -> None:
        """Apply current texture to selected quad."""
        if self._quad_selected is None:
            return
        zone = self.zone
        if not zone or not zone.quads:
            return
        idx = self._quad_selected
        if idx < 0 or idx >= len(zone.quads):
            return
        self._push_undo()
        zone.quads[idx]["texture"] = self.current_texture
        self.dirty = True
