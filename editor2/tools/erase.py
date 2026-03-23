"""editor2/tools/erase.py — Eraser tool for quick cell resets.

LMB        — full cell reset (flat ground, open sky, clear all)
Shift+LMB  — clear textures only (keep geometry)
RMB        — reset height only (keep tile type and textures)
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from core.zones import Zone
from editor2.camera import Camera
from editor2.core import (
    CommandBus, SetCellFieldCmd, SetFaceFieldCmd, BatchCmd,
)
from editor2.mesh import SKY_HEIGHT
from editor2.picking import CellHit, Face, pick_cell
from editor2.tools import Overlay, quad_to_tris

_HIGHLIGHT = (1.0, 0.3, 0.3, 0.25)  # reddish to indicate erasing


class EraseTool:
    """Eraser — quick cell/height/texture resets."""

    name = "erase"
    wants_right_click = False

    def __init__(self, zone: Zone, bus: CommandBus, camera: Camera) -> None:
        self._zone = zone
        self._bus = bus
        self._camera = camera
        self.hover_hit: CellHit | None = None
        self.on_changed: Callable[[], None] | None = None

    @property
    def name(self) -> str:
        return "Erase"

    # ── Input events ──────────────────────────────────────────────

    def on_mouse_move(self, sx: float, sy: float,
                      vp_w: int, vp_h: int) -> None:
        self.hover_hit = pick_cell(sx, sy, vp_w, vp_h,
                                   self._camera, self._zone)

    def on_mouse_press(self, sx: float, sy: float,
                       vp_w: int, vp_h: int, button: int) -> None:
        hit = pick_cell(sx, sy, vp_w, vp_h, self._camera, self._zone)
        if hit is None:
            return

        app = QApplication.instance()
        mods = app.keyboardModifiers() if app else Qt.KeyboardModifier.NoModifier

        if button == 1:
            if mods & Qt.KeyboardModifier.ControlModifier:
                self._erase_height(hit)
            elif mods & Qt.KeyboardModifier.ShiftModifier:
                self._erase_textures(hit)
            else:
                self._erase_cell(hit)

    def on_mouse_release(self, sx: float, sy: float,
                         vp_w: int, vp_h: int, button: int) -> None:
        pass

    # ── Operations ────────────────────────────────────────────────

    def _erase_cell(self, hit: CellHit) -> None:
        """Full cell reset to defaults."""
        r, c = hit.row, hit.col
        zone = self._zone
        cmds: list = []

        if zone.tiles[r][c] != "grass":
            cmds.append(SetCellFieldCmd(r, c, "tiles", "grass"))
        if zone.floor_heights and zone.floor_heights[r][c] != 0.0:
            cmds.append(SetCellFieldCmd(r, c, "floor_heights", 0.0))
        if zone.ceil_heights and zone.ceil_heights[r][c] != SKY_HEIGHT:
            cmds.append(SetCellFieldCmd(r, c, "ceil_heights", SKY_HEIGHT))
        if zone.floor_textures and zone.floor_textures[r][c]:
            cmds.append(SetCellFieldCmd(r, c, "floor_textures", ""))
        if zone.ceil_textures and zone.ceil_textures[r][c]:
            cmds.append(SetCellFieldCmd(r, c, "ceil_textures", ""))
        if zone.wall_textures and zone.wall_textures[r][c]:
            cmds.append(SetCellFieldCmd(r, c, "wall_textures", ""))
        if zone.face_textures:
            for fi in range(4):
                if zone.face_textures[r][c][fi]:
                    cmds.append(SetFaceFieldCmd(r, c, fi, "face_textures", ""))
        if cmds:
            self._bus.execute(BatchCmd(cmds, f"Erase cell ({c},{r})"))

    def _erase_height(self, hit: CellHit) -> None:
        """Reset height only (keep textures and tile)."""
        r, c = hit.row, hit.col
        zone = self._zone
        cmds: list = []

        if hit.part == "ceiling":
            if zone.ceil_heights and zone.ceil_heights[r][c] != SKY_HEIGHT:
                cmds.append(SetCellFieldCmd(r, c, "ceil_heights", SKY_HEIGHT))
        else:
            if zone.floor_heights and zone.floor_heights[r][c] != 0.0:
                cmds.append(SetCellFieldCmd(r, c, "floor_heights", 0.0))
        if cmds:
            self._bus.execute(BatchCmd(cmds, f"Erase height ({c},{r})"))

    def _erase_textures(self, hit: CellHit) -> None:
        """Clear textures only (keep geometry)."""
        r, c = hit.row, hit.col
        zone = self._zone
        cmds: list = []

        if zone.face_textures:
            for fi in range(4):
                if zone.face_textures[r][c][fi]:
                    cmds.append(SetFaceFieldCmd(r, c, fi, "face_textures", ""))
        if zone.wall_textures and zone.wall_textures[r][c]:
            cmds.append(SetCellFieldCmd(r, c, "wall_textures", ""))
        if zone.floor_textures and zone.floor_textures[r][c]:
            cmds.append(SetCellFieldCmd(r, c, "floor_textures", ""))
        if zone.ceil_textures and zone.ceil_textures[r][c]:
            cmds.append(SetCellFieldCmd(r, c, "ceil_textures", ""))
        if cmds:
            self._bus.execute(BatchCmd(cmds, f"Erase textures ({c},{r})"))

    # ── Overlays ──────────────────────────────────────────────────

    def overlays(self) -> list[Overlay]:
        hit = self.hover_hit
        if hit is None:
            return []
        from editor2.mesh import compute_cell_boxes
        for part, yb, yt in compute_cell_boxes(self._zone, hit.row, hit.col):
            if part == hit.part:
                r, c = hit.row, hit.col
                y = yt + 0.02
                corners = [
                    (float(c), y, float(r)),
                    (float(c + 1), y, float(r)),
                    (float(c + 1), y, float(r + 1)),
                    (float(c), y, float(r + 1)),
                ]
                return [quad_to_tris(corners, _HIGHLIGHT)]
        return []
