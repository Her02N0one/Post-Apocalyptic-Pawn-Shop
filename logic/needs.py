"""logic/needs_system.py — Hunger drain, starvation, and need evaluation.

Runs once per frame on every entity that has a ``Hunger`` component.
Drains hunger over time, applies starvation damage when empty,
and sets the ``Needs.priority`` so brains can react.

Priority thresholds (fraction of ``hunger.maximum``):
    >= 0.5   → 'none'   (well-fed, do whatever)
    >= 0.25  → 'eat'    urgency 0.3  (getting hungry, time to eat)
    >= 0.0   → 'eat'    urgency 0.7  (very hungry)
    == 0.0   → 'eat'    urgency 1.0  (starving, taking damage)

Settlement NPCs also eat communal meals from the storehouse when
they run out of personal food — the village takes care of its own.
"""

from __future__ import annotations
from components import (
    Hunger, Health, Needs, Inventory, ItemRegistry, Identity,
    Brain, GameClock, Faction, Position, SubzonePos, RefillTimers,
)
from core.tuning import get as _tun


def hunger_system(world, dt: float) -> None:
    """Tick hunger for every entity that has it."""
    for eid, hunger in world.all_of(Hunger):
        if world.has(eid, SubzonePos):
            continue
        # ── Drain ────────────────────────────────────────────────────
        hunger.current = max(0.0, hunger.current - hunger.rate * dt)

        # ── Starvation damage ────────────────────────────────────────
        if hunger.current <= 0.0:
            health = world.get(eid, Health)
            if health:
                health.current = max(0.0, health.current - hunger.starve_dps * dt)

        # ── Evaluate needs ───────────────────────────────────────────
        needs = world.get(eid, Needs)
        if needs is None:
            continue

        ratio = hunger.current / max(hunger.maximum, 0.01)
        well_fed = _tun("needs", "well_fed_ratio", 0.5)
        hungry = _tun("needs", "hungry_ratio", 0.25)

        if ratio >= well_fed:
            # Don't override an existing higher-urgency non-eat need
            if needs.priority == "eat":
                needs.priority = "none"
                needs.urgency = 0.0
        elif ratio >= hungry:
            needs.priority = "eat"
            needs.urgency = 0.3
        elif hunger.current > 0.0:
            needs.priority = "eat"
            needs.urgency = 0.7
        else:
            needs.priority = "eat"
            needs.urgency = 1.0


# ── Auto-eat system ─────────────────────────────────────────────────
# Runs after hunger_system.  Any non-player entity with Hunger + Needs
# + Inventory whose priority is "eat" will automatically consume the
# best available food item.  This replaces the eat logic that was
# hard-coded inside the villager brain.

# Minimum seconds between auto-eat attempts per entity (prevents
# eating every frame).  With rate ~0.03, a full eat cycle is ~15 min.
_EAT_COOLDOWN_DEFAULT = 30.0


def auto_eat_system(world, dt: float) -> None:
    """Auto-eat for any NPC entity whose needs say 'eat'."""
    clock = world.res(GameClock)
    game_time = clock.time if clock else 0.0

    for eid, needs in world.all_of(Needs):
        if world.has(eid, SubzonePos):
            continue
        if needs.priority != "eat" or needs.urgency < 0.3:
            continue
        hunger = world.get(eid, Hunger)
        inv = world.get(eid, Inventory)
        if hunger is None or inv is None:
            continue
        # Skip player — player eats via UI
        from components import Player
        if world.has(eid, Player):
            continue
        # Cooldown check (stored in brain.state or a simple attr)
        brain = world.get(eid, Brain)
        if brain is not None:
            eat_cd = _tun("needs", "eat_cooldown", _EAT_COOLDOWN_DEFAULT)
            last_eat = brain.state.get("_auto_eat_at", 0.0)
            if game_time - last_eat < eat_cd:
                continue
        # Try to eat
        if npc_eat_from_inventory(world, eid):
            if brain is not None:
                brain.state["_auto_eat_at"] = game_time
        elif _npc_eat_communal(world, eid):
            if brain is not None:
                brain.state["_auto_eat_at"] = game_time


