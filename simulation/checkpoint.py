"""simulation/checkpoint.py — Checkpoint evaluation at subzone arrivals.

When an entity's ARRIVE_NODE event fires, this module runs the
checkpoint evaluation:

1. PRESENCE CHECK — Who else is at this node?  (+ adjacent nodes)
2. DISCOVERY CHECK — What's here that the entity didn't know?
3. INTERRUPT CHECK — Should the entity deviate from their plan?
4. POST NEXT EVENT

Adjacent-node awareness uses the SubzoneNode ``visibility`` field
to modulate detection probability — high-visibility nodes (open road)
let entities spot hostiles from adjacent nodes, while low-visibility
nodes (dense ruins, indoors) require co-location.
"""

from __future__ import annotations
import hashlib
import random
from typing import Any

from components import Health, Hunger, Inventory, Faction, Identity
from components.simulation import SubzonePos, TravelPlan, WorldMemory
from simulation.subzone import SubzoneGraph, SubzoneNode


def run_checkpoint(world: Any, eid: int, node_id: str,
                   graph: SubzoneGraph, scheduler: Any,
                   game_time: float) -> str:
    """Run the full checkpoint evaluation for an entity arriving at a node.

    Returns a string indicating the outcome:
      "continue"  — entity proceeds on their path
      "encounter" — hostile encounter initiated
      "divert"    — entity diverted to a new activity
      "arrived"   — entity reached their destination
    """
    node = graph.get_node(node_id)
    if node is None:
        return "continue"

    # 1. PRESENCE CHECK
    encounter_result = _presence_check(world, eid, node_id, graph,
                                       scheduler, game_time)
    if encounter_result == "encounter":
        return "encounter"

    # 2. DISCOVERY CHECK
    _discovery_check(world, eid, node, game_time)

    # 3. INTERRUPT CHECK
    interrupt = _interrupt_check(world, eid, node, graph,
                                 scheduler, game_time)
    if interrupt:
        return "divert"

    # 4. Continue travel or arrive
    from simulation.travel import continue_travel
    plan = world.get(eid, TravelPlan)
    if plan and not plan.complete:
        continued = continue_travel(world, eid, node_id, graph,
                                    scheduler, game_time)
        return "continue" if continued else "arrived"

    return "arrived"


def _presence_check(world: Any, eid: int, node_id: str,
                    graph: SubzoneGraph, scheduler: Any,
                    game_time: float) -> str | None:
    """Check who else is at this node and adjacent nodes.

    Same-node entities are always detected.  Adjacent-node entities
    are detected based on the visibility of both nodes — high
    visibility means you can spot them from next door.

    Returns "encounter" if hostile combat was triggered, else None.
    """
    my_faction = world.get(eid, Faction)
    node = graph.get_node(node_id)

    # ── Same-node check ──────────────────────────────────────────
    others_here = entities_at_node(world, node_id, exclude=eid)

    for other_eid in others_here:
        if not world.alive(other_eid):
            continue

        other_faction = world.get(other_eid, Faction)
        relationship = _check_relationship(my_faction, other_faction)

        if relationship == "hostile":
            from simulation.stat_combat import resolve_encounter
            resolve_encounter(world, eid, other_eid, node_id,
                              graph, scheduler, game_time)
            return "encounter"

        elif relationship == "friendly":
            _share_memories(world, eid, other_eid, game_time)

    # ── Adjacent-node awareness ──────────────────────────────────
    if node:
        my_visibility = node.visibility if node.visibility else 0.5
        for neighbor_id in node.connections:
            neighbor = graph.get_node(neighbor_id)
            if not neighbor:
                continue
            # Detection chance = product of both nodes' visibility
            detection_chance = my_visibility * (
                neighbor.visibility if neighbor.visibility else 0.5
            )
            # Deterministic hash-based roll (avoids consuming global
            # random state, which would break seed-dependent tests)
            h = hashlib.md5(
                f"{eid}:{neighbor_id}:{int(game_time)}".encode()
            ).hexdigest()
            detection_roll = int(h[:8], 16) / 0xFFFFFFFF
            if detection_roll > detection_chance:
                continue  # low visibility — didn't spot them

            neighbors_there = entities_at_node(world, neighbor_id,
                                               exclude=eid)
            for other_eid in neighbors_there:
                if not world.alive(other_eid):
                    continue
                other_faction = world.get(other_eid, Faction)
                relationship = _check_relationship(my_faction,
                                                   other_faction)

                if relationship == "hostile":
                    # Hostile spotted at adjacent node — move to engage
                    # (or flee if low HP)
                    health = world.get(eid, Health)
                    if health:
                        hp_ratio = health.current / max(health.maximum, 1)
                        if hp_ratio < 0.3:
                            # Too weak — flee away from the threat
                            _log_awareness(world, eid, other_eid,
                                           neighbor_id, "fleeing")
                            continue  # let interrupt check handle it

                    # Move to the node to engage
                    travel_time = node.connections.get(neighbor_id, 2.0)
                    scheduler.post(
                        time=game_time + travel_time,
                        eid=eid,
                        event_type="ARRIVE_NODE",
                        data={"node": neighbor_id, "from": node_id},
                    )
                    _log_awareness(world, eid, other_eid,
                                   neighbor_id, "engaging")
                    return "encounter"

                elif relationship == "friendly":
                    # Note their presence in memory
                    wmem = world.get(eid, WorldMemory)
                    if wmem:
                        other_ident = world.get(other_eid, Identity)
                        wmem.observe(
                            f"nearby:{other_eid}",
                            data={
                                "node": neighbor_id,
                                "name": (other_ident.name
                                         if other_ident else "unknown"),
                            },
                            game_time=game_time,
                            ttl=60.0,
                        )

    return None


