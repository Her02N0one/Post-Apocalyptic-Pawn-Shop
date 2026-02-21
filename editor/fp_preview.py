"""editor/fp_preview.py -- First-person preview & editing for the editor.

Reuses the game's rendering pipeline (``scenes.world.fp_renderer.Renderer``,
``systems.raycaster.cast_walls``) instead of duplicating DDA / texture code.

See FP_EDITOR_DESIGN.md for the full design spec.

Modes:
  * **PIP** (``P`` key) -- small raycaster overlay in the top-right corner.
  * **Fullscreen edit** (``F`` or ``Tab``) -- Minecraft-creative-style editing.

Fullscreen controls:
  * Look: mouse (grabbed)
  * Move: WASD, Shift=sprint
  * Left-click: place tile (ghost cell for walls, target cell for floors)
  * Right-click: eyedropper (pick tile -> current hotbar slot)
  * Middle-click: erase
  * Scroll / 1-0: cycle / select hotbar slot
  * T: tile picker overlay
  * C: noclip toggle
  * Ctrl+Z / Ctrl+Y: undo / redo
  * Esc: exit to PIP
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pygame

from core.fonts import get_font
from core.tiles import tile_def, TF, TILE_REGISTRY, tiles_by_category
from systems.raycaster import cast_walls, project_entities, WallSlice
from systems.textures import TextureAtlas
from scenes.world.fp_renderer import Renderer, FOV
from scenes.world.fp_lighting import compute_fog_params
from editor.ui import Theme, draw_text

if TYPE_CHECKING:
    from editor.state import EditorState

# =====================================================================
#  Constants
# =====================================================================

MAX_DEPTH = 24.0
RAY_STEP = 4
TURN_SPEED = 2.5            # rad/s (PIP keyboard turning)
MOVE_SPEED = 4.0            # tiles/s
SPRINT_MULT = 2.0           # sprint multiplier
MOUSE_SENS = 0.003          # rad/px

_EDITOR_DN = 1.0            # always daylight

# Hotbar defaults -- sensible starting tile set
_DEFAULT_HOTBAR = [
    "wall", "brick_wall", "stone", "grass", "concrete",
    "door", "wood_floor", "carpet", "sand", "void",
]

HOTBAR_SLOTS = 10


# =====================================================================
#  FPPreview
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
        # Input
        self._keys_held: set[int] = set()
        self._looking: bool = False
        # Crosshair target
        self._target_tile: str | None = None
        self._target_rc: tuple[int, int] | None = None
        self._target_dist: float = 0.0
        self._target_is_wall: bool = False      # True if ray hit a wall
        # Ghost cell (where left-click will paint)
        self._ghost_rc: tuple[int, int] | None = None
        # Noclip
        self.noclip: bool = True
        # Hotbar (10 tile slots)
        self.hotbar: list[str] = list(_DEFAULT_HOTBAR)
        self._sanitize_hotbar()
        self.hotbar_slot: int = 0
        # Tile picker overlay
        self.tile_picker_open: bool = False
        self._picker_cats: list[tuple[str, list]] | None = None
        self._picker_scroll: float = 0.0
        self._picker_hover: str | None = None
        # Renderer
        self._renderer: Renderer | None = None
        self._rt: pygame.Surface | None = None
        self._rt_size: tuple[int, int] = (0, 0)
        self._fog_rate: int = 0
        self._fog_lut: list[int] = []
        self._fog_ready = False
        # Texture atlas for ghost previews + hotbar
        self._atlas: TextureAtlas | None = None

    # -- helpers ------------------------------------------------------

    def _sanitize_hotbar(self):
        """Ensure all hotbar slots have valid tile IDs."""
        keys = set(TILE_REGISTRY.keys())
        fallback = "grass" if "grass" in keys else next(iter(keys), "void")
        for i in range(HOTBAR_SLOTS):
            if i >= len(self.hotbar):
                self.hotbar.append(fallback)
            elif self.hotbar[i] not in keys:
                self.hotbar[i] = fallback

    @property
    def selected_tile(self) -> str:
        """The tile currently selected via the hotbar."""
        return self.hotbar[self.hotbar_slot]

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

    def _get_atlas(self) -> TextureAtlas:
        if self._atlas is None:
            self._atlas = TextureAtlas()
        return self._atlas

    def _get_picker_cats(self) -> list[tuple[str, list]]:
        """Lazily build the tile picker category list."""
        if self._picker_cats is None:
            self._picker_cats = [
                (cat, tds)
                for cat, tds in tiles_by_category().items()
                if tds
            ]
        return self._picker_cats

    # -- public API ---------------------------------------------------

    def toggle(self):
        """Toggle PIP on/off."""
        if self.active:
            self.active = False
            self.fullscreen = False
            self.tile_picker_open = False
            self._looking = False
            self._ungrab()
        else:
            self.active = True
            self.fullscreen = False

    def toggle_fullscreen(self):
        """Switch between PIP and fullscreen edit mode."""
        if not self.active:
            return
        self.fullscreen = not self.fullscreen
        self.tile_picker_open = False
        if self.fullscreen:
            self._grab()
        else:
            self._ungrab()

    def enter_fullscreen(self):
        """Activate FP and go straight to fullscreen."""
        self.active = True
        self.fullscreen = True
        self.tile_picker_open = False
        self._grab()

    def sync_to_anchor(self, anchor: tuple[float, float]):
        self.px, self.py = anchor

    def sync_selected_tile(self, state: "EditorState"):
        """Sync hotbar active slot with EditorState.selected_tile."""
        state.selected_tile = self.selected_tile

    def _grab(self):
        try:
            pygame.event.set_grab(True)
            pygame.mouse.set_visible(False)
        except pygame.error:
            pass

    def _ungrab(self):
        try:
            pygame.event.set_grab(False)
            pygame.mouse.set_visible(True)
        except pygame.error:
            pass
        self._looking = False

    # =================================================================
    #  Event handling
    # =================================================================

    def handle_event(self, event: pygame.event.Event,
                     state: "EditorState | None" = None) -> bool:
        if not self.active:
            return False

        # Tile picker overlay captures all input when open
        if self.tile_picker_open and self.fullscreen:
            return self._handle_picker_event(event, state)

        # -- KEYDOWN --------------------------------------------------
        if event.type == pygame.KEYDOWN:
            self._keys_held.add(event.key)

            if event.key == pygame.K_ESCAPE:
                if self.fullscreen:
                    self.fullscreen = False
                    self._ungrab()
                else:
                    self.active = False
                return True

            if event.key == pygame.K_TAB:
                self.toggle_fullscreen()
                return True

            if self.fullscreen and state is not None:
                return self._handle_fullscreen_key(event, state)

            # PIP: consume movement keys
            return event.key in (pygame.K_w, pygame.K_a,
                                 pygame.K_s, pygame.K_d,
                                 pygame.K_LEFT, pygame.K_RIGHT)

        if event.type == pygame.KEYUP:
            self._keys_held.discard(event.key)
            return False

        # -- Fullscreen mouse events ----------------------------------
        if self.fullscreen and state is not None:
            return self._handle_fullscreen_mouse(event, state)

        return False

    # -- fullscreen key handler ---------------------------------------

    def _handle_fullscreen_key(self, event: pygame.event.Event,
                                state: "EditorState") -> bool:
        key = event.key
        mods = pygame.key.get_mods()
        ctrl = mods & pygame.KMOD_CTRL

        # Undo / redo
        if ctrl and key == pygame.K_z:
            state.undo()
            state.toast("Undo")
            return True
        if ctrl and key == pygame.K_y:
            state.redo()
            state.toast("Redo")
            return True

        # Noclip
        if key == pygame.K_c:
            self.noclip = not self.noclip
            state.toast(f"Noclip: {'ON' if self.noclip else 'OFF'}")
            return True

        # Rotation
        if key == pygame.K_r:
            _DIRS = ("N", "E", "S", "W")
            state.pending_rotation = (state.pending_rotation + 1) % 4
            state.toast(f"Rotation: {_DIRS[state.pending_rotation]}")
            return True

        # Tile picker
        if key == pygame.K_t:
            self.tile_picker_open = True
            self._picker_scroll = 0.0
            self._picker_hover = None
            # Ungrab mouse so user can click the picker
            self._ungrab()
            pygame.mouse.set_visible(True)
            return True

        # Number keys -> hotbar slot selection
        if pygame.K_1 <= key <= pygame.K_9:
            slot = key - pygame.K_1  # 0-8
            self._set_hotbar_slot(slot, state)
            return True
        if key == pygame.K_0:
            self._set_hotbar_slot(9, state)
            return True

        # Movement keys consumed
        return key in (pygame.K_w, pygame.K_a, pygame.K_s, pygame.K_d,
                       pygame.K_LSHIFT, pygame.K_RSHIFT)

    # -- fullscreen mouse handler -------------------------------------

    def _handle_fullscreen_mouse(self, event: pygame.event.Event,
                                  state: "EditorState") -> bool:
        if event.type == pygame.MOUSEMOTION:
            dx, _dy = event.rel
            self.angle += dx * MOUSE_SENS
            return True

        # Left-click = PLACE
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self._do_place(state)
            return True

        # Right-click = EYEDROPPER
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
            self._do_eyedropper(state)
            return True

        # Middle-click = ERASE
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 2:
            self._do_erase(state)
            return True

        # Scroll = cycle hotbar slot
        if event.type == pygame.MOUSEWHEEL:
            new_slot = (self.hotbar_slot - event.y) % HOTBAR_SLOTS
            self._set_hotbar_slot(new_slot, state)
            return True

        return False

    # -- tile picker event handler ------------------------------------

    def _handle_picker_event(self, event: pygame.event.Event,
                              state: "EditorState | None") -> bool:
        if event.type == pygame.KEYDOWN:
            self._keys_held.add(event.key)
            if event.key in (pygame.K_ESCAPE, pygame.K_t):
                self._close_picker()
                return True
            return True

        if event.type == pygame.KEYUP:
            self._keys_held.discard(event.key)
            return True

        if event.type == pygame.MOUSEWHEEL:
            self._picker_scroll -= event.y * 30
            self._picker_scroll = max(0, self._picker_scroll)
            return True

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._picker_hover:
                self.hotbar[self.hotbar_slot] = self._picker_hover
                if state:
                    state.selected_tile = self._picker_hover
                    td = tile_def(self._picker_hover)
                    state.toast(f"Slot {self.hotbar_slot + 1}: {td.name}")
                self._close_picker()
            return True

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
            # Right-click closes picker too
            self._close_picker()
            return True

        return True  # absorb all events while picker is open

    def _close_picker(self):
        self.tile_picker_open = False
        self._picker_hover = None
        if self.fullscreen:
            self._grab()

    # -- hotbar slot ---------------------------------------------------

    def _set_hotbar_slot(self, slot: int, state: "EditorState"):
        self.hotbar_slot = slot % HOTBAR_SLOTS
        tile_id = self.hotbar[self.hotbar_slot]
        state.selected_tile = tile_id
        td = tile_def(tile_id)
        state.toast(f"[{self.hotbar_slot + 1}] {td.name}")

    # -- placement actions --------------------------------------------

    def _do_place(self, state: "EditorState"):
        """Left-click: place at ghost cell (walls) or target cell (floor)."""
        if self._target_is_wall and self._ghost_rc:
            r, c = self._ghost_rc
        elif self._target_rc:
            r, c = self._target_rc
        else:
            return

        tile_id = self.selected_tile
        state.push_undo()
        state.tiles[r][c] = tile_id
        if state.rotations and 0 <= r < len(state.rotations) and 0 <= c < len(state.rotations[0]):
            state.rotations[r][c] = state.pending_rotation
        state.dirty = True
        td = tile_def(tile_id)
        state.toast(f"Placed {td.name} at [{r},{c}]")

    def _do_eyedropper(self, state: "EditorState"):
        """Right-click: pick the aimed tile into the current hotbar slot."""
        if self._target_tile:
            self.hotbar[self.hotbar_slot] = self._target_tile
            state.selected_tile = self._target_tile
            td = tile_def(self._target_tile)
            state.toast(f"Picked: {td.name} -> slot {self.hotbar_slot + 1}")

    def _do_erase(self, state: "EditorState"):
        """Middle-click: erase the aimed cell."""
        if self._target_rc:
            r, c = self._target_rc
            state.push_undo()
            state.tiles[r][c] = state.erase_tile
            if state.rotations and 0 <= r < len(state.rotations) and 0 <= c < len(state.rotations[0]):
                state.rotations[r][c] = 0
            state.dirty = True
            state.toast(f"Erased [{r},{c}]")

    # =================================================================
    #  Update (movement + crosshair)
    # =================================================================

    def update(self, dt: float, tiles: list[list[str]],
               map_w: int, map_h: int):
        if not self.active:
            return

        # Don't move while picker is open
        if self.tile_picker_open:
            return

        keys = self._keys_held

        # PIP keyboard turning
        if not self.fullscreen:
            if pygame.K_LEFT in keys:
                self.angle -= TURN_SPEED * dt
            if pygame.K_RIGHT in keys:
                self.angle += TURN_SPEED * dt

        # Movement
        speed = MOVE_SPEED
        if pygame.K_LSHIFT in keys or pygame.K_RSHIFT in keys:
            speed *= SPRINT_MULT

        dx, dy = 0.0, 0.0
        if pygame.K_w in keys:
            dx += math.cos(self.angle) * speed * dt
            dy += math.sin(self.angle) * speed * dt
        if pygame.K_s in keys:
            dx -= math.cos(self.angle) * speed * dt
            dy -= math.sin(self.angle) * speed * dt
        if pygame.K_a in keys:
            dx += math.sin(self.angle) * speed * dt
            dy -= math.cos(self.angle) * speed * dt
        if pygame.K_d in keys:
            dx -= math.sin(self.angle) * speed * dt
            dy += math.cos(self.angle) * speed * dt

        nx, ny = self.px + dx, self.py + dy
        if self.noclip:
            self.px, self.py = nx, ny
        else:
            margin = 0.2
            if self._passable(nx, self.py, tiles, map_w, map_h, margin):
                self.px = nx
            if self._passable(self.px, ny, tiles, map_w, map_h, margin):
                self.py = ny

        self._update_crosshair(tiles, map_w, map_h)

    # -- crosshair / DDA ---------------------------------------------

    def _update_crosshair(self, tiles: list[list[str]],
                           map_w: int, map_h: int):
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
            # Ray hit a wall
            if side == 0:
                dist = (mx - self.px + (1 - step_x) / 2) / cos_c
            else:
                dist = (my - self.py + (1 - step_y) / 2) / sin_c
            self._target_dist = abs(dist)
            self._target_tile = tiles[my][mx]
            self._target_rc = (my, mx)
            self._target_is_wall = True
            # Ghost = the empty cell just before the wall
            if 0 <= prev_my < map_h and 0 <= prev_mx < map_w:
                prev_td = tile_def(tiles[prev_my][prev_mx])
                if not (prev_td.flags & (TF.WALL | TF.SOLID)):
                    self._ghost_rc = (prev_my, prev_mx)
                else:
                    self._ghost_rc = None
            else:
                self._ghost_rc = None
        else:
            # Looking at open floor -- target the cell ~2 tiles ahead
            self._target_dist = MAX_DEPTH
            self._target_is_wall = False
            ahead_x = int(self.px + cos_c * 2.0)
            ahead_y = int(self.py + sin_c * 2.0)
            if (0 <= ahead_y < map_h and 0 <= ahead_x < map_w):
                self._target_tile = tiles[ahead_y][ahead_x]
                self._target_rc = (ahead_y, ahead_x)
                self._ghost_rc = (ahead_y, ahead_x)
            else:
                # Fallback to cell under feet
                fr, fc = int(self.py), int(self.px)
                if 0 <= fr < map_h and 0 <= fc < map_w:
                    self._target_tile = tiles[fr][fc]
                    self._target_rc = (fr, fc)
                    self._ghost_rc = (fr, fc)
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

    # =================================================================
    #  Rendering
    # =================================================================

    def draw(self, surface: pygame.Surface,
             tiles: list[list[str]], map_w: int, map_h: int,
             rect: pygame.Rect,
             selected_tile: str | None = None,
             entities: list | None = None,
             rotations: list[list[int]] | None = None,
             pending_rotation: int = 0):
        if not self.active:
            return

        # Stash for sub-methods (ghost preview, HUD)
        self._pending_rotation = pending_rotation

        renderer = self._ensure_renderer()
        fog_lut = self._ensure_fog()
        vw, vh = rect.w, rect.h
        half = vh // 2

        rt = self._get_rt(vw, vh)

        # 1. Floor + ceiling
        renderer.draw_floor_ceiling(
            rt, vw, vh, half,
            self.px, self.py, self.angle,
            fog_lut, _EDITOR_DN, FOV,
            tiles, map_w, map_h,
            True,
        )

        # 2. Textured walls
        slices, plat_col, zbuf_full, deferred_halves = renderer.draw_walls(
            rt, vw, vh, half,
            self.px, self.py,
            self.angle, FOV,
            tiles, fog_lut, _EDITOR_DN,
            rotations,
        )

        # 3. Visplane tops
        renderer.draw_visplane_tops(
            rt, vw, vh, half,
            self.px, self.py,
            self.angle, FOV,
            plat_col, fog_lut,
            tiles, map_w, map_h,
        )

        # 4. Entity billboards
        if entities:
            self._draw_editor_entities(
                rt, vw, vh, half, entities, zbuf_full)

        # 5. Ghost block preview (fullscreen only)
        if self.fullscreen and self._ghost_rc:
            tile_id = self.selected_tile
            if self._target_is_wall:
                self._draw_ghost_wall(rt, vw, vh, half, tile_id)
            else:
                self._draw_ghost_floor(rt, vw, vh, half, tile_id)

        # Blit render target
        surface.blit(rt, (rect.x, rect.y))

        # 6. Crosshair
        cx, cy = rect.centerx, rect.centery
        cross_col = (200, 200, 200)
        if self.fullscreen and self._target_tile:
            td = tile_def(self._target_tile)
            cross_col = tuple(min(255, c + 60) for c in td.color)
        _draw_crosshair(surface, cx, cy, cross_col)

        # 7. HUD
        from editor.layout import Layout as _L
        font_sm = get_font(max(9, round(11 * _L.scale)))
        if self.fullscreen:
            self._draw_fullscreen_hud(surface, rect, font_sm)
            if self.tile_picker_open:
                self._draw_tile_picker(surface, rect, font_sm)
        else:
            draw_text(surface, f"FP Preview  ({self.px:.1f}, {self.py:.1f})",
                      rect.x + 4, rect.y + 4, Theme.ACCENT, font_sm)
            draw_text(surface, "WASD=Move  Arrows=Turn  Tab=Edit  Esc=Close",
                      rect.x + 4, rect.y + 16, Theme.TEXT_DIM, font_sm)

    # -- entity billboards --------------------------------------------

    def _draw_editor_entities(
        self,
        surface: pygame.Surface,
        sw: int, sh: int, half: int,
        entities: list,
        zbuf: list[float],
    ):
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

        for bb in billboards:
            if bb.distance > MAX_DEPTH:
                continue
            scx = int(bb.screen_x)
            if 0 <= scx < sw and bb.distance > zbuf[scx]:
                continue

            bh = max(1, bb.height)
            fog = max(0.15, 1.0 - bb.distance / MAX_DEPTH)
            col = tuple(int(c * fog) for c in bb.color)

            font_size = max(8, min(48, bh))
            font_size = (font_size // 2) * 2
            font = get_font(font_size)

            glyph = font.render(bb.char, True, col)
            gx = int(bb.screen_x - glyph.get_width() * 0.5)
            gy = int(bb.screen_y) + (bh - glyph.get_height()) // 2
            surface.blit(glyph, (gx, gy))

    # -- ghost preview: wall placement --------------------------------

    def _draw_ghost_wall(self, surface: pygame.Surface,
                         sw: int, sh: int, half: int,
                         tile_id: str):
        """Translucent textured column at the ghost cell (wall placement)."""
        gr, gc = self._ghost_rc  # type: ignore[misc]
        cx_w = gc + 0.5
        cy_w = gr + 0.5
        dx = cx_w - self.px
        dy = cy_w - self.py

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
            return

        sx = int(sw * 0.5 * (1.0 + tx / ty))
        wall_h = sh / ty
        col_top = max(0, int(half - wall_h * 0.5))
        col_bot = min(sh, int(half + wall_h * 0.5))
        if col_bot <= col_top:
            return

        col_w = max(1, int(sw / (2.0 * ty * plane_scale)))
        x0 = sx - col_w // 2
        gw = max(1, col_w)
        gh = col_bot - col_top

        # Render actual tile texture (rotation-aware)
        td = tile_def(tile_id)
        atlas = self._get_atlas()
        rot = getattr(self, '_pending_rotation', 0)
        # Pick face from angle: the ghost is ahead of us, so we see
        # the face that points back at the camera.
        dx_n = math.cos(self.angle)
        dy_n = math.sin(self.angle)
        if abs(dx_n) > abs(dy_n):
            ghost_face = "west" if dx_n > 0 else "east"
        else:
            ghost_face = "north" if dy_n > 0 else "south"
        tex_key = td.tex_for_face(ghost_face, rot)
        tex_surf = atlas.get(tex_key)

        try:
            scaled = pygame.transform.scale(tex_surf, (gw, gh))
        except (pygame.error, ValueError):
            return

        # Pulsing alpha
        t = pygame.time.get_ticks() / 800.0
        alpha = int(130 + 40 * math.sin(t))
        scaled.set_alpha(alpha)

        bx = max(0, x0)
        if x0 < 0:
            crop = pygame.Rect(-x0, 0, gw + x0, gh)
            surface.blit(scaled, (0, col_top), crop)
        else:
            surface.blit(scaled, (bx, col_top))

        # Outline
        ghost_color = tuple(min(255, c + 60) for c in td.color)
        pulse = int(140 + 60 * math.sin(t))
        outline = pygame.Surface((gw, gh), pygame.SRCALPHA)
        pygame.draw.rect(outline, (*ghost_color, pulse),
                         pygame.Rect(0, 0, gw, gh), 2)
        if x0 < 0:
            crop = pygame.Rect(-x0, 0, gw + x0, gh)
            surface.blit(outline, (0, col_top), crop)
        else:
            surface.blit(outline, (bx, col_top))

        # Label
        from editor.layout import Layout as _L
        lbl_font = get_font(max(8, round(10 * _L.scale)))
        lbl = lbl_font.render(td.name[:12], True, ghost_color)
        lx = sx - lbl.get_width() // 2
        ly = col_top - lbl.get_height() - 2
        if ly >= 0:
            surface.blit(lbl, (lx, ly))

    # -- ghost preview: floor placement -------------------------------

    def _draw_ghost_floor(self, surface: pygame.Surface,
                          sw: int, sh: int, half: int,
                          tile_id: str):
        """Translucent floor highlight at the ghost cell (floor painting)."""
        gr, gc = self._ghost_rc  # type: ignore[misc]

        td = tile_def(tile_id)
        ghost_color = tuple(min(255, c + 60) for c in td.color)
        t = pygame.time.get_ticks() / 800.0

        # Project the 4 corners of the floor cell
        dir_x = math.cos(self.angle)
        dir_y = math.sin(self.angle)
        plane_scale = math.tan(FOV * 0.5)
        plane_x = -dir_y * plane_scale
        plane_y = dir_x * plane_scale

        det = plane_x * dir_y - dir_x * plane_y
        if abs(det) < 1e-10:
            return
        inv_det = 1.0 / det

        corners = [
            (gc + 0.0, gr + 0.0),
            (gc + 1.0, gr + 0.0),
            (gc + 1.0, gr + 1.0),
            (gc + 0.0, gr + 1.0),
        ]
        screen_pts: list[tuple[int, int]] = []
        for wx, wy in corners:
            dx = wx - self.px
            dy = wy - self.py
            tx = inv_det * (dir_y * dx - dir_x * dy)
            ty = inv_det * (-plane_y * dx + plane_x * dy)
            if ty <= 0.05:
                return  # corner behind camera -- skip entire quad
            scr_x = int(sw * 0.5 * (1.0 + tx / ty))
            # Floor is at the base of walls (bottom horizon line)
            floor_screen_y = int(half + (sh * 0.5) / ty)
            screen_pts.append((scr_x, floor_screen_y))

        if len(screen_pts) < 3:
            return

        # Draw filled polygon with tile color tint
        alpha = int(100 + 40 * math.sin(t))
        poly_surf = pygame.Surface((sw, sh), pygame.SRCALPHA)
        pygame.draw.polygon(poly_surf, (*ghost_color, alpha), screen_pts)
        pulse = int(180 + 60 * math.sin(t))
        pygame.draw.polygon(poly_surf, (*ghost_color, pulse), screen_pts, 2)
        surface.blit(poly_surf, (0, 0))

        # Label at centroid
        from editor.layout import Layout as _L
        centroid_x = sum(p[0] for p in screen_pts) // len(screen_pts)
        centroid_y = sum(p[1] for p in screen_pts) // len(screen_pts)
        lbl_font = get_font(max(8, round(10 * _L.scale)))
        lbl = lbl_font.render(td.name[:12], True, ghost_color)
        lx = centroid_x - lbl.get_width() // 2
        ly = centroid_y - lbl.get_height() // 2
        if 0 <= ly < sh and 0 <= lx < sw:
            surface.blit(lbl, (lx, ly))

    # =================================================================
    #  HUD
    # =================================================================

    def _draw_fullscreen_hud(self, surface: pygame.Surface,
                              rect: pygame.Rect,
                              font_sm: pygame.font.Font):
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
            label = "wall" if self._target_is_wall else "floor"
            draw_text(surface, f"Aim: {td.name} [{r},{c}] ({label})",
                      x0, y, Theme.TEXT, font_sm)
            y += 14

        # Ghost placement
        if self._ghost_rc:
            gr, gc = self._ghost_rc
            action = "build" if self._target_is_wall else "paint"
            draw_text(surface, f"Click: {action} [{gr},{gc}]",
                      x0, y, (120, 200, 120), font_sm)
            y += 14

        # Rotation indicator
        _DIR_LBL = ("N", "E", "S", "W")
        rot_txt = f"Rot: {_DIR_LBL[getattr(self, '_pending_rotation', 0) % 4]}"
        draw_text(surface, rot_txt, x0, y, Theme.ACCENT2, font_sm)
        y += 14

        # Noclip (top-right)
        if self.noclip:
            nw = font_sm.size("NOCLIP")[0]
            draw_text(surface, "NOCLIP",
                      rect.right - nw - 8, rect.y + 6,
                      (255, 120, 80), font_sm)

        # ---- HOTBAR ----
        self._draw_hotbar(surface, rect, font_sm)

        # Controls hint (below hotbar)
        hints = "WASD=Move  Shift=Sprint  T=Tiles  C=Noclip  Esc=Exit"
        tw = font_sm.size(hints)[0]
        draw_text(surface, hints,
                  rect.centerx - tw // 2, rect.bottom - 14,
                  Theme.TEXT_DIM, font_sm)

    # -- hotbar drawing -----------------------------------------------

    def _draw_hotbar(self, surface: pygame.Surface,
                      rect: pygame.Rect,
                      font_sm: pygame.font.Font):
        """Draw the 10-slot hotbar at the bottom center of the viewport."""
        from editor.layout import Layout as _L

        swatch = max(28, round(36 * _L.scale))
        gap = max(2, round(3 * _L.scale))
        total_w = HOTBAR_SLOTS * swatch + (HOTBAR_SLOTS - 1) * gap
        bar_x = rect.centerx - total_w // 2
        bar_y = rect.bottom - swatch - 28

        atlas = self._get_atlas()

        # Semi-transparent background
        bg = pygame.Surface((total_w + 8, swatch + 22), pygame.SRCALPHA)
        bg.fill((0, 0, 0, 100))
        surface.blit(bg, (bar_x - 4, bar_y - 16))

        for i in range(HOTBAR_SLOTS):
            x = bar_x + i * (swatch + gap)
            y = bar_y

            tile_id = self.hotbar[i]
            td = tile_def(tile_id)

            # Texture thumbnail
            tex = atlas.get(td.wall_tex())
            try:
                thumb = pygame.transform.scale(tex, (swatch, swatch))
            except (pygame.error, ValueError):
                thumb = pygame.Surface((swatch, swatch))
                thumb.fill(td.color)
            surface.blit(thumb, (x, y))

            # Border
            if i == self.hotbar_slot:
                pygame.draw.rect(surface, Theme.ACCENT,
                                 pygame.Rect(x - 1, y - 1,
                                             swatch + 2, swatch + 2), 2)
            else:
                pygame.draw.rect(surface, (80, 80, 80),
                                 pygame.Rect(x, y, swatch, swatch), 1)

            # Slot number above
            num = str((i + 1) % 10)
            num_col = Theme.ACCENT if i == self.hotbar_slot else Theme.TEXT_DIM
            nw = font_sm.size(num)[0]
            draw_text(surface, num,
                      x + (swatch - nw) // 2, y - 14,
                      num_col, font_sm)

    # -- tile picker overlay ------------------------------------------

    def _draw_tile_picker(self, surface: pygame.Surface,
                           rect: pygame.Rect,
                           font_sm: pygame.font.Font):
        """Full-viewport translucent tile picker grouped by category."""
        from editor.layout import Layout as _L

        # Overlay background
        overlay = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        surface.blit(overlay, (rect.x, rect.y))

        atlas = self._get_atlas()
        cats = self._get_picker_cats()

        swatch = max(40, round(48 * _L.scale))
        gap = max(4, round(6 * _L.scale))
        pad = 20
        cols = max(1, (rect.w - pad * 2 + gap) // (swatch + gap))

        # Title
        title_font = get_font(max(12, round(16 * _L.scale)))
        title = title_font.render(
            "TILE PICKER  (click to assign, Esc to close)",
            True, Theme.ACCENT)
        tx = rect.x + rect.w // 2 - title.get_width() // 2
        surface.blit(title, (tx, rect.y + 8))

        # Content area
        content_y = rect.y + 36
        max_y = rect.y + rect.h - 10
        draw_y = content_y - int(self._picker_scroll)
        mx, my = pygame.mouse.get_pos()
        self._picker_hover = None

        for cat_name, tds in cats:
            if draw_y + 20 > max_y:
                break
            if draw_y >= content_y - 20:
                hdr = font_sm.render(
                    f"--- {cat_name} ({len(tds)}) ---",
                    True, Theme.TEXT_DIM)
                surface.blit(hdr, (rect.x + pad, max(content_y, draw_y)))
            draw_y += 22

            row_count = (len(tds) + cols - 1) // cols
            for row_i in range(row_count):
                if draw_y > max_y:
                    break
                for col_i in range(cols):
                    idx = row_i * cols + col_i
                    if idx >= len(tds):
                        break
                    td_item = tds[idx]
                    sx = rect.x + pad + col_i * (swatch + gap)
                    sy = draw_y

                    if sy + swatch < content_y or sy > max_y:
                        continue

                    # Draw texture swatch
                    tex = atlas.get(td_item.wall_tex())
                    try:
                        thumb = pygame.transform.scale(
                            tex, (swatch, swatch))
                    except (pygame.error, ValueError):
                        thumb = pygame.Surface((swatch, swatch))
                        thumb.fill(td_item.color)
                    surface.blit(thumb, (sx, sy))

                    # Hover detection
                    sr = pygame.Rect(sx, sy, swatch, swatch)
                    if sr.collidepoint(mx, my):
                        pygame.draw.rect(surface, Theme.ACCENT, sr, 2)
                        self._picker_hover = td_item.id
                        # Tooltip
                        tip = font_sm.render(td_item.name, True, Theme.TEXT)
                        surface.blit(tip, (sx, sy + swatch + 2))
                    else:
                        if td_item.id in self.hotbar:
                            pygame.draw.rect(
                                surface, (100, 100, 100), sr, 1)
                        else:
                            pygame.draw.rect(
                                surface, (50, 50, 50), sr, 1)

                draw_y += swatch + gap
            draw_y += 6

        # Clamp scroll
        total_h = draw_y + int(self._picker_scroll) - content_y
        max_scroll = max(0, total_h - (max_y - content_y))
        self._picker_scroll = min(self._picker_scroll, max_scroll)


# =====================================================================
#  Helpers
# =====================================================================

def _draw_crosshair(surface: pygame.Surface, cx: int, cy: int,
                     color: tuple):
    pygame.draw.line(surface, color, (cx - 8, cy), (cx - 3, cy), 1)
    pygame.draw.line(surface, color, (cx + 3, cy), (cx + 8, cy), 1)
    pygame.draw.line(surface, color, (cx, cy - 8), (cx, cy - 3), 1)
    pygame.draw.line(surface, color, (cx, cy + 3), (cx, cy + 8), 1)
