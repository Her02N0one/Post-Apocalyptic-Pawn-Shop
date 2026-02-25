"""core.zones.format — Binary zone format (.zone) constants.

Defines the file signature, version, chunk identifiers, and per-cell
collision bitmasks for the chunked binary level format.

File Layout
-----------
::

    ┌──────────────────────────────────────┐
    │  File Header (12 bytes)              │
    │    magic   : uint32  = 0x5A4F4E45    │  "ZONE" in ASCII
    │    version : uint16  = 1             │  format revision
    │    flags   : uint16  = 0             │  reserved
    │    width   : uint16                  │  grid columns
    │    height  : uint16                  │  grid rows
    ├──────────────────────────────────────┤
    │  Chunk[]                             │
    │  ┌────────────────────────────────┐  │
    │  │  chunk_id  : uint32            │  │  e.g. CHUNK_NAVI
    │  │  chunk_len : uint32            │  │  payload bytes
    │  │  payload   : uint8[chunk_len]  │  │
    │  └────────────────────────────────┘  │
    │  … repeated for each chunk …         │
    └──────────────────────────────────────┘

Chunk types are identified by 4-byte ASCII tags packed into uint32.
Readers skip unknown chunks using ``chunk_len``, so older loaders
can open newer files without crashing.

Chunk Roster (v1)
-----------------
* **NAVI** — Navigation/collision grid (per-cell bitmask).
* **ELEV** — Elevation data (floor/ceiling heights, per-cell floats).
* **RNDR** — Render/visual data (tile IDs, texture overrides,
  lighting, wall segments).
* **ENTY** — Entity spawn descriptors (prefab ID, position, properties).

Collision Bitmasks
------------------
Each cell in the NAVI chunk stores a ``uint16`` with independent flag
bits for wall state and per-edge blocking.  The per-edge flags let the
pathfinder know which directions are passable even when the cell itself
is "open" (e.g., a railing blocks north but allows south).

::

    Bit  0  SOLID           Cell is impassable (full wall / filled)
    Bit  1  BLOCK_NORTH     Blocks movement northward out of this cell
    Bit  2  BLOCK_SOUTH     Blocks movement southward
    Bit  3  BLOCK_EAST      Blocks movement eastward
    Bit  4  BLOCK_WEST      Blocks movement westward
    Bit  5  WATER           Cell contains water (swim/wade)
    Bit  6  HAZARD          Cell is hazardous (damage on entry)
    Bit  7  INTERIOR        Cell has a ceiling (interior zone)
    Bit  8  PLATFORM        Cell is a raised platform
    Bit  9  DOOR            Cell contains a door (togglable solid)
    Bit 10  PORTAL          Cell is a zone-transition trigger
    Bit 11  HALF_WALL       Cell is a short/half-height wall
    Bits 12-15              Reserved (future use)
"""

from __future__ import annotations

import struct


# ═══════════════════════════════════════════════════════════════════
#  File Signature & Version
# ═══════════════════════════════════════════════════════════════════

# "ZONE" in big-endian ASCII → 0x5A4F4E45
ZONE_MAGIC: int = 0x5A4F4E45

# Format revision — increment when the chunk layout changes in a
# backward-incompatible way.
ZONE_VERSION: int = 1


# ═══════════════════════════════════════════════════════════════════
#  Chunk Identifiers (4-byte ASCII tags packed as uint32 big-endian)
# ═══════════════════════════════════════════════════════════════════

def _tag(s: str) -> int:
    """Pack a 4-character ASCII string into a big-endian uint32."""
    assert len(s) == 4, f"Chunk tag must be exactly 4 chars, got {s!r}"
    return struct.unpack(">I", s.encode("ascii"))[0]


CHUNK_NAVI: int = _tag("NAVI")   # Navigation / collision grid
CHUNK_ELEV: int = _tag("ELEV")   # Elevation data (floor/ceiling heights)
CHUNK_RNDR: int = _tag("RNDR")   # Render / visual data (tiles, textures, lighting)
CHUNK_ENTY: int = _tag("ENTY")   # Entity spawn descriptors

# Future chunks (reserved tags — not yet implemented)
CHUNK_LGHT: int = _tag("LGHT")   # Point lights / dynamic light sources
CHUNK_SNDZ: int = _tag("SNDZ")   # Sound zone / ambient audio regions
CHUNK_META: int = _tag("META")   # Metadata (author, description, tags)
CHUNK_SCPT: int = _tag("SCPT")   # Script triggers / event wiring

