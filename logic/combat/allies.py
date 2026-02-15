"""logic/combat/allies.py — Shared helpers for same-faction ally queries.

Many combat subsystems need to iterate over allies in the same zone
and faction.  This module centralises that boilerplate into a single
generator so every call site is just a ``for`` loop.

Also provides ``PointProxy`` — a lightweight namedtuple replacement
for the ad-hoc ``type("P", (), {"x": …, "y": …})()`` hack that was
scattered across the combat package.
"""

from __future__ import annotations
from collections import namedtuple

from core.ecs import World
from components import Position, Health, Faction


# ── Lightweight position proxy ───────────────────────────────────────

PointProxy = namedtuple("PointProxy", ("x", "y"))
"""Minimal x/y container passed to steering helpers that expect an
object with ``.x`` and ``.y`` attributes."""


# ── Same-faction ally iteration ──────────────────────────────────────

def iter_same_faction_allies(world: World, eid: int, pos):
    """Yield ``(ally_eid, ally_pos)`` for every same-faction, same-zone,
    alive ally — excluding *eid* itself.

    Uses ``world.query_zone()`` for O(1) zone lookup instead of a full
    table scan of all entities.

    Shared by:
      - ``targeting.ally_in_line_of_fire``
      - ``targeting.ally_near_target``
      - ``targeting.get_ally_positions``
      - ``targeting.find_blocking_ally``
      - ``fireline.get_ally_fire_lines``
    """
    fac = world.get(eid, Faction)
    if fac is None:
        return
    group = fac.group

    for aid, apos, _hp in world.query_zone(pos.zone, Position, Health):
        if aid == eid:
            continue
        af = world.get(aid, Faction)
        if af is None or af.group != group:
            continue
        yield aid, apos
