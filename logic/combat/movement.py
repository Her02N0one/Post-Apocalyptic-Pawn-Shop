"""logic/combat/movement.py — Velocity-producing movement behaviours.

Each public function takes minimal parameters and writes directly
to ``vel`` in place.  A mutable ``state`` dict is threaded through
so that sub-state timers persist across frames.

No World access is needed — every input is pre-resolved by the caller
(the combat_engagement orchestrator or the goal system).
"""

from __future__ import annotations
import random
import math

from core.tuning import get as _tun
from logic.ai.steering import (
    move_toward, move_toward_pathfind, move_away, strafe, run_idle,
)


# ── Simple modes ─────────────────────────────────────────────────────

def idle(patrol, pos, vel, state: dict, dt: float):
    """Patrol-envelope wander while not engaged."""
    if patrol:
        run_idle(patrol, pos, vel, state, dt)
    else:
        vel.x, vel.y = 0.0, 0.0


def chase(pos, vel, tx: float, ty: float, speed: float,
          state: dict, game_time: float):
    """Pathfind toward target position."""
    move_toward_pathfind(pos, vel, tx, ty, speed, state, game_time)


def flee(pos, vel, tx: float, ty: float, speed: float):
    """Move directly away from threat."""
    move_away(pos, vel, tx, ty, speed)


def return_home(pos, vel, ox: float, oy: float, speed: float,
                state: dict, game_time: float):
    """Navigate back to origin via pathfinding."""
    move_toward_pathfind(pos, vel, ox, oy, speed, state, game_time)


# ── Ranged attack movement ──────────────────────────────────────────

def ranged_attack(pos, vel, tx: float, ty: float, dist: float,
                  atk_range: float, speed: float, state: dict,
                  dt: float, *, wall_blocked: bool = False,
                  los_blocked: bool = False, game_time: float = 0.0,
                  repos_target: tuple[float, float] | None = None):
    """Ranged attack positioning: kite / strafe / reposition."""
    target_proxy = type("P", (), {"x": tx, "y": ty})()

    if wall_blocked:
        # Pathfind to a flanking position with LOS (if found),
        # otherwise pathfind toward the target as fallback.
        if repos_target:
            rx, ry = repos_target
            d_repos = math.hypot(pos.x - rx, pos.y - ry)
            if d_repos < 0.5:
                # Arrived at reposition spot — stop and wait for
                # next sensor tick to clear wall_blocked
                vel.x, vel.y = 0.0, 0.0
            else:
                move_toward_pathfind(
                    pos, vel, rx, ry,
                    speed * _tun("combat.engagement",
                                 "reposition_speed_mult", 1.4),
                    state, game_time,
                )
        else:
            move_toward_pathfind(
                pos, vel, tx, ty,
                speed * _tun("combat.engagement",
                             "chase_mult_ranged", 1.2),
                state, game_time,
            )
        return

    # ── Range maintenance — stay in optimal band ─────────────────
    ideal_min = atk_range * _tun("combat.engagement",
                                 "ranged_ideal_min_factor", 0.5)
    ideal_max = atk_range * _tun("combat.engagement",
                                 "ranged_ideal_max_factor", 0.85)

    too_close = atk_range * _tun("combat.engagement",
                                 "kite_close_factor", 0.35)
    if dist < too_close:
        # Panic kite — way too close
        move_away(pos, vel, tx, ty,
                  speed * _tun("combat.engagement",
                               "kite_away_speed_mult", 1.5))
    elif dist < ideal_min:
        # Back away while strafing to reach ideal range
        _strafe_with_drift(pos, vel, target_proxy, speed, state, dt,
                           drift=-0.5)  # negative = away
    elif dist > ideal_max and dist < atk_range * 1.3:
        # Close in slightly while strafing
        _strafe_with_drift(pos, vel, target_proxy, speed, state, dt,
                           drift=0.4)  # positive = toward
    elif los_blocked:
        _do_strafe(pos, vel, target_proxy, speed,
                   _tun("combat.engagement", "strafe_speed_los_mult", 1.2),
                   state, dt,
                   min_t=_tun("combat.engagement",
                              "strafe_timer_los_min", 0.4),
                   max_t=_tun("combat.engagement",
                              "strafe_timer_los_max", 0.8))
    else:
        _do_strafe(pos, vel, target_proxy, speed,
                   _tun("combat.engagement",
                        "strafe_speed_normal_mult", 0.6),
                   state, dt,
                   min_t=_tun("combat.engagement",
                              "strafe_timer_normal_min", 0.8),
                   max_t=_tun("combat.engagement",
                              "strafe_timer_normal_max", 2.0))


