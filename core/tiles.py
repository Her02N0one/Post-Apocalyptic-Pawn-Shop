"""core/tiles.py — Flag-based tile registry.

Every tile ID maps to a ``TileDef`` that carries a human-readable name,
a display colour, and a set of **binary flags** that systems query at
runtime instead of hard-coding tile IDs.

    from core.tiles import TILE_REGISTRY, TF

    td = TILE_REGISTRY[6]
    if td.flags & TF.SOLID:
        ...   # block movement

Flags are ``IntFlag`` so they compose naturally with ``|`` and ``&``.

Portal / teleporter behaviour is *not* a flag — it comes from the
portal list in the zone JSON.  Any tile can visually sit at a portal
coordinate (door, gateway, archway, etc.).

Design Goals
~~~~~~~~~~~~
* Adding a new tile only requires adding one ``TileDef`` entry.
* Systems never hard-code tile IDs — they ask *"does this tile have
  the SOLID flag?"* instead of *"is this tile_id == 6?"*.
* Forward-compatible with future flags (CLIMBABLE, DESTRUCTIBLE,
  SLOW, ELEVATED, …) and first-person render hints.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntFlag


# ═══════════════════════════════════════════════════════════════════
#  Tile Flags
# ═══════════════════════════════════════════════════════════════════

class TF(IntFlag):
    """Binary property flags for tiles.

    Compose with ``|``::

        TF.SOLID | TF.WALL   # blocks movement AND renders in raycaster
    """

    NONE        = 0
    SOLID       = 1 << 0   # Blocks entity movement (physics collision)
    WALL        = 1 << 1   # Full-height wall column in the raycaster
    TRANSPARENT = 1 << 2   # Raycaster renders this wall see-through
    LIQUID      = 1 << 3   # Water / swamp — future: slow, swimming
    FARMLAND    = 1 << 4   # Can be tilled / planted on
    HALF_WALL   = 1 << 5   # Half-height wall (counters, railings)
    PLATFORM    = 1 << 6   # Elevated platform — shows top surface texture
    # ── Reserved for future ──
    # CLIMBABLE = 1 << 7
    # SLOW      = 1 << 8
    # DESTRUCTIBLE = 1 << 9


# ═══════════════════════════════════════════════════════════════════
#  Tile Definition
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class TileDef:
    """Immutable description of a tile type."""

    id: int
    name: str
    color: tuple[int, int, int]
    flags: TF = TF.NONE

    # Key into the texture generator table (see systems/textures.py).
    # ``None`` means "use the generic noise generator".
    texture_key: str | None = None
    height_scale: float = 1.0   # raycaster wall height (1.0 = full, 0.5 = half)

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


# ═══════════════════════════════════════════════════════════════════
#  Built-in Tile Catalogue
# ═══════════════════════════════════════════════════════════════════
#
# Each entry is  TileDef(id, name, color, flags, texture_key).
# The ``id`` is the integer stored in the 2-D tile grid.
#
# To add a new tile, just append a new TileDef here.

_BUILTIN_TILES: list[TileDef] = [
    # --  id  name           colour              flags                     tex key
    TileDef(0,  "Void",       (40, 40, 40),       TF.SOLID | TF.WALL,      "void"),
    TileDef(1,  "Grass",      (50, 80, 40),       TF.NONE,                  "grass"),
    TileDef(2,  "Dirt",       (80, 70, 50),       TF.NONE,                  "dirt"),
    TileDef(3,  "Stone",      (60, 60, 70),       TF.NONE,                  "stone"),
    TileDef(4,  "Water",      (30, 60, 90),       TF.LIQUID,                "water"),
    TileDef(5,  "Wood Floor", (70, 50, 35),       TF.NONE,                  "wood"),
    TileDef(6,  "Wall",       (90, 90, 90),       TF.SOLID | TF.WALL,      "wall"),
    TileDef(7,  "Sand",       (140, 130, 90),     TF.NONE,                  "sand"),
    TileDef(8,  "Rubble",     (100, 85, 70),      TF.NONE,                  "rubble"),
    TileDef(9,  "Door",       (180, 20, 180),     TF.WALL,                  "door"),
    TileDef(10, "Window",     (100, 140, 180),    TF.SOLID | TF.WALL | TF.TRANSPARENT, "window"),
    TileDef(11, "Farmland",   (65, 50, 30),       TF.FARMLAND,              "dirt"),
    TileDef(12, "Gateway",    (120, 100, 80),     TF.WALL,                  "gateway"),
    TileDef(13, "Concrete",   (130, 130, 130),    TF.NONE,                  "concrete"),
    TileDef(14, "Tile Floor", (160, 140, 120),    TF.NONE,                  "tile_floor"),
    TileDef(15, "Metal Wall", (80, 85, 95),       TF.SOLID | TF.WALL,      "metal"),
    TileDef(16, "Half Wall",  (100, 95, 85),      TF.SOLID | TF.WALL | TF.HALF_WALL, "half_wall", 0.5),
    TileDef(17, "Low Wall",   (90, 85, 75),        TF.SOLID | TF.WALL | TF.HALF_WALL, "low_wall",  0.35),
    TileDef(18, "Pillar",     (110, 105, 100),     TF.SOLID | TF.WALL,      "pillar"),
    TileDef(19, "Counter Top",(120, 100, 70),      TF.SOLID | TF.WALL | TF.HALF_WALL | TF.PLATFORM, "counter_top", 0.35),
    TileDef(20, "Railing",    (70, 65, 55),        TF.SOLID | TF.WALL | TF.HALF_WALL | TF.PLATFORM, "railing",   0.4),
    TileDef(21, "Carpet",     (120, 50, 50),       TF.NONE,                  "carpet"),
    TileDef(22, "Brick Wall", (130, 75, 55),       TF.SOLID | TF.WALL,      "brick_wall"),
    TileDef(23, "Wood Panel", (100, 75, 50),       TF.SOLID | TF.WALL,      "wood_panel"),
    TileDef(24, "Cracked Fl.",(95, 90, 80),        TF.NONE,                  "cracked_floor"),
    TileDef(25, "Stone Floor",(125, 120, 115),     TF.NONE,                  "stone_floor"),
    TileDef(26, "Shelf Wall", (95, 80, 60),        TF.SOLID | TF.WALL,      "shelf_wall"),
    # ── Platforms (elevated surfaces with visible tops) ──
    TileDef(27, "Stone Plat.",(140, 135, 125),     TF.SOLID | TF.WALL | TF.HALF_WALL | TF.PLATFORM, "stone_platform", 0.45),
    TileDef(28, "Wood Plat.", (110, 80, 50),       TF.SOLID | TF.WALL | TF.HALF_WALL | TF.PLATFORM, "wood_platform",  0.35),
    TileDef(29, "Metal Plat.",(100, 105, 115),     TF.SOLID | TF.WALL | TF.HALF_WALL | TF.PLATFORM, "metal_platform", 0.4),
    TileDef(30, "Crate Stack",(130, 100, 60),      TF.SOLID | TF.WALL | TF.HALF_WALL | TF.PLATFORM, "crate_stack",    0.55),
    # ── Furniture ─────────────────────────────────────────────
    TileDef(31, "Table",       (100, 75, 50),      TF.SOLID | TF.WALL | TF.HALF_WALL | TF.PLATFORM, "table",         0.35),
    # ── Quarter-height (hs ≈ 0.25) ───────────────────────────────
    TileDef(32, "Curb",        (110, 110, 105),    TF.WALL | TF.HALF_WALL,                            "curb",          0.2),
    TileDef(33, "Stool",       (90, 70, 45),       TF.SOLID | TF.WALL | TF.HALF_WALL | TF.PLATFORM,  "stool",         0.25),
    TileDef(34, "Step",        (95, 95, 100),      TF.WALL | TF.HALF_WALL,                            "step",          0.15),
]


# ═══════════════════════════════════════════════════════════════════
#  Registry (dict: tile_id → TileDef)
# ═══════════════════════════════════════════════════════════════════

TILE_REGISTRY: dict[int, TileDef] = {td.id: td for td in _BUILTIN_TILES}

# Convenience: unknown tiles fall back to a safe default
_FALLBACK = TileDef(-1, "Unknown", (120, 120, 120), TF.NONE)


def tile_def(tile_id: int) -> TileDef:
    """Look up a tile definition, returning a safe fallback for unknowns."""
    return TILE_REGISTRY.get(tile_id, _FALLBACK)


# ── Derived lookup tables (for hot-path systems) ─────────────────

def solid_tile_ids() -> frozenset[int]:
    """Return the set of all tile IDs that have the SOLID flag."""
    return frozenset(tid for tid, td in TILE_REGISTRY.items() if td.solid)

def wall_tile_ids() -> frozenset[int]:
    """Return the set of all tile IDs that have the WALL flag."""
    return frozenset(tid for tid, td in TILE_REGISTRY.items() if td.wall)

def half_wall_tile_ids() -> frozenset[int]:
    """Return the set of all tile IDs that have the HALF_WALL flag."""
    return frozenset(tid for tid, td in TILE_REGISTRY.items() if td.half_wall)

def platform_tile_ids() -> frozenset[int]:
    """Return the set of all tile IDs that have the PLATFORM flag."""
    return frozenset(tid for tid, td in TILE_REGISTRY.items() if td.platform)


def door_tile_ids() -> frozenset[int]:
    """Return tile IDs that are WALL but not SOLID (doors, gateways)."""
    return frozenset(
        tid for tid, td in TILE_REGISTRY.items()
        if td.wall and not td.solid
    )


# Pre-computed sets for tight loops (rebuilt if you modify the registry
# at runtime — but that's rare).
SOLID_IDS: frozenset[int] = solid_tile_ids()
WALL_IDS: frozenset[int] = wall_tile_ids()
HALF_WALL_IDS: frozenset[int] = half_wall_tile_ids()
PLATFORM_IDS: frozenset[int] = platform_tile_ids()
DOOR_IDS: frozenset[int] = door_tile_ids()


# ── Backwards-compatible colour dict ─────────────────────────────────
# Consumed by renderers and the editor palette.

TILE_COLORS: dict[int, tuple[int, int, int]] = {
    td.id: td.color for td in TILE_REGISTRY.values()
}

TILE_NAMES: dict[int, str] = {
    td.id: td.name for td in TILE_REGISTRY.values()
}
