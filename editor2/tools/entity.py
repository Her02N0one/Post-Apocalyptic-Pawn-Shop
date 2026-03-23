"""editor2/tools/entity.py — Entity placement and manipulation tool.

Wall-placement helpers live in ``entity_wall.py``; 3D marker geometry
lives in ``entity_shapes.py``.  This module contains only the
``EntityTool`` class and snap presets.
"""

from __future__ import annotations

import math
from typing import Callable

from core.entity_defs import entity_palette
from core.zones import Zone
from core.zones.objects import EntityDescriptor
from editor2.camera import Camera
from editor2.core import CommandBus
from editor2.picking import CellHit, pick_cell, pick_floor_point
from editor2.tools import Overlay, OverlayMode
from editor2.tools.entity_wall import (
    _is_wall_entity_type,
    _wall_position,
    _wall_hit_for_placement,
)
from editor2.tools.entity_shapes import (
    _entity_marker,
    _placement_ghost,
)

# ── Snap presets ──────────────────────────────────────────────────

ENTITY_SNAP_PRESETS: tuple[float, ...] = (0.0, 0.25, 0.5, 1.0)
ENTITY_SNAP_LABELS: tuple[str, ...] = ("Free", "¼ Cell", "½ Cell", "Cell")
_DEFAULT_SNAP_IDX = 0  # Free by default


def _snap_coord(val: float, resolution: float) -> float:
    """Snap *val* to the nearest multiple of *resolution*.

    *resolution* ≤ 0 → no snap (free placement).
    *resolution* ≥ 1 → cell-centre snap (0.5, 1.5, …).
    """
    if resolution <= 0.0:
        return val
    if resolution >= 1.0:
        return math.floor(val) + 0.5
    return round(val / resolution) * resolution



