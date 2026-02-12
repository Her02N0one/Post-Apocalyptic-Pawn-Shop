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
from components import Faction, Health, Hurtbox
from logic.brains._helpers import (
    find_player, dist_pos, hp_ratio,
    move_toward, move_away, strafe, face_toward, run_idle,
    should_engage, try_dodge, try_heal,
    reset_faction_on_return,
)


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

    CLEAR = 0.6  # tiles — how close to the line counts as blocking

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
            else:
                if patrol:
                    run_idle(patrol, pos, vel, c, dt)
                else:
                    vel.x, vel.y = 0.0, 0.0
                return

        elif mode == "chase":
            if can_flee and cur_hp_ratio <= threat.flee_threshold:
                c["mode"] = "flee"
            elif home_dist > threat.leash_radius:
                c["mode"] = "return"
            elif is_ranged and dist <= atk_cfg.range * 1.1:
                c["mode"] = "attack"
            elif not is_ranged and dist <= atk_cfg.range:
                c["mode"] = "attack"

        elif mode == "attack":
            if can_flee and cur_hp_ratio <= threat.flee_threshold:
                c["mode"] = "flee"
            elif is_ranged and dist > atk_cfg.range * 1.8:
                c["mode"] = "chase"
            elif not is_ranged and dist > atk_cfg.range * 1.6:
                c["mode"] = "chase"
            elif not is_ranged and home_dist > threat.leash_radius:
                c["mode"] = "return"

            # Fire / strike when ready (timestamp cooldown)
            if c.get("attack_until", 0.0) <= game_time and p_eid is not None:
                if is_ranged:
                    # Check line of fire — strafe to reposition if ally is in the way
                    if _ally_in_line_of_fire(world, eid, pos, p_pos.x, p_pos.y):
                        c["_los_blocked"] = True
                    else:
                        c["_los_blocked"] = False
                        from logic.combat import npc_ranged_attack
                        npc_ranged_attack(world, eid, p_eid)
                        c["attack_until"] = game_time + atk_cfg.cooldown
                else:
                    from logic.combat import npc_melee_attack
                    npc_melee_attack(world, eid, p_eid)
                    c["attack_until"] = game_time + atk_cfg.cooldown

        elif mode == "flee":
            if cur_hp_ratio > threat.flee_threshold * 2.5 or dist > threat.aggro_radius:
                c["mode"] = "return"

        elif mode == "return":
            if math.hypot(pos.x - ox, pos.y - oy) < 1.0:
                c["mode"] = "idle"
                reset_faction_on_return(world, eid)
            elif dist <= threat.aggro_radius * 0.6:
                c["mode"] = "chase"

    # ── Cheap per-frame movement output ──────────────────────────────
    mode = c["mode"]
    p_cache = c.get("p_pos")
    ox, oy = c.get("origin", (pos.x, pos.y))
    p_speed = patrol.speed if patrol else 2.0

    if mode == "idle":
        if patrol:
            run_idle(patrol, pos, vel, c, dt)
        else:
            vel.x, vel.y = 0.0, 0.0

    elif mode == "chase" and p_cache:
        chase_mult = 1.2 if is_ranged else 1.4
        move_toward(pos, vel, p_cache[0], p_cache[1], p_speed * chase_mult)
        face_toward(world, eid, type("P", (), {"x": p_cache[0], "y": p_cache[1]})())

    elif mode == "attack" and p_cache:
        px, py = p_cache
        p_proxy = type("P", (), {"x": px, "y": py})()
        face_toward(world, eid, p_proxy)
        dist = math.hypot(pos.x - px, pos.y - py)

        if is_ranged:
            # Ranged: kite if too close, strafe otherwise
            too_close = atk_cfg.range * 0.4
            if dist < too_close:
                move_away(pos, vel, px, py, p_speed * 1.3)
            elif c.get("_los_blocked"):
                # Ally in the firing line — strafe aggressively to clear
                c.setdefault("strafe_dir", 1)
                strafe(pos, vel, p_proxy, p_speed * 1.2, c["strafe_dir"])
                # Flip direction every 0.4-0.8s when LOS-blocked
                c["strafe_timer"] = c.get("strafe_timer", 0.0) - dt
                if c["strafe_timer"] <= 0:
                    c["strafe_timer"] = random.uniform(0.4, 0.8)
                    c["strafe_dir"] *= -1
            else:
                c.setdefault("strafe_dir", 1)
                c["strafe_timer"] = c.get("strafe_timer", 0.0) - dt
                if c["strafe_timer"] <= 0:
                    c["strafe_timer"] = random.uniform(0.8, 2.0)
                    c["strafe_dir"] *= -1
                strafe(pos, vel, p_proxy, p_speed * 0.6, c["strafe_dir"])
        else:
            # Melee: close in or stand
            if dist > atk_cfg.range * 0.5:
                move_toward(pos, vel, px, py, p_speed * 0.5)
            else:
                vel.x, vel.y = 0.0, 0.0

    elif mode == "flee" and p_cache:
        move_away(pos, vel, p_cache[0], p_cache[1], p_speed * 1.3)

    elif mode == "return":
        move_toward(pos, vel, ox, oy, p_speed * 1.5 if not is_ranged else p_speed)

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
