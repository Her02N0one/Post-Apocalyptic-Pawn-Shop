"""logic/actions/inventory.py — Player inventory screen action."""

from __future__ import annotations
from components import Player, Position, Inventory, Equipment, ItemRegistry
from logic.actions import OpenInventoryIntent


def player_toggle_inventory(app):
    """Player presses I — return an inventory intent or None."""
    res = app.world.query_one(Player, Position)
    if not res:
        return None
    player_eid = res[0]

    inv = app.world.get(player_eid, Inventory)
    if inv is None:
        return None

    equip = app.world.get(player_eid, Equipment)
    registry = app.world.res(ItemRegistry)

    return OpenInventoryIntent(
        player_inv=inv.items,
        equipment=equip,
        registry=registry,
        title="Inventory",
    )
