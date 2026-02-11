"""simulation/stat_combat.py — Stat-check combat for off-screen encounters.

When two hostile entities share a subzone node, combat resolves via
stat check rather than real-time simulation.  The result must be
statistically consistent with what real-time combat would produce.
"""

from __future__ import annotations
import random
from dataclasses import dataclass
from typing import Any

from components import (
    Health, Combat, Equipment, ItemRegistry, Inventory,
    Identity, Loot,
)
from components.simulation import SubzonePos, TravelPlan, WorldMemory, Home


# ── Result dataclass ─────────────────────────────────────────────────

@dataclass
class CombatResult:
    winner_eid: int = 0
    loser_eid: int = 0
    fight_duration: float = 0.0
    winner_damage_taken: float = 0.0
    loser_fled: bool = False
    flee_eid: int = 0


# ── Configuration ────────────────────────────────────────────────────

FLEE_CHECK_INTERVAL: float = 2.0   # game-minutes between flee checks
VARIANCE_SIGMA: float = 0.15       # ±15% damage variance
MIN_DPS: float = 0.1               # floor for effective DPS


# ── Core resolution ──────────────────────────────────────────────────

def stat_check_combat(world: Any, attacker_eid: int,
                      defender_eid: int) -> CombatResult:
    """Resolve combat between two entities via stat check.

    Both are real entities with real Health, Combat, and Inventory.
    Returns a CombatResult describing the outcome.
    """
    # Gather stats
    atk_dps = _effective_dps(world, attacker_eid)
    def_dps = _effective_dps(world, defender_eid)

    atk_health = world.get(attacker_eid, Health)
    def_health = world.get(defender_eid, Health)

    if not atk_health or not def_health:
        # Can't fight without health — attacker wins by default
        return CombatResult(winner_eid=attacker_eid, loser_eid=defender_eid)

    atk_combat = world.get(attacker_eid, Combat)
    def_combat = world.get(defender_eid, Combat)

    # Account for defense
    atk_def = def_combat.defense if def_combat else 0.0
    def_def = atk_combat.defense if atk_combat else 0.0

    atk_effective = max(atk_dps - atk_def * 0.3, MIN_DPS)
    def_effective = max(def_dps - def_def * 0.3, MIN_DPS)

    # Time to kill
    ttk_defender = def_health.current / atk_effective
    ttk_attacker = atk_health.current / def_effective

    # ── Flee checks along the conceptual fight timeline ──────────────
    atk_flee = _get_flee_threshold(world, attacker_eid)
    def_flee = _get_flee_threshold(world, defender_eid)

    fight_duration = min(ttk_defender, ttk_attacker)
    fled = False
    flee_eid = 0

    t = FLEE_CHECK_INTERVAL
    while t < fight_duration:
        # Check attacker flee
        if atk_flee > 0:
            atk_hp_at_t = atk_health.current - def_effective * t
            atk_ratio = atk_hp_at_t / max(atk_health.maximum, 1.0)
            if atk_ratio <= atk_flee:
                if _flee_roll(world, attacker_eid, defender_eid):
                    # Attacker flees
                    fight_duration = t
                    fled = True
                    flee_eid = attacker_eid
                    break

        # Check defender flee
        if def_flee > 0:
            def_hp_at_t = def_health.current - atk_effective * t
            def_ratio = def_hp_at_t / max(def_health.maximum, 1.0)
            if def_ratio <= def_flee:
                if _flee_roll(world, defender_eid, attacker_eid):
                    fight_duration = t
                    fled = True
                    flee_eid = defender_eid
                    break

        t += FLEE_CHECK_INTERVAL

    # ── Apply outcomes ───────────────────────────────────────────────
    variance = random.gauss(1.0, VARIANCE_SIGMA)
    variance = max(0.5, min(1.5, variance))  # clamp

    if fled:
        # Both take proportional damage; flee_eid escapes
        atk_damage = def_effective * fight_duration * variance
        def_damage = atk_effective * fight_duration * variance
        atk_health.current = max(1.0, atk_health.current - atk_damage)
        def_health.current = max(1.0, def_health.current - def_damage)

        if flee_eid == attacker_eid:
            return CombatResult(
                winner_eid=defender_eid,
                loser_eid=attacker_eid,
                fight_duration=fight_duration,
                winner_damage_taken=atk_effective * fight_duration * variance,
                loser_fled=True,
                flee_eid=attacker_eid,
            )
        else:
            return CombatResult(
                winner_eid=attacker_eid,
                loser_eid=defender_eid,
                fight_duration=fight_duration,
                winner_damage_taken=def_effective * fight_duration * variance,
                loser_fled=True,
                flee_eid=defender_eid,
            )

    # No flee: fight to the death
    if ttk_defender < ttk_attacker:
        winner_eid, loser_eid = attacker_eid, defender_eid
        winner_damage = def_effective * fight_duration * variance
    else:
        winner_eid, loser_eid = defender_eid, attacker_eid
        winner_damage = atk_effective * fight_duration * variance

    # Apply damage
    winner_health = world.get(winner_eid, Health)
    loser_health = world.get(loser_eid, Health)
    if winner_health:
        winner_health.current = max(1.0, winner_health.current - winner_damage)
    if loser_health:
        loser_health.current = 0.0

    return CombatResult(
        winner_eid=winner_eid,
        loser_eid=loser_eid,
        fight_duration=fight_duration,
        winner_damage_taken=winner_damage,
    )


