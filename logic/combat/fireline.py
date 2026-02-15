"""logic/combat/fireline.py — Fire-line awareness and communication.

Pure geometry helpers that let NPCs detect when they (or their allies)
are standing in another ranged ally's line of fire, compute dodge
vectors, and request allies to reposition.

Fire-lines are modelled as segments from shooter → target.  Any NPC
whose body capsule overlaps a fire-line is "in the lane" and should
strafe clear or reposition.
"""

from __future__ import annotations
import math
from dataclasses import dataclass

from core.ecs import World
from components import Position, Brain, Faction, AttackConfig
from core.tuning import get as _tun
from logic.combat.allies import iter_same_faction_allies


# ── Data structure ───────────────────────────────────────────────────

@dataclass
class FireLine:
    """A line-of-fire from a ranged ally toward their target."""
    shooter_x: float
    shooter_y: float
    target_x: float
    target_y: float
    shooter_eid: int = -1


# ── Queries ──────────────────────────────────────────────────────────

def get_ally_fire_lines(world: World, eid: int, pos) -> list[FireLine]:
    """Collect fire-lines of all same-faction ranged allies in attack mode.

    Each fire-line runs from the ally's current position toward their
    cached target position.  Only allies who are *currently attacking*
    with a ranged weapon produce fire-lines.
    """
    lines: list[FireLine] = []

    for aid, apos in iter_same_faction_allies(world, eid, pos):
        abrain = world.get(aid, Brain)
        if abrain is None:
            continue
        acfg = world.get(aid, AttackConfig)
        if acfg is None or acfg.attack_type != "ranged":
            continue
        ac = abrain.state.get("combat", {})
        if ac.get("mode") != "attack":
            continue
        tgt = ac.get("p_pos")
        if tgt is None:
            continue
        lines.append(FireLine(
            shooter_x=apos.x, shooter_y=apos.y,
            target_x=tgt[0], target_y=tgt[1],
            shooter_eid=aid,
        ))
    return lines


# ── Pure geometry ────────────────────────────────────────────────────

def point_fire_line_dist(px: float, py: float, fl: FireLine) -> float:
    """Perpendicular distance from point (px, py) to a fire-line segment.

    Returns the distance to the segment (clamped), or a large value
    if the point is behind the shooter or past the target.
    """
    sx, sy = fl.shooter_x, fl.shooter_y
    tx, ty = fl.target_x, fl.target_y
    dx = tx - sx
    dy = ty - sy
    seg_sq = dx * dx + dy * dy
    if seg_sq < 0.01:
        return 999.0
    t = ((px - sx) * dx + (py - sy) * dy) / seg_sq
    if t < 0.0 or t > 1.2:
        return 999.0
    cx = sx + t * dx
    cy = sy + t * dy
    return math.hypot(px - cx, py - cy)


def fire_line_dodge_vector(px: float, py: float,
                           fire_lines: list[FireLine],
                           clearance: float = 0.0) -> tuple[float, float]:
    """Compute a lateral dodge direction away from the nearest fire-line.

    Returns a unit vector ``(nx, ny)`` perpendicular to the closest
    fire-line pushing the entity OUT of the lane, or ``(0, 0)`` if
    the entity is not in any lane.

    ``clearance`` defaults to the tuning value ``combat.fireline.clearance``.
    """
    if clearance <= 0.0:
        clearance = _tun("combat.fireline", "clearance", 1.2)

    best_dist = clearance
    best_nx, best_ny = 0.0, 0.0

    for fl in fire_lines:
        sx, sy = fl.shooter_x, fl.shooter_y
        tx, ty = fl.target_x, fl.target_y
        dx = tx - sx
        dy = ty - sy
        seg_sq = dx * dx + dy * dy
        if seg_sq < 0.01:
            continue
        seg_len = math.sqrt(seg_sq)

        t = ((px - sx) * dx + (py - sy) * dy) / seg_sq
        if t < 0.05 or t > 1.1:
            continue
        cx = sx + t * dx
        cy = sy + t * dy
        perp_dist = math.hypot(px - cx, py - cy)

        if perp_dist < best_dist:
            best_dist = perp_dist
            cross = (px - sx) * dy - (py - sy) * dx
            if cross >= 0:
                best_nx = -dy / seg_len
                best_ny = dx / seg_len
            else:
                best_nx = dy / seg_len
                best_ny = -dx / seg_len

    return (best_nx, best_ny)


# ── Active communication ────────────────────────────────────────────

def request_clear_fire_line(world: World, blocker_eid: int,
                            shooter_pos: tuple[float, float],
                            target_pos: tuple[float, float]):
    """Tell *blocker_eid* to reposition out of the shooter's fire lane.

    Sets a ``_clear_fire_line`` flag in the blocker's brain state so
    that on its next movement frame it will pick a tactical position
    that clears the lane.
    """
    brain = world.get(blocker_eid, Brain)
    if brain is None:
        return
    c = brain.state.get("combat")
    if c is None:
        return
    if c.get("_tac_repos"):
        return
    c["_clear_fire_line"] = {
        "shooter": shooter_pos,
        "target": target_pos,
    }
