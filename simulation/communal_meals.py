"""simulation/communal_meals.py — Communal mealtime system.

Twice per game-day (morning + evening), settlers gather at the communal
area (``sett_well``) to eat together.  Guards eat later — they stay on
post until the main group has finished.

Day length: 1440 game-minutes (= 24 real minutes)
Breakfast:  360  (06:00 game-time)
Dinner:    1080  (18:00 game-time)
Guard delay: 30 game-minutes after each communal meal.

Extracted from ``simulation/events.py`` for clarity.
"""

from __future__ import annotations
from typing import Any

from components import Hunger, Inventory, Identity, ItemRegistry, Faction
from components.simulation import SubzonePos
from simulation.subzone import SubzoneGraph


# ── Constants ────────────────────────────────────────────────────────

DAY_LENGTH    = 1440.0   # game-minutes in a full day
MEAL_TIMES    = [360.0, 1080.0]   # 06:00, 18:00
MEAL_DURATION = 10.0     # minutes spent eating at communal area
GUARD_DELAY   = 30.0     # guards eat this many minutes after civilians
COMMUNAL_NODE = "sett_well"  # gathering point for meals


# ── Main handler ─────────────────────────────────────────────────────

def handle_communal_meal(world: Any, eid: int, event_type: str,
                         data: dict, scheduler: Any, game_time: float,
                         graph: SubzoneGraph | None = None) -> None:
    """NPC responds to communal mealtime call.

    Non-guard settlers travel to the communal area and eat.
    Guards get a delayed mealtime event instead.
    After eating, a new decision cycle fires.
    """
    if not world.alive(eid):
        return

    from components.ai import AttackConfig
    from simulation.travel import plan_route, begin_travel

    szp = world.get(eid, SubzonePos)
    if szp is None:
        return

    faction = world.get(eid, Faction)
    if not faction or faction.group != "settlers":
        return

    is_guard = world.has(eid, AttackConfig)
    current_node = szp.subzone

    # --- If entity is already at the communal node, eat ---
    if current_node == COMMUNAL_NODE:
        _communal_eat(world, eid, scheduler, game_time, current_node)
        return

    # --- Navigate to communal area ---
    if graph:
        route = plan_route(graph, current_node, COMMUNAL_NODE)
        if route:
            begin_travel(world, eid, route, graph, scheduler, game_time)
            eta = graph.total_path_time(route.path, current_node)
            scheduler.post(
                time=game_time + eta + 0.1,
                eid=eid,
                event_type="COMMUNAL_MEAL",
                data={"phase": "eat"},
            )
            _log_meal(world, eid, "heading to communal meal")
            return

    # Can't reach communal area — eat from inventory instead
    from simulation.events import _try_eat, _schedule_hunger_event
    _try_eat(world, eid, game_time)
    _schedule_hunger_event(world, eid, scheduler, game_time)
    _post_decision_after_meal(scheduler, eid, current_node, game_time)


# ── Internal helpers ─────────────────────────────────────────────────

def _communal_eat(world, eid, scheduler, game_time, current_node):
    """Eat from the communal storehouse containers at this node."""
    hunger = world.get(eid, Hunger)
    if hunger is None:
        _post_decision_after_meal(scheduler, eid, current_node, game_time)
        return

    from simulation.events import (
        _try_eat, _try_eat_from_stockpile, _schedule_hunger_event,
    )

    # Try personal inventory first
    ate = _try_eat(world, eid, game_time)

    # Then communal containers
    if not ate:
        ate = _try_eat_from_stockpile(world, eid, game_time)

    if not ate:
        registry = world.res(ItemRegistry)
        _try_communal_container(world, eid, hunger, registry, game_time)

    _schedule_hunger_event(world, eid, scheduler, game_time)
    _log_meal(world, eid, "finished communal meal")

    # Schedule next mealtime for this entity
    from components.ai import AttackConfig
    is_guard = world.has(eid, AttackConfig)
    _schedule_next_meal_for(scheduler, eid, game_time, is_guard)

    # Return to duties after eating
    scheduler.post(
        game_time + MEAL_DURATION, eid,
        "DECISION_CYCLE", {"node": current_node},
    )


