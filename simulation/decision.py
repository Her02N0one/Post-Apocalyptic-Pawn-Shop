"""simulation/decision.py — One-shot AI decision cycle.

When an entity needs to make a decision (arrived at destination,
woke up, interrupted by hunger, etc.), this module runs a priority
stack to produce a plan.

Priority 1: SURVIVAL THREAT  — low HP, find shelter
Priority 2: CRITICAL NEEDS   — hunger, exhaustion
Priority 3: DUTY / ROLE      — farming, guarding, scavenging, trading
Priority 4: DISCRETIONARY    — explore interesting memories
Priority 5: DEFAULT          — return home, idle

The result is one or more events posted to the scheduler.
"""

from __future__ import annotations
import random
from typing import Any

from components import (
    Health, Hunger, Inventory, Identity, Faction,
)
from components.simulation import (
    SubzonePos, WorldMemory, Home, Stockpile, TravelPlan,
)
from simulation.subzone import SubzoneGraph


def run_decision_cycle(world: Any, eid: int, current_node: str,
                       graph: SubzoneGraph, scheduler: Any,
                       game_time: float) -> str:
    """Run the full decision cycle for an entity.

    Returns a string describing the chosen action:
      "rest", "eat", "scavenge", "farm", "guard", "trade",
      "explore", "return_home", "idle"
    """
    # Ensure entity is alive
    if not world.alive(eid):
        return "dead"

    szp = world.get(eid, SubzonePos)
    if szp is None:
        return "no_position"

    # If entity already has an active travel plan, let it continue
    plan = world.get(eid, TravelPlan)
    if plan and not plan.complete:
        _log_decision(world, eid, "continuing existing travel plan")
        return "traveling"

    # Priority 1: SURVIVAL THREAT
    action = _check_survival(world, eid, current_node, graph,
                             scheduler, game_time)
    if action:
        return action

    # Priority 2: CRITICAL NEEDS
    action = _check_critical_needs(world, eid, current_node, graph,
                                   scheduler, game_time)
    if action:
        return action

    # Priority 3: DUTY / ROLE
    action = _check_role_duties(world, eid, current_node, graph,
                                scheduler, game_time)
    if action:
        return action

    # Priority 4: DISCRETIONARY
    action = _check_discretionary(world, eid, current_node, graph,
                                  scheduler, game_time)
    if action:
        return action

    # Priority 5: DEFAULT
    return _default_behavior(world, eid, current_node, graph,
                             scheduler, game_time)


# ═════════════════════════════════════════════════════════════════════
#  PRIORITY 1: SURVIVAL
# ═════════════════════════════════════════════════════════════════════

def _check_survival(world, eid, current_node, graph, scheduler,
                    game_time) -> str | None:
    health = world.get(eid, Health)
    if not health:
        return None

    hp_ratio = health.current / max(health.maximum, 1.0)
    if hp_ratio >= 0.3:
        return None

    # Critically low HP — find shelter and rest
    node = graph.get_node(current_node)
    if node and node.shelter:
        # Already at shelter — rest here
        rest_duration = max(10.0, (1.0 - hp_ratio) * 60.0)
        scheduler.post(
            time=game_time + rest_duration,
            eid=eid,
            event_type="REST_COMPLETE",
            data={"node": current_node, "duration": rest_duration},
        )
        _log_decision(world, eid, f"resting at {current_node} ({rest_duration:.0f} min)")
        return "rest"

    # Find nearest shelter
    from simulation.travel import find_nearest_with, plan_route, begin_travel
    shelter = find_nearest_with(graph, current_node,
                                predicate=lambda n: n.shelter)
    if shelter:
        plan = plan_route(graph, current_node, shelter)
        if plan:
            begin_travel(world, eid, plan, graph, scheduler, game_time)
            _log_decision(world, eid, f"fleeing to shelter at {shelter}")
            return "rest"

    # No shelter found — rest in place anyway
    scheduler.post(
        time=game_time + 15.0,
        eid=eid,
        event_type="REST_COMPLETE",
        data={"node": current_node, "duration": 15.0},
    )
    return "rest"


