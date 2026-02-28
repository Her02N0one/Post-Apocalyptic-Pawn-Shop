"""editor/view_3d/primitives.py — Low-level 3D drawing helpers."""

from __future__ import annotations

import math

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
        wireframe: bool = False,
    ) -> None:
        """Draw a filled, face-shaded box with wireframe edges.

        *face_colors* -- optional list of 6 RGB tuples in ``_FACE_DEFS``
        order (top, bot, north, south, west, east).
        If *wireframe* is True only edges are drawn (no filled faces).
        """
        if wireframe:
            ec = edge_color or base_color
            self._box(surface, vp, hw, hh,
                      x0, y0, z0, x1, y1, z1, ec, edge_width)
            return

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

    # ── Rotated box (yaw around centre) ──────────────────────────

    def _filled_rotated_box(
        self, surface: pygame.Surface, vp: list[float],
        hw: float, hh: float,
        cx: float, cz: float,
        w: float, h: float, d: float,
        base_y: float, yaw: float,
        base_color: tuple[int, ...],
        edge_color: tuple[int, ...] | None = None,
        edge_width: int = 1,
        alpha: int = 255,
        face_colors: list[tuple[int, int, int]] | None = None,
        wireframe: bool = False,
    ) -> None:
        """Draw a filled box rotated by *yaw* radians around its centre.

        *cx, cz* -- world-space centre (X, Z).
        *w, d*   -- half-extents along local X, Z before rotation.
        *h*      -- full height.
        *base_y* -- world Y of the bottom face.
        """
        cos_y = math.cos(yaw)
        sin_y = math.sin(yaw)
        hw2, hd2 = w * 0.5, d * 0.5
        top_y = base_y + h

        # Local corners (X, Z) relative to centre before rotation.
        local = [
            (-hw2, -hd2), ( hw2, -hd2),
            ( hw2,  hd2), (-hw2,  hd2),
        ]
        # Rotate and translate into world (X, Z), producing 8 corners
        # with bottom (y=base_y) and top (y=top_y).
        corners: list[tuple[float, float, float]] = []
        for lx, lz in local:
            wx = cx + lx * cos_y - lz * sin_y
            wz = cz + lx * sin_y + lz * cos_y
            corners.append((wx, base_y, wz))
        for lx, lz in local:
            wx = cx + lx * cos_y - lz * sin_y
            wz = cz + lx * sin_y + lz * cos_y
            corners.append((wx, top_y, wz))

        if wireframe:
            L = self._line3d
            ec = edge_color or base_color
            for i in range(4):
                j = (i + 1) % 4
                L(surface, vp, hw, hh, *corners[i], *corners[j], ec, edge_width)
                L(surface, vp, hw, hh, *corners[i+4], *corners[j+4], ec, edge_width)
                L(surface, vp, hw, hh, *corners[i], *corners[i+4], ec, edge_width)
            return

        cam = (self.cam_x, self.cam_y, self.cam_z)
        sw2, sh2 = int(hw * 2), int(hh * 2)
        use_alpha = alpha < 255

        for indices, normal, brightness in _FACE_DEFS:
            # Rotate normal by yaw (only X and Z components).
            nx = normal[0] * cos_y - normal[2] * sin_y
            ny = normal[1]
            nz = normal[0] * sin_y + normal[2] * cos_y
            # Face centre for back-face culling.
            fc_pts = [corners[i] for i in indices]
            fcx = sum(p[0] for p in fc_pts) * 0.25
            fcy = sum(p[1] for p in fc_pts) * 0.25
            fcz = sum(p[2] for p in fc_pts) * 0.25
            dx = cam[0] - fcx
            dy = cam[1] - fcy
            dz = cam[2] - fcz
            if dx * nx + dy * ny + dz * nz <= 0:
                continue
            poly = _project_poly(vp, fc_pts, hw, hh)
            if poly is None:
                continue
            xs = [p[0] for p in poly]
            ys = [p[1] for p in poly]
            if max(xs) < -50 or min(xs) > sw2 + 50:
                continue
            if max(ys) < -50 or min(ys) > sh2 + 50:
                continue
            fi = _FACE_DEFS.index((indices, normal, brightness))
            fc = face_colors[fi] if face_colors else base_color
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
            L = self._line3d
            for i in range(4):
                j = (i + 1) % 4
                L(surface, vp, hw, hh, *corners[i], *corners[j], edge_color, edge_width)
                L(surface, vp, hw, hh, *corners[i+4], *corners[j+4], edge_color, edge_width)
                L(surface, vp, hw, hh, *corners[i], *corners[i+4], edge_color, edge_width)
