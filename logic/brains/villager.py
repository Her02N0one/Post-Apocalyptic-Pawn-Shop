"""logic/brains/villager.py — Needs-driven village NPC brain.

FSM: idle -> forage -> eat -> idle

A villager wanders around their home area until their hunger need
becomes urgent enough.  When ``Needs.priority == 'eat'``:
  1. Check inventory for food — if found, stop and eat immediately.
  2. If no food, switch to 'forage' — walk toward a known food
     source or wander looking for loot (placeholder for now).

After eating, return to normal idle/wander behaviour.

This brain is intended for peaceful village NPCs (farmers, traders).
Combat-capable variants should extend hostile_melee/guard instead.
"""

from __future__ import annotations
import random
import math
from core.ecs import World
from components import Brain, Patrol, Position, Velocity, Needs, Hunger, Inventory
from core.zone import is_passable
from logic.brains._helpers import find_player, move_away
from logic.brains import register_brain


# How long the NPC pauses while "eating" (auto_eat_system does the actual eat)
EAT_PAUSE = 2.0

# Hunger ratio below which we interrupt idle to eat/forage
EAT_THRESHOLD = 0.4


def _villager_brain(world: World, eid: int, brain: Brain, dt: float,
                    game_time: float = 0.0):
    """Villager — wander, pause when eating, forage when no food."""
    pos = world.get(eid, Position)
    vel = world.get(eid, Velocity)
    if not pos or not vel:
        return

    patrol = world.get(eid, Patrol)
    if patrol is None:
        return

    s = brain.state
    v = s.setdefault("villager", {})
    if "origin" not in v:
        v["origin"] = (pos.x, pos.y)
    v.setdefault("mode", "idle")

    needs = world.get(eid, Needs)
    hunger = world.get(eid, Hunger)
    inv = world.get(eid, Inventory)
    mode = v["mode"]

    # ── Crime panic: flee the player briefly ────────────────────────
    flee_until = s.get("crime_flee_until", 0.0)
    if flee_until > game_time:
        p_eid, p_pos = find_player(world)
        if p_pos and p_pos.zone == pos.zone:
            move_away(pos, vel, p_pos.x, p_pos.y, patrol.speed * 1.6)
            return

    # ── Needs interrupt ──────────────────────────────────────────────
    # auto_eat_system handles the actual eating; the brain just decides
    # whether to stand still (eating) or forage (no food).
    if mode == "idle" and needs and needs.priority == "eat":
        if hunger and (hunger.current / max(hunger.maximum, 0.01)) < EAT_THRESHOLD:
            has_food = inv is not None and len(inv.items) > 0
            if has_food:
                # Stand still — auto_eat_system will handle consumption
                v["mode"] = "eat"
                v["eat_until"] = game_time + EAT_PAUSE
                mode = "eat"
            else:
                # No food — go forage
                v["mode"] = "forage"
                v["forage_until"] = game_time + random.uniform(8.0, 15.0)
                mode = "forage"

    # ── Eat state (just pause, system handles actual eating) ─────────
    if mode == "eat":
        vel.x, vel.y = 0.0, 0.0
        if v.get("eat_until", 0.0) <= game_time:
            v["mode"] = "idle"
        return

    # ── Forage state (placeholder) ───────────────────────────────────
    if mode == "forage":
        if v.get("forage_until", 0.0) <= game_time:
            v["mode"] = "return"
            return
        _wander_step(patrol, pos, vel, v, dt, speed_mult=1.3)
        return

    # ── Return state ─────────────────────────────────────────────────
    if mode == "return":
        ox, oy = v.get("origin", (pos.x, pos.y))
        dist = math.hypot(pos.x - ox, pos.y - oy)
        if dist < 1.5:
            v["mode"] = "idle"
            vel.x, vel.y = 0.0, 0.0
            return
        dx = ox - pos.x
        dy = oy - pos.y
        length = max(0.01, math.hypot(dx, dy))
        spd = patrol.speed
        vel.x = (dx / length) * spd
        vel.y = (dy / length) * spd
        return

    # ── Idle state (wander) ──────────────────────────────────────────
    _wander_step(patrol, pos, vel, v, dt)


def _wander_step(patrol: Patrol, pos, vel, s: dict, dt: float,
                 speed_mult: float = 1.0):
    """Perform one frame of random-walk, constrained to patrol radius."""
    s.setdefault("timer", 0.0)
    s.setdefault("dir", (0.0, 0.0))

    s["timer"] -= dt
    if s["timer"] <= 0.0:
        angle = random.uniform(0, 2 * math.pi)
        spd = random.uniform(patrol.speed * 0.3,
                             patrol.speed) * speed_mult
        s["dir"] = (spd * math.cos(angle), spd * math.sin(angle))
        s["timer"] = random.uniform(1.0, 3.0)

    dx, dy = s["dir"]
    ox, oy = s.get("origin", (pos.x, pos.y))

    nx = pos.x + dx * dt
    ny = pos.y + dy * dt
    if (nx - ox) ** 2 + (ny - oy) ** 2 > patrol.radius ** 2:
        to_ox = ox - pos.x
        to_oy = oy - pos.y
        length = max(0.01, math.hypot(to_ox, to_oy))
        spd = patrol.speed * 0.5 * speed_mult
        s["dir"] = ((to_ox / length) * spd, (to_oy / length) * spd)
        s["timer"] = random.uniform(0.5, 1.5)
        dx, dy = s["dir"]

    if is_passable(pos.zone, pos.x + dx * dt, pos.y + dy * dt):
        vel.x = dx
        vel.y = dy
    else:
        vel.x, vel.y = 0.0, 0.0
        s["timer"] = 0.1


register_brain("villager", _villager_brain)
