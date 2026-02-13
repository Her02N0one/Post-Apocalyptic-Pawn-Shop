"""logic/particles.py — Lightweight particle system

Usage:
    particles = ParticleManager()
    app.world.set_res(particles)

    # Spawn effects from anywhere:
    pm = app.world.res(ParticleManager)
    pm.emit_burst(x, y, count=12, color=(255, 50, 50))   # blood
    pm.emit_burst(x, y, count=6, color=(255, 255, 100))   # sparks

    # In scene update:
    pm.update(dt)

    # Drawing is handled by scenes/world_draw.draw_particles().
"""

from __future__ import annotations
import random
import math
from core.tuning import get as _tun


class Particle:
    __slots__ = ("x", "y", "vx", "vy", "life", "max_life", "color", "size", "gravity", "drag", "fade")

    def __init__(
        self,
        x: float, y: float,
        vx: float, vy: float,
        life: float,
        color: tuple[int, int, int],
        size: float = 2.0,
        gravity: float = 0.0,
        drag: float = 0.98,
        fade: bool = True,
    ):
        self.x = x
        self.y = y
        self.vx = vx
        self.vy = vy
        self.life = life
        self.max_life = life
        self.color = color
        self.size = size
        self.gravity = gravity
        self.drag = drag
        self.fade = fade


class ParticleManager:
    """Manages all active particles. Stored as a world resource."""

    def __init__(self, max_particles: int | None = None):
        if max_particles is None:
            max_particles = int(_tun("particles", "max_particles", 512))
        self._particles: list[Particle] = []
        self._max = max_particles

    @property
    def count(self) -> int:
        return len(self._particles)

    @property
    def particles(self) -> list[Particle]:
        """Public read-only access to the live particle list."""
        return self._particles

    # ── emitters ─────────────────────────────────────────────────────

    def emit(self, p: Particle):
        """Add a single particle (low-level)."""
        if len(self._particles) < self._max:
            self._particles.append(p)

    def emit_burst(
        self,
        x: float, y: float,
        count: int = 8,
        color: tuple[int, int, int] = (255, 255, 255),
        speed: float = 3.0,
        life: float = 0.5,
        size: float = 2.0,
        gravity: float = 0.0,
        drag: float = 0.96,
        spread: float = 2 * math.pi,
        angle: float = 0.0,
        fade: bool = True,
    ):
        """Emit a radial burst of particles.

        Args:
            x, y:     world-tile position (float)
            count:    number of particles
            color:    RGB tuple
            speed:    base speed in tiles/sec (randomized ±50 %)
            life:     seconds each particle lives (randomized ±30 %)
            size:     pixel radius of each dot
            gravity:  downward acceleration in tiles/sec²
            drag:     velocity multiplier per frame (0-1, lower = more drag)
            spread:   arc width in radians (2π = full circle)
            angle:    center angle of the arc (0 = right, π/2 = down)
            fade:     whether particles fade out over lifetime
        """
        half = spread / 2.0
        for _ in range(count):
            a = angle + random.uniform(-half, half)
            s = speed * random.uniform(0.5, 1.5)
            plife = life * random.uniform(0.7, 1.3)
            self.emit(Particle(
                x=x, y=y,
                vx=math.cos(a) * s,
                vy=math.sin(a) * s,
                life=plife,
                color=color,
                size=size + random.uniform(-0.5, 0.5),
                gravity=gravity,
                drag=drag,
                fade=fade,
            ))

    # ── tick / draw ──────────────────────────────────────────────────

    def update(self, dt: float):
        alive: list[Particle] = []
        for p in self._particles:
            p.life -= dt
            if p.life <= 0:
                continue
            p.vy += p.gravity * dt
            p.vx *= p.drag
            p.vy *= p.drag
            p.x += p.vx * dt
            p.y += p.vy * dt
            alive.append(p)
        self._particles = alive

    def clear(self):
        """Remove all particles immediately."""
        self._particles.clear()
