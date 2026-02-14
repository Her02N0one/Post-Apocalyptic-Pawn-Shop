"""logic/lod_system.py — Zone-based LOD promotion / demotion.

Entities in the **same zone** as the player are always active.  Their
LOD tier decides rendering and update frequency, not whether they
simulate at all:

    high   — same zone, within screen-buffer radius
             (full rendering, brains run)
    medium — same zone, beyond screen-buffer radius
             (brains run, entities move, cheaper rendering)
    low    — **different zone** from the player
             (brains deactivated, event-driven scheduler)

Entities in the player's zone are **never** demoted to low LOD.
When an entity is *promoted* from low → high it gets an "orienting"
grace period (``Lod.transition_until``) so the brain doesn't execute
on stale data for the first few frames.
"""

from __future__ import annotations
import math
from components import Position, Player, Lod, GameClock, Brain, LodTimer
from simulation.subzone import SubzoneGraph
from simulation.scheduler import WorldScheduler
from simulation.lod_transition import sync_lod_by_distance
from core.tuning import get as _tun


def lod_system(world, dt: float) -> None:
    """Evaluate entity LOD levels based on zone + screen proximity."""
    HIGH_RADIUS  = _tun("lod", "high_radius", 20.0)
    GRACE_PERIOD = _tun("lod", "grace_period", 0.5)
    LOD_INTERVAL = _tun("lod", "lod_interval", 0.25)

    clock = world.res(GameClock)
    game_time = clock.time if clock else 0.0

    # Throttle: don't sweep every frame (stored as a World resource)
    timer = world.res(LodTimer)
    if timer is None:
        timer = LodTimer()
        world.set_res(timer)
    if game_time - timer.last_time < LOD_INTERVAL:
        return
    timer.last_time = game_time

    # Find the player position
    result = world.query_one(Player, Position)
    if not result:
        return
    _, _, p_pos = result

    # If the simulation graph exists, do real promotion/demotion.
    graph = world.res(SubzoneGraph)
    scheduler = world.res(WorldScheduler)
    if graph is not None and scheduler is not None:
        sync_lod_by_distance(world, graph, scheduler, game_time,
                             p_pos, HIGH_RADIUS)
        return

    # Sweep all entities that have a Lod component
    for eid, lod in world.all_of(Lod):
        pos = world.get(eid, Position)
        if pos is None:
            continue

        # Skip players — always high
        if world.get(eid, Player):
            if lod.level != "high":
                lod.level = "high"
            continue

        # ── Different zone → always low ──────────────────────────────
        if pos.zone != p_pos.zone:
            if lod.level != "low":
                lod.level = "low"
                brain = world.get(eid, Brain)
                if brain:
                    brain.active = False
            continue

        # ── Same zone → high or medium (never low) ──────────────────
        dist = math.hypot(pos.x - p_pos.x, pos.y - p_pos.y)

        if dist <= HIGH_RADIUS:
            if lod.level != "high":
                was_low = lod.level == "low"
                lod.level = "high"
                if was_low:
                    lod.transition_until = game_time + GRACE_PERIOD
                brain = world.get(eid, Brain)
                if brain:
                    brain.active = True
        else:
            if lod.level == "low":
                # Promoting from low → medium (came from another zone)
                lod.level = "medium"
                lod.transition_until = game_time + GRACE_PERIOD
                brain = world.get(eid, Brain)
                if brain:
                    brain.active = True
            elif lod.level != "medium":
                lod.level = "medium"
                brain = world.get(eid, Brain)
                if brain:
                    brain.active = True
