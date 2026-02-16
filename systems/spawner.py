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
    Position, Velocity, Sprite, Identity, Health,
    Facing, Collider, PrefabRef, Player,
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
        "collider": {"w": 0.8, "h": 0.8, "solid": True},
        "facing": {"direction": "down"},
    },
    "npc": {
        "identity": {"name": "NPC", "kind": "npc"},
        "sprite": {"char": "N", "color": [180, 180, 255], "layer": 5},
        "health": {"current": 100, "maximum": 100},
        "collider": {"w": 0.8, "h": 0.8, "solid": True},
        "facing": {"direction": "down"},
    },
    "player": {
        "identity": {"name": "You", "kind": "player"},
        "sprite": {"char": "@", "color": [255, 255, 100], "layer": 10},
        "health": {"current": 100, "maximum": 100},
        "collider": {"w": 0.8, "h": 0.8, "solid": True},
        "facing": {"direction": "down"},
        "player": {"speed": 6.0},
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
