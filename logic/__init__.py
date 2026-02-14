"""logic — Game systems package.

Subpackages
-----------
combat/     — damage, attacks, projectiles, engagement FSM, targeting, movement
ai/         — brain registry, perception, steering, defense,
              wander/villager brain implementations
actions/    — player action handlers (attacks, interact, inventory)

Top-level modules
-----------------
tick            — per-frame system orchestrator (+ input & pickup systems)
entity_factory  — entity creation from TOML data
lod             — LOD promotion/demotion
pathfinding     — A* navigation
movement        — physics / collision
input_manager   — raw input → intent mapping
needs           — NPC hunger, eating, food production
crime           — crime & law system
dialogue        — dialogue trees + quest tracking
loot_tables     — loot table manager
particles       — VFX particle simulation
"""
