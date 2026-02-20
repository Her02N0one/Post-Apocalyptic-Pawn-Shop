"""editor/fp_preview.py — First-person preview & editing for the editor.

Render modes:
  * **PIP** (``P`` key) -- small raycaster overlay in the top-right corner.
  * **Full-screen edit** (``Tab`` while PIP is open) -- takes over the
    entire canvas area.  The designer can look around, walk and **paint
    tiles** directly from the first-person view.

Editing controls (full-screen only):
  * Left-click:  paint the selected tile onto the wall/floor you're
    looking at (same as the top-down brush).
  * Right-click: eyedropper -- pick the tile you're looking at.
  * Middle-click: erase (paint erase_tile).
  * Mouse-look: always on in fullscreen.
  * WASD: move, mouse: look, Scroll: cycle selected tile, Esc: back to PIP.

The raycaster is a simple DDA column-cast against the editor's tile
grid -- no ECS, no entities, no lighting.  Good enough for a designer
sanity check and quick tile placement.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pygame

from core.tiles import TILE_COLORS, tile_def, TF, TILE_REGISTRY, TileType
from editor.ui import Theme, draw_text

if TYPE_CHECKING:
    from editor.state import EditorState

# =====================================================================
#  Constants
# =====================================================================

FOV = math.pi / 3          # 60 deg horizontal
MAX_DEPTH = 24.0
RAY_STEP = 2               # pixels per column (2 = fast, 1 = crisp)
TURN_SPEED = 2.5           # rad/s (keyboard turning)
MOVE_SPEED = 4.0           # tiles/s
MOUSE_SENS = 0.003         # mouse-look sensitivity (rad/px)


# =====================================================================
#  FP Preview
# =====================================================================

class FPPreview:
    """First-person raycaster with optional in-viewport editing."""

    def __init__(self):
        self.active = False
        self.fullscreen = False   # True = takes over the canvas
        # Camera
        self.px: float = 15.0
        self.py: float = 10.0
        self.angle: float = 0.0
        # Speed
        self._keys_held: set[int] = set()
        # Mouse-look state
        self._looking: bool = False
        # Crosshair target (updated each frame)
        self._target_tile: str | None = None   # tile ID at crosshair
        self._target_rc: tuple[int, int] | None = None  # (row, col) on map
        self._target_dist: float = 0.0

    # -- public API ---------------------------------------------------

    def toggle(self):
        """Toggle PIP on/off.  Turning PIP off also disables fullscreen."""
        if self.active:
            self.active = False
            self.fullscreen = False
            self._looking = False
            try:
                pygame.event.set_grab(False)
                pygame.mouse.set_visible(True)
            except pygame.error:
                pass
        else:
            self.active = True
            self.fullscreen = False

    def toggle_fullscreen(self):
        """Switch between PIP and fullscreen edit mode."""
        if not self.active:
            return
        self.fullscreen = not self.fullscreen
        try:
            if self.fullscreen:
                pygame.event.set_grab(True)
                pygame.mouse.set_visible(False)
            else:
                pygame.event.set_grab(False)
                pygame.mouse.set_visible(True)
                self._looking = False
        except pygame.error:
            pass

    def sync_to_anchor(self, anchor: tuple[float, float]):
        """Set camera position from the editor anchor."""
        self.px, self.py = anchor

    # -- event handling -----------------------------------------------

    def handle_event(self, event: pygame.event.Event,
                     state: "EditorState | None" = None) -> bool:
        """Process events.  Returns True if consumed.

        *state* is required for fullscreen editing (painting/picking).
        """
        if not self.active:
            return False

        # -- KEYDOWN --------------------------------------------------
        if event.type == pygame.KEYDOWN:
            self._keys_held.add(event.key)
            if event.key == pygame.K_ESCAPE:
                if self.fullscreen:
                    self.fullscreen = False
                    try:
                        pygame.event.set_grab(False)
                        pygame.mouse.set_visible(True)
                    except pygame.error:
                        pass
                    self._looking = False
                else:
                    self.active = False
                return True
            if event.key == pygame.K_TAB:
                self.toggle_fullscreen()
                return True
            return event.key in (pygame.K_w, pygame.K_a,
                                 pygame.K_s, pygame.K_d,
                                 pygame.K_LEFT, pygame.K_RIGHT)

        if event.type == pygame.KEYUP:
            self._keys_held.discard(event.key)
            return False

        # -- Fullscreen-only events -----------------------------------
        if self.fullscreen and state is not None:
            # Mouse-look (always on in fullscreen via relative motion)
            if event.type == pygame.MOUSEMOTION:
                dx, _dy = event.rel
                self.angle += dx * MOUSE_SENS
                return True

            # Left-click = paint selected tile
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self._target_rc:
                    r, c = self._target_rc
                    state.push_undo()
                    state.tiles[r][c] = state.selected_tile
                    state.dirty = True
                    state.toast(f"Painted {state.selected_tile}")
                return True

            # Right-click = eyedropper
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
                if self._target_tile:
                    state.selected_tile = self._target_tile
                    state.toast(f"Picked: {self._target_tile}")
                return True

            # Middle-click = erase
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 2:
                if self._target_rc:
                    r, c = self._target_rc
                    state.push_undo()
                    state.tiles[r][c] = state.erase_tile
                    state.dirty = True
                    state.toast(f"Erased -> {state.erase_tile}")
                return True

            # Scroll = cycle through tiles
            if event.type == pygame.MOUSEWHEEL:
                ids = list(TILE_REGISTRY.keys())
                if ids:
                    try:
                        idx = ids.index(state.selected_tile)
                    except ValueError:
                        idx = 0
                    idx = (idx + event.y) % len(ids)
                    state.selected_tile = ids[idx]
                    state.toast(f"Tile: {state.selected_tile}")
                return True

        return False

    def update(self, dt: float, tiles: list[list[str]],
               map_w: int, map_h: int):
        """Move camera and update crosshair target."""
        if not self.active:
            return
        keys = self._keys_held

        # Keyboard turn (non-fullscreen and fallback)
        if not self.fullscreen:
            if pygame.K_LEFT in keys:
                self.angle -= TURN_SPEED * dt
            if pygame.K_RIGHT in keys:
                self.angle += TURN_SPEED * dt

        # Movement
        dx, dy = 0.0, 0.0
        if pygame.K_w in keys:
            dx += math.cos(self.angle) * MOVE_SPEED * dt
            dy += math.sin(self.angle) * MOVE_SPEED * dt
        if pygame.K_s in keys:
            dx -= math.cos(self.angle) * MOVE_SPEED * dt
            dy -= math.sin(self.angle) * MOVE_SPEED * dt
        if pygame.K_a in keys:
            dx += math.sin(self.angle) * MOVE_SPEED * dt
            dy -= math.cos(self.angle) * MOVE_SPEED * dt
        if pygame.K_d in keys:
            dx -= math.sin(self.angle) * MOVE_SPEED * dt
            dy += math.cos(self.angle) * MOVE_SPEED * dt

        # Collision
        nx, ny = self.px + dx, self.py + dy
        margin = 0.2
        if self._passable(nx, self.py, tiles, map_w, map_h, margin):
            self.px = nx
        if self._passable(self.px, ny, tiles, map_w, map_h, margin):
            self.py = ny

        # Update crosshair target (centre ray)
        cos_c = math.cos(self.angle)
        sin_c = math.sin(self.angle)
        dist, tid, _side, rc = self._cast_ray_full(
            self.px, self.py, cos_c, sin_c, tiles, map_w, map_h)
        self._target_tile = tid
        self._target_rc = rc
        self._target_dist = dist

    # -- collision ----------------------------------------------------

    @staticmethod
    def _passable(x: float, y: float,
                  tiles: list[list[str]], map_w: int, map_h: int,
                  margin: float) -> bool:
        for ox in (-margin, margin):
            for oy in (-margin, margin):
                c = int(x + ox)
                r = int(y + oy)
                if not (0 <= r < map_h and 0 <= c < map_w):
                    return False
                td = tile_def(tiles[r][c])
                if td.solid:
                    return False
        return True

    # -- rendering ----------------------------------------------------

    def draw(self, surface: pygame.Surface,
             tiles: list[list[str]], map_w: int, map_h: int,
             rect: pygame.Rect,
             selected_tile: str | None = None):
        """Render the first-person view into *rect*.

        *selected_tile* is used in fullscreen mode to show a placement
        HUD with the tile name and colour.
        """
        if not self.active:
            return

        vw, vh = rect.w, rect.h
        half_h = vh / 2

        # Background (sky + floor)
        sky_r = pygame.Rect(rect.x, rect.y, vw, vh // 2)
        floor_r = pygame.Rect(rect.x, rect.y + vh // 2, vw, vh // 2)
        pygame.draw.rect(surface, (40, 50, 70), sky_r)
        pygame.draw.rect(surface, (50, 45, 35), floor_r)

        num_cols = vw // RAY_STEP

        for col in range(num_cols):
            frac = (col / num_cols) - 0.5
            ray_angle = self.angle + frac * FOV

            cos_a = math.cos(ray_angle)
            sin_a = math.sin(ray_angle)

            dist, hit_tile, hit_side = self._cast_ray(
                self.px, self.py, cos_a, sin_a,
                tiles, map_w, map_h)

            if dist <= 0:
                continue

            perp = dist * math.cos(ray_angle - self.angle)
            if perp < 0.05:
                perp = 0.05

            line_h = int(vh / perp)
            draw_top = int(half_h - line_h / 2) + rect.y
            draw_bot = int(half_h + line_h / 2) + rect.y

            td = tile_def(hit_tile)
            color = list(td.color)
            if hit_side == 1:
                color = [max(0, c - 30) for c in color]
            fog = max(0.15, 1.0 - dist / MAX_DEPTH)
            color = [int(c * fog) for c in color]

            sx = rect.x + col * RAY_STEP
            pygame.draw.rect(surface, color,
                             (sx, max(rect.y, draw_top),
                              RAY_STEP,
                              min(rect.bottom, draw_bot) - max(rect.y, draw_top)))

        # -- Crosshair ------------------------------------------------
        cx, cy = rect.centerx, rect.centery
        cross_col = (200, 200, 200)
        if self.fullscreen and self._target_tile:
            td = tile_def(self._target_tile)
            cross_col = tuple(min(255, c + 60) for c in td.color)
        pygame.draw.line(surface, cross_col,
                         (cx - 8, cy), (cx - 3, cy), 1)
        pygame.draw.line(surface, cross_col,
                         (cx + 3, cy), (cx + 8, cy), 1)
        pygame.draw.line(surface, cross_col,
                         (cx, cy - 8), (cx, cy - 3), 1)
        pygame.draw.line(surface, cross_col,
                         (cx, cy + 3), (cx, cy + 8), 1)

        # -- Info overlay ----------------------------------------------
        font_sm = pygame.font.SysFont("monospace", 11)
        if self.fullscreen:
            self._draw_fullscreen_hud(surface, rect, font_sm, selected_tile)
        else:
            draw_text(surface, f"FP Preview  ({self.px:.1f}, {self.py:.1f})",
                      rect.x + 4, rect.y + 4, Theme.ACCENT, font_sm)
            draw_text(surface, "WASD=Move  Arrows=Turn  Tab=Edit  Esc=Close",
                      rect.x + 4, rect.y + 16, Theme.TEXT_DIM, font_sm)

    def _draw_fullscreen_hud(self, surface: pygame.Surface,
                              rect: pygame.Rect,
                              font_sm: pygame.font.Font,
                              selected_tile: str | None):
        """Draw editing HUD elements in fullscreen mode."""
        x0 = rect.x + 6
        y = rect.y + 6

        # Position
        draw_text(surface, f"({self.px:.1f}, {self.py:.1f})",
                  x0, y, Theme.TEXT_DIM, font_sm)
        y += 14

        # Target info
        if self._target_tile and self._target_rc:
            td = tile_def(self._target_tile)
            r, c = self._target_rc
            draw_text(surface, f"Looking at: {td.name} [{r},{c}]",
                      x0, y, Theme.TEXT, font_sm)
            y += 14
            draw_text(surface, f"  type={td.type.value}  dist={self._target_dist:.1f}",
                      x0, y, Theme.TEXT_DIM, font_sm)
        y += 14

        # Selected tile (bottom-left)
        if selected_tile:
            by = rect.bottom - 50
            td = tile_def(selected_tile)
            sw_r = pygame.Rect(x0, by, 20, 20)
            pygame.draw.rect(surface, td.color, sw_r, border_radius=2)
            pygame.draw.rect(surface, (120, 120, 120), sw_r, 1, border_radius=2)
            draw_text(surface, f"Brush: {td.name}",
                      x0 + 26, by + 3, Theme.ACCENT, font_sm)
            draw_text(surface, f"  ({td.type.value})",
                      x0 + 26, by + 16, Theme.TEXT_DIM, font_sm)

        # Controls hint (bottom-right)
        hints = "LClick=Paint  RClick=Pick  MClick=Erase  Scroll=Cycle  Tab=TopDown  Esc=PIP"
        tw = font_sm.size(hints)[0]
        draw_text(surface, hints,
                  rect.right - tw - 6, rect.bottom - 16,
                  Theme.TEXT_DIM, font_sm)

    # -- raycasting ---------------------------------------------------

    @staticmethod
    def _cast_ray(px: float, py: float,
                  cos_a: float, sin_a: float,
                  tiles: list[list[str]], map_w: int, map_h: int,
                  ) -> tuple[float, str, int]:
        """Simple DDA raycast.  Returns (distance, tile_id, side)."""
        eps = 1e-9
        if abs(cos_a) < eps:
            cos_a = eps
        if abs(sin_a) < eps:
            sin_a = eps

        step_x = 1 if cos_a > 0 else -1
        step_y = 1 if sin_a > 0 else -1
        map_x = int(px)
        map_y = int(py)
        ddx = abs(1.0 / cos_a)
        ddy = abs(1.0 / sin_a)

        if cos_a > 0:
            side_x = (map_x + 1.0 - px) * ddx
        else:
            side_x = (px - map_x) * ddx
        if sin_a > 0:
            side_y = (map_y + 1.0 - py) * ddy
        else:
            side_y = (py - map_y) * ddy

        hit = False
        side = 0

        for _ in range(int(MAX_DEPTH * 4)):
            if side_x < side_y:
                side_x += ddx
                map_x += step_x
                side = 0
            else:
                side_y += ddy
                map_y += step_y
                side = 1

            if not (0 <= map_y < map_h and 0 <= map_x < map_w):
                break

            tid = tiles[map_y][map_x]
            td = tile_def(tid)
            if td.flags & (TF.WALL | TF.SOLID):
                hit = True
                break

        if not hit:
            return MAX_DEPTH, "void", 0

        if side == 0:
            dist = (map_x - px + (1 - step_x) / 2) / cos_a
        else:
            dist = (map_y - py + (1 - step_y) / 2) / sin_a

        return abs(dist), tiles[map_y][map_x], side

    @staticmethod
    def _cast_ray_full(px: float, py: float,
                       cos_a: float, sin_a: float,
                       tiles: list[list[str]], map_w: int, map_h: int,
                       ) -> tuple[float, "str | None", int, "tuple[int, int] | None"]:
        """Like _cast_ray but also returns the (row, col) of the hit cell."""
        eps = 1e-9
        if abs(cos_a) < eps:
            cos_a = eps
        if abs(sin_a) < eps:
            sin_a = eps

        step_x = 1 if cos_a > 0 else -1
        step_y = 1 if sin_a > 0 else -1
        map_x = int(px)
        map_y = int(py)
        ddx = abs(1.0 / cos_a)
        ddy = abs(1.0 / sin_a)

        if cos_a > 0:
            side_x = (map_x + 1.0 - px) * ddx
        else:
            side_x = (px - map_x) * ddx
        if sin_a > 0:
            side_y = (map_y + 1.0 - py) * ddy
        else:
            side_y = (py - map_y) * ddy

        hit = False
        side = 0

        for _ in range(int(MAX_DEPTH * 4)):
            if side_x < side_y:
                side_x += ddx
                map_x += step_x
                side = 0
            else:
                side_y += ddy
                map_y += step_y
                side = 1

            if not (0 <= map_y < map_h and 0 <= map_x < map_w):
                break

            tid = tiles[map_y][map_x]
            td = tile_def(tid)
            if td.flags & (TF.WALL | TF.SOLID):
                hit = True
                break

        if not hit:
            # Return the floor cell the player is standing on
            fr, fc = int(py), int(px)
            if 0 <= fr < map_h and 0 <= fc < map_w:
                return MAX_DEPTH, tiles[fr][fc], 0, (fr, fc)
            return MAX_DEPTH, None, 0, None

        if side == 0:
            dist = (map_x - px + (1 - step_x) / 2) / cos_a
        else:
            dist = (map_y - py + (1 - step_y) / 2) / sin_a

        return abs(dist), tiles[map_y][map_x], side, (map_y, map_x)
