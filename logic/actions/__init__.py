"""logic/actions — High-level player actions.

Thin wrappers that scenes call in response to key presses / clicks.
Each function does everything needed so the scene stays small.

Public API (re-exported here for backward-compatible imports)
-------------------------------------------------------------
``AttackResult``              — visual-effect descriptor from attacks
``weapon_rect_for``           — weapon hitbox in world coords
``mouse_world_pos``           — screen -> world coordinate conversion
``player_attack``             — melee/ranged dispatcher
``player_melee_attack``       — swing melee weapon
``player_ranged_attack``      — fire projectile toward cursor
``player_interact_nearby``    — E-key interact dispatcher
``player_loot_nearby``        — open transfer UI with nearest container
``player_toggle_inventory``   — open/close inventory screen
``open_npc_trade``            — open trade modal for a specific NPC
"""

from __future__ import annotations
import math
from dataclasses import dataclass
from components import Position, Player, Inventory, Equipment, ItemRegistry


# ── Intent objects (action functions return these; scene maps to UI) ──

@dataclass
class OpenDialogueIntent:
    """Scene should open a DialogueModal with these parameters."""
    tree: dict
    npc_name: str
    npc_eid: int
    quest_log: object = None


@dataclass
class OpenTransferIntent:
    """Scene should open a TransferModal with these parameters."""
    player_inv: dict
    container_inv: dict
    equipment: object = None
    registry: object = None
    title: str = "Your Bag"
    container_title: str = "Container"
    owner_faction: str = ""   # non-empty = owned; theft triggers witnesses
    on_steal: object = None   # callback(item_id) -> str|None  (flash msg)
    locked: bool = False       # container requires lockpicking
    on_lockpick: object = None # callback() -> (bool_success, str_msg)


@dataclass
class OpenInventoryIntent:
    """Scene should open an InventoryModal with these parameters."""
    player_inv: dict
    equipment: object = None
    registry: object = None
    title: str = "Inventory"


# ── Attack result (returned from attack actions -> applied by scene) ──

@dataclass
class AttackResult:
    """Describes visual effects that an attack produced.

    The scene reads these fields and applies them to its own state,
    keeping action logic decoupled from rendering/scene internals.
    """
    melee_active: bool = False
    melee_timer: float = 0.0
    melee_direction: tuple[float, float] = (1, 0)
    muzzle_flash_timer: float = 0.0
    muzzle_flash_start: tuple[float, float] = (0.0, 0.0)
    muzzle_flash_end: tuple[float, float] = (0.0, 0.0)


# ── Constants ────────────────────────────────────────────────────────

FIST_REACH   = 1.0
FIST_WIDTH   = 0.5
PLAYER_SIZE  = 0.8


# ── Weapon hitbox helper ─────────────────────────────────────────────

def weapon_rect_for(pos: Position, facing: str,
                    reach: float | None = None) -> tuple[float, float, float, float]:
    """Return (x, y, w, h) in world-tile coords for the weapon swing."""
    r = reach if reach is not None else FIST_REACH
    w = FIST_WIDTH
    if facing == "right":
        return (pos.x + PLAYER_SIZE, pos.y + (PLAYER_SIZE - w) / 2, r, w)
    elif facing == "left":
        return (pos.x - r, pos.y + (PLAYER_SIZE - w) / 2, r, w)
    elif facing == "up":
        return (pos.x + (PLAYER_SIZE - w) / 2, pos.y - r, w, r)
    else:  # down
        return (pos.x + (PLAYER_SIZE - w) / 2, pos.y + PLAYER_SIZE, w, r)


# ── Mouse helpers ────────────────────────────────────────────────────

def mouse_world_pos(app, scene=None, screen_pos: tuple[int, int] | None = None) -> tuple[float, float] | None:
    """Convert mouse screen position to world-tile coordinates."""
    if screen_pos is None:
        screen_pos = app.mouse_pos()
    mx, my = screen_pos
    from components import Camera
    from core.constants import TILE_SIZE
    cam = app.world.res(Camera)
    if cam is None:
        return None
    sw, sh = app._virtual_size
    ox = sw // 2 - int(cam.x * TILE_SIZE)
    oy = sh // 2 - int(cam.y * TILE_SIZE)
    wx = (mx - ox) / TILE_SIZE
    wy = (my - oy) / TILE_SIZE
    return wx, wy


def _facing_from_angle(angle: float) -> str:
    """Convert a radian angle to one of four cardinal directions."""
    deg = math.degrees(angle) % 360
    if 45 <= deg < 135:
        return "down"
    elif 135 <= deg < 225:
        return "left"
    elif 225 <= deg < 315:
        return "up"
    else:
        return "right"


# ── Re-exports from submodules ───────────────────────────────────────
# These imports MUST come after the definitions above because the
# submodules depend on symbols defined in this __init__.

from logic.actions.player_attacks import (          # noqa: E402, F401
    player_attack, player_melee_attack, player_ranged_attack,
)
from logic.actions.interact import (        # noqa: E402, F401
    player_interact_nearby, player_loot_nearby, open_npc_trade,
)


# ── Inventory action (small, lives here directly) ────────────────────

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
