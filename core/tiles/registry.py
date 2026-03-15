"""core/tiles/registry.py — Module-level tile registry and LUT builders.

Contains all shared mutable state (TILE_REGISTRY, TILE_COLORS, etc.)
and the compact-int mapping used by the C raycaster extension.
"""

from __future__ import annotations

import os as _os
from collections import OrderedDict

from core.paths import (
    TILE_TEX_DIR as _TILE_TEX_DIR_P,
    TILES_TOML_DIR as _TILES_TOML_DIR_P,
)
from core.tiles.types import TileType, TF, TileDef

# ── Paths (string versions) ─────────────────────────────────────

TILE_TEX_DIR = str(_TILE_TEX_DIR_P)
TILES_TOML_DIR = str(_TILES_TOML_DIR_P)

# ── Category constants ───────────────────────────────────────────

TC_TERRAIN   = "Terrain"
TC_FLOORS    = "Floors"
TC_WALLS     = "Walls"
TC_OPENINGS  = "Openings"
TC_BARRIERS  = "Barriers"
TC_PLATFORMS = "Platforms"
TC_CUSTOM    = "Custom"

TILE_CATEGORIES: list[str] = [
    TC_TERRAIN, TC_FLOORS, TC_WALLS, TC_OPENINGS,
    TC_BARRIERS, TC_PLATFORMS, TC_CUSTOM,
]

# ── Registry (keyed by text ID) ─────────────────────────────────

TILE_REGISTRY: dict[str, TileDef] = {}
_FALLBACK = TileDef("void", "Unknown", (120, 120, 120),
                     TileType.WALL, TF.SOLID | TF.WALL)


def tile_def(tile_id: str) -> TileDef:
    """Look up a tile definition, returning a safe fallback for unknowns."""
    return TILE_REGISTRY.get(tile_id, _FALLBACK)


# ── Derived ID sets ──────────────────────────────────────────────

SOLID_IDS: frozenset[str] = frozenset()
WALL_IDS: frozenset[str] = frozenset()
HALF_WALL_IDS: frozenset[str] = frozenset()
PLATFORM_IDS: frozenset[str] = frozenset()
DOOR_IDS: frozenset[str] = frozenset()

TILE_COLORS: dict[str, tuple[int, int, int]] = {}
TILE_NAMES: dict[str, str] = {}

# ── Compact int mapping (for C extension / numpy) ───────────────

_INT_MAP: dict[str, int] = {}
_INT_REV: dict[int, str] = {}


def _rebuild_int_map() -> None:
    _INT_MAP.clear()
    _INT_REV.clear()
    for i, key in enumerate(sorted(TILE_REGISTRY.keys())):
        _INT_MAP[key] = i
        _INT_REV[i] = key


# Extra texture keys (entity face textures, etc.) appended after tiles.
_EXTRA_KEYS: list[str] = []

# Stable atlas index mapping — once a key is assigned an index, it keeps
# that index forever (even if other keys are added or removed).  This
# prevents adding a new entity type from silently invalidating cached
# atlas indices in saved data or particle systems.
_STABLE_MAP: dict[str, int] = {}
_STABLE_MAP_PATH: "Path | None" = None


def _init_stable_map() -> None:
    """Load the persistent key→index map (or create it)."""
    global _STABLE_MAP_PATH
    from pathlib import Path
    _STABLE_MAP_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "_atlas_index_map.json"
    if _STABLE_MAP_PATH.exists():
        import json
        try:
            with open(_STABLE_MAP_PATH) as f:
                raw = json.load(f)
            _STABLE_MAP.update({k: int(v) for k, v in raw.items()})
        except Exception:
            pass  # corrupt or missing — will rebuild


def _save_stable_map() -> None:
    """Persist the stable key→index map to disk."""
    if _STABLE_MAP_PATH is None:
        return
    import json
    try:
        _STABLE_MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_STABLE_MAP_PATH, "w") as f:
            json.dump(_STABLE_MAP, f, indent=1, sort_keys=True)
    except OSError:
        pass  # non-critical — next run will reassign


