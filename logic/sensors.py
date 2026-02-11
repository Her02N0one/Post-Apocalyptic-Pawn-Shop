"""logic/sensors.py — Periodic sensor system for AI entities.

Sensors are throttled functions that scan the world and write
observations into an entity's ``Memory``.  The AI orchestrator calls
``run_sensors`` once per entity per AI tick; individual sensors
self-throttle via ``Threat.sensor_interval``.

Built-in sensors
----------------
NearestHostileSensor  — finds closest hostile-to-us entity
HurtSensor            — detects recent damage (HitFlash)
HungerSensor          — sets ``is_hungry`` flag

Sensor protocol
~~~~~~~~~~~~~~~
Each sensor is a callable with signature::

    (world, eid, memory, game_time) → None

Sensors write their results into *memory*.  They are expected to
self-throttle (only run every N seconds) using the shared
``Threat.sensor_interval`` via the ``_last_sensor`` memory key.

``run_sensors`` handles the global throttle gate so individual sensor
callables just do their work unconditionally when invoked.
"""

from __future__ import annotations
import math
from core.ecs import World
from components import (
    Position, Health, Hunger, Faction, HitFlash, Player,
)
from components.ai import Threat, Memory, AttackConfig
from components.simulation import WorldMemory


# ══════════════════════════════════════════════════════════════════════
#  SENSOR REGISTRY
# ══════════════════════════════════════════════════════════════════════

# sensor_name → callable(world, eid, memory, game_time)
_SENSOR_REGISTRY: dict[str, callable] = {}


def register_sensor(name: str, fn):
    _SENSOR_REGISTRY[name] = fn


def get_sensor(name: str):
    return _SENSOR_REGISTRY.get(name)


# ══════════════════════════════════════════════════════════════════════
#  TOP-LEVEL RUNNER (called by ai_system per entity)
# ══════════════════════════════════════════════════════════════════════

def run_sensors(
    world: World,
    eid: int,
    memory: Memory,
    game_time: float,
    sensor_names: list[str] | None = None,
) -> None:
    """Execute sensors for one entity, respecting the throttle interval.

    If *sensor_names* is ``None`` all registered sensors run.
    """
    threat = world.get(eid, Threat)
    interval = threat.sensor_interval if threat else 0.25
    last = memory.get("_last_sensor", 0.0)

    if game_time - last < interval:
        return  # not yet due

    memory.set("_last_sensor", game_time)

    names = sensor_names or list(_SENSOR_REGISTRY.keys())
    for name in names:
        fn = _SENSOR_REGISTRY.get(name)
        if fn:
            fn(world, eid, memory, game_time)


# ══════════════════════════════════════════════════════════════════════
#  BUILT-IN SENSORS
# ══════════════════════════════════════════════════════════════════════


def _nearest_hostile_sensor(world: World, eid: int, memory: Memory,
                            game_time: float) -> None:
    """Find the nearest entity that is hostile *to us*.

    Stores ``nearest_hostile`` → ``(target_eid, x, y, dist)``
    in memory.  Clears the key if no hostile found.

    Detection range is capped at ``Threat.aggro_radius`` (or 10.0).
    """
    pos = world.get(eid, Position)
    if not pos:
        memory.forget("nearest_hostile")
        return

    threat = world.get(eid, Threat)
    aggro = threat.aggro_radius if threat else 10.0

    my_faction = world.get(eid, Faction)

    best = None
    best_dist = aggro + 1

    # Scan same-zone entities
    zone_eids = world.zone_entities(pos.zone)
    for other_eid in zone_eids:
        if other_eid == eid:
            continue
        o_pos = world.get(other_eid, Position)
        if o_pos is None:
            continue
        d = math.hypot(pos.x - o_pos.x, pos.y - o_pos.y)
        if d > aggro:
            continue

        # Determine if *other* is hostile to *us*
        if _is_hostile_to(world, eid, other_eid, my_faction):
            if d < best_dist:
                best = (other_eid, o_pos.x, o_pos.y, d)
                best_dist = d

    if best:
        memory.set("nearest_hostile", best)
    else:
        memory.forget("nearest_hostile")


