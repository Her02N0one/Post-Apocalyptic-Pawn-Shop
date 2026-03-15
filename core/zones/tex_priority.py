"""core.zones.tex_priority — Canonical texture resolution rules.

This is the **single source of truth** for the wall / floor / ceiling
texture priority chain.  Both the zone compiler (``compiler.py``) and
the runtime renderer (``ray_renderer.py``) delegate to these functions
instead of reimplementing the logic.

Wall Priority (highest → lowest)
--------------------------------
1. ``face_textures[r][c][face_idx]``  — per-cell per-face override
2. ``wall_textures[r][c]``           — per-cell wall override
3. ``TileDef.tex_for_face(face, rotation)`` — tile definition default

Floor/Ceiling Priority
----------------------
1. ``floor_textures[r][c]`` / ``ceil_textures[r][c]``
2. ``TileDef.wall_tex()`` (tile definition's base texture)

Step-Wall Defaults
------------------
Floor step faces default to ``"dirt"`` if unset.
Ceiling step faces default to ``"concrete"`` if unset.
"""

from __future__ import annotations

from typing import Protocol


# ═══════════════════════════════════════════════════════════════════
#  Face constants
# ═══════════════════════════════════════════════════════════════════

FACE_NAMES: tuple[str, ...] = ("north", "south", "east", "west")
FACE_INDEX: dict[str, int] = {n: i for i, n in enumerate(FACE_NAMES)}

FLOOR_STEP_DEFAULT: str = "dirt"
CEIL_STEP_DEFAULT: str = "concrete"


# ═══════════════════════════════════════════════════════════════════
#  Grid accessor protocol
# ═══════════════════════════════════════════════════════════════════

class _ZoneLike(Protocol):
    """Minimal interface used by the resolution functions.

    Satisfied by both :class:`Zone` and any test stub that has the
    right attribute names.
    """
    tiles: list[list[str]]
    rotations: list[list[int]]
    wall_textures: list[list[str]]
    face_textures: list[list[list[str]]]
    floor_textures: list[list[str]]
    ceil_textures: list[list[str]]


# ═══════════════════════════════════════════════════════════════════
#  Resolution functions
# ═══════════════════════════════════════════════════════════════════

def _safe_get_2d(grid: list[list], r: int, c: int, default=""):
    """Read ``grid[r][c]`` with bounds checking."""
    if grid and r < len(grid):
        row = grid[r]
        if c < len(row):
            return row[c]
    return default


def _safe_get_face(grid: list[list[list[str]]], r: int, c: int,
                   face_idx: int) -> str:
    """Read ``grid[r][c][face_idx]`` with bounds checking."""
    if grid and r < len(grid):
        row = grid[r]
        if c < len(row):
            faces = row[c]
            if face_idx < len(faces):
                return faces[face_idx]
    return ""


def resolve_wall_texture(
    zone: _ZoneLike,
    r: int, c: int,
    face: str,
    tdef,
    rotation: int,
) -> str:
    """Return the **texture key** for a wall face after applying
    the full priority chain.

    Parameters
    ----------
    zone : _ZoneLike
        Zone (or zone-like) object with grid attributes.
    r, c : int
        Cell row / column.
    face : str
        ``"north"`` | ``"south"`` | ``"east"`` | ``"west"``.
    tdef
        TileDef for the cell (from ``tile_def()``).
    rotation : int
        Rotation value for the cell.

    Returns
    -------
    str
        The resolved texture key.  May be ``""`` if nothing resolves.
    """
    face_idx = FACE_INDEX.get(face, 0)

    # 1. Per-cell per-face override
    ft = _safe_get_face(zone.face_textures, r, c, face_idx)
    if ft:
        return ft

    # 2. Per-cell wall override
    wt = _safe_get_2d(zone.wall_textures, r, c)
    if wt:
        return wt

    # 3. Tile definition default
    return tdef.tex_for_face(face, rotation)


def resolve_floor_ceil_texture(
    zone: _ZoneLike,
    r: int, c: int,
    is_ceil: bool,
    tdef=None,
) -> str:
    """Return the **texture key** for a floor or ceiling surface.

    Parameters
    ----------
    zone : _ZoneLike
        Zone (or zone-like) object.
    r, c : int
        Cell coordinates.
    is_ceil : bool
        ``True`` for ceiling, ``False`` for floor.
    tdef
        Optional TileDef for fallback.  If ``None``, only the
        zone per-cell grid is consulted.

    Returns
    -------
    str
        Resolved texture key.
    """
    grid = zone.ceil_textures if is_ceil else zone.floor_textures
    val = _safe_get_2d(grid, r, c)
    if val:
        return val

    if tdef is not None:
        return tdef.wall_tex()

    return ""
