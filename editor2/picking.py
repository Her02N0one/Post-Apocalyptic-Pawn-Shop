"""editor2/picking.py — Screen-to-world ray casting and cell/face picking."""

from __future__ import annotations

import enum
import math
from dataclasses import dataclass

from core.zones import Zone
from editor2.camera import Camera, FAR_CLIP
from editor2.mesh import compute_cell_boxes


# ── Face enum ─────────────────────────────────────────────────────


class Face(enum.Enum):
    """Identifies which face of a cell box was hit."""
    NORTH = 0
    SOUTH = 1
    EAST = 2
    WEST = 3
    TOP = 4
    BOT = 5
    GROUND = 6   # virtual: Y=0 ground plane

    @property
    def is_wall(self) -> bool:
        return self in (Face.NORTH, Face.SOUTH, Face.EAST, Face.WEST)

    @property
    def is_horizontal(self) -> bool:
        return self in (Face.TOP, Face.BOT, Face.GROUND)

    @property
    def face_tex_idx(self) -> int | None:
        """Index into zone.face_textures[r][c][i], or None for non-wall."""
        if self.is_wall:
            return self.value  # N=0, S=1, E=2, W=3
        return None


# ── Hit result ───────────────────────────────────────────────────


@dataclass()
class CellHit:
    """A ray hit on a cell box or the ground plane."""
    t: float        # ray parameter (distance along ray)
    col: int        # grid column (X)
    row: int        # grid row (Z)
    part: str       # "wall", "floor", "ceiling"
    face: Face      # which face was hit
    hit_y: float    # world-space Y at the hit point
    hit_x: float = 0.0   # world-space X at the hit point
    hit_z: float = 0.0   # world-space Z at the hit point


# ── Ray-AABB intersection ────────────────────────────────────────

_FACE_X = (Face.WEST, Face.EAST)
_FACE_Y = (Face.BOT, Face.TOP)
_FACE_Z = (Face.NORTH, Face.SOUTH)


def _ray_vs_aabb(
    ox: float, oy: float, oz: float,
    dx: float, dy: float, dz: float,
    x0: float, y0: float, z0: float,
    x1: float, y1: float, z1: float,
) -> tuple[float, Face] | None:
    """Slab intersection of ray with an AABB.

    Returns ``(t, face)`` for the nearest hit, or ``None``.
    When the origin is inside the box, returns the exit face.
    """
    tmin = 0.0
    tmax = FAR_CLIP
    face_in: Face | None = None
    face_out: Face | None = None

    # X slab
    if abs(dx) > 1e-10:
        t1 = (x0 - ox) / dx
        t2 = (x1 - ox) / dx
        if t1 <= t2:
            fn_in, fn_out = _FACE_X
        else:
            fn_in, fn_out = _FACE_X[1], _FACE_X[0]
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
            fn_in, fn_out = _FACE_Y
        else:
            fn_in, fn_out = _FACE_Y[1], _FACE_Y[0]
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
            fn_in, fn_out = _FACE_Z
        else:
            fn_in, fn_out = _FACE_Z[1], _FACE_Z[0]
            t1, t2 = t2, t1
        if t1 > tmin:
            tmin = t1; face_in = fn_in
        if t2 < tmax:
            tmax = t2; face_out = fn_out
        if tmin > tmax:
            return None
    elif oz < z0 or oz > z1:
        return None

    if tmin > 0.001:
        return (tmin, face_in)
    if tmax > 0.001:
        return (tmax, face_out)
    return None


# ── Screen → world ray ───────────────────────────────────────────


