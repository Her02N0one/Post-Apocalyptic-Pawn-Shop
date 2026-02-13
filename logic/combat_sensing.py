"""logic/combat_sensing.py — Target acquisition and line-of-sight queries.

Pure queries against the World — no mutations, no side effects.
Used by ``combat_engagement.py`` (orchestrator) and by the goal system
so that target-finding, wall-LOS, and ally-collision logic lives in
exactly one place.
"""

from __future__ import annotations
import math
from dataclasses import dataclass

from core.ecs import World
from components import Position, Health, Faction, Facing
from components.ai import VisionCone
from core.zone import has_line_of_sight
from core.tuning import get as _tun
from logic.brains._helpers import (
    find_player, find_nearest_enemy, in_vision_cone,
)


@dataclass
class TargetInfo:
    """Everything the combat FSM needs to know about the current target."""
    eid: int | None = None
    x: float = 0.0
    y: float = 0.0
    dist: float = 999.0
    wall_los: bool = False
    ally_in_fire: bool = False


def acquire_target(world: World, eid: int, pos,
                   aggro_radius: float) -> TargetInfo:
    """Find the best combat target (player first, then nearest enemy).

    Wall-LOS and ally-in-fire are computed eagerly so callers never
    need to re-check.
    """
    info = TargetInfo()

    # Player is always highest-priority target
    p_eid, p_pos = find_player(world)
    if p_pos is not None and p_pos.zone == pos.zone:
        info.eid = p_eid
        info.x = p_pos.x
        info.y = p_pos.y
    else:
        e_eid, e_pos = find_nearest_enemy(world, eid,
                                          max_range=aggro_radius * 3)
        if e_pos is not None and e_pos.zone == pos.zone:
            info.eid = e_eid
            info.x = e_pos.x
            info.y = e_pos.y

    if info.eid is None:
        return info

    info.dist = math.hypot(pos.x - info.x, pos.y - info.y)
    info.wall_los = has_line_of_sight(
        pos.zone, pos.x + 0.4, pos.y + 0.4,
        info.x + 0.4, info.y + 0.4,
    )
    info.ally_in_fire = ally_in_line_of_fire(world, eid, pos,
                                             info.x, info.y)
    return info


def is_detected_idle(world: World, eid: int, pos,
                     tx: float, ty: float,
                     dist: float, aggro_radius: float) -> bool:
    """Return True if the target at (tx, ty) is detected from idle state.

    Uses ``VisionCone`` if present, otherwise simple radius check.
    """
    cone = world.get(eid, VisionCone)
    if cone is not None:
        facing = world.get(eid, Facing)
        fdir = facing.direction if facing else "down"
        t_proxy = type("P", (), {"x": tx, "y": ty})()
        return in_vision_cone(pos, fdir, t_proxy, cone)
    return dist <= aggro_radius


def ally_in_line_of_fire(world: World, eid: int, pos,
                         tx: float, ty: float) -> bool:
    """Return True if a same-faction ally is between *eid* and (tx, ty).

    Capsule test: projects each ally onto the shooter->target segment
    and checks clearance radius.
    """
    faction = world.get(eid, Faction)
    if faction is None:
        return False
    group = faction.group

    dx = tx - pos.x
    dy = ty - pos.y
    seg_len_sq = dx * dx + dy * dy
    if seg_len_sq < 0.01:
        return False

    CLEAR = _tun("combat.engagement", "line_of_fire_clearance", 0.6)

    for aid, apos in world.all_of(Position):
        if aid == eid:
            continue
        if apos.zone != pos.zone:
            continue
        af = world.get(aid, Faction)
        if af is None or af.group != group:
            continue
        if not world.has(aid, Health):
            continue
        ax = apos.x - pos.x
        ay = apos.y - pos.y
        t = (ax * dx + ay * dy) / seg_len_sq
        if t < 0.05 or t > 0.95:
            continue
        cx = t * dx
        cy = t * dy
        dist_sq = (ax - cx) ** 2 + (ay - cy) ** 2
        if dist_sq < CLEAR * CLEAR:
            return True
    return False


def ally_near_target(world: World, eid: int, pos,
                     tx: float, ty: float,
                     melee_range: float) -> bool:
    """Return True if a same-faction ally is within *melee_range* of the target."""
    faction = world.get(eid, Faction)
    if faction is None:
        return False
    group = faction.group
    threshold = melee_range * _tun("combat.engagement",
                                   "ally_near_target_factor", 0.8)

    for aid, apos in world.all_of(Position):
        if aid == eid:
            continue
        if apos.zone != pos.zone:
            continue
        af = world.get(aid, Faction)
        if af is None or af.group != group:
            continue
        if not world.has(aid, Health):
            continue
        d = math.hypot(apos.x - tx, apos.y - ty)
        if d < threshold:
            return True
    return False