# ═════════════════════════════════════════════════════════════════════
#  PRIORITY 2: CRITICAL NEEDS
# ═════════════════════════════════════════════════════════════════════

def _check_critical_needs(world, eid, current_node, graph, scheduler,
                          game_time) -> str | None:
    hunger = world.get(eid, Hunger)
    if not hunger:
        return None

    ratio = hunger.current / max(hunger.maximum, 0.01)
    if ratio >= 0.4:
        return None

    # Try to eat from inventory
    inv = world.get(eid, Inventory)
    if inv and len(inv.items) > 0:
        from simulation.events import _try_eat
        if _try_eat(world, eid, game_time):
            from simulation.events import _schedule_hunger_event
            _schedule_hunger_event(world, eid, scheduler, game_time)
            _log_decision(world, eid, "eating from inventory")
            # Continue to next decision after eating
            scheduler.post(game_time + 2.0, eid, "DECISION_CYCLE",
                           {"node": current_node})
            return "eat"

    # Try communal stockpile
    from simulation.events import _try_eat_from_stockpile
    if _try_eat_from_stockpile(world, eid, game_time):
        from simulation.events import _schedule_hunger_event
        _schedule_hunger_event(world, eid, scheduler, game_time)
        _log_decision(world, eid, "eating from stockpile")
        scheduler.post(game_time + 2.0, eid, "DECISION_CYCLE",
                       {"node": current_node})
        return "eat"

    # No food — must scavenge
    return _go_scavenge(world, eid, current_node, graph, scheduler,
                        game_time, reason="hunger")


# ═════════════════════════════════════════════════════════════════════
#  PRIORITY 3: ROLE / DUTY
# ═════════════════════════════════════════════════════════════════════

