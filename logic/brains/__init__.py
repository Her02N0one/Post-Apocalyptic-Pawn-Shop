"""logic/brains — Brain registry and AI runner.

Public API
----------
``register_brain(name, fn)``  — add a brain to the registry
``get_brain(name)``           — look up a brain by name
``run_brains(world, dt)``     — tick all active high-LOD brains

Brain modules register themselves at import time via ``register_brain``.

Throttling
----------
Brains receive ``game_time`` (absolute ``GameClock.time``) so they can
use timestamp-based expiry and decide when to run expensive sensor
sweeps vs. cheap movement-only ticks.
"""

from __future__ import annotations
from typing import Callable
from core.ecs import World
from components import Brain, Position, Lod, GameClock, Threat, AttackConfig, HitFlash, Combat, Identity
from components.dev_log import DevLog


_registry: dict[str, Callable] = {}


def register_brain(name: str, fn: Callable):
    _registry[name] = fn


def get_brain(name: str):
    return _registry.get(name)


def run_brains(world: World, dt: float):
    """Execute brains for active, high-LOD entities.

    Brains receive ``game_time`` (``GameClock.time``) which advances
    at 1.0 per real second (at 1x speed).  Brain cooldowns, sensor
    intervals, and attack timers are all in seconds, matching this
    clock directly.
    """
    clock = world.res(GameClock)
    game_time = clock.time if clock else 0.0

    for eid, brain in world.all_of(Brain):
        if not brain.active:
            continue
        lod = world.get(eid, Lod)
        if lod is not None and lod.level != "high":
            continue
        # Grace period — entity is still "orienting"
        if lod is not None and lod.transition_until > game_time:
            continue
        if not world.has(eid, Position):
            continue

        # Ensure hostile combatants have combat config even if missing in data.
        if world.has(eid, Combat) and not world.has(eid, AttackConfig):
            from components import Faction
            faction = world.get(eid, Faction)
            if faction and faction.disposition == "hostile":
                world.add(eid, AttackConfig())
                if not world.has(eid, Threat):
                    world.add(eid, Threat())
        if world.has(eid, Threat) and world.has(eid, AttackConfig):
            from logic.brains._helpers import should_engage
            from logic.combat_engagement import run_combat_brain
            if should_engage(world, eid) or brain.kind in ("guard", "hostile_melee", "hostile_ranged"):
                try:
                    run_combat_brain(world, eid, brain, dt, game_time)
                except Exception as exc:
                    import traceback; traceback.print_exc()
                    _log(world, eid, "error", f"combat brain crash: {exc}", game_time)
                continue

        fn = get_brain(brain.kind)
        if fn:
            try:
                fn(world, eid, brain, dt, game_time)
            except Exception as exc:
                import traceback; traceback.print_exc()
                _log(world, eid, "error", f"brain '{brain.kind}' crash: {exc}", game_time)


def _log(world: World, eid: int, cat: str, msg: str, t: float = 0.0, **kw):
    """Write to DevLog if available."""
    log = world.res(DevLog)
    if log is None:
        return
    ident = world.get(eid, Identity)
    name = ident.name if ident else f"e{eid}"
    log.record(eid, cat, msg, name=name, t=t, **kw)


# Import brain modules to trigger their register_brain() calls.
# These imports MUST come after the registry functions are defined.
from logic.brains import wander as _wander                       # noqa: F401, E402
from logic import combat_engagement as _combat_engagement        # noqa: F401, E402
from logic.brains import villager as _villager                   # noqa: F401, E402
