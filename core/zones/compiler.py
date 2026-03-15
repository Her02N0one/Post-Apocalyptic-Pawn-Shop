"""core/zone_compiler.py — Compile a Zone object into flat numpy arrays.

Converts the nested Python lists in a :class:`~core.zones.Zone` into
compact, C-friendly numpy arrays suitable for the binary ``.zone``
format or for direct consumption by the C raycaster extension.

The returned :class:`CompiledZone` holds:

* **navi_grid** — ``uint16 [H, W]``  per-cell NAV bitmask.
* **floor_z**   — ``float32 [H, W]`` floor elevation.
* **ceil_z**    — ``float32 [H, W]`` ceiling elevation.
* **textures**  — ``uint16 [H, W, 6]`` texture IDs per face
  ``[Floor, Ceil, North, South, East, West]``.
* **light_levels** — ``float32 [H, W]`` spatial lighting.

String texture names are resolved via a :class:`~core.game_registry.GameRegistry`
(namespace ``"texture"``).  Unknown textures are auto-registered so the
registry stays in sync with what the zone actually references.

Usage
-----
::

    from core.zones import load_zone
    from core.game_registry import GameRegistry
    from core.zone_compiler import compile_zone_to_arrays

    zone = load_zone("pawn_shop")
    reg  = GameRegistry(["tile", "texture", "prefab"])
    compiled = compile_zone_to_arrays(zone, reg)

    print(compiled.navi_grid.shape)   # (H, W)
    print(compiled.textures.shape)    # (H, W, 6)
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from core.zones.game_registry import GameRegistry
from core.zones.zone import Zone
from core.zones.format import (
    NAV_SOLID,
    NAV_WATER,
    NAV_HAZARD,
    NAV_INTERIOR,
    NAV_PLATFORM,
    NAV_DOOR,
    NAV_PORTAL,
    NAV_HALF_WALL,
)
from core.tiles.types import TileType
from core.tiles.registry import tile_def
from core.zones.tex_priority import (
    resolve_wall_texture,
    resolve_floor_ceil_texture,
    FACE_NAMES as _TEX_FACE_NAMES,
)


# ═══════════════════════════════════════════════════════════════════
#  Constants
# ═══════════════════════════════════════════════════════════════════

# Cells with clearance (ceil - floor) below this are impassable.
HEAD_CLEARANCE: float = 0.4

# Ceiling heights at or above this value mean "open sky" (no ceiling).
SKY_HEIGHT: float = 10.0

# Texture face indices within the textures array (axis 2).
TEX_FLOOR: int = 0
TEX_CEIL:  int = 1
TEX_NORTH: int = 2
TEX_SOUTH: int = 3
TEX_EAST:  int = 4
TEX_WEST:  int = 5

# Empty-texture sentinel: ID 0 is always reserved for "no texture".
_NO_TEX_KEY = ""


# ═══════════════════════════════════════════════════════════════════
#  CompiledZone — result container
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class CompiledZone:
    """Immutable container for compiled zone arrays.

    Attributes
    ----------
    name : str
        Zone name (carried over from the source Zone).
    width : int
        Grid columns.
    height : int
        Grid rows.
    navi_grid : np.ndarray
        ``uint16 [H, W]`` — per-cell navigation bitmask.
    floor_z : np.ndarray
        ``float32 [H, W]`` — floor elevation per cell.
    ceil_z : np.ndarray
        ``float32 [H, W]`` — ceiling elevation per cell.
    textures : np.ndarray
        ``uint16 [H, W, 6]`` — texture registry IDs per face.
        Face order: ``[Floor, Ceil, North, South, East, West]``.
    light_levels : np.ndarray
        ``float32 [H, W]`` — spatial lighting (0.0–1.0).
    """

    name: str
    width: int
    height: int
    navi_grid: np.ndarray
    floor_z: np.ndarray
    ceil_z: np.ndarray
    textures: np.ndarray
    light_levels: np.ndarray


# ═══════════════════════════════════════════════════════════════════
#  Texture resolution helpers
# ═══════════════════════════════════════════════════════════════════

_FACE_NAMES = ("north", "south", "east", "west")
_FACE_INDICES = {
    "north": TEX_NORTH,
    "south": TEX_SOUTH,
    "east":  TEX_EAST,
    "west":  TEX_WEST,
}


def _resolve_tex(name: str, tex_ns) -> int:
    """Register and return the uint16 ID for a texture name.

    Empty strings map to ID 0 (the no-texture sentinel).
    """
    if not name:
        return 0
    uid = tex_ns.to_int(name)
    if uid == -1:
        uid = tex_ns.register(name)
    return uid


def _resolve_wall_tex(
    r: int, c: int,
    face: str,
    zone: Zone,
    tdef,
    rotation: int,
    tex_ns,
) -> int:
    """Resolve a single wall-face texture with the full priority chain.

    Delegates to :func:`~core.zones.tex_priority.resolve_wall_texture`
    for the priority logic, then maps the resulting key to a uint16 ID.
    """
    key = resolve_wall_texture(zone, r, c, face, tdef, rotation)
    return _resolve_tex(key, tex_ns)


def _resolve_floor_ceil_tex(
    r: int, c: int,
    zone: Zone,
    is_ceil: bool,
    tex_ns,
) -> int:
    """Resolve floor or ceiling texture for a cell.

    Delegates to :func:`~core.zones.tex_priority.resolve_floor_ceil_texture`
    for the priority logic, then maps the resulting key to a uint16 ID.
    """
    tile_id = zone.tiles[r][c] if (r < len(zone.tiles) and c < len(zone.tiles[r])) else ""
    tdef = tile_def(tile_id)
    key = resolve_floor_ceil_texture(zone, r, c, is_ceil, tdef)
    return _resolve_tex(key, tex_ns)


# ═══════════════════════════════════════════════════════════════════
#  Navigation bitmask builder
# ═══════════════════════════════════════════════════════════════════

def _build_nav_flags(
    tdef,
    fh: float,
    ch: float,
    has_portal: bool,
) -> int:
    """Compute the NAV bitmask for a single cell."""
    flags = 0

    clearance = ch - fh

    # Solid: full wall, or floor >= ceiling, or insufficient clearance
    if tdef.wall and tdef.solid:
        flags |= NAV_SOLID
    elif clearance < HEAD_CLEARANCE:
        flags |= NAV_SOLID

    # Interior: has a real ceiling (below sky threshold)
    if ch < SKY_HEIGHT:
        flags |= NAV_INTERIOR

    # Tile-type flags
    if tdef.liquid:
        flags |= NAV_WATER
    if tdef.half_wall:
        flags |= NAV_HALF_WALL
    if tdef.platform:
        flags |= NAV_PLATFORM
    if tdef.type == TileType.DOOR:
        flags |= NAV_DOOR

    # Portal cells
    if has_portal:
        flags |= NAV_PORTAL

    return flags


# ═══════════════════════════════════════════════════════════════════
#  Main compiler
# ═══════════════════════════════════════════════════════════════════

def compile_zone_to_arrays(
    zone: Zone,
    registry: GameRegistry,
) -> CompiledZone:
    """Compile a Zone into flat numpy arrays.

    All string texture names are resolved through (and auto-registered
    into) the ``"texture"`` namespace of *registry*.  ID ``0`` is
    reserved as the "no texture" sentinel and is registered as ``""``.

    Parameters
    ----------
    zone : Zone
        Source zone loaded via :func:`core.zones.load_zone`.
    registry : GameRegistry
        Game-wide asset registry.  The ``"texture"`` namespace will be
        populated with every texture referenced by the zone.

    Returns
    -------
    CompiledZone
        Frozen dataclass holding the compiled arrays.

    Examples
    --------
    >>> from core.zones import load_zone
    >>> from core.game_registry import GameRegistry
    >>> reg = GameRegistry(["tile", "texture"])
    >>> cz = compile_zone_to_arrays(load_zone("pawn_shop"), reg)
    >>> cz.navi_grid.dtype
    dtype('uint16')
    """
    H, W = zone.height, zone.width

    # Ensure the "texture" namespace exists and reserve ID 0 for
    # the empty-string sentinel.
    tex_ns = registry.namespace("texture")
    if _NO_TEX_KEY not in tex_ns:
        tex_ns.register(_NO_TEX_KEY)  # always ID 0

    # ── Pre-compute portal set ────────────────────────────────────
    # Build a set of (row, col) cells that contain a portal.
    portal_cells: set[tuple[int, int]] = set()
    for portal in zone.portals:
        for tile_rc in portal.tiles:
            portal_cells.add((int(tile_rc[0]), int(tile_rc[1])))

    # ── Allocate output arrays ────────────────────────────────────
    navi_grid    = np.zeros((H, W), dtype=np.uint16)
    floor_z      = np.zeros((H, W), dtype=np.float32)
    ceil_z       = np.zeros((H, W), dtype=np.float32)
    textures     = np.zeros((H, W, 6), dtype=np.uint16)
    light_levels = np.ones((H, W), dtype=np.float32)  # default full bright

    # ── Fill arrays cell-by-cell ──────────────────────────────────
    for r in range(H):
        for c in range(W):
            # --- Tile definition ---
            tile_id = zone.tiles[r][c] if (r < len(zone.tiles) and
                                            c < len(zone.tiles[r])) else "void"
            tdef = tile_def(tile_id)
            rotation = (zone.rotations[r][c]
                        if zone.rotations and r < len(zone.rotations)
                        and c < len(zone.rotations[r])
                        else 0)

            # --- Heights ---
            fh = (zone.floor_heights[r][c]
                  if zone.floor_heights and r < len(zone.floor_heights)
                  and c < len(zone.floor_heights[r])
                  else 0.0)
            ch = (zone.ceil_heights[r][c]
                  if zone.ceil_heights and r < len(zone.ceil_heights)
                  and c < len(zone.ceil_heights[r])
                  else SKY_HEIGHT)

            floor_z[r, c] = fh
            ceil_z[r, c] = ch

            # --- Navigation ---
            has_portal = (r, c) in portal_cells
            navi_grid[r, c] = _build_nav_flags(tdef, fh, ch, has_portal)

            # --- Textures ---
            # Floor & ceiling
            textures[r, c, TEX_FLOOR] = _resolve_floor_ceil_tex(
                r, c, zone, is_ceil=False, tex_ns=tex_ns)
            textures[r, c, TEX_CEIL] = _resolve_floor_ceil_tex(
                r, c, zone, is_ceil=True, tex_ns=tex_ns)

            # Wall faces (N, S, E, W)
            for face in _FACE_NAMES:
                idx = _FACE_INDICES[face]
                textures[r, c, idx] = _resolve_wall_tex(
                    r, c, face, zone, tdef, rotation, tex_ns)

            # --- Lighting ---
            if zone.light_levels and r < len(zone.light_levels):
                row = zone.light_levels[r]
                if c < len(row):
                    light_levels[r, c] = float(row[c])

    return CompiledZone(
        name=zone.name,
        width=W,
        height=H,
        navi_grid=navi_grid,
        floor_z=floor_z,
        ceil_z=ceil_z,
        textures=textures,
        light_levels=light_levels,
    )
