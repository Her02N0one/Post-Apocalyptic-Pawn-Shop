"""logic/tick.py — System tick orchestration.

Extracts the core per-frame system calls from world_scene.update()
so they can be reused by test scenes and are easier to reason about.

Usage::

    from logic.tick import tick_systems

    class WorldScene(Scene):
        def update(self, dt, app):
            ...
            tick_systems(app.world, scaled_dt, self.tiles)
            ...
"""

from __future__ import annotations
from typing import TYPE_CHECKING

from components import GameClock
from logic.systems import movement_system
from logic.brains import run_brains
from logic.lod_system import lod_system
from logic.needs_system import hunger_system, auto_eat_system, settlement_food_production
from logic.projectiles import projectile_system
from logic.particles import ParticleManager
from core.events import EventBus

if TYPE_CHECKING:
    from core.ecs import World


def tick_systems(world: "World", dt: float, tiles: list[list[int]],
                 *, skip_lod: bool = False,
                 skip_needs: bool = False,
                 skip_brains: bool = False) -> None:
    """Run all core gameplay systems for one frame.

    Parameters
    ----------
    world : World
        The ECS world.
    dt : float
        Delta-time (already scaled by time_scale if applicable).
    tiles : list[list[int]]
        Current zone tile map for movement/projectile collision.
    skip_lod : bool
        Skip the LOD promote/demote system (useful in test scenes).
    skip_needs : bool
        Skip hunger/eating systems.
    skip_brains : bool
        Skip AI brain ticks.
    """
    # Advance game clock
    clock = world.res(GameClock)
    if clock:
        clock.time += dt

    # LOD transitions
    if not skip_lod:
        lod_system(world, dt)

    # Needs / hunger
    if not skip_needs:
        hunger_system(world, dt)
        auto_eat_system(world, dt)
        settlement_food_production(world, dt)

    # AI brains
    if not skip_brains:
        run_brains(world, dt)

    # Physics
    movement_system(world, dt, tiles)
    projectile_system(world, dt, tiles)

    # Event bus drain
    bus = world.res(EventBus)
    if bus:
        bus.drain()

    # Particles
    pm = world.res(ParticleManager)
    if pm:
        pm.update(dt)
