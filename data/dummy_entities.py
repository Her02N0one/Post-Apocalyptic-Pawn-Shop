"""data/dummy_entities.py — Test-dummy definitions.

Descriptor dicts consumed by ``spawn_from_descriptor``.  Each entry
may specify a ``prefab`` key to inherit from the prefab hierarchy and
only list overrides.

Test dummies are explicitly **not** future NPCs — they exist so you can
spawn disposable targets to test combat, AI brains, loot, etc.  Real
NPCs will eventually extend a richer base-entity template with textures.
"""

# ── Dummy enemies ────────────────────────────────────────────────────

TEST_DUMMIES = {
    "raider": {
        "prefab": "raider",
        "identity": {"name": "Raider"},
        "health": {"current": 40.0, "maximum": 40.0},
        "sprite": {"char": "R", "color": (200, 80, 80)},
        "combat_stats": {"damage": 6.0, "defense": 1.0},
        "position": {"x": 10.0, "y": 10.0},
        "threat": {"aggro_radius": 8.0, "leash_radius": 15.0,
                   "flee_threshold": 0.15},
        "attack_config": {"cooldown": 0.6},
        "home_range": {"speed": 2.5},
        "equipment": {"weapon": "knife"},
        "inventory": {"items": {"bandages": 1}},
    },
    "gunner": {
        "prefab": "gunner",
        "identity": {"name": "Gunner"},
        "health": {"current": 25.0, "maximum": 25.0},
        "sprite": {"char": "G", "color": (100, 150, 200)},
        "position": {"x": 15.0, "y": 15.0},
        "threat": {"aggro_radius": 12.0, "leash_radius": 20.0,
                   "flee_threshold": 0.25},
        "attack_config": {"cooldown": 0.9},
        "home_range": {"speed": 2.0},
        "equipment": {"weapon": "pistol"},
    },
    "brute": {
        "prefab": "guard",
        "identity": {"name": "Brute"},
        "health": {"current": 100.0, "maximum": 100.0},
        "sprite": {"char": "B", "color": (160, 160, 100)},
        "combat_stats": {"damage": 10.0, "defense": 5.0},
        "position": {"x": 12.0, "y": 8.0},
        "brain": {"kind": "guard", "active": True},
        "faction": {"group": "raiders", "disposition": "hostile"},
        "threat": {"aggro_radius": 5.0, "leash_radius": 8.0,
                   "flee_threshold": 0.0},
        "attack_config": {"range": 1.5, "cooldown": 0.8},
        "home_range": {"speed": 1.8},
        "equipment": {"weapon": "bat"},
        "inventory": {"items": {"canned_beans": 2}},
    },
}

# ── Containers (loot chests) ─────────────────────────────────────────

TEST_CONTAINERS = {
    "basic_chest": {
        "prefab": "container",
        "identity": {"name": "Wooden Chest"},
        "position": {"x": 20.0, "y": 20.0},
        "loot_table_ref": {"table_name": "basic_chest"},
    },
    "treasure_chest": {
        "prefab": "container",
        "identity": {"name": "Treasure Chest"},
        "sprite": {"char": "$", "color": (255, 200, 100)},
        "position": {"x": 25.0, "y": 20.0},
        "loot_table_ref": {"table_name": "treasure_chest"},
    },
}

# ── Friendly / neutral NPCs ─────────────────────────────────────────

TEST_NPCS = {
    "trader": {
        "prefab": "trader",
        "identity": {"name": "Dusty"},
        "health": {"current": 80.0, "maximum": 80.0},
        "sprite": {"char": "T", "color": (100, 200, 100)},
        "combat_stats": {"damage": 3.0, "defense": 2.0},
        "position": {"x": 5.0, "y": 5.0},
        "faction": {"home_disposition": "friendly", "alert_radius": 15.0},
        "dialogue": {"tree_id": "trader_intro", "can_trade": True},
        "home_range": {"radius": 3.0, "speed": 1.0},
        "inventory": {"items": {"bandages": 3, "canned_beans": 5, "knife": 1, "pistol": 1}},
    },
    "settler": {
        "prefab": "settler",
        "identity": {"name": "Jess"},
        "health": {"current": 50.0, "maximum": 50.0},
        "sprite": {"char": "J", "color": (150, 180, 150)},
        "combat_stats": {"damage": 5.0, "defense": 1.0},
        "position": {"x": 7.0, "y": 5.0},
        "faction": {"home_disposition": "friendly", "alert_radius": 12.0},
        "dialogue": {"tree_id": "settler_generic"},
        "home_range": {"radius": 4.0, "speed": 1.2},
        "equipment": {"weapon": "knife"},
    },
}

