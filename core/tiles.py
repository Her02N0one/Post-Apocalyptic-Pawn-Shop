"""core/tiles.py — JSON-backed tile registry with type system.

Tile IDs are human-readable strings (``"grass"``, ``"wall"``).
Definitions live as individual JSON files in ``assets/tiles/{key}.json``.

Each tile has a **type** that determines rendering behaviour and physics::

    "floor"     — walkable ground, no wall geometry
    "wall"      — full-height wall, blocks view & movement
    "half_wall" — partial-height wall, can see over, floor visible beneath
    "platform"  — elevated surface with visible top
    "door"      — wall-height, interactive (walkable when open)
    "liquid"    — floor-level liquid surface

DRY JSON — only non-default fields are stored::

    # assets/tiles/grass.json
    {"name": "Grass", "type": "floor", "color": [50, 80, 40],
     "sound": "grass"}

    # assets/tiles/wall.json
    {"name": "Wall", "type": "wall", "color": [100, 100, 100]}

    # assets/tiles/shelf_wall.json  (directional — distinct faces)
    {"name": "Shelf Wall", "type": "wall", "color": [120, 90, 60],
     "face_textures": {"south": "shelf_front"}}

    # assets/tiles/half_wall.json  (top surface visible)
    {"name": "Half Wall", "type": "half_wall",
     "color": [100, 95, 85], "face_textures": {"top": "stone_floor"}}

Tile-type texture profiles — each type dictates available face slots::

    FLOOR     → ("top",)              surface only
    WALL      → (N, S, E, W)          uniform or per-face walls
    HALF_WALL → (N, S, E, W, "top")   walls + visible top
    PLATFORM  → (N, S, E, W, "top")   walls + visible top
    DOOR      → (N, S, E, W)          like wall
    LIQUID    → ("top",)              surface only

Renderer texture usage:
  - **texture_key** → default wall PNG for all faces (fallback = tile id)
  - **face_textures** → per-face overrides {"north"/"south"/"east"/"west"/"top": key}
  - **color** → floor flat-colour fallback + editor/minimap

Systems never hard-code tile IDs — they query type or flags::

    from core.tiles import tile_def, TileType
    td = tile_def("wall")
    if td.type == TileType.WALL:
        ...
"""

from __future__ import annotations

import json
import os as _os
from dataclasses import dataclass
from enum import IntFlag, Enum
from typing import Any


# ═══════════════════════════════════════════════════════════════════
#  Tile Type
# ═══════════════════════════════════════════════════════════════════

class TileType(str, Enum):
    """Tile rendering / physics behaviour category."""

    FLOOR     = "floor"
    WALL      = "wall"
    HALF_WALL = "half_wall"
    PLATFORM  = "platform"
    DOOR      = "door"
    LIQUID    = "liquid"


# ═══════════════════════════════════════════════════════════════════
#  Tile Flags  (derived from type — kept for compatibility)
# ═══════════════════════════════════════════════════════════════════

class TF(IntFlag):
    """Binary property flags for tiles."""

    NONE        = 0
    SOLID       = 1 << 0
    WALL        = 1 << 1
    TRANSPARENT = 1 << 2
    LIQUID      = 1 << 3
    FARMLAND    = 1 << 4
    HALF_WALL   = 1 << 5
    PLATFORM    = 1 << 6


# Type → default flags
_TYPE_FLAGS: dict[TileType, TF] = {
    TileType.FLOOR:     TF.NONE,
    TileType.WALL:      TF.SOLID | TF.WALL,
    TileType.HALF_WALL: TF.SOLID | TF.WALL | TF.HALF_WALL,
    TileType.PLATFORM:  TF.SOLID | TF.PLATFORM,
    TileType.DOOR:      TF.WALL,           # wall but not solid
    TileType.LIQUID:    TF.LIQUID,
}

