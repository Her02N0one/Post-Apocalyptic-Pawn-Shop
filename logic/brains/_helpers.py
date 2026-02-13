"""logic/brains/_helpers.py — Shared AI helper functions.

Movement, targeting, faction gating, and defense utilities used by
multiple brain implementations.

Cooldowns use absolute GameClock timestamps rather than ``-= dt``
countdowns to prevent floating-point drift on long-running timers.
"""

from __future__ import annotations
import random
import math
from core.ecs import World
from components import (
    Brain, Patrol, Threat, AttackConfig,
    Position, Velocity, Health, Player, Facing,
    HitFlash, Faction, Inventory, ItemRegistry, Identity,
)
from components.ai import VisionCone
from core.zone import is_passable
from logic.pathfinding import find_path, path_next_waypoint
from core.tuning import get as _tun


# ── Vision cone utilities ────────────────────────────────────────────

_FACING_ANGLES: dict[str, float] = {
    "right": 0.0,
    "down":  math.pi / 2,
    "left":  math.pi,
    "up":    -math.pi / 2,
}


def facing_to_angle(direction: str) -> float:
    """Convert a cardinal Facing.direction string to radians.

    right → 0, down → π/2, left → π, up → −π/2
    """
    return _FACING_ANGLES.get(direction, 0.0)


def in_vision_cone(pos, facing_dir: str, target_pos,
                   cone: VisionCone) -> bool:
    """Return True if *target_pos* is visible from *pos* given a VisionCone.

    Detection succeeds if:
    • target is within ``cone.peripheral_range`` (omni-directional), OR
    • target is within ``cone.view_distance`` AND within the facing arc.
    """
    dx = target_pos.x - pos.x
    dy = target_pos.y - pos.y
    dist = math.hypot(dx, dy)
    # Close-range peripheral — always detected
    if dist <= cone.peripheral_range:
        return True
    # Beyond forward range
    if dist > cone.view_distance:
        return False
    # Angle check
    angle_to_target = math.atan2(dy, dx)
    face_angle = facing_to_angle(facing_dir)
    diff = abs(math.atan2(math.sin(angle_to_target - face_angle),
                          math.cos(angle_to_target - face_angle)))
    half_fov = math.radians(cone.fov_degrees / 2.0)
    return diff <= half_fov


# ── Targeting ────────────────────────────────────────────────────────

def find_player(world: World):
    """Return (eid, Position) of the player, or (None, None)."""
    res = world.query_one(Player, Position)
    if res:
        return res[0], res[2]
    return None, None


def find_nearest_enemy(world: World, eid: int, max_range: float = 999.0,
                       use_vision_cone: bool = False):
    """Return (target_eid, target_Position) of the nearest hostile entity.

    An entity is considered hostile if it belongs to a *different*
    faction group and has a ``Health`` component (i.e. is alive and
    can be damaged).  Entities with no ``Faction`` are skipped.

    If *use_vision_cone* is True and the entity has a ``VisionCone``
    component, only targets inside the cone (or within peripheral
    range) are considered.

    Returns (None, None) if no enemy is within *max_range* tiles.
    """
    pos = world.get(eid, Position)
    faction = world.get(eid, Faction)
    if pos is None or faction is None:
        return None, None

    # Vision cone setup
    cone = None
    facing_dir = "down"
    if use_vision_cone:
        cone = world.get(eid, VisionCone)
        facing = world.get(eid, Facing)
        if facing:
            facing_dir = facing.direction

    my_group = faction.group
    best_eid = None
    best_pos = None
    best_dist = max_range + 1

    for other_eid, other_pos in world.all_of(Position):
        if other_eid == eid:
            continue
        if other_pos.zone != pos.zone:
            continue
        if not world.has(other_eid, Health):
            continue
        other_hp = world.get(other_eid, Health)
        if other_hp.current <= 0:
            continue
        other_fac = world.get(other_eid, Faction)
        if other_fac is None:
            continue
        if other_fac.group == my_group:
            continue  # same team
        d = math.hypot(other_pos.x - pos.x, other_pos.y - pos.y)
        if d >= best_dist:
            continue
        # Vision cone filter (if enabled and component exists)
        if cone is not None:
            if not in_vision_cone(pos, facing_dir, other_pos, cone):
                continue
        best_dist = d
        best_eid = other_eid
        best_pos = other_pos

    if best_eid is not None:
        return best_eid, best_pos
    return None, None


def dist_pos(a, b) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def hp_ratio(world: World, eid: int) -> float:
    h = world.get(eid, Health)
    if h is None:
        return 1.0
    return h.current / max(1.0, h.maximum)


# ── Movement ─────────────────────────────────────────────────────────

def move_toward(pos, vel, tx: float, ty: float, speed: float):
    dx = tx - pos.x
    dy = ty - pos.y
    d = math.hypot(dx, dy)
    if d < 0.05:
        vel.x, vel.y = 0.0, 0.0
        return
    vel.x = (dx / d) * speed
    vel.y = (dy / d) * speed


