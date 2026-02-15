"""systems/combat/state.py — Typed combat state dataclass.

Replaces the untyped ``brain.state["combat"]`` dict with a proper
dataclass.  Every key that was previously a magic string is now a
typed attribute with a sensible default.

Usage::

    from systems.combat.state import CombatState, get_combat_state

    cs = get_combat_state(brain)
    cs.mode = "chase"
    cs.p_eid = target_eid

``get_combat_state`` lazily creates the ``CombatState`` inside
``brain.state["combat"]`` on first access so existing code that
checks ``brain.state.get("combat")`` still works.

Melee sub-FSM keys (``melee_sub``, ``melee_circle_timer``, etc.)
are stored in a nested :class:`MeleeState` so the hierarchy is
explicit: ``cs.melee.sub``, ``cs.melee.circle_timer``, etc.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

from components.ai import Brain


# ── Melee sub-FSM state ─────────────────────────────────────────────

@dataclass
class MeleeState:
    """Sub-state for the melee attack FSM (approach/circle/feint/lunge/retreat)."""
    sub: str = "approach"
    circle_timer: float = 0.0
    circle_dir: int = 1
    feint_timer: float = 0.0
    feint_phase: str = "advance"
    retreat_timer: float = 0.0
    retreat_dir: int | None = None
    just_hit: bool = False


# ── Main combat state ───────────────────────────────────────────────

@dataclass
class CombatState:
    """Typed replacement for ``brain.state["combat"]`` dict.

    Every attribute that was previously a magic-string key is now a
    properly-typed field with a documented default.
    """

    # ── FSM mode ─────────────────────────────────────────────────────
    mode: str = "idle"
    """Current top-level mode: idle / chase / attack / flee / return / searching."""

    # ── Target tracking ──────────────────────────────────────────────
    p_eid: int | None = None
    """Entity id of the current target (player or enemy)."""

    p_pos: tuple[float, float] | None = None
    """Last-known (x, y) of the target."""

    # ── Origin / patrol anchor ───────────────────────────────────────
    origin: tuple[float, float] | None = None
    """Spawn position — entity returns here when combat ends."""

    # ── Timing / cooldowns ───────────────────────────────────────────
    attack_until: float = 0.0
    """Timestamp until which the entity stays in attack mode."""

    search_until: float = 0.0
    """Timestamp until which the entity searches the area."""

    _search_start: float = 0.0
    """When the current search began (for spiral calculations)."""

    search_source: tuple[float, float] | None = None
    """Location to search toward."""

    # ── Sensor stagger ───────────────────────────────────────────────
    _staggered: bool = False
    """Whether the first sensor tick has been offset."""

    # ── LOS / wall tracking ──────────────────────────────────────────
    _wall_blocked: bool = False
    """Target is behind a wall on the current frame."""

    _los_blocked: bool = False
    """A *friendly* entity is blocking line-of-sight."""

    _los_blocked_count: int = 0
    """Consecutive frames with LOS blocked by allies."""

    # ── Fire-line awareness ──────────────────────────────────────────
    _fire_lines: list = field(default_factory=list)
    """Cached list of ally fire-lines (from :func:`fireline.get_ally_fire_lines`)."""

    _chase_los_wp: tuple[float, float] | None = None
    """Waypoint to move toward to clear a blocked fire-line during chase."""

    _clear_fire_line: dict | None = None
    """Active fire-line clearing manoeuvre data."""

    # ── Tactical repositioning ───────────────────────────────────────
    _tac_repos: Any = None
    """Current tactical reposition target point (or None)."""

    _tac_repos_until: float = 0.0
    """Timestamp until which the tac-repos manoeuvre is valid."""

    _repos_target: Any = None
    """Extra data for the reposition target."""

    # ── Melee sub-FSM ────────────────────────────────────────────────
    melee: MeleeState = field(default_factory=MeleeState)
    """Nested state for the melee approach/circle/feint/lunge/retreat sub-FSM."""

    # ── Overflow for movement / steering keys ────────────────────────
    _extra: dict = field(default_factory=dict, repr=False)
    """Dict-compat overflow for keys that haven't been promoted to
    typed fields yet (strafe_dir, idle_timer, pathfinding state, etc.).
    These are accessed via the dict-compat methods below so that
    movement.py / steering.py continue to work unchanged.
    """

    # ── Melee key aliases ───────────────────────────────────────────
    # Maps old flat dict keys (``c["melee_sub"]``) to nested
    # ``MeleeState`` attribute names so legacy callers still work.
    _MELEE_ALIASES: dict[str, str] = field(
        init=False, repr=False,
        default_factory=lambda: {
            "melee_sub": "sub",
            "melee_circle_timer": "circle_timer",
            "melee_circle_dir": "circle_dir",
            "melee_feint_timer": "feint_timer",
            "melee_feint_phase": "feint_phase",
            "melee_retreat_timer": "retreat_timer",
            "melee_retreat_dir": "retreat_dir",
            "_melee_just_hit": "just_hit",
        }
    )

    # ── Dict-compat methods ──────────────────────────────────────────
    # Allow movement.py, steering.py, and tests to use state["key"]
    # syntax while typed fields use attribute access.

    def _resolve(self, key: str):
        """Return (obj, attr) for *key*, handling melee aliases."""
        melee_attr = self._MELEE_ALIASES.get(key)
        if melee_attr is not None:
            return self.melee, melee_attr
        if key != "_extra" and key != "_MELEE_ALIASES" and hasattr(type(self), key):
            return self, key
        return None, key  # overflow

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
            return getattr(obj, attr)
        return self._extra.pop(key, *args)

    def keys(self):
        """All visible keys — typed fields + melee aliases + overflow."""
        import dataclasses as _dc
        ks = [f.name for f in _dc.fields(self)
              if f.name not in ("_extra", "_MELEE_ALIASES", "melee")]
        ks.extend(self._MELEE_ALIASES)
        ks.extend(self._extra)
        return ks

    def items(self):
        """Iterate (key, value) for all visible keys."""
        import dataclasses as _dc
        for f in _dc.fields(self):
            if f.name not in ("_extra", "_MELEE_ALIASES", "melee"):
                yield f.name, getattr(self, f.name)
        for alias, melee_attr in self._MELEE_ALIASES.items():
            yield alias, getattr(self.melee, melee_attr)
        yield from self._extra.items()


# ── Accessor ─────────────────────────────────────────────────────────

def get_combat_state(brain: Brain) -> CombatState:
    """Return (and lazily create) the :class:`CombatState` for *brain*.

    If a plain dict exists (e.g. from LOD demotion), its values are
    migrated into a fresh CombatState.
    """
    cs = brain.state.get("combat")
    if isinstance(cs, CombatState):
        return cs
    new_cs = CombatState()
    if isinstance(cs, dict):
        for k, v in cs.items():
            new_cs[k] = v
    brain.state["combat"] = new_cs
    return new_cs
