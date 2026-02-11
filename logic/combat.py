"""logic/combat.py — Combat and interaction system

Basic melee combat:
- Player uses X key (near entity) to attack
- Damage based on attacker's weapon + defender's armor
- Enemies drop loot on death, then disappear
- Knockback on hit, brief hit flash indicator

Lootable containers:
- Chests, bodies, rubble piles, etc.
- Press E to open/loot
- One-time loot per container (saved in zone_state)
"""

from __future__ import annotations
import math
import random
from typing import TYPE_CHECKING
from components import (
    Combat as CombatComp, Health, Identity, Position, Velocity,
    HitFlash, Loot, Hurtbox, Equipment, ItemRegistry, Projectile,
    Facing, Brain, Player, Faction,
)
from logic.particles import ParticleManager

if TYPE_CHECKING:
    from core.app import App


def attack_entity(world, attacker_eid: int, defender_eid: int,
                  bonus_damage: float = 0.0,
                  knockback: float = 3.0,
                  crit_chance: float = 0.1,
                  crit_mult: float = 1.5) -> bool:
    """One entity attacks another. Returns True if defender dies.

    Works for both player and NPC attackers — pass ``world`` directly.
    Attacker must have Combat component.
    Defender must have Health component.
    """
    if not world.has(attacker_eid, CombatComp) or not world.has(defender_eid, Health):
        return False

    combat = world.get(attacker_eid, CombatComp)
    health = world.get(defender_eid, Health)

    # Calculate damage: base + weapon bonus − defender defense, with ±20% variance
    raw = combat.damage + bonus_damage
    defender_def = 0.0
    if world.has(defender_eid, CombatComp):
        defender_def = world.get(defender_eid, CombatComp).defense
    base_damage = max(1.0, raw - defender_def)
    variance = random.uniform(0.8, 1.2)
    damage = base_damage * variance

    # Chance for critical hit
    is_crit = random.random() < crit_chance
    if is_crit:
        damage *= crit_mult

    health.current -= damage

    # Apply knockback to defender
    if world.has(defender_eid, Position) and world.has(defender_eid, Velocity):
        def_pos = world.get(defender_eid, Position)
        att_pos = world.get(attacker_eid, Position)
        def_vel = world.get(defender_eid, Velocity)

        dx = def_pos.x - att_pos.x
        dy = def_pos.y - att_pos.y
        mag = (dx*dx + dy*dy) ** 0.5
        if mag > 0.01:
            def_vel.x = (dx / mag) * knockback
            def_vel.y = (dy / mag) * knockback

    # Apply hit flash effect
    if not world.has(defender_eid, HitFlash):
        world.add(defender_eid, HitFlash(remaining=0.1))
    else:
        hf = world.get(defender_eid, HitFlash)
        hf.remaining = 0.1

    # Particle effects on hit
    pm = world.res(ParticleManager)
    if pm and world.has(defender_eid, Position):
        dp = world.get(defender_eid, Position)
        hit_color = (255, 50, 50) if not is_crit else (255, 200, 50)
        pm.emit_burst(dp.x + 0.4, dp.y + 0.4, count=6 if not is_crit else 12,
                      color=hit_color, speed=2.5, life=0.3, size=2.0)

    # Get names for log
    attacker_name = "?"
    defender_name = "?"
    if world.has(attacker_eid, Identity):
        attacker_name = world.get(attacker_eid, Identity).name
    if world.has(defender_eid, Identity):
        defender_name = world.get(defender_eid, Identity).name

    crit_tag = " [CRIT]" if is_crit else ""
    print(f"[COMBAT] {attacker_name} hit {defender_name} for {damage:.0f} damage{crit_tag} (HP: {health.current:.0f}/{health.maximum})")

    if health.current <= 0:
        print(f"[COMBAT] {defender_name} died")
        handle_death(world, defender_eid)
        return True

    # Alert same-faction allies when the player attacks
    alert_nearby_faction(world, defender_eid, attacker_eid)

    return False


