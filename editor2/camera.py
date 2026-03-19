"""editor2/camera.py — FPS camera with projection and view matrices."""

from __future__ import annotations

import math

import numpy as np

FOV_DEG   = 75.0
NEAR_CLIP = 0.05
FAR_CLIP  = 80.0

MOVE_SPEED  = 4.0
SPRINT_MULT = 2.5
MOUSE_SENS  = 0.003


class Camera:
    """FPS camera with WASD + mouse look."""

    def __init__(self) -> None:
        self.x = 5.0
        self.y = 1.5
        self.z = 5.0
        self.yaw = 0.0
        self.pitch = 0.0

    def forward(self) -> tuple[float, float, float]:
        cp = math.cos(self.pitch)
        return (-cp * math.sin(self.yaw),
                math.sin(self.pitch),
                cp * math.cos(self.yaw))

    def right(self) -> tuple[float, float, float]:
        return (-math.cos(self.yaw), 0.0, -math.sin(self.yaw))

    def view_matrix(self) -> np.ndarray:
        """Column-major 4x4 view matrix."""
        cp = math.cos(self.pitch)
        sp = math.sin(self.pitch)
        cy = math.cos(self.yaw)
        sy = math.sin(self.yaw)

        fx = -cp * sy
        fy = sp
        fz = cp * cy

        rx = -cy
        ry = 0.0
        rz = -sy

        ux = ry * fz - rz * fy
        uy = rz * fx - rx * fz
        uz = rx * fy - ry * fx

        ex, ey, ez = self.x, self.y, self.z
        return np.array([
            rx,        ux,      -fx,        0.0,
            ry,        uy,      -fy,        0.0,
            rz,        uz,      -fz,        0.0,
            -(rx*ex + ry*ey + rz*ez),
            -(ux*ex + uy*ey + uz*ez),
            (fx*ex + fy*ey + fz*ez),
            1.0,
        ], dtype=np.float32)

    def projection_matrix(self, aspect: float) -> np.ndarray:
        """Column-major 4x4 perspective projection."""
        fov_rad = math.radians(FOV_DEG)
        f = 1.0 / math.tan(fov_rad * 0.5)
        nf = 1.0 / (NEAR_CLIP - FAR_CLIP)
        return np.array([
            f / aspect, 0, 0, 0,
            0, f, 0, 0,
            0, 0, (FAR_CLIP + NEAR_CLIP) * nf, -1,
            0, 0, 2 * FAR_CLIP * NEAR_CLIP * nf, 0,
        ], dtype=np.float32)