# Type → default wall height
_TYPE_DEFAULT_HEIGHT: dict[TileType, float] = {
    TileType.FLOOR:     0.0,
    TileType.WALL:      1.0,
    TileType.HALF_WALL: 0.5,
    TileType.PLATFORM:  0.3,
    TileType.DOOR:      1.0,
    TileType.LIQUID:    0.0,
}


# ── Flag name ↔ TF helpers (kept for migration / editor extras) ──

_FLAG_MAP: dict[str, TF] = {
    "SOLID": TF.SOLID, "WALL": TF.WALL, "TRANSPARENT": TF.TRANSPARENT,
    "LIQUID": TF.LIQUID, "FARMLAND": TF.FARMLAND, "HALF_WALL": TF.HALF_WALL,
    "PLATFORM": TF.PLATFORM,
}

_PROP_FLAG_MAP: dict[str, TF] = {
    "solid": TF.SOLID, "wall": TF.WALL, "transparent": TF.TRANSPARENT,
    "liquid": TF.LIQUID, "farmland": TF.FARMLAND, "half_wall": TF.HALF_WALL,
    "platform": TF.PLATFORM,
}


def _flags_from_names(names: list[str]) -> TF:
    """Build TF bits from a list of flag name strings (case-insensitive)."""
    result = TF.NONE
    for n in names:
        result |= _FLAG_MAP.get(n.strip().upper(), TF.NONE)
    return result


def _flags_to_names(flags: TF) -> list[str]:
    """Convert TF bits to a sorted list of uppercase flag names."""
    return [name for name, val in _FLAG_MAP.items() if flags & val]


def _type_from_flags(flags: TF) -> TileType:
    """Infer tile type from legacy flag bits (migration helper)."""
    if flags & TF.HALF_WALL:
        return TileType.HALF_WALL
    if flags & TF.PLATFORM:
        return TileType.PLATFORM
    if flags & TF.LIQUID:
        return TileType.LIQUID
    if flags & TF.WALL:
        if not (flags & TF.SOLID):
            return TileType.DOOR
        return TileType.WALL
    return TileType.FLOOR


# ═══════════════════════════════════════════════════════════════════
#  Tile Definition
# ═══════════════════════════════════════════════════════════════════

# ── Face slots available per tile type ────────────────────────────

FACE_WALL_SLOTS = ("north", "south", "east", "west")
FACE_TOP_SLOT   = ("top",)
FACE_ALL_SLOTS  = FACE_WALL_SLOTS + FACE_TOP_SLOT

TILE_FACE_SLOTS: dict[TileType, tuple[str, ...]] = {
    TileType.FLOOR:     FACE_TOP_SLOT,
    TileType.WALL:      FACE_WALL_SLOTS,
    TileType.HALF_WALL: FACE_ALL_SLOTS,
    TileType.PLATFORM:  FACE_ALL_SLOTS,
    TileType.DOOR:      FACE_WALL_SLOTS,
    TileType.LIQUID:    FACE_TOP_SLOT,
}