def register_extra_texture_keys(keys: list[str]) -> None:
    """Register additional texture keys (e.g. entity face textures).

    These are appended after all tile keys so ``tile_str_to_int``
    returns valid indices for them.  The atlas builder is responsible
    for loading pixel data at these indices.

    Indices are **stable** — once assigned, a key keeps its index
    across restarts (persisted in ``data/_atlas_index_map.json``).
    New keys get the next available index.  This prevents adding a
    new entity type from silently shifting every subsequent texture.

    Safe to call multiple times — only keys not already registered
    are added.  Call *after* ``rebuild_derived()`` / ``_rebuild_int_map()``.
    """
    if not _STABLE_MAP:
        _init_stable_map()

    next_id = max(_INT_REV) + 1 if _INT_REV else 0
    # Also account for stable map indices that might exceed _INT_REV
    if _STABLE_MAP:
        next_id = max(next_id, max(_STABLE_MAP.values()) + 1)

    changed = False
    for k in keys:
        if not k or k in _INT_MAP:
            continue
        # Use stable index if one exists, otherwise assign new
        if k in _STABLE_MAP:
            idx = _STABLE_MAP[k]
        else:
            idx = next_id
            next_id += 1
            _STABLE_MAP[k] = idx
            changed = True
        _INT_MAP[k] = idx
        _INT_REV[idx] = k
        _EXTRA_KEYS.append(k)

    if changed:
        _save_stable_map()


def extra_texture_keys() -> list[str]:
    """Return the list of registered extra (non-tile) texture keys."""
    return list(_EXTRA_KEYS)


def total_texture_count() -> int:
    """Number of entries in the int map (tiles + extra textures)."""
    return max(len(_INT_REV), 1)


def rebuild_derived() -> None:
    """Rebuild all derived lookup tables from TILE_REGISTRY."""
    global SOLID_IDS, WALL_IDS, HALF_WALL_IDS, PLATFORM_IDS, DOOR_IDS
    SOLID_IDS = frozenset(k for k, td in TILE_REGISTRY.items() if td.solid)
    WALL_IDS = frozenset(k for k, td in TILE_REGISTRY.items() if td.wall)
    HALF_WALL_IDS = frozenset(k for k, td in TILE_REGISTRY.items() if td.half_wall)
    PLATFORM_IDS = frozenset(k for k, td in TILE_REGISTRY.items() if td.platform)
    DOOR_IDS = frozenset(k for k, td in TILE_REGISTRY.items()
                         if td.wall and not td.solid)
    TILE_COLORS.clear()
    TILE_COLORS.update({k: td.color for k, td in TILE_REGISTRY.items()})
    TILE_NAMES.clear()
    TILE_NAMES.update({k: td.name for k, td in TILE_REGISTRY.items()})
    for td in TILE_REGISTRY.values():
        if td.category and td.category not in TILE_CATEGORIES:
            TILE_CATEGORIES.append(td.category)
    _rebuild_int_map()


# ── Grouping helpers ─────────────────────────────────────────────

def tiles_by_category() -> dict[str, list[TileDef]]:
    groups: dict[str, list[TileDef]] = OrderedDict()
    for cat in TILE_CATEGORIES:
        groups[cat] = []
    for td in TILE_REGISTRY.values():
        groups.setdefault(td.category, []).append(td)
    for cat in groups:
        groups[cat].sort(key=lambda t: t.id)
    return {k: v for k, v in groups.items() if v}


def tiles_by_type() -> dict[TileType, list[TileDef]]:
    groups: dict[TileType, list[TileDef]] = OrderedDict()
    for tt in TileType:
        groups[tt] = []
    for td in TILE_REGISTRY.values():
        groups[td.type].append(td)
    for tt in groups:
        groups[tt].sort(key=lambda t: t.name)
    return {k: v for k, v in groups.items() if v}


