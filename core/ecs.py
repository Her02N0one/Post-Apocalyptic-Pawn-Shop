"""
core/ecs.py — Entity-Component-System

Entities are ints. Components are any object, stored by type.
Query by component types to get matching entities.

    w = World()
    e = w.spawn()
    w.add(e, Position(5.0, 3.0))
    w.add(e, Health(100))

    for eid, pos, hp in w.query(Position, Health):
        pos.x += 1
        hp.current -= 5
"""

from __future__ import annotations
from typing import Any, Iterator


class World:
    def __init__(self):
        self._next_id = 0
        self._stores: dict[type, dict[int, Any]] = {}
        self._dead: set[int] = set()
        # Zone index: zone_name → set of entity IDs whose Position.zone
        # matches.  Maintained automatically by zone_add / zone_set so
        # systems can query ``world.zone_entities("overworld")`` in O(1)
        # instead of scanning every Position component.
        self._zone_index: dict[str, set[int]] = {}

    # -- Zone helpers (keep index in sync) --

    def zone_add(self, eid: int, zone: str):
        """Register *eid* in the zone index for *zone*."""
        self._zone_index.setdefault(zone, set()).add(eid)

    def zone_set(self, eid: int, new_zone: str):
        """Move *eid* from its current zone to *new_zone* in the index."""
        for z, eids in self._zone_index.items():
            eids.discard(eid)
        self._zone_index.setdefault(new_zone, set()).add(eid)

    def zone_entities(self, zone: str) -> set[int]:
        """Return the set of living entity IDs in *zone* (fast O(1) lookup)."""
        return self._zone_index.get(zone, set()) - self._dead

    # -- Spatial queries (use zone index for O(1) zone lookup) --

    def query_zone(self, zone: str, *types: type) -> Iterator[tuple]:
        """Yield ``(eid, comp1, comp2, ...)`` for zone-filtered entities.

        Like ``query()`` but only examines entities registered in *zone*,
        avoiding the full table scan.
        """
        eids = self.zone_entities(zone)
        if not eids or not types:
            return
        # Ensure every eid has all required component types
        stores = [(t, self._stores.get(t, {})) for t in types]
        for eid in eids:
            if all(eid in s for _, s in stores):
                yield (eid, *(s[eid] for _, s in stores))

    def nearby(self, zone: str, x: float, y: float, radius: float,
               *types: type) -> Iterator[tuple]:
        """Yield ``(eid, comp1, comp2, ..., dist_sq)`` within *radius*.

        Zone-filtered, distance-filtered.  The last element of each
        tuple is the squared distance so callers can sort/compare
        without an extra sqrt.

        Usage::

            for eid, pos, health, dsq in world.nearby("town", 5, 3, 10, Position, Health):
                ...

        """
        r_sq = radius * radius
        for result in self.query_zone(zone, *types):
            eid = result[0]
            pos = result[1]  # first type should be Position
            dx = pos.x - x
            dy = pos.y - y
            dsq = dx * dx + dy * dy
            if dsq <= r_sq:
                yield (*result, dsq)

    # -- Entities --

    def spawn(self) -> int:
        self._next_id += 1
        return self._next_id

    def kill(self, eid: int):
        self._dead.add(eid)

    def alive(self, eid: int) -> bool:
        return eid not in self._dead

    def purge(self):
        """Remove dead entities from all stores. Call once per frame."""
        for store in self._stores.values():
            for eid in self._dead:
                store.pop(eid, None)
        # clean zone index
        for eids in self._zone_index.values():
            eids -= self._dead
        self._dead.clear()

    # -- Components --

    def add(self, eid: int, comp: Any):
        t = type(comp)
        if t not in self._stores:
            self._stores[t] = {}
        self._stores[t][eid] = comp

    def get(self, eid: int, comp_type: type) -> Any | None:
        return self._stores.get(comp_type, {}).get(eid)

    def has(self, eid: int, comp_type: type) -> bool:
        return eid in self._stores.get(comp_type, {})

    def remove(self, eid: int, comp_type: type):
        store = self._stores.get(comp_type)
        if store and eid in store:
            del store[eid]

    # -- Queries --

    def query(self, *types: type) -> Iterator[tuple]:
        """Yield (eid, comp1, comp2, ...) for entities that have ALL types."""
        if not types:
            return
        # Iterate over the smallest bucket
        buckets = [(t, self._stores.get(t, {})) for t in types]
        buckets.sort(key=lambda b: len(b[1]))
        smallest = buckets[0][1]
        for eid in smallest:
            if eid in self._dead:
                continue
            if all(eid in b for _, b in buckets):
                yield (eid, *(self._stores[t][eid] for t in types))

    def query_one(self, *types: type) -> tuple | None:
        """Return first match or None."""
        for result in self.query(*types):
            return result
        return None

    def all_of(self, comp_type: type) -> Iterator[tuple[int, Any]]:
        """Yield (eid, component) for every entity with this type."""
        for eid, comp in self._stores.get(comp_type, {}).items():
            if eid not in self._dead:
                yield eid, comp

    def count(self, comp_type: type) -> int:
        return sum(1 for _ in self.all_of(comp_type))

    # -- Resources (singletons, not tied to entities) --

    def set_res(self, resource: Any):
        t = type(resource)
        if t not in self._stores:
            self._stores[t] = {}
        self._stores[t][-1] = resource

    def res(self, res_type: type) -> Any | None:
        return self._stores.get(res_type, {}).get(-1)

    # -- Debug --

    def debug_dump(self) -> dict[int, list[Any]]:
        """Return {eid: [components...]} for every living entity."""
        entities: dict[int, list[Any]] = {}
        for comp_type, store in self._stores.items():
            for eid, comp in store.items():
                if eid not in self._dead and eid >= 0:
                    entities.setdefault(eid, []).append(comp)
        return entities
