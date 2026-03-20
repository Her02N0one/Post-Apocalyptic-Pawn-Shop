"""editor2/tools/entity.py — Entity placement and manipulation tool."""

from __future__ import annotations

import math
from typing import Callable

from core.entity_defs import entity_registry, get_entity_def
from core.zones import Zone
from core.zones.objects import EntityDescriptor
from editor2.camera import Camera
from editor2.core import CommandBus
from editor2.picking import pick_cell
from editor2.tools import Overlay, OverlayMode


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

    def on_mouse_move(self, sx: float, sy: float,
                      vp_w: int, vp_h: int) -> None:
        hit = pick_cell(sx, sy, vp_w, vp_h, self._cam, self._zone)
        self.hover_hit = hit
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
                # Place new entity
                self._place_entity(hit.row, hit.col)
        elif button == 2:  # Right click
            existing = self._find_entity_at(hit.row, hit.col)
            if existing:
                self._delete_entity(existing.uid)

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

    def _place_entity(self, row: int, col: int) -> None:
        if not self.current_type:
            return
        ent = EntityDescriptor(
            uid=self._zone.next_uid(),
            type=self.current_type,
            x=col + 0.5,
            y=row + 0.5,
            angle=0.0,
            state="default",
        )
        from editor2.core import EntityPlaceCmd
        cmd = EntityPlaceCmd(ent)
        self._bus.execute(cmd)
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
        """Move the selected entity to the currently hovered cell."""
        if self.selected_uid is None or self.hover_hit is None:
            return
        r, c = self.hover_hit.row, self.hover_hit.col
        from editor2.core import EntityMoveCmd
        self._bus.execute(EntityMoveCmd(self.selected_uid, c + 0.5, r + 0.5))

    def delete_selected(self) -> None:
        """Delete the currently selected entity."""
        if self.selected_uid is not None:
            self._delete_entity(self.selected_uid)

    # ── Overlays ──────────────────────────────────────────────────

    def overlays(self) -> list[Overlay]:
        ovls: list[Overlay] = []
        zone = self._zone

        # Draw all entities as colored cell markers
        for ent in zone.entities:
            edef = get_entity_def(ent.type)
            if edef:
                r, g, b = edef.color
                cr, cg, cb = r / 255, g / 255, b / 255
            else:
                cr, cg, cb = 0.8, 0.8, 0.8

            ex, ey = ent.x, ent.y
            fh = 0.0
            row, col = int(ey), int(ex)
            if 0 <= row < zone.height and 0 <= col < zone.width:
                fh = zone.floor_heights[row][col] if zone.floor_heights else 0.0

            # Diamond marker on the floor
            y = fh + 0.02
            s = 0.3  # half-size
            is_selected = ent.uid == self.selected_uid
            is_hovered = ent.uid == self._hover_entity_uid
            alpha = 0.8 if is_selected else (0.6 if is_hovered else 0.4)

            verts = [
                (ex, y, ey - s),
                (ex + s, y, ey),
                (ex, y, ey + s),
                (ex - s, y, ey),
            ]
            # Two triangles for diamond
            tri_verts = [verts[0], verts[1], verts[2],
                         verts[0], verts[2], verts[3]]
            ovls.append(Overlay(
                mode=OverlayMode.TRIS,
                verts=tri_verts,
                color=(cr, cg, cb, alpha),
            ))

            # Facing direction line
            if is_selected or is_hovered:
                dx = math.cos(ent.angle) * 0.5
                dy = math.sin(ent.angle) * 0.5
                ovls.append(Overlay(
                    mode=OverlayMode.LINES,
                    verts=[(ex, y + 0.01, ey),
                           (ex + dx, y + 0.01, ey + dy)],
                    color=(1.0, 1.0, 0.0, 0.8),
                ))

        # Hover cell highlight
        hit = self.hover_hit
        if hit is not None:
            r, c = hit.row, hit.col
            fh = zone.floor_heights[r][c] if zone.floor_heights else 0.0
            y = fh + 0.01
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
