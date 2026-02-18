"""systems/lod.py — Level-of-detail position management.

Handles the transition between fine-grained ``Position`` (float, used
when an entity is in the player's active zone) and ``CoarsePos`` (int
tile, used for off-screen simulation).

Public API:

    promote(world, eid)   — CoarsePos → Position  (entity enters active zone)
    demote(world, eid)    — Position → CoarsePos   (entity leaves active zone)
    sync_zone_lod(world, active_zone)
                          — bulk promote/demote after a zone transition

    tick_timers(world, dt) — decrement all Timers, prune expired entries
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from components import Position, Velocity, CoarsePos, Timers

if TYPE_CHECKING:
    from core.ecs import World


# ── Promote / Demote ──────────────────────────────────────────────────

def promote(world: "World", eid: int) -> None:
    """Convert an entity from coarse to fine-grained position.

    Reads ``CoarsePos`` and creates / updates ``Position`` (float).
    The coarse component is **kept** — it stays in sync on demotion.
    A ``Velocity`` is added if missing.
    """
    cp = world.get(eid, CoarsePos)
    if cp is None:
        return

    pos = world.get(eid, Position)
    if pos is None:
        pos = Position(
            x=float(cp.col) + 0.5,
            y=float(cp.row) + 0.5,
            zone=cp.zone,
        )
        world.add(eid, pos)
    else:
        pos.x = float(cp.col) + 0.5
        pos.y = float(cp.row) + 0.5
        pos.zone = cp.zone

    if not world.has(eid, Velocity):
        world.add(eid, Velocity())


def demote(world: "World", eid: int) -> None:
    """Write the fine-grained Position back to CoarsePos (integer snap).

    Position is **removed** — the entity leaves the fine-resolution
    world and lives only in the coarse sim until promoted again.
    Velocity is also removed.
    """
    pos = world.get(eid, Position)
    cp = world.get(eid, CoarsePos)
    if pos is None:
        return

    if cp is None:
        cp = CoarsePos(
            row=int(pos.y),
            col=int(pos.x),
            zone=pos.zone,
        )
        world.add(eid, cp)
    else:
        cp.row = int(pos.y)
        cp.col = int(pos.x)
        cp.zone = pos.zone

    world.remove(eid, Position)
    world.remove(eid, Velocity)


def sync_zone_lod(world: "World", active_zone: str) -> None:
    """Bulk promote/demote after the player changes zone.

    - Every entity in *active_zone* that has ``CoarsePos`` gets promoted.
    - Every entity in other zones that has ``Position`` (and isn't the
      player) gets demoted.

    This keeps the invariant:
        Active-zone NPCs → fine Position + Velocity
        Off-screen NPCs  → CoarsePos only
    """
    from components import Player

    # Promote: entities in the active zone with CoarsePos
    for eid, cp in world.all_of(CoarsePos):
        if cp.zone == active_zone:
            promote(world, eid)

    # Demote: entities NOT in the active zone that still have Position
    # (skip the player — they always keep fine position)
    for eid, pos in list(world.all_of(Position)):
        if pos.zone == active_zone:
            continue
        if world.has(eid, Player):
            continue
        demote(world, eid)


# ── Timer ticking ─────────────────────────────────────────────────────

def tick_timers(world: "World", dt: float) -> None:
    """Decrement every active timer by *dt*.  Remove expired entries."""
    for eid, timers in world.all_of(Timers):
        expired: list[str] = []
        for name, remaining in timers.active.items():
            remaining -= dt
            if remaining <= 0.0:
                expired.append(name)
            else:
                timers.active[name] = remaining
        for name in expired:
            del timers.active[name]