@dataclass(frozen=True)
class TileDef:
    """Immutable description of a tile type.

    ``id`` is the text key (e.g. ``"wall"``, ``"grass"``).
    ``type`` determines rendering behaviour and default physics flags.

    Texture fields::

        texture_key   — default wall PNG name ("" → use id)
        face_textures — per-face overrides {"north"/"south"/"east"/"west"/"top": key}
    """

    id: str
    name: str
    color: tuple[int, int, int]
    type: TileType = TileType.FLOOR
    flags: TF = TF.NONE
    texture_key: str = ""           # default wall PNG  ("" → use self.id)
    face_textures: tuple = ()       # frozen pairs: (("south","shelf"), ...)
    height_scale: float = 1.0
    category: str = "Terrain"
    sound: str = "stone"

    # ── flag convenience properties ──────────────────────────
    @property
    def solid(self) -> bool:
        return bool(self.flags & TF.SOLID)

    @property
    def wall(self) -> bool:
        return bool(self.flags & TF.WALL)

    @property
    def half_wall(self) -> bool:
        return bool(self.flags & TF.HALF_WALL)

    @property
    def transparent(self) -> bool:
        return bool(self.flags & TF.TRANSPARENT)

    @property
    def liquid(self) -> bool:
        return bool(self.flags & TF.LIQUID)

    @property
    def farmland(self) -> bool:
        return bool(self.flags & TF.FARMLAND)

    @property
    def platform(self) -> bool:
        return bool(self.flags & TF.PLATFORM)

    # ── texture helpers ──────────────────────────────────────
    def wall_tex(self) -> str:
        """Default wall-surface PNG key.  Falls back to tile id."""
        return self.texture_key or self.id

    def face_tex_dict(self) -> dict[str, str]:
        """Return face_textures as a plain dict."""
        return dict(self.face_textures)

    def tex_for_face(self, face: str) -> str:
        """Texture key for *face* ('north'|'south'|'east'|'west'|'top').

        Wall faces fall back to ``wall_tex()``.  'top' falls back to
        empty string (meaning flat colour).
        """
        d = dict(self.face_textures)
        if face in d:
            return d[face]
        if face in ("north", "south", "east", "west"):
            return self.wall_tex()
        return ""  # top → flat colour

    def top_tex(self) -> str:
        """Top-surface texture key, or ``""`` for flat colour."""
        return self.tex_for_face("top")

    def has_face_overrides(self) -> bool:
        """True if any per-face texture overrides are set."""
        return bool(self.face_textures)

    # Backward-compat shims
    @property
    def front_texture(self) -> str:
        return dict(self.face_textures).get("south", "")

    @property
    def floor_texture(self) -> str:
        return self.top_tex()

    def front_tex(self) -> str:
        return self.tex_for_face("south")

    def floor_tex(self) -> str:
        return self.top_tex()

    def has_front(self) -> bool:
        return "south" in dict(self.face_textures)


# ═══════════════════════════════════════════════════════════════════
#  Paths
# ═══════════════════════════════════════════════════════════════════

_PROJECT_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
TILE_TEX_DIR = _os.path.join(_PROJECT_ROOT, "assets", "textures", "tiles")
_TILES_DIR = _os.path.join(_PROJECT_ROOT, "assets", "tiles")


# ═══════════════════════════════════════════════════════════════════
#  Categories  (ordered list, editable via the editor)
# ═══════════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════════
#  Registry  (keyed by text ID)
# ═══════════════════════════════════════════════════════════════════

TILE_REGISTRY: dict[str, TileDef] = {}
_FALLBACK = TileDef("void", "Unknown", (120, 120, 120),
                     TileType.WALL, TF.SOLID | TF.WALL)


def tile_def(tile_id: str) -> TileDef:
    """Look up a tile definition, returning a safe fallback for unknowns."""
    return TILE_REGISTRY.get(tile_id, _FALLBACK)


# ═══════════════════════════════════════════════════════════════════
#  Derived lookup tables
# ═══════════════════════════════════════════════════════════════════

SOLID_IDS: frozenset[str] = frozenset()
WALL_IDS: frozenset[str] = frozenset()
HALF_WALL_IDS: frozenset[str] = frozenset()
PLATFORM_IDS: frozenset[str] = frozenset()
DOOR_IDS: frozenset[str] = frozenset()

TILE_COLORS: dict[str, tuple[int, int, int]] = {}
TILE_NAMES: dict[str, str] = {}

# ── Internal compact int mapping (for C extension / numpy) ───
_INT_MAP: dict[str, int] = {}   # tile_key → compact int
_INT_REV: dict[int, str] = {}   # compact int → tile_key


def _rebuild_int_map() -> None:
    """Assign compact sequential ints for rendering boundaries."""
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


