"""logic/faction_ops.py — Canonical faction mutation helpers.

Every call-site that needs to flip an NPC to hostile or trigger a
panic-flee should come through here.  This eliminates the 5+ places
that each did ``faction.disposition = "hostile"`` with ad-hoc logging,
and the 3 places that set ``brain.state["crime_flee_until"]``.

Public API
----------
``make_hostile``       — flip faction + log + optional combat kick-start
``make_flee``          — unarmed civilian panic timer
``entity_display_name`` — consistent name for logging
"""

from __future__ import annotations
from typing import Any

from components import Identity, Faction, Position
from components.ai import Brain, Threat, AttackConfig
from core.tuning import get as _tun


def entity_display_name(world: Any, eid: int) -> str:
    """Return display name of an entity, or ``'?'`` if unknown."""
    ident = world.get(eid, Identity)
    return ident.name if ident else "?"


def make_hostile(world: Any, eid: int, reason: str = "",
                 threat_eid: int | None = None,
                 threat_pos: tuple[float, float] | None = None,
                 game_time: float = 0.0) -> bool:
    """Flip an entity's faction to hostile and optionally kick-start combat.

    Returns True if the disposition actually changed (was not already hostile).
    """
    faction = world.get(eid, Faction)
    if faction is None:
        return False

    changed = faction.disposition != "hostile"
    faction.disposition = "hostile"

    if changed:
        name = entity_display_name(world, eid)
        label = f" ({reason})" if reason else ""
        print(f"[FACTION] {name} is now hostile!{label}")

    # Kick-start combat brain if entity is armed
    if world.has(eid, AttackConfig):
        _activate_combat(world, eid, threat_pos, game_time)

    return changed


def make_flee(world: Any, eid: int, game_time: float,
              duration: float | None = None) -> bool:
    """Set an unarmed NPC's panic-flee timer.

    Returns True if the flee timer was set.
    """
    brain = world.get(eid, Brain)
    if brain is None:
        return False

    if duration is None:
        duration = _tun("combat.hearing", "civilian_flee_duration", 10.0)
    brain.active = True
    brain.state["crime_flee_until"] = game_time + duration

    name = entity_display_name(world, eid)
    print(f"[FACTION] {name} panics — fleeing for {duration:.0f}s")
    return True


def activate_hostile_or_flee(world: Any, eid: int,
                             threat_pos: tuple[float, float] | None,
                             game_time: float, reason: str = "") -> None:
    """Flip to hostile if armed, flee if unarmed.

    Combined helper for alert/sound/crime witnesses.
    """
    if world.has(eid, AttackConfig):
        make_hostile(world, eid, reason=reason,
                     threat_pos=threat_pos, game_time=game_time)
    else:
        make_flee(world, eid, game_time)


# ── internal ─────────────────────────────────────────────────────────

def _activate_combat(world: Any, eid: int,
                     threat_pos: tuple[float, float] | None,
                     game_time: float):
    """Kick a brain into chase mode toward the threat position."""
    brain = world.get(eid, Brain)
    if brain is None:
        return
    brain.active = True
    c = brain.state.setdefault("combat", {})
    c["mode"] = "chase"
    if threat_pos:
        c["p_pos"] = threat_pos

    threat = world.get(eid, Threat)
    if threat:
        threat.last_sensor_time = game_time - threat.sensor_interval
