"""logic/combat/targeting.py — Target acquisition and ally queries.

Pure queries against the World — no mutations, no side effects.
Used by the engagement orchestrator so that target-finding and
ally-collision logic lives in exactly one place.

Fire-line math moved to ``fireline.py``; tactical positioning moved
to ``tactical.py``.
"""

from __future__ import annotations
import math
from dataclasses import dataclass

from core.ecs import World
from components import Position, Facing
from components.ai import VisionCone
from core.zone import has_line_of_sight
from core.tuning import get as _tun
from logic.ai.perception import (
    find_player, find_nearest_enemy, in_vision_cone,
)
from logic.combat.allies import PointProxy, iter_same_faction_allies

# ── Re-exports so existing ``from logic.combat.targeting import …``
#    in tests and other callers keeps working after the split. ────────
from logic.combat.fireline import (           # noqa: F401
    FireLine, get_ally_fire_lines,
    point_fire_line_dist, fire_line_dodge_vector,
    request_clear_fire_line,
)
from logic.combat.tactical import (           # noqa: F401
    find_tactical_position, find_los_position,
    find_chase_los_waypoint, _has_adjacent_wall,
)


# ── Data structures ──────────────────────────────────────────────────

@dataclass
class TargetInfo:
    """Everything the combat FSM needs to know about the current target."""
    eid: int | None = None
    x: float = 0.0
    y: float = 0.0
    dist: float = 999.0
    wall_los: bool = False
    ally_in_fire: bool = False


# ── Target acquisition ───────────────────────────────────────────────

def acquire_target(world: World, eid: int, pos,
                   aggro_radius: float) -> TargetInfo:
    """Find the best combat target (player first, then nearest enemy).

    Wall-LOS and ally-in-fire are computed eagerly so callers never
    need to re-check.
    """
    info = TargetInfo()

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


# ── Idle detection ───────────────────────────────────────────────────

def is_detected_idle(world: World, eid: int, pos,
                     tx: float, ty: float,
                     dist: float, aggro_radius: float) -> bool:
    """Return True if the target at (tx, ty) is detected from idle state.

    Uses the entity's ``VisionCone`` if present — idle detection is
    **directional**.  Falls back to omnidirectional radius check.
    """
    if dist > aggro_radius:
        return False
    cone = world.get(eid, VisionCone)
    if cone is None:
        return True
    facing = world.get(eid, Facing)
    facing_dir = facing.direction if facing else "down"
    return in_vision_cone(pos, facing_dir, PointProxy(tx, ty), cone)


# ── Ally queries ─────────────────────────────────────────────────────

def ally_in_line_of_fire(world: World, eid: int, pos,
                         tx: float, ty: float) -> bool:
    """Return True if a same-faction ally is between *eid* and (tx, ty).

    Capsule test: projects each ally onto the shooter→target segment.
    """
    dx = tx - pos.x
    dy = ty - pos.y
    seg_len_sq = dx * dx + dy * dy
    if seg_len_sq < 0.01:
        return False

    CLEAR = _tun("combat.engagement", "line_of_fire_clearance", 0.6)

    for _aid, apos in iter_same_faction_allies(world, eid, pos):
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
    threshold = melee_range * _tun("combat.engagement",
                                   "ally_near_target_factor", 0.8)
    for _aid, apos in iter_same_faction_allies(world, eid, pos):
        if math.hypot(apos.x - tx, apos.y - ty) < threshold:
            return True
    return False


def get_ally_positions(world: World, eid: int, pos) -> list[tuple[float, float]]:
    """Return positions of all same-faction allies in the same zone.

    Used for anti-clump scoring.
    """
    return [(apos.x, apos.y)
            for _aid, apos in iter_same_faction_allies(world, eid, pos)]


def find_blocking_ally(world: World, eid: int, pos,
                       tx: float, ty: float) -> int | None:
    """Return the eid of the closest same-faction ally blocking the line
    of fire, or ``None`` if the lane is clear.
    """
    dx = tx - pos.x
    dy = ty - pos.y
    seg_len_sq = dx * dx + dy * dy
    if seg_len_sq < 0.01:
        return None

    CLEAR = _tun("combat.engagement", "line_of_fire_clearance", 0.6)
    best_t = 2.0
    best_eid: int | None = None

    for aid, apos in iter_same_faction_allies(world, eid, pos):
        ax = apos.x - pos.x
        ay = apos.y - pos.y
        t = (ax * dx + ay * dy) / seg_len_sq
        if t < 0.05 or t > 0.95:
            continue
        cx = t * dx
        cy = t * dy
        dist_sq = (ax - cx) ** 2 + (ay - cy) ** 2
        if dist_sq < CLEAR * CLEAR and t < best_t:
            best_t = t
            best_eid = aid
    return best_eid
