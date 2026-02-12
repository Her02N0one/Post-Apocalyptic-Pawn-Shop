"""logic/combat_engagement.py — Unified combat engagement system.

Replaces the three near-duplicate brain modules (hostile_melee,
hostile_ranged, guard) with a single data-driven system.

Entities with Brain + Threat + AttackConfig get an idle → chase →
attack → flee → return FSM driven entirely by component data:

  - **melee vs ranged** is determined by ``AttackConfig.attack_type``.
    Melee entities close distance; ranged ones maintain standoff and strafe.
  - **guard vs hostile** is determined by ``Threat.flee_threshold``.
    Guards have ``flee_threshold == 0`` so they never flee.

All sensor work is throttled to ``Threat.sensor_interval``.
"""

from __future__ import annotations
import random
import math
from core.ecs import World
from components import (
    Brain, Patrol, Threat, AttackConfig,
    Position, Velocity, GameClock, Lod,
)
from logic.brains import register_brain
from components import Faction, Health, Hurtbox, Identity
from components.dev_log import DevLog
from logic.brains._helpers import (
    find_player, dist_pos, hp_ratio,
    move_toward, move_toward_pathfind, move_away, strafe, face_toward,
    run_idle, should_engage, try_dodge, try_heal,
    reset_faction_on_return,
)
from core.tuning import get as _tun
from core.events import EventBus, AttackIntent


def _log(world: World, eid: int, cat: str, msg: str, t: float = 0.0, **kw):
    log = world.res(DevLog)
    if log is None:
        return
    ident = world.get(eid, Identity)
    name = ident.name if ident else f"e{eid}"
    log.record(eid, cat, msg, name=name, t=t, **kw)


def _ally_near_target(world: World, eid: int, pos, tx: float, ty: float,
                      melee_range: float) -> bool:
    """Return True if a same-faction ally is within *melee_range* of the target.

    Prevents melee attackers from striking when an ally is standing
    right next to the target and could be caught in the swing.
    """
    faction = world.get(eid, Faction)
    if faction is None:
        return False
    group = faction.group
    threshold = melee_range * _tun("combat.engagement", "ally_near_target_factor", 0.8)

    for aid, apos in world.all_of(Position):
        if aid == eid:
            continue
        if apos.zone != pos.zone:
            continue
        af = world.get(aid, Faction)
        if af is None or af.group != group:
            continue
        if not world.has(aid, Health):
            continue
        # Is this ally close to the target?
        d = math.hypot(apos.x - tx, apos.y - ty)
        if d < threshold:
            return True
    return False


def _ally_in_line_of_fire(world: World, eid: int, pos, tx: float, ty: float) -> bool:
    """Return True if a same-faction ally is between *eid* and (tx, ty).

    Performs a simple capsule test: for each ally, project its centre
    onto the shooter→target line segment.  If the closest point on
    the segment is within ~0.6 tiles of the ally, they're in the way.
    """
    faction = world.get(eid, Faction)
    if faction is None:
        return False
    group = faction.group

    # Direction vector and squared length of the segment
    dx = tx - pos.x
    dy = ty - pos.y
    seg_len_sq = dx * dx + dy * dy
    if seg_len_sq < 0.01:
        return False

    CLEAR = _tun("combat.engagement", "line_of_fire_clearance", 0.6)

    for aid, apos in world.all_of(Position):
        if aid == eid:
            continue
        if apos.zone != pos.zone:
            continue
        af = world.get(aid, Faction)
        if af is None or af.group != group:
            continue
        if not world.has(aid, Health):
            continue

        # Project ally onto shooter→target segment
        ax = apos.x - pos.x
        ay = apos.y - pos.y
        t = (ax * dx + ay * dy) / seg_len_sq
        if t < 0.05 or t > 0.95:      # behind shooter or past target
            continue
        # Closest point on segment
        cx = t * dx
        cy = t * dy
        dist_sq = (ax - cx) ** 2 + (ay - cy) ** 2
        if dist_sq < CLEAR * CLEAR:
            return True
    return False


# ── Shared FSM ───────────────────────────────────────────────────────

