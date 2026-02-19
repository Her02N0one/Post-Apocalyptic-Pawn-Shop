"""systems/gameplay.py — Shared gameplay logic for all view modes.

Scene-agnostic operations (pickup, containers, loot, inventory,
platforms, NPC dialogue) that both TopDown and FirstPerson call into.
No module here imports anything from ``scenes/``.

Usage::

    from systems.gameplay import (
        do_interact, open_inventory, open_container,
        pickup_ground_item, spawn_ground_item,
        try_platform_interact_td, try_platform_interact_fp,
        roll_loot,
    )
"""

from __future__ import annotations

import logging
import math
import random
from pathlib import Path
from typing import Any, TYPE_CHECKING

from core.tiles import PLATFORM_IDS, tile_def as _tile_def
from core.types import Direction, EntityKind
from components import (
    Position, Velocity, Facing, Player,
    Identity, Inventory, TileEntity,
)
from systems.interaction import try_interact, nearest_interactable
from systems.item_registry import ItemRegistry

if TYPE_CHECKING:
    from core.ecs import World
    from core.app import App
    from core.session import Session
    from ui.modal import ModalStack

_log = logging.getLogger(__name__)

# Loot table data — cached after first load so we don't re-read from
# disk on every container opened.
_loot_data: dict[str, Any] | None = None


def _get_loot_data() -> dict[str, Any]:
    """Return cached loot-table data, loading from disk on first call."""
    global _loot_data
    if _loot_data is not None:
        return _loot_data
    try:
        try:
            import tomllib
        except ModuleNotFoundError:
            import tomli as tomllib  # type: ignore[no-redef]
        path = Path(__file__).resolve().parent.parent / "data" / "loot_tables.toml"
        with open(path, "rb") as f:
            _loot_data = tomllib.load(f)
    except Exception as exc:
        _log.warning("Failed to load loot_tables.toml: %s", exc)
        _loot_data = {}
    return _loot_data


# ═════════════════════════════════════════════════════════════════════
#  Loot rolling
# ═════════════════════════════════════════════════════════════════════

def roll_loot(table_id: str) -> dict[str, int]:
    """Roll a loot table and return ``{item_id: count}``."""
    try:
        data = _get_loot_data()
        table = data.get("tables", {}).get(table_id)
        if not table:
            return {}
        items: dict[str, int] = {}
        for pool in table.get("pools", []):
            rolls = int(pool.get("rolls", 1))
            bonus = pool.get("bonus_rolls", 0)
            if bonus:
                rolls += int(random.random() * bonus)
            entries = pool.get("entries", [])
            if not entries:
                continue
            weights = [e.get("weight", 1) for e in entries]
            for _ in range(rolls):
                chosen = random.choices(entries, weights=weights, k=1)[0]
                item = chosen.get("item", "")
                lo = chosen.get("min_count", 1)
                hi = chosen.get("max_count", 1)
                count = random.randint(lo, hi)
                items[item] = items.get(item, 0) + count
        return items
    except Exception as exc:
        _log.warning("roll_loot(%s) failed: %s", table_id, exc)
        return {}


# ═════════════════════════════════════════════════════════════════════
#  Item pickup / spawn
# ═════════════════════════════════════════════════════════════════════

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
    registry: ItemRegistry,
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


# ═════════════════════════════════════════════════════════════════════
#  Containers
# ═════════════════════════════════════════════════════════════════════

def open_container(
    world: "World",
    eid: int,
    te: TileEntity,
    modals: "ModalStack",
    registry: ItemRegistry,
    *,
    release_mouse: Any = None,
) -> None:
    """Open a container tile entity for item transfer.

    ``release_mouse`` is an optional callable (for FP mode) to
    ungrab the mouse before pushing the modal.
    """
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


# ═════════════════════════════════════════════════════════════════════
#  Inventory
# ═════════════════════════════════════════════════════════════════════

def open_inventory(
    world: "World",
    modals: "ModalStack",
    registry: ItemRegistry,
    zone_name: str,
    *,
    release_mouse: Any = None,
) -> None:
    """Open the player inventory modal (with drop support)."""
    from ui.inventory_modal import InventoryModal

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


# ═════════════════════════════════════════════════════════════════════
#  NPC dialogue
# ═════════════════════════════════════════════════════════════════════

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


# ═════════════════════════════════════════════════════════════════════
#  Platform interaction (surface containers)
# ═════════════════════════════════════════════════════════════════════

def get_platform_entity(
    world: "World",
    col: int,
    row: int,
    tid: int,
    zone: str,
) -> int:
    """Find or create an ECS entity for a platform tile at (col, row)."""
    for eid, pos, te in world.query(Position, TileEntity):
        if (pos.zone == zone
                and te.tile_type == "platform_surface"
                and te.tiles == [[row, col]]):
            return eid
    td = _tile_def(tid)
    name = td.name if td else "Surface"
    eid = world.spawn()
    world.add(eid, Position(x=col + 0.5, y=row + 0.5, zone=zone))
    world.add(eid, Identity(name=name, kind=EntityKind.CONTAINER))
    world.add(eid, TileEntity(
        tile_type="platform_surface",
        tiles=[[row, col]],
    ))
    world.add(eid, Inventory(items={}))
    return eid


