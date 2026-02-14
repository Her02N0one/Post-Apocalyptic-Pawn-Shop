"""data/test_entities.py — Test-dummy definitions.

A test dummy is the *minimal* NPC archetype: health, position, identity,
a text-character sprite, collision, hurtbox, combat stats, and a Brain
(inactive by default).  Equipment slots exist but are empty.

Test dummies are explicitly **not** future NPCs — they exist so you can
spawn disposable targets to test combat, AI brains, loot, etc.  Real
NPCs will eventually extend a richer base-entity template with textures.
"""

# ── Dummy enemies ────────────────────────────────────────────────────

TEST_DUMMIES = {
    "raider": {
        "identity": {"name": "Raider", "kind": "dummy"},
        "health": {"current": 40.0, "maximum": 40.0},
        "sprite": {"char": "R", "color": (200, 80, 80), "layer": 5},
        "combat_stats": {"damage": 6.0, "defense": 1.0},
        "position": {"x": 10.0, "y": 10.0},
        "brain": {
            "kind": "hostile_melee", "active": True,
            "aggro_radius": 8.0, "attack_range": 1.3,
            "attack_cooldown": 0.6, "patrol_speed": 2.5,
            "flee_threshold": 0.15,
        },
        "equipment": {"weapon": "knife"},
        "faction": {"group": "raiders", "disposition": "hostile", "alert_radius": 10.0},
        "inventory": {"items": {"bandages": 1}},
    },
    "gunner": {
        "identity": {"name": "Gunner", "kind": "dummy"},
        "health": {"current": 25.0, "maximum": 25.0},
        "sprite": {"char": "G", "color": (100, 150, 200), "layer": 5},
        "combat_stats": {"damage": 4.0, "defense": 0.0},
        "position": {"x": 15.0, "y": 15.0},
        "brain": {
            "kind": "hostile_ranged", "active": True,
            "aggro_radius": 12.0, "attack_range": 8.0,
            "attack_cooldown": 0.9, "patrol_speed": 2.0,
            "flee_threshold": 0.25,
        },
        "equipment": {"weapon": "pistol"},
        "faction": {"group": "raiders", "disposition": "hostile", "alert_radius": 12.0},
    },
    "brute": {
        "identity": {"name": "Brute", "kind": "dummy"},
        "health": {"current": 100.0, "maximum": 100.0},
        "sprite": {"char": "B", "color": (160, 160, 100), "layer": 5},
        "combat_stats": {"damage": 10.0, "defense": 5.0},
        "position": {"x": 12.0, "y": 8.0},
        "brain": {
            "kind": "guard", "active": True,
            "aggro_radius": 5.0, "leash_radius": 8.0,
            "attack_range": 1.5, "attack_cooldown": 0.8,
            "patrol_speed": 1.8, "flee_threshold": 0.0,
        },
        "equipment": {"weapon": "bat"},
        "faction": {"group": "raiders", "disposition": "hostile", "alert_radius": 8.0},
        "inventory": {"items": {"canned_beans": 2}},
    },
}

# ── Containers (loot chests) ─────────────────────────────────────────

TEST_CONTAINERS = {
    "basic_chest": {
        "identity": {"name": "Wooden Chest", "kind": "container"},
        "sprite": {"char": "C", "color": (200, 150, 50), "layer": 3},
        "position": {"x": 20.0, "y": 20.0},
        "loot_table_ref": {"table_name": "basic_chest"},
    },
    "treasure_chest": {
        "identity": {"name": "Treasure Chest", "kind": "container"},
        "sprite": {"char": "$", "color": (255, 200, 100), "layer": 3},
        "position": {"x": 25.0, "y": 20.0},
        "loot_table_ref": {"table_name": "treasure_chest"},
    },
}

# ── Friendly / neutral NPCs ─────────────────────────────────────────

TEST_NPCS = {
    "trader": {
        "identity": {"name": "Dusty", "kind": "npc"},
        "health": {"current": 80.0, "maximum": 80.0},
        "sprite": {"char": "T", "color": (100, 200, 100), "layer": 5},
        "combat_stats": {"damage": 3.0, "defense": 2.0},
        "position": {"x": 5.0, "y": 5.0},
        "faction": {
            "group": "settlers", "disposition": "friendly",
            "home_disposition": "friendly", "alert_radius": 15.0,
        },
        "dialogue": {"tree_id": "trader_intro", "can_trade": True},
        "brain": {
            "kind": "wander", "active": True,
            "patrol_radius": 3.0, "patrol_speed": 1.0,
        },
        "inventory": {"items": {"bandages": 3, "canned_beans": 5, "knife": 1, "pistol": 1}},
        "equipment": {"weapon": ""},
    },
    "settler": {
        "identity": {"name": "Jess", "kind": "npc"},
        "health": {"current": 50.0, "maximum": 50.0},
        "sprite": {"char": "J", "color": (150, 180, 150), "layer": 5},
        "combat_stats": {"damage": 5.0, "defense": 1.0},
        "position": {"x": 7.0, "y": 5.0},
        "faction": {
            "group": "settlers", "disposition": "friendly",
            "home_disposition": "friendly", "alert_radius": 12.0,
        },
        "dialogue": {"tree_id": "settler_generic"},
        "brain": {
            "kind": "wander", "active": True,
            "patrol_radius": 4.0, "patrol_speed": 1.2,
        },
        "equipment": {"weapon": "knife"},
    },
}

