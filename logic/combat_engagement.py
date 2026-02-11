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
from logic.brains._helpers import (
    find_player, dist_pos, hp_ratio,
    move_toward, move_away, strafe, face_toward, run_idle,
    should_engage, try_dodge, try_heal,
    reset_faction_on_return,
)


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
    if "origin" not in s:
        s["origin"] = (pos.x, pos.y)
    s.setdefault("mode", "idle")

    is_ranged = atk_cfg.attack_type == "ranged"

    # ── Sensor throttle ──────────────────────────────────────────────
    sensor_due = (game_time - threat.last_sensor_time) >= threat.sensor_interval

    if sensor_due:
        threat.last_sensor_time = game_time

        # Faction gate — not hostile? Just wander.
        if not should_engage(world, eid):
            s["mode"] = "idle"
            if patrol:
                run_idle(patrol, pos, vel, s, dt)
            else:
                vel.x, vel.y = 0.0, 0.0
            return

        p_eid, p_pos = find_player(world)
        if p_pos is None or p_pos.zone != pos.zone:
            s["p_eid"] = None
            s["p_pos"] = None
            if patrol:
                run_idle(patrol, pos, vel, s, dt)
            else:
                vel.x, vel.y = 0.0, 0.0
            return

        # Cache sensor results for inter-frame movement
        s["p_eid"] = p_eid
        s["p_pos"] = (p_pos.x, p_pos.y)

        # Defense behaviors
        if s["mode"] in ("chase", "attack"):
            if try_dodge(world, eid, brain, pos, vel, s, dt, game_time):
                return
            try_heal(world, eid, brain, s, game_time)

        dist = dist_pos(pos, p_pos)
        ox, oy = s["origin"]
        home_dist = math.hypot(pos.x - ox, pos.y - oy)
        cur_hp_ratio = hp_ratio(world, eid)
        mode = s["mode"]

        can_flee = threat.flee_threshold > 0.0

        if mode == "idle":
            if dist <= threat.aggro_radius:
                s["mode"] = "chase"
            else:
                if patrol:
                    run_idle(patrol, pos, vel, s, dt)
                else:
                    vel.x, vel.y = 0.0, 0.0
                return

        elif mode == "chase":
            if can_flee and cur_hp_ratio <= threat.flee_threshold:
                s["mode"] = "flee"
            elif home_dist > threat.leash_radius:
                s["mode"] = "return"
            elif is_ranged and dist <= atk_cfg.range * 1.1:
                s["mode"] = "attack"
            elif not is_ranged and dist <= atk_cfg.range:
                s["mode"] = "attack"

        elif mode == "attack":
            if can_flee and cur_hp_ratio <= threat.flee_threshold:
                s["mode"] = "flee"
            elif is_ranged and dist > atk_cfg.range * 1.8:
                s["mode"] = "chase"
            elif not is_ranged and dist > atk_cfg.range * 1.6:
                s["mode"] = "chase"
            elif not is_ranged and home_dist > threat.leash_radius:
                s["mode"] = "return"

            # Fire / strike when ready (timestamp cooldown)
            if s.get("attack_until", 0.0) <= game_time and p_eid is not None:
                if is_ranged:
                    from logic.combat import npc_ranged_attack
                    npc_ranged_attack(world, eid, p_eid)
                else:
                    from logic.combat import npc_melee_attack
                    npc_melee_attack(world, eid, p_eid)
                s["attack_until"] = game_time + atk_cfg.cooldown

        elif mode == "flee":
            if cur_hp_ratio > threat.flee_threshold * 2.5 or dist > threat.aggro_radius:
                s["mode"] = "return"

        elif mode == "return":
            if math.hypot(pos.x - ox, pos.y - oy) < 1.0:
                s["mode"] = "idle"
                reset_faction_on_return(world, eid)
            elif dist <= threat.aggro_radius * 0.6:
                s["mode"] = "chase"

    # ── Cheap per-frame movement output ──────────────────────────────
    mode = s["mode"]
    p_cache = s.get("p_pos")
    ox, oy = s.get("origin", (pos.x, pos.y))
    p_speed = patrol.speed if patrol else 2.0

    if mode == "idle":
        if patrol:
            run_idle(patrol, pos, vel, s, dt)
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
            else:
                s.setdefault("strafe_dir", 1)
                s["strafe_timer"] = s.get("strafe_timer", 0.0) - dt
                if s["strafe_timer"] <= 0:
                    s["strafe_timer"] = random.uniform(0.8, 2.0)
                    s["strafe_dir"] *= -1
                strafe(pos, vel, p_proxy, p_speed * 0.6, s["strafe_dir"])
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
            run_idle(patrol, pos, vel, s, dt)
        else:
            vel.x, vel.y = 0.0, 0.0


# Register under all three brain kinds so existing entities work unchanged
register_brain("hostile_melee", _combat_brain)
register_brain("hostile_ranged", _combat_brain)
register_brain("guard", _combat_brain)