def _is_hostile_to(world, eid, other_eid, my_faction) -> bool:
    """Return True if *other_eid* should be considered hostile to *eid*.

    Logic:
    - Player is always hostile to entities with ``disposition == 'hostile'``.
    - Entities without a Faction are treated as hostile (backward compat).
    - Hostile mobs target the player.
    - Two factions are hostile if one's disposition is ``'hostile'``.
    """
    # If I'm hostile and the other is the player → yes
    if my_faction and my_faction.disposition == "hostile":
        if world.has(other_eid, Player):
            return True

    # If the other has hostile disposition toward me
    other_faction = world.get(other_eid, Faction)
    if other_faction is None:
        # No faction = wild mob, aggressive to everything
        if world.has(other_eid, Health):
            return True
        return False

    if other_faction.disposition == "hostile":
        return True

    # If I'm the player and the other is hostile
    if world.has(eid, Player) and other_faction.disposition == "hostile":
        return True

    return False


def _hurt_sensor(world: World, eid: int, memory: Memory,
                 game_time: float) -> None:
    """Detect recent damage via HitFlash.

    Sets ``attacker`` in memory with a short TTL so rage goals can
    react.  Currently stores eid=0 (unknown attacker) — will be
    upgraded when a damage-source tracking component is added.
    """
    hf = world.get(eid, HitFlash)
    if hf and hf.remaining > 0.05:
        # We were recently hit — record it
        # Try to guess attacker: nearest hostile (best available signal)
        nh = memory.get("nearest_hostile")
        attacker = nh[0] if nh else None
        if attacker is not None:
            memory.set("attacker", attacker, ttl=5.0, game_time=game_time)
    # Don't clear attacker — let TTL handle expiry


def _hunger_sensor(world: World, eid: int, memory: Memory,
                   game_time: float) -> None:
    """Set ``is_hungry`` flag when hunger drops below threshold."""
    hunger = world.get(eid, Hunger)
    if hunger is None:
        memory.forget("is_hungry")
        return
    ratio = hunger.current / max(hunger.maximum, 0.01)
    if ratio < 0.4:
        memory.set("is_hungry", True)
    else:
        memory.forget("is_hungry")


def _crime_awareness_sensor(world: World, eid: int, memory: Memory,
                            game_time: float) -> None:
    """Guards who know about player crimes turn hostile when nearby.

    When a guard NPC (has AttackConfig) with ``crime:`` entries in
    their WorldMemory detects the player within aggro range, they
    switch to hostile disposition.  Non-guard NPCs with crime
    knowledge store a warning memory but don't attack.
    """
    faction = world.get(eid, Faction)
    if not faction or faction.disposition == "hostile":
        return  # already hostile or no faction

    # Check if this NPC has crime memories
    wmem = world.get(eid, WorldMemory)
    if wmem is None:
        return
    crimes = wmem.query_prefix("crime:", game_time, stale_ok=False)
    if not crimes:
        return

    # NPC knows about crimes — check if player is nearby
    pos = world.get(eid, Position)
    if not pos:
        return

    threat = world.get(eid, Threat)
    detect_radius = threat.aggro_radius if threat else 10.0

    for p_eid, p_pos in world.all_of(Position):
        if not world.has(p_eid, Player):
            continue
        if p_pos.zone != pos.zone:
            continue
        dx = pos.x - p_pos.x
        dy = pos.y - p_pos.y
        dist = (dx * dx + dy * dy) ** 0.5
        if dist > detect_radius:
            continue

        # Player is nearby and NPC knows about crimes
        is_guard = world.has(eid, AttackConfig)
        if is_guard:
            # Guard turns hostile
            faction.disposition = "hostile"
            from components import Identity
            ident = world.get(eid, Identity)
            name = ident.name if ident else f"guard_{eid}"
            print(f"[CRIME] {name} confronts the player about theft!")
            memory.set("crime_confrontation", True)
        else:
            # Civilian — remember the player is a criminal
            memory.set("player_is_criminal", True)
        break


# ── Register built-ins ───────────────────────────────────────────────

register_sensor("nearest_hostile", _nearest_hostile_sensor)
register_sensor("hurt", _hurt_sensor)
register_sensor("hunger", _hunger_sensor)
register_sensor("crime_awareness", _crime_awareness_sensor)
