"""simulation/subzone.py — Subzone graph: world topology for off-screen sim.

The world is divided into zones (tile maps) and subzones (meaningful
areas within a zone).  Every location an entity can be is a subzone
node.  Nodes form a weighted graph where edge weights are travel time
in game-minutes.

    graph = SubzoneGraph()
    graph.add_node(SubzoneNode(id="pharmacy", zone="commercial", ...))
    graph.add_edge("pharmacy", "commercial_strip", travel_time=2.0)
    path = graph.shortest_path("raider_camp", "pharmacy")
"""

from __future__ import annotations
import heapq
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SubzoneNode:
    """A single subzone — a meaningful area within a zone.

    Attributes
    ----------
    id : str
        Unique identifier, e.g. ``"pharmacy"``.
    zone : str
        Parent zone this subzone belongs to.
    anchor : tuple[int, int]
        Tile coordinates of the anchor point within the zone.
    connections : dict[str, float]
        Neighbor subzone ID → travel time in game-minutes.
    threat_level : float
        Ambient danger (informs NPC route planning).
    container_eids : list[int]
        Entity IDs of containers at this node (real, shared state).
    resource_nodes : list[str]
        Harvestable resource identifiers present here.
    shelter : bool
        Can entities rest/sleep here?
    visibility : float
        How easily entities spot each other (affects encounter detection).
    """
    id: str = ""
    zone: str = ""
    anchor: tuple[int, int] = (0, 0)
    connections: dict[str, float] = field(default_factory=dict)
    threat_level: float = 0.0
    container_eids: list[int] = field(default_factory=list)
    resource_nodes: list[str] = field(default_factory=list)
    shelter: bool = False
    visibility: float = 1.0


