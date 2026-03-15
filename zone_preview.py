#!/usr/bin/env python3
"""zone_preview.py — Standalone zone preview window with hot-reload.

Spawns a first-person raycaster view of a zone.  Polls the zone file
for changes and reloads automatically on save, enabling a fast
edit → save → see loop.

Usage::

    python zone_preview.py <zone_name>

The editor's *View → Preview Window* menu item launches this script
as a subprocess.  The preview keeps running until the user closes
the window (Escape or ×).

Controls
--------
- WASD / arrow keys — move
- Mouse — look
- Shift — sprint
- Ctrl — slow walk
- N — toggle noclip
- Escape — quit
"""

from __future__ import annotations

import math
import os
import sys
import time

import pygame
from pygame.locals import DOUBLEBUF, RESIZABLE

# ── Ensure project root is on sys.path ────────────────────────────
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.zones import load_zone, Zone             # noqa: E402
from core.paths import ZONES_DIR                    # noqa: E402
from engine.textures import TextureAtlas            # noqa: E402
from engine.ray_renderer import RayRenderer         # noqa: E402
from editor.fly_camera import MOUSE_SENS, wasd_2d   # noqa: E402

# ── Preview constants ─────────────────────────────────────────────
PREVIEW_W    = 960
PREVIEW_H    = 540
RAY_W        = 640
RAY_H        = 360
FOV          = math.pi / 3
PITCH_MAX    = math.pi * 0.30
MOVE_SPEED   = 3.0
SPRINT_MULT  = 2.0
SLOW_MULT    = 0.3
EYE_HEIGHT   = 0.5
MAX_STEP_UP  = 0.5
HEAD_CLEAR   = 0.4
CAM_LERP     = 8.0
POLL_INTERVAL = 0.5  # seconds between file-change polls
FPS_CAP      = 60


def _zone_mtime(zone_name: str) -> float:
    """Return mtime of the zone file, or 0.0 if absent."""
    p = ZONES_DIR / f"{zone_name}.zone"
    try:
        return os.path.getmtime(p)
    except OSError:
        return 0.0