# ── Encounter wrapper (integrates with scheduler) ───────────────────

def resolve_encounter(world: Any, eid_a: int, eid_b: int,
                      node_id: str, graph: Any, scheduler: Any,
                      game_time: float) -> CombatResult:
    """Full encounter resolution: combat → death/flee → loot → post events.

    Called from checkpoint evaluation when hostiles share a node.
    """
    result = stat_check_combat(world, eid_a, eid_b)

    _log_combat(world, result)

    if result.loser_fled:
        # Loser flees — divert to nearest shelter or home
        _handle_flee(world, result.flee_eid, node_id, graph,
                     scheduler, game_time)
        # Winner continues their plan or makes a new decision
        _post_decision_event(world, result.winner_eid, node_id,
                             scheduler, game_time + result.fight_duration)
    else:
        # Loser dies
        _handle_death(world, result.loser_eid, node_id, scheduler, game_time)
        # Winner loots and continues
        _loot_corpse(world, result.winner_eid, result.loser_eid)
        _post_decision_event(world, result.winner_eid, node_id,
                             scheduler, game_time + result.fight_duration)

    # Record combat in both entities' memories
    _record_combat_memory(world, eid_a, eid_b, node_id, result, game_time)

    return result


# ── Helpers ──────────────────────────────────────────────────────────

def _effective_dps(world: Any, eid: int) -> float:
    """Compute total DPS for an entity (base + weapon)."""
    combat = world.get(eid, Combat)
    base_damage = combat.damage if combat else 1.0

    equip = world.get(eid, Equipment)
    registry = world.res(ItemRegistry)
    weapon_dmg = 0.0
    attack_speed = 1.0  # hits per game-minute

    if equip and equip.weapon and registry:
        weapon_dmg = registry.get_field(equip.weapon, "damage", 0.0)
        cooldown = registry.get_field(equip.weapon, "cooldown", 0.5)
        if cooldown > 0:
            attack_speed = 1.0 / cooldown

    return (base_damage + weapon_dmg) * attack_speed


def _get_flee_threshold(world: Any, eid: int) -> float:
    """Get entity's flee threshold from Threat component."""
    from components import Threat
    threat = world.get(eid, Threat)
    if threat:
        return threat.flee_threshold
    return 0.0


def _flee_roll(world: Any, fleer_eid: int, opponent_eid: int) -> bool:
    """Roll whether a flee attempt succeeds.

    Based on relative speed and some randomness.
    """
    from components import Patrol
    fleer_patrol = world.get(fleer_eid, Patrol)
    opp_patrol = world.get(opponent_eid, Patrol)
    fleer_speed = fleer_patrol.speed if fleer_patrol else 2.0
    opp_speed = opp_patrol.speed if opp_patrol else 2.0

    flee_chance = min(0.9, fleer_speed / max(opp_speed, 0.1) * 0.5)
    return random.random() < flee_chance


def _handle_death(world: Any, dead_eid: int, node_id: str,
                  scheduler: Any, game_time: float) -> None:
    """Create a corpse entity with the dead entity's inventory."""
    # Cancel all pending events for the dead entity
    scheduler.cancel_entity(dead_eid)

    dead_ident = world.get(dead_eid, Identity)
    dead_inv = world.get(dead_eid, Inventory)
    dead_szp = world.get(dead_eid, SubzonePos)

    # Create corpse entity at the same subzone
    corpse_eid = world.spawn()
    zone = dead_szp.zone if dead_szp else ""
    world.add(corpse_eid, Identity(
        name=f"Corpse of {dead_ident.name if dead_ident else 'unknown'}",
        kind="corpse",
    ))
    world.add(corpse_eid, SubzonePos(zone=zone, subzone=node_id))

    # Transfer inventory to corpse
    if dead_inv and dead_inv.items:
        corpse_inv = Inventory(items=dict(dead_inv.items))
        world.add(corpse_eid, corpse_inv)

    # Roll loot table if entity has one
    from components import LootTableRef
    loot_ref = world.get(dead_eid, LootTableRef)
    if loot_ref and loot_ref.table_name:
        from logic.loot_tables import LootTableManager
        loot_mgr = world.res(LootTableManager)
        if loot_mgr:
            items = loot_mgr.roll(loot_ref.table_name)
            corpse_inv = world.get(corpse_eid, Inventory)
            if corpse_inv is None:
                corpse_inv = Inventory()
                world.add(corpse_eid, corpse_inv)
            for item_id in items:
                corpse_inv.items[item_id] = corpse_inv.items.get(item_id, 0) + 1

    # Mark corpse as lootable
    world.add(corpse_eid, Loot(looted=False))

    name = dead_ident.name if dead_ident else f"entity_{dead_eid}"
    print(f"[SIM] {name} died at {node_id} — corpse created (eid={corpse_eid})")

    # Kill the original entity
    world.kill(dead_eid)