def tiles_by_category() -> dict[str, list[TileDef]]:
    """Return tiles grouped by category, preserving TILE_CATEGORIES order."""
    from collections import OrderedDict
    groups: dict[str, list[TileDef]] = OrderedDict()
    for cat in TILE_CATEGORIES:
        groups[cat] = []
    for td in TILE_REGISTRY.values():
        groups.setdefault(td.category, []).append(td)
    for cat in groups:
        groups[cat].sort(key=lambda t: t.id)
    return {k: v for k, v in groups.items() if v}


def tiles_by_type() -> dict[TileType, list[TileDef]]:
    """Return tiles grouped by TileType, ordered by the enum definition."""
    from collections import OrderedDict
    groups: dict[TileType, list[TileDef]] = OrderedDict()
    for tt in TileType:
        groups[tt] = []
    for td in TILE_REGISTRY.values():
        groups[td.type].append(td)
    for tt in groups:
        groups[tt].sort(key=lambda t: t.name)
    return {k: v for k, v in groups.items() if v}


# ═══════════════════════════════════════════════════════════════════
#  Rendering-boundary helpers  (str ↔ compact int)
# ═══════════════════════════════════════════════════════════════════

def tile_str_to_int(key: str) -> int:
    """Convert a string tile ID to its compact rendering integer."""
    return _INT_MAP.get(key, 0)


def tile_int_to_str(i: int) -> str:
    """Convert a compact rendering integer to a string tile ID."""
    return _INT_REV.get(i, "void")


def grid_to_ints(tiles: list[list[str]]) -> list[list[int]]:
    """Convert a string tile grid to a compact-int grid for rendering."""
    m = _INT_MAP
    return [[m.get(c, 0) for c in row] for row in tiles]


def color_lut() -> list[tuple[int, int, int]]:
    """Build a colour LUT indexed by compact int."""
    n = max(len(_INT_REV), 1)
    lut: list[tuple[int, int, int]] = [(50, 50, 45)] * n
    for i, key in _INT_REV.items():
        td = TILE_REGISTRY.get(key)
        if td:
            lut[i] = td.color
    return lut


def solid_int_set() -> frozenset[int]:
    """Compact-int set of solid tiles."""
    return frozenset(_INT_MAP[k] for k in SOLID_IDS if k in _INT_MAP)


def wall_lut() -> bytearray:
    """Bytearray[compact_int] → 1 if wall, 0 otherwise (for C ext)."""
    n = max(len(_INT_REV), 1)
    ba = bytearray(n)
    for i, key in _INT_REV.items():
        if key in WALL_IDS:
            ba[i] = 1
    return ba


def half_wall_lut() -> bytearray:
    """Bytearray[compact_int] → 1 if half_wall (for C ext)."""
    n = max(len(_INT_REV), 1)
    ba = bytearray(n)
    for i, key in _INT_REV.items():
        if key in HALF_WALL_IDS:
            ba[i] = 1
    return ba


def platform_lut() -> bytearray:
    """Bytearray[compact_int] → 1 if platform."""
    n = max(len(_INT_REV), 1)
    ba = bytearray(n)
    for i, key in _INT_REV.items():
        if key in PLATFORM_IDS:
            ba[i] = 1
    return ba


def hs_lut() -> list[float]:
    """Height-scale LUT indexed by compact int."""
    n = max(len(_INT_REV), 1)
    lut = [1.0] * n
    for i, key in _INT_REV.items():
        td = TILE_REGISTRY.get(key)
        if td:
            lut[i] = td.height_scale
    return lut


# ═══════════════════════════════════════════════════════════════════
#  Old int→str migration map
# ═══════════════════════════════════════════════════════════════════

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
    """Convert an old integer tile grid to string IDs."""
    m = _OLD_INT_TO_STR
    return [[m.get(c, "void") for c in row] for row in tiles]


# ═══════════════════════════════════════════════════════════════════
#  JSON persistence  — DRY format, one file per tile
# ═══════════════════════════════════════════════════════════════════

def _tile_json_path(tile_key: str) -> str:
    """Return ``assets/tiles/{key}.json``."""
    return _os.path.join(_TILES_DIR, f"{tile_key}.json")


