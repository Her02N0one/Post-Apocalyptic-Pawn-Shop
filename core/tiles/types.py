"""core/tiles/types.py — Tile enums, flags, and TileDef dataclass.

Pure data definitions with zero project dependencies.
"""

from __future__ import annotations

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
#  Tile Flags
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
    THIN_WALL   = 1 << 7
    TALL_WALL   = 1 << 8


# Type → default flags
_TYPE_FLAGS: dict[TileType, TF] = {
    TileType.FLOOR:     TF.NONE,
    TileType.WALL:      TF.SOLID | TF.WALL,
    TileType.HALF_WALL: TF.SOLID | TF.WALL | TF.HALF_WALL,
    TileType.PLATFORM:  TF.SOLID | TF.PLATFORM,
    TileType.DOOR:      TF.WALL,
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


# ── Flag name ↔ TF helpers ──────────────────────────────────────

_FLAG_MAP: dict[str, TF] = {
    "SOLID": TF.SOLID, "WALL": TF.WALL, "TRANSPARENT": TF.TRANSPARENT,
    "LIQUID": TF.LIQUID, "FARMLAND": TF.FARMLAND, "HALF_WALL": TF.HALF_WALL,
    "PLATFORM": TF.PLATFORM, "THIN_WALL": TF.THIN_WALL, "TALL_WALL": TF.TALL_WALL,
}

_PROP_FLAG_MAP: dict[str, TF] = {
    "solid": TF.SOLID, "wall": TF.WALL, "transparent": TF.TRANSPARENT,
    "liquid": TF.LIQUID, "farmland": TF.FARMLAND, "half_wall": TF.HALF_WALL,
    "platform": TF.PLATFORM, "thin_wall": TF.THIN_WALL, "tall_wall": TF.TALL_WALL,
}


def _flags_from_names(names: list[str]) -> TF:
    result = TF.NONE
    for n in names:
        result |= _FLAG_MAP.get(n.strip().upper(), TF.NONE)
    return result


def _flags_to_names(flags: TF) -> list[str]:
    return [name for name, val in _FLAG_MAP.items() if flags & val]


def _type_from_flags(flags: TF) -> TileType:
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
#  Face-slot constants
# ═══════════════════════════════════════════════════════════════════

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

_ROT_FRONT = ("south", "west", "north", "east")
_ROT_BACK  = ("north", "east", "south", "west")


# ═══════════════════════════════════════════════════════════════════
#  TileDef dataclass
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class TileDef:
    """Immutable description of a tile type."""

    id: str
    name: str
    color: tuple[int, int, int]
    type: TileType = TileType.FLOOR
    flags: TF = TF.NONE
    texture_key: str = ""
    texture_front: str = ""
    texture_back: str = ""
    tex_n: str = ""
    tex_s: str = ""
    tex_e: str = ""
    tex_w: str = ""
    alt_texture: str = ""
    height_scale: float = 1.0
    v_scale: float = 1.0          # vertical texture scale (0.5 = covers 2 world-units)
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

    @property
    def thin_wall(self) -> bool:
        return bool(self.flags & TF.THIN_WALL)

    @property
    def tall_wall(self) -> bool:
        return bool(self.flags & TF.TALL_WALL)

    # ── texture helpers ──────────────────────────────────────
    def wall_tex(self) -> str:
        return self.texture_key or self.id

    def tex_for_face(self, face: str, rotation: int = 0) -> str:
        if face == "top":
            return ""
        _PER_FACE = {"north": self.tex_n, "south": self.tex_s,
                      "east": self.tex_e, "west": self.tex_w}
        per = _PER_FACE.get(face, "")
        if per:
            return per
        rot = rotation % 4
        if face == _ROT_FRONT[rot] and self.texture_front:
            return self.texture_front
        if face == _ROT_BACK[rot] and self.texture_back:
            return self.texture_back
        return self.wall_tex()

    def top_tex(self) -> str:
        return ""

    def has_directional_textures(self) -> bool:
        return bool(self.texture_front or self.texture_back
                     or self.tex_n or self.tex_s
                     or self.tex_e or self.tex_w)

    @property
    def face_textures(self) -> tuple:
        pairs: list[tuple[str, str]] = []
        if self.texture_front:
            pairs.append(("south", self.texture_front))
        if self.texture_back:
            pairs.append(("north", self.texture_back))
        return tuple(sorted(pairs))

    def face_tex_dict(self) -> dict[str, str]:
        return dict(self.face_textures)

    def has_face_overrides(self) -> bool:
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
