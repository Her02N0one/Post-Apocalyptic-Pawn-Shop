"""core/tiles.py — TOML-backed tile registry with directional textures.

Tile IDs are human-readable strings (``"grass"``, ``"wall"``).
Definitions live as individual TOML files in ``assets/models/tiles/{key}.toml``.

Each tile has a **type** that determines rendering behaviour and physics::

    "floor"     — walkable ground, no wall geometry
    "wall"      — full-height wall, blocks view & movement
    "half_wall" — partial-height wall, can see over, floor visible beneath
    "platform"  — elevated surface with visible top
    "door"      — wall-height, interactive (walkable when open)
    "liquid"    — floor-level liquid surface

DRY TOML — only non-default fields are stored::

    # assets/models/tiles/grass.toml
    name = "Grass"
    type = "floor"
    category = "Terrain"
    color = [50, 80, 40]
    sound = "grass"

    # assets/models/tiles/crt_tv.toml  (directional — distinct front/back)
    name = "CRT Television"
    type = "wall"
    category = "Props"
    color = [40, 40, 40]
    texture = "tv_casing"
    texture_front = "tv_static"
    texture_back = "tv_vents"

Directional texture model::

    texture       — default PNG for all faces (fallback = tile id)
    texture_front — optional override for the tile's "front" face
    texture_back  — optional override for the tile's "back" face

    Which world-face (N/S/E/W) is "front" depends on the tile's
    **rotation** (0–3) stored in the zone's rotation grid:

        rotation 0 → front=south  back=north
        rotation 1 → front=west   back=east
        rotation 2 → front=north  back=south
        rotation 3 → front=east   back=west

Systems never hard-code tile IDs — they query type or flags::

    from core.tiles import tile_def, TileType
    td = tile_def("wall")
    if td.type == TileType.WALL:
        ...
"""

from __future__ import annotations

import os as _os
from dataclasses import dataclass
from enum import IntFlag, Enum
from typing import Any

try:
    import tomllib as _tomllib          # Python 3.11+
except ModuleNotFoundError:
    import tomli as _tomllib            # Python 3.9–3.10


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


# ── Rotation → cardinal face mapping ─────────────────────────────

# Which world-face is "front" for each rotation value (0–3).
_ROT_FRONT = ("south", "west", "north", "east")
_ROT_BACK  = ("north", "east", "south", "west")


@dataclass(frozen=True)
class TileDef:
    """Immutable description of a tile type.

    ``id`` is the text key (e.g. ``"wall"``, ``"grass"``).
    ``type`` determines rendering behaviour and default physics flags.

    Texture fields (directional model)::

        texture_key     — default PNG for all faces ("" → use tile id)
        texture_front   — optional front-face override
        texture_back    — optional back-face override

    The "front" and "back" faces are relative to the tile's rotation
    in the zone grid.  See ``tex_for_face()``.
    """

    id: str
    name: str
    color: tuple[int, int, int]
    type: TileType = TileType.FLOOR
    flags: TF = TF.NONE
    texture_key: str = ""           # default PNG for all faces ("" → use self.id)
    texture_front: str = ""         # optional front-face override
    texture_back: str = ""          # optional back-face override
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

    def tex_for_face(self, face: str, rotation: int = 0) -> str:
        """Texture key for a world face, accounting for tile rotation.

        *face*: ``'north'`` | ``'south'`` | ``'east'`` | ``'west'`` | ``'top'``
        *rotation*: 0–3 (0=default, 1=90° CW, 2=180°, 3=270° CW)

        For wall faces the method checks whether *face* is the tile's
        "front" or "back" (determined by *rotation*) and returns the
        appropriate override texture.  Falls back to ``wall_tex()``.
        ``'top'`` always returns ``""`` (flat colour).
        """
        if face == "top":
            return ""  # top → flat colour
        rot = rotation % 4
        if face == _ROT_FRONT[rot] and self.texture_front:
            return self.texture_front
        if face == _ROT_BACK[rot] and self.texture_back:
            return self.texture_back
        return self.wall_tex()

    def top_tex(self) -> str:
        """Top-surface texture key, or ``""`` for flat colour."""
        return ""

    def has_directional_textures(self) -> bool:
        """True if front or back texture overrides are set."""
        return bool(self.texture_front or self.texture_back)

    # ── Backward-compat shims (face_textures tuple API) ──────
    @property
    def face_textures(self) -> tuple:
        """Legacy compat: synthesize face_textures from directional fields.

        Maps texture_front → "south" and texture_back → "north"
        (assuming rotation 0).
        """
        pairs: list[tuple[str, str]] = []
        if self.texture_front:
            pairs.append(("south", self.texture_front))
        if self.texture_back:
            pairs.append(("north", self.texture_back))
        return tuple(sorted(pairs))

    def face_tex_dict(self) -> dict[str, str]:
        """Legacy compat: return face_textures as a plain dict."""
        return dict(self.face_textures)

    def has_face_overrides(self) -> bool:
        """Legacy compat: same as has_directional_textures."""
        return self.has_directional_textures()

    @property
    def front_texture(self) -> str:
        return self.texture_front

    @property
    def floor_texture(self) -> str:
        return ""

    def front_tex(self) -> str:
        return self.texture_front

    def floor_tex(self) -> str:
        return ""

    def has_front(self) -> bool:
        return bool(self.texture_front)


