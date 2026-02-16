"""core/ecs.py — Typed Entity-Component-System.

Entities are ints.  Components must subclass ``Component``.
Resources (singletons) live in a **separate** ``Resources`` store —
not mixed with entity data.

    w = World()
    e = w.spawn()
    w.add(e, Position(x=5.0, y=3.0))
    w.add(e, Health(current=100))

    for eid, pos, hp in w.query(Position, Health):
        pos.x += 1
        hp.current -= 5

    cam = w.resources.get(Camera)

Design principles (Rust-inspired):
  - Components must be Component subclasses — ``add()`` rejects anything else.
  - Resources are typed singletons, separate from entity storage.
  - Zone index is updated automatically when a Position is added.
  - ``get()`` returns ``T | None`` with proper type narrowing.
  - ``query()`` has overloads for 1–3 component types for type safety.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import (
    Any, ClassVar, Iterator, TypeVar,
    overload,
)


# ═══════════════════════════════════════════════════════════════════
#  Component base
# ═══════════════════════════════════════════════════════════════════

@dataclass
class Component:
    """Marker base for all ECS components.

    Subclass and set ``_persist = True`` for components whose state
    should survive save/load cycles.  Everything else is treated as
    static (rebuilt from templates on zone load).
    """
    _persist: ClassVar[bool] = False


# TypeVars bound to Component for typed queries
T1 = TypeVar("T1", bound=Component)
T2 = TypeVar("T2", bound=Component)
T3 = TypeVar("T3", bound=Component)
R = TypeVar("R")


# ═══════════════════════════════════════════════════════════════════
#  Resources — typed singletons, NOT tied to entities
# ═══════════════════════════════════════════════════════════════════

class Resources:
    """Separate typed store for world-level singletons.

    Unlike the old design, resources do NOT share storage with entity
    components and do NOT require a magic entity ID.
    """

    def __init__(self) -> None:
        self._data: dict[type, Any] = {}

    def set(self, resource: Any) -> None:
        """Register or replace a resource by its type."""
        self._data[type(resource)] = resource

    def get(self, res_type: type[R]) -> R:
        """Retrieve a resource.  Raises ``KeyError`` if missing."""
        val = self._data.get(res_type)
        if val is None:
            raise KeyError(f"Resource {res_type.__name__} not set")
        return val  # type: ignore[return-value]

    def try_get(self, res_type: type[R]) -> R | None:
        """Retrieve a resource, returning ``None`` if unset."""
        return self._data.get(res_type)  # type: ignore[return-value]

    def has(self, res_type: type) -> bool:
        """Check if a resource type has been registered."""
        return res_type in self._data


# ═══════════════════════════════════════════════════════════════════
#  World
# ═══════════════════════════════════════════════════════════════════

class World:
    """The ECS world: entity IDs, typed component stores, zone index."""

    def __init__(self) -> None:
        self._next_id: int = 0
        self._stores: dict[type[Component], dict[int, Component]] = {}
        self._dead: set[int] = set()
        self._zone_index: dict[str, set[int]] = {}
        self.resources = Resources()

    # ── Zone index ────────────────────────────────────────────────

    def _zone_update(self, eid: int, zone: str) -> None:
        """Move *eid* to *zone* in the internal index."""
        for eids in self._zone_index.values():
            eids.discard(eid)
        self._zone_index.setdefault(zone, set()).add(eid)

    def set_zone(self, eid: int, zone: str) -> None:
        """Move *eid* to *zone*, updating both the index and Position."""
        self._zone_update(eid, zone)
        # Keep Position.zone in sync (duck-typed to avoid circular import)
        for store in self._stores.values():
            comp = store.get(eid)
            if comp is not None and hasattr(comp, "zone"):
                comp.zone = zone  # type: ignore[attr-defined]
                break

    def zone_entities(self, zone: str) -> set[int]:
        """Return living entity IDs in *zone* (O(1) lookup)."""
        return self._zone_index.get(zone, set()) - self._dead

    # ── Entities ──────────────────────────────────────────────────

    def spawn(self) -> int:
        """Create a new entity and return its ID."""
        self._next_id += 1
        return self._next_id

    def kill(self, eid: int) -> None:
        """Mark an entity for deferred removal."""
        self._dead.add(eid)

    def alive(self, eid: int) -> bool:
        """Check if an entity is still alive."""
        return eid not in self._dead

    def purge(self) -> None:
        """Remove dead entities from all stores.  Call once per frame."""
        for store in self._stores.values():
            for eid in self._dead:
                store.pop(eid, None)
        for eids in self._zone_index.values():
            eids -= self._dead
        self._dead.clear()

    # ── Components (typed) ────────────────────────────────────────

    def add(self, eid: int, comp: Component) -> None:
        """Attach a component to an entity.

        Raises ``TypeError`` if *comp* is not a ``Component`` subclass.
        Automatically updates the zone index when a component with a
        ``zone`` attribute is added (i.e. Position).
        """
        if not isinstance(comp, Component):
            raise TypeError(
                f"Expected a Component subclass, got {type(comp).__name__}"
            )
        t = type(comp)
        self._stores.setdefault(t, {})[eid] = comp

        # Auto-index: any component with a 'zone' attribute
        zone = getattr(comp, "zone", None)
        if isinstance(zone, str) and zone:
            self._zone_update(eid, zone)

    @overload
    def get(self, eid: int, comp_type: type[T1]) -> T1 | None: ...
    def get(self, eid: int, comp_type: type) -> Any:
        """Get a component by type, or ``None`` if the entity lacks it."""
        store = self._stores.get(comp_type)
        if store is None:
            return None
        return store.get(eid)

    def has(self, eid: int, comp_type: type[Component]) -> bool:
        """Check if *eid* has a component of *comp_type*."""
        return eid in self._stores.get(comp_type, {})

    def remove(self, eid: int, comp_type: type[Component]) -> None:
        """Detach a component from an entity."""
        store = self._stores.get(comp_type)
        if store and eid in store:
            del store[eid]

    # ── Queries (with typed overloads) ────────────────────────────

    @overload
    def query(self, t1: type[T1], /) -> Iterator[tuple[int, T1]]: ...
    @overload
    def query(self, t1: type[T1], t2: type[T2], /) -> Iterator[tuple[int, T1, T2]]: ...
    @overload
    def query(self, t1: type[T1], t2: type[T2], t3: type[T3], /) -> Iterator[tuple[int, T1, T2, T3]]: ...
    def query(self, *types: type[Component]) -> Iterator[tuple]:
        """Yield ``(eid, comp1, comp2, ...)`` for entities with ALL types."""
        if not types:
            return
        # Iterate over the smallest bucket for efficiency
        buckets = [(t, self._stores.get(t, {})) for t in types]
        buckets.sort(key=lambda b: len(b[1]))
        smallest = buckets[0][1]
        for eid in smallest:
            if eid in self._dead:
                continue
            if all(eid in b for _, b in buckets):
                yield (eid, *(self._stores[t][eid] for t in types))

    @overload
    def query_one(self, t1: type[T1], /) -> tuple[int, T1] | None: ...
    @overload
    def query_one(self, t1: type[T1], t2: type[T2], /) -> tuple[int, T1, T2] | None: ...
    @overload
    def query_one(self, t1: type[T1], t2: type[T2], t3: type[T3], /) -> tuple[int, T1, T2, T3] | None: ...
    def query_one(self, *types: type[Component]) -> tuple | None:
        """Return the first match or ``None``."""
        for result in self.query(*types):
            return result
        return None

    def query_zone(self, zone: str, *types: type[Component]) -> Iterator[tuple]:
        """Like ``query()`` but only examines entities in *zone*."""
        eids = self.zone_entities(zone)
        if not eids or not types:
            return
        stores = [(t, self._stores.get(t, {})) for t in types]
        for eid in eids:
            if all(eid in s for _, s in stores):
                yield (eid, *(s[eid] for _, s in stores))

    def all_of(self, comp_type: type[T1]) -> Iterator[tuple[int, T1]]:
        """Yield ``(eid, component)`` for every living entity with this type."""
        for eid, comp in self._stores.get(comp_type, {}).items():
            if eid not in self._dead:
                yield eid, comp  # type: ignore[misc]

    def count(self, comp_type: type[Component]) -> int:
        """Count living entities with *comp_type*."""
        return sum(1 for _ in self.all_of(comp_type))

    # ── Debug ─────────────────────────────────────────────────────

    def debug_dump(self) -> dict[int, list[Component]]:
        """Return ``{eid: [components...]}`` for every living entity."""
        entities: dict[int, list[Component]] = {}
        for store in self._stores.values():
            for eid, comp in store.items():
                if eid not in self._dead:
                    entities.setdefault(eid, []).append(comp)
        return entities
