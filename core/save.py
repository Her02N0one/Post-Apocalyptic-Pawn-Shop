"""core/save.py — Game state persistence (format version 3).

Only **dynamic** component data is saved.  Static data (sprite colour,
dialogue barks, collider shape, etc.) comes from zone templates and is
loaded by ID when the zone spawns entities.  This keeps save files
small and means you can iterate on template data without invalidating
saves.

Save format (JSON)
------------------
.. code-block:: json

    {
        "format_version": 3,
        "current_zone": "playground",
        "entities": {
            "player": {
                "Position": {"x": 5.0, "y": 10.0, "zone": "playground"},
                "Health":   {"current": 95, "maximum": 100},
                ...
            },
            "dummy_bob": {
                "Position": {"x": 12.0, "y": 8.0, "zone": "playground"},
                ...
            }
        }
    }

The entity key is ``Persist.uid``.  On load, entities are first spawned
from their zone template (which provides all static data), then any
saved dynamic fields are overlaid on top.
"""

from __future__ import annotations
import dataclasses
import json
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from core.app import App
    from core.ecs import World

SAVES_DIR = Path("saves")
FORMAT_VERSION = 3

# ── Static / dynamic split ───────────────────────────────────────────
#
# Static components come from zone templates (loaded by entity ID).
# They are **not** written to save files — only dynamic state is saved.
# If you add a new component that holds mutable game state, make sure
# it is NOT listed here so it gets saved automatically.

STATIC_COMPONENTS: frozenset[str] = frozenset({
    # Appearance — loaded from template
    "Sprite",
    # Dialogue / quest hooks — loaded from template
    "Dialogue",
    # Physics shape — loaded from template
    "Collider", "Hurtbox", "Pushable",
    # Base attack config — loaded from template
    "AttackConfig",
    # Loot / ownership — loaded from template
    "LootTableRef", "Ownership", "Locked", "Loot",
    # AI pathing / perception config — loaded from template
    "HomeRange", "Threat", "VisionCone",
    # Identity — name/kind come from template
    "Identity",
    # Spawn bookkeeping — template only
    "SpawnInfo",
    # Transient runtime state — reconstructed each session
    "Velocity", "Facing", "Lod", "HitFlash", "Needs",
})


# ── Component registry ───────────────────────────────────────────────
#
# Maps ``ClassName`` → class for every known component type.
# Populated lazily on first use from the ``components`` package.

_COMPONENT_REGISTRY: dict[str, type] = {}
_REGISTRY_READY = False


def _ensure_registry() -> None:
    """Lazily populate the component registry from the components package."""
    global _REGISTRY_READY
    if _REGISTRY_READY:
        return
    import components as _pkg
    import components.spatial
    import components.rendering
    import components.rpg
    import components.combat
    import components.ai
    import components.social
    import components.resources
    import components.offscreen

    _modules = [
        _pkg,
        components.spatial,
        components.rendering,
        components.rpg,
        components.combat,
        components.ai,
        components.social,
        components.resources,
        components.offscreen,
    ]
    for mod in _modules:
        for name in dir(mod):
            obj = getattr(mod, name)
            if isinstance(obj, type) and dataclasses.is_dataclass(obj):
                _COMPONENT_REGISTRY[obj.__name__] = obj
    _REGISTRY_READY = True


# ── Serialisation helpers ─────────────────────────────────────────────

def _serialise_value(val: Any) -> Any:
    """Convert a Python value to a JSON-safe representation."""
    if isinstance(val, tuple):
        return list(val)
    if isinstance(val, dict):
        return {str(k): _serialise_value(v) for k, v in val.items()}
    if isinstance(val, list):
        return [_serialise_value(v) for v in val]
    if dataclasses.is_dataclass(val) and not isinstance(val, type):
        return serialise_component(val)
    if isinstance(val, (int, float, str, bool, type(None))):
        return val
    # Fallback: convert to string
    return str(val)


def serialise_component(comp: Any) -> dict[str, Any]:
    """Serialise a single dataclass component to a plain dict."""
    d: dict[str, Any] = {}
    for f in dataclasses.fields(comp):
        d[f.name] = _serialise_value(getattr(comp, f.name))
    return d


def deserialise_component(cls: type, data: dict[str, Any]) -> Any:
    """Create a dataclass component instance from a serialised dict."""
    valid_fields = {f.name: f for f in dataclasses.fields(cls)}
    kwargs: dict[str, Any] = {}
    for key, val in data.items():
        if key not in valid_fields:
            continue
        f = valid_fields[key]
        # tuple coercion: if the field's default is a tuple, convert
        default = f.default
        if default is dataclasses.MISSING:
            default = None
        if isinstance(val, list) and isinstance(default, tuple):
            val = tuple(val)
        kwargs[key] = val
    return cls(**kwargs)


