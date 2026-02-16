"""systems/engine/prefabs.py — Prefab-based entity library.

Prefabs are dict-based entity templates arranged in an inheritance
hierarchy via ``__parent__`` chains.  ``resolve_prefab(name)`` walks
the chain and deep-merges to produce a flat descriptor dict that
``spawn_from_descriptor`` can process.

Zone JSON files and code-side helpers reference a prefab by name;
the factory resolves it, merges the caller's overrides on top, then
the existing table-driven spawn path takes over.

Hierarchy
---------
::

    physical            collider, facing
    ├── prop            static world object (barrel, sign, rubble)
    │   └── container   lootable chest / crate
    ├── dummy           pushable + punchable passive target
    ├── creature        mobile entity with brain & health
    │   ├── humanoid    talks, trades, eats, has inventory
    │   │   ├── guard   armed settler defender
    │   │   ├── raider  hostile melee human
    │   │   ├── gunner  hostile ranged human
    │   │   ├── trader  friendly merchant
    │   │   └── settler friendly civilian
    │   └── beast       hostile animal (no social components)
"""

from __future__ import annotations


# ── Deep-merge helper ────────────────────────────────────────────────

def _deep_merge(base: dict, overlay: dict) -> dict:
    """Deep-merge *overlay* on top of *base*; overlay wins on conflicts."""
    result = dict(base)
    for key, val in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


# ── Prefab registry ──────────────────────────────────────────────────
#
# Each entry is a partial descriptor dict.  ``__parent__`` names the
# base prefab to inherit from (recursive).  Fields in a child override
# or extend the parent via deep-merge.

PREFABS: dict[str, dict] = {

    # ── Base layer ───────────────────────────────────────────────────
    "physical": {
        "collider": {"width": 0.8, "height": 0.8, "solid": True},
    },

    # ── Props (static world objects) ─────────────────────────────────
    "prop": {
        "__parent__": "physical",
        "identity": {"kind": "object"},
        "sprite": {"char": ".", "color": [150, 150, 150], "layer": 3},
    },
    "container": {
        "__parent__": "prop",
        "identity": {"kind": "container"},
        "sprite": {"char": "C", "color": [200, 150, 50], "layer": 3},
    },

    # ── Dummies (pushable / punchable targets) ───────────────────────
    "dummy": {
        "__parent__": "physical",
        "identity": {"kind": "dummy"},
        "sprite": {"char": "D", "color": [200, 200, 200], "layer": 5},
        "health": {"current": 999.0, "maximum": 999.0},
        "hurtbox": {},
        "pushable": {"friction": 5.0},
        "persist": {},
    },

    # ── Creatures (mobile entities with brains) ──────────────────────
    "creature": {
        "__parent__": "physical",
        "identity": {"kind": "npc"},
        "sprite": {"layer": 5},
        "health": {"current": 100.0, "maximum": 100.0},
        "hurtbox": {},
        "combat_stats": {"damage": 5.0, "defense": 0.0},
        "brain": {"kind": "wander", "active": True},
        "home_range": {"radius": 6.0, "speed": 2.0},
    },

    # ── Humanoids (creatures that talk, trade, eat) ──────────────────
    "humanoid": {
        "__parent__": "creature",
        "faction": {"group": "neutral", "disposition": "neutral"},
        "dialogue": {},
        "hunger": {"current": 80.0, "maximum": 100.0, "rate": 0.03},
        "equipment": {},
        "inventory": {"items": {}},
    },

    # ── Hostile archetypes ───────────────────────────────────────────
    "raider": {
        "__parent__": "humanoid",
        "brain": {"kind": "hostile_melee", "active": True},
        "faction": {"group": "raiders", "disposition": "hostile"},
        "combat_stats": {"damage": 10.0, "defense": 2.0},
        "threat": {"aggro_radius": 8.0, "leash_radius": 15.0},
        "attack_config": {"attack_type": "melee", "range": 1.2, "cooldown": 0.5},
    },
    "gunner": {
        "__parent__": "humanoid",
        "brain": {"kind": "hostile_ranged", "active": True},
        "faction": {"group": "raiders", "disposition": "hostile"},
        "combat_stats": {"damage": 4.0, "defense": 0.0},
        "threat": {"aggro_radius": 12.0, "leash_radius": 20.0},
        "attack_config": {"attack_type": "ranged", "range": 8.0, "cooldown": 0.9},
    },

    # ── Friendly archetypes ──────────────────────────────────────────
    "guard": {
        "__parent__": "humanoid",
        "brain": {"kind": "guard", "active": True},
        "faction": {"group": "settlers", "disposition": "neutral"},
        "combat_stats": {"damage": 8.0, "defense": 3.0},
        "threat": {"aggro_radius": 10.0, "leash_radius": 20.0},
        "attack_config": {"attack_type": "melee", "range": 1.2, "cooldown": 0.5},
    },
    "trader": {
        "__parent__": "humanoid",
        "faction": {"group": "settlers", "disposition": "friendly"},
        "dialogue": {"can_trade": True},
    },
    "settler": {
        "__parent__": "humanoid",
        "faction": {"group": "settlers", "disposition": "friendly"},
    },

    # ── Beasts (hostile animals, no social components) ───────────────
    "beast": {
        "__parent__": "creature",
        "brain": {"kind": "hostile_melee", "active": True},
        "threat": {"aggro_radius": 8.0, "leash_radius": 15.0},
        "attack_config": {"attack_type": "melee", "range": 1.2, "cooldown": 0.5},
    },
}


# ── Resolution ───────────────────────────────────────────────────────

def resolve_prefab(name: str) -> dict:
    """Walk the ``__parent__`` chain and return a fully-merged descriptor.

    Raises ``KeyError`` if *name* is not in the registry.
    """
    if name not in PREFABS:
        raise KeyError(f"Unknown prefab: {name!r}")

    chain: list[dict] = []
    current: str | None = name
    seen: set[str] = set()

    while current:
        if current in seen:
            raise ValueError(f"Circular prefab inheritance: {current!r}")
        seen.add(current)
        prefab = PREFABS[current]
        chain.append(prefab)
        current = prefab.get("__parent__")

    # Merge from root → leaf (leaf wins)
    result: dict = {}
    for prefab in reversed(chain):
        overlay = {k: v for k, v in prefab.items() if k != "__parent__"}
        result = _deep_merge(result, overlay)
    return result
