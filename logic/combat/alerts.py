"""logic/combat/alerts.py — Sound alerts, intel sharing, and faction flipping.

Three alert mechanisms:

1. **Faction alert** — when an entity is attacked, same-faction allies
   within ``alert_radius`` become hostile toward the attacker.
2. **Combat sound** — gunshots / melee impacts alert NPCs within hearing
   radius; guards investigate, civilians flee.
3. **Intel sharing** — active combatants share target locations with
   idle same-faction allies (callouts).

All three use ``world.nearby()`` for O(1) zone-filtered spatial queries
and delegate faction/flee mutations to ``logic.faction_ops``.
"""

from __future__ import annotations

from components import (
    Brain, Faction, Position, Identity,
    AttackConfig, Threat, GameClock, Health,
)
from core.tuning import get as _tun
from logic.faction_ops import (
    make_hostile, make_flee, activate_hostile_or_flee,
    entity_display_name,
)


# ── Faction alert propagation ────────────────────────────────────────

def alert_nearby_faction(world, defender_eid: int, attacker_eid: int):
    """When an entity is attacked, flip its faction to hostile and alert
    nearby same-group allies.

    Works for both player and NPC attackers.
    """
    faction = world.get(defender_eid, Faction)
    if faction is None:
        return
    pos = world.get(defender_eid, Position)
    if pos is None:
        return

    atk_fac = world.get(attacker_eid, Faction)
    if atk_fac is not None and atk_fac.group == faction.group:
        return

    clock = world.res(GameClock)
    game_time = clock.time if clock else 0.0
    attacker_pos = world.get(attacker_eid, Position)
    threat_xy = (attacker_pos.x, attacker_pos.y) if attacker_pos else None

    # Flip the defender itself
    make_hostile(world, defender_eid, reason="attacked",
                 threat_pos=threat_xy, game_time=game_time)

    # Alert same-faction allies in radius (using zone-indexed query)
    r = faction.alert_radius
    for eid, apos, _af, dsq in world.nearby(
        pos.zone, pos.x, pos.y, r, Position, Faction,
    ):
        if eid == defender_eid or eid == attacker_eid:
            continue
        af = world.get(eid, Faction)
        if af is None or af.group != faction.group:
            continue
        # Skip allies already fighting
        ally_brain = world.get(eid, Brain)
        if ally_brain:
            ally_mode = ally_brain.state.get("combat", {}).get("mode")
            if ally_mode in ("chase", "attack", "flee"):
                continue
        activate_hostile_or_flee(world, eid, threat_xy, game_time,
                                reason="ally attacked")


# ── Hearing / sound alert system ─────────────────────────────────────

_SOUND_DEFAULTS = {"gunshot": 1600.0, "melee": 40.0, "shout": 150.0}


def emit_combat_sound(world, source_eid: int, source_pos,
                      sound_type: str = "gunshot"):
    """Alert NPCs within hearing radius of a combat event.

    ``sound_type`` determines the alert radius (via tuning):
      - ``"gunshot"``  → large radius (default 1600 m)
      - ``"melee"``    → small radius (default 40 m)
      - ``"shout"``    → medium radius (default 150 m)

    Non-hostile NPCs that hear the sound become alert — guards
    investigate, civilians flee.
    """
    if source_pos is None:
        return

    radius = _tun("combat.hearing", f"{sound_type}_radius",
                  _SOUND_DEFAULTS.get(sound_type, 150.0))

    source_fac = world.get(source_eid, Faction)
    source_group = source_fac.group if source_fac else None

    clock = world.res(GameClock)
    game_time = clock.time if clock else 0.0

    for eid, npc_pos, _brain, dsq in world.nearby(
        source_pos.zone, source_pos.x, source_pos.y, radius,
        Position, Brain,
    ):
        if eid == source_eid:
            continue

        npc_fac = world.get(eid, Faction)
        if npc_fac and source_group and npc_fac.group == source_group:
            continue

        brain = world.get(eid, Brain)
        if brain is None:
            continue

        c_state = brain.state.get("combat", {})
        active_mode = c_state.get("mode")
        if active_mode in ("chase", "attack", "flee"):
            continue

        if world.has(eid, AttackConfig):
            brain.active = True
            c = brain.state.setdefault("combat", {})
            if c.get("mode") in (None, "idle", "searching"):
                search_dur = _tun("combat.hearing", "search_duration", 5.0)
                c["mode"] = "searching"
                c["search_source"] = (source_pos.x, source_pos.y)
                c["search_until"] = game_time + search_dur
                c["_search_start"] = game_time
                threat = world.get(eid, Threat)
                if threat:
                    threat.last_sensor_time = game_time - threat.sensor_interval
                name = entity_display_name(world, eid)
                print(f"[HEARING] {name} heard {sound_type} → searching")
        else:
            make_flee(world, eid, game_time,
                      duration=_tun("combat.hearing",
                                    "civilian_flee_duration", 10.0))


# ── Intel sharing ────────────────────────────────────────────────────

def share_combat_intel(world, eid: int, pos, target_pos_xy: tuple,
                       game_time: float):
    """Active combatant shares target location with idle same-faction allies.

    Called during the sensor tick when an NPC in chase/attack mode has
    a confirmed target.  Nearby idle/returning allies enter
    ``'searching'`` toward the target.
    """
    fac = world.get(eid, Faction)
    if fac is None:
        return
    group = fac.group

    callout_radius = _tun("combat.intel", "callout_radius", 12.0)
    search_dur = _tun("combat.hearing", "search_duration", 5.0)

    for ally_eid, ally_pos, _af, dsq in world.nearby(
        pos.zone, pos.x, pos.y, callout_radius,
        Position, Faction,
    ):
        if ally_eid == eid:
            continue
        af = world.get(ally_eid, Faction)
        if af is None or af.group != group:
            continue
        if not world.has(ally_eid, Brain):
            continue
        if not world.has(ally_eid, AttackConfig):
            continue

        brain = world.get(ally_eid, Brain)
        c = brain.state.get("combat", {})
        ally_mode = c.get("mode")
        if ally_mode not in (None, "idle", "return"):
            continue

        brain.active = True
        c = brain.state.setdefault("combat", {})
        c["mode"] = "searching"
        c["search_source"] = target_pos_xy
        c["search_until"] = game_time + search_dur
        c["_search_start"] = game_time
        threat = world.get(ally_eid, Threat)
        if threat:
            threat.last_sensor_time = game_time - threat.sensor_interval

        name = entity_display_name(world, ally_eid)
        print(f"[INTEL] {name} alerted by ally callout → searching")