class SubzoneGraph:
    """Weighted graph of all subzone nodes in the world.

    Provides shortest-path queries and threat-aware routing.
    Stored as a world resource on the ECS World.
    """

    def __init__(self) -> None:
        self.nodes: dict[str, SubzoneNode] = {}

    # ── Construction ─────────────────────────────────────────────────

    def add_node(self, node: SubzoneNode) -> None:
        self.nodes[node.id] = node

    def add_edge(self, a: str, b: str, travel_time: float,
                 bidirectional: bool = True) -> None:
        """Add a connection between two nodes.

        If bidirectional, both A→B and B→A are set.
        """
        if a in self.nodes:
            self.nodes[a].connections[b] = travel_time
        if bidirectional and b in self.nodes:
            self.nodes[b].connections[a] = travel_time

    def get_node(self, node_id: str) -> SubzoneNode | None:
        return self.nodes.get(node_id)

    def zone_nodes(self, zone: str) -> list[SubzoneNode]:
        """Return all subzone nodes belonging to a zone."""
        return [n for n in self.nodes.values() if n.zone == zone]

    # ── Pathfinding ──────────────────────────────────────────────────

    def shortest_path(self, start: str, goal: str) -> list[str] | None:
        """Dijkstra shortest path returning list of node IDs (excluding start).

        Returns None if no path exists.
        """
        if start not in self.nodes or goal not in self.nodes:
            return None
        if start == goal:
            return []

        dist: dict[str, float] = {start: 0.0}
        prev: dict[str, str | None] = {start: None}
        pq: list[tuple[float, str]] = [(0.0, start)]
        visited: set[str] = set()

        while pq:
            d, u = heapq.heappop(pq)
            if u in visited:
                continue
            visited.add(u)
            if u == goal:
                break
            node = self.nodes.get(u)
            if node is None:
                continue
            for neighbor, weight in node.connections.items():
                if neighbor in visited:
                    continue
                nd = d + weight
                if nd < dist.get(neighbor, float("inf")):
                    dist[neighbor] = nd
                    prev[neighbor] = u
                    heapq.heappush(pq, (nd, neighbor))

        if goal not in prev:
            return None

        # Reconstruct path (excluding start)
        path: list[str] = []
        cur: str | None = goal
        while cur is not None and cur != start:
            path.append(cur)
            cur = prev.get(cur)
        path.reverse()
        return path

    def threat_aware_path(self, start: str, goal: str,
                          memory: Any = None,
                          threat_weight: float = 5.0,
                          game_time: float = 0.0) -> list[str] | None:
        """Route that penalises high-threat nodes.

        Combines travel time with threat_level (from the node itself)
        and threat memories from the entity's WorldMemory.
        ``threat_weight`` controls how much threat affects routing.
        """
        if start not in self.nodes or goal not in self.nodes:
            return None
        if start == goal:
            return []

        dist: dict[str, float] = {start: 0.0}
        prev: dict[str, str | None] = {start: None}
        pq: list[tuple[float, str]] = [(0.0, start)]
        visited: set[str] = set()

        while pq:
            d, u = heapq.heappop(pq)
            if u in visited:
                continue
            visited.add(u)
            if u == goal:
                break
            node = self.nodes.get(u)
            if node is None:
                continue
            for neighbor, travel_time in node.connections.items():
                if neighbor in visited:
                    continue
                nnode = self.nodes.get(neighbor)
                threat_cost = 0.0
                if nnode:
                    threat_cost = nnode.threat_level * threat_weight
                # Also check entity memory for known threats
                if memory is not None:
                    mem_entry = memory.recall_fresh(
                        f"threat:{neighbor}", game_time
                    )
                    if mem_entry:
                        threat_cost += mem_entry.data.get("level", 0.0) * threat_weight
                nd = d + travel_time + threat_cost
                if nd < dist.get(neighbor, float("inf")):
                    dist[neighbor] = nd
                    prev[neighbor] = u
                    heapq.heappush(pq, (nd, neighbor))

        if goal not in prev:
            return None

        path: list[str] = []
        cur: str | None = goal
        while cur is not None and cur != start:
            path.append(cur)
            cur = prev.get(cur)
        path.reverse()
        return path

    def travel_time(self, a: str, b: str) -> float:
        """Direct travel time between adjacent nodes, or inf."""
        node = self.nodes.get(a)
        if node is None:
            return float("inf")
        return node.connections.get(b, float("inf"))

    def total_path_time(self, path: list[str], start: str) -> float:
        """Sum of edge weights along a path."""
        total = 0.0
        prev = start
        for node_id in path:
            total += self.travel_time(prev, node_id)
            prev = node_id
        return total

    # ── Queries ──────────────────────────────────────────────────────

    def nodes_with_shelter(self, zone: str | None = None) -> list[SubzoneNode]:
        """Return all shelter nodes, optionally filtered by zone."""
        out = []
        for n in self.nodes.values():
            if not n.shelter:
                continue
            if zone and n.zone != zone:
                continue
            out.append(n)
        return out

    def nodes_with_containers(self, zone: str | None = None) -> list[SubzoneNode]:
        """Return nodes that have at least one container."""
        out = []
        for n in self.nodes.values():
            if not n.container_eids:
                continue
            if zone and n.zone != zone:
                continue
            out.append(n)
        return out

    def nearest_node_to_tile(self, zone: str, x: int, y: int) -> SubzoneNode | None:
        """Find the subzone node closest to tile (x, y) within a zone."""
        best: SubzoneNode | None = None
        best_dist = float("inf")
        for n in self.nodes.values():
            if n.zone != zone:
                continue
            dx = n.anchor[0] - x
            dy = n.anchor[1] - y
            d = dx * dx + dy * dy
            if d < best_dist:
                best_dist = d
                best = n
        return best

    # ── Serialization ────────────────────────────────────────────────

    @classmethod
    def from_toml(cls, filepath: str | Path) -> "SubzoneGraph":
        """Load a subzone graph from a TOML definition file.

        Expected format:

            [nodes.pharmacy]
            zone = "commercial"
            anchor = [12, 8]
            shelter = true
            threat_level = 0.1
            resource_nodes = ["medical_supplies"]

            [nodes.pharmacy.connections]
            commercial_strip = 3.0

        """
        graph = cls()
        filepath = Path(filepath)
        if not filepath.exists():
            print(f"[SUBZONE] graph file not found: {filepath}")
            return graph

        with open(filepath, "rb") as f:
            data = tomllib.load(f)

        for node_id, ndata in data.get("nodes", {}).items():
            if not isinstance(ndata, dict):
                continue
            anchor_raw = ndata.get("anchor", [0, 0])
            anchor = (int(anchor_raw[0]), int(anchor_raw[1]))
            connections = {}
            conn_data = ndata.get("connections", {})
            if isinstance(conn_data, dict):
                connections = {k: float(v) for k, v in conn_data.items()}
            node = SubzoneNode(
                id=node_id,
                zone=ndata.get("zone", ""),
                anchor=anchor,
                connections=connections,
                threat_level=float(ndata.get("threat_level", 0.0)),
                resource_nodes=list(ndata.get("resource_nodes", [])),
                shelter=bool(ndata.get("shelter", False)),
                visibility=float(ndata.get("visibility", 1.0)),
            )
            graph.add_node(node)

        # Second pass: ensure bidirectional connections
        for node_id, node in graph.nodes.items():
            for neighbor, tt in list(node.connections.items()):
                nb = graph.nodes.get(neighbor)
                if nb and node_id not in nb.connections:
                    nb.connections[node_id] = tt

        print(f"[SUBZONE] loaded {len(graph.nodes)} subzone nodes")
        return graph

    def to_dict(self) -> dict:
        """Serialize graph to a dict (for save files)."""
        return {
            "nodes": {
                nid: {
                    "zone": n.zone,
                    "anchor": list(n.anchor),
                    "connections": dict(n.connections),
                    "threat_level": n.threat_level,
                    "container_eids": list(n.container_eids),
                    "resource_nodes": list(n.resource_nodes),
                    "shelter": n.shelter,
                    "visibility": n.visibility,
                }
                for nid, n in self.nodes.items()
            }
        }