def _check_role_duties(world, eid, current_node, graph, scheduler,
                       game_time) -> str | None:
    faction = world.get(eid, Faction)
    home = world.get(eid, Home)
    _inv = world.get(eid, Inventory)

    group = faction.group if faction else "neutral"

    # ── Farmer: work the farm if at home
    if home and current_node == home.subzone:
        node = graph.get_node(current_node)
        farm_tags = {"farmable", "wheat", "corn"}
        if node and any(tag in node.resource_nodes for tag in farm_tags):
            # Farm for 15-30 minutes
            work_duration = random.uniform(15.0, 30.0)
            scheduler.post(
                time=game_time + work_duration,
                eid=eid,
                event_type="FINISH_WORK",
                data={
                    "job": "farming",
                    "node": current_node,
                    "yield": random.randint(2, 5),
                },
            )
            _log_decision(world, eid, f"farming at {current_node}")
            return "farm"

    # ── Guard / Settler: patrol near home ──────────────────────────
    # Guards (entities with AttackConfig) patrol up to 2 hops from
    # home, including cross-zone nodes.  Regular settlers stick to
    # direct connections of their home node.
    if group == "guards" or group == "settlers":
        if home and home.subzone:
            home_node = graph.get_node(home.subzone)
            if home_node:
                from components.ai import AttackConfig
                is_guard = world.has(eid, AttackConfig)

                if is_guard:
                    # Guards patrol wider: 2 hops from home
                    patrol_zone: dict[str, float] = dict(
                        home_node.connections)
                    for adj_id in list(home_node.connections.keys()):
                        adj_node = graph.get_node(adj_id)
                        if adj_node:
                            for adj2_id, adj2_time in (
                                    adj_node.connections.items()):
                                if (adj2_id != home.subzone
                                        and adj2_id not in patrol_zone):
                                    patrol_zone[adj2_id] = (
                                        home_node.connections[adj_id]
                                        + adj2_time
                                    )
                else:
                    # Regular settlers: 1 hop from home
                    patrol_zone = dict(home_node.connections)

                # If not within patrol range, return to post
                if (current_node != home.subzone
                        and current_node not in patrol_zone):
                    return _go_home(world, eid, current_node, graph,
                                    scheduler, game_time, reason="patrol")

                # Patrol: pick a random node within patrol zone
                candidates = list(patrol_zone.keys())
                if candidates:
                    patrol_target = random.choice(candidates)
                    cur_node = graph.get_node(current_node)
                    cur_conns = cur_node.connections if cur_node else {}
                    if patrol_target in cur_conns:
                        travel_time = cur_conns[patrol_target]
                        scheduler.post(
                            time=game_time + travel_time,
                            eid=eid,
                            event_type="ARRIVE_NODE",
                            data={"node": patrol_target,
                                  "from": current_node},
                        )
                    else:
                        from simulation.travel import (
                            plan_route, begin_travel,
                        )
                        plan = plan_route(graph, current_node,
                                          patrol_target)
                        if plan:
                            begin_travel(world, eid, plan, graph,
                                         scheduler, game_time)
                        else:
                            scheduler.post(
                                time=game_time + random.uniform(
                                    3.0, 8.0),
                                eid=eid, event_type="DECISION_CYCLE",
                                data={"node": current_node},
                            )
                    szp = world.get(eid, SubzonePos)
                    if szp:
                        szp.subzone = current_node
                    _log_decision(world, eid,
                                  f"patrolling to {patrol_target}")
                    return "guard"

    # ── Scavenger: go scavenge if camp needs supplies
    if group in ("scavengers", "raiders", "settlers"):
        if _settlement_needs_supplies(world, home):
            return _go_scavenge(world, eid, current_node, graph,
                                scheduler, game_time, reason="supply")

    # ── Raider: may raid settlements
    if group == "raiders":
        wmem = world.get(eid, WorldMemory)
        if wmem:
            settlements = wmem.query_prefix("location:",
                                            game_time, stale_ok=True)
            for entry in settlements:
                if entry.data.get("containers", 0) > 0:
                    target = entry.key.replace("location:", "")
                    if target != current_node:
                        from simulation.travel import plan_route, begin_travel
                        plan = plan_route(graph, current_node, target,
                                          wmem, game_time)
                        if plan:
                            begin_travel(world, eid, plan, graph,
                                         scheduler, game_time)
                            _log_decision(world, eid,
                                          f"raiding toward {target}")
                            return "raid"

    return None


# ═════════════════════════════════════════════════════════════════════
#  PRIORITY 4: DISCRETIONARY
# ═════════════════════════════════════════════════════════════════════

def _check_discretionary(world, eid, current_node, graph, scheduler,
                         game_time) -> str | None:
    wmem = world.get(eid, WorldMemory)
    if not wmem:
        return None

    # Check for interesting unexplored areas
    node = graph.get_node(current_node)
    if not node:
        return None

    # Pick a connected node we haven't visited recently
    unvisited = []
    for neighbor in node.connections:
        entry = wmem.recall_fresh(f"location:{neighbor}", game_time)
        if entry is None:
            unvisited.append(neighbor)

    if unvisited and random.random() < 0.3:
        target = random.choice(unvisited)
        travel_time = node.connections[target]
        scheduler.post(
            time=game_time + travel_time,
            eid=eid,
            event_type="ARRIVE_NODE",
            data={"node": target, "from": current_node},
        )
        _log_decision(world, eid, f"exploring {target}")
        return "explore"

    return None


# ═════════════════════════════════════════════════════════════════════
#  PRIORITY 5: DEFAULT
# ═════════════════════════════════════════════════════════════════════

