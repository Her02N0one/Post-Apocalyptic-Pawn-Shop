"""logic/entity_factory.py — Table-driven entity spawning.

A single ``_COMPONENT_TABLE`` maps descriptor keys to component classes
and their field schemas.  ``spawn_from_descriptor`` iterates the table,
reads the sub-dict for each key, casts fields, and attaches components.

Special handlers cover the handful of components that need non-trivial
logic (position zone registration, brain-split backward compat, etc.).
"""

from __future__ import annotations
from typing import Any, Callable
from core.ecs import World
from components import (
    Position, Velocity, Sprite, Identity, SpawnInfo, Brain, HomeRange, Threat, AttackConfig,
    Collider, Health, Hunger, Needs, Inventory, Equipment, Facing,
    Lod, Hurtbox, CombatStats, Loot, LootTableRef,
    Faction, Dialogue, Ownership, Locked,
    SubzonePos, TravelPlan, Home, WorldMemory,
)


# ── Field-schema helpers ─────────────────────────────────────────────

def _float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _bool(v: Any, default: bool = False) -> bool:
    return bool(v) if v is not None else default


def _str(v: Any, default: str = "") -> str:
    return str(v) if v is not None else default


# ── Component table ──────────────────────────────────────────────────
# Each entry: (descriptor_key, ComponentClass, field_map)
# field_map: dict mapping component-kwarg → (descriptor-sub-key, cast, default)

_COMPONENT_TABLE: list[tuple[str, type, dict[str, tuple[str, Callable, Any]]]] = [
    ("sprite", Sprite, {
        "char":  ("char",  _str,   "?"),
        "color": ("color", lambda v, d: tuple(v) if v else d, (200, 200, 200)),
        "layer": ("layer", lambda v, d: int(v) if v is not None else d, 1),
    }),
    ("health", Health, {
        "current": ("current", _float, 100.0),
        "maximum": ("maximum", _float, 100.0),
    }),
    ("combat_stats", CombatStats, {
        "damage":  ("damage",  _float, 5.0),
        "defense": ("defense", _float, 0.0),
    }),
    ("collider", Collider, {
        "width":  ("width",  _float, 0.8),
        "height": ("height", _float, 0.8),
        "solid":  ("solid",  _bool, True),
    }),
    ("hurtbox", Hurtbox, {
        "ox": ("ox", _float, 0.0),
        "oy": ("oy", _float, 0.0),
        "w":  ("w",  _float, 0.8),
        "h":  ("h",  _float, 0.8),
    }),
    ("velocity", Velocity, {
        "x": ("x", _float, 0.0),
        "y": ("y", _float, 0.0),
    }),
    ("equipment", Equipment, {
        "weapon": ("weapon", _str, ""),
        "armor":  ("armor",  _str, ""),
    }),
    ("hunger", Hunger, {
        "current":    ("current",    _float, 80.0),
        "maximum":    ("maximum",    _float, 100.0),
        "rate":       ("rate",       _float, 0.03),
        "starve_dps": ("starve_dps", _float, 0.3),
    }),
    ("loot_table_ref", LootTableRef, {
        "table_name": ("table_name", _str, ""),
    }),
    ("faction", Faction, {
        "group":            ("group",            _str, "neutral"),
        "disposition":      ("disposition",      _str, "neutral"),
        "home_disposition": ("home_disposition", lambda v, d: _str(v, d), "__inherit__"),
        "alert_radius":     ("alert_radius",     _float, 150.0),
    }),
    ("dialogue", Dialogue, {
        "tree_id":   ("tree_id",   _str, ""),
        "greeting":  ("greeting",  _str, ""),
        "bark":      ("bark",      _str, ""),
        "can_trade": ("can_trade", _bool, False),
    }),
    ("ownership", Ownership, {
        "faction_group": ("faction_group", _str, "settlers"),
    }),
    ("locked", Locked, {
        "faction_access": ("faction_access", _str, "settlers"),
        "difficulty":     ("difficulty", lambda v, d: int(v) if v is not None else d, 1),
    }),
    ("spawn_info", SpawnInfo, {
        "zone":         ("zone",         _str, ""),
        "abstract":     ("abstract",     _bool, False),
        "spawn_radius": ("spawn_radius", _float, 8.0),
    }),
]