def _parse_tile_json(path: str) -> TileDef | None:
    """Parse a DRY-format tile JSON into a TileDef.

    Supports both the new ``type``-based format and the legacy
    ``flags``-list format (auto-migrated on next save).
    """
    try:
        with open(path, "r") as f:
            data = json.load(f)
    except Exception:
        return None

    basename = _os.path.splitext(_os.path.basename(path))[0]
    if basename.startswith("_"):
        return None  # skip meta files like _categories.json

    tile_key = basename
    raw_color = data.get("color", [120, 120, 120])
    color = (int(raw_color[0]), int(raw_color[1]), int(raw_color[2]))

    # ── Type (new) or Flags (legacy) ────────────────────────
    type_str = data.get("type")
    if type_str:
        try:
            tile_type = TileType(type_str)
        except ValueError:
            tile_type = TileType.FLOOR
        flags = _TYPE_FLAGS.get(tile_type, TF.NONE)
    else:
        # Legacy format: infer type from flags array
        flag_names = data.get("flags", [])
        legacy_flags = _flags_from_names(flag_names)
        tile_type = _type_from_flags(legacy_flags)
        flags = _TYPE_FLAGS.get(tile_type, TF.NONE)

    # Extra flag modifiers (not covered by type)
    if data.get("transparent", False):
        flags |= TF.TRANSPARENT
    if data.get("farmland", False):
        flags |= TF.FARMLAND

    # ── Height (explicit or default from type) ──────────────
    default_h = _TYPE_DEFAULT_HEIGHT.get(tile_type, 1.0)
    height = float(data.get("height", default_h))

    # ── Texture fields ──────────────────────────────────────
    texture_key = data.get("texture_key", "")
    # Legacy: old "texture" field that was a string
    if not texture_key:
        old_tex = data.get("texture")
        if isinstance(old_tex, str):
            texture_key = old_tex

    # face_textures: new dict format or migrated from legacy fields
    raw_ft = data.get("face_textures")
    if isinstance(raw_ft, dict):
        face_textures = tuple(sorted(raw_ft.items()))
    else:
        # Migrate legacy front_texture / floor_texture
        _pairs: list[tuple[str, str]] = []
        _old_front = data.get("front_texture", "")
        if _old_front:
            _pairs.append(("south", _old_front))
        _old_floor = data.get("floor_texture", "")
        if _old_floor:
            _pairs.append(("top", _old_floor))
        face_textures = tuple(sorted(_pairs))

    return TileDef(
        id=tile_key,
        name=data.get("name", tile_key),
        color=color,
        type=tile_type,
        flags=flags,
        texture_key=texture_key,
        face_textures=face_textures,
        height_scale=height,
        category=data.get("category", "Custom"),
        sound=data.get("sound", "stone"),
    )


def _load_categories_json() -> bool:
    """Load ``assets/tiles/_categories.json``."""
    path = _os.path.join(_TILES_DIR, "_categories.json")
    if not _os.path.exists(path):
        return False
    try:
        with open(path, "r") as f:
            data = json.load(f)
        cats: list[str] = data if isinstance(data, list) else []
        if cats:
            TILE_CATEGORIES.clear()
            TILE_CATEGORIES.extend(cats)
        return True
    except Exception:
        return False


def _load_tiles_json() -> bool:
    """Load all ``assets/tiles/*.json`` files into TILE_REGISTRY."""
    if not _os.path.isdir(_TILES_DIR):
        return False
    _load_categories_json()
    loaded = 0
    for fname in sorted(_os.listdir(_TILES_DIR)):
        if not fname.endswith(".json") or fname.startswith("_"):
            continue
        td = _parse_tile_json(_os.path.join(_TILES_DIR, fname))
        if td is not None:
            TILE_REGISTRY[td.id] = td
            loaded += 1
    if loaded == 0:
        return False
    rebuild_derived()
    return True