# ── str ↔ compact int conversion ────────────────────────────────

def tile_str_to_int(key: str) -> int:
    return _INT_MAP.get(key, 0)


def tile_int_to_str(i: int) -> str:
    return _INT_REV.get(i, "void")


def grid_to_ints(tiles: list[list[str]]) -> list[list[int]]:
    m = _INT_MAP
    return [[m.get(c, 0) for c in row] for row in tiles]


# ── Rendering LUT builders ──────────────────────────────────────

def color_lut() -> list[tuple[int, int, int]]:
    n = max(len(_INT_REV), 1)
    lut: list[tuple[int, int, int]] = [(50, 50, 45)] * n
    for i, key in _INT_REV.items():
        td = TILE_REGISTRY.get(key)
        if td:
            lut[i] = td.color
    return lut


def solid_int_set() -> frozenset[int]:
    return frozenset(_INT_MAP[k] for k in SOLID_IDS if k in _INT_MAP)


def wall_lut() -> bytearray:
    n = max(len(_INT_REV), 1)
    ba = bytearray(n)
    for i, key in _INT_REV.items():
        if key in WALL_IDS:
            ba[i] = 1
    return ba


def half_wall_lut() -> bytearray:
    n = max(len(_INT_REV), 1)
    ba = bytearray(n)
    for i, key in _INT_REV.items():
        if key in HALF_WALL_IDS:
            ba[i] = 1
    return ba


def platform_lut() -> bytearray:
    n = max(len(_INT_REV), 1)
    ba = bytearray(n)
    for i, key in _INT_REV.items():
        if key in PLATFORM_IDS:
            ba[i] = 1
    return ba


def hs_lut() -> list[float]:
    n = max(len(_INT_REV), 1)
    lut = [1.0] * n
    for i, key in _INT_REV.items():
        td = TILE_REGISTRY.get(key)
        if td:
            lut[i] = td.height_scale
    return lut


def transparent_lut() -> bytearray:
    n = max(len(_INT_REV), 1)
    ba = bytearray(n)
    for i, key in _INT_REV.items():
        td = TILE_REGISTRY.get(key)
        if td and td.transparent:
            ba[i] = 1
    return ba


def thin_wall_lut() -> bytearray:
    n = max(len(_INT_REV), 1)
    ba = bytearray(n)
    for i, key in _INT_REV.items():
        td = TILE_REGISTRY.get(key)
        if td and td.thin_wall:
            ba[i] = 1
    return ba


def tall_wall_lut() -> bytearray:
    n = max(len(_INT_REV), 1)
    ba = bytearray(n)
    for i, key in _INT_REV.items():
        td = TILE_REGISTRY.get(key)
        if td and td.tall_wall:
            ba[i] = 1
    return ba


def alt_tex_lut() -> list[int]:
    n = max(len(_INT_REV), 1)
    out = [-1] * n
    for i, key in _INT_REV.items():
        td = TILE_REGISTRY.get(key)
        if td and td.alt_texture:
            alt_id = tile_str_to_int(td.alt_texture)
            if alt_id >= 0:
                out[i] = alt_id
    return out


def anim_lut() -> list[int]:
    """Build animated-texture LUT: 4 ints per tile.

    Layout per tile: ``[base_id, n_frames, stride, ticks_per_frame]``.
    For static tiles ``n_frames == 1`` and the resolver is a no-op.
    """
    n = max(len(_INT_REV), 1)
    lut: list[int] = []
    for i in range(n):
        key = _INT_REV.get(i)
        td = TILE_REGISTRY.get(key) if key else None
        if td and getattr(td, "anim_frames", 1) > 1:
            lut.extend([i, td.anim_frames, td.anim_stride, td.anim_ticks])
        else:
            lut.extend([i, 1, 1, 1])
    return lut

