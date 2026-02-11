"""components — ECS component dataclasses, organised by domain.

Submodules
----------
spatial        Position, Velocity, Collider, Facing, Hurtbox
rendering      Identity, Sprite, HitFlash
rpg            Health, Hunger, Inventory, Equipment
combat         Combat, Loot, LootTableRef, Projectile
ai             Brain, Task
resources      Camera, Meta, Lod, ZoneMetadata, Player
item_registry  ItemRegistry

All public names are re-exported here so existing code that does
``from components import Position`` continues to work unchanged.
"""

# ── Spatial ──────────────────────────────────────────────────────────
from components.spatial import Position, Velocity, Collider, Facing, Hurtbox

# ── Rendering ────────────────────────────────────────────────────────
from components.rendering import Identity, Sprite, HitFlash

# ── RPG ──────────────────────────────────────────────────────────────
from components.rpg import Health, Hunger, Needs, Inventory, Equipment

# ── Combat ───────────────────────────────────────────────────────────
from components.combat import Combat, Loot, LootTableRef, Projectile

# ── AI ───────────────────────────────────────────────────────────────
from components.ai import Brain, Patrol, Threat, AttackConfig, Task, Memory, GoalSet

# ── Social ───────────────────────────────────────────────────────────
from components.social import Faction, Dialogue, Ownership, CrimeRecord, Locked

# ── World resources / singletons ─────────────────────────────────────
from components.resources import Camera, GameClock, Meta, Lod, ZoneMetadata, Player

# ── Registries ───────────────────────────────────────────────────────
from components.item_registry import ItemRegistry

# ── Simulation ───────────────────────────────────────────────────────
from components.simulation import (
    SubzonePos, TravelPlan, Home, Stockpile, MemoryEntry, WorldMemory,
)

__all__ = [
    # spatial
    "Position", "Velocity", "Collider", "Facing", "Hurtbox",
    # rendering
    "Identity", "Sprite", "HitFlash",
    # rpg
    "Health", "Hunger", "Needs", "Inventory", "Equipment",
    # combat
    "Combat", "Loot", "LootTableRef", "Projectile",
    # ai
    "Brain", "Patrol", "Threat", "AttackConfig", "Task", "Memory", "GoalSet",
    # social
    "Faction", "Dialogue", "Ownership", "CrimeRecord", "Locked",
    # resources
    "Camera", "GameClock", "Meta", "Lod", "ZoneMetadata", "Player",
    # registries
    "ItemRegistry",
    # simulation
    "SubzonePos", "TravelPlan", "Home", "Stockpile",
    "MemoryEntry", "WorldMemory",
]
