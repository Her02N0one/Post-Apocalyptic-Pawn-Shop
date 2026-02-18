"""systems/combat_sim.py — Off-screen coarse combat.

When beasts and NPCs (or beasts and the player) are in the same
off-screen zone, close enough, and have line-of-sight, combat happens
automatically at the coarse-tick rate.

This module plugs into ``ZoneSim._sight_checks`` — when two entities
with ``CombatStats`` see each other, the hostile one attacks.

Public API:

    resolve_coarse_combat(world, event_log, eid_a, cp_a, eid_b, cp_b, tiles)
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from components import (
    CoarsePos, Health, Identity, CombatStats, Timers,
    WorldEventLog, GameClock,
)
from core.types import EntityKind

if TYPE_CHECKING:
    from core.ecs import World


def resolve_coarse_combat(
    world: "World",
    eid_a: int, cp_a: CoarsePos,
    eid_b: int, cp_b: CoarsePos,
    tiles: list[list[int]],
) -> None:
    """Resolve one round of combat between two visible entities.

    Only fires if at least one entity is hostile.  Non-hostile entities
    fight back when attacked.
    """
    stats_a = world.get(eid_a, CombatStats)
    stats_b = world.get(eid_b, CombatStats)

    if stats_a is None and stats_b is None:
        return  # neither can fight

    # Determine attacker(s)
    a_hostile = stats_a.hostile if stats_a else False
    b_hostile = stats_b.hostile if stats_b else False

    if not a_hostile and not b_hostile:
        return  # no aggression

    dist = abs(cp_a.row - cp_b.row) + abs(cp_a.col - cp_b.col)

    event_log = world.resources.try_get(WorldEventLog)

    # A attacks B
    if a_hostile and stats_a:
        if dist <= stats_a.attack_range:
            _apply_attack(world, eid_a, eid_b, stats_a, event_log, cp_a.zone)

    # B attacks A (retaliation or hostile)
    if stats_b and (b_hostile or a_hostile):
        rng = stats_b.attack_range if stats_b else 1
        if dist <= rng:
            _apply_attack(world, eid_b, eid_a, stats_b, event_log, cp_b.zone)


def _apply_attack(
    world: "World",
    attacker: int, defender: int,
    stats: CombatStats,
    event_log: "WorldEventLog | None",
    zone: str,
) -> None:
    """Apply one hit from attacker to defender."""
    # Check attack cooldown
    timers = world.get(attacker, Timers)
    if timers and "attack_cd" in timers.active:
        return

    hp = world.get(defender, Health)
    if hp is None or hp.current <= 0:
        return  # already dead

    # Damage with small variance
    dmg = stats.damage * random.uniform(0.8, 1.2)
    hp.current = max(0.0, hp.current - dmg)

    # Set attack cooldown
    if timers is None:
        timers = Timers(active={})
        world.add(attacker, timers)
    timers.active["attack_cd"] = stats.attack_cooldown

    # Log the event
    if event_log:
        gc = world.resources.try_get(GameClock)
        t = gc.time if gc else 0.0
        a_name = _entity_name(world, attacker)
        d_name = _entity_name(world, defender)
        if hp.current <= 0:
            event_log.add(
                f"{a_name} killed {d_name}!",
                zone=zone, category="combat", time=t,
            )
        else:
            event_log.add(
                f"{a_name} attacked {d_name} ({int(hp.current)} HP left)",
                zone=zone, category="combat", time=t,
            )


def _entity_name(world: "World", eid: int) -> str:
    ident = world.get(eid, Identity)
    return ident.name if ident else f"Entity#{eid}"
