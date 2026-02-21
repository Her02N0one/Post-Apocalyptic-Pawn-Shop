"""core/save.py — Save/load using component _persist flags.

Only components with ``_persist = True`` are serialised.  Everything
else is rebuilt from zone data on load (sprites, colliders, etc.).

Save format: JSON dict with:
  - "zone": current zone name
  - "clock": game clock time
  - "entities": list of {eid, components...}

Each component is stored under its class name as a flat dict.

    from core.save import save_game, load_game
    save_game(world, "playground", slot=1)
    data = load_game(slot=1)
"""

from __future__ import annotations

import json
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any, TYPE_CHECKING

from core.ecs import Component

if TYPE_CHECKING:
    from core.ecs import World

from core.paths import SAVES_DIR

# ── Registry: component class name → class ───────────────────────────
# Populated at import time from components.__init__

_COMPONENT_REGISTRY: dict[str, type[Component]] = {}


def _ensure_registry() -> None:
    """Lazy-populate the registry on first use."""
    if _COMPONENT_REGISTRY:
        return
    import components as c
    for name in dir(c):
        obj = getattr(c, name)
        if (isinstance(obj, type) and issubclass(obj, Component)
                and obj is not Component):
            _COMPONENT_REGISTRY[name] = obj


# ── Serialisation helpers ────────────────────────────────────────────

def _component_to_dict(comp: Component) -> dict[str, Any]:
    """Serialise a component to a JSON-safe dict."""
    d = asdict(comp)  # type: ignore[arg-type]
    # Convert enums to their name string
    for f in fields(comp):
        val = d.get(f.name)
        if hasattr(val, "name") and hasattr(val, "value"):
            d[f.name] = val.name
    return d


def _component_from_dict(cls: type[Component], data: dict[str, Any]) -> Component:
    """Deserialise a component from a dict, converting enum strings back."""
    from core.types import Direction, EntityKind

    enum_map: dict[str, type] = {
        "direction": Direction,
        "kind": EntityKind,
    }

    kwargs: dict[str, Any] = {}
    for f in fields(cls):
        if f.name in data:
            val = data[f.name]
            # Reconvert enum strings
            enum_cls = enum_map.get(f.name)
            if enum_cls is not None and isinstance(val, str):
                try:
                    val = enum_cls[val]
                except KeyError:
                    print(f"[SAVE] Unknown enum '{val}' for {f.name}, skipping")
                    continue
            kwargs[f.name] = val
    return cls(**kwargs)


# ── Save ─────────────────────────────────────────────────────────────

def save_game(world: "World", zone: str, slot: int = 0, *,
              visited_zones: set[str] | None = None) -> Path:
    """Persist all _persist=True components to a save file.

    Returns the path written.
    """
    from components import GameClock, WorldClock

    SAVES_DIR.mkdir(parents=True, exist_ok=True)
    _ensure_registry()

    clock = world.resources.try_get(GameClock)
    clock_time = clock.time if clock else 0.0

    # WorldClock data
    wc = world.resources.try_get(WorldClock)
    wc_data = None
    if wc:
        wc_data = {
            "real_time": wc.real_time,
            "world_time": wc.world_time,
            "day": wc.day,
            "day_phase": wc.day_phase,
        }

    entities: list[dict[str, Any]] = []

    # Collect entities that have at least one persistent component
    all_eids: set[int] = set()
    for store in world._stores.values():
        all_eids.update(store.keys())
    all_eids -= world._dead

    for eid in sorted(all_eids):
        entry: dict[str, Any] = {"eid": eid}
        has_persist = False
        for comp_type, store in world._stores.items():
            comp = store.get(eid)
            if comp is None:
                continue
            if not comp_type._persist:
                continue
            has_persist = True
            entry[comp_type.__name__] = _component_to_dict(comp)
        if has_persist:
            entities.append(entry)

    save_data = {
        "zone": zone,
        "clock": clock_time,
        "world_clock": wc_data,
        "visited_zones": sorted(visited_zones) if visited_zones else [zone],
        "entities": entities,
    }

    path = SAVES_DIR / f"slot_{slot}.json"
    try:
        with open(path, "w") as f:
            json.dump(save_data, f, indent=2)
    except OSError as exc:
        print(f"[SAVE] Failed to write {path.name}: {exc}")
        return path  # return path even on failure so caller has it

    return path


# ── Load ─────────────────────────────────────────────────────────────

def load_game(slot: int = 0) -> dict[str, Any] | None:
    """Load raw save data from a slot.  Returns None if no save exists."""
    path = SAVES_DIR / f"slot_{slot}.json"
    if not path.exists():
        return None
    try:
        with open(path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[SAVE] Failed to load {path.name}: {exc}")
        return None
    if not isinstance(data, dict):
        print(f"[SAVE] Corrupt save: expected dict, got {type(data).__name__}")
        return None
    return data


def restore_entity(world: "World", entry: dict[str, Any]) -> int:
    """Restore an entity's persistent components from save data.

    Creates a new entity and attaches all recognised persistent
    components.  Returns the new entity ID.

    Non-persistent components (Sprite, Collider, etc.) must be
    rebuilt separately from zone data or prefabs.
    """
    _ensure_registry()
    eid = world.spawn()

    for key, val in entry.items():
        if key == "eid":
            continue
        cls = _COMPONENT_REGISTRY.get(key)
        if cls is None:
            continue
        comp = _component_from_dict(cls, val)
        world.add(eid, comp)

    return eid


def has_save(slot: int = 0) -> bool:
    """Check if a save file exists for the given slot."""
    return (SAVES_DIR / f"slot_{slot}.json").exists()


def delete_save(slot: int = 0) -> None:
    """Delete a save file."""
    path = SAVES_DIR / f"slot_{slot}.json"
    if path.exists():
        path.unlink()
