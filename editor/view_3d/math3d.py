"""editor/view_3d/math3d.py — 3D projection and matrix helpers."""

from __future__ import annotations

import math

# ─── Clip planes / field of view ──────────────────────────────────
NEAR_CLIP = 0.05
FAR_CLIP  = 80.0
FOV_DEG   = 75.0


def _perspective(fov_rad: float, aspect: float, near: float, far: float):
    """Return a 4x4 perspective projection matrix as a flat list[16]."""
    f = 1.0 / math.tan(fov_rad * 0.5)
    nf = 1.0 / (near - far)
    return [
        f / aspect, 0,  0,                    0,
        0,          f,  0,                    0,
        0,          0,  (far + near) * nf,   -1,
        0,          0,  2 * far * near * nf,  0,
    ]


def _mat4_mul(a: list[float], b: list[float]) -> list[float]:
    """Multiply two column-major 4x4 matrices."""
    r = [0.0] * 16
    for row in range(4):
        for col in range(4):
            s = 0.0
            for k in range(4):
                s += a[row + k * 4] * b[k + col * 4]
            r[row + col * 4] = s
    return r


def _build_view_matrix(eye: tuple, yaw: float, pitch: float) -> list[float]:
    """Column-major 4x4 view matrix from eye + yaw/pitch."""
    cp = math.cos(pitch)
    sp = math.sin(pitch)
    cy = math.cos(yaw)
    sy = math.sin(yaw)

    fx = -cp * sy
    fy = sp
    fz = cp * cy

    rx = -cy
    ry = 0.0
    rz = -sy

    ux = ry * fz - rz * fy
    uy = rz * fx - rx * fz
    uz = rx * fy - ry * fx

    ex, ey, ez = eye
    return [
        rx,        ux,      -fx,        0.0,
        ry,        uy,      -fy,        0.0,
        rz,        uz,      -fz,        0.0,
        -(rx*ex + ry*ey + rz*ez),
        -(ux*ex + uy*ey + uz*ez),
        (fx*ex + fy*ey + fz*ez),
        1.0,
    ]


def _project(
    vp: list[float],
    x: float, y: float, z: float,
    hw: float, hh: float,
) -> tuple[float, float, float] | None:
    """Project a world point to screen coords.  None if behind camera."""
    cx = vp[0]*x + vp[4]*y + vp[8]*z  + vp[12]
    cy = vp[1]*x + vp[5]*y + vp[9]*z  + vp[13]
    cw = vp[3]*x + vp[7]*y + vp[11]*z + vp[15]
    if cw < NEAR_CLIP:
        return None
    inv_w = 1.0 / cw
    sx = hw + cx * inv_w * hw
    sy = hh - cy * inv_w * hh
    return (sx, sy, cw)


def _project_line(
    vp: list[float],
    x0: float, y0: float, z0: float,
    x1: float, y1: float, z1: float,
    hw: float, hh: float,
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """Project a 3D line segment with near-plane clipping."""
    cw0 = vp[3]*x0 + vp[7]*y0 + vp[11]*z0 + vp[15]
    cw1 = vp[3]*x1 + vp[7]*y1 + vp[11]*z1 + vp[15]
    if cw0 < NEAR_CLIP and cw1 < NEAR_CLIP:
        return None
    if cw0 < NEAR_CLIP or cw1 < NEAR_CLIP:
        t = (NEAR_CLIP - cw0) / (cw1 - cw0) if abs(cw1 - cw0) > 1e-10 else 0.5
        t = max(0.0, min(1.0, t))
        nx = x0 + t * (x1 - x0)
        ny = y0 + t * (y1 - y0)
        nz = z0 + t * (z1 - z0)
        if cw0 < NEAR_CLIP:
            x0, y0, z0 = nx, ny, nz
        else:
            x1, y1, z1 = nx, ny, nz
    p0 = _project(vp, x0, y0, z0, hw, hh)
    p1 = _project(vp, x1, y1, z1, hw, hh)
    if p0 is None or p1 is None:
        return None
    return ((p0[0], p0[1]), (p1[0], p1[1]))


def _project_poly(
    vp: list[float],
    corners: list[tuple[float, float, float]],
    hw: float, hh: float,
) -> list[tuple[int, int]] | None:
    """Project a 3D polygon with Sutherland-Hodgman near-plane clipping.

    Returns integer screen-space points, or *None* if entirely behind camera.
    Unlike per-vertex ``_project`` (which discards faces when any vertex
    is behind the camera), this clips the polygon against the near plane
    so partially-visible faces render correctly.
    """
    # Compute clip-space w for each corner
    cws = [vp[3] * x + vp[7] * y + vp[11] * z + vp[15]
           for x, y, z in corners]

    # All behind near plane → skip
    if all(cw < NEAR_CLIP for cw in cws):
        return None

    # All in front → project directly (fast path)
    if all(cw >= NEAR_CLIP for cw in cws):
        result = []
        for x, y, z in corners:
            p = _project(vp, x, y, z, hw, hh)
            if p is None:          # pragma: no cover – shouldn't happen
                return None
            result.append((int(p[0]), int(p[1])))
        return result

    # Sutherland-Hodgman clip against near plane (keep cw >= NEAR_CLIP)
    clipped: list[tuple[float, float, float]] = []
    n = len(corners)
    for i in range(n):
        cur_pt = corners[i]
        prev_pt = corners[i - 1]
        cur_cw = cws[i]
        prev_cw = cws[i - 1]
        cur_in = cur_cw >= NEAR_CLIP
        prev_in = prev_cw >= NEAR_CLIP

        if cur_in:
            if not prev_in:
                denom = cur_cw - prev_cw
                t = ((NEAR_CLIP - prev_cw) / denom
                     if abs(denom) > 1e-10 else 0.5)
                t = max(0.0, min(1.0, t))
                clipped.append((
                    prev_pt[0] + t * (cur_pt[0] - prev_pt[0]),
                    prev_pt[1] + t * (cur_pt[1] - prev_pt[1]),
                    prev_pt[2] + t * (cur_pt[2] - prev_pt[2]),
                ))
            clipped.append(cur_pt)
        elif prev_in:
            denom = cur_cw - prev_cw
            t = ((NEAR_CLIP - prev_cw) / denom
                 if abs(denom) > 1e-10 else 0.5)
            t = max(0.0, min(1.0, t))
            clipped.append((
                prev_pt[0] + t * (cur_pt[0] - prev_pt[0]),
                prev_pt[1] + t * (cur_pt[1] - prev_pt[1]),
                prev_pt[2] + t * (cur_pt[2] - prev_pt[2]),
            ))

    if len(clipped) < 3:
        return None

    result = []
    for x, y, z in clipped:
        p = _project(vp, x, y, z, hw, hh)
        if p is None:          # pragma: no cover
            return None
        result.append((int(p[0]), int(p[1])))
    return result