def npc_eat_from_inventory(world, eid: int) -> bool:
    """Canonical "eat best food from inventory" — used by all systems.

    Delegates to ``logic.inventory_ops.consume_best_food``.
    """
    from logic.inventory_ops import consume_best_food
    return consume_best_food(world, eid)


# ── Communal meal — settlement storehouse ────────────────────────────

def _npc_eat_communal(world, eid: int) -> bool:
    """Settlement NPC eats from the nearest communal storehouse.

    Only settlers (faction.group == 'settlers') can use this — the
    village feeds its own.  Uses ``world.query_zone()`` to find
    containers and ``inventory_ops.consume_from_container`` for the
    actual eating.
    """
    from logic.inventory_ops import consume_from_container
    from logic.faction_ops import entity_display_name

    faction = world.get(eid, Faction)
    if not faction or faction.group != "settlers":
        return False

    pos = world.get(eid, Position)
    szp = world.get(eid, SubzonePos)
    if not pos and not szp:
        return False

    hunger = world.get(eid, Hunger)
    if not hunger:
        return False

    registry = world.res(ItemRegistry)
    ent_zone = pos.zone if pos else szp.zone
    health = world.get(eid, Health)

    # Find settlement containers in the same zone (zone-indexed)
    for ceid, cpos, cident in world.query_zone(ent_zone, Position, Identity):
        if cident.kind != "container":
            continue
        cinv = world.get(ceid, Inventory)
        if not cinv or not cinv.items:
            continue

        if consume_from_container(cinv, hunger, registry,
                                   heal_health=health):
            name = entity_display_name(world, eid)
            print(f"[NEEDS] {name} ate communal food")
            return True

    return False


# ── Storehouse refill — the village produces food ────────────────────

_REFILL_ITEMS = {"stew": 3, "ration": 5}
_MAX_STOCK = {"stew": 20, "ration": 30, "canned_beans": 15, "dried_meat": 15}


def settlement_food_production(world, dt: float) -> None:
    """Slowly refill settlement storehouses — the village farms & cooks.

    Call once per frame.  Accumulates time and adds food periodically
    so the storehouse never stays empty for long.
    """
    clock = world.res(GameClock)
    game_time = clock.time if clock else 0.0

    for ceid, cident in world.all_of(Identity):
        if cident.kind != "container":
            continue

        # Only refill settlement containers
        cpos = world.get(ceid, Position)
        cszp = world.get(ceid, SubzonePos)
        cont_zone = cpos.zone if cpos else (cszp.zone if cszp else None)

        # Only containers in the settlement zone auto-refill
        if cont_zone != "settlement":
            continue

        cinv = world.get(ceid, Inventory)
        if cinv is None:
            continue

        # Use a brain-style state dict for timing (or simple attr)
        brain = world.get(ceid, Brain)
        if brain is None:
            # Containers don't have brains — use a World resource for timing
            _do_refill_check(world, ceid, cinv, game_time)


def _do_refill_check(world, ceid: int, cinv: Inventory, game_time: float) -> None:
    """Check if it's time to restock a container."""
    timer_res = world.res(RefillTimers)
    if timer_res is None:
        timer_res = RefillTimers()
        world.set_res(timer_res)

    last = timer_res.timers.get(ceid, 0.0)
    refill_ivl = _tun("needs.storehouse_refill", "refill_interval", 300.0)
    if game_time - last < refill_ivl:
        return

    timer_res.timers[ceid] = game_time

    for item_id, amount in _REFILL_ITEMS.items():
        current = cinv.items.get(item_id, 0)
        cap = _MAX_STOCK.get(item_id, 20)
        if current < cap:
            add = min(amount, cap - current)
            cinv.items[item_id] = current + add
            if add > 0:
                print(f"[VILLAGE] Storehouse restocked +{add} {item_id}")