def try_platform_interact_td(
    world: "World",
    tiles: list[list[int]],
    modals: "ModalStack",
    registry: ItemRegistry,
    zone: str,
) -> bool:
    """Top-down platform interaction using Facing direction."""
    result = world.query_one(Player, Position, Facing)
    if not result:
        return False
    _, _, p_pos, p_face = result
    offsets = {
        Direction.UP:    (0, -1),
        Direction.DOWN:  (0,  1),
        Direction.LEFT:  (-1, 0),
        Direction.RIGHT: (1,  0),
    }
    dx, dy = offsets.get(p_face.direction, (0, 0))
    tx = int(p_pos.x) + dx
    ty = int(p_pos.y) + dy
    if not tiles:
        return False
    mh = len(tiles)
    mw = len(tiles[0]) if mh else 0
    if 0 <= ty < mh and 0 <= tx < mw:
        tid = tiles[ty][tx]
        if tid in PLATFORM_IDS:
            eid = get_platform_entity(world, tx, ty, tid, zone)
            te = world.get(eid, TileEntity)
            open_container(world, eid, te, modals, registry)
            return True
    return False


def try_platform_interact_fp(
    world: "World",
    tiles: list[list[int]],
    player_angle: float,
    modals: "ModalStack",
    registry: ItemRegistry,
    zone: str,
    *,
    release_mouse: Any = None,
) -> bool:
    """First-person platform interaction using look angle."""
    result = world.query_one(Player, Position)
    if not result:
        return False
    _, _, p_pos = result
    cos_a = math.cos(player_angle)
    sin_a = math.sin(player_angle)
    if not tiles:
        return False
    mh = len(tiles)
    mw = len(tiles[0]) if mh else 0
    for dist in (0.8, 1.2, 1.6):
        tx = int(p_pos.x + cos_a * dist)
        ty = int(p_pos.y + sin_a * dist)
        if 0 <= ty < mh and 0 <= tx < mw:
            tid = tiles[ty][tx]
            if tid in PLATFORM_IDS:
                eid = get_platform_entity(world, tx, ty, tid, zone)
                te = world.get(eid, TileEntity)
                open_container(
                    world, eid, te, modals, registry,
                    release_mouse=release_mouse,
                )
                return True
    return False


# ═════════════════════════════════════════════════════════════════════
#  Unified interact dispatch
# ═════════════════════════════════════════════════════════════════════

def do_interact_td(
    world: "World",
    session: "Session",
    modals: "ModalStack",
    registry: ItemRegistry,
) -> None:
    """Handle E key in top-down mode — interact with nearest entity."""
    found = nearest_interactable(world)
    if found:
        t_eid, _ = found
        te = world.get(t_eid, TileEntity)
        if te:
            if te.tile_type == "container":
                open_container(world, t_eid, te, modals, registry)
                return
            elif te.tile_type == "ground_item":
                pickup_ground_item(world, t_eid, te, session=session)
                return
        ident = world.get(t_eid, Identity)
        if ident and ident.kind == EntityKind.NPC:
            open_npc_dialogue(world, t_eid, modals)
        elif try_interact(world, world.events):
            name = ident.name if ident else "???"
            session.status = f"Interacted with {name}"
            session.status_timer = 1.5
    else:
        if try_platform_interact_td(
            world, session.tiles, modals, registry, session.zone_name
        ):
            return
        session.status = "Nothing nearby"
        session.status_timer = 1.0


def do_interact_fp(
    world: "World",
    session: "Session",
    modals: "ModalStack",
    registry: ItemRegistry,
    player_angle: float,
    *,
    release_mouse: Any = None,
) -> None:
    """Handle E key in first-person mode — interact with nearest entity."""
    found = nearest_interactable(world)
    if found:
        t_eid, _ = found
        te = world.get(t_eid, TileEntity)
        if te:
            if te.tile_type == "container":
                open_container(
                    world, t_eid, te, modals, registry,
                    release_mouse=release_mouse,
                )
                return
            elif te.tile_type == "ground_item":
                pickup_ground_item(world, t_eid, te, session=session)
                return
        ident = world.get(t_eid, Identity)
        if ident and ident.kind == EntityKind.NPC:
            open_npc_dialogue(
                world, t_eid, modals, release_mouse=release_mouse,
            )
        elif try_interact(world, world.events):
            name = ident.name if ident else "???"
            session.status = f"Interacted with {name}"
            session.status_timer = 1.5
    else:
        if try_platform_interact_fp(
            world, session.tiles, player_angle, modals, registry,
            session.zone_name, release_mouse=release_mouse,
        ):
            return
        session.status = "Nothing nearby"
        session.status_timer = 1.0