class EntityTool:
    """Place, select, move, rotate, and delete entities.

    - LMB on empty cell: place new entity of the selected type
    - LMB on existing entity: select it
    - Shift+LMB: place regardless of existing entities
    - RMB: delete hovered entity
    - R: rotate selected entity 90° CW
    - Delete: delete selected entity
    """

    name = "entity"
    wants_right_click = False

    def __init__(self, zone: Zone, bus: CommandBus, cam: Camera) -> None:
        self._zone = zone
        self._bus = bus
        self._cam = cam
        self.on_changed: Callable[[], None] | None = None

        # Currently selected entity type for placement
        self.current_type: str = ""
        # Currently selected entity (uid)
        self.selected_uid: int | None = None
        # Hover info
        self.hover_hit = None
        self._hover_entity_uid: int | None = None
        # Continuous hover position (world coords, snapped)
        self._hover_wx: float | None = None
        self._hover_wz: float | None = None
        self._hover_fh: float = 0.0
        # Snap
        self._snap_idx: int = _DEFAULT_SNAP_IDX

    # ── Entity queries ────────────────────────────────────────────

    def _find_entity_at(self, row: int, col: int) -> EntityDescriptor | None:
        """Find the first entity whose position falls in (row, col)."""
        for ent in self._zone.entities:
            er = int(ent.y)
            ec = int(ent.x)
            if er == row and ec == col:
                return ent
        return None

    def _entity_by_uid(self, uid: int) -> EntityDescriptor | None:
        for ent in self._zone.entities:
            if ent.uid == uid:
                return ent
        return None

    # ── Tool protocol ─────────────────────────────────────────────

    # ── Snap accessors ─────────────────────────────────────────

    @property
    def snap_idx(self) -> int:
        return self._snap_idx

    @property
    def snap_resolution(self) -> float:
        return ENTITY_SNAP_PRESETS[self._snap_idx]

    def cycle_snap(self) -> None:
        """Advance to the next snap preset (wraps around)."""
        self._snap_idx = (self._snap_idx + 1) % len(ENTITY_SNAP_PRESETS)

    def cycle_type(self, direction: int = 1) -> str:
        """Cycle to the next (+1) or previous (-1) entity type in the palette.

        Returns the new entity type id.
        """
        pal = entity_palette()
        if not pal:
            return self.current_type
        try:
            idx = pal.index(self.current_type)
        except ValueError:
            idx = -1 if direction > 0 else 0
        idx = (idx + direction) % len(pal)
        self.current_type = pal[idx]
        return self.current_type

    def set_type(self, etype: str) -> None:
        """Set the current entity type directly."""
        self.current_type = etype

    # ── Tool protocol ─────────────────────────────────────────────

    def on_mouse_move(self, sx: float, sy: float,
                      vp_w: int, vp_h: int) -> None:
        hit = pick_cell(sx, sy, vp_w, vp_h, self._cam, self._zone)
        self.hover_hit = hit

        # Compute continuous floor position
        pt = pick_floor_point(sx, sy, vp_w, vp_h, self._cam, self._zone)
        if pt is not None:
            wx, wz, fh = pt
            res = self.snap_resolution
            self._hover_wx = _snap_coord(wx, res)
            self._hover_wz = _snap_coord(wz, res)
            self._hover_fh = fh
        else:
            self._hover_wx = None
            self._hover_wz = None

        if hit:
            ent = self._find_entity_at(hit.row, hit.col)
            self._hover_entity_uid = ent.uid if ent else None
        else:
            self._hover_entity_uid = None
        if self.on_changed:
            self.on_changed()

    def on_mouse_press(self, sx: float, sy: float,
                       vp_w: int, vp_h: int, button: int) -> None:
        hit = pick_cell(sx, sy, vp_w, vp_h, self._cam, self._zone)
        if hit is None:
            return

        if button == 1:  # Left click
            existing = self._find_entity_at(hit.row, hit.col)
            if existing and not self._is_shift_held():
                # Select existing entity
                self.selected_uid = existing.uid
            else:
                # Place new entity at smooth/snapped position
                self._place_entity_at_hover()

        if self.on_changed:
            self.on_changed()

    def on_mouse_release(self, sx: float, sy: float,
                         vp_w: int, vp_h: int, button: int) -> None:
        pass

    def _is_shift_held(self) -> bool:
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import Qt
        return bool(QApplication.keyboardModifiers()
                    & Qt.KeyboardModifier.ShiftModifier)

    # ── Entity operations ─────────────────────────────────────────

    def _place_entity_at_hover(self) -> None:
        """Place a new entity at the current hover position (smooth or snapped).

        If the cursor is on a wall face and the entity type is wall-mountable,
        automatically sets ``wall_face`` and ``wall_height`` in the entity's
        extra dict so the runtime renderer treats it as wall-anchored.
        """
        if not self.current_type:
            return

        zone = self._zone
        hit = self.hover_hit
        is_wall_type = _is_wall_entity_type(self.current_type)

        # Wall placement when clicking a wall face (or the top of a
        # wall cell — inferred to the nearest cardinal face).
        wall_hit = _wall_hit_for_placement(hit) if hit is not None else None
        if is_wall_type and wall_hit is not None:
            from core.entity_defs import get_entity_def
            edef = get_entity_def(self.current_type)
            ent_h = edef.scale * 0.6 if edef else 0.3
            wx, wz, wh, wface = _wall_position(wall_hit, zone,
                                                  snap=self.snap_resolution,
                                                  entity_height=ent_h)
            ent = EntityDescriptor(
                uid=zone.next_uid(),
                type=self.current_type,
                x=wx, y=wz,
                angle=0.0,
                state="default",
                extra={"wall_face": wface, "wall_height": wh},
            )
        else:
            # Normal floor placement
            if self._hover_wx is None or self._hover_wz is None:
                return
            ex = max(0.01, min(self._hover_wx, zone.width - 0.01))
            ez = max(0.01, min(self._hover_wz, zone.height - 0.01))
            ent = EntityDescriptor(
                uid=zone.next_uid(),
                type=self.current_type,
                x=ex, y=ez,
                angle=0.0,
                state="default",
            )

        from editor2.core import EntityPlaceCmd
        self._bus.execute(EntityPlaceCmd(ent))
        self.selected_uid = ent.uid

    def _delete_entity(self, uid: int) -> None:
        ent = self._entity_by_uid(uid)
        if ent is None:
            return
        from editor2.core import EntityDeleteCmd
        self._bus.execute(EntityDeleteCmd(uid, ent))
        if self.selected_uid == uid:
            self.selected_uid = None

    def rotate_selected(self, delta: float = math.pi / 2) -> None:
        """Rotate the selected entity by *delta* radians."""
        if self.selected_uid is None:
            return
        ent = self._entity_by_uid(self.selected_uid)
        if ent is None:
            return
        from editor2.core import EntityRotateCmd
        self._bus.execute(EntityRotateCmd(self.selected_uid, delta))

    def move_selected_to_hover(self) -> None:
        """Move the selected entity to the current hover position."""
        if self.selected_uid is None:
            return
        if self._hover_wx is None or self._hover_wz is None:
            return
        zone = self._zone
        ex = max(0.01, min(self._hover_wx, zone.width - 0.01))
        ez = max(0.01, min(self._hover_wz, zone.height - 0.01))
        from editor2.core import EntityMoveCmd
        self._bus.execute(EntityMoveCmd(self.selected_uid, ex, ez))

    def delete_selected(self) -> None:
        """Delete the currently selected entity."""
        if self.selected_uid is not None:
            self._delete_entity(self.selected_uid)

    # ── Overlays ──────────────────────────────────────────────────

    def overlays(self) -> list[Overlay]:
        ovls: list[Overlay] = []
        zone = self._zone

        for ent in zone.entities:
            is_selected = ent.uid == self.selected_uid
            is_hovered = ent.uid == self._hover_entity_uid
            ovls.extend(_entity_marker(
                ent, zone, is_selected, is_hovered, detailed=True,
            ))

        # ── Placement preview ghost ───────────────────────────
        wx, wz = self._hover_wx, self._hover_wz
        hit = self.hover_hit
        if hit is not None and wx is not None and wz is not None:
            fh = self._hover_fh

            # Only show ghost if we have a type selected and no entity
            # is already being hovered (avoids stacking ghost on existing)
            if self.current_type and self._hover_entity_uid is None:
                ovls.extend(_placement_ghost(
                    self.current_type, wx, wz, fh, zone, hit,
                    snap=self.snap_resolution,
                ))

            # Hover cell outline — use hit_y for wall parts so the
            # outline sits at the wall top, not inside the mesh.
            r, c = hit.row, hit.col
            y = (hit.hit_y + 0.01) if hit.part == "wall" else (fh + 0.01)
            ovls.append(Overlay(
                mode=OverlayMode.LINES,
                verts=[
                    (c, y, r), (c + 1, y, r),
                    (c + 1, y, r), (c + 1, y, r + 1),
                    (c + 1, y, r + 1), (c, y, r + 1),
                    (c, y, r + 1), (c, y, r),
                ],
                color=(1.0, 1.0, 1.0, 0.5),
            ))

        return ovls