def handle_death(world, dead_eid: int) -> None:
    """Unified death sequence: particles → loot → kill.

    Called from both melee combat and projectile hits.
    Accepts a World directly (no App dependency).
    Skips the player entity — scene handles game-over.
    """
    if world.has(dead_eid, Player):
        print("[COMBAT] Player down!")
        return
    pm = world.res(ParticleManager)
    if pm and world.has(dead_eid, Position):
        dp = world.get(dead_eid, Position)
        pm.emit_burst(dp.x + 0.4, dp.y + 0.4, count=20,
                      color=(180, 30, 30), speed=3.5, life=0.6,
                      size=2.5, gravity=4.0)
    _drop_loot(world, dead_eid)
    world.kill(dead_eid)


def _drop_loot(world, dead_eid: int) -> None:
    """Spawn loot items where entity died."""
    pos = world.get(dead_eid, Position)
    if not pos:
        return
    if world.has(dead_eid, Loot):
        loot = world.get(dead_eid, Loot)
        if loot.items:
            print(f"[LOOT] Items dropped at ({pos.x},{pos.y}): {loot.items}")


def get_hitbox_targets(
    app: "App",
    weapon_rect: tuple[float, float, float, float],
    actor_zone: str,
    exclude_eid: int | None = None,
) -> list[int]:
    """Return entity IDs whose Hurtbox overlaps `weapon_rect`.

    weapon_rect: (x, y, w, h) in world-tile coordinates.
    Falls back to Position centre if entity has no Hurtbox.
    """
    wx, wy, ww, wh = weapon_rect
    hits: list[int] = []
    for eid, pos in app.world.all_of(Position):
        if exclude_eid is not None and eid == exclude_eid:
            continue
        if pos.zone != actor_zone:
            continue
        if not app.world.has(eid, Health):
            continue
        # Build target AABB
        hb = app.world.get(eid, Hurtbox)
        if hb:
            tx = pos.x + hb.ox
            ty = pos.y + hb.oy
            tw = hb.w
            th = hb.h
        else:
            # Fallback: small box at position
            tx = pos.x
            ty = pos.y
            tw = 0.8
            th = 0.8
        # AABB overlap test
        if wx < tx + tw and wx + ww > tx and wy < ty + th and wy + wh > ty:
            hits.append(eid)
    return hits


# ── Faction alert propagation ────────────────────────────────────────

def alert_nearby_faction(world, defender_eid: int, attacker_eid: int):
    """When the player attacks an entity, flip its faction to hostile
    and alert nearby same-group allies.

    Does nothing if the attacker isn't the player.
    """
    if not world.has(attacker_eid, Player):
        return
    faction = world.get(defender_eid, Faction)
    if faction is None:
        return
    pos = world.get(defender_eid, Position)
    if pos is None:
        return

    # Flip defender to hostile
    if faction.disposition != "hostile":
        faction.disposition = "hostile"
        name = "?"
        if world.has(defender_eid, Identity):
            name = world.get(defender_eid, Identity).name
        print(f"[FACTION] {name} is now hostile!")

    # Alert same-group allies within alert radius
    r_sq = faction.alert_radius ** 2
    for eid, ally_pos in world.all_of(Position):
        if eid == defender_eid or eid == attacker_eid:
            continue
        if ally_pos.zone != pos.zone:
            continue
        af = world.get(eid, Faction)
        if af is None or af.group != faction.group:
            continue
        if af.disposition == "hostile":
            continue
        dx = ally_pos.x - pos.x
        dy = ally_pos.y - pos.y
        if dx * dx + dy * dy <= r_sq:
            af.disposition = "hostile"
            ally_name = "?"
            if world.has(eid, Identity):
                ally_name = world.get(eid, Identity).name
            print(f"[FACTION] {ally_name} alerted — now hostile!")


# ── NPC combat helpers ──────────────────────────────────────────────

