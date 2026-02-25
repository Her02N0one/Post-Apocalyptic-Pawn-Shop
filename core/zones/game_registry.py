"""core.zones.game_registry — Centralised string ↔ uint16 asset registry.

The binary zone format (``.zone``) stores only integer IDs for tiles,
textures, entity prefabs, and other named assets.  This registry
provides the canonical two-way mapping between human-readable string
keys (like ``"brick_wall"``) and compact ``uint16`` integers.

Design goals
------------
* **Stable IDs** — once a key is assigned an integer, that mapping is
  persistent across sessions.  Deleting a key retires its integer
  (it is never reassigned).
* **Namespace separation** — tiles, textures, prefabs, sounds each
  occupy independent ID spaces so their uint16 values never collide.
* **O(1) both directions** — dict lookups for ``str → int`` and
  ``int → str``.
* **64 K ceiling** — uint16 allows up to 65 535 entries per namespace.
  More than enough for a tile-based game.
* **Drop-in replacement** — the existing ``tile_str_to_int`` /
  ``tile_int_to_str`` in ``core.tiles.registry`` can be backed by
  this registry without changing call-sites.

Persistence
-----------
The registry can be serialised as a simple JSON mapping file that is
version-controlled alongside the zone data.  The ``save`` / ``load``
helpers round-trip through ``{namespace: {key: int, ...}, ...}``.

Usage
-----
::

    from core.game_registry import GameRegistry

    reg = GameRegistry()

    # Register assets (at bootstrap / TOML load time)
    reg.register("tile", "brick_wall")
    reg.register("tile", "grass")

    # Lookup
    assert reg.to_int("tile", "brick_wall") == 0
    assert reg.to_str("tile", 0) == "brick_wall"

    # Bulk-register an iterable
    reg.register_many("tile", ["dirt", "stone", "water"])

    # Namespace accessor (avoids repeating the namespace string)
    tiles = reg.namespace("tile")
    tiles.to_int("dirt")   # fast path
    tiles.to_str(2)

    # Persistence
    reg.save("assets/registry.json")
    reg.load("assets/registry.json")
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator


# ── Maximum ID value (uint16) ────────────────────────────────────
_MAX_ID = 0xFFFF  # 65 535


# ═══════════════════════════════════════════════════════════════════
#  NamespaceView — lightweight accessor for a single namespace
# ═══════════════════════════════════════════════════════════════════

class NamespaceView:
    """Read-through view into one namespace of a :class:`GameRegistry`.

    Avoids repeating the namespace string on every call::

        tiles = registry.namespace("tile")
        tex_id = tiles.to_int("brick_wall")
        name   = tiles.to_str(tex_id)
    """

    __slots__ = ("_reg", "_ns")

    def __init__(self, registry: GameRegistry, namespace: str) -> None:
        self._reg = registry
        self._ns = namespace

    # ── Lookups ───────────────────────────────────────────────────

    def to_int(self, key: str) -> int:
        """Return the uint16 ID for *key*, or ``-1`` if unregistered."""
        return self._reg.to_int(self._ns, key)

    def to_str(self, uid: int) -> str:
        """Return the string key for *uid*, or ``""`` if unregistered."""
        return self._reg.to_str(self._ns, uid)

    # ── Registration ──────────────────────────────────────────────

    def register(self, key: str) -> int:
        """Register *key* and return its assigned ID."""
        return self._reg.register(self._ns, key)

    def register_many(self, keys: list[str] | tuple[str, ...]) -> None:
        """Register multiple keys in insertion order."""
        self._reg.register_many(self._ns, keys)

    # ── Queries ───────────────────────────────────────────────────

    def __contains__(self, key: str) -> bool:
        return self._reg.contains(self._ns, key)

    def __len__(self) -> int:
        return self._reg.namespace_size(self._ns)

    def keys(self) -> Iterator[str]:
        """Iterate registered string keys in ID order."""
        return self._reg.namespace_keys(self._ns)

    def __repr__(self) -> str:
        return f"NamespaceView({self._ns!r}, len={len(self)})"


# ═══════════════════════════════════════════════════════════════════
#  _NamespaceData — internal storage for one namespace
# ═══════════════════════════════════════════════════════════════════

@dataclass
class _NamespaceData:
    """Mutable storage for a single namespace's mappings."""
    str_to_int: dict[str, int] = field(default_factory=dict)
    int_to_str: dict[int, str] = field(default_factory=dict)
    next_id: int = 0


# ═══════════════════════════════════════════════════════════════════
#  GameRegistry
# ═══════════════════════════════════════════════════════════════════

