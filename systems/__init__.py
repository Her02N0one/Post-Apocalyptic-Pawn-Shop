"""systems — Game mechanics and rendering systems.

Modules
-------
raycaster       Pure-Python DDA wall-casting
ray_renderer    Python wrapper for C raycaster (_ray_render)
textures        Tile texture atlas loading / caching
physics         Tile-collision movement system
pathfinding     A*, BFS flood-fill, line-of-sight
gameplay        Item pickup, containers, loot, inventory
interaction     Nearby-entity detection + facing preference
spawner         Entity creation from data descriptors
beast_spawner   Periodic hostile-creature spawning
combat_sim      Off-screen stat-check combat
zone_sim        Off-screen zone simulation (NPC movement, portals)
lod             Level-of-detail entity promote / demote
item_registry   Item template lookup from items.toml
dialogue_gen    Contextual NPC dialogue tree generation
"""
