"""logic/ai/steering.py — AI movement helpers.

Velocity-producing functions used by brain implementations to steer
entities toward targets, away from threats, along A* paths, or in
idle wander patterns.
"""

from __future__ import annotations
import random
import math
from core.ecs import World
from components import Position, Velocity, Facing, HomeRange
from core.zone import is_passable
from logic.pathfinding import find_path, path_next_waypoint
from core.tuning import get as _tun

# Angular offsets for reactive steering fallback (radians).
_STEER_OFFSETS = [0.0, 0.4, -0.4, 0.8, -0.8, 1.2, -1.2,
                  math.pi * 0.5, -math.pi * 0.5,
                  math.pi * 0.75, -math.pi * 0.75]


def move_toward(pos, vel, tx: float, ty: float, speed: float):
    """Set velocity to move directly toward (tx, ty)."""
    dx = tx - pos.x
    dy = ty - pos.y
    d = math.hypot(dx, dy)
    if d < 0.05:
        vel.x, vel.y = 0.0, 0.0
        return
    vel.x = (dx / d) * speed
    vel.y = (dy / d) * speed


def move_toward_pathfind(pos, vel, tx: float, ty: float, speed: float,
                         state: dict, game_time: float = 0.0, *,
                         tuning_ns: str = "ai.helpers",
                         max_dist: int = 24,
                         arrival_dist: float = 0.0,
                         reactive_steering: bool = False,
                         dt: float = 0.0) -> float:
    """Move toward (tx, ty) using a cached A* path.

    Returns the straight-line distance to the target.

    Parameters
    ----------
    tuning_ns : str
        Tuning namespace for path_recompute_interval, waypoint_reach, etc.
    max_dist : int
        Maximum A* search distance in tiles.
    arrival_dist : float
        If > 0, stop and return dist once within this distance.
    reactive_steering : bool
        If True, use angular sweep fallback instead of direct-line when
        A* fails (better for tight spaces).
    dt : float
        Frame delta (only needed when reactive_steering is True).
    """
    dx = tx - pos.x
    dy = ty - pos.y
    dist = math.hypot(dx, dy)

    if arrival_dist > 0 and dist < arrival_dist:
        vel.x, vel.y = 0.0, 0.0
        return dist

    # ── Cached A* path ───────────────────────────────────────────────
    path = state.get("_path")
    path_time = state.get("_path_t", 0.0)
    path_tgt = state.get("_path_tgt")
    recomp = _tun(tuning_ns, "path_recompute_interval", 0.8)
    drift = _tun(tuning_ns, "path_target_drift_threshold", 1.5)

    need = (
        path is None
        or path_tgt is None
        or abs(path_tgt[0] - tx) > drift
        or abs(path_tgt[1] - ty) > drift
        or (game_time - path_time) > recomp
    )
    if need:
        new_path = find_path(pos.zone, pos.x, pos.y, tx, ty, max_dist=max_dist)
        state["_path"] = new_path
        state["_path_t"] = game_time
        state["_path_tgt"] = (tx, ty)
        path = new_path

    if path is not None and len(path) > 0:
        wp_reach = _tun(tuning_ns, "waypoint_reach", 0.45)
        wp = path_next_waypoint(path, pos.x, pos.y, reach=wp_reach)
        if wp is not None:
            wx, wy = wp
            wdx = wx - pos.x
            wdy = wy - pos.y
            wd = math.hypot(wdx, wdy)
            if wd > 0.05:
                vel.x = (wdx / wd) * speed
                vel.y = (wdy / wd) * speed
            return dist
        else:
            # Path exhausted
            vel.x, vel.y = 0.0, 0.0
            state["_path"] = None
            return dist

    # ── Fallback ─────────────────────────────────────────────────────
    if reactive_steering:
        base_angle = math.atan2(dy, dx)
        for offset in _STEER_OFFSETS:
            a = base_angle + offset
            sx = math.cos(a) * speed
            sy = math.sin(a) * speed
            near = 0.15
            if (is_passable(pos.zone, pos.x + sx * near, pos.y + sy * near) and
                    is_passable(pos.zone, pos.x + sx * dt, pos.y + sy * dt)):
                vel.x = sx
                vel.y = sy
                return dist
        vel.x, vel.y = 0.0, 0.0
    else:
        move_toward(pos, vel, tx, ty, speed)

    return dist


def move_away(pos, vel, tx: float, ty: float, speed: float):
    """Set velocity to flee directly away from (tx, ty)."""
    dx = pos.x - tx
    dy = pos.y - ty
    d = math.hypot(dx, dy)
    if d < 0.05:
        vel.x = speed
        vel.y = 0.0
        return
    vel.x = (dx / d) * speed
    vel.y = (dy / d) * speed


def strafe(pos, vel, target_pos, speed: float, direction: int):
    """Move perpendicular to the line toward *target_pos*."""
    dx = target_pos.x - pos.x
    dy = target_pos.y - pos.y
    d = math.hypot(dx, dy)
    if d < 0.05:
        return
    # Rotate 90°
    vel.x = (-dy / d) * direction * speed
    vel.y = (dx / d) * direction * speed


def face_toward(world: World, eid: int, target_pos):
    """Update entity's Facing component to face *target_pos*."""
    facing = world.get(eid, Facing)
    if facing is None:
        return
    pos = world.get(eid, Position)
    if pos is None:
        return
    dx = target_pos.x - pos.x
    dy = target_pos.y - pos.y
    if abs(dx) >= abs(dy):
        facing.direction = "right" if dx > 0 else "left"
    else:
        facing.direction = "down" if dy > 0 else "up"


def run_idle(patrol, pos, vel, s: dict, dt: float):
    """Shared idle / slow-wander used by combat brains when no target."""
    s.setdefault("idle_timer", 0.0)
    s.setdefault("idle_dir", (0.0, 0.0))
    s["idle_timer"] -= dt
    if s["idle_timer"] <= 0:
        angle = random.uniform(0, 2 * math.pi)
        spd_min = patrol.speed * _tun("ai.helpers", "idle_wander_speed_min", 0.2)
        spd_max = patrol.speed * _tun("ai.helpers", "idle_wander_speed_max", 0.5)
        speed = random.uniform(spd_min, spd_max)
        s["idle_dir"] = (speed * math.cos(angle), speed * math.sin(angle))
        s["idle_timer"] = random.uniform(
            _tun("ai.helpers", "idle_timer_min", 1.5),
            _tun("ai.helpers", "idle_timer_max", 4.0),
        )

    dx, dy = s["idle_dir"]
    ox, oy = s.get("origin", (pos.x, pos.y))

    # Stay near origin
    nx = pos.x + dx * dt
    ny = pos.y + dy * dt
    if (nx - ox) ** 2 + (ny - oy) ** 2 > patrol.radius ** 2:
        to_ox = ox - pos.x
        to_oy = oy - pos.y
        length = max(0.01, math.hypot(to_ox, to_oy))
        spd = patrol.speed * _tun("ai.helpers", "idle_return_speed_mult", 0.3)
        dx = (to_ox / length) * spd
        dy = (to_oy / length) * spd
        s["idle_dir"] = (dx, dy)
        s["idle_timer"] = random.uniform(0.5, 1.0)

    if is_passable(pos.zone, pos.x + dx * dt, pos.y + dy * dt):
        vel.x = dx
        vel.y = dy
    else:
        vel.x, vel.y = 0.0, 0.0
        s["idle_timer"] = _tun("ai.helpers", "idle_blocked_timer", 0.1)