def _save_categories_json() -> None:
    """Write categories as a plain JSON array."""
    _os.makedirs(_TILES_DIR, exist_ok=True)
    path = _os.path.join(_TILES_DIR, "_categories.json")
    with open(path, "w") as f:
        json.dump(list(TILE_CATEGORIES), f, indent=2)
        f.write("\n")


def _save_tile_json(td: TileDef) -> str:
    """Write a single tile definition to its DRY JSON file."""
    out: dict[str, Any] = {
        "name": td.name,
        "type": td.type.value,
        "category": td.category,
    }
    if td.sound != "stone":
        out["sound"] = td.sound
    out["color"] = list(td.color)

    # Extra flags not derived from type
    if td.flags & TF.TRANSPARENT:
        out["transparent"] = True
    if td.flags & TF.FARMLAND:
        out["farmland"] = True

    # Textures (only when non-default)
    if td.texture_key:
        out["texture_key"] = td.texture_key
    if td.face_textures:
        out["face_textures"] = dict(td.face_textures)

    # Height (only when different from type default)
    default_h = _TYPE_DEFAULT_HEIGHT.get(td.type, 1.0)
    if td.height_scale != default_h:
        out["height"] = td.height_scale

    _os.makedirs(_TILES_DIR, exist_ok=True)
    path = _tile_json_path(td.id)
    with open(path, "w") as f:
        json.dump(out, f, indent=2)
        f.write("\n")
    return path


def save_tiles() -> None:
    """Write ALL tiles and categories to ``assets/tiles/``."""
    _save_categories_json()
    for td in TILE_REGISTRY.values():
        _save_tile_json(td)
    rebuild_derived()


def save_tile(tile_id: str) -> None:
    """Write a single tile's JSON file."""
    td = TILE_REGISTRY.get(tile_id)
    if td:
        _save_tile_json(td)


# ═══════════════════════════════════════════════════════════════════
#  CRUD operations  (editor calls these)
# ═══════════════════════════════════════════════════════════════════

def _next_tile_key(name: str) -> str:
    """Generate a unique key from a display name."""
    key = name.lower().replace(" ", "_")
    if key not in TILE_REGISTRY:
        return key
    i = 2
    while f"{key}_{i}" in TILE_REGISTRY:
        i += 1
    return f"{key}_{i}"


def register_tile(
    name: str,
    color: tuple[int, int, int],
    tile_type: TileType = TileType.FLOOR,
    flags: TF | None = None,
    texture_key: str = "",
    face_textures: dict[str, str] | None = None,
    height_scale: float | None = None,
    category: str = "Custom",
    sound: str = "stone",
    *,
    tile_key: str = "",
    # Legacy compat kwargs (silently converted)
    front_texture: str = "",
    floor_texture: str = "",
) -> TileDef:
    """Create and register a new tile.  Auto-assigns key, saves JSON."""
    key = tile_key or _next_tile_key(name)
    if flags is None:
        flags = _TYPE_FLAGS.get(tile_type, TF.NONE)
    if height_scale is None:
        height_scale = _TYPE_DEFAULT_HEIGHT.get(tile_type, 1.0)
    # Build face_textures tuple
    ft_dict: dict[str, str] = dict(face_textures) if face_textures else {}
    if front_texture and "south" not in ft_dict:
        ft_dict["south"] = front_texture
    if floor_texture and "top" not in ft_dict:
        ft_dict["top"] = floor_texture
    ft_pairs = tuple(sorted(ft_dict.items()))
    td = TileDef(
        id=key, name=name, color=color, type=tile_type,
        flags=flags, texture_key=texture_key,
        face_textures=ft_pairs,
        height_scale=height_scale,
        category=category, sound=sound,
    )
    TILE_REGISTRY[key] = td
    rebuild_derived()
    _save_tile_json(td)
    _save_categories_json()
    return td