def get_entity_weapon_stats(world, eid: int) -> tuple[float, float, str]:
    """Return (bonus_damage, reach, style) from an entity's equipped weapon."""
    equip = world.get(eid, Equipment)
    registry = world.res(ItemRegistry)
    if equip and equip.weapon and registry:
        dmg = registry.get_field(equip.weapon, "damage", 0.0)
        rch = registry.get_field(equip.weapon, "reach", 1.5)
        style = registry.get_field(equip.weapon, "style", "melee")
        return dmg, rch, style
    return 0.0, 1.0, "melee"


def npc_melee_attack(world, attacker_eid: int, target_eid: int) -> bool:
    """NPC performs a melee attack. Returns True if target dies."""
    bonus_dmg, _, _ = get_entity_weapon_stats(world, attacker_eid)
    equip = world.get(attacker_eid, Equipment)
    registry = world.res(ItemRegistry)
    kb, cc, cm = 3.0, 0.1, 1.5
    if equip and equip.weapon and registry:
        kb = registry.get_field(equip.weapon, "knockback", 3.0)
        cc = registry.get_field(equip.weapon, "crit_chance", 0.1)
        cm = registry.get_field(equip.weapon, "crit_mult", 1.5)
    return attack_entity(world, attacker_eid, target_eid,
                         bonus_damage=bonus_dmg, knockback=kb,
                         crit_chance=cc, crit_mult=cm)


def npc_ranged_attack(world, attacker_eid: int, target_eid: int) -> bool:
    """NPC fires a projectile at target. Returns True if projectile spawned."""
    att_pos = world.get(attacker_eid, Position)
    def_pos = world.get(target_eid, Position)
    if not att_pos or not def_pos:
        return False

    cx = att_pos.x + 0.4
    cy = att_pos.y + 0.4
    tx = def_pos.x + 0.4
    ty = def_pos.y + 0.4
    dx = tx - cx
    dy = ty - cy
    dist = math.hypot(dx, dy)
    if dist < 0.01:
        return False
    dx /= dist
    dy /= dist

    # Weapon stats
    bonus_dmg, _, _ = get_entity_weapon_stats(world, attacker_eid)
    combat = world.get(attacker_eid, CombatComp)
    total_dmg = (combat.damage if combat else 0.0) + bonus_dmg

    equip = world.get(attacker_eid, Equipment)
    registry = world.res(ItemRegistry)
    accuracy = 0.7
    proj_speed = 12.0
    max_range = 10.0
    pchar = "."
    pcolor = (255, 200, 100)
    if equip and equip.weapon and registry:
        accuracy = registry.get_field(equip.weapon, "accuracy", 0.7)
        proj_speed = registry.get_field(equip.weapon, "proj_speed", 12.0)
        max_range = registry.get_field(equip.weapon, "range", 10.0)
        pchar = registry.get_field(equip.weapon, "proj_char", ".")
        pcolor = registry.get_field(equip.weapon, "proj_color", (255, 200, 100))

    # Apply accuracy spread
    angle = math.atan2(dy, dx)
    spread = (1.0 - accuracy) * 0.4
    angle += random.uniform(-spread, spread)
    pdx = math.cos(angle)
    pdy = math.sin(angle)

    # Spawn projectile
    eid = world.spawn()
    sx = cx + pdx * 0.5
    sy = cy + pdy * 0.5
    world.add(eid, Position(x=sx, y=sy, zone=att_pos.zone))
    world.add(eid, Projectile(
        owner_eid=attacker_eid,
        damage=total_dmg,
        speed=proj_speed,
        dx=pdx, dy=pdy,
        max_range=max_range,
        char=pchar, color=pcolor,
    ))

    # Muzzle flash particles
    pm = world.res(ParticleManager)
    if pm:
        pm.emit_burst(sx, sy, count=3, color=(255, 180, 60),
                      speed=1.5, life=0.1, size=1.0, spread=0.5, angle=angle)

    attacker_name = "?"
    if world.has(attacker_eid, Identity):
        attacker_name = world.get(attacker_eid, Identity).name
    print(f"[NPC RANGED] {attacker_name} fired")
    return True
