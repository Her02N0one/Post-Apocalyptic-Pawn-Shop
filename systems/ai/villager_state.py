"""systems/ai/villager_state.py — Typed villager state dataclass.

Replaces the untyped ``brain.state["villager"]`` dict with a proper
dataclass.  Every key that was previously a magic string is now a
typed attribute with a sensible default.

Usage::

    from systems.ai.villager_state import VillagerState, get_villager_state

    vs = get_villager_state(brain)
    vs.mode = "travel"
    vs.travel_target = (10.0, 5.0)

``get_villager_state`` lazily creates the ``VillagerState`` inside
``brain.state["villager"]`` on first access.

Wander / pathfinding keys (``_vw_path``, ``_path``, ``timer``, ``dir``,
etc.) are stored in an overflow ``_extra`` dict accessed through the
dict-compat bridge so that ``wander_step()`` and
``move_toward_pathfind()`` continue to work unchanged.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

from components.ai import Brain


@dataclass
class VillagerState:
    """Typed replacement for ``brain.state["villager"]`` dict."""

    # ── FSM mode ─────────────────────────────────────────────────────
    mode: str = "idle"
    """Current mode: idle / travel / eat / forage / return /
    schedule_walk / schedule_idle."""

    # ── Spatial ──────────────────────────────────────────────────────
    origin: tuple[float, float] | None = None
    """Home position — entity returns here when idle."""

    home_subzone: str = ""
    """Subzone the villager considers home."""

    # ── Travel ───────────────────────────────────────────────────────
    travel_target: tuple[float, float] | None = None
    """Current travel destination (x, y), or None."""

    # ── Eating / foraging ────────────────────────────────────────────
    eat_until: float = 0.0
    """Timestamp until which the entity stays in 'eat' mode."""

    forage_until: float = 0.0
    """Timestamp until which the entity stays in 'forage' mode."""

    # ── Schedule ─────────────────────────────────────────────────────
    period: str = ""
    """Current time-of-day period: morning / midday / afternoon / evening."""

    schedule_target: tuple[float, float] | None = None
    """Target position for the current scheduled activity."""

    socializing: bool = False
    """Whether the villager is currently socializing."""

    greet_cooldown: float = 0.0
    """Game-time before which the villager won't greet again."""

    # ── Stuck detection ──────────────────────────────────────────────
    stuck_check_t: float = 0.0
    """Next game-time to check stuck status."""

    stuck_check_pos: tuple[float, float] | None = None
    """Last position when stuck check was started."""

    stuck_strikes: int = 0
    """Consecutive stuck checks that failed (position didn't change)."""

    # ── Overflow for wander / pathfinding keys ───────────────────────
    _extra: dict = field(default_factory=dict, repr=False)
    """Dict-compat overflow for wander/pathfinding keys (_vw_path,
    _path, _path_t, _path_tgt, timer, dir, etc.)."""

    # ── Dict-compat methods ──────────────────────────────────────────

    def _resolve(self, key: str):
        """Return (obj, attr) for *key*."""
        if key != "_extra" and hasattr(type(self), key):
            return self, key
        return None, key

    def __getitem__(self, key: str):
        obj, attr = self._resolve(key)
        if obj is not None:
            return getattr(obj, attr)
        return self._extra[key]

    def __setitem__(self, key: str, value):
        obj, attr = self._resolve(key)
        if obj is not None:
            setattr(obj, attr, value)
        else:
            self._extra[key] = value

    def __contains__(self, key: str) -> bool:
        obj, _ = self._resolve(key)
        if obj is not None:
            return True
        return key in self._extra

    def get(self, key: str, default=None):
        obj, attr = self._resolve(key)
        if obj is not None:
            return getattr(obj, attr)
        return self._extra.get(key, default)

    def setdefault(self, key: str, default=None):
        obj, attr = self._resolve(key)
        if obj is not None:
            return getattr(obj, attr)
        return self._extra.setdefault(key, default)

    def pop(self, key: str, *args):
        obj, attr = self._resolve(key)
        if obj is not None:
            val = getattr(obj, attr)
            return val
        return self._extra.pop(key, *args)

    def keys(self):
        """All visible keys."""
        import dataclasses as _dc
        ks = [f.name for f in _dc.fields(self) if f.name != "_extra"]
        ks.extend(self._extra)
        return ks

    def items(self):
        """Iterate (key, value) for all visible keys."""
        import dataclasses as _dc
        for f in _dc.fields(self):
            if f.name != "_extra":
                yield f.name, getattr(self, f.name)
        yield from self._extra.items()

    def update(self, d: dict):
        """Merge a mapping into this state."""
        for k, v in d.items():
            self[k] = v


# ── Accessor ─────────────────────────────────────────────────────────

def get_villager_state(brain: Brain) -> VillagerState:
    """Return (and lazily create) the :class:`VillagerState` for *brain*.

    If a plain dict exists (e.g. from LOD demotion which stores a
    small preserved dict), the values are migrated into a fresh
    VillagerState.
    """
    vs = brain.state.get("villager")
    if isinstance(vs, VillagerState):
        return vs
    new_vs = VillagerState()
    if isinstance(vs, dict):
        for k, v in vs.items():
            new_vs[k] = v
    brain.state["villager"] = new_vs
    return new_vs
