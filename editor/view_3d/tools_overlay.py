"""editor/view_3d/tools_overlay.py — Overlay wall placement for Zone3DEditor.

Place, select, move, delete free-form overlay walls that are not
bound to the tile grid (fences, diagonal walls, partial walls).

OverlayWall model (core.zones.zone):
  x1, y1, x2, y2  — line segment endpoints in tile-coordinate space
  texture          — texture name
  height_scale     — vertical scale (default 1.0)
  transparent      — magenta pixels see-through
  blocks           — blocks player movement

Actions (when tool == "overlay"):
  LMB on ground          Start placing first endpoint
  LMB again              Set second endpoint → create wall
  LMB on overlay wall    Select it
  LMB (w/ selected)      Move selected wall to aimed position
  RMB on ground          Deselect / cancel placement
  RMB on overlay wall    Delete it
  Scroll                 Cycle texture palette
  Shift+Scroll           Adjust height_scale of selected
  Delete                 Delete selected overlay wall
  Escape                 Deselect / cancel
  MMB                    Toggle transparent flag on selected
"""

from __future__ import annotations

import math

from core.zones.zone import OverlayWall


class OverlayWallMixin:
    """Overlay wall (free-form wall segment) tool mixin for Zone3DEditor."""

    # ── Tool state ────────────────────────────────────────────────
    _ow_selected: int | None = None
    _ow_placing: bool = False       # True while setting second endpoint
    _ow_start_x: float = 0.0       # first endpoint (tile coords)
    _ow_start_z: float = 0.0
    _ow_snap: float = 0.25         # grid snap (0 = disabled)
    _ow_height: float = 1.0        # default height_scale for new walls

    # ── Picking ───────────────────────────────────────────────────

    def _ow_hit_world(self) -> tuple[float, float] | None:
        """Get world (x, z) where the crosshair ray hits the ground plane."""
        hit = self.aimed
        if hit is None:
            return None
        fx, _, fz = self._forward()
        ox, oz = self.cam_x, self.cam_z
        wx = ox + fx * hit.t
        wz = oz + fz * hit.t
        zone = self.zone
        if not zone:
            return None
        wx = max(0.0, min(float(zone.width), wx))
        wz = max(0.0, min(float(zone.height), wz))
        snap = self._ow_snap
        if snap > 0:
            wx = round(wx / snap) * snap
            wz = round(wz / snap) * snap
            wx = max(0.0, min(float(zone.width), wx))
            wz = max(0.0, min(float(zone.height), wz))
        return (wx, wz)

    def _ow_find_aimed(self) -> int | None:
        """Return index of overlay wall closest to the crosshair ray, or None.

        Uses a thin-slab distance test from the camera ray to the wall segment.
        """
        zone = self.zone
        if not zone or not zone.overlay_walls:
            return None

        fx, fy, fz = self._forward()
        ox, oy, oz = self.cam_x, self.cam_y, self.cam_z

        PICK_DIST = 0.35  # max perpendicular distance for picking

        best_dist = PICK_DIST
        best_idx: int | None = None

        for i, ow in enumerate(zone.overlay_walls):
            # Midpoint of wall segment
            mx = (ow.x1 + ow.x2) * 0.5
            mz = (ow.y1 + ow.y2) * 0.5
            # Approximate: check distance from ray to midpoint (xz plane)
            # Project midpoint onto ray
            dx = mx - ox
            dz = mz - oz
            # Ray parameter
            denom = fx * fx + fz * fz
            if denom < 1e-9:
                continue
            t = (dx * fx + dz * fz) / denom
            if t < 0.5:
                continue  # behind camera
            # Closest point on ray
            px = ox + fx * t
            pz = oz + fz * t
            dist = math.sqrt((px - mx) ** 2 + (pz - mz) ** 2)
            if dist < best_dist:
                best_dist = dist
                best_idx = i

        return best_idx

    # ── Placement (two-click) ─────────────────────────────────────

    def _ow_begin_place(self) -> None:
        """Set the first endpoint of a new overlay wall."""
        pos = self._ow_hit_world()
        if pos is None:
            return
        self._ow_placing = True
        self._ow_start_x, self._ow_start_z = pos

    def _ow_finish_place(self) -> None:
        """Set the second endpoint and create the overlay wall."""
        pos = self._ow_hit_world()
        if pos is None:
            self._ow_placing = False
            return
        zone = self.zone
        if not zone:
            self._ow_placing = False
            return

        x1, z1 = self._ow_start_x, self._ow_start_z
        x2, z2 = pos
        # Don't create zero-length walls
        if abs(x2 - x1) < 0.05 and abs(z2 - z1) < 0.05:
            self._ow_placing = False
            return

        self._push_undo()
        ow = OverlayWall(
            x1=round(x1, 3),
            y1=round(z1, 3),
            x2=round(x2, 3),
            y2=round(z2, 3),
            texture=self.current_texture,
            height_scale=round(self._ow_height, 3),
            transparent=False,
            blocks=True,
        )
        zone.overlay_walls.append(ow)
        self._ow_placing = False
        self._ow_selected = len(zone.overlay_walls) - 1
        self.dirty = True

    def _ow_cancel_place(self) -> None:
        """Cancel an in-progress placement."""
        self._ow_placing = False

    # ── Selection ─────────────────────────────────────────────────

    def _ow_select(self, idx: int) -> None:
        self._ow_selected = idx

    def _ow_deselect(self) -> None:
        self._ow_selected = None
        self._ow_placing = False

    # ── Deletion ──────────────────────────────────────────────────

    def _ow_delete(self, idx: int | None = None) -> None:
        zone = self.zone
        if not zone or not zone.overlay_walls:
            return
        if idx is None:
            idx = self._ow_selected
        if idx is None or idx < 0 or idx >= len(zone.overlay_walls):
            return
        self._push_undo()
        zone.overlay_walls.pop(idx)
        self._flash("Overlay wall deleted — Ct+Z to undo",
                     1.5, (1.0, 0.6, 0.5, 1.0))
        if self._ow_selected is not None:
            if self._ow_selected == idx:
                self._ow_selected = None
            elif self._ow_selected > idx:
                self._ow_selected -= 1
        self.dirty = True

    # ── Move ──────────────────────────────────────────────────────

    def _ow_move_to_aimed(self) -> None:
        """Move the selected overlay wall so its midpoint is at the aimed position."""
        pos = self._ow_hit_world()
        if pos is None or self._ow_selected is None:
            return
        zone = self.zone
        if not zone or not zone.overlay_walls:
            return
        idx = self._ow_selected
        if idx < 0 or idx >= len(zone.overlay_walls):
            return

        ow = zone.overlay_walls[idx]
        # Current midpoint
        mx = (ow.x1 + ow.x2) * 0.5
        mz = (ow.y1 + ow.y2) * 0.5
        # Delta
        dx = pos[0] - mx
        dz = pos[1] - mz

        self._push_undo()
        ow.x1 = round(ow.x1 + dx, 3)
        ow.y1 = round(ow.y1 + dz, 3)
        ow.x2 = round(ow.x2 + dx, 3)
        ow.y2 = round(ow.y2 + dz, 3)
        self.dirty = True

    # ── Height adjust ─────────────────────────────────────────────

    def _ow_adjust_height(self, direction: int) -> None:
        """Shift+Scroll: adjust height_scale of selected or default."""
        step = 0.125 * direction
        if self._ow_selected is not None:
            zone = self.zone
            if not zone or not zone.overlay_walls:
                return
            idx = self._ow_selected
            if idx < 0 or idx >= len(zone.overlay_walls):
                return
            ow = zone.overlay_walls[idx]
            ow.height_scale = round(max(0.125, ow.height_scale + step), 3)
            self.dirty = True
        else:
            self._ow_height = max(0.125, self._ow_height + step)

    # ── Toggle transparent ────────────────────────────────────────

    def _ow_toggle_transparent(self) -> None:
        """MMB: toggle transparent flag on selected overlay wall."""
        if self._ow_selected is None:
            return
        zone = self.zone
        if not zone or not zone.overlay_walls:
            return
        idx = self._ow_selected
        if idx < 0 or idx >= len(zone.overlay_walls):
            return
        self._push_undo()
        ow = zone.overlay_walls[idx]
        ow.transparent = not ow.transparent
        self.dirty = True

    # ── Paint texture ─────────────────────────────────────────────

    def _ow_paint(self) -> None:
        """Apply current texture to selected overlay wall."""
        if self._ow_selected is None:
            return
        zone = self.zone
        if not zone or not zone.overlay_walls:
            return
        idx = self._ow_selected
        if idx < 0 or idx >= len(zone.overlay_walls):
            return
        self._push_undo()
        zone.overlay_walls[idx].texture = self.current_texture
        self.dirty = True