def screen_to_ray(
    sx: float, sy: float,
    vp_w: int, vp_h: int,
    camera: Camera,
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Convert a screen pixel to a world-space ray (origin, direction).

    *sx, sy* are pixel coords with (0,0) at top-left.
    Returns (origin, direction) where direction is normalised.
    """
    # NDC: [-1, 1]
    ndc_x = 2.0 * sx / vp_w - 1.0
    ndc_y = 1.0 - 2.0 * sy / vp_h  # flip Y

    # Undo perspective: direction in view space
    fov_rad = math.radians(75.0)
    half_tan = math.tan(fov_rad * 0.5)
    aspect = vp_w / vp_h if vp_h > 0 else 1.0
    view_x = ndc_x * half_tan * aspect
    view_y = ndc_y * half_tan

    # Camera basis vectors
    fx, fy, fz = camera.forward()
    rx, ry, rz = camera.right()
    # up = right × forward
    ux = ry * fz - rz * fy
    uy = rz * fx - rx * fz
    uz = rx * fy - ry * fx

    # World direction = forward + view_x * right + view_y * up
    dx = fx + view_x * rx + view_y * ux
    dy = fy + view_x * ry + view_y * uy
    dz = fz + view_x * rz + view_y * uz

    # Normalise
    length = math.sqrt(dx * dx + dy * dy + dz * dz)
    if length < 1e-12:
        dx, dy, dz = fx, fy, fz
    else:
        dx /= length; dy /= length; dz /= length

    return (camera.x, camera.y, camera.z), (dx, dy, dz)


# ── Floor-point pick (continuous world coords) ──────────────────


def pick_floor_point(
    sx: float, sy: float,
    vp_w: int, vp_h: int,
    camera: Camera,
    zone: Zone,
) -> tuple[float, float, float] | None:
    """Return *(world_x, world_z, floor_height)* where the cursor ray hits
    the floor plane.

    Unlike `pick_cell`, this returns **continuous** coordinates rather
    than integer cell indices, making it suitable for smooth entity
    placement.  Returns ``None`` when the ray misses the zone area.
    """
    (ox, oy, oz), (dx, dy, dz) = screen_to_ray(sx, sy, vp_w, vp_h, camera)
    if abs(dy) < 1e-10:
        return None
    # Intersect with Y = 0 to find approximate cell
    t0 = -oy / dy
    if t0 < 0.01:
        return None
    hx = ox + dx * t0
    hz = oz + dz * t0
    c = int(math.floor(hx))
    r = int(math.floor(hz))
    W, H = zone.width, zone.height
    if not (0 <= c < W and 0 <= r < H):
        return None
    fh = zone.floor_heights[r][c] if zone.floor_heights else 0.0
    # Re-intersect with Y = fh for accuracy on non-zero floors
    if abs(fh) > 0.001 and abs(dy) > 1e-10:
        t1 = (fh - oy) / dy
        if t1 > 0.01:
            hx = ox + dx * t1
            hz = oz + dz * t1
    return (hx, hz, fh)


# ── Main pick function ───────────────────────────────────────────

_SEARCH_RADIUS = 16


def pick_cell(
    sx: float, sy: float,
    vp_w: int, vp_h: int,
    camera: Camera,
    zone: Zone,
) -> CellHit | None:
    """Pick the nearest cell face under screen coordinate (sx, sy).

    Returns a `CellHit` or ``None`` if nothing was hit.
    """
    (ox, oy, oz), (dx, dy, dz) = screen_to_ray(sx, sy, vp_w, vp_h, camera)
    W, H = zone.width, zone.height

    best: CellHit | None = None

    # Ground-plane hit (Y = 0)
    if abs(dy) > 1e-10:
        t = -oy / dy
        if 0.01 < t < FAR_CLIP:
            hx = ox + dx * t
            hz = oz + dz * t
            c = int(math.floor(hx))
            r = int(math.floor(hz))
            if 0 <= c < W and 0 <= r < H:
                blocked = False
                for part, yb, yt in compute_cell_boxes(zone, r, c):
                    tb = _ray_vs_aabb(ox, oy, oz, dx, dy, dz,
                                      float(c), yb, float(r),
                                      c + 1.0, yt, r + 1.0)
                    if tb and tb[0] < t:
                        blocked = True
                        if best is None or tb[0] < best.t:
                            best = CellHit(tb[0], c, r, part, tb[1],
                                           oy + tb[0] * dy,
                                           ox + tb[0] * dx,
                                           oz + tb[0] * dz)
                if not blocked and (best is None or t < best.t):
                    best = CellHit(t, c, r, "floor", Face.GROUND, 0.0,
                                   hx, hz)

    # Scan cells near camera
    cam_c = int(math.floor(ox))
    cam_r = int(math.floor(oz))
    r_lo = max(0, cam_r - _SEARCH_RADIUS)
    r_hi = min(H, cam_r + _SEARCH_RADIUS)
    c_lo = max(0, cam_c - _SEARCH_RADIUS)
    c_hi = min(W, cam_c + _SEARCH_RADIUS)

    for r in range(r_lo, r_hi):
        for c in range(c_lo, c_hi):
            for part, yb, yt in compute_cell_boxes(zone, r, c):
                result = _ray_vs_aabb(
                    ox, oy, oz, dx, dy, dz,
                    float(c), yb, float(r),
                    c + 1.0, yt, r + 1.0,
                )
                if result is None:
                    continue
                t_hit, face = result
                if best is None or t_hit < best.t:
                    best = CellHit(t_hit, c, r, part, face,
                                   oy + t_hit * dy,
                                   ox + t_hit * dx,
                                   oz + t_hit * dz)

    return best
