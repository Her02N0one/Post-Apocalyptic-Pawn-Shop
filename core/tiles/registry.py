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


# ── Old int→str migration map ───────────────────────────────────

_OLD_INT_TO_STR: dict[int, str] = {
    0: "void", 1: "grass", 2: "dirt", 3: "stone", 4: "water",
    5: "wood_floor", 6: "wall", 7: "sand", 8: "rubble",
    9: "door", 10: "window", 11: "farmland", 12: "gateway",
    13: "concrete", 14: "tile_floor", 15: "metal_wall",
    16: "half_wall", 17: "low_wall", 18: "pillar",
    19: "counter_top", 20: "railing", 21: "carpet",
    22: "brick_wall", 23: "wood_panel", 24: "cracked_floor",
    25: "stone_floor", 26: "shelf_wall", 27: "stone_platform",
    28: "wood_platform", 29: "metal_platform", 30: "crate_stack",
    31: "table", 32: "curb", 33: "stool", 34: "step",
}


def migrate_int_grid(tiles: list[list[int]]) -> list[list[str]]:
    m = _OLD_INT_TO_STR
    return [[m.get(c, "void") for c in row] for row in tiles]
