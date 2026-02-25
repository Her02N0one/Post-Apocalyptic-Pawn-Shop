"""systems.gameplay — Unified interact dispatch + platform interaction.

Scene-agnostic interaction logic that both TopDown and FirstPerson call.
Loot rolling lives in :mod:`systems.loot`, container/inventory/NPC modals
in :mod:`systems.containers`, and ground-item pickup/spawn in
:mod:`systems.items`.

Usage::

    from systems.gameplay import (
        do_interact_td, do_interact_fp,
        open_inventory, open_container,
        pickup_ground_item, spawn_ground_item,
        try_platform_interact_td, try_platform_interact_fp,
        roll_loot,
    )
"""

from __future__ import annotations

import math
from typing import Any, TYPE_CHECKING

from core.tiles import PLATFORM_IDS, tile_def as _tile_def
from core.types import Direction, EntityKind
from components import (
    Position, Facing, Player, Identity, Inventory, TileEntity,
)
from systems.interaction import try_interact, nearest_interactable

# Re-export from submodules so existing callers keep working
from systems.loot import roll_loot                       # noqa: F401
from systems.containers import (                          # noqa: F401
    open_container,
    open_inventory,
    open_npc_dialogue,
)
from systems.items import pickup_ground_item, spawn_ground_item  # noqa: F401

if TYPE_CHECKING:
    from core.ecs import World
    from core.session import Session
    from systems.item_registry import ItemRegistry
    from ui.modal import ModalStack


# ═════════════════════════════════════════════════════════════════════
#  Platform interaction (surface containers)
# ═════════════════════════════════════════════════════════════════════

def get_platform_entity(
    world: "World",
    col: int,
    row: int,
    tid: str,
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
    tiles: list[list[str]],
    modals: "ModalStack",
    registry: "ItemRegistry",
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
    tiles: list[list[str]],
    player_angle: float,
    modals: "ModalStack",
    registry: "ItemRegistry",
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
    registry: "ItemRegistry",
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
    registry: "ItemRegistry",
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
