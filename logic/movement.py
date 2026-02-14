"""logic/movement.py — Physics / movement system.

Moves entities with Position+Velocity, resolves tile collisions
(wall-sliding) and simple entity-vs-entity overlap rejection.
"""

from __future__ import annotations
from core.ecs import World
from components import Position, Velocity, Player, Collider, Lod
from core.collision import aabb_hits_wall, HITBOX_W, HITBOX_H


def movement_system(world: World, dt: float, tiles: list[list[int]]):
    """Move entities, prevent movement into wall tiles, handle collisions.

    - Walls are tile id 6 (TILE_WALL).
    - Entities with ``Collider`` participate in entity-entity checks.
    """
    # Build quick lookup of collidable entities
    colliders = {}
    for oid, opos, oc in world.query(Position, Collider):
        colliders[oid] = (opos, oc)

    h = len(tiles)
    w = len(tiles[0]) if h else 0

    # Process movement
    for eid, pos, vel in world.query(Position, Velocity):
        # Only move players and same-zone (high/medium) LOD NPCs
        if not world.has(eid, Player):
            lod = world.get(eid, Lod)
            if lod is not None and lod.level == "low":
                vel.x = 0.0
                vel.y = 0.0
                continue

        nx = pos.x + vel.x * dt
        ny = pos.y + vel.y * dt

        # Axis-separated tile collision — allows wall-sliding
        if aabb_hits_wall(nx, pos.y, HITBOX_W, HITBOX_H, h, w, tiles):
            nx = pos.x
            vel.x = 0.0
        if aabb_hits_wall(nx, ny, HITBOX_W, HITBOX_H, h, w, tiles):
            ny = pos.y
            vel.y = 0.0

        # Entity collisions (simple overlap rejection)
        if eid in colliders:
            mypos, mycol = colliders[eid]
            collide = False
            for oid, (opos, oc) in colliders.items():
                if oid == eid:
                    continue
                if not world.alive(oid):
                    continue
                if opos.zone != pos.zone:
                    continue
                dx = nx - opos.x
                dy = ny - opos.y
                min_dist = (mycol.width + oc.width) * 0.5
                if dx * dx + dy * dy < (min_dist * min_dist):
                    collide = True
                    break
            if collide:
                nx = pos.x
                ny = pos.y
                vel.x = 0.0
                vel.y = 0.0

        # Commit movement
        pos.x = nx
        pos.y = ny

        # Knockback friction (post-commit)
        if not world.has(eid, Player):
            vel.x *= 0.85
            vel.y *= 0.85
            if abs(vel.x) < 0.05:
                vel.x = 0.0
            if abs(vel.y) < 0.05:
                vel.y = 0.0
