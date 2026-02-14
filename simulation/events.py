"""simulation/events.py — Event resolution handlers for the WorldScheduler.

Each handler is a function with signature:
    handler(world, eid, event_type, data, scheduler, game_time)

Registered on the scheduler during initialization.
"""

from __future__ import annotations
from typing import Any

from components import Health, Hunger, Inventory, Identity, ItemRegistry, Faction
from components.simulation import SubzonePos, TravelPlan, WorldMemory, Home
from simulation.subzone import SubzoneGraph


def register_all_handlers(scheduler: Any, graph: SubzoneGraph) -> None:
    """Register all event handlers on the scheduler.

    ``graph`` is captured in the handler closures.
    """
    scheduler.register_handler("ARRIVE_NODE",
                               lambda *a: handle_arrive_node(*a, graph=graph))
    scheduler.register_handler("HUNGER_CRITICAL", handle_hunger_critical)
    scheduler.register_handler("FINISH_SEARCH", handle_finish_search)
    scheduler.register_handler("FINISH_WORK", handle_finish_work)
    scheduler.register_handler("FINISH_EAT", handle_finish_eat)
    scheduler.register_handler("REST_COMPLETE", handle_rest_complete)
    scheduler.register_handler("DECISION_CYCLE",
                               lambda *a: handle_decision_cycle(*a, graph=graph))
    scheduler.register_handler("COMBAT_RESOLVED", handle_combat_resolved)
    scheduler.register_handler("COMMUNAL_MEAL",
                               lambda *a: handle_communal_meal(*a, graph=graph))


# ═════════════════════════════════════════════════════════════════════
#  EVENT HANDLERS
# ═════════════════════════════════════════════════════════════════════


def handle_arrive_node(world: Any, eid: int, event_type: str,
                       data: dict, scheduler: Any, game_time: float,
                       graph: SubzoneGraph | None = None) -> None:
    """Entity arrived at a subzone node on their travel path.

    1. Update SubzonePos
    2. Run checkpoint evaluation
    3. Continue travel or run decision cycle
    """
    node_id = data.get("node", "")
    from_node = data.get("from", "")

    # Update position
    szp = world.get(eid, SubzonePos)
    if szp:
        szp.subzone = node_id
        # Update zone if crossing
        if graph:
            node = graph.get_node(node_id)
            if node:
                szp.zone = node.zone

    name = "?"
    ident = world.get(eid, Identity)
    if ident:
        name = ident.name
    print(f"[SIM] {name} arrived at {node_id} (from {from_node})")

    # Run checkpoint evaluation
    if graph:
        from simulation.checkpoint import run_checkpoint
        outcome = run_checkpoint(world, eid, node_id, graph,
                                 scheduler, game_time)

        if outcome == "arrived":
            # Reached destination — full decision cycle
            from simulation.decision import run_decision_cycle
            run_decision_cycle(world, eid, node_id, graph,
                               scheduler, game_time)


def handle_hunger_critical(world: Any, eid: int, event_type: str,
                           data: dict, scheduler: Any,
                           game_time: float) -> None:
    """Entity's hunger crossed the critical threshold.

    1. Set hunger to threshold value
    2. Try to eat from inventory
    3. If no food: divert to find food
    """
    hunger = world.get(eid, Hunger)
    if not hunger:
        return

    # Set hunger to the threshold
    hunger.current = max(0.0, hunger.maximum * 0.3)

    name = "?"
    ident = world.get(eid, Identity)
    if ident:
        name = ident.name

    # Try to eat from inventory
    if _try_eat(world, eid, game_time):
        print(f"[SIM] {name} ate food (hunger critical)")
        # Reschedule next hunger event
        _schedule_hunger_event(world, eid, scheduler, game_time)
        return

    # Try communal stockpile
    if _try_eat_from_stockpile(world, eid, game_time):
        print(f"[SIM] {name} ate from stockpile (hunger critical)")
        _schedule_hunger_event(world, eid, scheduler, game_time)
        return

    print(f"[SIM] {name} is critically hungry — no food!")

    # Interrupt current activity — trigger decision cycle to find food
    szp = world.get(eid, SubzonePos)
    node_id = szp.subzone if szp else ""

    scheduler.cancel_entity_type(eid, "ARRIVE_NODE")
    world.remove(eid, TravelPlan)

    scheduler.post(
        time=game_time + 0.1,
        eid=eid,
        event_type="DECISION_CYCLE",
        data={"node": node_id, "reason": "hunger"},
    )


