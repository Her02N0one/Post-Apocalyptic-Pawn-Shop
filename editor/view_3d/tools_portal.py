"""editor/view_3d/tools_portal.py — Render-portal placement for Zone3DEditor.

Place, edit, and delete render portals (non-Euclidean geometry links).

Actions (when tool == "portal"):
  LMB          Place portal on aimed wall face (opens dest input in inspector)
  RMB          Delete portal on aimed wall face
  Scroll       Cycle through existing portals for inspection
"""

from __future__ import annotations

import math

from editor.view_3d.constants import FACE_IDX


class PortalMixin:
    """Render portal placement and inspection."""

    _portal_selected: int | None = None

    def _portal_find_at_face(self, r: int, c: int, face_name: str) -> int | None:
        """Find portal index at a specific cell face, or None."""
        zone = self.zone
        if not zone or not zone.render_portals:
            return None
        face_idx = FACE_IDX.get(face_name)
        if face_idx is None:
            return None
        for i, p in enumerate(zone.render_portals):
            pc = p.get("cell", (None, None))
            if isinstance(pc, (list, tuple)) and len(pc) >= 2:
                if int(pc[0]) == r and int(pc[1]) == c and int(p.get("face", -1)) == face_idx:
                    return i
        return None

    def _portal_place(self) -> None:
        """LMB: place a portal on the aimed wall face."""
        hit = self.aimed
        if not hit:
            return
        if hit.face not in FACE_IDX:
            return  # only cardinal faces

        zone = self.zone
        r, c = hit.row, hit.col
        face_idx = FACE_IDX[hit.face]

        # Check if portal already exists at this face
        existing = self._portal_find_at_face(r, c, hit.face)
        if existing is not None:
            self._portal_selected = existing
            return

        self._push_undo()
        portal = {
            "cell": [r, c],
            "face": face_idx,
            "dest_x": float(c) + 0.5,   # default: points to self
            "dest_y": float(r) + 0.5,
            "angle_offset": 0.0,
        }
        zone.render_portals.append(portal)
        self._portal_selected = len(zone.render_portals) - 1
        self.dirty = True

    def _portal_delete(self) -> None:
        """RMB: delete portal on aimed wall face."""
        hit = self.aimed
        if not hit:
            return
        if hit.face not in FACE_IDX:
            return

        r, c = hit.row, hit.col
        existing = self._portal_find_at_face(r, c, hit.face)
        if existing is None:
            return

        self._push_undo()
        self.zone.render_portals.pop(existing)
        if self._portal_selected is not None:
            if self._portal_selected == existing:
                self._portal_selected = None
            elif self._portal_selected > existing:
                self._portal_selected -= 1
        self.dirty = True

    def _portal_cycle(self, direction: int) -> None:
        """Scroll: cycle through portals for inspection."""
        zone = self.zone
        if not zone or not zone.render_portals:
            self._portal_selected = None
            return
        n = len(zone.render_portals)
        if self._portal_selected is None:
            self._portal_selected = 0 if direction > 0 else n - 1
        else:
            self._portal_selected = (self._portal_selected + direction) % n

    def _portal_deselect(self) -> None:
        self._portal_selected = None