def _handle_flee(world: Any, flee_eid: int, from_node: str,
                 graph: Any, scheduler: Any,
                 game_time: float) -> None:
    """Entity flees from combat — divert to shelter or home."""
    # Cancel current travel events
    scheduler.cancel_entity(flee_eid)
    world.remove(flee_eid, TravelPlan)

    # Find flee destination
    home = world.get(flee_eid, Home)
    flee_target = None

    if home and home.subzone:
        flee_target = home.subzone
    else:
        # Find nearest shelter
        from simulation.travel import find_nearest_with
        flee_target = find_nearest_with(
            graph, from_node,
            predicate=lambda n: n.shelter,
        )

    if flee_target and flee_target != from_node:
        from simulation.travel import plan_route, begin_travel
        plan = plan_route(graph, from_node, flee_target)
        if plan:
            begin_travel(world, flee_eid, plan, graph, scheduler,
                         game_time)
            return

    # Can't find anywhere to flee — just rest here
    scheduler.post(
        time=game_time + 10.0,
        eid=flee_eid,
        event_type="REST_COMPLETE",
        data={"node": from_node, "duration": 10.0},
    )


def _loot_corpse(world: Any, winner_eid: int, loser_eid: int) -> None:
    """Winner takes items from loser's inventory (if any)."""
    winner_inv = world.get(winner_eid, Inventory)
    loser_inv = world.get(loser_eid, Inventory)
    if not winner_inv or not loser_inv:
        return

    for item_id, count in list(loser_inv.items.items()):
        winner_inv.items[item_id] = winner_inv.items.get(item_id, 0) + count

    loser_inv.items.clear()


def _post_decision_event(world: Any, eid: int, node_id: str,
                         scheduler: Any, game_time: float) -> None:
    """Schedule a decision cycle after combat or arrival."""
    scheduler.post(
        time=game_time + 0.1,  # near-immediate
        eid=eid,
        event_type="DECISION_CYCLE",
        data={"node": node_id},
    )


def _record_combat_memory(world: Any, eid_a: int, eid_b: int,
                          node_id: str, result: CombatResult,
                          game_time: float) -> None:
    """Record the fight in both entities' WorldMemory (if alive)."""
    for eid, opponent_eid in [(eid_a, eid_b), (eid_b, eid_a)]:
        if not world.alive(eid):
            continue
        wmem = world.get(eid, WorldMemory)
        if wmem is None:
            continue

        opp_ident = world.get(opponent_eid, Identity)
        wmem.observe(
            f"combat:{opponent_eid}",
            data={
                "node": node_id,
                "opponent_name": opp_ident.name if opp_ident else "unknown",
                "won": eid == result.winner_eid,
                "damage_taken": result.winner_damage_taken if eid == result.winner_eid else 0,
            },
            game_time=game_time,
            ttl=600.0,
        )

        # Also record threat at this node
        wmem.observe(
            f"threat:{node_id}",
            data={"level": 1.0, "source": f"combat with {opp_ident.name if opp_ident else 'unknown'}"},
            game_time=game_time,
            ttl=300.0,
        )


def _log_combat(world: Any, result: CombatResult) -> None:
    """Print combat result to console."""
    w_name = "?"
    l_name = "?"
    w_ident = world.get(result.winner_eid, Identity)
    l_ident = world.get(result.loser_eid, Identity)
    if w_ident:
        w_name = w_ident.name
    if l_ident:
        l_name = l_ident.name

    if result.loser_fled:
        print(f"[SIM COMBAT] {w_name} vs {l_name} — {l_name} fled "
              f"after {result.fight_duration:.1f} min")
    else:
        print(f"[SIM COMBAT] {w_name} vs {l_name} — {w_name} wins "
              f"({result.winner_damage_taken:.0f} dmg taken, "
              f"{result.fight_duration:.1f} min)")
