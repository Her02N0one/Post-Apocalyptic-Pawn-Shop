"""logic/brains/wander.py — Random-walk brain.

Reads the ``Patrol`` component (radius, speed) to constrain movement
and picks random walk directions.
"""

from __future__ import annotations
import random
import math
from core.ecs import World
from components import Brain, Patrol, Position, Velocity
from core.zone import is_passable
from logic.brains import register_brain


def _wander_brain(world: World, eid: int, brain: Brain, dt: float,
                  game_time: float = 0.0):
    """Random-walk brain — stay near spawn point and avoid walls."""
    pos = world.get(eid, Position)
    vel = world.get(eid, Velocity)
    if pos is None:
        return
    if vel is None:
        vel = Velocity()
        world.add(eid, vel)

    patrol = world.get(eid, Patrol)
    if patrol is None:
        return
    p_speed = patrol.speed
    p_radius = patrol.radius

    s = brain.state
    # remember spawn origin on first tick
    if "origin" not in s:
        s["origin"] = (pos.x, pos.y)
    s.setdefault("timer", 0.0)
    s.setdefault("dir", (0.0, 0.0))

    s["timer"] -= dt
    if s["timer"] <= 0.0:
        angle = random.uniform(0, 2 * math.pi)
        speed = random.uniform(p_speed * 0.3, p_speed)
        dx = speed * math.cos(angle)
        dy = speed * math.sin(angle)
        s["dir"] = (dx, dy)
        s["timer"] = random.uniform(1.0, 3.0)

    dx, dy = s["dir"]
    ox, oy = s["origin"]

    # Would the next step leave the patrol radius?
    nx = pos.x + dx * dt
    ny = pos.y + dy * dt
    dist_sq = (nx - ox) ** 2 + (ny - oy) ** 2

    if dist_sq > p_radius * p_radius:
        # Turn back toward origin
        to_ox = ox - pos.x
        to_oy = oy - pos.y
        length = max(0.01, (to_ox ** 2 + to_oy ** 2) ** 0.5)
        spd = p_speed * 0.5
        dx = (to_ox / length) * spd
        dy = (to_oy / length) * spd
        s["dir"] = (dx, dy)
        s["timer"] = random.uniform(0.5, 1.5)

    # Wall check
    if is_passable(pos.zone, pos.x + dx * dt, pos.y + dy * dt):
        vel.x = dx
        vel.y = dy
    else:
        vel.x = 0.0
        vel.y = 0.0
        s["timer"] = 0.1


register_brain("wander", _wander_brain)
