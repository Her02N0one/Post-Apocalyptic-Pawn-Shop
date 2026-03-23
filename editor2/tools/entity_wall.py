"""editor2/tools/entity_wall.py — Wall-entity placement helpers.

Factored out of ``entity.py`` to keep per-module size manageable.
"""

from __future__ import annotations

from core.zones import Zone
from editor2.picking import CellHit, Face

# ── Wall entity catalogue ─────────────────────────────────────────

# Entity types that should be placed flush against walls.
# This is a name-based heuristic; entities with collider.wall_mount
# or wall_sprite components could also be detected.
_WALL_ENTITY_TYPES = frozenset({
    "wall_lamp", "vent_grate",
})

# Map Face enum → (wall_face string, normal_dx, normal_dz)
_FACE_TO_WALL: dict[Face, tuple[str, float, float]] = {
    Face.NORTH: ("south", 0.0, -1.0),   # hit the N face of cell → entity faces south
    Face.SOUTH: ("north", 0.0, 1.0),    # hit the S face of cell → entity faces north
    Face.EAST:  ("west", -1.0, 0.0),    # hit the E face of cell → entity faces west
    Face.WEST:  ("east", 1.0, 0.0),     # hit the W face of cell → entity faces east
}


def _is_wall_entity_type(etype: str) -> bool:
    """Heuristic: is this entity type typically mounted on a wall?"""
    if etype in _WALL_ENTITY_TYPES:
        return True
    from core.entity_defs import get_entity_def
    edef = get_entity_def(etype)
    if edef is None:
        return False
    return any(cn == "wall_sprite" for cn, _ in edef.components)


def _wall_face_from_hit(hit: CellHit | None) -> str | None:
    """If *hit* is on a wall face, return the wall_face string for the entity."""
    if hit is None:
        return None
    entry = _FACE_TO_WALL.get(hit.face)
    return entry[0] if entry else None


def _wall_position(
    hit: CellHit, zone: Zone,
    snap: float = 0.0,
    entity_height: float = 0.0,
) -> tuple[float, float, float, str]:
    """Compute (world_x, world_z, wall_height, wall_face) for an entity
    placed on the wall face described by *hit*.

    The entity is pushed flush against the wall surface with a small
    offset so it doesn't z-fight.  The position along the wall and the
    vertical height come from the actual hit-point coordinates so the
    user can place the entity wherever they click on the wall.

    ``wall_height`` is the entity **base** (bottom edge), matching the
    convention used by all 2.5D renderers.  The click point (hit_y) is
    treated as the visual centre, so half of *entity_height* is
    subtracted to get the base.

    *snap* — if > 0, the parallel-to-wall coordinate and height are
    snapped to the nearest multiple.
    """
    import math

    r, c = hit.row, hit.col
    face_info = _FACE_TO_WALL[hit.face]
    wall_face = face_info[0]

    offset = 0.01  # tiny standoff from wall

    # Perpendicular axis → pushed just OUTSIDE the wall face so the
    # entity (and its ghost overlay) sits in front of the wall, not
    # hidden behind the geometry.
    # Parallel axis → taken from the hit point.
    if hit.face == Face.NORTH:
        # North face is at z = r; push outward (toward lower z).
        wz = float(r) - offset
        wx = hit.hit_x
    elif hit.face == Face.SOUTH:
        # South face is at z = r+1; push outward (toward higher z).
        wz = float(r + 1) + offset
        wx = hit.hit_x
    elif hit.face == Face.EAST:
        # East face is at x = c+1; push outward (toward higher x).
        wx = float(c + 1) + offset
        wz = hit.hit_z
    else:  # WEST
        # West face is at x = c; push outward (toward lower x).
        wx = float(c) - offset
        wz = hit.hit_z

    # Clamp the parallel-to-wall coordinate within cell bounds.
    # The perpendicular axis is already set by the face position.
    if hit.face in (Face.NORTH, Face.SOUTH):
        wx = max(float(c) + 0.01, min(wx, float(c + 1) - 0.01))
    else:
        wz = max(float(r) + 0.01, min(wz, float(r + 1) - 0.01))

    # Height: click Y is the visual centre; subtract half entity height
    # to get the base (bottom edge), which is what 2.5D renderers expect.
    wall_h = hit.hit_y - entity_height * 0.5

    # Apply snap
    if snap > 0.0 and snap < 1.0:
        wx = round(wx / snap) * snap
        wz = round(wz / snap) * snap
        wall_h = round(wall_h / snap) * snap
    elif snap >= 1.0:
        # Cell-centre snap
        wx = math.floor(wx) + 0.5
        wz = math.floor(wz) + 0.5

    return (wx, wz, wall_h, wall_face)


def _infer_wall_face(hit: CellHit) -> Face | None:
    """For a hit on the TOP/BOT of a wall cell, infer the nearest wall face.

    When the camera is above a wall looking down, ``pick_cell`` returns
    ``Face.TOP``.  Wall-placement logic requires a cardinal face
    (N/S/E/W).  This function determines which wall face the user
    likely intends by finding the nearest cell edge from the hit point.

    Returns a wall ``Face`` for wall-face hits, the inferred face for
    TOP/BOT hits on wall parts, or ``None`` for non-wall parts.
    """
    if hit.face.is_wall:
        return hit.face
    if hit.part != "wall":
        return None
    # Position within cell [0, 1]
    local_x = hit.hit_x - hit.col
    local_z = hit.hit_z - hit.row
    # Clamp in case floating-point puts us slightly outside
    local_x = max(0.0, min(1.0, local_x))
    local_z = max(0.0, min(1.0, local_z))
    # Distance from each edge
    d_west = local_x           # west edge = low X
    d_east = 1.0 - local_x    # east edge = high X
    d_south = local_z          # south edge = low Z (row boundary)
    d_north = 1.0 - local_z   # north edge = high Z (row + 1 boundary)
    min_d = min(d_west, d_east, d_south, d_north)
    if min_d == d_north:
        return Face.NORTH
    if min_d == d_south:
        return Face.SOUTH
    if min_d == d_east:
        return Face.EAST
    return Face.WEST


def _wall_hit_for_placement(hit: CellHit) -> CellHit | None:
    """Return a CellHit suitable for ``_wall_position``.

    If the hit is already on a wall face, returns it unchanged.
    If it is on the TOP/BOT of a wall part, returns a copy with
    the face set to the nearest cardinal direction.
    Returns ``None`` for non-wall parts.
    """
    face = _infer_wall_face(hit)
    if face is None:
        return None
    if face == hit.face:
        return hit
    from dataclasses import replace as _dc_replace
    return _dc_replace(hit, face=face)
