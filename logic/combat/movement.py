"""logic/combat/movement.py — Velocity-producing movement behaviours.

Each public function takes minimal parameters and writes directly
to ``vel`` in place.  A mutable ``state`` dict is threaded through
so that sub-state timers persist across frames.

No World access is needed — every input is pre-resolved by the caller
(the combat_engagement orchestrator or the goal system).

Melee sub-FSM has been extracted to ``melee_fsm.py``.
"""

from __future__ import annotations
import random
import math

from core.tuning import get as _tun
from core.zone import is_passable
from logic.ai.steering import (
    move_toward, move_toward_pathfind, move_away, strafe, run_idle,
)
from logic.combat.allies import PointProxy
from logic.combat.melee_fsm import melee_attack  # noqa: F401 — re-export


# ── Simple modes ─────────────────────────────────────────────────────

def idle(patrol, pos, vel, state: dict, dt: float):
    """Patrol-envelope wander while not engaged."""
    if patrol:
        run_idle(patrol, pos, vel, state, dt)
    else:
        vel.x, vel.y = 0.0, 0.0


def searching(pos, vel, sx: float, sy: float, speed: float,
              state: dict, dt: float):
    """Walk cautiously toward the sound source, stop when close."""
    dx = sx - pos.x
    dy = sy - pos.y
    dist = math.hypot(dx, dy)
    if dist < 1.5:
        vel.x, vel.y = 0.0, 0.0
        return
    move_toward(pos, vel, sx, sy, speed)


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


# ── Tactical reposition ─────────────────────────────────────────────

def tactical_reposition(pos, vel, rx: float, ry: float, speed: float,
                        state: dict, game_time: float):
    """Move toward a tactical position using A* pathfinding.

    Called when the engagement orchestrator has identified a new
    position the NPC should move to (clearing fire-line, seeking
    cover, de-clumping).  Uses boosted speed.
    """
    repos_speed = speed * _tun("combat.tactical",
                               "repos_speed_mult", 1.4)
    move_toward_pathfind(pos, vel, rx, ry, repos_speed,
                         state, game_time)


# ── Ranged attack movement ──────────────────────────────────────────

def ranged_attack(pos, vel, tx: float, ty: float, dist: float,
                  atk_range: float, speed: float, state: dict,
                  dt: float, *, wall_blocked: bool = False,
                  los_blocked: bool = False, game_time: float = 0.0,
                  repos_target: tuple[float, float] | None = None):
    """Ranged attack positioning: kite / strafe / reposition."""
    target_proxy = PointProxy(tx, ty)

    if wall_blocked:
        if repos_target:
            rx, ry = repos_target
            d_repos = math.hypot(pos.x - rx, pos.y - ry)
            if d_repos < 0.5:
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

    ideal_min = atk_range * _tun("combat.engagement",
                                 "ranged_ideal_min_factor", 0.5)
    ideal_max = atk_range * _tun("combat.engagement",
                                 "ranged_ideal_max_factor", 0.85)

    too_close = atk_range * _tun("combat.engagement",
                                 "kite_close_factor", 0.35)
    if dist < too_close:
        move_away(pos, vel, tx, ty,
                  speed * _tun("combat.engagement",
                               "kite_away_speed_mult", 1.5))
    elif dist < ideal_min:
        _strafe_with_drift(pos, vel, target_proxy, speed, state, dt,
                           drift=-0.5)
    elif dist > ideal_max and dist < atk_range * 1.3:
        _strafe_with_drift(pos, vel, target_proxy, speed, state, dt,
                           drift=0.4)
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


# ── Strafe helpers ───────────────────────────────────────────────────

def _do_strafe(pos, vel, target_proxy, speed: float, speed_mult: float,
               state: dict, dt: float, min_t: float, max_t: float):
    """Strafe around target with periodic direction changes.

    Includes passability awareness — reverses direction near walls.
    """
    state.setdefault("strafe_dir", 1)
    state["strafe_timer"] = state.get("strafe_timer", 0.0) - dt
    if state["strafe_timer"] <= 0:
        state["strafe_timer"] = random.uniform(min_t, max_t)
        state["strafe_dir"] *= -1
    strafe(pos, vel, target_proxy, speed * speed_mult, state["strafe_dir"])

    if hasattr(pos, "zone"):
        probe_dt = 0.15
        nx = pos.x + vel.x * probe_dt
        ny = pos.y + vel.y * probe_dt
        if not is_passable(pos.zone, nx, ny):
            state["strafe_dir"] *= -1
            strafe(pos, vel, target_proxy, speed * speed_mult,
                   state["strafe_dir"])
            state["strafe_timer"] = random.uniform(min_t, max_t)


def _strafe_with_drift(pos, vel, target_proxy, speed: float,
                       state: dict, dt: float, drift: float = 0.0):
    """Strafe while drifting toward/away from target for range maintenance.

    ``drift`` < 0 means away, > 0 means toward.
    """
    state.setdefault("strafe_dir", 1)
    state["strafe_timer"] = state.get("strafe_timer", 0.0) - dt
    if state["strafe_timer"] <= 0:
        state["strafe_timer"] = random.uniform(0.6, 1.5)
        state["strafe_dir"] *= -1

    dx = target_proxy.x - pos.x
    dy = target_proxy.y - pos.y
    d = math.hypot(dx, dy)
    if d < 0.1:
        vel.x, vel.y = 0.0, 0.0
        return
    nx, ny = dx / d, dy / d
    cdir = state["strafe_dir"]
    tang_x = -ny * cdir
    tang_y = nx * cdir
    bx = tang_x * 0.7 + nx * drift
    by = tang_y * 0.7 + ny * drift
    blen = math.hypot(bx, by)
    spd = speed * 0.8
    if blen > 0.01:
        vel.x = (bx / blen) * spd
        vel.y = (by / blen) * spd
    else:
        vel.x, vel.y = 0.0, 0.0

    if hasattr(pos, "zone"):
        probe_dt = 0.15
        px = pos.x + vel.x * probe_dt
        py = pos.y + vel.y * probe_dt
        if not is_passable(pos.zone, px, py):
            state["strafe_dir"] *= -1
            cdir = state["strafe_dir"]
            tang_x = -ny * cdir
            tang_y = nx * cdir
            bx = tang_x * 0.7 + nx * drift
            by = tang_y * 0.7 + ny * drift
            blen = math.hypot(bx, by)
            if blen > 0.01:
                vel.x = (bx / blen) * spd
                vel.y = (by / blen) * spd
            else:
                vel.x, vel.y = 0.0, 0.0
            state["strafe_timer"] = random.uniform(0.6, 1.5)
