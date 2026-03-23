"""editor2/panels/raycaster_mini.py — Small 2.5D raycaster preview panel.

Sits in the minimap dock during 3D editing mode.  Automatically tracks
the editor camera, rendering the zone from the same perspective the
player would see in-game.  Non-interactive — just a live view.
"""

from __future__ import annotations

import logging
import math

import pygame

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter, QFont
from PySide6.QtWidgets import QWidget

from core.zones import Zone

log = logging.getLogger(__name__)

# Small fixed render resolution for the panel
MINI_W, MINI_H = 320, 180
MINI_FOV = math.radians(100)
EYE_HEIGHT = 0.5
PITCH_MAX = math.pi * 0.30


class RaycasterMiniView(QWidget):
    """Non-interactive live 2.5D raycaster preview that tracks the editor camera."""

    def __init__(self, zone: Zone, parent=None) -> None:
        super().__init__(parent)
        self._zone = zone
        self._renderer = None
        self._atlas = None
        self._pygame_ready = False
        self._dirty = True

        # Camera state (synced from editor)
        self.px = zone.width / 2.0
        self.py = zone.height / 2.0
        self.angle = 0.0
        self.pitch = 0.0
        self.cam_h = EYE_HEIGHT

        self.setMinimumSize(160, 90)

    # ── Public API ────────────────────────────────────────────────

    def sync_camera(self, cam) -> None:
        """Update the preview camera from the 3D editor camera.

        Called periodically by the minimap timer.  The XZ position and
        yaw come directly from the editor camera.  The height is
        computed from the floor at the camera's XZ position plus
        ``EYE_HEIGHT`` so the preview always shows a realistic
        first-person perspective — the raw editor camera Y (which can
        be 5+ units when editing from above) would push every entity
        off the bottom of the screen.
        """
        px = cam.x
        py = cam.z
        # Use floor height at the camera position + fixed eye height
        # rather than the 3D editor camera's raw Y, which is far too
        # high when editing from above.
        if self._renderer is not None:
            fh = self._renderer.floor_height_at(px, py)
            cam_h = fh + EYE_HEIGHT
        else:
            cam_h = EYE_HEIGHT
        angle = cam.yaw + math.pi * 0.5
        pitch = max(-PITCH_MAX, min(PITCH_MAX, cam.pitch))

        # Only repaint if the camera actually moved
        if (abs(px - self.px) > 0.01 or abs(py - self.py) > 0.01
                or abs(angle - self.angle) > 0.005
                or abs(pitch - self.pitch) > 0.005
                or abs(cam_h - self.cam_h) > 0.01):
            self.px = px
            self.py = py
            self.angle = angle
            self.pitch = pitch
            self.cam_h = cam_h

            self._dirty = True
            self.update()

    def update_zone(self, zone: Zone) -> None:
        """Push new zone data to the renderer."""
        self._zone = zone
        if self._renderer and self._atlas:
            self._renderer.update_zone(zone, self._atlas, 1.0, force=True)
        self._dirty = True
        self.update()

    def ensure_ready(self) -> None:
        """Lazily initialize renderer on first use."""
        if self._renderer is not None:
            return
        try:
            self._init_pygame()
            from engine.textures import TextureAtlas
            from engine.ray_renderer import RayRenderer

            self._atlas = TextureAtlas()
            self._atlas.ensure_all()
            self._renderer = RayRenderer(
                self._zone, self._atlas,
                sw=MINI_W, sh=MINI_H,
                fov=MINI_FOV,
                dn=1.0,
                pitch_max=PITCH_MAX,
            )
            self._renderer._is_interior = 1
            fh = self._renderer.floor_height_at(self.px, self.py)
            self.cam_h = fh + EYE_HEIGHT
            log.info("Raycaster mini-preview initialized (%dx%d)",
                     MINI_W, MINI_H)
        except Exception:
            log.exception("Failed to init raycaster mini-preview")
            self._renderer = None

    def _init_pygame(self) -> None:
        if not pygame.get_init():
            pygame.init()
        if not pygame.display.get_init():
            pygame.display.init()
        try:
            pygame.display.set_mode((1, 1), pygame.HIDDEN)
        except Exception:
            pass
        self._pygame_ready = True

    # ── Paint ─────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:
        painter = QPainter(self)

        if not self._renderer:
            painter.fillRect(self.rect(), Qt.GlobalColor.black)
            painter.setPen(Qt.GlobalColor.gray)
            painter.setFont(QFont("Segoe UI", 9))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             "2.5D Preview")
            painter.end()
            return

        # Only re-render when something changed
        if self._dirty:
            self._renderer.render(
                self.px, self.py, self.angle, self.cam_h, self.pitch)
            self._renderer.render_entities(self.px, self.py, self.angle)
            self._dirty = False

        # Framebuffer → QImage, stretch to fill panel
        qimg = QImage(
            bytes(self._renderer._fb),
            MINI_W, MINI_H,
            MINI_W * 3,
            QImage.Format.Format_RGB888,
        )
        painter.drawImage(self.rect(), qimg)
        painter.end()