def _combat_brain(world: World, eid: int, brain: Brain, dt: float,
                  game_time: float = 0.0):
    """Unified combat FSM: idle → chase → attack → flee → return."""
    pos = world.get(eid, Position)
    vel = world.get(eid, Velocity)
    if not pos or not vel:
        return

    patrol = world.get(eid, Patrol)
    threat = world.get(eid, Threat)
    atk_cfg = world.get(eid, AttackConfig)
    if not threat or not atk_cfg:
        return

    s = brain.state
    c = s.setdefault("combat", {})
    if "origin" not in c:
        c["origin"] = (pos.x, pos.y)
    c.setdefault("mode", "idle")

    is_ranged = atk_cfg.attack_type == "ranged"

    # ── Sensor throttle ──────────────────────────────────────────────
    sensor_due = (game_time - threat.last_sensor_time) >= threat.sensor_interval

    if sensor_due:
        threat.last_sensor_time = game_time

        # Faction gate — not hostile? Just wander.
        if not should_engage(world, eid):
            c["mode"] = "idle"
            if patrol:
                run_idle(patrol, pos, vel, c, dt)
            else:
                vel.x, vel.y = 0.0, 0.0
            return

        p_eid, p_pos = find_player(world)
        if p_pos is None or p_pos.zone != pos.zone:
            c["p_eid"] = None
            c["p_pos"] = None
            if c["mode"] != "idle":
                _log(world, eid, "combat", "target lost → idle", game_time)
            if patrol:
                run_idle(patrol, pos, vel, c, dt)
            else:
                vel.x, vel.y = 0.0, 0.0
            return

        # Cache sensor results for inter-frame movement
        c["p_eid"] = p_eid
        c["p_pos"] = (p_pos.x, p_pos.y)

        # Defense behaviors
        if c["mode"] in ("chase", "attack"):
            if try_dodge(world, eid, brain, pos, vel, c, dt, game_time):
                return
            try_heal(world, eid, brain, c, game_time)

        dist = dist_pos(pos, p_pos)
        ox, oy = c.get("origin", (pos.x, pos.y))
        home_dist = math.hypot(pos.x - ox, pos.y - oy)
        cur_hp_ratio = hp_ratio(world, eid)
        mode = c["mode"]

        can_flee = threat.flee_threshold > 0.0

        if mode == "idle":
            if dist <= threat.aggro_radius:
                c["mode"] = "chase"
                _log(world, eid, "combat", f"idle → chase (dist={dist:.1f})", game_time)
            else:
                if patrol:
                    run_idle(patrol, pos, vel, c, dt)
                else:
                    vel.x, vel.y = 0.0, 0.0
                return

        elif mode == "chase":
            if can_flee and cur_hp_ratio <= threat.flee_threshold:
                c["mode"] = "flee"
                _log(world, eid, "combat", f"chase → flee (hp={cur_hp_ratio:.0%})", game_time)
            elif home_dist > threat.leash_radius:
                c["mode"] = "return"
                _log(world, eid, "combat", f"chase → return (leash={home_dist:.1f})", game_time)
            elif is_ranged and dist <= atk_cfg.range * _tun("combat.engagement", "ranged_chase_to_attack", 1.1):
                c["mode"] = "attack"
                _log(world, eid, "combat", f"chase → attack (ranged, dist={dist:.1f})", game_time)
            elif not is_ranged and dist <= atk_cfg.range:
                c["mode"] = "attack"
                _log(world, eid, "combat", f"chase → attack (melee, dist={dist:.1f})", game_time)

        elif mode == "attack":
            if can_flee and cur_hp_ratio <= threat.flee_threshold:
                c["mode"] = "flee"
                _log(world, eid, "combat", f"attack → flee (hp={cur_hp_ratio:.0%})", game_time)
            elif home_dist > threat.leash_radius:
                c["mode"] = "return"
                _log(world, eid, "combat", f"attack → return (leash={home_dist:.1f})", game_time)
            elif is_ranged and dist > atk_cfg.range * _tun("combat.engagement", "ranged_attack_to_chase", 1.8):
                c["mode"] = "chase"
                _log(world, eid, "combat", f"attack → chase (too far, dist={dist:.1f})", game_time)
            elif not is_ranged and dist > atk_cfg.range * _tun("combat.engagement", "melee_attack_to_chase", 1.6):
                c["mode"] = "chase"
                _log(world, eid, "combat", f"attack → chase (melee lost range)", game_time)

            # Fire / strike when ready (timestamp cooldown)
            if c.get("attack_until", 0.0) <= game_time and p_eid is not None:
                if is_ranged:
                    # Check line of fire — strafe to reposition if ally is in the way
                    if _ally_in_line_of_fire(world, eid, pos, p_pos.x, p_pos.y):
                        c["_los_blocked"] = True
                        _log(world, eid, "combat", "LOS blocked by ally, strafing", game_time)
                    else:
                        c["_los_blocked"] = False
                        bus = world.res(EventBus)
                        if bus:
                            bus.emit(AttackIntent(attacker_eid=eid, target_eid=p_eid, attack_type="ranged"))
                        else:
                            from logic.combat import npc_ranged_attack
                            npc_ranged_attack(world, eid, p_eid)
                        c["attack_until"] = game_time + atk_cfg.cooldown
                        _log(world, eid, "attack", "fired ranged attack", game_time)
                else:
                    # Check for allies near target before swinging
                    if _ally_near_target(world, eid, pos, p_pos.x, p_pos.y, atk_cfg.range):
                        _log(world, eid, "combat", "melee held — ally near target", game_time)
                    else:
                        bus = world.res(EventBus)
                        if bus:
                            bus.emit(AttackIntent(attacker_eid=eid, target_eid=p_eid, attack_type="melee"))
                        else:
                            from logic.combat import npc_melee_attack
                            npc_melee_attack(world, eid, p_eid)
                        c["attack_until"] = game_time + atk_cfg.cooldown
                        _log(world, eid, "attack", "melee strike", game_time)

        elif mode == "flee":
            if cur_hp_ratio > threat.flee_threshold * _tun("combat.engagement", "flee_recovery_mult", 2.5) or dist > threat.aggro_radius:
                c["mode"] = "return"
                _log(world, eid, "combat", "flee → return", game_time)

        elif mode == "return":
            if math.hypot(pos.x - ox, pos.y - oy) < _tun("combat.engagement", "return_arrive_dist", 1.0):
                c["mode"] = "idle"
                reset_faction_on_return(world, eid)
                _log(world, eid, "combat", "returned home → idle", game_time)
            elif dist <= threat.aggro_radius * _tun("combat.engagement", "return_reaggro_factor", 0.6):
                c["mode"] = "chase"
                _log(world, eid, "combat", "return interrupted → chase", game_time)

    # ── Cheap per-frame movement output ──────────────────────────────
    mode = c["mode"]
    p_cache = c.get("p_pos")
    ox, oy = c.get("origin", (pos.x, pos.y))
    p_speed = patrol.speed if patrol else _tun("combat.engagement", "fallback_patrol_speed", 2.0)

    if mode == "idle":
        if patrol:
            run_idle(patrol, pos, vel, c, dt)
        else:
            vel.x, vel.y = 0.0, 0.0

    elif mode == "chase" and p_cache:
        chase_mult = _tun("combat.engagement", "chase_mult_ranged", 1.2) if is_ranged \
            else _tun("combat.engagement", "chase_mult_melee", 1.4)
        move_toward_pathfind(pos, vel, p_cache[0], p_cache[1],
                             p_speed * chase_mult, c, game_time)
        face_toward(world, eid, type("P", (), {"x": p_cache[0], "y": p_cache[1]})())

    elif mode == "attack" and p_cache:
        px, py = p_cache
        p_proxy = type("P", (), {"x": px, "y": py})()
        face_toward(world, eid, p_proxy)
        dist = math.hypot(pos.x - px, pos.y - py)

        if is_ranged:
            # Ranged: kite if too close, strafe otherwise
            too_close = atk_cfg.range * _tun("combat.engagement", "kite_close_factor", 0.4)
            if dist < too_close:
                move_away(pos, vel, px, py, p_speed * _tun("combat.engagement", "kite_away_speed_mult", 1.3))
            elif c.get("_los_blocked"):
                # Ally in the firing line — strafe aggressively to clear
                c.setdefault("strafe_dir", 1)
                strafe(pos, vel, p_proxy, p_speed * _tun("combat.engagement", "strafe_speed_los_mult", 1.2), c["strafe_dir"])
                # Flip direction every 0.4-0.8s when LOS-blocked
                c["strafe_timer"] = c.get("strafe_timer", 0.0) - dt
                if c["strafe_timer"] <= 0:
                    c["strafe_timer"] = random.uniform(
                        _tun("combat.engagement", "strafe_timer_los_min", 0.4),
                        _tun("combat.engagement", "strafe_timer_los_max", 0.8),
                    )
                    c["strafe_dir"] *= -1
            else:
                c.setdefault("strafe_dir", 1)
                c["strafe_timer"] = c.get("strafe_timer", 0.0) - dt
                if c["strafe_timer"] <= 0:
                    c["strafe_timer"] = random.uniform(
                        _tun("combat.engagement", "strafe_timer_normal_min", 0.8),
                        _tun("combat.engagement", "strafe_timer_normal_max", 2.0),
                    )
                    c["strafe_dir"] *= -1
                strafe(pos, vel, p_proxy, p_speed * _tun("combat.engagement", "strafe_speed_normal_mult", 0.6), c["strafe_dir"])
        else:
            # Melee: close in or stand
            if dist > atk_cfg.range * _tun("combat.engagement", "melee_close_in_factor", 0.5):
                move_toward(pos, vel, px, py, p_speed * _tun("combat.engagement", "melee_close_in_speed", 0.5))
            else:
                vel.x, vel.y = 0.0, 0.0

    elif mode == "flee" and p_cache:
        move_away(pos, vel, p_cache[0], p_cache[1], p_speed * _tun("combat.engagement", "flee_speed_mult", 1.3))

    elif mode == "return":
        ret_mult = _tun("combat.engagement", "return_speed_mult_melee", 1.5) if not is_ranged else 1.0
        move_toward_pathfind(pos, vel, ox, oy,
                             p_speed * ret_mult,
                             c, game_time)

    else:
        if patrol:
            run_idle(patrol, pos, vel, c, dt)
        else:
            vel.x, vel.y = 0.0, 0.0


def run_combat_brain(world: World, eid: int, brain: Brain, dt: float,
                     game_time: float = 0.0) -> None:
    _combat_brain(world, eid, brain, dt, game_time)


# Register under all three brain kinds so existing entities work unchanged
register_brain("hostile_melee", _combat_brain)
register_brain("hostile_ranged", _combat_brain)
register_brain("guard", _combat_brain)
