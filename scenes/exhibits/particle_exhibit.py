"""scenes/exhibits/particle_exhibit.py — Particle Sandbox exhibit.

Click to spawn particle bursts. RMB to cycle effect type.
"""

from __future__ import annotations
import random
import pygame
from core.app import App
from core.constants import TILE_SIZE
from logic.particles import ParticleManager
from scenes.exhibits.base import Exhibit

_MODES = ["hit", "crit", "death", "muzzle", "custom"]


class ParticleExhibit(Exhibit):
    """Tab 6 — Particle sandbox."""

    name = "Particles"

    def __init__(self):
        self._mode = 0

    def setup(self, app: App, zone: str, tiles: list[list[int]]) -> list[int]:
        self._mode = 0
        if not app.world.res(ParticleManager):
            app.world.set_res(ParticleManager())
        return []

    def on_space(self, app: App) -> str | None:
        return "reset"

    def handle_event(self, event: pygame.event.Event, app: App,
                     mouse_to_tile) -> bool:
        if event.type == pygame.MOUSEBUTTONDOWN:
            rc = mouse_to_tile()
            if rc is None:
                return False
            row, col = rc
            if event.button == 1:
                self._spawn_at(app, col + 0.5, row + 0.5)
                return True
            elif event.button == 3:
                self._mode = (self._mode + 1) % len(_MODES)
                return True
        return False

    def update(self, app: App, dt: float, tiles: list[list[int]],
               eids: list[int]):
        pm = app.world.res(ParticleManager)
        if pm:
            pm.update(dt)

    def draw(self, surface: pygame.Surface, ox: int, oy: int,
             app: App, eids: list[int]):
        pm = app.world.res(ParticleManager)
        if not pm:
            return
        for p in pm.particles:
            sx = ox + int(p.x * TILE_SIZE)
            sy = oy + int(p.y * TILE_SIZE)
            alpha = p.life / max(p.max_life, 0.01) if p.fade else 1.0
            r, g, b = p.color
            c = (int(r * alpha), int(g * alpha), int(b * alpha))
            sz = max(1, int(p.size * alpha))
            pygame.draw.circle(surface, c, (sx, sy), sz)

    def info_text(self, app: App, eids: list[int]) -> str:
        return (f"Particles: LMB=spawn  RMB=cycle type  "
                f"Current: {_MODES[self._mode]}  [Space] reset")

    def _spawn_at(self, app: App, tx: float, ty: float):
        pm = app.world.res(ParticleManager)
        if not pm:
            pm = ParticleManager()
            app.world.set_res(pm)

        from core.tuning import section as _tun_sec
        mode = _MODES[self._mode]
        if mode == "hit":
            ps = _tun_sec("particles.hit_normal")
            pm.emit_burst(tx, ty, count=ps.get("count", 6),
                          color=tuple(ps.get("color", [255, 50, 50])),
                          speed=ps.get("speed", 2.5),
                          life=ps.get("life", 0.3),
                          size=ps.get("size", 2.0))
        elif mode == "crit":
            ps = _tun_sec("particles.hit_crit")
            pm.emit_burst(tx, ty, count=ps.get("count", 12),
                          color=tuple(ps.get("color", [255, 200, 50])),
                          speed=ps.get("speed", 2.5),
                          life=ps.get("life", 0.3),
                          size=ps.get("size", 2.0))
        elif mode == "death":
            ps = _tun_sec("particles.death")
            pm.emit_burst(tx, ty, count=ps.get("count", 20),
                          color=tuple(ps.get("color", [180, 30, 30])),
                          speed=ps.get("speed", 3.5),
                          life=ps.get("life", 0.6),
                          size=ps.get("size", 2.5),
                          gravity=ps.get("gravity", 4.0))
        elif mode == "muzzle":
            ps = _tun_sec("particles.muzzle_flash")
            pm.emit_burst(tx, ty, count=ps.get("count", 3),
                          color=tuple(ps.get("color", [255, 180, 60])),
                          speed=ps.get("speed", 1.5),
                          life=ps.get("life", 0.1),
                          size=ps.get("size", 1.0))
        elif mode == "custom":
            pm.emit_burst(tx, ty, count=30,
                          color=(random.randint(50, 255),
                                 random.randint(50, 255),
                                 random.randint(50, 255)),
                          speed=random.uniform(1.5, 4.0),
                          life=random.uniform(0.3, 1.2),
                          size=random.uniform(1.5, 4.0),
                          gravity=random.uniform(0.0, 6.0))
