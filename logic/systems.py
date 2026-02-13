"""logic/systems.py — Game systems

A system is just a function that takes the World and does something
to components. Call them from your scene's update() method.
"""

from __future__ import annotations
from core.ecs import World
import math
from components import Position, Identity, Player, Collider, Velocity, Lod, Inventory, Facing
from core.constants import TILE_WALL

# ── Tile-collision helpers ───────────────────────────────────────────
# Entity occupies an axis-aligned box of this size (tile units).
# Matches PLAYER_SIZE (0.8) used elsewhere in the codebase.
HITBOX_W = 0.8
HITBOX_H = 0.8


def _aabb_hits_wall(x: float, y: float, bw: float, bh: float,
                    map_h: int, map_w: int,
                    tiles: list[list[int]]) -> bool:
    """Return True if the box (x,y)→(x+bw, y+bh) overlaps a wall or OOB."""
    min_c = int(math.floor(x))
    max_c = int(math.floor(x + bw - 0.001))
    min_r = int(math.floor(y))
    max_r = int(math.floor(y + bh - 0.001))
    for r in range(min_r, max_r + 1):
        for c in range(min_c, max_c + 1):
            if r < 0 or r >= map_h or c < 0 or c >= map_w:
                return True
            if tiles[r][c] == TILE_WALL:
                return True
    return False


def movement_system(world: World, dt: float, tiles: list[list[int]]):
    """Move entities with `Position`+`Velocity`, prevent movement into wall tiles
    and simple entity collisions.

    - Walls are tile id 6.
    - Entities with `Collider` participate in collision checks.
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
                # low LOD (different zone) entities don't move
                vel.x = 0.0
                vel.y = 0.0
                continue

        # Knockback friction: applied AFTER position update below so
        # that brain-driven velocity is used at full strength for the
        # current frame.  The dampening only reduces residual velocity
        # (e.g. knockback) that isn't overwritten by the brain next frame.

        nx = pos.x + vel.x * dt
        ny = pos.y + vel.y * dt

        # Axis-separated tile collision (AABB vs tile grid).
        # Entity occupies a HITBOX_W × HITBOX_H box starting at (pos.x, pos.y).
        # Try X movement first, then Y — allows wall-sliding.
        if _aabb_hits_wall(nx, pos.y, HITBOX_W, HITBOX_H, h, w, tiles):
            nx = pos.x
            vel.x = 0.0
        if _aabb_hits_wall(nx, ny, HITBOX_W, HITBOX_H, h, w, tiles):
            ny = pos.y
            vel.y = 0.0

        # Entity collisions (very simple): don't move if overlapping another collider
        if eid in colliders:
            mypos, mycol = colliders[eid]
            collide = False
            for oid, (opos, oc) in colliders.items():
                if oid == eid:
                    continue
                if not world.alive(oid):
                    continue
                # Only consider entities in same zone
                if opos.zone != pos.zone:
                    continue
                dx = nx - opos.x
                dy = ny - opos.y
                # use simple radius test
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

        # Knockback friction (post-commit): dampen residual velocity
        # so knockback decays.  Brain overwrites vel every frame,
        # making this a no-op for intentional movement.
        if not world.has(eid, Player):
            vel.x *= 0.85
            vel.y *= 0.85
            if abs(vel.x) < 0.05:
                vel.x = 0.0
            if abs(vel.y) < 0.05:
                vel.y = 0.0


def input_system(world: World, move: tuple[float, float] | None = None) -> None:
    """Set Player velocity from movement input.

    Pass ``move=(dx, dy)`` normalised from the InputManager.
    Also updates the player's Facing direction.
    """
    if move is not None:
        dx, dy = move
    else:
        return

    for eid, player, vel in world.query(Player, Velocity):
        vel.x = dx * player.speed
        vel.y = dy * player.speed

        # Update Facing from movement direction (only when moving)
        if abs(vel.x) > 0.01 or abs(vel.y) > 0.01:
            facing = world.get(eid, Facing)
            if facing is not None:
                if abs(vel.x) >= abs(vel.y):
                    facing.direction = "right" if vel.x > 0 else "left"
                else:
                    facing.direction = "down" if vel.y > 0 else "up"


def item_pickup_system(world: World) -> None:
    """Pick up nearby item entities and add them to the player's Inventory.

    An item entity is an entity with `Identity.kind == 'item'` and a `Position`.
    When the player is within ~0.6 tiles of an item it is collected.
    """
    result = world.query_one(Player, Position, Inventory)
    if not result:
        return
    pid, _, ppos, pinv = result

    for eid, ipos, ident in world.query(Position, Identity):
        if getattr(ident, 'kind', '') != 'item':
            continue
        if not world.alive(eid):
            continue
        dx = ipos.x - ppos.x
        dy = ipos.y - ppos.y
        if dx * dx + dy * dy <= 0.36:  # 0.6²
            name = getattr(ident, 'name', f'item_{eid}') or f'item_{eid}'
            pinv.items[name] = pinv.items.get(name, 0) + 1
            print(f"[PICKUP] player picked up {name}")
            world.kill(eid)
