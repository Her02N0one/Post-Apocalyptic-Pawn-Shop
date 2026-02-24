"""editor/view_3d/primitives.py — Low-level 3D drawing helpers."""

from __future__ import annotations

import pygame

from editor.view_3d.math3d import _project, _project_line, _project_poly
from editor.view_3d.constants import _FACE_DEFS


class DrawPrimitivesMixin:
    """_line3d, _box, _filled_box — pure projection + pygame.draw."""

    def _line3d(
        self, surface: pygame.Surface, vp: list[float],
        hw: float, hh: float,
        x0: float, y0: float, z0: float,
        x1: float, y1: float, z1: float,
        color: tuple, width: int = 1,
    ) -> None:
        pts = _project_line(vp, x0, y0, z0, x1, y1, z1, hw, hh)
        if pts is None:
            return
        (sx0, sy0), (sx1, sy1) = pts
        sw2, sh2 = int(hw * 2), int(hh * 2)
        if (sx0 < -200 and sx1 < -200) or (sx0 > sw2+200 and sx1 > sw2+200):
            return
        if (sy0 < -200 and sy1 < -200) or (sy0 > sh2+200 and sy1 > sh2+200):
            return
        try:
            pygame.draw.line(surface, color,
                             (int(sx0), int(sy0)),
                             (int(sx1), int(sy1)), width)
        except (OverflowError, ValueError):
            pass

    def _box(
        self, surface: pygame.Surface, vp: list[float],
        hw: float, hh: float,
        x0: float, y0: float, z0: float,
        x1: float, y1: float, z1: float,
        color: tuple, width: int = 1,
    ) -> None:
        L = self._line3d
        L(surface, vp, hw, hh, x0,y0,z0, x1,y0,z0, color, width)
        L(surface, vp, hw, hh, x1,y0,z0, x1,y0,z1, color, width)
        L(surface, vp, hw, hh, x1,y0,z1, x0,y0,z1, color, width)
        L(surface, vp, hw, hh, x0,y0,z1, x0,y0,z0, color, width)
        L(surface, vp, hw, hh, x0,y1,z0, x1,y1,z0, color, width)
        L(surface, vp, hw, hh, x1,y1,z0, x1,y1,z1, color, width)
        L(surface, vp, hw, hh, x1,y1,z1, x0,y1,z1, color, width)
        L(surface, vp, hw, hh, x0,y1,z1, x0,y1,z0, color, width)
        L(surface, vp, hw, hh, x0,y0,z0, x0,y1,z0, color, width)
        L(surface, vp, hw, hh, x1,y0,z0, x1,y1,z0, color, width)
        L(surface, vp, hw, hh, x1,y0,z1, x1,y1,z1, color, width)
        L(surface, vp, hw, hh, x0,y0,z1, x0,y1,z1, color, width)

    def _filled_box(
        self, surface: pygame.Surface, vp: list[float],
        hw: float, hh: float,
        x0: float, y0: float, z0: float,
        x1: float, y1: float, z1: float,
        base_color: tuple[int, ...],
        edge_color: tuple[int, ...] | None = None,
        edge_width: int = 1,
        alpha: int = 255,
        face_colors: list[tuple[int, int, int]] | None = None,
    ) -> None:
        """Draw a filled, face-shaded box with wireframe edges.

        *face_colors* -- optional list of 6 RGB tuples in ``_FACE_DEFS``
        order (top, bot, north, south, west, east).
        """
        corners = [
            (x0, y0, z0), (x1, y0, z0),
            (x1, y0, z1), (x0, y0, z1),
            (x0, y1, z0), (x1, y1, z0),
            (x1, y1, z1), (x0, y1, z1),
        ]

        cam = (self.cam_x, self.cam_y, self.cam_z)
        bcx = (x0 + x1) * 0.5
        bcy = (y0 + y1) * 0.5
        bcz = (z0 + z1) * 0.5
        hsx = (x1 - x0) * 0.5
        hsy = (y1 - y0) * 0.5
        hsz = (z1 - z0) * 0.5

        use_alpha = alpha < 255
        sw2, sh2 = int(hw * 2), int(hh * 2)

        for fi_box, (indices, normal, brightness) in enumerate(_FACE_DEFS):
            nx, ny, nz = normal
            fcx = bcx + nx * hsx
            fcy = bcy + ny * hsy
            fcz = bcz + nz * hsz
            dx = cam[0] - fcx
            dy = cam[1] - fcy
            dz = cam[2] - fcz
            if dx * nx + dy * ny + dz * nz <= 0:
                continue
            face_corners = [corners[i] for i in indices]
            poly = _project_poly(vp, face_corners, hw, hh)
            if poly is None:
                continue
            xs = [p[0] for p in poly]
            ys = [p[1] for p in poly]
            if max(xs) < -50 or min(xs) > sw2 + 50:
                continue
            if max(ys) < -50 or min(ys) > sh2 + 50:
                continue
            fc = face_colors[fi_box] if face_colors else base_color
            r = min(255, int(fc[0] * brightness))
            g = min(255, int(fc[1] * brightness))
            b = min(255, int(fc[2] * brightness))
            try:
                if use_alpha:
                    min_x = max(0, min(xs))
                    min_y = max(0, min(ys))
                    max_x = min(sw2, max(xs))
                    max_y = min(sh2, max(ys))
                    tw = max_x - min_x + 1
                    th = max_y - min_y + 1
                    if tw > 0 and th > 0:
                        tmp = pygame.Surface((tw, th), pygame.SRCALPHA)
                        off = [(px - min_x, py - min_y) for px, py in poly]
                        pygame.draw.polygon(tmp, (r, g, b, alpha), off)
                        surface.blit(tmp, (min_x, min_y))
                else:
                    pygame.draw.polygon(surface, (r, g, b), poly)
            except (ValueError, OverflowError):
                pass

        if edge_color is not None:
            self._box(surface, vp, hw, hh,
                      x0, y0, z0, x1, y1, z1, edge_color, edge_width)
