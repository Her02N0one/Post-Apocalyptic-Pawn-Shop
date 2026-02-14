"""logic/ai/wander.py — Random-walk brain using A* pathfinding.

Reads the ``HomeRange`` component (radius, speed) to constrain movement.
Periodically picks a random passable tile within patrol radius
and pathfinds to it with A*.  Falls back to reactive steering when
the zone map isn't loaded.
"""

from __future__ import annotations
import random
import math
from core.ecs import World
from components import Brain, HomeRange, Position, Velocity
from core.zone import is_passable, ZONE_MAPS
from logic.ai.brains import register_brain
from logic.pathfinding import find_path, path_next_waypoint
from core.tuning import get as _tun


def _pick_random_passable(zone: str, ox: float, oy: float,
                          radius: float) -> tuple[float, float] | None:
    """Return a random passable tile position within *radius* of (ox, oy)."""
    tiles = ZONE_MAPS.get(zone)
    if not tiles:
        return None
    rows = len(tiles)
    cols = len(tiles[0]) if rows else 0

    for _ in range(int(_tun("ai.wander", "max_dest_attempts", 8))):
        angle = random.uniform(0, 2 * math.pi)
        r = random.uniform(_tun("ai.wander", "min_dest_radius", 2.0), radius)
        tx = ox + math.cos(angle) * r
        ty = oy + math.sin(angle) * r
        tr, tc = int(ty), int(tx)
        if 0 <= tr < rows and 0 <= tc < cols:
            if is_passable(zone, tx, ty):
                return (tx, ty)
    return None


def _wander_brain(world: World, eid: int, brain: Brain, dt: float,
                  game_time: float = 0.0):
    """A*-based wander brain — pick random destinations within patrol radius."""
    pos = world.get(eid, Position)
    vel = world.get(eid, Velocity)
    if pos is None:
        return
    if vel is None:
        vel = Velocity()
        world.add(eid, vel)

    patrol = world.get(eid, HomeRange)
    if patrol is None:
        return
    p_speed = patrol.speed
    p_radius = patrol.radius

    s = brain.state
    # remember spawn origin on first tick
    if "origin" not in s:
        s["origin"] = (pos.x, pos.y)

    path = s.get("_path")
    pick_time = s.get("_pick_time", 0.0)

    # ── Need a new destination? ──────────────────────────────────────
    pick_max = _tun("ai.wander", "pick_interval_max", 5.0)
    need_new = (
        path is None
        or len(path) == 0
        or (game_time - pick_time) > s.get("_pick_interval", pick_max)
    )

    if need_new:
        ox, oy = s["origin"]
        dest = _pick_random_passable(pos.zone, ox, oy, p_radius)
        if dest:
            new_path = find_path(pos.zone, pos.x, pos.y, dest[0], dest[1],
                                 max_dist=int(p_radius) + 8)
            s["_path"] = new_path
        else:
            s["_path"] = None
        s["_pick_time"] = game_time
        pick_min = _tun("ai.wander", "pick_interval_min", 2.0)
        s["_pick_interval"] = random.uniform(pick_min, pick_max)
        path = s.get("_path")

    # ── Follow path ──────────────────────────────────────────────────
    if path is not None and len(path) > 0:
        wp = path_next_waypoint(path, pos.x, pos.y,
                                reach=_tun("ai.wander", "waypoint_reach", 0.45))
        if wp is not None:
            wx, wy = wp
            dx = wx - pos.x
            dy = wy - pos.y
            d = math.hypot(dx, dy)
            if d > 0.05:
                spd_min_mult = _tun("ai.wander", "path_speed_min_mult", 0.5)
                spd = random.uniform(p_speed * spd_min_mult, p_speed) if s.get("_speed") is None else s["_speed"]
                s["_speed"] = spd
                vel.x = (dx / d) * spd
                vel.y = (dy / d) * spd
            else:
                vel.x, vel.y = 0.0, 0.0
            return
        else:
            # Path exhausted — arrived, idle briefly then pick next
            s["_path"] = None
            s["_speed"] = None
            vel.x, vel.y = 0.0, 0.0
            return

    # ── Fallback: simple random walk when no path available ──────────
    s.setdefault("timer", 0.0)
    s.setdefault("dir", (0.0, 0.0))

    s["timer"] -= dt
    if s["timer"] <= 0.0:
        angle = random.uniform(0, 2 * math.pi)
        speed = random.uniform(p_speed * 0.3, p_speed)
        dx = speed * math.cos(angle)
        dy = speed * math.sin(angle)
        s["dir"] = (dx, dy)
        s["timer"] = random.uniform(
            _tun("ai.wander", "fallback_timer_min", 1.0),
            _tun("ai.wander", "fallback_timer_max", 3.0),
        )

    dx, dy = s["dir"]
    ox, oy = s["origin"]

    # Would the next step leave the patrol radius?
    nx = pos.x + dx * dt
    ny = pos.y + dy * dt
    dist_sq = (nx - ox) ** 2 + (ny - oy) ** 2

    if dist_sq > p_radius * p_radius:
        to_ox = ox - pos.x
        to_oy = oy - pos.y
        length = max(0.01, (to_ox ** 2 + to_oy ** 2) ** 0.5)
        spd = p_speed * 0.5
        dx = (to_ox / length) * spd
        dy = (to_oy / length) * spd
        s["dir"] = (dx, dy)
        s["timer"] = random.uniform(0.5, 1.5)

    if is_passable(pos.zone, pos.x + dx * dt, pos.y + dy * dt):
        vel.x = dx
        vel.y = dy
    else:
        vel.x = 0.0
        vel.y = 0.0
        s["timer"] = 0.1


register_brain("wander", _wander_brain)
