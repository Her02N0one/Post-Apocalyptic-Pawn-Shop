"""logic/combat/damage.py — Canonical damage application and death sequence.

Every code-path that deals damage (melee hits, projectile impacts,
environmental effects) should funnel through ``apply_damage()`` so
that knockback, hit-flash, particles, and logging are consistent.

``handle_death()`` centralises the death pipeline (particles → loot → kill)
so all damage sources share the same death animation + loot logic.
"""

from __future__ import annotations
import math
import random
from components import (
    Health, Position, Velocity, HitFlash, Identity,
    CombatStats, Player, Loot,
)
from logic.particles import ParticleManager
from core.tuning import get as _tun, section as _tun_sec
from logic.faction_ops import entity_display_name


def apply_damage(
    world,
    attacker_eid: int,
    defender_eid: int,
    raw_damage: float,
    *,
    defender_armor: float | None = None,
    knockback: float = 3.0,
    knockback_dir: tuple[float, float] | None = None,
    crit_chance: float = 0.0,
    crit_mult: float = 1.5,
    particle_preset: str = "hit_normal",
    crit_particle_preset: str = "hit_crit",
    log_prefix: str = "COMBAT",
) -> tuple[float, bool, bool]:
    """Deal damage to *defender_eid*.

    Returns ``(damage_dealt, is_crit, is_dead)``.

    Parameters
    ----------
    raw_damage
        Pre-armour damage value (already includes weapon bonus, falloff, etc.)
    defender_armor
        Override armour value.  If *None*, reads from defender's CombatStats comp.
    knockback_dir
        ``(dx, dy)`` unit vector for knockback.  If *None*, computed from
        attacker → defender positions.
    """
    if not world.has(defender_eid, Health):
        return 0.0, False, False
    health = world.get(defender_eid, Health)

    # ── Armour subtraction ───────────────────────────────────────────
    if defender_armor is None:
        if world.has(defender_eid, CombatStats):
            defender_armor = world.get(defender_eid, CombatStats).defense
        else:
            defender_armor = 0.0
    min_dmg = _tun("combat.melee", "min_base_damage", 1.0)
    damage = max(min_dmg, raw_damage - defender_armor)

    # ── Crit roll ────────────────────────────────────────────────────
    is_crit = crit_chance > 0 and random.random() < crit_chance
    if is_crit:
        damage *= crit_mult

    # ── Apply to HP ──────────────────────────────────────────────────
    health.current -= damage

    # ── Knockback ────────────────────────────────────────────────────
    if knockback > 0 and world.has(defender_eid, Position) and world.has(defender_eid, Velocity):
        def_pos = world.get(defender_eid, Position)
        def_vel = world.get(defender_eid, Velocity)
        if knockback_dir is not None:
            dx, dy = knockback_dir
        else:
            att_pos = world.get(attacker_eid, Position)
            if att_pos is not None:
                dx = def_pos.x - att_pos.x
                dy = def_pos.y - att_pos.y
                mag = math.hypot(dx, dy)
                if mag > 0.01:
                    dx /= mag
                    dy /= mag
                else:
                    dx, dy = 0.0, 0.0
            else:
                dx, dy = 0.0, 0.0
        def_vel.x = dx * knockback
        def_vel.y = dy * knockback

    # ── Hit flash ────────────────────────────────────────────────────
    flash_dur = _tun("combat.melee", "hit_flash_duration", 0.1)
    if not world.has(defender_eid, HitFlash):
        world.add(defender_eid, HitFlash(remaining=flash_dur))
    else:
        world.get(defender_eid, HitFlash).remaining = flash_dur

    # ── Particles ────────────────────────────────────────────────────
    pm = world.res(ParticleManager)
    if pm and world.has(defender_eid, Position):
        dp = world.get(defender_eid, Position)
        preset = crit_particle_preset if is_crit else particle_preset
        ps = _tun_sec(f"particles.{preset}")
        hit_color = tuple(ps.get("color", [255, 50, 50]))
        pm.emit_burst(
            dp.x + 0.4, dp.y + 0.4,
            count=ps.get("count", 6),
            color=hit_color,
            speed=ps.get("speed", 2.5),
            life=ps.get("life", 0.3),
            size=ps.get("size", 2.0),
        )

    # ── Log ──────────────────────────────────────────────────────────
    attacker_name = entity_display_name(world, attacker_eid)
    defender_name = entity_display_name(world, defender_eid)
    crit_tag = " [CRIT]" if is_crit else ""
    print(f"[{log_prefix}] {attacker_name} hit {defender_name} for "
          f"{damage:.0f} damage{crit_tag} (HP: {health.current:.0f}/{health.maximum})")

    is_dead = health.current <= 0
    return damage, is_crit, is_dead


# ── Death sequence ───────────────────────────────────────────────────

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
        ds = _tun_sec("particles.death")
        pm.emit_burst(dp.x + 0.4, dp.y + 0.4,
                      count=ds.get("count", 20),
                      color=tuple(ds.get("color", [180, 30, 30])),
                      speed=ds.get("speed", 3.5),
                      life=ds.get("life", 0.6),
                      size=ds.get("size", 2.5),
                      gravity=ds.get("gravity", 4.0))
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