# ═══════════════════════════════════════════════════════════════════
#  Paths  (imported from core/paths — single source of truth)
# ═══════════════════════════════════════════════════════════════════

from core.paths import (
    TILE_TEX_DIR as _TILE_TEX_DIR_P,
    TILES_TOML_DIR as _TILES_TOML_DIR_P,
)

# String versions for os.path callers that still exist in this module
TILE_TEX_DIR = str(_TILE_TEX_DIR_P)
_TILES_TOML_DIR = str(_TILES_TOML_DIR_P)        # primary TOML


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
#  TOML persistence  — DRY format, one file per tile in assets/models/tiles/
# ═══════════════════════════════════════════════════════════════════

def _tile_toml_path(tile_key: str) -> str:
    """Return ``assets/models/tiles/{key}.toml``."""
    return _os.path.join(_TILES_TOML_DIR, f"{tile_key}.toml")


def _parse_tile_toml(path: str) -> TileDef | None:
    """Parse a DRY-format tile TOML into a TileDef."""
    try:
        with open(path, "rb") as f:
            data = _tomllib.load(f)
    except Exception:
        return None

    basename = _os.path.splitext(_os.path.basename(path))[0]
    if basename.startswith("_"):
        return None

    tile_key = basename
    raw_color = data.get("color", [120, 120, 120])
    color = (int(raw_color[0]), int(raw_color[1]), int(raw_color[2]))

    type_str = data.get("type", "floor")
    try:
        tile_type = TileType(type_str)
    except ValueError:
        tile_type = TileType.FLOOR
    flags = _TYPE_FLAGS.get(tile_type, TF.NONE)

    if data.get("transparent", False):
        flags |= TF.TRANSPARENT
    if data.get("farmland", False):
        flags |= TF.FARMLAND

    default_h = _TYPE_DEFAULT_HEIGHT.get(tile_type, 1.0)
    height = float(data.get("height", default_h))

    # Directional texture fields
    texture_key = data.get("texture", "")
    texture_front = data.get("texture_front", "")
    texture_back = data.get("texture_back", "")

    return TileDef(
        id=tile_key,
        name=data.get("name", tile_key),
        color=color,
        type=tile_type,
        flags=flags,
        texture_key=texture_key,
        texture_front=texture_front,
        texture_back=texture_back,
        height_scale=height,
        category=data.get("category", "Custom"),
        sound=data.get("sound", "stone"),
    )


def _load_tiles_toml() -> bool:
    """Load all ``assets/models/tiles/*.toml`` files into TILE_REGISTRY."""
    if not _os.path.isdir(_TILES_TOML_DIR):
        return False
    loaded = 0
    for fname in sorted(_os.listdir(_TILES_TOML_DIR)):
        if not fname.endswith(".toml") or fname.startswith("_"):
            continue
        td = _parse_tile_toml(_os.path.join(_TILES_TOML_DIR, fname))
        if td is not None:
            TILE_REGISTRY[td.id] = td
            loaded += 1
    if loaded == 0:
        return False
    rebuild_derived()
    return True


def _save_tile_toml(td: TileDef) -> str:
    """Write a single tile definition to its DRY TOML file."""
    lines: list[str] = []
    lines.append(f'name = "{td.name}"')
    lines.append(f'type = "{td.type.value}"')
    lines.append(f'category = "{td.category}"')
    lines.append(f'color = [{td.color[0]}, {td.color[1]}, {td.color[2]}]')

    if td.sound != "stone":
        lines.append(f'sound = "{td.sound}"')

    # Textures (only when non-default)
    if td.texture_key:
        lines.append("")
        lines.append(f'texture = "{td.texture_key}"')
    if td.texture_front:
        lines.append(f'texture_front = "{td.texture_front}"')
    if td.texture_back:
        lines.append(f'texture_back = "{td.texture_back}"')

    # Extra flags not derived from type
    if td.flags & TF.TRANSPARENT:
        lines.append("transparent = true")
    if td.flags & TF.FARMLAND:
        lines.append("farmland = true")

    # Height (only when different from type default)
    default_h = _TYPE_DEFAULT_HEIGHT.get(td.type, 1.0)
    if td.height_scale != default_h:
        lines.append(f"height = {td.height_scale}")

    _os.makedirs(_TILES_TOML_DIR, exist_ok=True)
    path = _tile_toml_path(td.id)
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return path


