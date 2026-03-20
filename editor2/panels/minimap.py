"""editor2/panels/minimap.py — Top-down 2D minimap overview panel."""

from __future__ import annotations

import math

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from core.tiles import tile_def, TILE_COLORS
from core.entity_defs import get_entity_def
from core.zones import Zone


class MinimapPanel(QWidget):
    """Small top-down 2D overview of the zone.

    Shows tile types as colored cells, entity positions as dots,
    and optionally the camera position/frustum.
    """

    def __init__(self, zone: Zone, parent=None) -> None:
        super().__init__(parent)
        self._zone = zone
        self._cam_pos: tuple[float, float] | None = None
        self._cam_yaw: float = 0.0
        self._selection: set[tuple[int, int]] = set()
        self.setMinimumSize(150, 150)

    def set_zone(self, zone: Zone) -> None:
        self._zone = zone
        self.update()

    def set_camera(self, x: float, z: float, yaw: float) -> None:
        """Update camera position indicator. x=col, z=row in world space."""
        self._cam_pos = (x, z)
        self._cam_yaw = yaw
        self.update()

    def set_selection(self, cells: set[tuple[int, int]]) -> None:
        self._selection = cells
        self.update()

    def paintEvent(self, event) -> None:
        zone = self._zone
        if zone is None:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        w, h = self.width(), self.height()
        zw, zh = zone.width, zone.height

        # Calculate cell size to fit with margin
        margin = 4
        cell_w = max(1, (w - margin * 2) / zw)
        cell_h = max(1, (h - margin * 2) / zh)
        cell = min(cell_w, cell_h)

        ox = (w - zw * cell) / 2
        oy = (h - zh * cell) / 2

        # Background
        painter.fillRect(self.rect(), QColor(20, 20, 25))

        # Draw cells
        for r in range(zh):
            for c in range(zw):
                tile_id = zone.tiles[r][c]
                td = tile_def(tile_id)
                if td and td.wall:
                    color = QColor(80, 80, 100)
                else:
                    tc = TILE_COLORS.get(tile_id, (60, 100, 60))
                    # Modulate by light level
                    ll = zone.light_levels[r][c] if zone.light_levels else 1.0
                    color = QColor(
                        int(tc[0] * ll),
                        int(tc[1] * ll),
                        int(tc[2] * ll),
                    )
                x = ox + c * cell
                y = oy + r * cell
                painter.fillRect(QRectF(x, y, cell, cell), color)

        # Selection overlay
        if self._selection:
            painter.setPen(Qt.PenStyle.NoPen)
            sel_color = QColor(80, 160, 255, 100)
            for r, c in self._selection:
                if 0 <= r < zh and 0 <= c < zw:
                    x = ox + c * cell
                    y = oy + r * cell
                    painter.fillRect(QRectF(x, y, cell, cell), sel_color)

        # Grid lines (only if cells are large enough)
        if cell >= 4:
            painter.setPen(QPen(QColor(50, 50, 60), 1))
            for r in range(zh + 1):
                y = oy + r * cell
                painter.drawLine(int(ox), int(y), int(ox + zw * cell), int(y))
            for c in range(zw + 1):
                x = ox + c * cell
                painter.drawLine(int(x), int(oy), int(x), int(oy + zh * cell))

        # Draw entities
        for ent in zone.entities:
            edef = get_entity_def(ent.type)
            if edef:
                er, eg, eb = edef.color
            else:
                er, eg, eb = 200, 200, 200
            ex = ox + ent.x * cell
            ey = oy + ent.y * cell
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(er, eg, eb))
            radius = max(2, cell * 0.3)
            painter.drawEllipse(QRectF(ex - radius, ey - radius,
                                       radius * 2, radius * 2))

        # Camera position and direction
        if self._cam_pos:
            cx = ox + self._cam_pos[0] * cell
            cy = oy + self._cam_pos[1] * cell

            # Frustum triangle
            fov = 75 * math.pi / 180
            length = cell * 3
            angle = self._cam_yaw + math.pi * 0.5
            from PySide6.QtCore import QPointF
            from PySide6.QtGui import QPolygonF
            tip = QPointF(cx, cy)
            left_angle = angle - fov / 2
            right_angle = angle + fov / 2
            left = QPointF(cx + math.cos(left_angle) * length,
                           cy + math.sin(left_angle) * length)
            right = QPointF(cx + math.cos(right_angle) * length,
                            cy + math.sin(right_angle) * length)

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 100, 40))
            painter.drawPolygon(QPolygonF([tip, left, right]))

            # Camera dot
            painter.setBrush(QColor(255, 255, 0))
            painter.drawEllipse(QRectF(cx - 3, cy - 3, 6, 6))

        painter.end()