def move_toward_pathfind(pos, vel, tx: float, ty: float, speed: float,
                         state: dict, game_time: float = 0.0):
    """Move toward (tx, ty) using a cached A* path.

    Falls back to direct ``move_toward`` if pathfinding fails or the
    zone map isn't loaded.  The *state* dict caches the computed path.
    """
    path = state.get("_chase_path")
    path_time = state.get("_chase_path_t", 0.0)
    path_tgt = state.get("_chase_path_tgt")
    recompute_interval = _tun("ai.helpers", "path_recompute_interval", 0.8)
    drift_threshold = _tun("ai.helpers", "path_target_drift_threshold", 1.5)
    need = (
        path is None
        or path_tgt is None
        or abs(path_tgt[0] - tx) > drift_threshold
        or abs(path_tgt[1] - ty) > drift_threshold
        or (game_time - path_time) > recompute_interval
    )
    if need:
        new_path = find_path(pos.zone, pos.x, pos.y, tx, ty, max_dist=24)
        state["_chase_path"] = new_path
        state["_chase_path_t"] = game_time
        state["_chase_path_tgt"] = (tx, ty)
        path = new_path

    if path is not None and len(path) > 0:
        wp_reach = _tun("ai.helpers", "waypoint_reach", 0.45)
        wp = path_next_waypoint(path, pos.x, pos.y, reach=wp_reach)
        if wp is not None:
            wx, wy = wp
            dx = wx - pos.x
            dy = wy - pos.y
            d = math.hypot(dx, dy)
            if d > 0.05:
                vel.x = (dx / d) * speed
                vel.y = (dy / d) * speed
            return

    # Fallback: direct line
    move_toward(pos, vel, tx, ty, speed)


def move_away(pos, vel, tx: float, ty: float, speed: float):
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


# ── Faction / defense ───────────────────────────────────────────────

def should_engage(world: World, eid: int) -> bool:
    """Return True if entity should use hostile combat AI.

    No Faction component -> always hostile (backward compat).
    """
    hf = world.get(eid, HitFlash)
    if hf is not None and hf.remaining > 0.05:
        return True
    faction = world.get(eid, Faction)
    if faction is None:
        return True
    return faction.disposition == "hostile"


def try_dodge(world: World, eid: int, brain: Brain,
              pos, vel, s: dict, dt: float, game_time: float) -> bool:
    """On a fresh hit, dash perpendicular. Returns True if dodging."""
    hf = world.get(eid, HitFlash)
    if hf is None or hf.remaining < 0.08:
        return False
    if s.get("dodge_until", 0.0) > game_time:
        return False
    # Dodge away from the nearest threat (player or enemy)
    p_eid, p_pos = find_player(world)
    if p_pos is None or p_pos.zone != pos.zone:
        p_eid, p_pos = find_nearest_enemy(world, eid, max_range=8.0)
    if p_pos is None:
        return False
    dx = p_pos.x - pos.x
    dy = p_pos.y - pos.y
    d = math.hypot(dx, dy)
    if d < 0.05:
        return False
    patrol = world.get(eid, Patrol)
    dodge_speed = (patrol.speed if patrol else 2.0) * _tun("ai.helpers", "dodge_speed_mult", 3.0)
    direction = 1 if random.random() > 0.5 else -1
    vel.x = (-dy / d) * direction * dodge_speed
    vel.y = (dx / d) * direction * dodge_speed
    s["dodge_until"] = game_time + _tun("ai.helpers", "dodge_duration", 1.5)
    return True


def try_heal(world: World, eid: int, brain: Brain, s: dict,
             game_time: float) -> bool:
    """If HP is low and entity has consumables, use the best one."""
    if s.get("heal_until", 0.0) > game_time:
        return False
    hp = hp_ratio(world, eid)
    if hp > _tun("ai.helpers", "heal_hp_threshold", 0.4):
        return False
    inv = world.get(eid, Inventory)
    if inv is None:
        return False
    registry = world.res(ItemRegistry)
    if registry is None:
        return False
    best_id = None
    best_heal = 0.0
    for item_id, qty in inv.items.items():
        if qty <= 0:
            continue
        if registry.item_type(item_id) != "consumable":
            continue
        heal = registry.get_field(item_id, "heal", 0.0)
        if heal > best_heal:
            best_heal = heal
            best_id = item_id
    if best_id is None:
        return False
    health = world.get(eid, Health)
    if health:
        health.current = min(health.maximum, health.current + best_heal)
    inv.items[best_id] -= 1
    if inv.items[best_id] <= 0:
        del inv.items[best_id]
    name = "?"
    if world.has(eid, Identity):
        name = world.get(eid, Identity).name
    print(f"[AI] {name} used {registry.display_name(best_id)} (+{best_heal:.0f} HP)")
    s["heal_until"] = game_time + _tun("ai.helpers", "heal_cooldown", 5.0)
    return True


def reset_faction_on_return(world: World, eid: int):
    """When a combat entity returns home, reset disposition."""
    faction = world.get(eid, Faction)
    if faction and faction.disposition != faction.home_disposition:
        faction.disposition = faction.home_disposition