def _build_component(cls: type, field_map: dict, sub: dict, **overrides) -> Any:
    """Construct a component from its field_map and descriptor sub-dict."""
    kwargs: dict[str, Any] = {}
    for kwarg_name, (sub_key, cast_fn, default) in field_map.items():
        raw = sub.get(sub_key)
        if raw is None:
            kwargs[kwarg_name] = default
        else:
            try:
                kwargs[kwarg_name] = cast_fn(raw, default)
            except (TypeError, ValueError):
                kwargs[kwarg_name] = default
    # Fix faction home_disposition inheriting from disposition
    if "home_disposition" in kwargs and kwargs["home_disposition"] == "__inherit__":
        kwargs["home_disposition"] = kwargs.get("disposition", "neutral")
    kwargs.update(overrides)
    return cls(**kwargs)


def spawn_from_descriptor(world: World, desc: dict, zone: str) -> int:
    """Create an entity from a data descriptor dict.

    Works with both zone-file entity blocks and test_entities dicts.
    Returns the new entity ID.
    """
    eid = world.spawn()

    # ── Identity (special: fallback for flat dicts) ──────────────────
    if "identity" in desc and isinstance(desc["identity"], dict):
        d = desc["identity"]
        world.add(eid, Identity(
            name=d.get("name", "unnamed"),
            kind=d.get("kind", "npc"),
        ))
    else:
        name = desc.get("name") or desc.get("id") or f"entity_{eid}"
        kind = desc.get("kind") or "npc"
        world.add(eid, Identity(name=name, kind=kind))

    # ── Position (special: zone_add side-effect) ─────────────────────
    if "position" in desc and isinstance(desc["position"], dict):
        p = desc["position"]
        world.add(eid, Position(
            x=_float(p.get("x"), 0.0),
            y=_float(p.get("y"), 0.0),
            zone=zone,
        ))
        world.zone_add(eid, zone)
    elif "x" in desc and "y" in desc:
        try:
            world.add(eid, Position(x=float(desc["x"]), y=float(desc["y"]), zone=zone))
            world.zone_add(eid, zone)
        except Exception:
            pass

    # ── Table-driven simple components ───────────────────────────────
    for key, cls, field_map in _COMPONENT_TABLE:
        if key not in desc or not isinstance(desc[key], dict):
            continue
        sub = desc[key]
        comp = _build_component(cls, field_map, sub, **({"zone": zone} if key == "spawn_info" and "zone" not in sub else {}))
        world.add(eid, comp)

    # ── Hunger auto-attaches Needs ───────────────────────────────────
    if world.has(eid, Hunger) and not world.has(eid, Needs):
        world.add(eid, Needs())

    # ── Inventory (special: nested items dict) ───────────────────────
    if "inventory" in desc and isinstance(desc["inventory"], dict):
        inv_data = desc["inventory"]
        items = dict(inv_data["items"]) if isinstance(inv_data.get("items"), dict) else {}
        world.add(eid, Inventory(items=items))

    # ── Loot (special: list field) ───────────────────────────────────
    if "loot" in desc and isinstance(desc["loot"], dict):
        l = desc["loot"]
        world.add(eid, Loot(
            items=l.get("items", []),
            looted=_bool(l.get("looted"), False),
        ))

    # ── Simulation components (SubzonePos, Home, WorldMemory) ────
    if "subzone_pos" in desc and isinstance(desc["subzone_pos"], dict):
        sp = desc["subzone_pos"]
        world.add(eid, SubzonePos(
            zone=sp.get("zone", zone),
            subzone=sp.get("subzone", ""),
        ))

    if "home" in desc and isinstance(desc["home"], dict):
        h = desc["home"]
        world.add(eid, Home(
            zone=h.get("zone", zone),
            subzone=h.get("subzone", ""),
        ))

    if desc.get("world_memory", False):
        world.add(eid, WorldMemory())

    # ── Facing (auto-add for brain entities) ─────────────────────────
    if desc.get("_add_facing", False) or "brain" in desc:
        world.add(eid, Facing())

    # ── Brain + split components (backward-compat migration) ─────────
    _apply_brain_split(world, eid, desc)

    # ── Auto-add physics / defaults for combat entities ──────────────
    if desc.get("_add_collider") and not world.has(eid, Collider):
        world.add(eid, Collider())
    if desc.get("_add_hurtbox") and not world.has(eid, Hurtbox):
        world.add(eid, Hurtbox())
    if desc.get("_add_velocity") and not world.has(eid, Velocity):
        world.add(eid, Velocity())

    if world.has(eid, Health):
        if not world.has(eid, Collider):
            world.add(eid, Collider())
        if not world.has(eid, Hurtbox):
            world.add(eid, Hurtbox())
    if world.has(eid, Brain) and not world.has(eid, Velocity):
        world.add(eid, Velocity())

    # ── Lod (ensure exists) ──────────────────────────────────────────
    if not world.has(eid, Lod):
        world.add(eid, Lod(level="low"))

    return eid


