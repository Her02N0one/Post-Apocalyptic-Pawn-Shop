"""editor2/raycaster_preview.py — Live 2.5D raycaster preview widget.

When Tab is pressed, this widget replaces the 3D viewport as the central
widget, filling the full available space.  The internal render resolution
scales to match the widget size (capped to avoid excessive CPU usage).
"""

from __future__ import annotations

import logging
import math
import time

import pygame

from PySide6.QtCore import Qt, QTimer, QRect
from PySide6.QtGui import QImage, QPainter, QCursor, QFont
from PySide6.QtWidgets import QWidget

from core.zones import Zone

log = logging.getLogger(__name__)

# Render resolution cap (actual resolution is widget size clamped to this)
MAX_RAY_W, MAX_RAY_H = 960, 540
RAY_FOV = math.radians(100)

# Movement constants (match old editor)
MOVE_SPEED = 3.0
SPRINT_MULT = 2.0
EYE_HEIGHT = 0.5
MAX_STEP_UP = 0.5
HEAD_CLEARANCE = 0.4
CAM_LERP = 8.0
MOUSE_SENS = 0.003
PITCH_MAX = math.pi * 0.30


class RaycasterPreview(QWidget):
    """Full-viewport 2.5D raycaster preview.

    Takes over from the 3D editor viewport when toggled on via Tab.
    Supports WASD+mouse FPS navigation (click to capture, Esc to release).
    """

    def __init__(self, zone: Zone, parent=None) -> None:
        super().__init__(parent)
        self._zone = zone
        self._renderer = None
        self._atlas = None
        self._pygame_ready = False
        self._enabled = False

        # Current internal render resolution
        self._ray_w = 640
        self._ray_h = 360

        # Camera state
        anchor = zone.anchor if zone.anchor else (zone.height / 2, zone.width / 2)
        self.px = anchor[1] + 0.5
        self.py = anchor[0] + 0.5
        self.angle = 0.0
        self.pitch = 0.0
        self.player_fh = 0.0
        self.cam_h = EYE_HEIGHT

        # Input state
        self._keys: set[int] = set()
        self._mouse_captured = False
        self._last_time = time.monotonic()

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

        # Render loop timer (~60 FPS)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    # ── Public API ────────────────────────────────────────────────

    def set_enabled(self, on: bool) -> None:
        """Start or stop the render loop."""
        if on == self._enabled:
            return
        self._enabled = on
        if on:
            self._ensure_renderer()
            self._last_time = time.monotonic()
            self._timer.start(16)
        else:
            self._timer.stop()
            if self._mouse_captured:
                self._release_mouse()

    def sync_from_editor_camera(self, cam) -> None:
        """Transfer the 3D editor camera position into raycaster coords."""
        self.px = cam.x
        self.py = cam.z
        self.angle = cam.yaw + math.pi * 0.5
        self.pitch = max(-PITCH_MAX, min(PITCH_MAX, cam.pitch))
        if self._renderer:
            self.player_fh = self._renderer.floor_height_at(self.px, self.py)
            self.cam_h = self.player_fh + EYE_HEIGHT

    def sync_to_editor_camera(self, cam) -> None:
        """Transfer raycaster camera back to the 3D editor camera."""
        cam.x = self.px
        cam.z = self.py
        cam.y = self.cam_h
        cam.yaw = self.angle - math.pi * 0.5
        cam.pitch = self.pitch

    def update_zone(self, zone: Zone) -> None:
        """Push new zone data to the renderer (full buffer rebuild)."""
        self._zone = zone
        if self._renderer and self._atlas:
            self._renderer.update_zone(zone, self._atlas, 1.0, force=True)

    # ── Renderer management ───────────────────────────────────────

    def _ensure_renderer(self) -> None:
        """Lazily create the raycaster renderer."""
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
                sw=self._ray_w, sh=self._ray_h,
                fov=RAY_FOV,
                dn=1.0,
                pitch_max=PITCH_MAX,
            )
            self._renderer._is_interior = 1
            self.player_fh = self._renderer.floor_height_at(self.px, self.py)
            self.cam_h = self.player_fh + EYE_HEIGHT
            log.info("Raycaster renderer initialized (%dx%d)",
                     self._ray_w, self._ray_h)
        except Exception:
            log.exception("Failed to initialize raycaster renderer")
            self._renderer = None

    def _init_pygame(self) -> None:
        if self._pygame_ready:
            return
        if not pygame.get_init():
            pygame.init()
        if not pygame.display.get_init():
            pygame.display.init()
        try:
            pygame.display.set_mode((1, 1), pygame.HIDDEN)
        except Exception:
            pass
        self._pygame_ready = True

    def _resize_renderer(self, w: int, h: int) -> None:
        """Resize the internal render resolution to match the widget."""
        w = max(320, min(MAX_RAY_W, w))
        h = max(180, min(MAX_RAY_H, h))
        if w == self._ray_w and h == self._ray_h:
            return
        self._ray_w = w
        self._ray_h = h
        if self._renderer:
            self._renderer.resize(w, h)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._enabled and self._renderer:
            self._resize_renderer(self.width(), self.height())

    # ── Render loop ───────────────────────────────────────────────

    def _tick(self) -> None:
        if not self._renderer:
            return
        now = time.monotonic()
        dt = min(now - self._last_time, 0.05)
        self._last_time = now

        if self._mouse_captured:
            self._update_movement(dt)

        self.update()

    def _update_movement(self, dt: float) -> None:
        speed = MOVE_SPEED
        if Qt.Key.Key_Shift in self._keys:
            speed *= SPRINT_MULT

        dx, dy = 0.0, 0.0
        cos_a = math.cos(self.angle)
        sin_a = math.sin(self.angle)
        v = speed * dt

        if Qt.Key.Key_W in self._keys:
            dx += cos_a * v; dy += sin_a * v
        if Qt.Key.Key_S in self._keys:
            dx -= cos_a * v; dy -= sin_a * v
        if Qt.Key.Key_A in self._keys:
            dx += sin_a * v; dy -= cos_a * v
        if Qt.Key.Key_D in self._keys:
            dx -= sin_a * v; dy += cos_a * v

        if abs(dx) > 1e-9 or abs(dy) > 1e-9:
            nx = self.px + dx
            if self._renderer.can_step_to(nx, self.py, self.player_fh,
                                          MAX_STEP_UP, HEAD_CLEARANCE):
                self.px = nx
            ny = self.py + dy
            if self._renderer.can_step_to(self.px, ny, self.player_fh,
                                          MAX_STEP_UP, HEAD_CLEARANCE):
                self.py = ny
            self.player_fh = self._renderer.floor_height_at(
                self.px, self.py, self.player_fh)

        target = self.player_fh + EYE_HEIGHT
        if abs(self.cam_h - target) < 0.001:
            self.cam_h = target
        else:
            self.cam_h += (target - self.cam_h) * min(1.0, CAM_LERP * dt)

    # ── Paint ─────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:
        painter = QPainter(self)

        if not self._renderer:
            painter.fillRect(self.rect(), Qt.GlobalColor.black)
            painter.setPen(Qt.GlobalColor.gray)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             "Raycaster initializing...")
            painter.end()
            return

        # Render frame
        self._renderer.render(
            self.px, self.py, self.angle, self.cam_h, self.pitch)
        self._renderer.render_entities(self.px, self.py, self.angle)

        # Framebuffer → QImage, scale to fill entire widget
        qimg = QImage(
            bytes(self._renderer._fb),
            self._ray_w, self._ray_h,
            self._ray_w * 3,
            QImage.Format.Format_RGB888,
        )
        painter.drawImage(self.rect(), qimg)

        # ── HUD overlay ──
        painter.setPen(Qt.GlobalColor.white)
        painter.setFont(QFont("Consolas", 10))

        # Crosshair
        cx, cy = self.width() // 2, self.height() // 2
        painter.drawLine(cx - 10, cy, cx + 10, cy)
        painter.drawLine(cx, cy - 10, cx, cy + 10)

        # Position / angle
        painter.drawText(
            8, 20,
            f"Pos: ({self.px:.1f}, {self.py:.1f})  "
            f"Angle: {math.degrees(self.angle):.0f}\u00b0  "
            f"H: {self.cam_h:.2f}"
        )

        # Controls hint (top-right)
        hint = "Click to look \u2022 WASD move \u2022 Esc release \u2022 Tab exit"
        fm = painter.fontMetrics()
        tw = fm.horizontalAdvance(hint)
        painter.drawText(self.width() - tw - 8, 20, hint)

        painter.end()

    # ── Input ─────────────────────────────────────────────────────

    def keyPressEvent(self, ev) -> None:
        key = ev.key()
        self._keys.add(key)
        if key == Qt.Key.Key_Escape and self._mouse_captured:
            self._release_mouse()
            ev.accept()
            return
        # Let Tab propagate to parent for view toggle
        if key == Qt.Key.Key_Tab:
            ev.ignore()
            return
        ev.accept()

    def keyReleaseEvent(self, ev) -> None:
        self._keys.discard(ev.key())
        ev.accept()

    def mousePressEvent(self, ev) -> None:
        if ev.button() in (Qt.MouseButton.LeftButton,
                           Qt.MouseButton.RightButton):
            if not self._mouse_captured:
                self._capture_mouse()
        ev.accept()

    def mouseMoveEvent(self, ev) -> None:
        if not self._mouse_captured:
            return
        centre = self.rect().center()
        dx = ev.position().x() - centre.x()
        dy = ev.position().y() - centre.y()
        if abs(dx) < 0.5 and abs(dy) < 0.5:
            return
        self.angle += dx * MOUSE_SENS
        self.pitch = max(-PITCH_MAX, min(PITCH_MAX,
                                         self.pitch - dy * MOUSE_SENS))
        QCursor.setPos(self.mapToGlobal(centre))
        ev.accept()

    def focusOutEvent(self, ev) -> None:
        if self._mouse_captured:
            self._release_mouse()
        self._keys.clear()
        super().focusOutEvent(ev)

    def _capture_mouse(self) -> None:
        self._mouse_captured = True
        self.setCursor(Qt.CursorShape.BlankCursor)
        self.grabMouse()
        self.setFocus()

    def _release_mouse(self) -> None:
        self._mouse_captured = False
        self.releaseMouse()
        self.setCursor(Qt.CursorShape.ArrowCursor)