def _do_strafe(pos, vel, target_proxy, speed: float, speed_mult: float,
               state: dict, dt: float, min_t: float, max_t: float):
    """Strafe around target with periodic direction changes."""
    state.setdefault("strafe_dir", 1)
    state["strafe_timer"] = state.get("strafe_timer", 0.0) - dt
    if state["strafe_timer"] <= 0:
        state["strafe_timer"] = random.uniform(min_t, max_t)
        state["strafe_dir"] *= -1
    strafe(pos, vel, target_proxy, speed * speed_mult, state["strafe_dir"])


def _strafe_with_drift(pos, vel, target_proxy, speed: float,
                       state: dict, dt: float, drift: float = 0.0):
    """Strafe while drifting toward/away from target for range maintenance.

    *drift* < 0 means away, > 0 means toward.  The tangential
    (strafing) component is blended with a radial component so the
    NPC adjusts distance while still moving laterally.
    """
    state.setdefault("strafe_dir", 1)
    state["strafe_timer"] = state.get("strafe_timer", 0.0) - dt
    if state["strafe_timer"] <= 0:
        state["strafe_timer"] = random.uniform(0.6, 1.5)
        state["strafe_dir"] *= -1

    # Radial direction (toward target)
    dx = target_proxy.x - pos.x
    dy = target_proxy.y - pos.y
    d = math.hypot(dx, dy)
    if d < 0.1:
        vel.x, vel.y = 0.0, 0.0
        return
    nx, ny = dx / d, dy / d
    # Tangential direction (strafe)
    cdir = state["strafe_dir"]
    tang_x = -ny * cdir
    tang_y = nx * cdir
    # Blend: mostly tangential, some radial drift
    bx = tang_x * 0.7 + nx * drift
    by = tang_y * 0.7 + ny * drift
    blen = math.hypot(bx, by)
    spd = speed * 0.8
    if blen > 0.01:
        vel.x = (bx / blen) * spd
        vel.y = (by / blen) * spd
    else:
        vel.x, vel.y = 0.0, 0.0


# ── Melee attack sub-FSM ────────────────────────────────────────────

def melee_attack(pos, vel, tx: float, ty: float, dist: float,
                 atk_range: float, speed: float, state: dict,
                 dt: float):
    """Melee sub-FSM: approach -> circle -> feint -> lunge -> retreat.

    Writes to *vel* and mutates *state* dict.

    State keys:
        melee_sub, melee_circle_timer, melee_circle_dir,
        melee_feint_timer, melee_feint_phase,
        melee_retreat_timer, melee_retreat_dir, _melee_just_hit.
    """
    sub = state.get("melee_sub", "approach")
    ideal_r = atk_range * _tun("combat.engagement", "melee_circle_radius", 1.6)

    if sub == "approach":
        _melee_approach(pos, vel, tx, ty, dist, ideal_r, speed, state)
    elif sub == "circle":
        _melee_circle(pos, vel, tx, ty, dist, ideal_r, atk_range, speed,
                      state, dt)
    elif sub == "feint":
        _melee_feint(pos, vel, tx, ty, dist, atk_range, speed, state, dt)
    elif sub == "lunge":
        _melee_lunge(pos, vel, tx, ty, dist, atk_range, speed, state)
    elif sub == "retreat":
        _melee_retreat(pos, vel, tx, ty, dist, speed, state, dt)
    else:
        state["melee_sub"] = "approach"


def _melee_approach(pos, vel, tx, ty, dist, ideal_r, speed, state):
    if dist > ideal_r * 1.2:
        move_toward(pos, vel, tx, ty,
                    speed * _tun("combat.engagement",
                                 "melee_close_in_speed", 1.2))
    else:
        state["melee_sub"] = "circle"
        state["melee_circle_timer"] = random.uniform(
            _tun("combat.engagement", "melee_circle_time_min", 1.2),
            _tun("combat.engagement", "melee_circle_time_max", 3.0),
        )
        state.setdefault("melee_circle_dir", random.choice((-1, 1)))