def _discovery_check(world: Any, eid: int, node: SubzoneNode,
                     game_time: float) -> None:
    """Record observations about this node into entity's WorldMemory."""
    wmem = world.get(eid, WorldMemory)
    if wmem is None:
        return

    # Observe the location itself
    wmem.observe(
        f"location:{node.id}",
        data={
            "zone": node.zone,
            "shelter": node.shelter,
            "threat_level": node.threat_level,
            "containers": len(node.container_eids),
            "resources": list(node.resource_nodes),
        },
        game_time=game_time,
        ttl=600.0,  # 10 game-hours
    )

    # Observe containers (rough contents check)
    for ceid in node.container_eids:
        inv = world.get(ceid, Inventory)
        if inv is not None:
            has_items = len(inv.items) > 0
            wmem.observe(
                f"container:{ceid}",
                data={
                    "node": node.id,
                    "has_items": has_items,
                    "item_count": sum(inv.items.values()) if has_items else 0,
                },
                game_time=game_time,
                ttl=300.0,
            )

    # Observe other entities present
    others = entities_at_node(world, node.id, exclude=eid)
    for other_eid in others:
        if not world.alive(other_eid):
            continue
        other_ident = world.get(other_eid, Identity)
        other_faction = world.get(other_eid, Faction)
        wmem.observe(
            f"entity:{other_eid}",
            data={
                "node": node.id,
                "name": other_ident.name if other_ident else "unknown",
                "group": other_faction.group if other_faction else "unknown",
                "disposition": other_faction.disposition if other_faction else "neutral",
            },
            game_time=game_time,
            ttl=200.0,
        )


def _interrupt_check(world: Any, eid: int, node: SubzoneNode,
                     graph: SubzoneGraph, scheduler: Any,
                     game_time: float) -> bool:
    """Fast priority filter: should entity deviate from current plan?

    Returns True if entity was diverted, False to continue.
    """
    # Check critical hunger + food available here
    hunger = world.get(eid, Hunger)
    if hunger:
        ratio = hunger.current / max(hunger.maximum, 0.01)
        if ratio < 0.25:
            inv = world.get(eid, Inventory)
            # Has food in inventory — stop to eat
            if inv and len(inv.items) > 0:
                scheduler.post(
                    time=game_time + 2.0,  # 2 min eating pause
                    eid=eid,
                    event_type="FINISH_EAT",
                    data={"node": node.id},
                )
                return True
            # No food but containers here — search for food
            if node.container_eids:
                scheduler.post(
                    time=game_time + 5.0,  # 5 min search
                    eid=eid,
                    event_type="FINISH_SEARCH",
                    data={
                        "node": node.id,
                        "container": node.container_eids[0],
                    },
                )
                return True

    # Check low HP + shelter here
    health = world.get(eid, Health)
    if health and node.shelter:
        hp_ratio = health.current / max(health.maximum, 0.01)
        if hp_ratio < 0.4:
            # Rest here
            rest_duration = max(5.0, (1.0 - hp_ratio) * 30.0)
            scheduler.post(
                time=game_time + rest_duration,
                eid=eid,
                event_type="REST_COMPLETE",
                data={"node": node.id, "duration": rest_duration},
            )
            return True

    return False