# ── Entity serialisation ─────────────────────────────────────────────

def serialise_entity(world: "World", eid: int) -> dict[str, dict]:
    """Serialise the *dynamic* components of entity *eid*.

    Static components (listed in ``STATIC_COMPONENTS``) are skipped —
    they come from zone templates and don't need saving.
    Returns ``{ClassName: {fields}}``.
    """
    _ensure_registry()
    result: dict[str, dict] = {}
    for cls_name, cls in _COMPONENT_REGISTRY.items():
        if cls_name in STATIC_COMPONENTS:
            continue
        comp = world.get(eid, cls)
        if comp is not None:
            result[cls_name] = serialise_component(comp)
    return result


def deserialise_entity(world: "World", components_data: dict[str, dict]) -> int:
    """Create a new entity from serialised component data. Returns eid."""
    _ensure_registry()
    eid = world.spawn()
    for cls_name, fields in components_data.items():
        cls = _COMPONENT_REGISTRY.get(cls_name)
        if cls is None:
            continue
        comp = deserialise_component(cls, fields)
        world.add(eid, comp)
    # Register in zone spatial index if Position present
    from components import Position
    pos = world.get(eid, Position)
    if pos:
        world.zone_add(eid, pos.zone)
    return eid


# ── Save / Load ──────────────────────────────────────────────────────

def get_save_file(slot: int = 0) -> Path:
    """Get the path for a save slot."""
    SAVES_DIR.mkdir(parents=True, exist_ok=True)
    return SAVES_DIR / f"slot{slot}.json"


def save_game_state(app: "App", slot: int = 0) -> Path:
    """Save current game state to disk.

    Iterates all entities with a ``Persist`` component and serialises
    every component attached to them.
    """
    from components import Persist, GameClock

    save_path = get_save_file(slot)

    # Determine current zone from the active scene
    current_zone = "playground"
    if getattr(app, "_scenes", None):
        scene = app._scenes[-1]
        if hasattr(scene, "zone"):
            current_zone = scene.zone

    # Serialise all persistent entities
    entities_data: dict[str, dict] = {}
    for eid, persist in app.world.all_of(Persist):
        if not persist.uid:
            continue
        entities_data[persist.uid] = serialise_entity(app.world, eid)

    save_data = {
        "format_version": FORMAT_VERSION,
        "current_zone": current_zone,
        "entities": entities_data,
    }

    with open(save_path, "w") as f:
        json.dump(save_data, f, indent=2)
        f.write("\n")

    return save_path


def load_game_state(app: "App | None" = None, slot: int = 0) -> dict[str, Any] | None:
    """Load game state from a save file.

    Returns the raw dict or ``None`` if no save exists.
    """
    save_path = get_save_file(slot)
    if not save_path.exists():
        return None
    try:
        with open(save_path) as f:
            return json.load(f)
    except Exception as ex:
        print(f"[SAVE] Error loading save: {ex}")
        return None


def restore_entities(world: "World", save_data: dict[str, Any]) -> dict[str, int]:
    """Recreate all entities from a save dict.

    Returns ``{uid: eid}`` mapping for caller convenience.
    """
    uid_to_eid: dict[str, int] = {}
    for uid, comp_data in save_data.get("entities", {}).items():
        eid = deserialise_entity(world, comp_data)
        uid_to_eid[uid] = eid
    return uid_to_eid


def apply_zone_saves(world: "World", save_data: dict[str, Any] | None) -> int:
    """Overlay saved dynamic data onto zone-spawned entities.

    After ``spawn_zone_entities`` creates entities from templates, call
    this to restore any saved mutable state (position, health, etc.).

    Only touches non-player ``Persist``-tagged entities whose uid
    appears in *save_data*.  Returns the number of entities updated.
    """
    if not save_data:
        return 0
    _ensure_registry()
    entities = save_data.get("entities", {})
    if not entities:
        return 0

    from components import Persist, Position

    count = 0
    for eid, persist in world.all_of(Persist):
        if not persist.uid or persist.uid == "player":
            continue
        saved = entities.get(persist.uid)
        if not saved:
            continue
        # Overlay each saved dynamic component onto the template entity
        for cls_name, fields in saved.items():
            if cls_name in STATIC_COMPONENTS:
                continue  # template data — don't touch
            cls = _COMPONENT_REGISTRY.get(cls_name)
            if cls is None:
                continue
            comp = deserialise_component(cls, fields)
            if world.has(eid, cls):
                world.remove(eid, cls)
            world.add(eid, comp)
        # Update zone spatial index if Position was changed
        pos = world.get(eid, Position)
        if pos:
            world.zone_set(eid, pos.zone)
        count += 1
    return count