def handle_finish_search(world: Any, eid: int, event_type: str,
                         data: dict, scheduler: Any,
                         game_time: float) -> None:
    """Entity finished searching a container.

    Transfer items from container to entity inventory.
    The container is real — items removed are gone for everyone.
    """
    container_eid = data.get("container", 0)
    node_id = data.get("node", "")

    if not world.alive(container_eid):
        _post_decision(scheduler, eid, node_id, game_time)
        return

    ent_inv = world.get(eid, Inventory)
    cont_inv = world.get(container_eid, Inventory)

    if not ent_inv or not cont_inv:
        _post_decision(scheduler, eid, node_id, game_time)
        return

    name = "?"
    ident = world.get(eid, Identity)
    if ident:
        name = ident.name

    # Transfer all items
    transferred = 0
    for item_id, count in list(cont_inv.items.items()):
        ent_inv.items[item_id] = ent_inv.items.get(item_id, 0) + count
        transferred += count

    cont_inv.items.clear()

    # Record in memory
    wmem = world.get(eid, WorldMemory)
    if wmem:
        wmem.observe(
            f"searched:{container_eid}",
            data={"node": node_id, "items_found": transferred},
            game_time=game_time, ttl=600.0,
        )

    print(f"[SIM] {name} searched container at {node_id} — got {transferred} items")

    # Decision cycle for next action
    _post_decision(scheduler, eid, node_id, game_time)


def handle_finish_work(world: Any, eid: int, event_type: str,
                       data: dict, scheduler: Any,
                       game_time: float) -> None:
    """Entity finished a work task (farming, crafting, etc.).

    Work results depend on the job type.
    """
    job = data.get("job", "")
    node_id = data.get("node", "")

    name = "?"
    ident = world.get(eid, Identity)
    if ident:
        name = ident.name

    if job == "farming":
        # Add food to entity's settlement stockpile
        home = world.get(eid, Home)
        if home:
            # Find the settlement entity for this subzone
            _add_to_settlement_stockpile(world, home.subzone,
                                         "raw_food", data.get("yield", 3))
        print(f"[SIM] {name} finished farming at {node_id}")

    elif job == "crafting":
        product = data.get("product", "")
        if product:
            inv = world.get(eid, Inventory)
            if inv:
                inv.items[product] = inv.items.get(product, 0) + 1
        print(f"[SIM] {name} crafted {product}")

    _post_decision(scheduler, eid, node_id, game_time)


def handle_finish_eat(world: Any, eid: int, event_type: str,
                      data: dict, scheduler: Any,
                      game_time: float) -> None:
    """Entity finishes eating (pause timer expired)."""
    _try_eat(world, eid, game_time)

    node_id = data.get("node", "")

    # Resume interrupted travel or decide next action
    plan = world.get(eid, TravelPlan)
    if plan and not plan.complete:
        # Continue travel
        graph = world.res(SubzoneGraph)
        if graph:
            from simulation.travel import continue_travel
            szp = world.get(eid, SubzonePos)
            if szp:
                continue_travel(world, eid, szp.subzone, graph,
                                scheduler, game_time)
                return

    _post_decision(scheduler, eid, node_id, game_time)


def handle_rest_complete(world: Any, eid: int, event_type: str,
                         data: dict, scheduler: Any,
                         game_time: float) -> None:
    """Entity finishes resting.

    Heal HP proportional to rest duration and shelter quality.
    """
    node_id = data.get("node", "")
    duration = data.get("duration", 10.0)

    health = world.get(eid, Health)
    if health:
        # Heal 20% of max HP per 10 minutes of rest
        heal_rate = 0.02 * duration
        health.current = min(health.maximum,
                             health.current + health.maximum * heal_rate)

    name = "?"
    ident = world.get(eid, Identity)
    if ident:
        name = ident.name
    print(f"[SIM] {name} rested for {duration:.0f} min (HP: {health.current:.0f})"
          if health else f"[SIM] {name} rested")

    _post_decision(scheduler, eid, node_id, game_time)


def handle_decision_cycle(world: Any, eid: int, event_type: str,
                          data: dict, scheduler: Any,
                          game_time: float,
                          graph: SubzoneGraph | None = None) -> None:
    """Trigger a full decision cycle for the entity."""
    node_id = data.get("node", "")
    if graph:
        from simulation.decision import run_decision_cycle
        run_decision_cycle(world, eid, node_id, graph,
                           scheduler, game_time)


