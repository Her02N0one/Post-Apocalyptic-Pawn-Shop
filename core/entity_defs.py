"""core/entity_defs.py — Entity type definitions (rendering + editor metadata).

Loads ``data/entity_defs.toml`` and provides :class:`EntityDef` plus
lookup helpers.  Gameplay / ECS data is NOT stored here — only the
visual and placement properties the editor and renderer need.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]


_DEFS_PATH = Path(__file__).resolve().parent.parent / "data" / "entity_defs.toml"


@dataclass(frozen=True, slots=True)
class EntityDef:
    """Immutable descriptor for one placeable entity type."""

    id: str
    display_name: str
    category: str
    color: tuple[int, int, int]
    scale: float
    directional: bool
    states: tuple[str, ...]


# ── Module-level cache ────────────────────────────────────────────

_REGISTRY: dict[str, EntityDef] = {}
_PALETTE: list[str] = []           # ordered list of type IDs


def _load() -> None:
    """Load (or reload) entity definitions from disk."""
    _REGISTRY.clear()
    _PALETTE.clear()
    if not _DEFS_PATH.exists():
        return
    with open(_DEFS_PATH, "rb") as f:
        data = tomllib.load(f)
    for key, raw in data.items():
        color_raw = raw.get("color", [200, 200, 200])
        color = (int(color_raw[0]), int(color_raw[1]), int(color_raw[2]))
        edef = EntityDef(
            id=key,
            display_name=raw.get("display_name", key),
            category=raw.get("category", "misc"),
            color=color,
            scale=float(raw.get("scale", 1.0)),
            directional=bool(raw.get("directional", False)),
            states=tuple(raw.get("states", ["default"])),
        )
        _REGISTRY[key] = edef
    # Sort palette: category then display_name
    _PALETTE.extend(
        sorted(_REGISTRY, key=lambda k: (_REGISTRY[k].category,
                                         _REGISTRY[k].display_name))
    )


def entity_registry() -> dict[str, EntityDef]:
    """Return the full ``{id: EntityDef}`` mapping.  Loads on first call."""
    if not _REGISTRY:
        _load()
    return _REGISTRY


def entity_palette() -> list[str]:
    """Ordered list of entity type IDs for the editor palette."""
    if not _PALETTE:
        _load()
    return _PALETTE


def get_entity_def(type_id: str) -> EntityDef | None:
    """Look up a single entity def by ID."""
    return entity_registry().get(type_id)


# ── Angle helpers ─────────────────────────────────────────────────

def snap_angle_8dir(angle: float) -> float:
    """Snap *angle* (radians) to the nearest 45° increment.

    Returns a value in ``[0, 2π)``.
    """
    step = math.pi / 4.0
    snapped = round(angle / step) * step
    return snapped % (2.0 * math.pi)


def angle_to_label(angle: float) -> str:
    """Return a human-readable compass label for an angle (radians, 0 = east).

    Returns one of: E, NE, N, NW, W, SW, S, SE.
    """
    idx = round(angle / (math.pi / 4.0)) % 8
    return ("E", "NE", "N", "NW", "W", "SW", "S", "SE")[idx]
