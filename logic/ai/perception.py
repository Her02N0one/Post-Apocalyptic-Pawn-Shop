"""logic/ai/perception.py — Vision, targeting, and awareness helpers.

Used by brain implementations to find and evaluate targets.
"""

from __future__ import annotations
import math
from core.ecs import World
from components import (
    Position, Health, Player, Facing, HitFlash, Faction,
)
from components.ai import VisionCone


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
    """Euclidean distance between two Position-like objects."""
    return math.hypot(a.x - b.x, a.y - b.y)


def hp_ratio(world: World, eid: int) -> float:
    """Return entity's HP as a 0–1 fraction (1.0 if no Health)."""
    h = world.get(eid, Health)
    if h is None:
        return 1.0
    return h.current / max(1.0, h.maximum)


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
