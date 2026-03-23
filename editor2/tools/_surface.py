"""editor2/tools/_surface.py — Shared surface-detection helpers.

Common logic for hover-highlight computation, face-quad generation,
and surface classification used by multiple tools (sculpt, paint,
erase, entity, etc.).
"""

from __future__ import annotations

from core.zones import Zone
from editor2.mesh import compute_cell_boxes
from editor2.picking import CellHit, Face


# ── Hover Y ───────────────────────────────────────────────────────

def hover_y_for_hit(hit: CellHit, zone: Zone) -> float:
    """Return the best Y coordinate for a hover overlay on *hit*.

    For non-wall parts, returns the top of the matching cell box.
    For wall parts, returns ``hit.hit_y`` (the actual ray intersection
    height) so the overlay sits at the visible surface rather than
    inside the wall mesh.
    """
    if hit.part == "wall":
        return hit.hit_y
    boxes = compute_cell_boxes(zone, hit.row, hit.col)
    for part, yb, yt in boxes:
        if part == hit.part:
            return yt
    return 0.0


def floor_height_at(zone: Zone, r: int, c: int) -> float:
    """Safe accessor for zone floor height at (r, c)."""
    if zone.floor_heights and 0 <= r < zone.height and 0 <= c < zone.width:
        return zone.floor_heights[r][c]
    return 0.0


# ── Face quad ─────────────────────────────────────────────────────

def compute_face_quad(
    hit: CellHit, zone: Zone,
) -> list[tuple[float, float, float]] | None:
    """Compute the 4 corners of the highlighted face for *hit*.

    Returns a list of four ``(x, y, z)`` corners suitable for
    ``quad_to_tris``, or ``None`` if the face is unrecognised.
    The quad is pushed outward by a small epsilon so it doesn't
    z-fight with the underlying geometry.
    """
    c, r = hit.col, hit.row
    x0, z0 = float(c), float(r)
    x1, z1 = x0 + 1.0, z0 + 1.0

    # Get this cell's box extents for the hit part
    boxes = compute_cell_boxes(zone, r, c)
    y0, y1 = 0.0, 1.0
    for part, yb, yt in boxes:
        if part == hit.part:
            y0, y1 = yb, yt
            break

    f = hit.face
    # Epsilon push outward so overlay sits in front of the face
    E = 0.002

    if f == Face.TOP or f == Face.GROUND:
        y = y1 + E
        return [(x0, y, z0), (x1, y, z0), (x1, y, z1), (x0, y, z1)]
    elif f == Face.BOT:
        y = y0 - E
        return [(x0, y, z0), (x0, y, z1), (x1, y, z1), (x1, y, z0)]
    elif f == Face.NORTH:
        z = z0 - E
        return [(x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z)]
    elif f == Face.SOUTH:
        z = z1 + E
        return [(x1, y0, z), (x0, y0, z), (x0, y1, z), (x1, y1, z)]
    elif f == Face.WEST:
        x = x0 - E
        return [(x, y0, z1), (x, y0, z0), (x, y1, z0), (x, y1, z1)]
    elif f == Face.EAST:
        x = x1 + E
        return [(x, y0, z0), (x, y0, z1), (x, y1, z1), (x, y1, z0)]
    return None


# ── Surface classification ────────────────────────────────────────

def face_texture_index(face: Face) -> int | None:
    """Return the ``face_textures[r][c][i]`` index for a wall face.

    Uses the canonical ordering: N=0, S=1, E=2, W=3.
    Returns ``None`` for non-wall faces.
    """
    return face.face_tex_idx


def sample_face_texture(
    zone: Zone, r: int, c: int, face: Face,
) -> str:
    """Sample the texture at (r, c) on *face*, checking face_textures
    first, then wall_textures, then returning ``""``."""
    fi = face_texture_index(face)
    if fi is not None:
        if (zone.face_textures and r < len(zone.face_textures)
                and c < len(zone.face_textures[r])
                and zone.face_textures[r][c][fi]):
            return zone.face_textures[r][c][fi]
    if zone.wall_textures and r < len(zone.wall_textures):
        return zone.wall_textures[r][c]
    return ""


def sample_surface_texture(
    zone: Zone, hit: CellHit,
) -> str:
    """Return the texture at the surface identified by *hit*.

    Handles floor (TOP/GROUND), ceiling (BOT), and wall faces with
    the standard fallback chain.
    """
    r, c = hit.row, hit.col
    f = hit.face
    if f == Face.TOP or f == Face.GROUND:
        return zone.floor_textures[r][c] if zone.floor_textures else ""
    if f == Face.BOT:
        return zone.ceil_textures[r][c] if zone.ceil_textures else ""
    if f.is_wall:
        return sample_face_texture(zone, r, c, f)
    return ""
