"""editor/fp_preview.py -- First-person preview & editing for the editor.

Reuses the game's rendering pipeline (``scenes.world.fp_renderer.Renderer``,
``systems.raycaster.cast_walls``) instead of duplicating DDA / texture code.

Render modes:
  * **PIP** (``P`` key) -- small raycaster overlay in the top-right corner.
  * **Full-screen edit** (``Tab`` while PIP is open) -- takes over the
    entire canvas area.

Editing controls (full-screen only):
  * Left-click:  paint tile onto the aimed wall/floor.
  * Right-click: eyedropper -- pick the tile you're looking at.
  * Middle-click: erase (paint erase_tile).
  * Scroll: cycle selected tile.
  * Ctrl+Z / Ctrl+Y: undo / redo.
  * Mouse-look: always on in fullscreen.
  * WASD: move.  Esc: back to PIP.

Ghost-block preview: when aiming at a wall, the adjacent empty cell
is highlighted with a translucent tinted column so you can see where
a new block would be placed before clicking.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pygame

from core.tiles import tile_def, TF, TILE_REGISTRY
from systems.raycaster import cast_walls, project_entities, WallSlice
from scenes.world.fp_renderer import Renderer, FOV
from scenes.world.fp_lighting import compute_fog_params
from editor.ui import Theme, draw_text

if TYPE_CHECKING:
    from editor.state import EditorState

# =====================================================================
#  Constants
# =====================================================================

MAX_DEPTH = 24.0
RAY_STEP = 4               # match the game renderer
TURN_SPEED = 2.5            # rad/s (keyboard turning)
MOVE_SPEED = 4.0            # tiles/s
MOUSE_SENS = 0.003          # mouse-look sensitivity (rad/px)

# Day/night factor for editor (always bright daylight)
_EDITOR_DN = 1.0


# =====================================================================
#  FP Preview
# =====================================================================

class FPPreview:
    """First-person raycaster with optional in-viewport editing.

    Delegates all rendering to the game's ``Renderer`` so that
    textures, face overrides, fog, floor/ceiling, visplane, and
    AO shadows are identical to the actual game.
    """

    def __init__(self):
        self.active = False
        self.fullscreen = False
        # Camera
        self.px: float = 15.0
        self.py: float = 10.0
        self.angle: float = 0.0
        # Speed
        self._keys_held: set[int] = set()
        # Mouse-look state
        self._looking: bool = False
        # Crosshair target (updated each frame)
        self._target_tile: str | None = None
        self._target_rc: tuple[int, int] | None = None
        self._target_dist: float = 0.0
        # Ghost placement: the empty cell adjacent to crosshair wall
        self._ghost_rc: tuple[int, int] | None = None
        # Shared game renderer (lazy-init)
        self._renderer: Renderer | None = None
        # Cached render target -- avoids re-alloc each frame
        self._rt: pygame.Surface | None = None
        self._rt_size: tuple[int, int] = (0, 0)
        # Cached fog_lut for editor daylight
        self._fog_rate: int = 0
        self._fog_lut: list[int] = []
        self._fog_ready = False

    # -- lazy init ----------------------------------------------------

    def _ensure_renderer(self) -> Renderer:
        if self._renderer is None:
            self._renderer = Renderer()
        return self._renderer

    def _ensure_fog(self) -> list[int]:
        if not self._fog_ready:
            self._fog_rate, _, self._fog_lut = compute_fog_params(_EDITOR_DN)
            self._fog_ready = True
        return self._fog_lut

    def _get_rt(self, w: int, h: int) -> pygame.Surface:
        if self._rt is None or self._rt_size != (w, h):
            self._rt = pygame.Surface((w, h)).convert()
            self._rt_size = (w, h)
        return self._rt

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
        """Process events.  Returns True if consumed."""
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

            # Fullscreen editor shortcuts
            if self.fullscreen and state is not None:
                mods = pygame.key.get_mods()
                ctrl = mods & pygame.KMOD_CTRL
                if ctrl and event.key == pygame.K_z:
                    state.undo()
                    state.toast("Undo")
                    return True
                if ctrl and event.key == pygame.K_y:
                    state.redo()
                    state.toast("Redo")
                    return True

            return event.key in (pygame.K_w, pygame.K_a,
                                 pygame.K_s, pygame.K_d,
                                 pygame.K_LEFT, pygame.K_RIGHT)

        if event.type == pygame.KEYUP:
            self._keys_held.discard(event.key)
            return False

        # -- Fullscreen-only events -----------------------------------
        if self.fullscreen and state is not None:
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

    # -- update -------------------------------------------------------

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

        # Update crosshair target via DDA (single centre ray)
        self._update_crosshair(tiles, map_w, map_h)

    def _update_crosshair(self, tiles: list[list[str]],
                           map_w: int, map_h: int):
        """Cast a single centre ray to find the aimed tile + ghost cell."""
        cos_c = math.cos(self.angle)
        sin_c = math.sin(self.angle)
        eps = 1e-9
        if abs(cos_c) < eps:
            cos_c = eps
        if abs(sin_c) < eps:
            sin_c = eps

        step_x = 1 if cos_c > 0 else -1
        step_y = 1 if sin_c > 0 else -1
        mx = int(self.px)
        my = int(self.py)
        ddx = abs(1.0 / cos_c)
        ddy = abs(1.0 / sin_c)

        if cos_c > 0:
            side_x = (mx + 1.0 - self.px) * ddx
        else:
            side_x = (self.px - mx) * ddx
        if sin_c > 0:
            side_y = (my + 1.0 - self.py) * ddy
        else:
            side_y = (self.py - my) * ddy

        prev_mx, prev_my = mx, my
        side = 0
        hit = False

        for _ in range(int(MAX_DEPTH * 4)):
            prev_mx, prev_my = mx, my
            if side_x < side_y:
                side_x += ddx
                mx += step_x
                side = 0
            else:
                side_y += ddy
                my += step_y
                side = 1

            if not (0 <= my < map_h and 0 <= mx < map_w):
                break

            tid = tiles[my][mx]
            td = tile_def(tid)
            if td.flags & (TF.WALL | TF.SOLID):
                hit = True
                break

        if hit:
            if side == 0:
                dist = (mx - self.px + (1 - step_x) / 2) / cos_c
            else:
                dist = (my - self.py + (1 - step_y) / 2) / sin_c
            self._target_dist = abs(dist)
            self._target_tile = tiles[my][mx]
            self._target_rc = (my, mx)
            # Ghost = empty cell just before the wall
            if 0 <= prev_my < map_h and 0 <= prev_mx < map_w:
                prev_td = tile_def(tiles[prev_my][prev_mx])
                if not (prev_td.flags & (TF.WALL | TF.SOLID)):
                    self._ghost_rc = (prev_my, prev_mx)
                else:
                    self._ghost_rc = None
            else:
                self._ghost_rc = None
        else:
            self._target_dist = MAX_DEPTH
            fr, fc = int(self.py), int(self.px)
            if 0 <= fr < map_h and 0 <= fc < map_w:
                self._target_tile = tiles[fr][fc]
                self._target_rc = (fr, fc)
            else:
                self._target_tile = None
                self._target_rc = None
            self._ghost_rc = None

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
             selected_tile: str | None = None,
             entities: list | None = None):
        """Render the first-person view into *rect*.

        Uses the game's ``Renderer`` for textured walls, floor/ceiling,
        and visplanes.  Entity billboards are projected from the
        editor's ``EntityDef`` list.

        *selected_tile* is used in fullscreen mode for the HUD.
        *entities* is the editor's list[EntityDef] for billboard
        rendering (optional).
        """
        if not self.active:
            return

        renderer = self._ensure_renderer()
        fog_lut = self._ensure_fog()
        vw, vh = rect.w, rect.h
        half = vh // 2

        # Render to an offscreen surface at rect size, then blit
        rt = self._get_rt(vw, vh)

        # 1. Floor + ceiling (uses the game's textured floor renderer)
        renderer.draw_floor_ceiling(
            rt, vw, vh, half,
            self.px, self.py, self.angle,
            fog_lut, _EDITOR_DN, FOV,
            tiles, map_w, map_h,
            True,  # is_interior (use indoor ceiling)
        )

        # 2. Textured walls (game's full pipeline)
        slices, plat_col, zbuf_full, deferred_halves = renderer.draw_walls(
            rt, vw, vh, half,
            self.px, self.py,
            self.angle, FOV,
            tiles, fog_lut, _EDITOR_DN,
        )

        # 3. Visplane tops (platforms)
        renderer.draw_visplane_tops(
            rt, vw, vh, half,
            self.px, self.py,
            self.angle, FOV,
            plat_col, fog_lut,
            tiles, map_w, map_h,
        )

        # 4. Entity billboards (from editor EntityDef list)
        if entities:
            self._draw_editor_entities(
                rt, vw, vh, half, entities, zbuf_full)

        # 5. Ghost block preview
        if self.fullscreen and self._ghost_rc and selected_tile:
            self._draw_ghost(rt, vw, vh, half, selected_tile)

        # Blit the render target onto the output surface
        surface.blit(rt, (rect.x, rect.y))

        # 6. Crosshair (drawn on the output surface directly)
        cx, cy = rect.centerx, rect.centery
        cross_col = (200, 200, 200)
        if self.fullscreen and self._target_tile:
            td = tile_def(self._target_tile)
            cross_col = tuple(min(255, c + 60) for c in td.color)
        _draw_crosshair(surface, cx, cy, cross_col)

        # 7. Info overlay / HUD
        from editor.layout import Layout as _L
        font_sm = pygame.font.SysFont("monospace",
                                      max(9, round(11 * _L.scale)))
        if self.fullscreen:
            self._draw_fullscreen_hud(surface, rect, font_sm, selected_tile)
        else:
            draw_text(surface, f"FP Preview  ({self.px:.1f}, {self.py:.1f})",
                      rect.x + 4, rect.y + 4, Theme.ACCENT, font_sm)
            draw_text(surface, "WASD=Move  Arrows=Turn  Tab=Edit  Esc=Close",
                      rect.x + 4, rect.y + 16, Theme.TEXT_DIM, font_sm)

    # -- entity billboards from editor defs ---------------------------

    def _draw_editor_entities(
        self,
        surface: pygame.Surface,
        sw: int, sh: int, half: int,
        entities: list,
        zbuf: list[float],
    ):
        """Project editor EntityDef objects as simple billboards."""
        from editor.entity_defs import EntityDef
        ent_data: list[tuple] = []
        for i, ent in enumerate(entities):
            if not isinstance(ent, EntityDef):
                continue
            ex = ent.position.x
            ey = ent.position.y
            sp = ent.sprite
            char = sp.char if sp else "?"
            color = tuple(sp.color) if sp and sp.color else (200, 200, 200)
            ent_data.append((i, ex, ey, char, color, 0.6, 0.4))

        if not ent_data:
            return

        billboards = project_entities(
            self.px, self.py, self.angle, FOV, sw, sh, ent_data)

        font_cache: dict[int, pygame.font.Font] = {}
        for bb in billboards:
            if bb.distance > MAX_DEPTH:
                continue

            # Depth test against wall zbuffer
            scx = int(bb.screen_x)
            if 0 <= scx < sw and bb.distance > zbuf[scx]:
                continue

            bx = int(bb.screen_x - bb.width * 0.5)
            by = int(bb.screen_y)
            bw = max(1, bb.width)
            bh = max(1, bb.height)

            # Fog
            fog = max(0.15, 1.0 - bb.distance / MAX_DEPTH)
            col = tuple(int(c * fog) for c in bb.color)

            # Simple glyph rendering
            font_size = max(8, min(48, bh))
            font_size = (font_size // 2) * 2
            if font_size not in font_cache:
                font_cache[font_size] = pygame.font.SysFont(
                    "monospace", font_size)
            font = font_cache[font_size]

            glyph = font.render(bb.char, True, col)
            gx = int(bb.screen_x - glyph.get_width() * 0.5)
            gy = by + (bh - glyph.get_height()) // 2
            surface.blit(glyph, (gx, gy))

    # -- ghost block preview ------------------------------------------

    def _draw_ghost(self, surface: pygame.Surface,
                    sw: int, sh: int, half: int,
                    tile_id: str):
        """Draw a translucent tinted column at the ghost cell position."""
        gr, gc = self._ghost_rc  # type: ignore[misc]
        # Project the ghost cell centre into screen space
        cx = gc + 0.5
        cy = gr + 0.5
        dx = cx - self.px
        dy = cy - self.py

        dir_x = math.cos(self.angle)
        dir_y = math.sin(self.angle)
        plane_scale = math.tan(FOV * 0.5)
        plane_x = -dir_y * plane_scale
        plane_y = dir_x * plane_scale

        det = plane_x * dir_y - dir_x * plane_y
        if abs(det) < 1e-10:
            return
        inv_det = 1.0 / det

        tx = inv_det * (dir_y * dx - dir_x * dy)
        ty = inv_det * (-plane_y * dx + plane_x * dy)

        if ty <= 0.1:
            return  # behind camera

        sx = int(sw * 0.5 * (1.0 + tx / ty))
        wall_h = sh / ty
        col_top = int(half - wall_h * 0.5)
        col_bot = int(half + wall_h * 0.5)

        # Clamp
        col_top = max(0, col_top)
        col_bot = min(sh, col_bot)
        if col_bot <= col_top:
            return

        col_w = max(1, int(wall_h * 0.5))
        x0 = sx - col_w // 2
        x1 = x0 + col_w

        # Get tile colour for the ghost tint
        td = tile_def(tile_id)
        ghost_color = tuple(min(255, c + 40) for c in td.color)

        # Draw translucent overlay
        gw = max(1, x1 - x0)
        gh = col_bot - col_top
        ghost_surf = pygame.Surface((gw, gh), pygame.SRCALPHA)
        ghost_surf.fill((*ghost_color, 80))
        surface.blit(ghost_surf, (max(0, x0), col_top))

        # Outline
        outline_rect = pygame.Rect(max(0, x0), col_top, gw, gh)
        pygame.draw.rect(surface, (*ghost_color, 160), outline_rect, 1)

    # -- HUD ----------------------------------------------------------

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
            draw_text(surface,
                      f"  type={td.type.value}  dist={self._target_dist:.1f}",
                      x0, y, Theme.TEXT_DIM, font_sm)
        y += 14

        # Ghost placement indicator
        if self._ghost_rc:
            gr, gc = self._ghost_rc
            draw_text(surface, f"Place at: [{gr},{gc}]",
                      x0, y, (120, 200, 120), font_sm)
            y += 14

        # Selected tile (bottom-left)
        if selected_tile:
            by = rect.bottom - 50
            td = tile_def(selected_tile)
            sw_r = pygame.Rect(x0, by, 20, 20)
            pygame.draw.rect(surface, td.color, sw_r, border_radius=2)
            pygame.draw.rect(surface, (120, 120, 120), sw_r, 1,
                             border_radius=2)
            draw_text(surface, f"Brush: {td.name}",
                      x0 + 26, by + 3, Theme.ACCENT, font_sm)
            draw_text(surface, f"  ({td.type.value})",
                      x0 + 26, by + 16, Theme.TEXT_DIM, font_sm)

        # Controls hint (bottom-right)
        hints = ("LClick=Paint  RClick=Pick  MClick=Erase  "
                 "Scroll=Cycle  Ctrl+Z/Y=Undo/Redo  Tab=TopDown  Esc=PIP")
        tw = font_sm.size(hints)[0]
        draw_text(surface, hints,
                  rect.right - tw - 6, rect.bottom - 16,
                  Theme.TEXT_DIM, font_sm)


# =====================================================================
#  Helpers
# =====================================================================

def _draw_crosshair(surface: pygame.Surface, cx: int, cy: int,
                     color: tuple):
    """Small crosshair at screen centre."""
    pygame.draw.line(surface, color, (cx - 8, cy), (cx - 3, cy), 1)
    pygame.draw.line(surface, color, (cx + 3, cy), (cx + 8, cy), 1)
    pygame.draw.line(surface, color, (cx, cy - 8), (cx, cy - 3), 1)
    pygame.draw.line(surface, color, (cx, cy + 3), (cx, cy + 8), 1)