def handle_combat_resolved(world: Any, eid: int, event_type: str,
                           data: dict, scheduler: Any,
                           game_time: float) -> None:
    """Post-combat cleanup (used when combat is deferred)."""
    # This is mostly handled inline by resolve_encounter
    node_id = data.get("node", "")
    _post_decision(scheduler, eid, node_id, game_time)


# ═════════════════════════════════════════════════════════════════════
#  HELPERS
# ═════════════════════════════════════════════════════════════════════


def _try_eat(world: Any, eid: int, game_time: float) -> bool:
    """Try to eat best food from inventory.  Delegates to the canonical
    ``npc_eat_from_inventory`` in ``logic.needs_system``."""
    from logic.needs import npc_eat_from_inventory
    return npc_eat_from_inventory(world, eid)


def _try_eat_from_stockpile(world: Any, eid: int,
                            game_time: float) -> bool:
    """Try to eat from the entity's home settlement stockpile."""
    from components.simulation import Stockpile
    home = world.get(eid, Home)
    if not home:
        return False

    home_zone = home.zone

    # Find settlement stockpile
    for seid, stockpile in world.all_of(Stockpile):
        szp = world.get(seid, SubzonePos)
        if not szp:
            continue
        if szp.subzone != home.subzone:
            if not home_zone or szp.zone != home_zone:
                continue
        # Try to take food
        for item_id in list(stockpile.items.keys()):
            if stockpile.items[item_id] > 0:
                stockpile.remove(item_id, 1)
                hunger = world.get(eid, Hunger)
                if hunger:
                    hunger.current = min(hunger.maximum,
                                         hunger.current + 25.0)
                return True
    return False


def _add_to_settlement_stockpile(world: Any, subzone_id: str,
                                 item_id: str, count: int) -> None:
    """Add items to the settlement stockpile at a subzone."""
    from components.simulation import Stockpile
    graph = world.res(SubzoneGraph)
    zone_id = None
    if graph:
        node = graph.get_node(subzone_id)
        if node:
            zone_id = node.zone
    for seid, stockpile in world.all_of(Stockpile):
        szp = world.get(seid, SubzonePos)
        if not szp:
            continue
        if szp.subzone != subzone_id:
            if not zone_id or szp.zone != zone_id:
                continue
        stockpile.add(item_id, count)
        return


def _post_decision(scheduler: Any, eid: int, node_id: str,
                   game_time: float) -> None:
    """Post a deferred decision cycle."""
    scheduler.post(
        time=game_time + 0.1,
        eid=eid,
        event_type="DECISION_CYCLE",
        data={"node": node_id},
    )


def schedule_hunger_events(world: Any, scheduler: Any,
                           game_time: float) -> int:
    """Schedule HUNGER_CRITICAL events for all entities with Hunger.

    Called once during initialization to bootstrap the event queue.
    Returns count of events scheduled.
    """
    count = 0
    for eid, hunger in world.all_of(Hunger):
        # Only for low-LOD entities (those with SubzonePos)
        if not world.has(eid, SubzonePos):
            continue
        _schedule_hunger_event(world, eid, scheduler, game_time)
        count += 1
    return count


def _schedule_hunger_event(world: Any, eid: int, scheduler: Any,
                           game_time: float) -> None:
    """Schedule the next HUNGER_CRITICAL for a single entity."""
    if not world.has(eid, SubzonePos):
        return
    hunger = world.get(eid, Hunger)
    if not hunger:
        return

    # Cancel existing hunger events for this entity
    scheduler.cancel_entity_type(eid, "HUNGER_CRITICAL")

    threshold = hunger.maximum * 0.3
    if hunger.current <= threshold:
        # Already critical — fire soon
        scheduler.post(game_time + 0.5, eid, "HUNGER_CRITICAL", {})
        return

    # Predict when hunger hits threshold
    # hunger.rate is hunger/second, but scheduler works in game-minutes
    # Convert: drain per minute = rate * 60
    drain_per_minute = hunger.rate * 60.0
    if drain_per_minute <= 0:
        return  # No drain

    time_to_critical = (hunger.current - threshold) / drain_per_minute
    scheduler.post(game_time + time_to_critical, eid, "HUNGER_CRITICAL", {})


# ═════════════════════════════════════════════════════════════════════
#  COMMUNAL MEALTIME SYSTEM  (extracted → simulation/communal_meals.py)
# ═════════════════════════════════════════════════════════════════════

from simulation.communal_meals import (          # noqa: F401 — re-export
    handle_communal_meal,
    schedule_meal_events,
    DAY_LENGTH,
    MEAL_TIMES,
    MEAL_DURATION,
    GUARD_DELAY,
    COMMUNAL_NODE,
)