def _default_behavior(world, eid, current_node, graph, scheduler,
                      game_time) -> str:
    home = world.get(eid, Home)

    # If far from home, return
    if home and home.subzone and current_node != home.subzone:
        return _go_home(world, eid, current_node, graph, scheduler,
                        game_time, reason="default") or "idle"

    # Idle at current location — wander to adjacent node occasionally
    node = graph.get_node(current_node)
    if node and node.connections and random.random() < 0.4:
        neighbor = random.choice(list(node.connections.keys()))
        travel_time = node.connections[neighbor]
        scheduler.post(
            time=game_time + travel_time,
            eid=eid,
            event_type="ARRIVE_NODE",
            data={"node": neighbor, "from": current_node},
        )
        _log_decision(world, eid, f"wandering to {neighbor}")
        return "wander"

    # Stay put — schedule next decision after a pause
    wait = random.uniform(5.0, 20.0)
    scheduler.post(
        time=game_time + wait,
        eid=eid,
        event_type="DECISION_CYCLE",
        data={"node": current_node},
    )
    _log_decision(world, eid, f"idling at {current_node} for {wait:.0f} min")
    return "idle"


# ═════════════════════════════════════════════════════════════════════
#  SHARED ACTIONS
# ═════════════════════════════════════════════════════════════════════

def _go_scavenge(world, eid, current_node, graph, scheduler,
                 game_time, reason="") -> str | None:
    """Navigate to the best known loot location and search."""
    wmem = world.get(eid, WorldMemory)

    # Find best container location from memory
    target = None
    if wmem:
        container_memories = wmem.query_prefix("container:",
                                               game_time, stale_ok=True)
        # Sort by freshness, prefer nodes with items
        candidates = []
        for entry in container_memories:
            if entry.data.get("has_items", False):
                node_id = entry.data.get("node", "")
                if node_id and node_id != current_node:
                    candidates.append((entry.timestamp, node_id))

        if candidates:
            # Pick most recently known location with items
            candidates.sort(reverse=True)
            target = candidates[0][1]

    # Fallback: find nearest node with containers
    if not target:
        from simulation.travel import find_nearest_with
        target = find_nearest_with(
            graph, current_node,
            predicate=lambda n: len(n.container_eids) > 0,
        )

    if target:
        from simulation.travel import plan_route, begin_travel
        plan = plan_route(graph, current_node, target, wmem, game_time)
        if plan:
            begin_travel(world, eid, plan, graph, scheduler, game_time)
            _log_decision(world, eid,
                          f"scavenging toward {target} ({reason})")
            return "scavenge"

    # Nothing to scavenge — explore a random direction
    node = graph.get_node(current_node)
    if node and node.connections:
        target = random.choice(list(node.connections.keys()))
        from simulation.travel import plan_route, begin_travel
        plan = plan_route(graph, current_node, target)
        if plan:
            begin_travel(world, eid, plan, graph, scheduler, game_time)
            _log_decision(world, eid, f"exploring randomly ({reason})")
            return "explore"

    return None


def _go_home(world, eid, current_node, graph, scheduler,
             game_time, reason="") -> str | None:
    """Navigate back to home subzone."""
    home = world.get(eid, Home)
    if not home or not home.subzone:
        return None

    if current_node == home.subzone:
        return None

    from simulation.travel import plan_route, begin_travel
    wmem = world.get(eid, WorldMemory)
    plan = plan_route(graph, current_node, home.subzone, wmem, game_time)
    if plan:
        begin_travel(world, eid, plan, graph, scheduler, game_time)
        _log_decision(world, eid,
                      f"returning home to {home.subzone} ({reason})")
        return "return_home"

    return None


def _settlement_needs_supplies(world, home) -> bool:
    """Check if the entity's home settlement needs supplies."""
    if not home or not home.subzone:
        return False
    for seid, stockpile in world.all_of(Stockpile):
        szp = world.get(seid, SubzonePos)
        if not szp:
            continue
        if szp.subzone != home.subzone:
            if not home.zone or szp.zone != home.zone:
                continue
            return stockpile.total_count() < 10
    return False


def _log_decision(world, eid, action_str: str) -> None:
    name = "?"
    ident = world.get(eid, Identity)
    if ident:
        name = ident.name
    print(f"[SIM AI] {name}: {action_str}")