def update_tile(tile_id: str, **kwargs: Any) -> TileDef | None:
    """Update an existing tile's properties.  Saves JSON."""
    old = TILE_REGISTRY.get(tile_id)
    if old is None:
        return None
    old_path = _tile_json_path(old.id)

    fields: dict[str, Any] = {
        "id": old.id, "name": old.name, "color": old.color,
        "type": old.type, "flags": old.flags,
        "texture_key": old.texture_key,
        "face_textures": old.face_textures,
        "height_scale": old.height_scale, "category": old.category,
        "sound": old.sound,
    }
    # Accept face_textures as dict → convert to tuple
    if "face_textures" in kwargs:
        v = kwargs.pop("face_textures")
        if isinstance(v, dict):
            fields["face_textures"] = tuple(sorted(v.items()))
        else:
            fields["face_textures"] = v
    # Legacy compat
    if "front_texture" in kwargs:
        ft_d = dict(fields["face_textures"])
        ft_d["south"] = kwargs.pop("front_texture")
        if not ft_d["south"]:
            ft_d.pop("south", None)
        fields["face_textures"] = tuple(sorted(ft_d.items()))
    if "floor_texture" in kwargs:
        ft_d = dict(fields["face_textures"])
        ft_d["top"] = kwargs.pop("floor_texture")
        if not ft_d["top"]:
            ft_d.pop("top", None)
        fields["face_textures"] = tuple(sorted(ft_d.items()))
    fields.update(kwargs)

    # Re-derive flags when type changes (unless caller explicitly set flags)
    if "type" in kwargs and "flags" not in kwargs:
        fields["flags"] = _TYPE_FLAGS.get(fields["type"], TF.NONE)

    td = TileDef(**fields)
    TILE_REGISTRY[td.id] = td
    rebuild_derived()

    new_path = _tile_json_path(td.id)
    if old_path != new_path and _os.path.exists(old_path):
        _os.remove(old_path)
    _save_tile_json(td)
    return td


def delete_tile(tile_id: str) -> bool:
    """Remove a tile from the registry and delete its JSON file."""
    td = TILE_REGISTRY.get(tile_id)
    if td is None:
        return False
    path = _tile_json_path(td.id)
    if _os.path.exists(path):
        _os.remove(path)
    del TILE_REGISTRY[tile_id]
    rebuild_derived()
    return True


def add_category(name: str) -> None:
    """Add a new category.  Saves categories JSON."""
    if name and name not in TILE_CATEGORIES:
        TILE_CATEGORIES.append(name)
        _save_categories_json()


def remove_category(name: str) -> None:
    """Remove a category.  Tiles in it become 'Custom'.  Saves JSON."""
    if name in TILE_CATEGORIES:
        TILE_CATEGORIES.remove(name)
        for tid, td in list(TILE_REGISTRY.items()):
            if td.category == name:
                update_tile(tid, category="Custom")
        _save_categories_json()


# ── Backward-compat aliases ──────────────────────────────────────

def register_custom_tile(name, color, flags=TF.NONE, texture_key="",
                         height_scale=1.0, category="Custom"):
    tile_type = _type_from_flags(flags)
    return register_tile(name, color, tile_type=tile_type, flags=flags,
                         texture_key=texture_key, height_scale=height_scale,
                         category=category)


def delete_custom_tile(tile_id):
    return delete_tile(tile_id)


def save_custom_tiles():
    save_tiles()


def load_custom_tiles():
    pass


def _next_custom_id():
    return _next_tile_key("custom")


# ═══════════════════════════════════════════════════════════════════
#  Bootstrap
# ═══════════════════════════════════════════════════════════════════

def _bootstrap() -> None:
    """Load tiles from JSON files in ``assets/tiles/``."""
    if _load_tiles_json():
        return
    # Minimal fallback — shouldn't happen with shipped asset files.
    TILE_REGISTRY["void"] = TileDef(
        "void", "Void", (40, 40, 40),
        type=TileType.WALL,
        flags=TF.SOLID | TF.WALL,
    )
    rebuild_derived()


_bootstrap()
