"""systems/combat/melee_fsm.py — Melee attack sub-state-machine.

Sub-FSM for melee NPCs while in **attack** mode:

    approach → circle → feint → lunge → retreat → circle → …

Each sub-state writes directly to ``vel`` and mutates the
:class:`~systems.combat.state.CombatState`.  The parent orchestrator
(``engagement.py``) calls :func:`melee_attack` every frame and this
module handles the rest.

Melee sub-state lives in ``state.melee`` (a :class:`MeleeState`).
"""

from __future__ import annotations
import random
import math

from core.tuning import get as _tun
from systems.ai.steering import move_toward, move_away

if False:  # TYPE_CHECKING
    from systems.combat.state import CombatState


# ── Public entry point ───────────────────────────────────────────────

def melee_attack(pos, vel, tx: float, ty: float, dist: float,
                 atk_range: float, speed: float, state: "CombatState",
                 dt: float):
    """Dispatch to the correct sub-state."""
    m = state.melee
    sub = m.sub
    ideal_r = atk_range * _tun("combat.engagement", "melee_circle_radius", 1.6)

    if sub == "approach":
        _approach(pos, vel, tx, ty, dist, ideal_r, speed, m)
    elif sub == "circle":
        _circle(pos, vel, tx, ty, dist, ideal_r, atk_range, speed, m, dt)
    elif sub == "feint":
        _feint(pos, vel, tx, ty, dist, atk_range, speed, m, dt)
    elif sub == "lunge":
        _lunge(pos, vel, tx, ty, dist, atk_range, speed, m)
    elif sub == "retreat":
        _retreat(pos, vel, tx, ty, dist, speed, m, dt)
    else:
        m.sub = "approach"


# ── Sub-states ───────────────────────────────────────────────────────

def _approach(pos, vel, tx, ty, dist, ideal_r, speed, m):
    """Close distance to circling range."""
    if dist > ideal_r * 1.2:
        move_toward(pos, vel, tx, ty,
                    speed * _tun("combat.engagement",
                                 "melee_close_in_speed", 1.2))
    else:
        m.sub = "circle"
        m.circle_timer = random.uniform(
            _tun("combat.engagement", "melee_circle_time_min", 1.2),
            _tun("combat.engagement", "melee_circle_time_max", 3.0),
        )
        if m.circle_dir == 1 and random.random() < 0.5:
            m.circle_dir = -1


def _circle(pos, vel, tx, ty, dist, ideal_r, atk_range, speed, m, dt):
    """Orbit the target, maintaining ideal distance."""
    m.circle_timer -= dt
    circ_speed = speed * _tun("combat.engagement", "melee_circle_speed", 0.9)

    if dist > 0.1:
        nx = (tx - pos.x) / dist
        ny = (ty - pos.y) / dist
        tang_x = -ny * m.circle_dir
        tang_y = nx * m.circle_dir

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
        m.circle_dir = -m.circle_dir

    if m.circle_timer <= 0:
        if random.random() < _tun("combat.engagement",
                                  "melee_feint_chance", 0.35):
            m.sub = "feint"
            m.feint_timer = random.uniform(0.3, 0.6)
            m.feint_phase = "advance"
        else:
            m.sub = "lunge"

    if dist > atk_range * 2.5:
        m.sub = "approach"


def _feint(pos, vel, tx, ty, dist, atk_range, speed, m, dt):
    """Fake advance followed by withdrawal — creates openings."""
    phase = m.feint_phase
    m.feint_timer -= dt

    if phase == "advance":
        feint_speed = speed * _tun("combat.engagement",
                                   "melee_feint_speed", 2.5)
        move_toward(pos, vel, tx, ty, feint_speed)
        if m.feint_timer <= 0 or dist < atk_range * 0.5:
            m.feint_phase = "withdraw"
            m.feint_timer = random.uniform(0.3, 0.7)
    elif phase == "withdraw":
        retreat_speed = speed * _tun("combat.engagement",
                                     "melee_feint_withdraw_speed", 2.0)
        move_away(pos, vel, tx, ty, retreat_speed)
        if m.feint_timer <= 0:
            m.sub = "circle"
            m.circle_timer = random.uniform(0.8, 1.5)
            m.circle_dir = random.choice((-1, 1))
    else:
        m.sub = "circle"

    if dist > atk_range * 3.0:
        m.sub = "approach"


def _lunge(pos, vel, tx, ty, dist, atk_range, speed, m):
    """Rush into striking range, then retreat after a hit."""
    lunge_speed = speed * _tun("combat.engagement",
                               "melee_lunge_speed", 3.5)
    lunge_close = atk_range * _tun("combat.engagement",
                                   "melee_lunge_dist", 0.3)
    if dist > lunge_close:
        move_toward(pos, vel, tx, ty, lunge_speed)
    else:
        vel.x, vel.y = 0.0, 0.0

    if m.just_hit:
        m.just_hit = False
        if _tun("combat.engagement", "melee_post_hit_retreat", True):
            m.sub = "retreat"
            m.retreat_timer = _tun(
                "combat.engagement", "melee_retreat_duration", 0.6)
        else:
            m.sub = "circle"
            m.circle_timer = random.uniform(
                _tun("combat.engagement", "melee_circle_time_min", 1.2),
                _tun("combat.engagement", "melee_circle_time_max", 3.0),
            )

    if dist > atk_range * 2.5:
        m.sub = "approach"


def _retreat(pos, vel, tx, ty, dist, speed, m, dt):
    """Diagonal retreat after landing a hit."""
    m.retreat_timer -= dt
    retreat_speed = speed * _tun("combat.engagement",
                                 "melee_retreat_speed", 2.5)

    r_dir = m.retreat_dir
    if r_dir is None:
        r_dir = random.choice((-1, 1))
        m.retreat_dir = r_dir

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

    if m.retreat_timer <= 0:
        m.sub = "circle"
        m.circle_timer = random.uniform(
            _tun("combat.engagement", "melee_circle_time_min", 1.2),
            _tun("combat.engagement", "melee_circle_time_max", 3.0),
        )
        m.circle_dir = random.choice((-1, 1))
        m.retreat_dir = None
