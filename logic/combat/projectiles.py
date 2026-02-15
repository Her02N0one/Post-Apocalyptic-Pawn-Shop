"""logic/combat/projectiles.py — Projectile tick system.

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
    HitFlash, Identity, CombatStats, Faction,
)
from logic.combat.damage import apply_damage
from logic.particles import ParticleManager
from core.tuning import get as _tun, section as _tun_sec
from core.events import EventBus, EntityDied, EntityHit, FactionAlert


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

    Uses ``world.query_zone()`` for O(1) zone lookup.
    """
    px, py, r = pos.x, pos.y, proj.radius

    # Resolve owner's faction group for ally filtering
    owner_faction = world.get(proj.owner_eid, Faction)
    owner_group = owner_faction.group if owner_faction else None

    for eid, epos, _hp in world.query_zone(pos.zone, Position, Health):
        if eid == proj_eid or eid == proj.owner_eid:
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
    """Deal damage to target via the shared damage pipeline."""
    if not world.has(target_eid, Health):
        return

    # Distance-based damage falloff: 100 % at origin → falloff_min at max range
    falloff_min = _tun("combat.ranged", "projectile_falloff_min", 0.5)
    t = min(1.0, proj.traveled / max(0.1, proj.max_range))
    falloff = 1.0 - (1.0 - falloff_min) * t
    raw_damage = proj.damage * falloff

    # Knockback in projectile direction
    kb_dir = (proj.dx, proj.dy)

    damage, is_crit, is_dead = apply_damage(
        world, proj.owner_eid, target_eid, raw_damage,
        knockback=2.5,
        knockback_dir=kb_dir,
        log_prefix="PROJECTILE",
    )

    # Death handling
    if is_dead:
        target_name = "?"
        if world.has(target_eid, Identity):
            target_name = world.get(target_eid, Identity).name
        print(f"[PROJECTILE] {target_name} killed")
        bus = world.res(EventBus)
        if bus:
            zone = world.get(target_eid, Position)
            bus.emit(EntityDied(
                eid=target_eid,
                killer_eid=proj.owner_eid,
                zone=zone.zone if zone else "",
            ))
        else:
            from logic.combat.damage import handle_death
            handle_death(world, target_eid)
    else:
        # Alert same-faction allies via event
        bus = world.res(EventBus)
        target_pos = world.get(target_eid, Position)
        target_fac = world.get(target_eid, Faction)
        if bus and target_pos and target_fac:
            bus.emit(FactionAlert(
                group=target_fac.group,
                x=target_pos.x, y=target_pos.y,
                zone=target_pos.zone,
                threat_eid=proj.owner_eid,
            ))
        else:
            from logic.combat.attacks import alert_nearby_faction
            alert_nearby_faction(world, target_eid, proj.owner_eid)


def _on_wall_hit(world, pos):
    """Particle puff when bullet hits a wall."""
    pm = world.res(ParticleManager)
    if pm:
        pm.emit_burst(pos.x, pos.y, count=4, color=(180, 180, 180),
                      speed=2.0, life=0.2, size=1.5)
