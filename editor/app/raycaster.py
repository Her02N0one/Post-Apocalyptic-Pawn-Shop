"""editor/app/raycaster.py — RaycasterMixin: 2D raycaster preview."""

from __future__ import annotations

import math

import pygame

from editor.fly_camera import MOUSE_SENS, wasd_2d
from editor.app.constants import (
    MOVE_SPEED, SPRINT_MULT, SLOW_MULT, EYE_HEIGHT,
    MAX_STEP_UP, HEAD_CLEARANCE, CAM_LERP,
)


class RaycasterMixin:
    """Raycaster preview camera & movement for :class:`ZoneEditorApp`."""

    # Pitch limits (radians) — ~55° up/down
    _PITCH_MAX = math.pi * 0.30

    def _toggle_view_mode(self) -> None:
        if not self.editor_3d or not self.renderer:
            return
        if self.view_mode == "3d":
            self.view_mode = "2d"
            self.px = self.editor_3d.cam_x
            self.py = self.editor_3d.cam_z
            self.angle = self.editor_3d.yaw + math.pi * 0.5
            self.pitch = max(-self._PITCH_MAX,
                             min(self._PITCH_MAX, self.editor_3d.pitch))
            self.renderer.update_zone(self.zone, self.atlas, self.dn)
            self.renderer._is_interior = int(self.is_interior)
            self.player_fh = self.renderer.floor_height_at(self.px, self.py)
            self.cam_h = self.player_fh + EYE_HEIGHT
        else:
            self.view_mode = "3d"
            self.editor_3d.cam_x = self.px
            self.editor_3d.cam_y = self.cam_h
            self.editor_3d.cam_z = self.py
            self.editor_3d.yaw = self.angle - math.pi * 0.5
            self.editor_3d.pitch = self.pitch

    def _raycaster_key(self, event: pygame.event.Event) -> None:
        """Handle raycaster-specific key presses (respects keybind registry)."""
        # The 3D editor owns the keybind registry — read from it when available.
        kb = getattr(self.editor_3d, 'kb', None) if self.editor_3d else None
        if event.key == pygame.K_i:
            self.is_interior = not self.is_interior
            if self.renderer:
                self.renderer._is_interior = int(self.is_interior)
        elif event.key == pygame.K_g:
            self.noclip = not self.noclip

    def _update_raycaster(self, dt: float) -> None:
        """WASD movement + mouse look for raycaster preview.

        Uses the keybind registry for movement keys when available so
        that user rebinds carry over from the 3D editor.
        """
        if not self.renderer:
            return

        mx, my = pygame.mouse.get_rel()
        self.angle += mx * MOUSE_SENS
        self.pitch = max(-self._PITCH_MAX,
                         min(self._PITCH_MAX,
                             self.pitch - my * MOUSE_SENS))

        keys = pygame.key.get_pressed()
        speed = MOVE_SPEED
        if keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT]:
            speed *= SPRINT_MULT
        if keys[pygame.K_LCTRL] or keys[pygame.K_RCTRL]:
            speed *= SLOW_MULT

        # Resolve movement keys from the keybind registry (falls back to WASD)
        kb = getattr(self.editor_3d, 'kb', None) if self.editor_3d else None
        k_fwd  = kb.key_for("camera.forward")  if kb else pygame.K_w
        k_back = kb.key_for("camera.backward") if kb else pygame.K_s
        k_left = kb.key_for("camera.left")     if kb else pygame.K_a
        k_right= kb.key_for("camera.right")    if kb else pygame.K_d

        dx, dy = wasd_2d(
            self.angle,
            keys[k_fwd], keys[k_back],
            keys[k_left], keys[k_right],
            speed, dt,
        )

        def try_move(mdx: float, mdy: float) -> None:
            nx, ny = self.px + mdx, self.py + mdy
            if self.noclip:
                self.px, self.py = nx, ny
                self.player_fh = self.renderer.floor_height_at(
                    self.px, self.py, self.player_fh)
                return
            if self.renderer.can_step_to(nx, self.py, self.player_fh,
                                         MAX_STEP_UP, HEAD_CLEARANCE):
                self.px = nx
            if self.renderer.can_step_to(self.px, ny, self.player_fh,
                                         MAX_STEP_UP, HEAD_CLEARANCE):
                self.py = ny
            self.player_fh = self.renderer.floor_height_at(
                self.px, self.py, self.player_fh)

        if abs(dx) > 1e-9 or abs(dy) > 1e-9:
            try_move(dx, dy)

        target = self.player_fh + EYE_HEIGHT
        if abs(self.cam_h - target) < 0.001:
            self.cam_h = target
        else:
            self.cam_h += (target - self.cam_h) * min(1.0, CAM_LERP * dt)
