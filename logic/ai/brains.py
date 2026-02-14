"""logic/ai/brains.py — Brain registry and AI runner.

Public API
----------
``register_brain(name, fn)``  — add a brain to the registry
``get_brain(name)``           — look up a brain by name
``registered_names()``        — list all registered brain names
``tick_ai(world, dt)``     — tick all active high-LOD brains

Brain implementations register themselves at import time via
``register_brain``.  Import order matters: this module must be
importable before the brain modules that call ``register_brain``.
"""

from __future__ import annotations
from typing import Callable
from core.ecs import World
from components import (
    Brain, Position, Lod, GameClock, Threat, AttackConfig,
    HitFlash, CombatStats, Identity,
)
from components.dev_log import DevLog

# ── Registry ─────────────────────────────────────────────────────────

_registry: dict[str, Callable] = {}


def register_brain(name: str, fn: Callable) -> None:
    """Register *fn* as the brain tick function for *name*."""
    _registry[name] = fn


def get_brain(name: str) -> Callable | None:
    """Return the brain function for *name*, or ``None``."""
    return _registry.get(name)


def registered_names() -> list[str]:
    """Return a sorted list of all registered brain names."""
    return sorted(_registry.keys())


# ── DevLog helper (shared with combat/engagement.py) ─────────────────

def _log(world: World, eid: int, cat: str, msg: str, t: float = 0.0, **kw):
    """Write to DevLog if available."""
    log = world.res(DevLog)
    if log is None:
        return
    ident = world.get(eid, Identity)
    name = ident.name if ident else f"e{eid}"
    log.record(eid, cat, msg, name=name, t=t, **kw)


# ── Runner ───────────────────────────────────────────────────────────

def tick_ai(world: World, dt: float):
    """Execute brains for active, high-LOD entities.

    Brains receive ``game_time`` (``GameClock.time``) which advances
    at 1.0 per real second (at 1x speed).
    """
    clock = world.res(GameClock)
    game_time = clock.time if clock else 0.0

    for eid, brain in world.all_of(Brain):
        if not brain.active:
            continue
        lod = world.get(eid, Lod)
        if lod is not None and lod.level == "low":
            continue
        if lod is not None and lod.transition_until > game_time:
            continue
        if not world.has(eid, Position):
            continue

        # Ensure hostile combatants have combat config.
        if world.has(eid, CombatStats) and not world.has(eid, AttackConfig):
            from components import Faction
            faction = world.get(eid, Faction)
            if faction and faction.disposition == "hostile":
                world.add(eid, AttackConfig())
                if not world.has(eid, Threat):
                    world.add(eid, Threat())

        if world.has(eid, Threat) and world.has(eid, AttackConfig):
            from logic.ai.perception import should_engage
            from logic.combat.engagement import tick_combat_fsm
            if should_engage(world, eid) or brain.kind in (
                "guard", "hostile_melee", "hostile_ranged",
            ):
                try:
                    tick_combat_fsm(world, eid, brain, dt, game_time)
                except Exception as exc:
                    import traceback; traceback.print_exc()
                    _log(world, eid, "error",
                         f"combat brain crash: {exc}", game_time)
                continue

        fn = get_brain(brain.kind)
        if fn:
            try:
                fn(world, eid, brain, dt, game_time)
            except Exception as exc:
                import traceback; traceback.print_exc()
                _log(world, eid, "error",
                     f"brain '{brain.kind}' crash: {exc}", game_time)


# ── Side-effect imports: trigger register_brain() calls ──────────────
from logic.ai import wander as _wander                              # noqa: F401, E402
from logic.combat import engagement as _combat_engagement            # noqa: F401, E402
from logic.ai import villager as _villager                           # noqa: F401, E402
