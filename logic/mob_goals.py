"""logic/mob_goals.py — Per-brain-kind goal and sensor templates.

Each function returns *fresh* Goal instances (goals may hold instance
state) and a list of sensor names to run on that entity.

Usage::

    goals, sensors = get_mob_template("hostile_melee")
    world.add(eid, GoalSet(goals=goals))

Lower priority number = more important.  Priority bands:

    1–2   Immediate response (revenge, flee)
    3–4   Primary behaviour  (attack, eat)
    5–6   Recovery           (return home, forage)
    7–8   Background         (wander, idle)
"""

from __future__ import annotations
from logic.goals import (
    WanderGoal, IdleGoal, AttackTargetGoal, FleeGoal,
    ReturnHomeGoal, EatGoal, ForageGoal,
)


# ── Template registry ────────────────────────────────────────────────

_TEMPLATES: dict[str, callable] = {}


def register_template(kind: str, fn):
    _TEMPLATES[kind] = fn


def get_mob_template(kind: str) -> tuple[list, list[str]] | None:
    """Return ``(goal_list, sensor_names)`` for a brain kind, or None."""
    fn = _TEMPLATES.get(kind)
    if fn:
        return fn()
    return None


# ══════════════════════════════════════════════════════════════════════
#  BUILT-IN TEMPLATES
# ══════════════════════════════════════════════════════════════════════


def _hostile_melee_template():
    goals = [
        (1, AttackTargetGoal()),   # Chase + melee attack
        (2, FleeGoal()),           # Flee when HP low
        (5, ReturnHomeGoal()),     # Return to spawn
        (7, WanderGoal()),         # Idle walk
        (8, IdleGoal()),           # Stand still
    ]
    sensors = ["nearest_hostile", "hurt"]
    return goals, sensors


def _hostile_ranged_template():
    goals = [
        (1, AttackTargetGoal()),   # Chase + ranged attack
        (2, FleeGoal()),           # Flee when HP low
        (5, ReturnHomeGoal()),     # Return to spawn
        (7, WanderGoal()),         # Idle walk
        (8, IdleGoal()),           # Stand still
    ]
    sensors = ["nearest_hostile", "hurt"]
    return goals, sensors


def _guard_template():
    goals = [
        (1, AttackTargetGoal()),   # Chase + melee attack
        # Guards never flee (Threat.flee_threshold == 0)
        (5, ReturnHomeGoal()),     # Return to post
        (8, IdleGoal()),           # Stand at post
    ]
    sensors = ["nearest_hostile", "hurt"]
    return goals, sensors


def _wander_template():
    goals = [
        (7, WanderGoal()),
        (8, IdleGoal()),
    ]
    sensors: list[str] = []
    return goals, sensors


def _villager_template():
    goals = [
        (3, EatGoal()),            # Eat when hungry
        (4, ForageGoal()),         # Look for food
        (5, ReturnHomeGoal()),     # Head home when far
        (7, WanderGoal()),         # Wander near home
        (8, IdleGoal()),           # Stand still
    ]
    sensors = ["hunger"]
    return goals, sensors


# ── Register ─────────────────────────────────────────────────────────

register_template("hostile_melee",  _hostile_melee_template)
register_template("hostile_ranged", _hostile_ranged_template)
register_template("guard",         _guard_template)
register_template("wander",        _wander_template)
register_template("villager",      _villager_template)
