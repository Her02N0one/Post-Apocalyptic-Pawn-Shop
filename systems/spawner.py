"""systems/spawner.py — Create entities from data descriptors.

A descriptor is a dict (from zone JSON files) describing an entity::

    {
        "id": "dummy_bob",
        "prefab": "dummy",
        "identity": {"name": "Bob the Mannequin"},
        "position": {"x": 5.0, "y": 4.0},
        "sprite": {"color": [220, 150, 80]}
    }

The spawner reads known keys and attaches typed Components.
Unknown keys are silently ignored (forward-compatible).
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from core.ecs import Component
from core.types import Direction, EntityKind
from components import (
    Position, Velocity, Sprite, Identity, Health, Inventory,
    Facing, Collider, PrefabRef, Player, TileEntity, WallSprite,
)

if TYPE_CHECKING:
    from core.ecs import World


# ── Mapping from descriptor keys to component builders ───────────────
# Each builder takes the raw dict value and returns a Component.

def _build_position(d: dict, zone: str) -> Position:
    return Position(
        x=float(d.get("x", 0.0)),
        y=float(d.get("y", 0.0)),
        zone=zone,
    )


def _build_sprite(d: dict) -> Sprite:
    color = d.get("color", [200, 200, 200])
    if not isinstance(color, (list, tuple)) or len(color) < 3:
        color = [200, 200, 200]
    return Sprite(
        char=d.get("char", "D"),
        color=(int(color[0]), int(color[1]), int(color[2])),
        layer=int(d.get("layer", 5)),
    )


_KIND_MAP: dict[str, EntityKind] = {
    "npc": EntityKind.NPC,
    "player": EntityKind.PLAYER,
    "item": EntityKind.ITEM,
    "container": EntityKind.CONTAINER,
    "dummy": EntityKind.DUMMY,
    "beast": EntityKind.BEAST,
    "ground_item": EntityKind.GROUND_ITEM,
    "crop": EntityKind.CROP,
}


def _build_identity(d: dict) -> Identity:
    kind_str = d.get("kind", "npc")
    kind = _KIND_MAP.get(kind_str, EntityKind.NPC)
    return Identity(name=d.get("name", ""), kind=kind)


def _build_health(d: dict) -> Health:
    return Health(
        current=float(d.get("current", 100.0)),
        maximum=float(d.get("maximum", 100.0)),
    )


def _build_collider(d: dict) -> Collider:
    return Collider(
        w=float(d.get("w", 0.8)),
        h=float(d.get("h", 0.8)),
        solid=bool(d.get("solid", True)),
    )


_DIRECTION_MAP: dict[str, Direction] = {
    "up": Direction.UP,
    "down": Direction.DOWN,
    "left": Direction.LEFT,
    "right": Direction.RIGHT,
}


def _build_facing(d: dict) -> Facing:
    dir_str = d.get("direction", "down")
    return Facing(direction=_DIRECTION_MAP.get(dir_str, Direction.DOWN))


def _build_tile_entity(d: dict) -> TileEntity:
    tiles_raw = d.get("tiles", [])
    tiles = []
    for t in tiles_raw:
        if isinstance(t, (list, tuple)) and len(t) >= 2:
            tiles.append((int(t[0]), int(t[1])))
    return TileEntity(
        tile_type=d.get("tile_type", ""),
        item_id=d.get("item_id", ""),
        item_qty=int(d.get("item_qty", 1)),
        tiles=tiles,
        loot_table=d.get("loot_table", ""),
        looted=bool(d.get("looted", False)),
    )


def _build_wall_sprite(d: dict) -> WallSprite:
    return WallSprite(
        texture_key=d.get("texture_key", ""),
        width=float(d.get("width", 1.0)),
        height=float(d.get("height", 1.0)),
        elevation=float(d.get("elevation", 0.0)),
    )


def _build_inventory(d: dict) -> Inventory:
    items_raw = d.get("items", {})
    items = {str(k): int(v) for k, v in items_raw.items()}
    return Inventory(items=items)


def _build_player(d: dict) -> Player:
    return Player(speed=float(d.get("speed", 6.0)))


# ── Prefab defaults ──────────────────────────────────────────────────
# A prefab is just a set of default components.  The descriptor can
# override any of them.

_PREFAB_DEFAULTS: dict[str, dict[str, Any]] = {
    "dummy": {
        "identity": {"name": "Mannequin", "kind": "dummy"},
        "sprite": {"char": "D", "color": [200, 200, 200], "layer": 5},
        "health": {"current": 100, "maximum": 100},
        "collider": {"w": 0.6, "h": 0.6, "solid": True},
        "facing": {"direction": "down"},
    },
    "npc": {
        "identity": {"name": "NPC", "kind": "npc"},
        "sprite": {"char": "N", "color": [180, 180, 255], "layer": 5},
        "health": {"current": 100, "maximum": 100},
        "collider": {"w": 0.6, "h": 0.6, "solid": True},
        "facing": {"direction": "down"},
    },
    "merchant": {
        "identity": {"name": "Shopkeeper", "kind": "npc"},
        "sprite": {"char": "M", "color": [220, 180, 60], "layer": 5},
        "health": {"current": 100, "maximum": 100},
        "collider": {"w": 0.6, "h": 0.6, "solid": True},
        "facing": {"direction": "down"},
        "dialogue": {"bark": "Welcome to my shop! Take a look around."},
    },
    "villager": {
        "identity": {"name": "Villager", "kind": "npc"},
        "sprite": {"char": "V", "color": [160, 200, 160], "layer": 5},
        "health": {"current": 100, "maximum": 100},
        "collider": {"w": 0.6, "h": 0.6, "solid": True},
        "facing": {"direction": "down"},
        "dialogue": {"bark": "Careful out there, stranger."},
    },
    "player": {
        "identity": {"name": "You", "kind": "player"},
        "sprite": {"char": "@", "color": [255, 255, 100], "layer": 10},
        "health": {"current": 100, "maximum": 100},
        "collider": {"w": 0.6, "h": 0.6, "solid": True},
        "facing": {"direction": "down"},
        "player": {"speed": 6.0},
        "inventory": {"items": {"scrap_metal": 5, "cloth": 3, "bottlecap": 10}},
    },
    "container": {
        "identity": {"name": "Container", "kind": "container"},
        "sprite": {"char": "C", "color": [180, 140, 80], "layer": 3},
        "collider": {"w": 0.8, "h": 0.8, "solid": True},
        "tile_entity": {"tile_type": "container"},
        "inventory": {"items": {}},
    },
    "crop": {
        "identity": {"name": "Crop", "kind": "crop"},
        "sprite": {"char": "#", "color": [80, 180, 60], "layer": 2},
        "collider": {"w": 0.8, "h": 0.8, "solid": False},
        "tile_entity": {"tile_type": "crop"},
    },
    "ground_item": {
        "identity": {"name": "Item", "kind": "ground_item"},
        "sprite": {"char": "*", "color": [220, 220, 180], "layer": 2},
        "collider": {"w": 0.4, "h": 0.4, "solid": False},
        "tile_entity": {"tile_type": "ground_item"},
    },
    # ── Props — decorative / interactive furniture ───────────────
    "shelf": {
        "identity": {"name": "Shelf", "kind": "container"},
        "sprite": {"char": "\u2261", "color": [140, 100, 60], "layer": 3},
        "collider": {"w": 0.8, "h": 0.8, "solid": True},
        "tile_entity": {"tile_type": "container"},
        "inventory": {"items": {}},
        "facing": {"direction": "down"},
    },
    "crate": {
        "identity": {"name": "Crate", "kind": "container"},
        "sprite": {"char": "\u25a1", "color": [160, 120, 60], "layer": 3},
        "collider": {"w": 0.7, "h": 0.7, "solid": True},
        "tile_entity": {"tile_type": "container"},
        "inventory": {"items": {}},
        "facing": {"direction": "down"},
    },
    "barrel": {
        "identity": {"name": "Barrel", "kind": "container"},
        "sprite": {"char": "O", "color": [120, 85, 50], "layer": 3},
        "collider": {"w": 0.6, "h": 0.6, "solid": True},
        "tile_entity": {"tile_type": "container"},
        "inventory": {"items": {}},
        "facing": {"direction": "down"},
    },
    "table": {
        "identity": {"name": "Table", "kind": "dummy"},
        "sprite": {"char": "\u2550", "color": [100, 75, 45], "layer": 3},
        "collider": {"w": 0.8, "h": 0.8, "solid": True},
        "facing": {"direction": "down"},
    },
    "chair": {
        "identity": {"name": "Chair", "kind": "dummy"},
        "sprite": {"char": "h", "color": [110, 80, 50], "layer": 3},
        "collider": {"w": 0.4, "h": 0.4, "solid": True},
        "facing": {"direction": "down"},
    },
    "lantern": {
        "identity": {"name": "Lantern", "kind": "dummy"},
        "sprite": {"char": "\u2606", "color": [255, 200, 80], "layer": 4},
        "collider": {"w": 0.3, "h": 0.3, "solid": False},
        "facing": {"direction": "down"},
    },
    "bookcase": {
        "identity": {"name": "Bookcase", "kind": "container"},
        "sprite": {"char": "\u2592", "color": [100, 60, 30], "layer": 3},
        "collider": {"w": 0.8, "h": 0.8, "solid": True},
        "tile_entity": {"tile_type": "container"},
        "inventory": {"items": {}},
        "facing": {"direction": "down"},
    },
    "counter": {
        "identity": {"name": "Counter", "kind": "dummy"},
        "sprite": {"char": "\u2500", "color": [130, 110, 80], "layer": 3},
        "collider": {"w": 0.9, "h": 0.5, "solid": True},
        "facing": {"direction": "down"},
    },
    "safe": {
        "identity": {"name": "Safe", "kind": "container"},
        "sprite": {"char": "\u25a0", "color": [70, 70, 80], "layer": 3},
        "collider": {"w": 0.6, "h": 0.6, "solid": True},
        "tile_entity": {"tile_type": "container"},
        "inventory": {"items": {}},
        "facing": {"direction": "down"},
    },
    "potted_plant": {
        "identity": {"name": "Potted Plant", "kind": "dummy"},
        "sprite": {"char": "\u2698", "color": [60, 140, 50], "layer": 3},
        "collider": {"w": 0.4, "h": 0.4, "solid": True},
        "facing": {"direction": "down"},
    },
}


# ── Public API ───────────────────────────────────────────────────────

def spawn_from_descriptor(world: "World", desc: dict[str, Any],
                          zone: str) -> int:
    """Spawn an entity from a data descriptor dict.

    Returns the new entity ID.
    """
    eid = world.spawn()

    # Resolve prefab defaults (descriptor values override)
    prefab_name = desc.get("prefab", "")
    defaults = _PREFAB_DEFAULTS.get(prefab_name, {})

    # PrefabRef — links entity to its template for rebuild on load
    uid = desc.get("id", "")
    if uid or prefab_name:
        world.add(eid, PrefabRef(uid=uid, prefab=prefab_name))

    def merged(key: str) -> dict | None:
        """Return merged prefab-default + descriptor-override dict."""
        base = defaults.get(key)
        over = desc.get(key)
        if base is None and over is None:
            return None
        if base is None:
            return over
        if over is None:
            return dict(base)
        result = dict(base)
        result.update(over)
        return result

    # Position (required — every spawned entity needs one)
    pos_data = merged("position") or {"x": 0.0, "y": 0.0}
    world.add(eid, _build_position(pos_data, zone))

    # Velocity (always — so physics system can move it)
    world.add(eid, Velocity())

    # Sprite
    sprite_data = merged("sprite")
    if sprite_data:
        world.add(eid, _build_sprite(sprite_data))

    # Identity
    id_data = merged("identity")
    if id_data:
        world.add(eid, _build_identity(id_data))

    # Health
    hp_data = merged("health")
    if hp_data:
        world.add(eid, _build_health(hp_data))

    # Collider
    col_data = merged("collider")
    if col_data:
        world.add(eid, _build_collider(col_data))

    # Facing
    face_data = merged("facing")
    if face_data:
        world.add(eid, _build_facing(face_data))

    # Player tag
    player_data = merged("player")
    if player_data:
        world.add(eid, _build_player(player_data))

    # Inventory
    inv_data = merged("inventory")
    if inv_data:
        world.add(eid, _build_inventory(inv_data))

    # TileEntity (containers, crops, ground items)
    te_data = merged("tile_entity")
    if te_data:
        world.add(eid, _build_tile_entity(te_data))

    # WallSprite (entities rendered as wall columns in FP mode)
    ws_data = merged("wall_sprite")
    if ws_data:
        world.add(eid, _build_wall_sprite(ws_data))

    return eid


def spawn_zone_entities(world: "World",
                        entities: list[dict[str, Any]],
                        zone: str) -> list[int]:
    """Spawn all entities from a zone data's entity list.

    Returns a list of spawned entity IDs.
    """
    return [spawn_from_descriptor(world, desc, zone) for desc in entities]


# ── Transient rebuild (used after loading a save) ────────────────────

def rebuild_transients(world: "World",
                       descriptor_index: dict[str, dict[str, Any]]) -> None:
    """Rebuild transient components for every entity that has a PrefabRef.

    After loading a save, entities only have their *persistent* components
    (Position, Health, Inventory, PrefabRef).  This function looks up each
    entity's prefab defaults + per-entity descriptor overrides and re-attaches
    the transient components (Sprite, Identity, Collider, Facing, Player, etc.).
    """
    for eid, ref in world.all_of(PrefabRef):
        desc = descriptor_index.get(ref.uid, {})
        defaults = _PREFAB_DEFAULTS.get(ref.prefab, {})

        def _merged(key: str, _d: dict = desc, _df: dict = defaults) -> dict | None:
            base = _df.get(key)
            over = _d.get(key)
            if base is None and over is None:
                return None
            if base is None:
                return over
            if over is None:
                return dict(base)
            result = dict(base)
            result.update(over)
            return result

        # Velocity (always present, starts at zero)
        if not world.has(eid, Velocity):
            world.add(eid, Velocity())

        # Sprite
        sprite_data = _merged("sprite")
        if sprite_data and not world.has(eid, Sprite):
            world.add(eid, _build_sprite(sprite_data))

        # Identity
        id_data = _merged("identity")
        if id_data and not world.has(eid, Identity):
            world.add(eid, _build_identity(id_data))

        # Collider
        col_data = _merged("collider")
        if col_data and not world.has(eid, Collider):
            world.add(eid, _build_collider(col_data))

        # Facing
        face_data = _merged("facing")
        if face_data and not world.has(eid, Facing):
            world.add(eid, _build_facing(face_data))

        # Player tag (only for player prefab)
        player_data = _merged("player")
        if player_data and not world.has(eid, Player):
            world.add(eid, _build_player(player_data))

        # Inventory (only rebuild if missing — normally persisted)
        inv_data = _merged("inventory")
        if inv_data and not world.has(eid, Inventory):
            world.add(eid, _build_inventory(inv_data))

        # TileEntity (containers, crops, ground items)
        te_data = _merged("tile_entity")
        if te_data and not world.has(eid, TileEntity):
            world.add(eid, _build_tile_entity(te_data))

        # WallSprite (entities rendered as wall columns in FP)
        ws_data = _merged("wall_sprite")
        if ws_data and not world.has(eid, WallSprite):
            world.add(eid, _build_wall_sprite(ws_data))
