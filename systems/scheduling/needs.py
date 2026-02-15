"""systems/scheduling/needs.py — Hunger drain, starvation, and need evaluation.

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
from core.ecs import World
from components import (
    Hunger, Health, Needs, Inventory,
    Brain, GameClock, SubzonePos,
)
from core.tuning import get as _tun


def hunger_system(world: World, dt: float) -> None:
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


def auto_eat_system(world: World) -> None:
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
        from systems.items.inventory_consume import npc_try_eat_any
        if npc_try_eat_any(world, eid):
            if brain is not None:
                brain.state["_auto_eat_at"] = game_time