class PreviewApp:
    """Lightweight first-person preview with file-watch hot-reload."""

    def __init__(self, zone_name: str) -> None:
        self.zone_name = zone_name
        self.running = True

        # Pygame init (no OpenGL — just a standard blit surface)
        pygame.init()
        self.screen = pygame.display.set_mode(
            (PREVIEW_W, PREVIEW_H), DOUBLEBUF | RESIZABLE)
        pygame.display.set_caption(f"Preview — {zone_name}")
        pygame.mouse.set_visible(False)
        pygame.event.set_grab(True)
        self.clock = pygame.time.Clock()

        # Load zone + renderer
        self.atlas = TextureAtlas()
        self.atlas.ensure_all()
        self.zone: Zone = load_zone(zone_name)
        self.renderer = RayRenderer(
            self.zone, self.atlas,
            sw=RAY_W, sh=RAY_H, fov=FOV,
            dn=1.0, pitch_max=PITCH_MAX,
        )
        self.renderer._is_interior = 1

        # Camera state
        anchor_r, anchor_c = self.zone.anchor
        self.px = float(anchor_c) + 0.5
        self.py = float(anchor_r) + 0.5
        self.angle = math.pi * 1.5
        self.pitch = 0.0
        self.player_fh = self.renderer.floor_height_at(self.px, self.py)
        self.cam_h = self.player_fh + EYE_HEIGHT
        self.noclip = False

        # Hot-reload state
        self._last_mtime = _zone_mtime(zone_name)
        self._poll_timer = 0.0

    # ── Hot-reload ────────────────────────────────────────────────

    def _check_reload(self, dt: float) -> None:
        self._poll_timer += dt
        if self._poll_timer < POLL_INTERVAL:
            return
        self._poll_timer = 0.0
        mt = _zone_mtime(self.zone_name)
        if mt > self._last_mtime:
            self._last_mtime = mt
            self._reload()

    def _reload(self) -> None:
        """Reload zone from disk and rebuild renderer buffers."""
        try:
            self.zone = load_zone(self.zone_name)
        except Exception as exc:                    # noqa: BLE001
            pygame.display.set_caption(
                f"Preview — {self.zone_name}  [reload error: {exc}]")
            return
        self.renderer.update_zone(self.zone, self.atlas, 1.0, force=True)
        self.renderer._is_interior = 1
        # Re-clamp player to new floor
        self.player_fh = self.renderer.floor_height_at(self.px, self.py)
        self.cam_h = self.player_fh + EYE_HEIGHT
        pygame.display.set_caption(f"Preview — {self.zone_name}  [reloaded]")

    # ── Events ────────────────────────────────────────────────────

    def _handle_events(self) -> None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    self.running = False
                elif event.key == pygame.K_n:
                    self.noclip = not self.noclip
            elif event.type == pygame.VIDEORESIZE:
                self.screen = pygame.display.set_mode(
                    (event.w, event.h), DOUBLEBUF | RESIZABLE)

    # ── Movement ──────────────────────────────────────────────────

    def _update(self, dt: float) -> None:
        mx, my = pygame.mouse.get_rel()
        self.angle += mx * MOUSE_SENS
        self.pitch = max(-PITCH_MAX,
                         min(PITCH_MAX, self.pitch - my * MOUSE_SENS))

        keys = pygame.key.get_pressed()
        speed = MOVE_SPEED
        if keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT]:
            speed *= SPRINT_MULT
        if keys[pygame.K_LCTRL] or keys[pygame.K_RCTRL]:
            speed *= SLOW_MULT

        dx, dy = wasd_2d(
            self.angle,
            keys[pygame.K_w] or keys[pygame.K_UP],
            keys[pygame.K_s] or keys[pygame.K_DOWN],
            keys[pygame.K_a] or keys[pygame.K_LEFT],
            keys[pygame.K_d] or keys[pygame.K_RIGHT],
            speed, dt,
        )

        if abs(dx) > 1e-9 or abs(dy) > 1e-9:
            nx, ny = self.px + dx, self.py + dy
            if self.noclip:
                self.px, self.py = nx, ny
            else:
                if self.renderer.can_step_to(nx, self.py, self.player_fh,
                                             MAX_STEP_UP, HEAD_CLEAR):
                    self.px = nx
                if self.renderer.can_step_to(self.px, ny, self.player_fh,
                                             MAX_STEP_UP, HEAD_CLEAR):
                    self.py = ny
            self.player_fh = self.renderer.floor_height_at(
                self.px, self.py, self.player_fh)

        target = self.player_fh + EYE_HEIGHT
        if abs(self.cam_h - target) < 0.001:
            self.cam_h = target
        else:
            self.cam_h += (target - self.cam_h) * min(1.0, CAM_LERP * dt)

    # ── Draw ──────────────────────────────────────────────────────

    def _draw(self) -> None:
        frame = self.renderer.render(
            self.px, self.py, self.angle, self.cam_h, self.pitch)
        self.renderer.render_entities(self.px, self.py, self.angle)
        win_w, win_h = self.screen.get_size()
        scaled = pygame.transform.scale(frame, (win_w, win_h))
        self.screen.blit(scaled, (0, 0))

        # Minimal HUD: position + noclip
        if not pygame.font.get_init():
            pygame.font.init()
        font = pygame.font.SysFont("monospace", 14)
        txt = f"({self.px:.1f}, {self.py:.1f})  {'NOCLIP' if self.noclip else ''}"
        surf = font.render(txt, True, (200, 200, 200))
        self.screen.blit(surf, (8, 8))

        pygame.display.flip()

    # ── Main loop ─────────────────────────────────────────────────

    def run(self) -> None:
        while self.running:
            raw_dt = self.clock.tick(FPS_CAP) / 1000.0
            dt = min(raw_dt, 0.05)
            self._handle_events()
            self._update(dt)
            self._check_reload(dt)
            self._draw()
        pygame.quit()


# ── Entry point ───────────────────────────────────────────────────

def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python zone_preview.py <zone_name>", file=sys.stderr)
        sys.exit(1)
    name = sys.argv[1]
    if not (ZONES_DIR / f"{name}.zone").exists():
        print(f"Zone not found: {name}", file=sys.stderr)
        sys.exit(1)
    PreviewApp(name).run()


if __name__ == "__main__":
    main()
