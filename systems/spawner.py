"""systems/spawner.py — Create entities from data descriptors.

Descriptor formats (both supported)::

    # New format — resolved via entity_defs.toml registry
    {
        "type": "barrel",
        "id": "barrel_42",
        "position": {"x": 5.0, "y": 4.0},
        "overrides": {"identity": {"name": "Big Barrel"}}
    }

    # Legacy format — resolved via _LEGACY_PREFAB_MAP
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

import warnings
from typing import Any, TYPE_CHECKING

from core.ecs import Component
from core.entity_defs import get_entity_def
from core.types import Direction, EntityKind
from components import (
    Position, Velocity, Sprite, Identity, Health, Inventory,
    Facing, Collider, PrefabRef, Player, TileEntity, WallSprite,
    CombatStats, PrismShape,
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
    "prop": EntityKind.PROP,
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


def _build_combat(d: dict) -> CombatStats:
    return CombatStats(
        damage=float(d.get("damage", 5.0)),
        attack_range=int(d.get("attack_range", 1)),
        attack_cooldown=float(d.get("attack_cooldown", 2.0)),
        hostile=bool(d.get("hostile", False)),
    )


# ── Component builder dispatch table ────────────────────────────────
# Maps component key → (builder_fn, component_class).
# Used by _attach_components() to DRY up both spawn and rebuild paths.

_BUILDERS: dict[str, tuple[Any, type[Component]]] = {
    "sprite":      (_build_sprite,       Sprite),
    "identity":    (_build_identity,     Identity),
    "health":      (_build_health,       Health),
    "collider":    (_build_collider,     Collider),
    "facing":      (_build_facing,       Facing),
    "player":      (_build_player,       Player),
    "inventory":   (_build_inventory,    Inventory),
    "tile_entity": (_build_tile_entity,  TileEntity),
    "wall_sprite": (_build_wall_sprite,  WallSprite),
    "combat":      (_build_combat,       CombatStats),
}

# Keys that are NOT component sub-tables (handled separately).
_NON_COMPONENT_KEYS = {"id", "type", "prefab", "position", "overrides"}

# ── Legacy prefab name → new type ID mapping ────────────────────────
# Old zone files / saves use "prefab": "merchant".
# New TOML registry uses "merchant_npc".

_LEGACY_PREFAB_MAP: dict[str, str] = {
    # Characters
    "npc":          "survivor_npc",
    "merchant":     "merchant_npc",
    "villager":     "villager_npc",
    # These map 1:1 — listed explicitly for clarity
    "dummy":        "dummy",
    "player":       "player",
    "beast":        "beast",
    # Containers / gameplay objects
    "container":    "container",
    "crop":         "crop",
    "ground_item":  "ground_item",
    "crate":        "wooden_crate",
    # Props / furniture — already match TOML IDs
    "shelf":        "shelf",
    "barrel":       "barrel",
    "table":        "table",
    "chair":        "chair",
    "lantern":      "lantern",
    "bookcase":     "bookcase",
    "counter":      "counter",
    "safe":         "safe",
    "potted_plant": "potted_plant",
}


def _resolve_type(desc: dict[str, Any]) -> tuple[str, dict[str, dict[str, Any]]]:
    """Resolve a descriptor to (type_id, defaults_dict).

    Supports both new ``"type"`` key and legacy ``"prefab"`` key.
    Returns the matched EntityDef's component defaults, or an empty dict
    if the type is unknown (with a warning).
    """
    # ── New format: "type" key ────────────────────────────────────
    type_id = desc.get("type", "")
    if type_id:
        edef = get_entity_def(type_id)
        if edef is not None:
            return type_id, edef.component_defaults()
        warnings.warn(f"[SPAWNER] Unknown entity type '{type_id}'",
                       stacklevel=3)
        return type_id, {}

    # ── Legacy format: "prefab" key ───────────────────────────────
    prefab = desc.get("prefab", "")
    if prefab:
        mapped_id = _LEGACY_PREFAB_MAP.get(prefab, prefab)
        edef = get_entity_def(mapped_id)
        if edef is not None:
            return mapped_id, edef.component_defaults()
        # Prefab not in new registry — truly unknown
        warnings.warn(f"[SPAWNER] Unknown prefab '{prefab}' "
                       f"(mapped to '{mapped_id}')", stacklevel=3)
        return mapped_id, {}

    return "", {}


def _merge(defaults: dict[str, Any] | None,
           overrides: dict[str, Any] | None) -> dict[str, Any] | None:
    """Shallow-merge two component dicts (defaults ← overrides)."""
    if defaults is None and overrides is None:
        return None
    if defaults is None:
        return overrides
    if overrides is None:
        return dict(defaults)
    result = dict(defaults)
    result.update(overrides)
    return result


def _attach_components(world: "World", eid: int,
                       defaults: dict[str, dict[str, Any]],
                       overrides: dict[str, Any],
                       skip_existing: bool = False) -> None:
    """Attach all known components from merged defaults + overrides.

    Parameters
    ----------
    world : World
        ECS world.
    eid : int
        Entity to attach to.
    defaults : dict
        Component defaults from the registry (``EntityDef.component_defaults()``).
    overrides : dict
        Per-entity overrides from the descriptor.
    skip_existing : bool
        If ``True``, skip components the entity already has (used during
        ``rebuild_transients``).
    """
    for comp_key, (builder, comp_cls) in _BUILDERS.items():
        data = _merge(defaults.get(comp_key), overrides.get(comp_key))
        if data is None:
            continue
        if skip_existing and world.has(eid, comp_cls):
            continue
        world.add(eid, builder(data))


# ── Public API ───────────────────────────────────────────────────────

def spawn_from_descriptor(world: "World", desc: dict[str, Any],
                          zone: str) -> int:
    """Spawn an entity from a data descriptor dict.

    Returns the new entity ID.
    """
    eid = world.spawn()

    # Resolve type via registry (new format) or legacy prefab map
    type_id, defaults = _resolve_type(desc)

    # ── Determine overrides ──────────────────────────────────────
    # New format: overrides live in desc["overrides"]
    # Legacy format: overrides are top-level keys in desc itself
    overrides: dict[str, Any]
    if "overrides" in desc:
        overrides = desc["overrides"]
    else:
        # Legacy: pick out component-like keys from the descriptor
        overrides = {k: v for k, v in desc.items()
                     if isinstance(v, dict) and k not in _NON_COMPONENT_KEYS}

    # PrefabRef — links entity to its template for rebuild on load
    uid = desc.get("id", "")
    prefab = desc.get("prefab", "")
    if uid or type_id or prefab:
        edef_for_ver = get_entity_def(type_id) if type_id else None
        def_ver = edef_for_ver.def_version if edef_for_ver else ""
        world.add(eid, PrefabRef(uid=uid, prefab=type_id or prefab,
                                 def_version=def_ver))

    # Position (required — every spawned entity needs one)
    # New unified format: flat x/y at descriptor top level
    # Legacy format: nested {"position": {"x": ..., "y": ...}}
    pos_data = _merge(defaults.get("position"),
                      overrides.get("position") or desc.get("position"))
    if pos_data is None and ("x" in desc or "y" in desc):
        pos_data = {"x": desc.get("x", 0.0), "y": desc.get("y", 0.0)}
    pos_data = pos_data or {"x": 0.0, "y": 0.0}
    world.add(eid, _build_position(pos_data, zone))

    # Velocity (always — so physics system can move it)
    world.add(eid, Velocity())

    # Attach all other components
    _attach_components(world, eid, defaults, overrides, skip_existing=False)

    # PrismShape — derived from entity def geometry, not a TOML component
    edef = get_entity_def(type_id)
    if edef and edef.render_type == "prism":
        world.add(eid, PrismShape(
            width=edef.width,
            depth=edef.depth,
            height=edef.height,
            elevation=edef.elevation,
            yaw=float(desc.get("angle", 0.0)),
            textures=edef.texture_map(),
            movable=bool(desc.get("movable", edef.movable)),
        ))

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
    entity's type defaults + per-entity descriptor overrides and re-attaches
    the transient components (Sprite, Identity, Collider, Facing, Player, etc.).
    """
    for eid, ref in world.all_of(PrefabRef):
        desc = descriptor_index.get(ref.uid, {})

        # Resolve type from PrefabRef.prefab (which is now the type_id
        # for new entities, or a legacy prefab name for old saves).
        mapped_id = _LEGACY_PREFAB_MAP.get(ref.prefab, ref.prefab)
        edef = get_entity_def(mapped_id)
        if edef is None and mapped_id:
            warnings.warn(
                f"[SPAWNER] rebuild_transients: unknown type '{mapped_id}' "
                f"for entity uid='{ref.uid}'. Entity definition may have "
                f"changed since this save was created.",
                stacklevel=2,
            )
        defaults = edef.component_defaults() if edef else {}

        # ── Version mismatch detection ────────────────────────────
        if edef and ref.def_version and edef.def_version != ref.def_version:
            warnings.warn(
                f"[SPAWNER] Entity definition for '{mapped_id}' has changed "
                f"since this save was created (saved version={ref.def_version}, "
                f"current={edef.def_version}).  Entity uid='{ref.uid}' may "
                f"have mismatched components.",
                stacklevel=2,
            )

        # Determine overrides (same new/legacy split as spawn)
        if "overrides" in desc:
            overrides = desc["overrides"]
        else:
            overrides = {k: v for k, v in desc.items()
                         if isinstance(v, dict) and k not in _NON_COMPONENT_KEYS}

        # Velocity (always present, starts at zero)
        if not world.has(eid, Velocity):
            world.add(eid, Velocity())

        # Attach transient components (skip those already persisted)
        _attach_components(world, eid, defaults, overrides, skip_existing=True)

        # PrismShape — derived from entity def geometry
        if edef and edef.render_type == "prism" and not world.has(eid, PrismShape):
            world.add(eid, PrismShape(
                width=edef.width,
                depth=edef.depth,
                height=edef.height,
                elevation=edef.elevation,
                yaw=float(desc.get("angle", 0.0)),
                textures=edef.texture_map(),
                movable=bool(desc.get("movable", edef.movable)),
            ))

    # All transient components rebuilt — mark the world as valid.
    world._transients_valid = True

