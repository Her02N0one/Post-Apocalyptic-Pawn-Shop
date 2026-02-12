"""logic/lod_system.py — Distance-based LOD promotion / demotion.

Every frame (or throttled), iterate non-player entities and set their
LOD level based on distance to the player camera:

    high   — within HIGH_RADIUS tiles  (brains run, full sim)
    medium — within MED_RADIUS tiles   (reserved for future use)
    low    — beyond MED_RADIUS tiles   (frozen, minimal sim)

When an entity is *promoted* from low → high it gets an "orienting"
grace period (``Lod.transition_until``) so the brain doesn't execute
on stale data for the first few frames.
"""

from __future__ import annotations
import math
from components import Position, Player, Lod, GameClock, Brain
from simulation.subzone import SubzoneGraph
from simulation.scheduler import WorldScheduler
from simulation.lod_transition import sync_lod_by_distance

# ── Tunables ─────────────────────────────────────────────────────────
HIGH_RADIUS: float = 20.0   # tiles — full brain sim radius
MED_RADIUS: float = 40.0    # tiles — medium LOD radius (reserved)
GRACE_PERIOD: float = 0.5   # seconds of orienting after promotion
LOD_INTERVAL: float = 0.25  # seconds between full LOD sweeps

_last_lod_time: float = 0.0


def lod_system(world, dt: float) -> None:
    """Evaluate entity LOD levels based on distance to player."""
    global _last_lod_time

    clock = world.res(GameClock)
    game_time = clock.time if clock else 0.0

    # Throttle: don't sweep every frame
    if game_time - _last_lod_time < LOD_INTERVAL:
        return
    _last_lod_time = game_time

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
                             p_pos, HIGH_RADIUS, MED_RADIUS)
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

        # Zone mismatch → always low
        if pos.zone != p_pos.zone:
            if lod.level != "low":
                lod.level = "low"
            continue

        dist = math.hypot(pos.x - p_pos.x, pos.y - p_pos.y)

        if dist <= HIGH_RADIUS:
            if lod.level != "high":
                # Promotion — set grace period and activate brain
                lod.level = "high"
                lod.transition_until = game_time + GRACE_PERIOD
                brain = world.get(eid, Brain)
                if brain:
                    brain.active = True
        elif dist <= MED_RADIUS:
            if lod.level != "medium":
                lod.level = "medium"
                # No grace needed for medium (brains don't run)
                brain = world.get(eid, Brain)
                if brain:
                    brain.active = False
        else:
            if lod.level != "low":
                lod.level = "low"
                brain = world.get(eid, Brain)
                if brain:
                    brain.active = False
