"""components.simulation — World simulation components.

New components for the off-screen persistent simulation:
  SubzonePos   — abstract location for low-LOD entities
  TravelPlan   — current path through the subzone graph
  Home         — entity's home subzone
  Stockpile    — shared resource pool for settlements
  WorldMemory  — structured observation log with timestamps and TTL
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


# ── Abstract positioning ─────────────────────────────────────────────

@dataclass
class SubzonePos:
    """Abstract location for off-screen (low-LOD) entities.

    Replaces Position when an entity is demoted.  An entity has
    Position OR SubzonePos, never both.
    """
    zone: str = ""         # parent zone name
    subzone: str = ""      # subzone node ID within that zone


# ── Travel ───────────────────────────────────────────────────────────

@dataclass
class TravelPlan:
    """Current path through the subzone graph.

    ``path`` is an ordered list of subzone IDs from current location
    to destination.  ``current_index`` points to the next node to
    reach (0 = first hop, etc.).  Attached when an entity decides
    to go somewhere, removed when they arrive.
    """
    path: list[str] = field(default_factory=list)
    current_index: int = 0
    destination: str = ""

    @property
    def next_node(self) -> str | None:
        if self.current_index < len(self.path):
            return self.path[self.current_index]
        return None

    @property
    def complete(self) -> bool:
        return self.current_index >= len(self.path)

    def advance(self) -> str | None:
        """Move to the next node. Returns that node's ID or None if done."""
        if self.current_index < len(self.path):
            node = self.path[self.current_index]
            self.current_index += 1
            return node
        return None


# ── Home ─────────────────────────────────────────────────────────────

@dataclass
class Home:
    """Where this entity considers 'home' — used by decision cycle."""
    zone: str = ""
    subzone: str = ""


# ── Stockpile ────────────────────────────────────────────────────────

@dataclass
class Stockpile:
    """Shared resource pool for a settlement or camp.

    Attached to a settlement entity (not individual NPCs).
    NPCs reference their settlement's Stockpile for communal eating,
    supply checks, and trade decisions.
    """
    items: dict[str, int] = field(default_factory=dict)
    capacity: float = 200.0

    def add(self, item_id: str, count: int = 1) -> int:
        """Add items. Returns actual amount added."""
        self.items[item_id] = self.items.get(item_id, 0) + count
        return count

    def remove(self, item_id: str, count: int = 1) -> int:
        """Remove items. Returns actual amount removed."""
        have = self.items.get(item_id, 0)
        taken = min(have, count)
        if taken > 0:
            self.items[item_id] = have - taken
            if self.items[item_id] <= 0:
                del self.items[item_id]
        return taken

    def has(self, item_id: str, count: int = 1) -> bool:
        return self.items.get(item_id, 0) >= count

    def total_count(self) -> int:
        return sum(self.items.values())


# ── Structured world memory ──────────────────────────────────────────

@dataclass
class MemoryEntry:
    """A single observation recorded by an entity.

    ``key``       — composite identifier, e.g. "location:pharmacy"
    ``data``      — flexible payload dict (what was observed)
    ``timestamp`` — game-time when observed
    ``ttl``       — seconds before this memory becomes 'stale'
    """
    key: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = 0.0
    ttl: float = 600.0       # 10 game-minutes default

    def is_stale(self, current_time: float) -> bool:
        return current_time - self.timestamp > self.ttl


@dataclass
class WorldMemory:
    """Per-entity knowledge of the world beyond immediate surroundings.

    Structured observation log with typed keys and TTL-based staleness.
    Coexists with the existing ``Memory`` component (which is used by
    the high-LOD goal system).
    """
    entries: dict[str, MemoryEntry] = field(default_factory=dict)

    def observe(self, key: str, data: dict[str, Any],
                game_time: float, ttl: float = 600.0) -> None:
        """Record or update an observation."""
        self.entries[key] = MemoryEntry(
            key=key, data=data, timestamp=game_time, ttl=ttl,
        )

    def recall(self, key: str) -> MemoryEntry | None:
        """Get a memory entry by key, or None."""
        return self.entries.get(key)

    def recall_fresh(self, key: str, current_time: float) -> MemoryEntry | None:
        """Get a memory entry only if it's not stale."""
        entry = self.entries.get(key)
        if entry and not entry.is_stale(current_time):
            return entry
        return None

    def query_prefix(self, prefix: str,
                     current_time: float | None = None,
                     stale_ok: bool = True) -> list[MemoryEntry]:
        """Return all entries whose key starts with ``prefix``.

        If ``stale_ok`` is False, filters out stale entries.
        """
        results = []
        for key, entry in self.entries.items():
            if not key.startswith(prefix):
                continue
            if not stale_ok and current_time is not None and entry.is_stale(current_time):
                continue
            results.append(entry)
        return results

    def forget(self, key: str) -> None:
        self.entries.pop(key, None)

    def purge_stale(self, current_time: float) -> int:
        """Remove all stale entries. Returns count removed."""
        stale = [k for k, e in self.entries.items() if e.is_stale(current_time)]
        for k in stale:
            del self.entries[k]
        return len(stale)