# ── Brain-split helper ───────────────────────────────────────────────

def _apply_brain_split(world: World, eid: int, desc: dict) -> None:
    """Handle Brain + HomeRange + Threat + AttackConfig from descriptor.

    Supports both new-style (separate ``patrol``, ``threat``,
    ``attack_config`` keys) and old-style (everything in ``brain``).
    """
    # ── Brain ────────────────────────────────────────────────────────
    if "brain" in desc and isinstance(desc["brain"], dict):
        b = desc["brain"]
        world.add(eid, Brain(
            kind=b.get("kind", "wander"),
            active=_bool(b.get("active"), False),
        ))
    elif "brain" in desc and isinstance(desc["brain"], str):
        world.add(eid, Brain(kind=desc["brain"], active=False))
    else:
        return  # no brain → no patrol/threat/atk needed

    b = desc.get("brain", {})
    if isinstance(b, str):
        b = {}
    kind = b.get("kind", "wander")

    # ── HomeRange ───────────────────────────────────────────────────────
    if "home_range" in desc and isinstance(desc["home_range"], dict):
        p = desc["home_range"]
        world.add(eid, HomeRange(
            origin_x=_float(p.get("origin_x"), 0.0),
            origin_y=_float(p.get("origin_y"), 0.0),
            radius=_float(p.get("radius"), 5.0),
            speed=_float(p.get("speed"), 2.0),
        ))
    else:
        world.add(eid, HomeRange(
            radius=_float(b.get("patrol_radius"), 5.0),
            speed=_float(b.get("patrol_speed"), 2.0),
        ))

    # ── Threat ───────────────────────────────────────────────────────
    if "threat" in desc and isinstance(desc["threat"], dict):
        t = desc["threat"]
        world.add(eid, Threat(
            aggro_radius=_float(t.get("aggro_radius"), 5000.0),
            leash_radius=_float(t.get("leash_radius"), 200.0),
            flee_threshold=_float(t.get("flee_threshold"), 0.2),
            sensor_interval=_float(t.get("sensor_interval"), 0.1),
        ))
    elif kind in ("hostile_melee", "hostile_ranged", "guard"):
        world.add(eid, Threat(
            aggro_radius=_float(b.get("aggro_radius"), 5000.0),
            leash_radius=_float(b.get("leash_radius"), 200.0),
            flee_threshold=_float(b.get("flee_threshold"), 0.2),
        ))

    # ── AttackConfig ─────────────────────────────────────────────────
    if "attack_config" in desc and isinstance(desc["attack_config"], dict):
        ac = desc["attack_config"]
        world.add(eid, AttackConfig(
            attack_type=ac.get("attack_type", "melee"),
            range=_float(ac.get("range"), 1.2),
            cooldown=_float(ac.get("cooldown"), 0.5),
        ))
    elif kind in ("hostile_melee", "hostile_ranged", "guard"):
        atk_type = "ranged" if kind == "hostile_ranged" else "melee"
        world.add(eid, AttackConfig(
            attack_type=atk_type,
            range=_float(b.get("attack_range"), 1.2),
            cooldown=_float(b.get("attack_cooldown"), 0.5),
        ))


def spawn_zone_entities(world: World, zone: str, npcs_enabled: bool = True) -> list[int]:
    """Spawn all entities defined in the zone's spawn data.

    Skips spawning if any entity with SpawnInfo.zone == zone already exists
    (prevents duplicates on re-entry).
    Returns list of spawned entity IDs.
    """
    if not npcs_enabled:
        return []

    from core.zone import ZONE_SPAWNS

    # Check for existing entities in this zone
    for _eid, meta in world.all_of(SpawnInfo):
        if getattr(meta, "zone", None) == zone:
            return []

    spawns = ZONE_SPAWNS.get(zone) or []
    eids: list[int] = []
    for desc in spawns:
        # Inject meta if not provided so abstract/zone are set properly
        if "spawn_info" not in desc:
            has_pos = "position" in desc or ("x" in desc and "y" in desc)
            desc = {**desc, "spawn_info": {
                "zone": zone,
                "abstract": not has_pos,
                "spawn_radius": 8.0,
            }}
        eids.append(spawn_from_descriptor(world, desc, zone))
    return eids


# Test spawning moved to data/test_spawner.py — re-export for backward compat.
from data.test_spawner import spawn_test_entities, spawn_test_dummy  # noqa: F401
