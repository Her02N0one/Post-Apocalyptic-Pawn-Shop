"""systems — ECS game-logic systems.

Each module provides functions or classes that operate on the ECS World,
typically called once per frame or on specific events.

Modules
-------
physics         Tile-collision movement system
pathfinding     A*, BFS flood-fill, line-of-sight
gameplay        Unified interact dispatch + platform interaction
interaction     Nearby-entity detection + facing preference
spawner         Entity creation from data descriptors
beast_spawner   Periodic hostile-creature spawning
combat_sim      Off-screen stat-check combat
zone_sim        Off-screen zone simulation (NPC movement, portals)
lod             Level-of-detail entity promote / demote
item_registry   Item template lookup from items.toml
dialogue_gen    Contextual NPC dialogue tree generation
loot            Loot table rolling
containers      Container, inventory, and NPC dialogue modals
items           Ground-item pickup and spawning

Note
----
Rendering infrastructure (raycaster, ray_renderer, textures) lives in
the ``engine`` package.
"""
