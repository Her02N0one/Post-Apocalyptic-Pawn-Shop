"""simulation/travel.py — Route planning through the subzone graph.

Provides helpers for computing travel paths, posting ARRIVE_NODE
events, and managing TravelPlan components.
"""

from __future__ import annotations
from typing import Any

from components.simulation import SubzonePos, TravelPlan, WorldMemory
from simulation.subzone import SubzoneGraph


def plan_route(graph: SubzoneGraph,
               start: str,
               goal: str,
               world_memory: WorldMemory | None = None,
               game_time: float = 0.0,
               threat_weight: float = 5.0) -> TravelPlan | None:
    """Compute a travel plan from ``start`` to ``goal``.

    Uses threat-aware routing if the entity has WorldMemory,
    falls back to shortest path otherwise.
    Returns None if no path exists.
    """
    if start == goal:
        return TravelPlan(path=[], destination=goal)

    if world_memory:
        path = graph.threat_aware_path(
            start, goal,
            memory=world_memory,
            threat_weight=threat_weight,
            game_time=game_time,
        )
    else:
        path = graph.shortest_path(start, goal)

    if path is None:
        return None

    return TravelPlan(path=path, current_index=0, destination=goal)


def begin_travel(world: Any, eid: int, plan: TravelPlan,
                 graph: SubzoneGraph, scheduler: Any,
                 current_time: float) -> None:
    """Attach TravelPlan and schedule the first ARRIVE_NODE event.

    ``world`` is the ECS World.
    ``scheduler`` is the WorldScheduler.
    """
    world.add(eid, plan)

    subzone_pos = world.get(eid, SubzonePos)
    if subzone_pos is None:
        return

    next_node = plan.next_node
    if next_node is None:
        # Already at destination
        return

    travel_time = graph.travel_time(subzone_pos.subzone, next_node)
    if travel_time == float("inf"):
        travel_time = 5.0  # fallback: 5 game-minutes

    scheduler.post(
        time=current_time + travel_time,
        eid=eid,
        event_type="ARRIVE_NODE",
        data={"node": next_node, "from": subzone_pos.subzone},
    )


def continue_travel(world: Any, eid: int, arrived_node: str,
                    graph: SubzoneGraph, scheduler: Any,
                    current_time: float) -> bool:
    """Advance the TravelPlan after arriving at a node.

    Posts the next ARRIVE_NODE if path continues.
    Returns True if travel continues, False if journey complete.
    """
    plan = world.get(eid, TravelPlan)
    if plan is None:
        return False

    # Advance index
    plan.advance()

    next_node = plan.next_node
    if next_node is None:
        # Journey complete — remove TravelPlan
        world.remove(eid, TravelPlan)
        return False

    travel_time = graph.travel_time(arrived_node, next_node)
    if travel_time == float("inf"):
        travel_time = 5.0

    scheduler.post(
        time=current_time + travel_time,
        eid=eid,
        event_type="ARRIVE_NODE",
        data={"node": next_node, "from": arrived_node},
    )
    return True


def find_nearest_with(graph: SubzoneGraph,
                      start: str,
                      predicate: callable,
                      max_hops: int = 20) -> str | None:
    """BFS through the subzone graph to find the nearest node matching
    a predicate function.

    ``predicate`` receives a SubzoneNode and returns bool.
    Returns the node ID, or None.
    """
    from collections import deque

    if start not in graph.nodes:
        return None

    visited: set[str] = {start}
    queue: deque[tuple[str, int]] = deque([(start, 0)])

    # Check start node first
    if predicate(graph.nodes[start]):
        return start

    while queue:
        current, depth = queue.popleft()
        if depth >= max_hops:
            continue
        node = graph.nodes.get(current)
        if not node:
            continue
        for neighbor in node.connections:
            if neighbor in visited:
                continue
            visited.add(neighbor)
            nnode = graph.nodes.get(neighbor)
            if nnode and predicate(nnode):
                return neighbor
            queue.append((neighbor, depth + 1))

    return None
