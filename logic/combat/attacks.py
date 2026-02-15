"""logic/combat/attacks.py — Core attack pipeline and NPC attack helpers.

Attack execution:
- ``attack_entity()`` — generic damage pipeline for any attacker/defender.
- ``npc_melee_attack()`` / ``npc_ranged_attack()`` — NPC-specific wrappers
  that handle cooldown gating, weapon stats, and sound emission.

Alert/sound/intel logic has been moved to ``alerts.py``.
"""

from __future__ import annotations
import math
import random
from typing import TYPE_CHECKING
from components import (
    CombatStats, Health, Identity, Position, Velocity,
    HitFlash, Loot, Hurtbox, Equipment, ItemRegistry, Projectile,
    Facing, Brain, Faction, AttackConfig, Threat, GameClock,
)
from logic.particles import ParticleManager
from logic.combat.damage import apply_damage as _apply_damage
from logic.combat.damage import handle_death  # re-exported for backward compat
from core.tuning import get as _tun, section as _tun_sec
from logic.faction_ops import entity_display_name

# ── Re-exports so existing ``from logic.combat.attacks import …``
#    keeps working after moving alerts to alerts.py. ──────────────────
from logic.combat.alerts import (             # noqa: F401
    alert_nearby_faction,
    emit_combat_sound,
    share_combat_intel,
)

if TYPE_CHECKING:
    from core.app import App


# ── Core attack pipeline ─────────────────────────────────────────────

def attack_entity(world, attacker_eid: int, defender_eid: int,
                  bonus_damage: float = 0.0,
                  knockback: float | None = None,
                  crit_chance: float | None = None,
                  crit_mult: float | None = None) -> bool:
    """One entity attacks another. Returns True if defender dies.

    Works for both player and NPC attackers.
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

    raw = combat.damage + bonus_damage
    v_min = _tun("combat.melee", "damage_variance_min", 0.8)
    v_max = _tun("combat.melee", "damage_variance_max", 1.2)
    raw_damage = raw * random.uniform(v_min, v_max)

    damage, is_crit, is_dead = _apply_damage(
        world, attacker_eid, defender_eid, raw_damage,
        knockback=knockback,
        crit_chance=crit_chance,
        crit_mult=crit_mult,
    )

    if is_dead:
        name = world.get(defender_eid, Identity).name if world.has(defender_eid, Identity) else "?"
        print(f"[COMBAT] {name} died")
        handle_death(world, defender_eid)
        return True

    alert_nearby_faction(world, defender_eid, attacker_eid)
    return False


# ── Hitbox query ─────────────────────────────────────────────────────

def get_hitbox_targets(
    app: "App",
    weapon_rect: tuple[float, float, float, float],
    actor_zone: str,
    exclude_eid: int | None = None,
) -> list[int]:
    """Return entity IDs whose Hurtbox overlaps ``weapon_rect``.

    ``weapon_rect``: ``(x, y, w, h)`` in world-tile coordinates.
    Uses ``world.query_zone()`` for O(1) zone lookup.
    """
    wx, wy, ww, wh = weapon_rect
    hits: list[int] = []
    for eid, pos, _hp in app.world.query_zone(actor_zone, Position, Health):
        if exclude_eid is not None and eid == exclude_eid:
            continue
        hb = app.world.get(eid, Hurtbox)
        if hb:
            tx, ty, tw, th = pos.x + hb.ox, pos.y + hb.oy, hb.w, hb.h
        else:
            fb_w = _tun("combat.melee", "fallback_hurtbox_w", 0.8)
            fb_h = _tun("combat.melee", "fallback_hurtbox_h", 0.8)
            tx, ty, tw, th = pos.x, pos.y, fb_w, fb_h
        if wx < tx + tw and wx + ww > tx and wy < ty + th and wy + wh > ty:
            hits.append(eid)
    return hits


# ── Weapon stats ─────────────────────────────────────────────────────

def get_entity_weapon_stats(world, eid: int) -> tuple[float, float, str]:
    """Return ``(bonus_damage, reach, style)`` from an entity's equipped weapon."""
    equip = world.get(eid, Equipment)
    registry = world.res(ItemRegistry)
    if equip and equip.weapon and registry:
        dmg = registry.get_field(equip.weapon, "damage", 0.0)
        rch = registry.get_field(equip.weapon, "reach", 1.5)
        style = registry.get_field(equip.weapon, "style", "melee")
        return dmg, rch, style
    return 0.0, 1.0, "melee"


# ── NPC attack helpers ───────────────────────────────────────────────

def npc_melee_attack(world, attacker_eid: int, target_eid: int) -> bool:
    """NPC performs a melee attack. Returns True if target dies."""
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
    result = attack_entity(world, attacker_eid, target_eid,
                           bonus_damage=bonus_dmg, knockback=kb,
                           crit_chance=cc, crit_mult=cm)

    att_pos = world.get(attacker_eid, Position)
    if att_pos:
        emit_combat_sound(world, attacker_eid, att_pos, "melee")

    return result


def npc_ranged_attack(world, attacker_eid: int, target_eid: int) -> bool:
    """NPC fires a projectile at target. Returns True if projectile spawned."""
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

    bonus_dmg, _, _ = get_entity_weapon_stats(world, attacker_eid)
    combat = world.get(attacker_eid, CombatStats)
    total_dmg = (combat.damage if combat else 0.0) + bonus_dmg

    equip = world.get(attacker_eid, Equipment)
    registry = world.res(ItemRegistry)
    atk_cfg = world.get(attacker_eid, AttackConfig)
    accuracy, proj_speed, max_range = 0.85, 14.0, 10.0
    pchar, pcolor = ".", (255, 200, 100)
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

    angle = math.atan2(dy, dx)
    spread = (1.0 - accuracy) * 0.4
    angle += random.uniform(-spread, spread)
    pdx = math.cos(angle)
    pdy = math.sin(angle)

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

    attacker_name = entity_display_name(world, attacker_eid)
    print(f"[NPC RANGED] {attacker_name} fired")

    emit_combat_sound(world, attacker_eid, att_pos, "gunshot")
    return True
