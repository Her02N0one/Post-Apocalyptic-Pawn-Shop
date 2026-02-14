"""logic/tick.py — System tick orchestration.

Houses the core per-frame system pipeline plus tiny single-purpose
systems (input, pickup) that don't warrant their own files.

Usage::

    from logic.tick import tick_systems, input_system, item_pickup_system
"""

from __future__ import annotations
from typing import TYPE_CHECKING

from components import (
    GameClock, Player, Velocity, Facing,
    Position, Inventory, Identity,
)
from logic.movement import movement_system
from logic.ai.brains import tick_ai
from logic.lod import lod_system
from logic.needs import hunger_system, auto_eat_system, settlement_food_production
from logic.combat.projectiles import projectile_system
from logic.particles import ParticleManager
from core.events import EventBus

if TYPE_CHECKING:
    from core.ecs import World


# ── Tiny per-frame systems ───────────────────────────────────────────

def input_system(world: "World", move: tuple[float, float] | None = None) -> None:
    """Set Player velocity from movement input.

    Pass ``move=(dx, dy)`` normalised from the InputManager.
    Also updates the player's Facing direction.
    """
    if move is None:
        return
    dx, dy = move
    for eid, player, vel in world.query(Player, Velocity):
        vel.x = dx * player.speed
        vel.y = dy * player.speed
        if abs(vel.x) > 0.01 or abs(vel.y) > 0.01:
            facing = world.get(eid, Facing)
            if facing is not None:
                if abs(vel.x) >= abs(vel.y):
                    facing.direction = "right" if vel.x > 0 else "left"
                else:
                    facing.direction = "down" if vel.y > 0 else "up"


def item_pickup_system(world: "World") -> None:
    """Pick up nearby item entities and add them to the player's Inventory."""
    result = world.query_one(Player, Position, Inventory)
    if not result:
        return
    pid, _, ppos, pinv = result
    for eid, ipos, ident in world.query(Position, Identity):
        if getattr(ident, 'kind', '') != 'item':
            continue
        if not world.alive(eid):
            continue
        dx = ipos.x - ppos.x
        dy = ipos.y - ppos.y
        if dx * dx + dy * dy <= 0.36:  # 0.6²
            name = getattr(ident, 'name', f'item_{eid}') or f'item_{eid}'
            pinv.items[name] = pinv.items.get(name, 0) + 1
            print(f"[PICKUP] player picked up {name}")
            world.kill(eid)


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
        tick_ai(world, dt)

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