def _check_relationship(my_faction: Any, other_faction: Any) -> str:
    """Determine relationship between two entities based on Faction.

    Returns "hostile", "friendly", or "neutral".
    """
    if my_faction is None or other_faction is None:
        return "neutral"

    # Same group is always friendly
    if my_faction.group == other_faction.group:
        return "friendly"

    # Check dispositions
    if my_faction.disposition == "hostile" or other_faction.disposition == "hostile":
        return "hostile"

    if my_faction.disposition == "friendly" and other_faction.disposition == "friendly":
        return "friendly"

    return "neutral"


def _share_memories(world: Any, eid_a: int, eid_b: int,
                    game_time: float) -> None:
    """Friendly entities share some WorldMemory entries.

    Shared categories:
    - ``location:`` — known locations and their features
    - ``threat:`` — dangerous areas
    - ``crime:`` — witnessed player crimes (word-of-mouth reputation)

    This is the core word-of-mouth mechanism: a witness tells a guard,
    the guard tells other settlers, and eventually everyone knows.
    """
    mem_a = world.get(eid_a, WorldMemory)
    mem_b = world.get(eid_b, WorldMemory)
    if mem_a is None or mem_b is None:
        return

    # Share location memories
    _transfer_entries(mem_a, mem_b, "location:", game_time)
    _transfer_entries(mem_b, mem_a, "location:", game_time)

    # Share threat memories
    _transfer_entries(mem_a, mem_b, "threat:", game_time)
    _transfer_entries(mem_b, mem_a, "threat:", game_time)

    # Share crime memories — word-of-mouth reputation spreading
    crime_spread_a = _transfer_entries(mem_a, mem_b, "crime:", game_time)
    crime_spread_b = _transfer_entries(mem_b, mem_a, "crime:", game_time)

    # If crime info was received, check if recipient is a guard
    if crime_spread_a > 0:
        _check_guard_crime_reaction(world, eid_b, game_time)
    if crime_spread_b > 0:
        _check_guard_crime_reaction(world, eid_a, game_time)


def _transfer_entries(src: Any, dst: Any, prefix: str,
                      game_time: float) -> int:
    """Copy fresh entries from src to dst if dst doesn't have them.

    Returns count of entries transferred.
    """
    count = 0
    for entry in src.query_prefix(prefix, game_time, stale_ok=False):
        existing = dst.recall(entry.key)
        if existing is None or existing.timestamp < entry.timestamp:
            dst.observe(entry.key, entry.data, game_time, entry.ttl)
            count += 1
    return count


def _check_guard_crime_reaction(world: Any, eid: int,
                                game_time: float) -> None:
    """If this entity is a guard who just learned of crimes, turn hostile.

    Guard = has AttackConfig component (combat-capable) + friendly faction.
    """
    from components.ai import AttackConfig
    if not world.has(eid, AttackConfig):
        return
    faction = world.get(eid, Faction)
    if not faction or faction.disposition != "friendly":
        return

    wmem = world.get(eid, WorldMemory)
    if wmem is None:
        return

    crimes = wmem.query_prefix("crime:", game_time, stale_ok=False)
    if crimes:
        from logic.faction_ops import make_hostile
        make_hostile(world, eid, reason="learned crimes via word-of-mouth",
                     game_time=game_time)


def _log_awareness(world: Any, eid: int, other_eid: int,
                   at_node: str, action: str) -> None:
    """Log adjacent-node awareness event."""
    name = "?"
    ident = world.get(eid, Identity)
    if ident:
        name = ident.name
    other_name = "?"
    other_ident = world.get(other_eid, Identity)
    if other_ident:
        other_name = other_ident.name
    print(f"[SIM AWARE] {name} spotted {other_name} at {at_node}"
          f" — {action}")


def entities_at_node(world: Any, node_id: str,
                     exclude: int | None = None) -> list[int]:
    """Return all entity IDs whose SubzonePos.subzone matches ``node_id``."""
    results = []
    for eid, szp in world.all_of(SubzonePos):
        if szp.subzone == node_id:
            if exclude is not None and eid == exclude:
                continue
            if world.alive(eid):
                results.append(eid)
    return results
