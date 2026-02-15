"""systems/economy.py — Village economic loop.

Farmers work farm plots (FINISH_WORK adds food to Stockpile).
Villagers eat from Stockpile (HUNGER_CRITICAL draws from shared resource).
Surplus/deficit drives trade willingness.
Scavengers go out to find what the village needs.
"""

from __future__ import annotations
from typing import Any

from components import Identity, Inventory
from components.offscreen import SubzonePos, Home, Stockpile
from core.subzone import SubzoneGraph
from systems.faction_disposition import entity_display_name


def create_settlement(world: Any, name: str, zone: str,
                      subzone: str, initial_items: dict | None = None) -> int:
    """Create a settlement entity with a Stockpile.

    The settlement entity represents the communal resources of a
    village/camp/outpost.  Individual NPCs reference it via their
    Home component.

    Returns the settlement entity ID.
    """
    eid = world.spawn()
    world.add(eid, Identity(name=name, kind="settlement"))
    world.add(eid, SubzonePos(zone=zone, subzone=subzone))
    world.add(eid, Stockpile(items=dict(initial_items or {})))
    print(f"[ECON] Created settlement '{name}' at {subzone} "
          f"(eid={eid}, items={sum((initial_items or {}).values())})")
    return eid


def get_settlement_stockpile(world: Any,
                             subzone: str) -> tuple[int, Any] | None:
    """Find the settlement entity + Stockpile at a subzone.

    Returns (eid, Stockpile) or None.
    """
    for eid, stockpile in world.all_of(Stockpile):
        szp = world.get(eid, SubzonePos)
        if szp and szp.subzone == subzone:
            return eid, stockpile
    return None


def settlement_needs(world: Any, subzone: str) -> dict[str, int]:
    """Return a dict of item_type → quantity_needed for a settlement.

    Currently simplified: just checks if food count is below threshold.
    """
    result = get_settlement_stockpile(world, subzone)
    if not result:
        return {}

    _, stockpile = result
    needs = {}

    # Count food items
    food_count = 0
    for item_id, qty in stockpile.items.items():
        if "food" in item_id.lower() or "bean" in item_id.lower():
            food_count += qty

    if food_count < 10:
        needs["food"] = 10 - food_count

    # Count medical items
    med_count = 0
    for item_id, qty in stockpile.items.items():
        if "bandage" in item_id.lower() or "med" in item_id.lower():
            med_count += qty

    if med_count < 3:
        needs["medical"] = 3 - med_count

    return needs


def deposit_to_stockpile(world: Any, eid: int,
                         item_id: str, count: int = 1) -> int:
    """An NPC deposits items from their inventory into their home stockpile.

    Returns the actual count deposited.
    """
    home = world.get(eid, Home)
    if not home:
        return 0

    inv = world.get(eid, Inventory)
    if not inv or inv.items.get(item_id, 0) < count:
        return 0

    result = get_settlement_stockpile(world, home.subzone)
    if not result:
        return 0

    _, stockpile = result

    # Transfer
    actual = min(count, inv.items.get(item_id, 0))
    inv.items[item_id] = inv.items.get(item_id, 0) - actual
    if inv.items[item_id] <= 0:
        del inv.items[item_id]

    stockpile.add(item_id, actual)

    name = entity_display_name(world, eid)
    print(f"[ECON] {name} deposited {actual}x {item_id} to stockpile")

    return actual


def withdraw_from_stockpile(world: Any, eid: int,
                            item_id: str, count: int = 1) -> int:
    """An NPC withdraws items from their home stockpile into inventory.

    Returns the actual count withdrawn.
    """
    home = world.get(eid, Home)
    if not home:
        return 0

    inv = world.get(eid, Inventory)
    if not inv:
        return 0

    result = get_settlement_stockpile(world, home.subzone)
    if not result:
        return 0

    _, stockpile = result
    actual = stockpile.remove(item_id, count)
    if actual > 0:
        inv.items[item_id] = inv.items.get(item_id, 0) + actual

    return actual


def tick_settlement_economy(world: Any, subzone: str,
                            graph: SubzoneGraph | None = None,
                            game_time: float = 0.0) -> None:
    """Periodic settlement economy update.

    Called from the scheduler or decision cycle to check settlement
    health and adjust NPC priorities.
    Not called per-frame — this is event-driven.
    """
    result = get_settlement_stockpile(world, subzone)
    if not result:
        return

    seid, stockpile = result
    needs = settlement_needs(world, subzone)

    if needs:
        ident = world.get(seid, Identity)
        name = ident.name if ident else subzone
        print(f"[ECON] {name} needs: {needs}")


def add_to_stockpile(world: Any, subzone_id: str,
                     item_id: str, count: int) -> None:
    """Add items to the settlement stockpile at a subzone.

    Used when NPCs deposit scavenged/farmed goods into the communal
    pool.  No-ops silently if no stockpile exists at that subzone.
    """
    from components.offscreen import Stockpile
    from core.subzone import SubzoneGraph

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


# ── Settlement food production ───────────────────────────────────────
# Moved from systems/needs.py — this is a settlement-economy concern,
# not a personal-hunger concern.

_REFILL_ITEMS = {"stew": 3, "ration": 5}
_MAX_STOCK = {"stew": 20, "ration": 30, "canned_beans": 15, "dried_meat": 15}


def settlement_food_production(world: Any) -> None:
    """Slowly refill settlement storehouses — the village farms & cooks.

    Call once per frame.  Accumulates time and adds food periodically
    so the storehouse never stays empty for long.
    """
    from components import (
        GameClock, Brain, Position, Inventory as Inv,
        Identity as Ident, RefillTimers,
    )
    from components.offscreen import SubzonePos as SZP
    from core.tuning import get as _tun

    clock = world.res(GameClock)
    game_time = clock.time if clock else 0.0

    for ceid, cident in world.all_of(Ident):
        if cident.kind != "container":
            continue

        cpos = world.get(ceid, Position)
        cszp = world.get(ceid, SZP)
        cont_zone = cpos.zone if cpos else (cszp.zone if cszp else None)

        if cont_zone != "settlement":
            continue

        cinv = world.get(ceid, Inv)
        if cinv is None:
            continue

        brain = world.get(ceid, Brain)
        if brain is None:
            _do_refill_check(world, ceid, cinv, game_time, _tun)


def _do_refill_check(world, ceid: int, cinv, game_time: float,
                     _tun) -> None:
    """Check if it's time to restock a container."""
    from components import RefillTimers

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
