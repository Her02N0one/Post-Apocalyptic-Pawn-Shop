"""logic/projectiles.py — Projectile tick system.

Each frame:
  1. Move every Projectile along its direction vector.
  2. Check for hurtbox collisions with non-owner entities.
  3. Check for wall-tile collisions.
  4. Despawn when max_range exceeded or hit something.

Damage falloff: projectiles lose up to 50 % damage at max range.
"""

from __future__ import annotations
import math
from components import (
    Projectile, Position, Health, Hurtbox,
    HitFlash, Identity, Combat as CombatComp, Faction,
)
from logic.particles import ParticleManager


def projectile_system(world, dt: float, tiles: list[list[int]]):
    """Tick all projectiles for one frame."""
    from core.constants import TILE_WALL
    h = len(tiles)
    w = len(tiles[0]) if h else 0

    to_kill: list[int] = []

    for eid, pos, proj in world.query(Position, Projectile):
        # Move
        step = proj.speed * dt
        pos.x += proj.dx * step
        pos.y += proj.dy * step
        proj.traveled += step

        # Wall collision
        tr = int(math.floor(pos.y))
        tc = int(math.floor(pos.x))
        if tr < 0 or tr >= h or tc < 0 or tc >= w or tiles[tr][tc] == TILE_WALL:
            _on_wall_hit(world, pos)
            to_kill.append(eid)
            continue

        # Range despawn
        if proj.traveled >= proj.max_range:
            to_kill.append(eid)
            continue

        # Hurtbox collision (circle vs AABB)
        hit_eid = _check_hit(world, eid, pos, proj)
        if hit_eid is not None:
            _apply_projectile_damage(world, proj, hit_eid, pos)
            to_kill.append(eid)
            continue

    for eid in to_kill:
        world.kill(eid)


# ── internal helpers ────────────────────────────────────────────────

def _check_hit(world, proj_eid: int, pos, proj) -> int | None:
    """Return first entity whose hurtbox overlaps the projectile, or None.

    Skips the projectile's owner AND any entity in the same faction group,
    so allied NPCs don't shoot each other.
    """
    px, py, r = pos.x, pos.y, proj.radius

    # Resolve owner's faction group for ally filtering
    owner_faction = world.get(proj.owner_eid, Faction)
    owner_group = owner_faction.group if owner_faction else None

    for eid, epos in world.all_of(Position):
        if eid == proj_eid or eid == proj.owner_eid:
            continue
        if epos.zone != pos.zone:
            continue
        if not world.has(eid, Health):
            continue

        # Skip same-faction entities (friendly fire protection)
        if owner_group is not None:
            ef = world.get(eid, Faction)
            if ef is not None and ef.group == owner_group:
                continue
        # Build target AABB (world coords)
        hb = world.get(eid, Hurtbox)
        if hb:
            bx, by, bw, bh = epos.x + hb.ox, epos.y + hb.oy, hb.w, hb.h
        else:
            bx, by, bw, bh = epos.x, epos.y, 0.8, 0.8
        # Circle-AABB overlap
        cx = max(bx, min(px, bx + bw))
        cy = max(by, min(py, by + bh))
        dx, dy = px - cx, py - cy
        if dx * dx + dy * dy <= r * r:
            return eid
    return None


def _apply_projectile_damage(world, proj, target_eid: int, pos):
    """Deal damage to target, apply knockback, particles, etc."""
    if not world.has(target_eid, Health):
        return

    health = world.get(target_eid, Health)

    # Distance-based damage falloff: 100 % at origin → 50 % at max range
    t = min(1.0, proj.traveled / max(0.1, proj.max_range))
    falloff = 1.0 - 0.5 * t
    damage = proj.damage * falloff

    # Subtract defender armor
    if world.has(target_eid, CombatComp):
        armor = world.get(target_eid, CombatComp).defense
        damage = max(1.0, damage - armor)

    health.current -= damage

    # Hit flash
    if not world.has(target_eid, HitFlash):
        world.add(target_eid, HitFlash(remaining=0.1))
    else:
        world.get(target_eid, HitFlash).remaining = 0.1

    # Knockback (in projectile direction)
    from components import Velocity as VelComp
    if world.has(target_eid, VelComp):
        v = world.get(target_eid, VelComp)
        v.x = proj.dx * 2.5
        v.y = proj.dy * 2.5

    # Particles
    pm = world.res(ParticleManager)
    if pm:
        pm.emit_burst(pos.x, pos.y, count=8, color=(255, 200, 80),
                      speed=3.0, life=0.3, size=2.0)

    # Log
    target_name = "?"
    if world.has(target_eid, Identity):
        target_name = world.get(target_eid, Identity).name
    print(f"[PROJECTILE] hit {target_name} for {damage:.0f} dmg (falloff {falloff:.0%})")

    # Death
    if health.current <= 0:
        print(f"[PROJECTILE] {target_name} killed")
        from logic.combat import handle_death
        handle_death(world, target_eid)
    else:
        # Alert same-faction allies
        from logic.combat import alert_nearby_faction
        alert_nearby_faction(world, target_eid, proj.owner_eid)


def _on_wall_hit(world, pos):
    """Particle puff when bullet hits a wall."""
    pm = world.res(ParticleManager)
    if pm:
        pm.emit_burst(pos.x, pos.y, count=4, color=(180, 180, 180),
                      speed=2.0, life=0.2, size=1.5)