# All known chunk tags for validation
KNOWN_CHUNKS: frozenset[int] = frozenset({
    CHUNK_NAVI, CHUNK_ELEV, CHUNK_RNDR, CHUNK_ENTY,
    CHUNK_LGHT, CHUNK_SNDZ, CHUNK_META, CHUNK_SCPT,
})

# Human-readable names for debugging
CHUNK_NAMES: dict[int, str] = {
    CHUNK_NAVI: "NAVI",
    CHUNK_ELEV: "ELEV",
    CHUNK_RNDR: "RNDR",
    CHUNK_ENTY: "ENTY",
    CHUNK_LGHT: "LGHT",
    CHUNK_SNDZ: "SNDZ",
    CHUNK_META: "META",
    CHUNK_SCPT: "SCPT",
}


# ═══════════════════════════════════════════════════════════════════
#  NAVI Chunk — Per-Cell Collision Bitmasks (uint16)
# ═══════════════════════════════════════════════════════════════════

NAV_SOLID:       int = 1 << 0    # 0x0001  Cell is fully impassable
NAV_BLOCK_NORTH: int = 1 << 1    # 0x0002  Blocks movement north
NAV_BLOCK_SOUTH: int = 1 << 2    # 0x0004  Blocks movement south
NAV_BLOCK_EAST:  int = 1 << 3    # 0x0008  Blocks movement east
NAV_BLOCK_WEST:  int = 1 << 4    # 0x0010  Blocks movement west
NAV_WATER:       int = 1 << 5    # 0x0020  Water cell (swim/wade)
NAV_HAZARD:      int = 1 << 6    # 0x0040  Damaging terrain
NAV_INTERIOR:    int = 1 << 7    # 0x0080  Has ceiling (interior)
NAV_PLATFORM:    int = 1 << 8    # 0x0100  Raised platform
NAV_DOOR:        int = 1 << 9    # 0x0200  Door (togglable solid)
NAV_PORTAL:      int = 1 << 10   # 0x0400  Zone-transition trigger
NAV_HALF_WALL:   int = 1 << 11   # 0x0800  Short/half-height wall

# Compound masks for convenience
NAV_BLOCK_ALL: int = (
    NAV_BLOCK_NORTH | NAV_BLOCK_SOUTH | NAV_BLOCK_EAST | NAV_BLOCK_WEST
)
NAV_PASSABLE: int = 0x0000       # Open, no flags — fully walkable


# ═══════════════════════════════════════════════════════════════════
#  Header Layout
# ═══════════════════════════════════════════════════════════════════

# struct format for the file header (12 bytes, big-endian):
#   magic(u32) + version(u16) + flags(u16) + width(u16) + height(u16)
HEADER_FMT: str = ">IHHHH"
HEADER_SIZE: int = struct.calcsize(HEADER_FMT)  # 12

# struct format for a chunk header (8 bytes, big-endian):
#   chunk_id(u32) + chunk_len(u32)
CHUNK_HEADER_FMT: str = ">II"
CHUNK_HEADER_SIZE: int = struct.calcsize(CHUNK_HEADER_FMT)  # 8


# ═══════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════

def chunk_name(tag: int) -> str:
    """Return the 4-character ASCII name for a chunk tag, or ``'????'``."""
    return CHUNK_NAMES.get(tag, "????")


def nav_flags_str(flags: int) -> str:
    """Return a human-readable string of active NAV flags."""
    names: list[str] = []
    _MAP = [
        (NAV_SOLID,       "SOLID"),
        (NAV_BLOCK_NORTH, "BLOCK_N"),
        (NAV_BLOCK_SOUTH, "BLOCK_S"),
        (NAV_BLOCK_EAST,  "BLOCK_E"),
        (NAV_BLOCK_WEST,  "BLOCK_W"),
        (NAV_WATER,       "WATER"),
        (NAV_HAZARD,      "HAZARD"),
        (NAV_INTERIOR,    "INTERIOR"),
        (NAV_PLATFORM,    "PLATFORM"),
        (NAV_DOOR,        "DOOR"),
        (NAV_PORTAL,      "PORTAL"),
        (NAV_HALF_WALL,   "HALF_WALL"),
    ]
    for bit, name in _MAP:
        if flags & bit:
            names.append(name)
    return "|".join(names) if names else "PASSABLE"
