"""scenes/world/fp_interact.py — Interaction / inventory / container logic.

Thin delegation layer that adapts the shared ``systems.gameplay``
functions to the FirstPerson scene's monkey-patch interface.

Defines methods attached to ``FirstPerson``:
    _do_interact, _open_npc_dialogue, _open_inventory,
    _spawn_ground_item, _pickup_ground_item, _open_container,
    _try_platform_interact, _get_platform_entity, _roll_loot.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from systems.gameplay import (
    do_interact_fp,
    open_inventory,
    open_npc_dialogue,
    open_container,
    pickup_ground_item,
    spawn_ground_item,
    try_platform_interact_fp,
    get_platform_entity,
    roll_loot,
)
from components import TileEntity

if TYPE_CHECKING:
    from core.app import App
    from scenes.world.firstperson import FirstPerson


# ═════════════════════════════════════════════════════════════════════
#  Interaction entry point
# ═════════════════════════════════════════════════════════════════════


def _do_interact(self: "FirstPerson", app: "App") -> None:
    """Handle E key — delegate to shared gameplay logic."""
    do_interact_fp(
        app.world, self.session, self.modals, self._registry,
        self.player_angle, release_mouse=self._release_mouse,
    )


def _open_npc_dialogue(self: "FirstPerson", app: "App", npc_eid: int) -> None:
    """Open a contextual dialogue modal for an NPC."""
    open_npc_dialogue(
        app.world, npc_eid, self.modals,
        release_mouse=self._release_mouse,
    )


# ═════════════════════════════════════════════════════════════════════
#  Inventory
# ═════════════════════════════════════════════════════════════════════


def _open_inventory(self: "FirstPerson", app: "App") -> None:
    """Open the player inventory modal."""
    open_inventory(
        app.world, self.modals, self._registry,
        self.session.zone_name,
        release_mouse=self._release_mouse,
    )


def _spawn_ground_item(self: "FirstPerson", app: "App", item_id: str, qty: int) -> None:
    """Spawn a ground item entity near the player."""
    spawn_ground_item(
        app.world, item_id, qty, self._registry, self.session.zone_name,
    )


def _pickup_ground_item(
    self: "FirstPerson", app: "App", eid: int, te: TileEntity,
) -> None:
    """Pick up a ground item entity, adding it to player inventory."""
    pickup_ground_item(app.world, eid, te, session=self.session)


# ═════════════════════════════════════════════════════════════════════
#  Containers
# ═════════════════════════════════════════════════════════════════════


def _open_container(
    self: "FirstPerson", app: "App", eid: int, te: TileEntity,
) -> None:
    """Open a container tile entity for transfer."""
    open_container(
        app.world, eid, te, self.modals, self._registry,
        release_mouse=self._release_mouse,
    )


def _try_platform_interact(self: "FirstPerson", app: "App") -> bool:
    """Check if looking at a PLATFORM tile and open as surface container."""
    return try_platform_interact_fp(
        app.world, self.session.tiles, self.player_angle,
        self.modals, self._registry, self.session.zone_name,
        release_mouse=self._release_mouse,
    )


def _get_platform_entity(
    self: "FirstPerson", app: "App", col: int, row: int, tid: str,
) -> int:
    """Find or create an entity for a platform tile at (col, row)."""
    return get_platform_entity(
        app.world, col, row, tid, self.session.zone_name,
    )


# ═════════════════════════════════════════════════════════════════════
#  Loot
# ═════════════════════════════════════════════════════════════════════


def _roll_loot(self: "FirstPerson", table_id: str) -> dict[str, int]:
    """Roll a loot table and return item dict."""
    return roll_loot(table_id)
