"""editor/view_3d.py — 3D wireframe zone editor.

Renders the zone as a true 3D wireframe scene with free-fly camera,
cell selection, and property editing.  Designed to be embedded in
ray_demo.py, sharing the same Zone object and swapping with the
2.5D raycaster via Tab.

Coordinate system (matches the raycaster):
    X = tile column (east+)
    Z = tile row (south+)          (Z replaces the raycaster's Y coordinate)
    Y = altitude (up+)

A tile at grid (col, row) occupies the box:
    X: [col, col+1]
    Z: [row, row+1]
    Y: [floor_height, ceil_height]
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any

import pygame

from core.tiles import TILE_REGISTRY, tile_def, TILE_COLORS
from core.zones import Zone, OverlayWall
from core.paths import ZONES_DIR


# ─── Colours ──────────────────────────────────────────────────────
COL_GRID       = (40, 40, 50)
COL_WALL       = (180, 60, 60)
COL_WALL_SEL   = (255, 100, 100)
COL_FLOOR_WIRE = (60, 80, 60)
COL_CEIL_WIRE  = (60, 60, 100)
COL_OVERLAY    = (80, 200, 220)
COL_OVERLAY_SEL= (120, 255, 255)
COL_SELECT     = (255, 220, 50)
COL_CROSSHAIR  = (200, 200, 200)
COL_AXIS_X     = (200, 50, 50)
COL_AXIS_Y     = (50, 200, 50)
COL_AXIS_Z     = (50, 50, 200)
COL_BG         = (18, 18, 24)
COL_HUD_BG     = (0, 0, 0, 180)
COL_HUD_TEXT   = (220, 220, 200)
COL_HUD_VAL    = (120, 220, 255)
COL_HUD_TITLE  = (255, 200, 80)

# ─── Config ───────────────────────────────────────────────────────
FLY_SPEED      = 6.0
FLY_SPRINT     = 2.5
FLY_SLOW       = 0.25
MOUSE_SENS     = 0.003
KB_TURN_SPEED  = 2.5
NEAR_CLIP      = 0.05
FAR_CLIP       = 80.0
FOV_DEG        = 75.0

EDIT_STEP_HEIGHT = 0.05
EDIT_STEP_LIGHT  = 0.05

# Selection types
SEL_NONE    = 0
SEL_CELL    = 1
SEL_OVERLAY = 2


# ═══════════════════════════════════════════════════════════════════
#  3D Math Helpers
# ═══════════════════════════════════════════════════════════════════

def _perspective(fov_rad: float, aspect: float, near: float, far: float):
    """Return a 4×4 perspective projection matrix as a flat list[16]."""
    f = 1.0 / math.tan(fov_rad * 0.5)
    nf = 1.0 / (near - far)
    return [
        f / aspect, 0,  0,                    0,
        0,          f,  0,                    0,
        0,          0,  (far + near) * nf,   -1,
        0,          0,  2 * far * near * nf,  0,
    ]


def _mat4_mul(a: list[float], b: list[float]) -> list[float]:
    """Multiply two column-major 4×4 matrices."""
    r = [0.0] * 16
    for row in range(4):
        for col in range(4):
            s = 0.0
            for k in range(4):
                s += a[row + k * 4] * b[k + col * 4]
            r[row + col * 4] = s
    return r


def _look_at(eye: tuple, yaw: float, pitch: float) -> list[float]:
    """Build a view matrix from eye position + yaw/pitch (radians)."""
    cp = math.cos(pitch)
    sp = math.sin(pitch)
    cy = math.cos(yaw)
    sy = math.sin(yaw)

    # Forward (into the screen = -Z in view space)
    fx, fy, fz = cp * sy, sp, cp * cy
    # Right
    rx, ry, rz = cy, 0.0, -sy
    # Up = right × forward
    ux = ry * fz - rz * fy
    uy = rz * fx - rx * fz
    uz = rx * fy - ry * fx

    ex, ey, ez = eye
    return [
        rx,  ux,  -fx,  0,
        ry,  uy,  -fy,  0,
        rz,  uz,  -fz,  0,
        -(rx*ex + ry*ey + rz*ez),
        -(ux*ex + uy*ey + uz*ez),
        -(-fx*ex + -fy*ey + -fz*ez),
        1,
    ]


def _project(
    vp: list[float],  # combined view·proj matrix (16 floats)
    x: float, y: float, z: float,
    hw: float, hh: float,
) -> tuple[float, float, float] | None:
    """Project a 3D point to screen coords.  Returns None if behind camera."""
    # Clip-space
    cx = vp[0]*x + vp[4]*y + vp[8]*z  + vp[12]
    cy = vp[1]*x + vp[5]*y + vp[9]*z  + vp[13]
    # cz = vp[2]*x + vp[6]*y + vp[10]*z + vp[14]   (unused)
    cw = vp[3]*x + vp[7]*y + vp[11]*z + vp[15]
    if cw < NEAR_CLIP:
        return None
    inv_w = 1.0 / cw
    sx = hw + cx * inv_w * hw
    sy = hh - cy * inv_w * hh    # flip Y (screen Y goes down)
    return (sx, sy, cw)


def _project_line(
    vp: list[float],
    x0: float, y0: float, z0: float,
    x1: float, y1: float, z1: float,
    hw: float, hh: float,
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """Project a 3D line segment; returns None if fully behind camera.
    Does basic near-plane clipping for one-behind cases."""
    # Full clip-space for both endpoints
    cw0 = vp[3]*x0 + vp[7]*y0 + vp[11]*z0 + vp[15]
    cw1 = vp[3]*x1 + vp[7]*y1 + vp[11]*z1 + vp[15]

    if cw0 < NEAR_CLIP and cw1 < NEAR_CLIP:
        return None

    # Clip to near plane if one endpoint is behind camera
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


# ═══════════════════════════════════════════════════════════════════
#  View Matrix — fixed version using proper 4×4 layout
# ═══════════════════════════════════════════════════════════════════

def _build_view_matrix(eye: tuple, yaw: float, pitch: float) -> list[float]:
    """Column-major 4×4 view matrix from eye + yaw/pitch."""
    cp = math.cos(pitch)
    sp = math.sin(pitch)
    cy = math.cos(yaw)
    sy = math.sin(yaw)

    # Camera basis vectors
    fx = cp * sy    # forward X
    fy = sp         # forward Y
    fz = cp * cy    # forward Z

    rx = cy         # right X
    ry = 0.0        # right Y
    rz = -sy        # right Z

    # Up = right × forward
    ux = ry * fz - rz * fy
    uy = rz * fx - rx * fz
    uz = rx * fy - ry * fx

    ex, ey, ez = eye
    # Column-major: mat[col*4 + row]
    return [
        # col 0    col 1    col 2       col 3
        rx,        ux,      -fx,        0.0,      # row 0
        ry,        uy,      -fy,        0.0,      # row 1
        rz,        uz,      -fz,        0.0,      # row 2
        -(rx*ex + ry*ey + rz*ez),                  # row 3, col 0
        -(ux*ex + uy*ey + uz*ez),                  # row 3, col 1
        (fx*ex + fy*ey + fz*ez),                   # row 3, col 2
        1.0,                                        # row 3, col 3
    ]


# ═══════════════════════════════════════════════════════════════════
#  Zone3DEditor
# ═══════════════════════════════════════════════════════════════════

class Zone3DEditor:
    """3D wireframe editor for zone geometry."""

    def __init__(self, zone: Zone) -> None:
        self.zone = zone
        # Camera state in world space (X=col east, Y=up, Z=row south)
        self.cam_x = zone.width / 2.0
        self.cam_y = 1.5    # start at eye level
        self.cam_z = zone.height / 2.0
        self.yaw   = 0.0    # radians (0 = looking along +Z)
        self.pitch = -0.3   # slight downward tilt

        # Selection
        self.sel_type: int = SEL_NONE
        self.sel_col: int = -1
        self.sel_row: int = -1
        self.sel_overlay_idx: int = -1
        self.sel_face: str = ""   # "floor", "ceil", "north", "south", "east", "west"

        # Display
        self.show_grid  = True
        self.show_walls = True
        self.show_floors = True
        self.show_ceilings = True
        self.show_overlays = True
        self.show_axes  = True
        self.show_hud   = True
        self.show_help  = False
        self.dirty = False         # zone modified since last save

        # Overlay creation mode
        self.placing_overlay = False
        self.overlay_start: tuple[float, float] | None = None

    def set_zone(self, zone: Zone) -> None:
        """Load a new zone into the editor."""
        self.zone = zone
        self.cam_x = zone.width / 2.0
        self.cam_y = 1.5
        self.cam_z = zone.height / 2.0
        self.sel_type = SEL_NONE
        self.dirty = False

    # ── Camera helpers ────────────────────────────────────────────

    def _forward(self) -> tuple[float, float, float]:
        cp = math.cos(self.pitch)
        return (cp * math.sin(self.yaw),
                math.sin(self.pitch),
                cp * math.cos(self.yaw))

    def _right(self) -> tuple[float, float, float]:
        return (math.cos(self.yaw), 0.0, -math.sin(self.yaw))

    # ── Input handling ────────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event) -> bool:
        """Process an event.  Returns True if consumed."""
        if event.type == pygame.KEYDOWN:
            return self._on_keydown(event)
        if event.type == pygame.MOUSEBUTTONDOWN:
            return self._on_click(event)
        return False

    def _on_keydown(self, event: pygame.event.Event) -> bool:
        key = event.key
        mod = pygame.key.get_mods()

        # Toggle layers
        if key == pygame.K_1: self.show_grid = not self.show_grid; return True
        if key == pygame.K_2: self.show_walls = not self.show_walls; return True
        if key == pygame.K_3: self.show_floors = not self.show_floors; return True
        if key == pygame.K_4: self.show_ceilings = not self.show_ceilings; return True
        if key == pygame.K_5: self.show_overlays = not self.show_overlays; return True
        if key == pygame.K_6: self.show_axes = not self.show_axes; return True
        if key == pygame.K_F1: self.show_help = not self.show_help; return True
        if key == pygame.K_h: self.show_hud = not self.show_hud; return True

        # Deselect
        if key == pygame.K_ESCAPE and self.sel_type != SEL_NONE:
            self.sel_type = SEL_NONE
            return True

        # ── Cell property editing (when cell selected) ────────
        if self.sel_type == SEL_CELL:
            r, c = self.sel_row, self.sel_col
            if 0 <= r < self.zone.height and 0 <= c < self.zone.width:
                if key == pygame.K_UP:
                    if mod & pygame.KMOD_SHIFT:
                        self.zone.ceil_heights[r][c] += EDIT_STEP_HEIGHT
                    else:
                        self.zone.floor_heights[r][c] += EDIT_STEP_HEIGHT
                    self.dirty = True; return True
                if key == pygame.K_DOWN:
                    if mod & pygame.KMOD_SHIFT:
                        self.zone.ceil_heights[r][c] -= EDIT_STEP_HEIGHT
                    else:
                        self.zone.floor_heights[r][c] -= EDIT_STEP_HEIGHT
                    self.dirty = True; return True
                if key == pygame.K_PAGEUP:
                    self.zone.light_levels[r][c] = min(
                        1.0, self.zone.light_levels[r][c] + EDIT_STEP_LIGHT)
                    self.dirty = True; return True
                if key == pygame.K_PAGEDOWN:
                    self.zone.light_levels[r][c] = max(
                        0.0, self.zone.light_levels[r][c] - EDIT_STEP_LIGHT)
                    self.dirty = True; return True

        # ── Overlay property editing (when overlay selected) ──
        if self.sel_type == SEL_OVERLAY:
            idx = self.sel_overlay_idx
            if 0 <= idx < len(self.zone.overlay_walls):
                ow = self.zone.overlay_walls[idx]
                if key == pygame.K_UP:
                    ow.height_scale += EDIT_STEP_HEIGHT
                    self.dirty = True; return True
                if key == pygame.K_DOWN:
                    ow.height_scale = max(0.05, ow.height_scale - EDIT_STEP_HEIGHT)
                    self.dirty = True; return True
                if key == pygame.K_DELETE or key == pygame.K_BACKSPACE:
                    self.zone.overlay_walls.pop(idx)
                    self.sel_type = SEL_NONE
                    self.dirty = True; return True

        # Save
        if key == pygame.K_s and (mod & pygame.KMOD_CTRL):
            self._save_zone()
            return True

        return False

    def _on_click(self, event: pygame.event.Event) -> bool:
        """Handle mouse clicks for selection."""
        if event.button == 1:   # left click = select
            # We'll do picking in update() using the screen-space crosshair
            self._do_pick(pygame.mouse.get_pos(),
                          pygame.display.get_surface().get_size())
            return True
        return False

    def update(self, dt: float, mouse_captured: bool) -> None:
        """Per-frame update: camera movement."""
        keys = pygame.key.get_pressed()
        speed = FLY_SPEED * dt
        if keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT]:
            speed *= FLY_SPRINT
        if keys[pygame.K_LCTRL] or keys[pygame.K_RCTRL]:
            speed *= FLY_SLOW

        # Mouse look
        if mouse_captured:
            mx, my = pygame.mouse.get_rel()
            self.yaw += mx * MOUSE_SENS
            self.pitch -= my * MOUSE_SENS
            self.pitch = max(-math.pi * 0.45, min(math.pi * 0.45, self.pitch))

        # Keyboard turn
        if keys[pygame.K_q]:
            self.yaw -= KB_TURN_SPEED * dt
        if keys[pygame.K_e]:
            self.yaw += KB_TURN_SPEED * dt

        fx, fy, fz = self._forward()
        rx, _, rz = self._right()

        # WASD — horizontal movement along forward/right
        if keys[pygame.K_w]:
            self.cam_x += fx * speed; self.cam_y += fy * speed; self.cam_z += fz * speed
        if keys[pygame.K_s]:
            self.cam_x -= fx * speed; self.cam_y -= fy * speed; self.cam_z -= fz * speed
        if keys[pygame.K_a]:
            self.cam_x -= rx * speed; self.cam_z -= rz * speed
        if keys[pygame.K_d]:
            self.cam_x += rx * speed; self.cam_z += rz * speed

        # Vertical fly (Space / C)
        if keys[pygame.K_SPACE]:
            self.cam_y += speed
        if keys[pygame.K_c]:
            self.cam_y -= speed

    # ── Rendering ─────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface) -> None:
        """Render the full 3D wireframe view."""
        surface.fill(COL_BG)
        sw, sh = surface.get_size()
        hw, hh = sw * 0.5, sh * 0.5

        # Build VP matrix
        aspect = sw / sh if sh > 0 else 1.0
        proj = _perspective(math.radians(FOV_DEG), aspect, NEAR_CLIP, FAR_CLIP)
        view = _build_view_matrix(
            (self.cam_x, self.cam_y, self.cam_z), self.yaw, self.pitch)
        vp = _mat4_mul(proj, view)

        zone = self.zone
        W, H = zone.width, zone.height

        # ── Ground grid ───────────────────────────────────────────
        if self.show_grid:
            for c in range(W + 1):
                self._draw_line3d(surface, vp, hw, hh,
                                  c, 0, 0, c, 0, H, COL_GRID)
            for r in range(H + 1):
                self._draw_line3d(surface, vp, hw, hh,
                                  0, 0, r, W, 0, r, COL_GRID)

        # ── Origin axes ──────────────────────────────────────────
        if self.show_axes:
            self._draw_line3d(surface, vp, hw, hh, 0,0,0, 2,0,0, COL_AXIS_X, 2)
            self._draw_line3d(surface, vp, hw, hh, 0,0,0, 0,2,0, COL_AXIS_Y, 2)
            self._draw_line3d(surface, vp, hw, hh, 0,0,0, 0,0,2, COL_AXIS_Z, 2)

        # ── Per-cell geometry ─────────────────────────────────────
        for r in range(H):
            for c in range(W):
                tid = zone.tiles[r][c]
                td = tile_def(tid)
                fh = zone.floor_heights[r][c] if zone.floor_heights else 0.0
                ch = zone.ceil_heights[r][c] if zone.ceil_heights else 1.0

                is_sel = (self.sel_type == SEL_CELL
                          and self.sel_row == r and self.sel_col == c)

                x0, z0 = float(c), float(r)
                x1, z1 = c + 1.0, r + 1.0

                if td.wall:
                    col = COL_WALL_SEL if is_sel else COL_WALL
                    w = 2 if is_sel else 1
                    if self.show_walls:
                        self._draw_box(surface, vp, hw, hh,
                                       x0, fh, z0, x1, ch, z1, col, w)
                else:
                    # Floor quad
                    if self.show_floors:
                        col_f = COL_SELECT if is_sel else COL_FLOOR_WIRE
                        w = 2 if is_sel else 1
                        self._draw_line3d(surface, vp, hw, hh,
                                          x0, fh, z0, x1, fh, z0, col_f, w)
                        self._draw_line3d(surface, vp, hw, hh,
                                          x1, fh, z0, x1, fh, z1, col_f, w)
                        self._draw_line3d(surface, vp, hw, hh,
                                          x1, fh, z1, x0, fh, z1, col_f, w)
                        self._draw_line3d(surface, vp, hw, hh,
                                          x0, fh, z1, x0, fh, z0, col_f, w)

                    # Ceiling quad (only if non-sky)
                    if self.show_ceilings and ch < 10.0:
                        col_c = COL_SELECT if is_sel else COL_CEIL_WIRE
                        self._draw_line3d(surface, vp, hw, hh,
                                          x0, ch, z0, x1, ch, z0, col_c, 1)
                        self._draw_line3d(surface, vp, hw, hh,
                                          x1, ch, z0, x1, ch, z1, col_c, 1)
                        self._draw_line3d(surface, vp, hw, hh,
                                          x1, ch, z1, x0, ch, z1, col_c, 1)
                        self._draw_line3d(surface, vp, hw, hh,
                                          x0, ch, z1, x0, ch, z0, col_c, 1)

                    # Vertical edges for selection highlight
                    if is_sel:
                        for cx_, cz_ in [(x0,z0),(x1,z0),(x1,z1),(x0,z1)]:
                            self._draw_line3d(surface, vp, hw, hh,
                                              cx_, fh, cz_, cx_, ch, cz_,
                                              COL_SELECT, 2)

        # ── Overlay walls ─────────────────────────────────────────
        if self.show_overlays:
            for idx, ow in enumerate(zone.overlay_walls):
                is_sel = (self.sel_type == SEL_OVERLAY
                          and self.sel_overlay_idx == idx)
                col = COL_OVERLAY_SEL if is_sel else COL_OVERLAY
                w = 2 if is_sel else 1

                # Get floor height at the midpoint for base height
                mx = (ow.x1 + ow.x2) * 0.5
                mz = (ow.y1 + ow.y2) * 0.5
                mi, mj = int(mx), int(mz)
                if 0 <= mj < H and 0 <= mi < W:
                    base = zone.floor_heights[mj][mi]
                else:
                    base = 0.0
                top = base + ow.height_scale

                # Four corners of the wall quad
                self._draw_line3d(surface, vp, hw, hh,
                                  ow.x1, base, ow.y1,
                                  ow.x2, base, ow.y2, col, w)
                self._draw_line3d(surface, vp, hw, hh,
                                  ow.x1, top, ow.y1,
                                  ow.x2, top, ow.y2, col, w)
                self._draw_line3d(surface, vp, hw, hh,
                                  ow.x1, base, ow.y1,
                                  ow.x1, top, ow.y1, col, w)
                self._draw_line3d(surface, vp, hw, hh,
                                  ow.x2, base, ow.y2,
                                  ow.x2, top, ow.y2, col, w)

                # Diagonal cross for visibility
                if is_sel:
                    self._draw_line3d(surface, vp, hw, hh,
                                      ow.x1, base, ow.y1,
                                      ow.x2, top, ow.y2, col, 1)
                    self._draw_line3d(surface, vp, hw, hh,
                                      ow.x2, base, ow.y2,
                                      ow.x1, top, ow.y1, col, 1)

        # ── Crosshair ────────────────────────────────────────────
        cx, cy = sw // 2, sh // 2
        pygame.draw.line(surface, COL_CROSSHAIR, (cx - 8, cy), (cx + 8, cy))
        pygame.draw.line(surface, COL_CROSSHAIR, (cx, cy - 8), (cx, cy + 8))

        # ── HUD ───────────────────────────────────────────────────
        if self.show_hud:
            self._draw_hud(surface)

        if self.show_help:
            self._draw_help(surface)

    # ── Drawing helpers ───────────────────────────────────────────

    def _draw_line3d(
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
        # Cull off-screen lines
        sw, sh = int(hw * 2), int(hh * 2)
        if (sx0 < -200 and sx1 < -200) or (sx0 > sw+200 and sx1 > sw+200):
            return
        if (sy0 < -200 and sy1 < -200) or (sy0 > sh+200 and sy1 > sh+200):
            return
        try:
            pygame.draw.line(surface, color,
                             (int(sx0), int(sy0)), (int(sx1), int(sy1)), width)
        except (OverflowError, ValueError):
            pass

    def _draw_box(
        self, surface: pygame.Surface, vp: list[float],
        hw: float, hh: float,
        x0: float, y0: float, z0: float,
        x1: float, y1: float, z1: float,
        color: tuple, width: int = 1,
    ) -> None:
        """Draw a wireframe axis-aligned box."""
        # Bottom face
        self._draw_line3d(surface, vp, hw, hh, x0,y0,z0, x1,y0,z0, color, width)
        self._draw_line3d(surface, vp, hw, hh, x1,y0,z0, x1,y0,z1, color, width)
        self._draw_line3d(surface, vp, hw, hh, x1,y0,z1, x0,y0,z1, color, width)
        self._draw_line3d(surface, vp, hw, hh, x0,y0,z1, x0,y0,z0, color, width)
        # Top face
        self._draw_line3d(surface, vp, hw, hh, x0,y1,z0, x1,y1,z0, color, width)
        self._draw_line3d(surface, vp, hw, hh, x1,y1,z0, x1,y1,z1, color, width)
        self._draw_line3d(surface, vp, hw, hh, x1,y1,z1, x0,y1,z1, color, width)
        self._draw_line3d(surface, vp, hw, hh, x0,y1,z1, x0,y1,z0, color, width)
        # Vertical edges
        self._draw_line3d(surface, vp, hw, hh, x0,y0,z0, x0,y1,z0, color, width)
        self._draw_line3d(surface, vp, hw, hh, x1,y0,z0, x1,y1,z0, color, width)
        self._draw_line3d(surface, vp, hw, hh, x1,y0,z1, x1,y1,z1, color, width)
        self._draw_line3d(surface, vp, hw, hh, x0,y0,z1, x0,y1,z1, color, width)

    # ── Picking ───────────────────────────────────────────────────

    def _do_pick(
        self, mouse_pos: tuple[int, int], screen_size: tuple[int, int]
    ) -> None:
        """Raycast from camera through screen center to find nearest cell."""
        sw, sh = screen_size
        hw, hh = sw * 0.5, sh * 0.5

        # Use screen center for crosshair picking
        # (mouse_pos ignored — we pick what the crosshair is aiming at)
        fx, fy, fz = self._forward()
        zone = self.zone
        W, H = zone.width, zone.height

        # Step along the ray and check grid cell intersections
        best_t = FAR_CLIP
        best_sel = SEL_NONE
        best_col = -1
        best_row = -1
        best_ov = -1

        # ── Check overlay walls first (free-form segments) ────
        for idx, ow in enumerate(zone.overlay_walls):
            t = self._ray_vs_overlay_quad(ow)
            if t is not None and t < best_t:
                best_t = t
                best_sel = SEL_OVERLAY
                best_ov = idx

        # ── Check grid cells (march along ray) ───────────────
        STEP = 0.1
        for i in range(int(FAR_CLIP / STEP)):
            t = i * STEP
            hx = self.cam_x + fx * t
            hy = self.cam_y + fy * t
            hz = self.cam_z + fz * t
            c = int(math.floor(hx))
            r = int(math.floor(hz))
            if 0 <= c < W and 0 <= r < H:
                fh = zone.floor_heights[r][c] if zone.floor_heights else 0.0
                ch = zone.ceil_heights[r][c] if zone.ceil_heights else 1.0
                # Is the sample point inside this cell's vertical extent?
                td = tile_def(zone.tiles[r][c])
                if td.wall:
                    if fh <= hy <= ch:
                        if t < best_t:
                            best_t = t
                            best_sel = SEL_CELL
                            best_col = c
                            best_row = r
                        break
                else:
                    # Floor/ceiling hit: check if near the surface
                    if abs(hy - fh) < 0.15:
                        if t < best_t:
                            best_t = t
                            best_sel = SEL_CELL
                            best_col = c
                            best_row = r
                        break
                    if ch < 10.0 and abs(hy - ch) < 0.15:
                        if t < best_t:
                            best_t = t
                            best_sel = SEL_CELL
                            best_col = c
                            best_row = r
                        break

        self.sel_type = best_sel
        if best_sel == SEL_CELL:
            self.sel_col = best_col
            self.sel_row = best_row
        elif best_sel == SEL_OVERLAY:
            self.sel_overlay_idx = best_ov

    def _ray_vs_overlay_quad(self, ow: OverlayWall) -> float | None:
        """Intersect the camera ray with an overlay wall quad."""
        fx, fy, fz = self._forward()
        # Overlay quad: vertical plane through (x1,y1)→(x2,y2) in XZ
        # Normal = perpendicular to segment direction in XZ, horizontal
        dx = ow.x2 - ow.x1
        dz = ow.y2 - ow.y1
        seg_len = math.sqrt(dx*dx + dz*dz)
        if seg_len < 1e-6:
            return None
        # Plane normal (horizontal): (-dz, 0, dx) normalized
        nx = -dz / seg_len
        nz = dx / seg_len

        # Ray: P = cam + t * forward
        denom = fx * nx + fz * nz
        if abs(denom) < 1e-10:
            return None
        # Distance from cam to plane
        t = ((ow.x1 - self.cam_x) * nx + (ow.y1 - self.cam_z) * nz) / denom
        if t < 0.05 or t > FAR_CLIP:
            return None

        # Hit point
        hx = self.cam_x + fx * t
        hy = self.cam_y + fy * t
        hz = self.cam_z + fz * t

        # Check if hit is within segment bounds (project onto segment)
        ax = hx - ow.x1
        az = hz - ow.y1
        along = (ax * dx + az * dz) / (seg_len * seg_len)
        if along < 0.0 or along > 1.0:
            return None

        # Check vertical bounds
        mi, mj = int((ow.x1 + ow.x2)*0.5), int((ow.y1 + ow.y2)*0.5)
        W, H = self.zone.width, self.zone.height
        if 0 <= mj < H and 0 <= mi < W:
            base = self.zone.floor_heights[mj][mi]
        else:
            base = 0.0
        top = base + ow.height_scale
        if hy < base or hy > top:
            return None

        return t

    # ── Save ──────────────────────────────────────────────────────

    def _save_zone(self) -> None:
        """Write the current zone data back to its JSON file."""
        zone = self.zone
        path = ZONES_DIR / f"{zone.name}.json"

        data: dict[str, Any] = {}
        data["anchor"] = list(zone.anchor)
        data["first_person"] = zone.first_person
        data["tiles"] = zone.tiles
        data["rotations"] = zone.rotations
        data["floor_heights"] = zone.floor_heights
        data["ceil_heights"] = zone.ceil_heights
        data["floor_textures"] = zone.floor_textures
        data["ceil_textures"] = zone.ceil_textures
        data["light_levels"] = zone.light_levels
        data["entities"] = zone.entities

        # Portals
        portals_out = []
        for p in zone.portals:
            portals_out.append({
                "tiles": [list(t) for t in p.tiles],
                "target_zone": p.target_zone,
                "target_pos": [p.target_row, p.target_col],
                "exit_direction": p.exit_direction,
            })
        data["portals"] = portals_out

        # Overlay walls
        if zone.overlay_walls:
            ov_out = []
            for ow in zone.overlay_walls:
                ov_out.append({
                    "x1": ow.x1, "y1": ow.y1,
                    "x2": ow.x2, "y2": ow.y2,
                    "texture": ow.texture,
                    "height_scale": ow.height_scale,
                    "transparent": ow.transparent,
                    "blocks": ow.blocks,
                })
            data["overlay_walls"] = ov_out

        with open(path, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")

        self.dirty = False

    # ── HUD ───────────────────────────────────────────────────────

    def _draw_hud(self, surface: pygame.Surface) -> None:
        sw, sh = surface.get_size()
        font = pygame.font.SysFont("monospace", 13)

        # ── Top-right: camera info ────────────────────────────
        lines = [
            (f"3D EDITOR", COL_HUD_TITLE),
            (f"Pos: ({self.cam_x:.1f}, {self.cam_y:.2f}, {self.cam_z:.1f})", COL_HUD_TEXT),
            (f"Yaw: {math.degrees(self.yaw):.0f}°  Pitch: {math.degrees(self.pitch):.0f}°", COL_HUD_TEXT),
            (f"Zone: {self.zone.name} ({self.zone.width}×{self.zone.height})", COL_HUD_TEXT),
        ]

        if self.dirty:
            lines.append(("* UNSAVED CHANGES (Ctrl+S to save)", (255, 100, 100)))

        y = 8
        for text, color in lines:
            surf = font.render(text, True, color)
            surface.blit(surf, (sw - surf.get_width() - 10, y))
            y += 16

        # ── Bottom-left: selection info ───────────────────────
        sel_lines: list[tuple[str, tuple]] = []
        if self.sel_type == SEL_CELL:
            r, c = self.sel_row, self.sel_col
            tid = self.zone.tiles[r][c]
            fh = self.zone.floor_heights[r][c]
            ch = self.zone.ceil_heights[r][c]
            ll = self.zone.light_levels[r][c]
            sel_lines = [
                (f"CELL ({c}, {r})", COL_HUD_TITLE),
                (f"Tile: {tid}", COL_HUD_VAL),
                (f"Floor: {fh:.2f}  Ceil: {ch:.2f}", COL_HUD_VAL),
                (f"Light: {ll:.2f}", COL_HUD_VAL),
                (f"↑↓ = floor height  Shift+↑↓ = ceil  PgUp/Dn = light", COL_HUD_TEXT),
            ]
        elif self.sel_type == SEL_OVERLAY:
            idx = self.sel_overlay_idx
            ow = self.zone.overlay_walls[idx]
            sel_lines = [
                (f"OVERLAY #{idx}", COL_HUD_TITLE),
                (f"({ow.x1:.1f},{ow.y1:.1f}) → ({ow.x2:.1f},{ow.y2:.1f})", COL_HUD_VAL),
                (f"Tex: {ow.texture}  HS: {ow.height_scale:.2f}", COL_HUD_VAL),
                (f"Transparent: {ow.transparent}  Blocks: {ow.blocks}", COL_HUD_VAL),
                (f"↑↓ = height  Del = remove", COL_HUD_TEXT),
            ]
        else:
            sel_lines = [
                ("Click to select a cell or overlay", (120, 120, 140)),
            ]

        y = sh - len(sel_lines) * 16 - 10
        # Background panel
        panel_h = len(sel_lines) * 16 + 8
        panel_w = 380
        panel = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        panel.fill(COL_HUD_BG)
        surface.blit(panel, (6, y - 4))

        for text, color in sel_lines:
            surf = font.render(text, True, color)
            surface.blit(surf, (10, y))
            y += 16

        # ── Toggle indicators (top-left) ──────────────────────
        toggles = [
            (f"1:Grid {'ON' if self.show_grid else 'off'}", self.show_grid),
            (f"2:Walls {'ON' if self.show_walls else 'off'}", self.show_walls),
            (f"3:Floor {'ON' if self.show_floors else 'off'}", self.show_floors),
            (f"4:Ceil {'ON' if self.show_ceilings else 'off'}", self.show_ceilings),
            (f"5:Overlay {'ON' if self.show_overlays else 'off'}", self.show_overlays),
            (f"6:Axes {'ON' if self.show_axes else 'off'}", self.show_axes),
        ]
        y = 8
        for label, active in toggles:
            col = (100, 200, 120) if active else (80, 80, 90)
            surf = font.render(label, True, col)
            surface.blit(surf, (10, y))
            y += 15

    def _draw_help(self, surface: pygame.Surface) -> None:
        sw, sh = surface.get_size()
        font = pygame.font.SysFont("monospace", 12)
        lines = [
            "─── 3D EDITOR CONTROLS ───",
            "",
            "WASD        = Fly forward/back/strafe",
            "Space / C   = Fly up / down",
            "Mouse       = Look around",
            "Q / E       = Yaw left / right",
            "Shift/Ctrl  = Sprint / slow",
            "",
            "Click       = Select cell / overlay",
            "Escape      = Deselect",
            "↑↓          = Adjust floor height",
            "Shift+↑↓    = Adjust ceil height",
            "PgUp/PgDn   = Adjust light level",
            "Delete      = Remove selected overlay",
            "Ctrl+S      = Save zone",
            "",
            "1-6         = Toggle layers (grid/walls/floor/ceil/overlay/axes)",
            "H           = Toggle HUD",
            "F1          = Toggle this help",
            "Tab         = Switch to 2.5D view",
        ]
        panel_w = 380
        panel_h = len(lines) * 15 + 20
        panel_x = (sw - panel_w) // 2
        panel_y = (sh - panel_h) // 2
        panel = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        panel.fill((0, 0, 0, 210))
        surface.blit(panel, (panel_x, panel_y))

        for i, line in enumerate(lines):
            col = COL_HUD_TITLE if i == 0 else COL_HUD_TEXT
            surf = font.render(line, True, col)
            surface.blit(surf, (panel_x + 15, panel_y + 10 + i * 15))
