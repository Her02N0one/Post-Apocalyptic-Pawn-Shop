"""logic/actions/combat.py — Melee and ranged player attack actions."""

from __future__ import annotations
import math
import random
from components import (
    Player, Position, Combat, Equipment, Facing, Projectile, ItemRegistry,
)
from logic.combat import attack_entity, get_hitbox_targets
from logic.actions import (
    AttackResult, FIST_REACH, PLAYER_SIZE,
    weapon_rect_for, mouse_world_pos, _facing_from_angle,
)


# ── Weapon stats ────────────────────────────────────────────────────

def _get_weapon_stats(app, player_eid: int) -> tuple[float, float, str]:
    """Return (bonus_damage, reach, style) from equipped weapon."""
    equip = app.world.get(player_eid, Equipment)
    registry = app.world.res(ItemRegistry)
    if equip and equip.weapon and registry:
        dmg = registry.get_field(equip.weapon, "damage", 0.0)
        rch = registry.get_field(equip.weapon, "reach", 1.5)
        style = registry.get_field(equip.weapon, "style", "melee")
        return dmg, rch, style
    return 0.0, FIST_REACH, "melee"


# ── Attack dispatcher (called on left-click or X key) ──────────────

def player_attack(app, scene) -> AttackResult | None:
    """Dispatch to melee or ranged based on equipped weapon."""
    res = app.world.query_one(Player, Position)
    if not res:
        return None
    player_eid = res[0]

    _, _, style = _get_weapon_stats(app, player_eid)
    if style == "ranged":
        return player_ranged_attack(app, scene)
    else:
        return player_melee_attack(app, scene)


# ── Melee ───────────────────────────────────────────────────────────

def player_melee_attack(app, scene) -> AttackResult | None:
    """Swing melee weapon in facing direction."""
    res = app.world.query_one(Player, Position)
    if not res:
        return None

    player_eid = res[0]
    _, _, player_pos = res

    # Update facing toward mouse
    mw = mouse_world_pos(app, scene)
    facing_comp = app.world.get(player_eid, Facing)
    if mw and facing_comp:
        cx = player_pos.x + PLAYER_SIZE / 2
        cy = player_pos.y + PLAYER_SIZE / 2
        angle = math.atan2(mw[1] - cy, mw[0] - cx)
        facing_comp.direction = _facing_from_angle(angle)

    facing = facing_comp.direction if facing_comp else "down"

    dir_map = {"right": (1, 0), "left": (-1, 0), "up": (0, -1), "down": (0, 1)}
    result = AttackResult(
        melee_active=True,
        melee_timer=0.15,
        melee_direction=dir_map.get(facing, (0, 1)),
    )

    bonus_dmg, reach, _ = _get_weapon_stats(app, player_eid)
    wrect = weapon_rect_for(player_pos, facing, reach=reach)
    hits = get_hitbox_targets(app, wrect, player_pos.zone, exclude_eid=player_eid)

    if not hits:
        return result

    if not app.world.has(player_eid, Combat):
        return result

    # Get weapon-specific combat modifiers
    equip = app.world.get(player_eid, Equipment)
    registry = app.world.res(ItemRegistry)
    kb = 3.0
    cc = 0.1
    cm = 1.5
    if equip and equip.weapon and registry:
        kb = registry.get_field(equip.weapon, "knockback", 3.0)
        cc = registry.get_field(equip.weapon, "crit_chance", 0.1)
        cm = registry.get_field(equip.weapon, "crit_mult", 1.5)

    for target_eid in hits:
        attack_entity(app.world, player_eid, target_eid, bonus_damage=bonus_dmg,
                      knockback=kb, crit_chance=cc, crit_mult=cm)
    return result


# ── Ranged ──────────────────────────────────────────────────────────

def player_ranged_attack(app, scene) -> AttackResult | None:
    """Fire a projectile toward the mouse cursor."""
    res = app.world.query_one(Player, Position)
    if not res:
        return None

    player_eid = res[0]
    _, _, player_pos = res

    mw = mouse_world_pos(app, scene)
    if mw is None:
        return None

    # Direction from player centre to mouse
    cx = player_pos.x + PLAYER_SIZE / 2
    cy = player_pos.y + PLAYER_SIZE / 2
    dx_raw = mw[0] - cx
    dy_raw = mw[1] - cy
    dist_to_cursor = math.hypot(dx_raw, dy_raw)
    if dist_to_cursor < 0.01:
        return None
    dx_norm = dx_raw / dist_to_cursor
    dy_norm = dy_raw / dist_to_cursor

    # Update facing
    angle = math.atan2(dy_raw, dx_raw)
    facing_comp = app.world.get(player_eid, Facing)
    if facing_comp:
        facing_comp.direction = _facing_from_angle(angle)

    # Get weapon data
    equip = app.world.get(player_eid, Equipment)
    registry = app.world.res(ItemRegistry)
    if not equip or not equip.weapon or not registry:
        return None
    item_id = equip.weapon
    base_dmg = registry.get_field(item_id, "damage", 0.0)
    combat = app.world.get(player_eid, Combat)
    total_dmg = (combat.damage if combat else 0.0) + base_dmg

    accuracy = registry.get_field(item_id, "accuracy", 0.9)
    proj_speed = registry.get_field(item_id, "proj_speed", 14.0)
    max_range = registry.get_field(item_id, "range", 10.0)
    pchar = registry.get_field(item_id, "proj_char", ".")
    pcolor = registry.get_field(item_id, "proj_color", (255, 255, 150))
    pellets = 1
    item_data = registry.get_item(item_id)
    if item_data:
        pellets = int(item_data.get("pellets", 1))

    # Build result — ranged uses muzzle flash, NOT melee rect
    result = AttackResult(
        melee_active=False,
        muzzle_flash_timer=0.08,
        muzzle_flash_start=(cx, cy),
        muzzle_flash_end=(cx + dx_norm * 1.2, cy + dy_norm * 1.2),
    )

    # Muzzle flash particles
    from logic.particles import ParticleManager
    pm = app.world.res(ParticleManager)
    if pm:
        muzzle_x = cx + dx_norm * 0.5
        muzzle_y = cy + dy_norm * 0.5
        pm.emit_burst(muzzle_x, muzzle_y, count=4, color=(255, 200, 80),
                      speed=2.0, life=0.12, size=1.5, spread=0.6, angle=angle)

    # Spawn projectile(s)
    for _ in range(pellets):
        spread = (1.0 - accuracy) * 0.35
        a_offset = random.uniform(-spread, spread)
        final_angle = angle + a_offset
        pdx = math.cos(final_angle)
        pdy = math.sin(final_angle)

        eid = app.world.spawn()
        sx = cx + pdx * 0.5
        sy = cy + pdy * 0.5
        app.world.add(eid, Position(x=sx, y=sy, zone=player_pos.zone))
        app.world.add(eid, Projectile(
            owner_eid=player_eid,
            damage=total_dmg / pellets if pellets > 1 else total_dmg,
            speed=proj_speed,
            dx=pdx,
            dy=pdy,
            max_range=max_range,
            char=pchar,
            color=pcolor,
        ))

    print(f"[RANGED] Fired {pellets} round(s) — {registry.display_name(item_id)}")
    return result
