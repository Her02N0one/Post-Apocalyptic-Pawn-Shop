"""editor/view_3d/tools_entity.py — Entity tool for Zone3DEditor.

Place, select, move, delete, and rotate entities in the 3D editor.

Actions:
  LMB on ground       Place entity of current palette type
  LMB on entity       Select it
  LMB (w/ selected)   Move selected entity to aimed position
  RMB on entity       Delete it
  RMB on ground       Deselect current entity
  Scroll              Cycle entity type palette
  Shift+Scroll        Rotate selected entity (8-dir snap)
  Delete / Backspace  Delete selected entity
  Escape              Deselect
"""

from __future__ import annotations

import math
import uuid

import pygame

from core.entity_defs import (
    entity_palette,
    get_entity_def,
    snap_angle_8dir,
)
from editor.view_3d.picking import _ray_vs_aabb


class EntityMixin:
    """Entity placement, selection, and manipulation."""

    # Current palette index
    _ent_type_idx: int = 0
    # Selected entity index (into zone.entities), or None
    _ent_selected: int | None = None

    # ── Palette helpers ───────────────────────────────────────────

    def _ent_current_type(self) -> str:
        """Return the entity type ID currently selected in the palette."""
        pal = entity_palette()
        if not pal:
            return ""
        return pal[self._ent_type_idx % len(pal)]

    def _ent_current_def(self):
        """Return the :class:`EntityDef` for the current palette type."""
        return get_entity_def(self._ent_current_type())

    def _ent_cycle_palette(self, direction: int) -> None:
        pal = entity_palette()
        if not pal:
            return
        self._ent_type_idx = (self._ent_type_idx + direction) % len(pal)

    # ── Entity aiming / picking ───────────────────────────────────

    def _ent_find_aimed(self) -> int | None:
        """Return index of entity under crosshair, or None.

        Uses ray-AABB intersection against each entity's bounding box.
        Only returns the entity if it is closer than the aimed cell.
        """
        zone = self.zone
        if not zone or not zone.entities:
            return None

        fx, fy, fz = self._forward()
        ox, oy, oz = self.cam_x, self.cam_y, self.cam_z

        best_t = float("inf")
        best_idx: int | None = None

        for i, ent in enumerate(zone.entities):
            ex, ez = self._ent_world_pos(ent)
            edef = get_entity_def(ent.get("type", ""))
            s = edef.scale if edef else 0.5
            half = max(s * 0.25, 0.15)  # half-width of bounding box

            # Floor height at entity cell
            ci = max(0, min(zone.width - 1, int(ex)))
            ri = max(0, min(zone.height - 1, int(ez)))
            fh = zone.floor_heights[ri][ci] if zone.floor_heights else 0.0

            result = _ray_vs_aabb(
                ox, oy, oz, fx, fy, fz,
                ex - half, fh, ez - half,
                ex + half, fh + s, ez + half,
            )
            if result is not None and result[0] < best_t:
                best_t = result[0]
                best_idx = i

        # Only pick entity if it's nearer than the aimed cell
        if best_idx is not None:
            aimed = self.aimed
            if aimed is None or best_t < aimed.t:
                return best_idx

        return None

    @staticmethod
    def _ent_world_pos(ent: dict) -> tuple[float, float]:
        """Return (world_x, world_z) from an entity dict.

        Handles both new format (``x``/``y`` keys) and legacy
        format (``position.x``/``position.y``).
        """
        if "x" in ent:
            return float(ent["x"]), float(ent["y"])
        pos = ent.get("position", {})
        return float(pos.get("x", 0)), float(pos.get("y", 0))

    # ── Placement ─────────────────────────────────────────────────

    def _ent_place(self) -> None:
        """Place a new entity at the aimed ground position."""
        hit = self.aimed
        if hit is None:
            return
        zone = self.zone
        if not zone:
            return
        etype = self._ent_current_type()
        if not etype:
            return

        # World position from camera + ray distance
        fx, fy, fz = self._forward()
        ox, oy, oz = self.cam_x, self.cam_y, self.cam_z
        wx = ox + fx * hit.t
        wz = oz + fz * hit.t
        wx = max(0.1, min(zone.width - 0.1, wx))
        wz = max(0.1, min(zone.height - 0.1, wz))

        self._push_undo()
        ent: dict = {
            "id": f"{etype}_{uuid.uuid4().hex[:6]}",
            "type": etype,
            "x": round(wx, 3),
            "y": round(wz, 3),
            "angle": 0.0,
            "state": "default",
            "properties": {},
        }
        zone.entities.append(ent)
        self._ent_selected = len(zone.entities) - 1
        self.dirty = True

    # ── Selection ─────────────────────────────────────────────────

    def _ent_select(self, idx: int) -> None:
        self._ent_selected = idx

    def _ent_deselect(self) -> None:
        self._ent_selected = None

    # ── Deletion ──────────────────────────────────────────────────

    def _ent_delete(self, idx: int | None = None) -> None:
        """Delete entity at *idx* (or the selected entity)."""
        zone = self.zone
        if not zone or not zone.entities:
            return
        if idx is None:
            idx = self._ent_selected
        if idx is None or idx < 0 or idx >= len(zone.entities):
            return

        self._push_undo()
        zone.entities.pop(idx)

        # Fix selection index
        if self._ent_selected is not None:
            if self._ent_selected == idx:
                self._ent_selected = None
            elif self._ent_selected > idx:
                self._ent_selected -= 1
        self.dirty = True

    # ── Move ──────────────────────────────────────────────────────

    def _ent_move_to_aimed(self) -> None:
        """Move the selected entity to where the crosshair hits."""
        hit = self.aimed
        if hit is None or self._ent_selected is None:
            return
        zone = self.zone
        if not zone or not zone.entities:
            return
        idx = self._ent_selected
        if idx < 0 or idx >= len(zone.entities):
            return

        fx, fy, fz = self._forward()
        ox, oy, oz = self.cam_x, self.cam_y, self.cam_z
        wx = ox + fx * hit.t
        wz = oz + fz * hit.t
        wx = max(0.1, min(zone.width - 0.1, wx))
        wz = max(0.1, min(zone.height - 0.1, wz))

        self._push_undo()
        zone.entities[idx]["x"] = round(wx, 3)
        zone.entities[idx]["y"] = round(wz, 3)
        self.dirty = True

    # ── Rotation ──────────────────────────────────────────────────

    def _ent_rotate(self, direction: int) -> None:
        """Rotate the selected entity by 45° increments."""
        if self._ent_selected is None:
            return
        zone = self.zone
        if not zone or not zone.entities:
            return
        idx = self._ent_selected
        if idx < 0 or idx >= len(zone.entities):
            return

        ent = zone.entities[idx]
        angle = float(ent.get("angle", 0.0))
        angle += direction * (math.pi / 4.0)
        ent["angle"] = snap_angle_8dir(angle)
        self.dirty = True

    # ── State cycling ─────────────────────────────────────────────

    def _ent_cycle_state(self, direction: int = 1) -> None:
        """Cycle the visual state of the selected entity."""
        if self._ent_selected is None:
            return
        zone = self.zone
        if not zone or not zone.entities:
            return
        idx = self._ent_selected
        if idx < 0 or idx >= len(zone.entities):
            return
        ent = zone.entities[idx]
        edef = get_entity_def(ent.get("type", ""))
        if not edef or len(edef.states) < 2:
            return
        cur = ent.get("state", "default")
        try:
            si = list(edef.states).index(cur)
        except ValueError:
            si = 0
        si = (si + direction) % len(edef.states)
        ent["state"] = edef.states[si]
        self.dirty = True
