"""components.dev_log — Structured AI / system event log.

A ring-buffer resource that records timestamped actions taken by
NPCs, system transitions, combat events, and errors.  Read by the
DevTools scene to give the developer a live feed of what every NPC
is doing and why.

Usage (structured):
    log = world.res(DevLog)
    log.record(eid, "combat", "mode → chase", details={"dist": 5.2})

Usage (convenience — writes to DevLog AND prints to stdout):
    from components.dev_log import log_event
    log_event(world, eid, "combat", "mode → chase", name="Guard")

Each entry is a dict:
    {"t": float, "eid": int, "name": str, "cat": str,
     "msg": str, "details": dict | None}
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class DevLog:
    """Ring-buffer of AI / system events for the dev tools."""

    entries: list[dict] = field(default_factory=list)
    max_entries: int = 500
    _paused: bool = False

    # ── Filters (set by the DevTools UI) ─────────────────────────────
    # If non-empty, only entries whose ``cat`` is in the set are kept.
    cat_filter: set[str] = field(default_factory=set)
    # If non-empty, only entries whose ``eid`` is in the set are kept.
    eid_filter: set[int] = field(default_factory=set)

    def record(self, eid: int, cat: str, msg: str, *,
               name: str = "", t: float = 0.0,
               details: dict | None = None) -> None:
        if self._paused:
            return
        # Pre-filter — skip entries the UI isn't interested in
        if self.cat_filter and cat not in self.cat_filter:
            return
        if self.eid_filter and eid not in self.eid_filter:
            return
        entry = {
            "t": t,
            "eid": eid,
            "name": name,
            "cat": cat,
            "msg": msg,
            "details": details,
        }
        self.entries.append(entry)
        if len(self.entries) > self.max_entries:
            self.entries = self.entries[-self.max_entries:]

    def clear(self):
        self.entries.clear()

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False

    def recent(self, n: int = 50) -> list[dict]:
        """Return the *n* most recent entries (newest last)."""
        return self.entries[-n:]

    def for_eid(self, eid: int, n: int = 30) -> list[dict]:
        """Return last *n* entries for a specific entity."""
        return [e for e in self.entries if e["eid"] == eid][-n:]

    def for_cat(self, cat: str, n: int = 50) -> list[dict]:
        """Return last *n* entries in a category."""
        return [e for e in self.entries if e["cat"] == cat][-n:]


# ── Module-level convenience function ────────────────────────────────

def log_event(world: Any, eid: int, cat: str, msg: str, *,
              name: str = "", details: dict | None = None) -> None:
    """Write to DevLog (if it exists) and print to stdout.

    This is the preferred replacement for bare ``print()`` calls in
    systems.  The DevLog captures events for the debug scene's event
    log, while stdout preserves the console output developers are used
    to reading.

    Parameters
    ----------
    world : World
        The ECS world (used to look up the DevLog resource and clock).
    eid : int
        Entity ID (use -1 for system-level messages).
    cat : str
        Category tag (e.g. "combat", "lod", "sim", "econ", "crime").
    msg : str
        Human-readable message (what happened).
    name : str
        Entity display name (optional — for readability).
    details : dict | None
        Optional structured data for programmatic inspection.
    """
    from components import GameClock
    t = 0.0
    try:
        clock = world.res(GameClock)
        if clock:
            t = clock.time
    except Exception:
        pass

    log = world.res(DevLog) if hasattr(world, 'res') else None
    if log is not None:
        log.record(eid, cat, msg, name=name, t=t, details=details)

    # Also print (with category tag) for console visibility
    tag = cat.upper()
    print(f"[{tag}] {name}{': ' if name else ''}{msg}")
