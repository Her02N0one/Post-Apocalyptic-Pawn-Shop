"""systems.items — Ground-item pickup and spawning.

Usage::

    from systems.items import pickup_ground_item, spawn_ground_item
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from components import (
    Position, Player, Identity, Inventory, TileEntity,
)

if TYPE_CHECKING:
    from core.ecs import World
    from core.session import Session
    from systems.item_registry import ItemRegistry


def pickup_ground_item(
    world: "World",
    eid: int,
    te: TileEntity,
    *,
    session: "Session",
) -> None:
    """Pick up a ground item entity, adding it to the player inventory."""
    res = world.query_one(Player, Inventory)
    if not res:
        return
    _, _, inv = res

    item_id = te.item_id
    qty = max(1, te.item_qty)
    if item_id:
        inv.items[item_id] = inv.items.get(item_id, 0) + qty

    ident = world.get(eid, Identity)
    name = ident.name if ident else item_id
    session.status = f"Picked up {name}" + (f" x{qty}" if qty > 1 else "")
    session.status_timer = 1.5
    world.kill(eid)


def spawn_ground_item(
    world: "World",
    item_id: str,
    qty: int,
    registry: "ItemRegistry",
    zone_name: str,
) -> None:
    """Spawn a ground-item entity near the player."""
    from systems.spawner import spawn_from_descriptor

    res = world.query_one(Player, Position)
    if not res:
        return
    _, _, p_pos = res

    desc = registry.to_descriptor(item_id)
    col = int(p_pos.x)
    row = int(p_pos.y)
    desc["position"] = {"x": float(col) + 0.5, "y": float(row) + 0.5}
    desc["id"] = f"ground_{item_id}_{id(desc)}"
    desc.setdefault("tile_entity", {})
    desc["tile_entity"]["item_id"] = item_id
    desc["tile_entity"]["item_qty"] = qty
    desc["tile_entity"]["tile_type"] = "ground_item"
    desc["tile_entity"]["tiles"] = [[row, col]]

    spawn_from_descriptor(world, desc, zone_name)
