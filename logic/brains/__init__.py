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
from components import Brain, Position, Lod, GameClock


_registry: dict[str, Callable] = {}


def register_brain(name: str, fn: Callable):
    _registry[name] = fn


def get_brain(name: str):
    return _registry.get(name)


def run_brains(world: World, dt: float):
    """Execute brains for active, high-LOD entities.

    Passes ``game_time`` through so brains can throttle sensors and
    use timestamp-based cooldowns instead of ``-= dt`` countdowns.

    Entities whose ``Lod.transition_until > game_time`` are in the
    orienting grace period — the brain is skipped so they don't snap
    into combat the instant they pop into existence.
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
        fn = get_brain(brain.kind)
        if fn:
            try:
                fn(world, eid, brain, dt, game_time)
            except Exception:
                pass


# Import brain modules to trigger their register_brain() calls.
# These imports MUST come after the registry functions are defined.
from logic.brains import wander as _wander                       # noqa: F401, E402
from logic import combat_engagement as _combat_engagement        # noqa: F401, E402
from logic.brains import villager as _villager                   # noqa: F401, E402
