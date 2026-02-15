"""logic/combat/melee_fsm.py — Melee attack sub-state-machine.

Sub-FSM for melee NPCs while in **attack** mode:

    approach → circle → feint → lunge → retreat → circle → …

Each sub-state writes directly to ``vel`` and mutates the shared
``state`` dict.  The parent orchestrator (``engagement.py``) calls
:func:`melee_attack` every frame and this module handles the rest.

State keys used:
    ``melee_sub``, ``melee_circle_timer``, ``melee_circle_dir``,
    ``melee_feint_timer``, ``melee_feint_phase``,
    ``melee_retreat_timer``, ``melee_retreat_dir``, ``_melee_just_hit``.
"""

from __future__ import annotations
import random
import math

from core.tuning import get as _tun
from logic.ai.steering import move_toward, move_away


# ── Public entry point ───────────────────────────────────────────────

def melee_attack(pos, vel, tx: float, ty: float, dist: float,
                 atk_range: float, speed: float, state: dict,
                 dt: float):
    """Dispatch to the correct sub-state."""
    sub = state.get("melee_sub", "approach")
    ideal_r = atk_range * _tun("combat.engagement", "melee_circle_radius", 1.6)

    if sub == "approach":
        _approach(pos, vel, tx, ty, dist, ideal_r, speed, state)
    elif sub == "circle":
        _circle(pos, vel, tx, ty, dist, ideal_r, atk_range, speed,
                state, dt)
    elif sub == "feint":
        _feint(pos, vel, tx, ty, dist, atk_range, speed, state, dt)
    elif sub == "lunge":
        _lunge(pos, vel, tx, ty, dist, atk_range, speed, state)
    elif sub == "retreat":
        _retreat(pos, vel, tx, ty, dist, speed, state, dt)
    else:
        state["melee_sub"] = "approach"


# ── Sub-states ───────────────────────────────────────────────────────

def _approach(pos, vel, tx, ty, dist, ideal_r, speed, state):
    """Close distance to circling range."""
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


def _circle(pos, vel, tx, ty, dist, ideal_r, atk_range, speed,
            state, dt):
    """Orbit the target, maintaining ideal distance."""
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


def _feint(pos, vel, tx, ty, dist, atk_range, speed, state, dt):
    """Fake advance followed by withdrawal — creates openings."""
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


def _lunge(pos, vel, tx, ty, dist, atk_range, speed, state):
    """Rush into striking range, then retreat after a hit."""
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


def _retreat(pos, vel, tx, ty, dist, speed, state, dt):
    """Diagonal retreat after landing a hit."""
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
