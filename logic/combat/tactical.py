"""logic/combat/tactical.py — Tactical position finding.

Ring-search algorithms that score candidate positions by range, cover,
fire-line clearance, ally spacing, and travel cost.  Used by the
engagement orchestrator when an NPC needs a better position — e.g.
wall-blocked, in a fire-lane, or clumped with allies.

Also contains the LOS-aware chase waypoint finder.
"""

from __future__ import annotations
import math

from core.zone import has_line_of_sight
from core.tuning import get as _tun
from logic.combat.fireline import FireLine, point_fire_line_dist


# ── Cover detection ──────────────────────────────────────────────────

def _has_adjacent_wall(zone: str, x: float, y: float) -> bool:
    """Return True if any of the 8 neighbouring tiles is a wall.

    Fast heuristic for "am I next to cover?"
    """
    from core.zone import ZONE_MAPS
    from core.constants import TILE_WALL
    tiles = ZONE_MAPS.get(zone)
    if not tiles:
        return False
    rows = len(tiles)
    cols = len(tiles[0]) if rows else 0
    r, c = int(y), int(x)
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr == 0 and dc == 0:
                continue
            nr, nc = r + dr, c + dc
            if 0 <= nr < rows and 0 <= nc < cols:
                if tiles[nr][nc] == TILE_WALL:
                    return True
    return False


# ── Main tactical position finder ────────────────────────────────────

def find_tactical_position(
    zone: str, sx: float, sy: float,
    tx: float, ty: float,
    atk_range: float,
    *,
    fire_lines: list[FireLine] | None = None,
    ally_positions: list[tuple[float, float]] | None = None,
    origin: tuple[float, float] | None = None,
) -> tuple[float, float] | None:
    """Find the best nearby position considering range, cover, fire-lines,
    and ally spacing.

    Samples candidate positions on concentric rings around the NPC,
    scoring each by:

    * **Range** — prefer the ideal engagement distance.
    * **Cover** — bonus for positions adjacent to a wall that still
      have LOS to the target.
    * **Fire-line clearance** — strong penalty for standing in an
      ally's line of fire.
    * **Ally spacing** — penalty for being too close to allies
      (anti-clump).
    * **Travel cost** — prefer positions close to current location.
    * **Leash** — mild penalty for drifting far from origin.

    Returns ``(x, y)`` or ``None`` if nothing beats the current spot.
    """
    from core.zone import is_passable as _passable

    best: tuple[float, float] | None = None
    best_score = -999.0
    ideal_range = atk_range * _tun("combat.tactical", "ideal_range_factor", 0.7)
    fl_clearance = _tun("combat.fireline", "clearance", 1.2)
    cover_bonus = _tun("combat.tactical", "cover_bonus", 3.0)
    ally_spacing_pen = _tun("combat.tactical", "ally_spacing_penalty", 3.0)
    ally_min_dist = _tun("combat.tactical", "ally_min_distance", 3.0)

    for radius in (2.0, 4.0, 6.0, 8.0):
        n_dirs = max(12, int(radius * 3))
        for i in range(n_dirs):
            angle = math.pi * 2.0 * i / n_dirs
            cx = sx + math.cos(angle) * radius
            cy = sy + math.sin(angle) * radius

            if not _passable(zone, cx, cy):
                continue
            if not has_line_of_sight(zone, cx + 0.4, cy + 0.4,
                                    tx + 0.4, ty + 0.4):
                continue

            d_to_target = math.hypot(cx - tx, cy - ty)
            range_score = -abs(d_to_target - ideal_range) / max(ideal_range, 1.0)
            travel_score = -math.hypot(cx - sx, cy - sy) * 0.15

            leash_score = 0.0
            if origin:
                leash_score = -math.hypot(cx - origin[0],
                                          cy - origin[1]) * 0.05

            cov_score = cover_bonus if _has_adjacent_wall(zone, cx, cy) else 0.0

            fl_score = 0.0
            if fire_lines:
                for fl in fire_lines:
                    fd = point_fire_line_dist(cx, cy, fl)
                    if fd < fl_clearance:
                        fl_score -= (fl_clearance - fd) * 5.0

            space_score = 0.0
            if ally_positions:
                for ax, ay in ally_positions:
                    ad = math.hypot(cx - ax, cy - ay)
                    if ad < ally_min_dist:
                        space_score -= ally_spacing_pen * (
                            1.0 - ad / ally_min_dist)

            score = (range_score + travel_score + leash_score
                     + cov_score + fl_score + space_score)
            if score > best_score:
                best_score = score
                best = (cx, cy)

    return best


def find_los_position(zone: str, sx: float, sy: float,
                      tx: float, ty: float,
                      atk_range: float,
                      origin: tuple[float, float] | None = None,
                      fire_lines: list[FireLine] | None = None,
                      ) -> tuple[float, float] | None:
    """Find the best nearby position that has LOS to the target.

    Thin wrapper around :func:`find_tactical_position` kept for
    backwards compatibility.
    """
    return find_tactical_position(
        zone, sx, sy, tx, ty, atk_range,
        fire_lines=fire_lines, origin=origin,
    )


# ── LOS-aware chase waypoint ────────────────────────────────────────

def find_chase_los_waypoint(zone: str, sx: float, sy: float,
                            tx: float, ty: float,
                            max_search: float = 8.0,
                            fire_lines: list[FireLine] | None = None,
                            ) -> tuple[float, float] | None:
    """Find the nearest passable tile that has LOS to the target.

    Used during chase mode when the NPC's direct path to the target
    is wall-blocked.  Instead of charging blindly at the wall, the
    NPC pathfinds to a tile where they can *see* (and then attack)
    the target.

    If ``fire_lines`` is provided, positions inside an ally's fire
    lane are penalised so NPCs prefer flanking positions.
    """
    from core.zone import is_passable as _passable

    best: tuple[float, float] | None = None
    best_score = 999.0
    fl_clearance = _tun("combat.fireline", "clearance", 1.2)

    for radius in (2.0, 4.0, 6.0, 8.0):
        if radius > max_search:
            break
        n_samples = max(8, int(radius * 4))
        for i in range(n_samples):
            angle = math.pi * 2.0 * i / n_samples
            cx = sx + math.cos(angle) * radius
            cy = sy + math.sin(angle) * radius

            if not _passable(zone, cx, cy):
                continue
            if not has_line_of_sight(zone, cx + 0.4, cy + 0.4,
                                    tx + 0.4, ty + 0.4):
                continue

            d_self = math.hypot(cx - sx, cy - sy)
            d_target = math.hypot(cx - tx, cy - ty)
            score = d_self * 0.6 + d_target * 0.4

            if fire_lines:
                for fl in fire_lines:
                    fd = point_fire_line_dist(cx, cy, fl)
                    if fd < fl_clearance:
                        score += (fl_clearance - fd) * 4.0

            if score < best_score:
                best_score = score
                best = (cx, cy)

    return best
