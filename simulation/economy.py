"""simulation/economy.py — Village economic loop.

Farmers work farm plots (FINISH_WORK adds food to Stockpile).
Villagers eat from Stockpile (HUNGER_CRITICAL draws from shared resource).
Surplus/deficit drives trade willingness.
Scavengers go out to find what the village needs.
"""

from __future__ import annotations
from typing import Any

from components import Identity, Inventory
from components.simulation import SubzonePos, Home, Stockpile
from simulation.subzone import SubzoneGraph


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

    name = "?"
    ident = world.get(eid, Identity)
    if ident:
        name = ident.name
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
