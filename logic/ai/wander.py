"""logic/ai/wander.py — Random-walk brain using A* pathfinding.

Reads the ``HomeRange`` component (radius, speed) to constrain movement.
Periodically picks a random passable tile within patrol radius
and pathfinds to it with A*.  Falls back to reactive steering when
the zone map isn't loaded.

The public :func:`wander_step` helper encapsulates the shared
pick→pathfind→follow→fallback loop.  Both the ``wander`` brain and
``villager`` brain delegate to it so the pattern is written once.
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


def pick_random_passable(zone: str, ox: float, oy: float,
                         radius: float, *,
                         attempts: int = 8,
                         min_radius: float = 2.0,
                         ) -> tuple[float, float] | None:
    """Return a random passable tile position within *radius* of (ox, oy)."""
    tiles = ZONE_MAPS.get(zone)
    if not tiles:
        return None
    rows = len(tiles)
    cols = len(tiles[0]) if rows else 0

    for _ in range(attempts):
        angle = random.uniform(0, 2 * math.pi)
        r = random.uniform(min_radius, radius)
        tx = ox + math.cos(angle) * r
        ty = oy + math.sin(angle) * r
        tr, tc = int(ty), int(tx)
        if 0 <= tr < rows and 0 <= tc < cols:
            if is_passable(zone, tx, ty):
                return (tx, ty)
    return None


# ── Shared wander loop ───────────────────────────────────────────────

def wander_step(zone: str, x: float, y: float, vel,
                patrol_radius: float, patrol_speed: float,
                s: dict, dt: float, game_time: float = 0.0,
                speed_mult: float = 1.0,
                prefix: str = "_w",
                tun_ns: str = "ai.wander") -> None:
    """One frame of the shared pick→pathfind→follow→fallback loop.

    Parameters
    ----------
    zone : str         – current zone key (for tile map + passability)
    x, y : float       – entity world position
    vel              – Velocity component (mutated in-place)
    patrol_radius    – maximum wander distance from origin
    patrol_speed     – base movement speed (metres / sec)
    s : dict           – ``brain.state`` (or any persistent dict)
    dt, game_time      – frame delta and wall-clock
    speed_mult         – multiplier applied on top of patrol_speed
    prefix             – state-key prefix so wander and villager
                         don't clobber each other's keys
    tun_ns             – tuning namespace (``ai.wander`` / ``ai.villager``)
    """
    ox, oy = s.get("origin", (x, y))
    if "origin" not in s:
        s["origin"] = (ox, oy)

    k_path = f"{prefix}_path"
    k_pick_t = f"{prefix}_pick_t"
    k_pick_ivl = f"{prefix}_pick_ivl"

    wpath = s.get(k_path)
    pick_time = s.get(k_pick_t, 0.0)
    pick_max = _tun(tun_ns, "pick_interval_max", 5.0)
    pick_ivl = s.get(k_pick_ivl, pick_max)

    need_new = (
        wpath is None
        or len(wpath) == 0
        or (game_time - pick_time) > pick_ivl
    )

    if need_new:
        dest = pick_random_passable(
            zone, ox, oy, patrol_radius,
            attempts=int(_tun(tun_ns, "max_dest_attempts", 8)),
            min_radius=_tun(tun_ns, "min_dest_radius", 1.5),
        )
        if dest:
            new_path = find_path(zone, x, y, dest[0], dest[1],
                                 max_dist=int(patrol_radius) + 8)
            s[k_path] = new_path
        else:
            s[k_path] = None
        s[k_pick_t] = game_time
        pick_min = _tun(tun_ns, "pick_interval_min", 2.0)
        s[k_pick_ivl] = random.uniform(pick_min, pick_max)
        wpath = s.get(k_path)

    # ── Follow path ──────────────────────────────────────────────────
    if wpath is not None and len(wpath) > 0:
        wp = path_next_waypoint(wpath, x, y,
                                reach=_tun(tun_ns, "waypoint_reach", 0.45))
        if wp is not None:
            wx, wy = wp
            dx = wx - x
            dy = wy - y
            d = math.hypot(dx, dy)
            if d > 0.05:
                spd = patrol_speed * speed_mult
                vel.x = (dx / d) * spd
                vel.y = (dy / d) * spd
            else:
                vel.x, vel.y = 0.0, 0.0
            return
        else:
            s[k_path] = None
            vel.x, vel.y = 0.0, 0.0
            return

    # ── Fallback: reactive random walk ───────────────────────────────
    s.setdefault("timer", 0.0)
    s.setdefault("dir", (0.0, 0.0))

    s["timer"] -= dt
    if s["timer"] <= 0.0:
        angle = random.uniform(0, 2 * math.pi)
        spd = random.uniform(patrol_speed * 0.3, patrol_speed) * speed_mult
        s["dir"] = (spd * math.cos(angle), spd * math.sin(angle))
        s["timer"] = random.uniform(
            _tun(tun_ns, "fallback_timer_min", 1.0),
            _tun(tun_ns, "fallback_timer_max", 3.0),
        )

    dx, dy = s["dir"]

    nx = x + dx * dt
    ny = y + dy * dt
    if (nx - ox) ** 2 + (ny - oy) ** 2 > patrol_radius ** 2:
        to_ox = ox - x
        to_oy = oy - y
        length = max(0.01, math.hypot(to_ox, to_oy))
        spd = patrol_speed * 0.5 * speed_mult
        s["dir"] = ((to_ox / length) * spd, (to_oy / length) * spd)
        s["timer"] = random.uniform(0.5, 1.5)
        dx, dy = s["dir"]

    if is_passable(zone, x + dx * dt, y + dy * dt):
        vel.x = dx
        vel.y = dy
    else:
        vel.x, vel.y = 0.0, 0.0
        s["timer"] = 0.1


# ── Wander brain (thin wrapper) ─────────────────────────────────────

def _wander_brain(world: World, eid: int, brain: Brain, dt: float,
                  game_time: float = 0.0):
    """A*-based wander brain — delegates to :func:`wander_step`."""
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

    wander_step(pos.zone, pos.x, pos.y, vel,
                patrol.radius, patrol.speed,
                brain.state, dt, game_time,
                prefix="_w", tun_ns="ai.wander")


register_brain("wander", _wander_brain)