def save_tiles() -> None:
    """Write ALL tiles to ``assets/models/tiles/``."""
    for td in TILE_REGISTRY.values():
        _save_tile_toml(td)
    rebuild_derived()


def save_tile(tile_id: str) -> None:
    """Write a single tile's TOML file."""
    td = TILE_REGISTRY.get(tile_id)
    if td:
        _save_tile_toml(td)


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
    texture_front: str = "",
    texture_back: str = "",
    height_scale: float | None = None,
    category: str = "Custom",
    sound: str = "stone",
    *,
    tile_key: str = "",
    # Legacy compat kwargs (silently converted)
    face_textures: dict[str, str] | None = None,
    front_texture: str = "",
) -> TileDef:
    """Create and register a new tile.  Auto-assigns key, saves TOML."""
    key = tile_key or _next_tile_key(name)
    if flags is None:
        flags = _TYPE_FLAGS.get(tile_type, TF.NONE)
    if height_scale is None:
        height_scale = _TYPE_DEFAULT_HEIGHT.get(tile_type, 1.0)

    # Legacy compat: convert face_textures dict to directional fields
    if face_textures:
        if not texture_front:
            texture_front = face_textures.get("south", "")
        if not texture_back:
            texture_back = face_textures.get("north", "")
    if front_texture and not texture_front:
        texture_front = front_texture

    td = TileDef(
        id=key, name=name, color=color, type=tile_type,
        flags=flags, texture_key=texture_key,
        texture_front=texture_front, texture_back=texture_back,
        height_scale=height_scale,
        category=category, sound=sound,
    )
    TILE_REGISTRY[key] = td
    rebuild_derived()
    _save_tile_toml(td)
    return td


def update_tile(tile_id: str, **kwargs: Any) -> TileDef | None:
    """Update an existing tile's properties.  Saves TOML."""
    old = TILE_REGISTRY.get(tile_id)
    if old is None:
        return None
    old_toml = _tile_toml_path(old.id)

    fields: dict[str, Any] = {
        "id": old.id, "name": old.name, "color": old.color,
        "type": old.type, "flags": old.flags,
        "texture_key": old.texture_key,
        "texture_front": old.texture_front,
        "texture_back": old.texture_back,
        "height_scale": old.height_scale, "category": old.category,
        "sound": old.sound,
    }

    # Legacy compat: convert face_textures dict to directional fields
    if "face_textures" in kwargs:
        ft = kwargs.pop("face_textures")
        if isinstance(ft, dict):
            if "south" in ft:
                fields["texture_front"] = ft["south"]
            if "north" in ft:
                fields["texture_back"] = ft["north"]
        # tuple of pairs
        elif isinstance(ft, tuple):
            d = dict(ft)
            if "south" in d:
                fields["texture_front"] = d["south"]
            if "north" in d:
                fields["texture_back"] = d["north"]
    if "front_texture" in kwargs:
        fields["texture_front"] = kwargs.pop("front_texture")
    if "floor_texture" in kwargs:
        kwargs.pop("floor_texture")  # no-op, no longer stored

    fields.update(kwargs)

    # Re-derive flags when type changes (unless caller explicitly set flags)
    if "type" in kwargs and "flags" not in kwargs:
        fields["flags"] = _TYPE_FLAGS.get(fields["type"], TF.NONE)

    td = TileDef(**fields)
    TILE_REGISTRY[td.id] = td
    rebuild_derived()

    new_toml = _tile_toml_path(td.id)
    # Clean up old TOML if the key changed
    if old_toml != new_toml and _os.path.exists(old_toml):
        _os.remove(old_toml)
    _save_tile_toml(td)
    return td


def delete_tile(tile_id: str) -> bool:
    """Remove a tile from the registry and delete its files."""
    td = TILE_REGISTRY.get(tile_id)
    if td is None:
        return False
    path = _tile_toml_path(td.id)
    if _os.path.exists(path):
        _os.remove(path)
    del TILE_REGISTRY[tile_id]
    rebuild_derived()
    return True


def add_category(name: str) -> None:
    """Add a new category."""
    if name and name not in TILE_CATEGORIES:
        TILE_CATEGORIES.append(name)


def remove_category(name: str) -> None:
    """Remove a category.  Tiles in it become 'Custom'."""
    if name in TILE_CATEGORIES:
        TILE_CATEGORIES.remove(name)
        for tid, td in list(TILE_REGISTRY.items()):
            if td.category == name:
                update_tile(tid, category="Custom")


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
    """Load tiles from TOML (assets/models/tiles/)."""
    if _load_tiles_toml():
        return
    # Minimal fallback — shouldn't happen with shipped asset files.
    TILE_REGISTRY["void"] = TileDef(
        "void", "Void", (40, 40, 40),
        type=TileType.WALL,
        flags=TF.SOLID | TF.WALL,
    )
    rebuild_derived()


_bootstrap()
