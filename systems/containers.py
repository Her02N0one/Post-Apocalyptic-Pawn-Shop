"""systems.containers — Container, inventory, and NPC dialogue interaction.

Scene-agnostic operations for opening containers, the player inventory,
and NPC dialogue modals.

Usage::

    from systems.containers import open_container, open_inventory
"""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from core.types import EntityKind
from components import (
    Position, Player, Identity, Inventory, TileEntity,
)
from systems.loot import roll_loot

if TYPE_CHECKING:
    from core.ecs import World
    from systems.item_registry import ItemRegistry
    from ui.modal import ModalStack

_log = logging.getLogger(__name__)


def open_container(
    world: "World",
    eid: int,
    te: TileEntity,
    modals: "ModalStack",
    registry: "ItemRegistry",
    *,
    release_mouse: Any = None,
) -> None:
    """Open a container tile entity for item transfer."""
    from ui.transfer_modal import TransferModal

    res = world.query_one(Player, Inventory)
    if not res:
        return
    _, _, p_inv = res

    container_inv = world.get(eid, Inventory)
    if container_inv is None:
        container_inv = Inventory(items={})
        world.add(eid, container_inv)

    # Roll loot on first open
    if te.loot_table and not te.looted:
        container_inv.items.update(roll_loot(te.loot_table))
        te.looted = True

    ident = world.get(eid, Identity)
    title = ident.name if ident else "Container"

    if release_mouse is not None:
        release_mouse()

    modals.push(TransferModal(
        player_inv=p_inv.items,
        container_inv=container_inv.items,
        registry=registry,
        container_title=title,
    ))


def open_inventory(
    world: "World",
    modals: "ModalStack",
    registry: "ItemRegistry",
    zone_name: str,
    *,
    release_mouse: Any = None,
) -> None:
    """Open the player inventory modal (with drop support)."""
    from ui.inventory_modal import InventoryModal
    from systems.items import spawn_ground_item

    res = world.query_one(Player, Inventory)
    if not res:
        p_res = world.query_one(Player, Position)
        if not p_res:
            return
        p_eid = p_res[0]
        inv = Inventory(items={})
        world.add(p_eid, inv)
    else:
        _, _, inv = res

    def on_drop(item_id: str, qty: int) -> None:
        spawn_ground_item(world, item_id, qty, registry, zone_name)

    if release_mouse is not None:
        release_mouse()

    modals.push(InventoryModal(
        player_inv=inv.items,
        registry=registry,
        on_drop=on_drop,
    ))


def open_npc_dialogue(
    world: "World",
    npc_eid: int,
    modals: "ModalStack",
    *,
    release_mouse: Any = None,
) -> None:
    """Open a contextual dialogue modal for an NPC."""
    from systems.dialogue_gen import build_npc_dialogue
    from ui.dialogue_modal import DialogueModal

    ident = world.get(npc_eid, Identity)
    npc_name = ident.name if ident else "???"
    tree = build_npc_dialogue(world, npc_eid)

    if release_mouse is not None:
        release_mouse()

    modals.push(DialogueModal(tree, npc_name=npc_name, npc_eid=npc_eid))