def _melee_circle(pos, vel, tx, ty, dist, ideal_r, atk_range, speed,
                  state, dt):
    state["melee_circle_timer"] = state.get("melee_circle_timer", 1.0) - dt
    circ_speed = speed * _tun("combat.engagement", "melee_circle_speed", 0.9)

    if dist > 0.1:
        nx = (tx - pos.x) / dist
        ny = (ty - pos.y) / dist
        cdir = state.get("melee_circle_dir", 1)
        tang_x = -ny * cdir
        tang_y = nx * cdir

        drift = (dist - ideal_r) / max(ideal_r, 0.5)
        jitter = _tun("combat.engagement", "melee_direction_jitter", 0.15)
        drift += random.uniform(-jitter, jitter) * dt
        bx = tang_x + nx * drift * 1.2
        by = tang_y + ny * drift * 1.2
        blen = math.hypot(bx, by)
        if blen > 0.01:
            vel.x = (bx / blen) * circ_speed
            vel.y = (by / blen) * circ_speed
        else:
            vel.x, vel.y = 0.0, 0.0
    else:
        vel.x, vel.y = 0.0, 0.0

    if random.random() < 0.008:
        state["melee_circle_dir"] = -state.get("melee_circle_dir", 1)

    if state["melee_circle_timer"] <= 0:
        if random.random() < _tun("combat.engagement",
                                  "melee_feint_chance", 0.35):
            state["melee_sub"] = "feint"
            state["melee_feint_timer"] = random.uniform(0.3, 0.6)
            state["melee_feint_phase"] = "advance"
        else:
            state["melee_sub"] = "lunge"

    if dist > atk_range * 2.5:
        state["melee_sub"] = "approach"


def _melee_feint(pos, vel, tx, ty, dist, atk_range, speed, state, dt):
    phase = state.get("melee_feint_phase", "advance")
    state["melee_feint_timer"] = state.get("melee_feint_timer", 0.5) - dt

    if phase == "advance":
        feint_speed = speed * _tun("combat.engagement",
                                   "melee_feint_speed", 2.5)
        move_toward(pos, vel, tx, ty, feint_speed)
        if state["melee_feint_timer"] <= 0 or dist < atk_range * 0.5:
            state["melee_feint_phase"] = "withdraw"
            state["melee_feint_timer"] = random.uniform(0.3, 0.7)
    elif phase == "withdraw":
        retreat_speed = speed * _tun("combat.engagement",
                                     "melee_feint_withdraw_speed", 2.0)
        move_away(pos, vel, tx, ty, retreat_speed)
        if state["melee_feint_timer"] <= 0:
            state["melee_sub"] = "circle"
            state["melee_circle_timer"] = random.uniform(0.8, 1.5)
            state["melee_circle_dir"] = random.choice((-1, 1))
    else:
        state["melee_sub"] = "circle"

    if dist > atk_range * 3.0:
        state["melee_sub"] = "approach"


def _melee_lunge(pos, vel, tx, ty, dist, atk_range, speed, state):
    lunge_speed = speed * _tun("combat.engagement",
                               "melee_lunge_speed", 3.5)
    lunge_close = atk_range * _tun("combat.engagement",
                                   "melee_lunge_dist", 0.3)
    if dist > lunge_close:
        move_toward(pos, vel, tx, ty, lunge_speed)
    else:
        vel.x, vel.y = 0.0, 0.0

    if state.get("_melee_just_hit"):
        state["_melee_just_hit"] = False
        if _tun("combat.engagement", "melee_post_hit_retreat", True):
            state["melee_sub"] = "retreat"
            state["melee_retreat_timer"] = _tun(
                "combat.engagement", "melee_retreat_duration", 0.6)
        else:
            state["melee_sub"] = "circle"
            state["melee_circle_timer"] = random.uniform(
                _tun("combat.engagement", "melee_circle_time_min", 1.2),
                _tun("combat.engagement", "melee_circle_time_max", 3.0),
            )

    if dist > atk_range * 2.5:
        state["melee_sub"] = "approach"


def _melee_retreat(pos, vel, tx, ty, dist, speed, state, dt):
    state["melee_retreat_timer"] = state.get("melee_retreat_timer", 0.5) - dt
    retreat_speed = speed * _tun("combat.engagement",
                                 "melee_retreat_speed", 2.5)

    r_dir = state.get("melee_retreat_dir")
    if r_dir is None:
        r_dir = random.choice((-1, 1))
        state["melee_retreat_dir"] = r_dir

    if dist > 0.1:
        away_x = (pos.x - tx) / dist
        away_y = (pos.y - ty) / dist
        side_x = -away_y * r_dir
        side_y = away_x * r_dir
        bx = away_x * 0.7 + side_x * 0.3
        by = away_y * 0.7 + side_y * 0.3
        blen = math.hypot(bx, by)
        if blen > 0.01:
            vel.x = (bx / blen) * retreat_speed
            vel.y = (by / blen) * retreat_speed
        else:
            move_away(pos, vel, tx, ty, retreat_speed)
    else:
        move_away(pos, vel, tx, ty, retreat_speed)

    if state["melee_retreat_timer"] <= 0:
        state["melee_sub"] = "circle"
        state["melee_circle_timer"] = random.uniform(
            _tun("combat.engagement", "melee_circle_time_min", 1.2),
            _tun("combat.engagement", "melee_circle_time_max", 3.0),
        )
        state["melee_circle_dir"] = random.choice((-1, 1))
        state.pop("melee_retreat_dir", None)