def _try_communal_container(world, eid, hunger, registry, game_time):
    """Eat from any container entity at the same subzone."""
    szp = world.get(eid, SubzonePos)
    if szp is None:
        return

    for ceid, cident in world.all_of(Identity):
        if cident.kind != "container":
            continue
        cszp = world.get(ceid, SubzonePos)
        if cszp is None or cszp.subzone != szp.subzone:
            continue
        cinv = world.get(ceid, Inventory)
        if cinv is None or not cinv.items:
            continue

        best_id = None
        best_food = 0.0
        for item_id, qty in cinv.items.items():
            if qty <= 0:
                continue
            if registry and registry.item_type(item_id) == "consumable":
                food = registry.get_field(item_id, "food_value", 0.0)
            else:
                food = (25.0 if any(w in item_id
                                    for w in ("stew", "ration", "beans", "meat"))
                        else 0.0)
            if food > best_food:
                best_food = food
                best_id = item_id
        if best_id:
            cinv.items[best_id] -= 1
            if cinv.items[best_id] <= 0:
                del cinv.items[best_id]
            hunger.current = min(hunger.maximum, hunger.current + best_food)
            _log_meal(world, eid, f"ate communal {best_id}")
            return


def _post_decision_after_meal(scheduler, eid, node, game_time):
    scheduler.post(game_time + MEAL_DURATION, eid,
                   "DECISION_CYCLE", {"node": node})


def _schedule_next_meal_for(scheduler, eid, game_time, is_guard):
    """Schedule the next COMMUNAL_MEAL for a single entity."""
    time_in_day = game_time % DAY_LENGTH
    next_meal = None
    for mt in MEAL_TIMES:
        if mt > time_in_day + 1.0:
            next_meal = game_time + (mt - time_in_day)
            break
    if next_meal is None:
        next_meal = game_time + (DAY_LENGTH - time_in_day) + MEAL_TIMES[0]
    scheduler.post(
        next_meal + (GUARD_DELAY if is_guard else 0.0),
        eid, "COMMUNAL_MEAL", {},
    )


def _log_meal(world, eid, msg):
    name = "?"
    ident = world.get(eid, Identity)
    if ident:
        name = ident.name
    print(f"[MEAL] {name}: {msg}")


# ── Bootstrap scheduling ────────────────────────────────────────────

def schedule_meal_events(world: Any, scheduler: Any,
                         game_time: float) -> int:
    """Schedule the first round of communal meal events.

    Called once during bootstrap.  Finds the next mealtime relative
    to the current game_time and posts COMMUNAL_MEAL for each settler.
    Returns the count of events scheduled.
    """
    from components.ai import AttackConfig

    # Find next mealtime
    time_in_day = game_time % DAY_LENGTH
    next_meal = None
    for mt in MEAL_TIMES:
        if mt > time_in_day:
            next_meal = game_time + (mt - time_in_day)
            break
    if next_meal is None:
        next_meal = game_time + (DAY_LENGTH - time_in_day) + MEAL_TIMES[0]

    count = 0
    for eid, szp in world.all_of(SubzonePos):
        faction = world.get(eid, Faction)
        if not faction or faction.group != "settlers":
            continue
        is_guard = world.has(eid, AttackConfig)
        meal_time = next_meal + (GUARD_DELAY if is_guard else 0.0)
        scheduler.post(meal_time, eid, "COMMUNAL_MEAL", {})
        count += 1

    _schedule_next_recurring_meals(world, scheduler, next_meal)

    return count


def _schedule_next_recurring_meals(world, scheduler, last_meal_time):
    """Post the next recurring mealtime after the given one."""
    from components.ai import AttackConfig

    time_in_day = last_meal_time % DAY_LENGTH
    next_offset = None
    for mt in MEAL_TIMES:
        if mt > time_in_day + 1.0:
            next_offset = mt - time_in_day
            break
    if next_offset is None:
        next_offset = (DAY_LENGTH - time_in_day) + MEAL_TIMES[0]

    next_meal = last_meal_time + next_offset

    for eid, szp in world.all_of(SubzonePos):
        faction = world.get(eid, Faction)
        if not faction or faction.group != "settlers":
            continue
        is_guard = world.has(eid, AttackConfig)
        scheduler.post(
            next_meal + (GUARD_DELAY if is_guard else 0.0),
            eid, "COMMUNAL_MEAL", {},
        )
