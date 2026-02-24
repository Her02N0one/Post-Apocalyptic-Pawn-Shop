"""editor/view_3d/picking.py — Ray-AABB intersection + hit result."""

from __future__ import annotations

from dataclasses import dataclass

from editor.view_3d.math3d import FAR_CLIP

# ─── Face name constants ──────────────────────────────────────────
_FACE_NAMES_X = ("west", "east")
_FACE_NAMES_Y = ("bot",  "top")
_FACE_NAMES_Z = ("north", "south")


def _ray_vs_aabb(
    ox: float, oy: float, oz: float,
    dx: float, dy: float, dz: float,
    x0: float, y0: float, z0: float,
    x1: float, y1: float, z1: float,
) -> tuple[float, str] | None:
    """Intersect ray (origin, direction) with an AABB.

    Returns (t, face_name) for the nearest hit, or None.
    face_name: 'west','east','bot','top','north','south'.

    When the ray origin is inside the box, returns the exit face
    so that step-wall faces can be picked from within extended boxes.
    """
    tmin = 0.0
    tmax = FAR_CLIP
    face_in = ""
    face_out = ""

    # X slab
    if abs(dx) > 1e-10:
        t1 = (x0 - ox) / dx
        t2 = (x1 - ox) / dx
        if t1 <= t2:
            fn_in = _FACE_NAMES_X[0]    # west
            fn_out = _FACE_NAMES_X[1]   # east
        else:
            fn_in = _FACE_NAMES_X[1]    # east
            fn_out = _FACE_NAMES_X[0]   # west
            t1, t2 = t2, t1
        if t1 > tmin:
            tmin = t1; face_in = fn_in
        if t2 < tmax:
            tmax = t2; face_out = fn_out
        if tmin > tmax:
            return None
    elif ox < x0 or ox > x1:
        return None

    # Y slab
    if abs(dy) > 1e-10:
        t1 = (y0 - oy) / dy
        t2 = (y1 - oy) / dy
        if t1 <= t2:
            fn_in = _FACE_NAMES_Y[0]    # bot
            fn_out = _FACE_NAMES_Y[1]   # top
        else:
            fn_in = _FACE_NAMES_Y[1]    # top
            fn_out = _FACE_NAMES_Y[0]   # bot
            t1, t2 = t2, t1
        if t1 > tmin:
            tmin = t1; face_in = fn_in
        if t2 < tmax:
            tmax = t2; face_out = fn_out
        if tmin > tmax:
            return None
    elif oy < y0 or oy > y1:
        return None

    # Z slab
    if abs(dz) > 1e-10:
        t1 = (z0 - oz) / dz
        t2 = (z1 - oz) / dz
        if t1 <= t2:
            fn_in = _FACE_NAMES_Z[0]    # north
            fn_out = _FACE_NAMES_Z[1]   # south
        else:
            fn_in = _FACE_NAMES_Z[1]    # south
            fn_out = _FACE_NAMES_Z[0]   # north
            t1, t2 = t2, t1
        if t1 > tmin:
            tmin = t1; face_in = fn_in
        if t2 < tmax:
            tmax = t2; face_out = fn_out
        if tmin > tmax:
            return None
    elif oz < z0 or oz > z1:
        return None

    # Normal case: ray enters from outside
    if tmin > 0.001:
        return (tmin, face_in)
    # Origin inside box: return exit face so step walls can be picked
    if tmax > 0.001:
        return (tmax, face_out)
    return None


@dataclass
class _CellHit:
    """Result of a crosshair ray hitting a cell box or the ground plane."""
    t: float       # ray parameter (distance)
    col: int       # grid column
    row: int       # grid row
    part: str      # "wall", "floor", "ceiling"
    face: str      # "west","east","north","south","top","bot","ground"
    hit_y: float = 0.0  # world-space Y coordinate of the hit point
