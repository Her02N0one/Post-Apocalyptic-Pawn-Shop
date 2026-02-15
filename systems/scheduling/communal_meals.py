"""systems/scheduling/communal_meals.py — Communal mealtime activity definition.

Configures the communal meal as a ``ScheduledActivity`` — the generic
scheduling, travel, and return-to-duties logic lives in
``systems/scheduling/scheduled_activities.py``.

Twice per game-day (morning + evening), settlers gather at the communal
area (``sett_well``) to eat together.  Guards eat later — they stay on
post until the main group has finished.

Day length: 1440 game-minutes (= 24 real minutes)
Breakfast:  360  (06:00 game-time)
Dinner:    1080  (18:00 game-time)
Guard delay: 30 game-minutes after each communal meal.
"""

from __future__ import annotations
from typing import Any

from components import Hunger
from systems.scheduling.scheduled_activities import ScheduledActivity


# ── Constants (kept public for backward compat) ──────────────────────

DAY_LENGTH    = 1440.0
MEAL_TIMES    = [360.0, 1080.0]
MEAL_DURATION = 10.0
GUARD_DELAY   = 30.0
COMMUNAL_NODE = "sett_well"


# ── Meal-specific callbacks ──────────────────────────────────────────

def _is_guard(world: Any, eid: int) -> bool:
    from systems.social.faction_disposition import is_guard
    return is_guard(world, eid)


def _on_meal_arrive(world: Any, eid: int, scheduler: Any,
                    game_time: float, current_node: str) -> None:
    """Eat from personal inventory, then stockpile, then containers."""
    from systems.items.inventory_consume import npc_try_eat_any
    from systems.offscreen.handlers import schedule_hunger_event

    hunger = world.get(eid, Hunger)
    if hunger is None:
        return

    npc_try_eat_any(world, eid)
    schedule_hunger_event(world, eid, scheduler, game_time)


def _on_meal_fallback(world: Any, eid: int, scheduler: Any,
                      game_time: float, current_node: str) -> None:
    """Can't reach communal area — eat from inventory instead."""
    from systems.items.inventory_consume import consume_best_food
    from systems.offscreen.handlers import schedule_hunger_event

    consume_best_food(world, eid)
    schedule_hunger_event(world, eid, scheduler, game_time)


# ── Activity definition ──────────────────────────────────────────────

COMMUNAL_MEAL_ACTIVITY = ScheduledActivity(
    name="meal",
    event_type="COMMUNAL_MEAL",
    gathering_node=COMMUNAL_NODE,
    times=MEAL_TIMES,
    duration=MEAL_DURATION,
    day_length=DAY_LENGTH,
    group_filter="settlers",
    delay_check=_is_guard,
    delay_amount=GUARD_DELAY,
    on_arrive=_on_meal_arrive,
    on_fallback=_on_meal_fallback,
)


# ── Public API (backward-compat wrappers) ────────────────────────────

def handle_communal_meal(world: Any, eid: int, event_type: str,
                         data: dict, scheduler: Any, game_time: float,
                         graph=None) -> None:
    """Handler for COMMUNAL_MEAL events — delegates to generic system."""
    from systems.scheduling.scheduled_activities import handle_activity
    handle_activity(COMMUNAL_MEAL_ACTIVITY, world, eid, event_type,
                    data, scheduler, game_time, graph=graph)


def schedule_meal_events(world: Any, scheduler: Any,
                         game_time: float) -> int:
    """Bootstrap: schedule first round of communal meal events."""
    from systems.scheduling.scheduled_activities import schedule_activities
    return schedule_activities(COMMUNAL_MEAL_ACTIVITY, world,
                               scheduler, game_time)
