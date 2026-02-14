"""logic/combat/attacks.py — CombatStats and interaction system

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
    CombatStats, Health, Identity, Position, Velocity,
    HitFlash, Loot, Hurtbox, Equipment, ItemRegistry, Projectile,
    Facing, Brain, Player, Faction, AttackConfig, Threat, GameClock,
)
from logic.particles import ParticleManager
from logic.combat.damage import apply_damage as _apply_damage
from logic.combat.damage import handle_death  # re-exported for backward compat
from core.tuning import get as _tun, section as _tun_sec

if TYPE_CHECKING:
    from core.app import App


def attack_entity(world, attacker_eid: int, defender_eid: int,
                  bonus_damage: float = 0.0,
                  knockback: float | None = None,
                  crit_chance: float | None = None,
                  crit_mult: float | None = None) -> bool:
    """One entity attacks another. Returns True if defender dies.

    Works for both player and NPC attackers — pass ``world`` directly.
    Attacker must have CombatStats component.
    Defender must have Health component.
    """
    if not world.has(attacker_eid, CombatStats) or not world.has(defender_eid, Health):
        return False

    if knockback is None:
        knockback = _tun("combat.melee", "default_knockback", 3.0)
    if crit_chance is None:
        crit_chance = _tun("combat.melee", "default_crit_chance", 0.1)
    if crit_mult is None:
        crit_mult = _tun("combat.melee", "default_crit_mult", 1.5)

    combat = world.get(attacker_eid, CombatStats)

    # Calculate raw damage: base + weapon bonus, with variance
    raw = combat.damage + bonus_damage
    v_min = _tun("combat.melee", "damage_variance_min", 0.8)
    v_max = _tun("combat.melee", "damage_variance_max", 1.2)
    variance = random.uniform(v_min, v_max)
    raw_damage = raw * variance

    # Delegate to canonical damage pipeline
    damage, is_crit, is_dead = _apply_damage(
        world, attacker_eid, defender_eid, raw_damage,
        knockback=knockback,
        crit_chance=crit_chance,
        crit_mult=crit_mult,
    )

    if is_dead:
        print(f"[COMBAT] {world.get(defender_eid, Identity).name if world.has(defender_eid, Identity) else '?'} died")
        handle_death(world, defender_eid)
        return True

    # Alert same-faction allies when the player attacks
    alert_nearby_faction(world, defender_eid, attacker_eid)

    return False


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
            fb_w = _tun("combat.melee", "fallback_hurtbox_w", 0.8)
            fb_h = _tun("combat.melee", "fallback_hurtbox_h", 0.8)
            tx = pos.x
            ty = pos.y
            tw = fb_w
            th = fb_h
        # AABB overlap test
        if wx < tx + tw and wx + ww > tx and wy < ty + th and wy + wh > ty:
            hits.append(eid)
    return hits


# ── Faction alert propagation ────────────────────────────────────────

def _activate_hostile(world, eid: int, player_pos, game_time: float):
    """Flip an entity's brain to hostile-chase mode (or crime-flee if unarmed)."""
    if not world.has(eid, Brain):
        return
    brain = world.get(eid, Brain)
    brain.active = True
    if world.has(eid, AttackConfig):
        c = brain.state.setdefault("combat", {})
        c["mode"] = "chase"
        if player_pos:
            c["p_pos"] = (player_pos.x, player_pos.y)
        threat = world.get(eid, Threat)
        if threat:
            threat.last_sensor_time = game_time - threat.sensor_interval
    else:
        brain.state["crime_flee_until"] = game_time + 20.0


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

    clock = world.res(GameClock)
    game_time = clock.time if clock else 0.0
    player_pos = world.get(attacker_eid, Position)

    # Flip defender to hostile
    if faction.disposition != "hostile":
        faction.disposition = "hostile"
        name = "?"
        if world.has(defender_eid, Identity):
            name = world.get(defender_eid, Identity).name
        print(f"[FACTION] {name} is now hostile!")

    _activate_hostile(world, defender_eid, player_pos, game_time)

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
            _activate_hostile(world, eid, player_pos, game_time)


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
    # Hard cooldown gate — prevents double-fire regardless of caller
    atk_cfg = world.get(attacker_eid, AttackConfig)
    if atk_cfg:
        clock = world.res(GameClock)
        now = clock.time if clock else 0.0
        if now - atk_cfg.last_attack_time < atk_cfg.cooldown * 0.9:
            return False
        atk_cfg.last_attack_time = now
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
    # Hard cooldown gate — prevents double-fire regardless of caller
    atk_cfg = world.get(attacker_eid, AttackConfig)
    if atk_cfg:
        clock = world.res(GameClock)
        now = clock.time if clock else 0.0
        if now - atk_cfg.last_attack_time < atk_cfg.cooldown * 0.9:
            return False
        atk_cfg.last_attack_time = now

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
    combat = world.get(attacker_eid, CombatStats)
    total_dmg = (combat.damage if combat else 0.0) + bonus_dmg

    equip = world.get(attacker_eid, Equipment)
    registry = world.res(ItemRegistry)
    atk_cfg = world.get(attacker_eid, AttackConfig)
    # Defaults — overridden by Equipment or AttackConfig
    accuracy = 0.85
    proj_speed = 14.0
    max_range = 10.0
    pchar = "."
    pcolor = (255, 200, 100)
    if equip and equip.weapon and registry:
        accuracy = registry.get_field(equip.weapon, "accuracy", 0.85)
        proj_speed = registry.get_field(equip.weapon, "proj_speed", 14.0)
        max_range = registry.get_field(equip.weapon, "range", 10.0)
        pchar = registry.get_field(equip.weapon, "proj_char", ".")
        pcolor = registry.get_field(equip.weapon, "proj_color", (255, 200, 100))
    elif atk_cfg:
        accuracy = atk_cfg.accuracy
        proj_speed = atk_cfg.proj_speed
        max_range = atk_cfg.range

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
        mf = _tun_sec("particles.muzzle_flash")
        pm.emit_burst(sx, sy,
                      count=mf.get("count", 3),
                      color=tuple(mf.get("color", [255, 180, 60])),
                      speed=mf.get("speed", 1.5),
                      life=mf.get("life", 0.1),
                      size=mf.get("size", 1.0),
                      spread=0.5, angle=angle)

    attacker_name = "?"
    if world.has(attacker_eid, Identity):
        attacker_name = world.get(attacker_eid, Identity).name
    print(f"[NPC RANGED] {attacker_name} fired")
    return True