class GameRegistry:
    """Centralised two-way ``str ↔ uint16`` registry for all named assets.

    Each *namespace* (``"tile"``, ``"texture"``, ``"prefab"``, …) is an
    independent ID space.  IDs are assigned sequentially starting from 0
    and are never reused — deleting a key simply retires its integer.

    Parameters
    ----------
    namespaces : list[str] | None
        Pre-create these namespaces at construction time.  Additional
        namespaces are created on-the-fly by :meth:`register`.
    """

    def __init__(self, namespaces: list[str] | None = None) -> None:
        self._ns: dict[str, _NamespaceData] = {}
        for ns in (namespaces or []):
            self._ns[ns] = _NamespaceData()

    # ── Internal helpers ──────────────────────────────────────────

    def _ensure_ns(self, namespace: str) -> _NamespaceData:
        """Return (or create) the data store for *namespace*."""
        ns = self._ns.get(namespace)
        if ns is None:
            ns = _NamespaceData()
            self._ns[namespace] = ns
        return ns

    # ── Registration ──────────────────────────────────────────────

    def register(self, namespace: str, key: str) -> int:
        """Assign a uint16 ID to *key* in *namespace*.

        If *key* is already registered, returns the existing ID.
        Raises :class:`OverflowError` if the namespace is full (65 535).

        Returns
        -------
        int
            The assigned uint16 ID (0 – 65 535).
        """
        ns = self._ensure_ns(namespace)
        existing = ns.str_to_int.get(key)
        if existing is not None:
            return existing

        uid = ns.next_id
        if uid > _MAX_ID:
            raise OverflowError(
                f"Namespace {namespace!r} exhausted: cannot assign ID "
                f"beyond {_MAX_ID} (tried to register {key!r})"
            )
        ns.str_to_int[key] = uid
        ns.int_to_str[uid] = key
        ns.next_id = uid + 1
        return uid

    def register_many(
        self,
        namespace: str,
        keys: list[str] | tuple[str, ...],
    ) -> None:
        """Register multiple keys in order, skipping duplicates."""
        for key in keys:
            self.register(namespace, key)

    # ── Lookups ───────────────────────────────────────────────────

    def to_int(self, namespace: str, key: str) -> int:
        """Return the uint16 ID for *key*, or ``-1`` if not found."""
        ns = self._ns.get(namespace)
        if ns is None:
            return -1
        return ns.str_to_int.get(key, -1)

    def to_str(self, namespace: str, uid: int) -> str:
        """Return the string key for *uid*, or ``""`` if not found."""
        ns = self._ns.get(namespace)
        if ns is None:
            return ""
        return ns.int_to_str.get(uid, "")

    def contains(self, namespace: str, key: str) -> bool:
        """Return ``True`` if *key* is registered in *namespace*."""
        ns = self._ns.get(namespace)
        return ns is not None and key in ns.str_to_int

    # ── Namespace queries ─────────────────────────────────────────

    def namespace(self, name: str) -> NamespaceView:
        """Return a :class:`NamespaceView` bound to *name*."""
        self._ensure_ns(name)
        return NamespaceView(self, name)

    def namespace_size(self, name: str) -> int:
        """Return the number of registered keys in *name*."""
        ns = self._ns.get(name)
        return len(ns.str_to_int) if ns else 0

    def namespace_keys(self, name: str) -> Iterator[str]:
        """Iterate registered string keys in *name*, ordered by ID."""
        ns = self._ns.get(name)
        if ns is None:
            return iter(())
        return (ns.int_to_str[i] for i in range(ns.next_id)
                if i in ns.int_to_str)

    def namespaces(self) -> list[str]:
        """Return the names of all namespaces."""
        return list(self._ns.keys())

    # ── Bulk export ───────────────────────────────────────────────

    def dump(self) -> dict[str, dict[str, int]]:
        """Export the full registry as a nested dict.

        Structure::

            {
                "tile":    {"brick_wall": 0, "grass": 1, ...},
                "texture": {"brick_wall": 0, ...},
                ...
            }
        """
        out: dict[str, dict[str, int]] = {}
        for ns_name, ns_data in self._ns.items():
            out[ns_name] = dict(ns_data.str_to_int)
        return out

    def load_from_dict(self, data: dict[str, dict[str, int]]) -> None:
        """Import a registry from a nested dict (as produced by :meth:`dump`).

        Merges into the current state — existing mappings are preserved.
        Any new keys or namespaces are added; conflicting IDs in the
        input override existing ones.
        """
        for ns_name, mappings in data.items():
            ns = self._ensure_ns(ns_name)
            for key, uid in mappings.items():
                if not (0 <= uid <= _MAX_ID):
                    continue
                ns.str_to_int[key] = uid
                ns.int_to_str[uid] = key
                if uid >= ns.next_id:
                    ns.next_id = uid + 1

    # ── File I/O ──────────────────────────────────────────────────

    def save(self, path: str | Path) -> None:
        """Serialise the registry to a JSON file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.dump(), f, indent=2, sort_keys=True)

    def load(self, path: str | Path) -> None:
        """Load (merge) a previously saved registry from JSON."""
        path = Path(path)
        if not path.exists():
            return
        with open(path) as f:
            data = json.load(f)
        self.load_from_dict(data)

    # ── Dunder ────────────────────────────────────────────────────

    def __repr__(self) -> str:
        parts = ", ".join(
            f"{ns}={len(d.str_to_int)}"
            for ns, d in self._ns.items()
        )
        return f"GameRegistry({parts})"
