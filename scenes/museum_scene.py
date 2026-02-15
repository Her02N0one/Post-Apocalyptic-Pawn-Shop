"""scenes/museum_scene.py — Interactive Exhibit Museum.

Two-mode UI:
    PICKER mode  — full-screen exhibit selector grouped by category
    EXHIBIT mode — active exhibit with camera, debug overlays, info panel

Controls (Picker):
    Arrow keys / Mouse  — navigate exhibits
    Enter / LMB         — open selected exhibit
    Escape              — back to scene picker

Controls (Exhibit):
    Tab             — return to exhibit picker
    Space           — start / reset the active demo
    I               — toggle info/description panel
    WASD / Arrows   — pan camera
    Scroll wheel    — zoom in / out
    Home            — reset camera to centre
    F1–F8           — toggle debug overlays
    LMB / RMB       — interact (exhibit-specific)
    Escape          — back to exhibit picker (or scene picker)
"""

from __future__ import annotations
import pygame
from core.scene import Scene
from core.app import App
from core.constants import TILE_SIZE, TILE_COLORS
from core.zone import ZONE_MAPS
from components import (
    Position, Sprite, Identity, Camera, Health, Brain, Facing, GameClock,
)
from components.social import Faction
from components.combat import Projectile

# ── Exhibits ─────────────────────────────────────────────────────────
from scenes.exhibits.base import Exhibit, DebugFlags, FLAG_META
from scenes.exhibits.patrol_exhibit import PatrolExhibit
from scenes.exhibits.combat_exhibit import CombatExhibit
from scenes.exhibits.hearing_exhibit import HearingExhibit
from scenes.exhibits.pathfinding_exhibit import PathfindingExhibit
from scenes.exhibits.faction_exhibit import FactionExhibit
from scenes.exhibits.vision_exhibit import VisionExhibit
from scenes.exhibits.particle_exhibit import ParticleExhibit
from scenes.exhibits.needs_exhibit import NeedsExhibit
from scenes.exhibits.lod_exhibit import LODExhibit
from scenes.exhibits.stat_combat_exhibit import StatCombatExhibit
from scenes.exhibits.economy_exhibit import EconomyExhibit
from scenes.exhibits.crime_exhibit import CrimeExhibit

from core.constants import TILE_WALL as _TILE_WALL

_TILE_GRASS = 0
_PAN_SPEED = 20.0     # tiles / s at zoom 1.0 (visual speed stays constant)
_ZOOM_MIN = 0.25
_ZOOM_MAX = 3.0
_ZOOM_STEP = 1.15     # multiplicative step per scroll tick

# F-key → debug-flag attribute
_FLAG_FKEYS = {
    pygame.K_F1: "names",
    pygame.K_F2: "health",
    pygame.K_F3: "brain",
    pygame.K_F4: "ranges",
    pygame.K_F5: "vision",
    pygame.K_F6: "grid",
    pygame.K_F7: "positions",
    pygame.K_F8: "faction",
}

# Brain mode → colour (generic per-entity overlay)
_BRAIN_COLORS = {
    "idle":      (150, 150, 150),
    "searching": (255, 180, 50),
    "chase":     (255, 200, 80),
    "attack":    (255, 80, 80),
    "flee":      (80, 180, 255),
    "return":    (180, 120, 255),
}

# Category colours for the picker
_CAT_COLORS = {
    "AI & Behaviour":   (0, 200, 160),
    "AI & Perception":  (100, 200, 255),
    "Combat":           (255, 80, 80),
    "Navigation":       (0, 220, 100),
    "Social":           (255, 200, 50),
    "Simulation":       (180, 140, 255),
    "Visual Effects":   (255, 160, 80),
    "General":          (180, 180, 180),
}


def _make_arena(w: int, h: int) -> list[list[int]]:
    """Build a grass arena of *w*×*h* tiles with a wall border."""
    tiles = [[_TILE_GRASS] * w for _ in range(h)]
    for r in range(h):
        tiles[r][0] = _TILE_WALL
        tiles[r][w - 1] = _TILE_WALL
    for c in range(w):
        tiles[0][c] = _TILE_WALL
        tiles[h - 1][c] = _TILE_WALL
    return tiles


class MuseumScene(Scene):
    """Interactive Exhibit Museum — picker + exhibit viewer."""

    def __init__(self):
        self.zone = "__museum__"
        self.tab = 0

        self._eids: list[int] = []

        # Camera state
        self._cam_x = 0.0
        self._cam_y = 0.0
        self._zoom = 1.0
        self._dragging = False
        self._drag_origin: tuple[int, int] = (0, 0)
        self._drag_cam: tuple[float, float] = (0.0, 0.0)

        # Debug overlay flags (reset per-tab from exhibit defaults)
        self._flags = DebugFlags()

        # Info panel toggle
        self._show_info = False

        # Mode: "picker" or "exhibit"
        self._mode = "picker"
        self._picker_sel = 0          # index into _exhibits
        self._picker_hover = -1       # mouse hover index
        self._picker_scroll = 0.0     # vertical scroll offset (pixels)

        # Build the exhibit list — order matches tab indices
        self._exhibits: list[Exhibit] = [
            PatrolExhibit(),       # 0  — settlement patrol
            CombatExhibit(),       # 1  — team fight
            HearingExhibit(),      # 2  — gunshot → searching → chase
            PathfindingExhibit(),  # 3  — A* pathfinding
            FactionExhibit(),      # 4  — alert cascade
            VisionExhibit(),       # 5  — directional vision cone
            ParticleExhibit(),     # 6  — particle effects
            NeedsExhibit(),        # 7  — hunger / eating
            LODExhibit(),          # 8  — LOD promote / demote
            StatCombatExhibit(),   # 9  — off-screen stat combat
            EconomyExhibit(),      # 10 — stockpile economy
            CrimeExhibit(),        # 11 — witness / crime
        ]

        # Pre-compute category order for picker
        self._cat_order: list[str] = []
        self._cat_exhibits: dict[str, list[int]] = {}
        seen_cats: set[str] = set()
        for i, ex in enumerate(self._exhibits):
            cat = ex.category
            if cat not in seen_cats:
                seen_cats.add(cat)
                self._cat_order.append(cat)
                self._cat_exhibits[cat] = []
            self._cat_exhibits[cat].append(i)

        # Arena (set from active exhibit on tab switch)
        self.tiles: list[list[int]] = []
        self.map_w = 0
        self.map_h = 0

        # Picker card rects (built each draw, in screen-space)
        self._card_rects: list[tuple[pygame.Rect, int]] = []
        # Total content height of the picker (set during draw)
        self._picker_content_h = 0

    @property
    def _exhibit(self) -> Exhibit:
        return self._exhibits[self.tab]

    # ── Lifecycle ────────────────────────────────────────────────────

    def on_enter(self, app: App):
        if not app.world.res(Camera):
            app.world.set_res(Camera())
        if not app.world.res(GameClock):
            app.world.set_res(GameClock())
        ZONE_MAPS[self.zone] = [[]]  # placeholder until setup_tab
        self._mode = "picker"

    def on_exit(self, app: App):
        self._clear_entities(app)

    def _clear_entities(self, app: App):
        for eid in self._eids:
            if app.world.alive(eid):
                app.world.kill(eid)
        app.world.purge()
        self._eids.clear()

    def _setup_tab(self, app: App):
        """Reset arena and delegate to the active exhibit."""
        self._clear_entities(app)
        ex = self._exhibit
        self.map_w = ex.arena_w
        self.map_h = ex.arena_h
        self.tiles = _make_arena(self.map_w, self.map_h)
        ZONE_MAPS[self.zone] = self.tiles
        # Centre camera on arena
        self._cam_x = self.map_w / 2.0
        self._cam_y = self.map_h / 2.0
        self._zoom = 1.0
        self._flags = DebugFlags.from_defaults(ex.default_debug)
        self._eids = ex.setup(app, self.zone, self.tiles)
        self._show_info = False

    def _open_exhibit(self, app: App, index: int):
        """Switch to exhibit mode with the given exhibit."""
        self.tab = index
        self._mode = "exhibit"
        self._setup_tab(app)

    # ── Events ───────────────────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event, app: App):
        if self._mode == "picker":
            self._handle_picker_event(event, app)
        else:
            self._handle_exhibit_event(event, app)

    def _handle_picker_event(self, event: pygame.event.Event, app: App):
        n = len(self._exhibits)
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                app.pop_scene()
                return

            if event.key in (pygame.K_RIGHT, pygame.K_d):
                self._picker_sel = (self._picker_sel + 1) % n
                self._scroll_to_selected(app)
                return
            if event.key in (pygame.K_LEFT, pygame.K_a):
                self._picker_sel = (self._picker_sel - 1) % n
                self._scroll_to_selected(app)
                return
            if event.key in (pygame.K_DOWN, pygame.K_s):
                self._picker_sel = min(self._picker_sel + 1, n - 1)
                self._scroll_to_selected(app)
                return
            if event.key in (pygame.K_UP, pygame.K_w):
                self._picker_sel = max(self._picker_sel - 1, 0)
                self._scroll_to_selected(app)
                return

            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self._open_exhibit(app, self._picker_sel)
                return

        # Scroll wheel in picker → vertical scroll
        if event.type == pygame.MOUSEWHEEL:
            self._picker_scroll -= event.y * 40
            self._clamp_scroll(app)
            return

        if event.type == pygame.MOUSEMOTION:
            mx, my = app.mouse_pos()
            self._picker_hover = -1
            for rect, idx in self._card_rects:
                if rect.collidepoint(mx, my):
                    self._picker_hover = idx
                    break

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = app.mouse_pos()
            for rect, idx in self._card_rects:
                if rect.collidepoint(mx, my):
                    self._open_exhibit(app, idx)
                    return

    # ── Picker scroll helpers ────────────────────────────────────────

    def _picker_viewport(self, app: App) -> tuple[int, int]:
        """Return (top, bottom) pixel coords of the scrollable region."""
        _, sh = app.screen.get_size()
        top = 64            # below title
        bottom = sh - 130   # above description preview
        return top, max(top + 10, bottom)

    def _clamp_scroll(self, app: App):
        top, bottom = self._picker_viewport(app)
        view_h = bottom - top
        max_scroll = max(0.0, self._picker_content_h - view_h)
        self._picker_scroll = max(0.0, min(self._picker_scroll, max_scroll))

    def _scroll_to_selected(self, app: App):
        """Ensure the selected card is visible in the scrollable area."""
        for rect, idx in self._card_rects:
            if idx == self._picker_sel:
                top, bottom = self._picker_viewport(app)
                # rect.y is screen-space; content-y = rect.y + scroll - top
                content_y = rect.y + self._picker_scroll - top
                content_bottom = content_y + rect.h
                view_h = bottom - top
                if content_y < self._picker_scroll:
                    self._picker_scroll = content_y
                elif content_bottom > self._picker_scroll + view_h:
                    self._picker_scroll = content_bottom - view_h
                self._clamp_scroll(app)
                return

    def _handle_exhibit_event(self, event: pygame.event.Event, app: App):
        if event.type == pygame.KEYDOWN:
            # Return to picker
            if event.key == pygame.K_ESCAPE or event.key == pygame.K_TAB:
                self._clear_entities(app)
                self._mode = "picker"
                return

            # Toggle info panel
            if event.key == pygame.K_i:
                self._show_info = not self._show_info
                return

            # Debug flag toggles (F1–F8)
            if event.key in _FLAG_FKEYS:
                self._flags.toggle(_FLAG_FKEYS[event.key])
                return

            # Reset camera
            if event.key == pygame.K_HOME:
                self._cam_x = self.map_w / 2.0
                self._cam_y = self.map_h / 2.0
                self._zoom = 1.0
                return

            # Space — exhibit action
            if event.key == pygame.K_SPACE:
                result = self._exhibit.on_space(app)
                if result == "reset":
                    self._setup_tab(app)
                return

        # Scroll-wheel zoom
        if event.type == pygame.MOUSEWHEEL:
            if event.y > 0:
                self._zoom = min(_ZOOM_MAX, self._zoom * _ZOOM_STEP)
            elif event.y < 0:
                self._zoom = max(_ZOOM_MIN, self._zoom / _ZOOM_STEP)
            return

        # Middle-mouse drag for panning
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 2:
            self._dragging = True
            self._drag_origin = app.mouse_pos()
            self._drag_cam = (self._cam_x, self._cam_y)
            return
        if event.type == pygame.MOUSEBUTTONUP and event.button == 2:
            self._dragging = False
            return
        if event.type == pygame.MOUSEMOTION and self._dragging:
            mx, my = app.mouse_pos()
            tile_px = max(1, int(TILE_SIZE * self._zoom))
            dx = (mx - self._drag_origin[0]) / tile_px
            dy = (my - self._drag_origin[1]) / tile_px
            self._cam_x = self._drag_cam[0] - dx
            self._cam_y = self._drag_cam[1] - dy
            return

        # Delegate to active exhibit
        self._exhibit.handle_event(event, app,
                                   lambda: self._mouse_to_tile(app))

    # ── Update ───────────────────────────────────────────────────────

    def update(self, dt: float, app: App):
        if self._mode == "picker":
            return

        # Keyboard panning (WASD / arrow keys)
        keys = pygame.key.get_pressed()
        pan = _PAN_SPEED / max(self._zoom, 0.1) * dt
        if keys[pygame.K_w] or keys[pygame.K_UP]:
            self._cam_y -= pan
        if keys[pygame.K_s] or keys[pygame.K_DOWN]:
            self._cam_y += pan
        if keys[pygame.K_a] or keys[pygame.K_LEFT]:
            self._cam_x -= pan
        if keys[pygame.K_d] or keys[pygame.K_RIGHT]:
            self._cam_x += pan
        # Clamp to arena bounds
        self._cam_x = max(0.0, min(float(self.map_w), self._cam_x))
        self._cam_y = max(0.0, min(float(self.map_h), self._cam_y))

        # Game clock
        clock = app.world.res(GameClock)
        if clock:
            clock.time += dt

        self._exhibit.update(app, dt, self.tiles, self._eids)
        app.world.purge()

    # ── Draw ─────────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, app: App):
        if self._mode == "picker":
            self._draw_picker(surface, app)
        else:
            self._draw_exhibit(surface, app)

    # ── Picker Drawing ───────────────────────────────────────────────

    def _draw_picker(self, surface: pygame.Surface, app: App):
        surface.fill((12, 16, 20))
        sw, sh = surface.get_size()

        # ── Fixed header ─────────────────────────────────────────────
        app.draw_text(surface, "MUSEUM — SELECT EXHIBIT", 24, 16,
                      (0, 255, 200), app.font_lg)
        app.draw_text(surface, "Arrow keys / scroll to navigate, Enter to open, Esc to quit",
                      24, 40, (100, 130, 120), app.font_sm)

        # ── Scrollable card region ───────────────────────────────────
        region_top, region_bot = self._picker_viewport(app)
        region_h = region_bot - region_top

        # Determine card layout sizes
        card_w = 220
        card_h = 52
        pad_x = 12
        pad_y = 8
        cols = max(1, (sw - 48) // (card_w + pad_x))
        # Max chars that fit inside the card (monospace 11px ≈ 7px/char)
        char_w = app.font_sm.size("M")[0]
        max_chars = max(10, (card_w - 16) // max(1, char_w))

        # First pass: compute total content height and card positions
        self._card_rects.clear()
        content_y = 0  # virtual y within scrollable content
        card_positions: list[tuple[int, int, int, str | None]] = []
        for cat in self._cat_order:
            indices = self._cat_exhibits[cat]
            # Category header
            card_positions.append((0, content_y, -1, cat))
            content_y += 20
            col = 0
            row_start = content_y
            for idx in indices:
                cx = 24 + col * (card_w + pad_x)
                card_positions.append((cx, row_start, idx, None))
                col += 1
                if col >= cols:
                    col = 0
                    row_start += card_h + pad_y
            # Advance past this category's last row
            if col > 0:
                content_y = row_start + card_h + pad_y
            else:
                content_y = row_start
            content_y += 6  # inter-category gap

        self._picker_content_h = content_y
        self._clamp_scroll(app)
        scroll = self._picker_scroll

        # Set clip to the scrollable region
        old_clip = surface.get_clip()
        surface.set_clip(pygame.Rect(0, region_top, sw, region_h))

        # Second pass: draw visible cards
        for cx_raw, cy_raw, idx, cat_hdr in card_positions:
            screen_y = region_top + cy_raw - int(scroll)
            # Skip if fully outside viewport
            if screen_y + card_h < region_top or screen_y > region_bot:
                continue

            if cat_hdr is not None:
                cat_color = _CAT_COLORS.get(cat_hdr, (180, 180, 180))
                app.draw_text(surface, cat_hdr.upper(), 24, screen_y,
                              cat_color, app.font_sm)
                continue

            # Card
            ex = self._exhibits[idx]
            cx = cx_raw
            cy = screen_y
            rect = pygame.Rect(cx, cy, card_w, card_h)
            self._card_rects.append((rect, idx))

            selected = (idx == self._picker_sel)
            hovered = (idx == self._picker_hover)
            if selected:
                bg = (0, 60, 50)
                border = (0, 220, 180)
            elif hovered:
                bg = (30, 40, 35)
                border = (80, 140, 120)
            else:
                bg = (20, 26, 30)
                border = (50, 60, 55)

            pygame.draw.rect(surface, bg, rect)
            pygame.draw.rect(surface, border, rect, 2 if selected else 1)

            # Card content — text clipped to card width
            name_color = (255, 255, 255) if selected else (180, 200, 190)
            app.draw_text(surface, ex.name[:max_chars], cx + 8, cy + 6,
                          name_color, app.font_sm)

            # Subtitle (first non-empty line after title)
            desc_lines = ex.description.split("\n") if ex.description else []
            subtitle = ""
            for line in desc_lines[1:]:
                stripped = line.strip()
                if stripped:
                    subtitle = stripped
                    break
            if subtitle:
                cat_color = _CAT_COLORS.get(ex.category, (180, 180, 180))
                sub_color = cat_color if selected else (90, 110, 100)
                app.draw_text(surface, subtitle[:max_chars],
                              cx + 8, cy + 22, sub_color, app.font_sm)

            # Systems tag
            sys_line = ""
            for line in desc_lines:
                if line.strip().startswith("Systems:"):
                    sys_line = line.strip()[8:].strip()
                    break
            if sys_line:
                app.draw_text(surface, sys_line[:max_chars],
                              cx + 8, cy + 36,
                              (70, 90, 80), app.font_sm)

        # Restore clip
        surface.set_clip(old_clip)

        # ── Scrollbar indicator ──────────────────────────────────────
        if self._picker_content_h > region_h:
            bar_x = sw - 8
            ratio = region_h / self._picker_content_h
            thumb_h = max(16, int(region_h * ratio))
            if self._picker_content_h - region_h > 0:
                frac = scroll / (self._picker_content_h - region_h)
            else:
                frac = 0.0
            thumb_y = region_top + int(frac * (region_h - thumb_h))
            pygame.draw.line(surface, (40, 50, 45),
                             (bar_x + 2, region_top), (bar_x + 2, region_bot), 1)
            pygame.draw.rect(surface, (0, 180, 140),
                             pygame.Rect(bar_x, thumb_y, 5, thumb_h),
                             border_radius=2)

        # ── Description preview — fixed at bottom ────────────────────
        sel_ex = self._exhibits[self._picker_sel]
        preview_y = sh - 126
        panel_h = sh - preview_y
        panel = pygame.Surface((sw, panel_h), pygame.SRCALPHA)
        panel.fill((0, 0, 0, 180))
        surface.blit(panel, (0, preview_y))

        desc_lines = sel_ex.description.split("\n") if sel_ex.description else []
        px = 24
        py = preview_y + 6
        for line in desc_lines[:8]:
            color = (0, 220, 180) if desc_lines and line == desc_lines[0] else (160, 180, 170)
            app.draw_text(surface, line, px, py, color, app.font_sm)
            py += 14

    # ── Exhibit Drawing ──────────────────────────────────────────────

    def _draw_exhibit(self, surface: pygame.Surface, app: App):
        surface.fill((16, 20, 24))
        sw, sh = surface.get_size()
        tile_px = max(1, int(TILE_SIZE * self._zoom))
        ox = sw // 2 - int(self._cam_x * tile_px)
        oy = sh // 2 - int(self._cam_y * tile_px)
        flags = self._flags

        # Viewport-culled tile range
        c0 = max(0, -ox // tile_px)
        r0 = max(0, -oy // tile_px)
        c1 = min(self.map_w, (-ox + sw) // tile_px + 2)
        r1 = min(self.map_h, (-oy + sh) // tile_px + 2)

        # ── Tiles ────────────────────────────────────────────────────
        for row in range(r0, r1):
            for col in range(c0, c1):
                tid = self.tiles[row][col]
                color = TILE_COLORS.get(tid, (255, 0, 255))
                rect = pygame.Rect(ox + col * tile_px, oy + row * tile_px,
                                   tile_px, tile_px)
                pygame.draw.rect(surface, color, rect)
                if flags.grid:
                    pygame.draw.rect(surface, (60, 60, 60), rect, 1)

        # ── Exhibit overlays ─────────────────────────────────────────
        self._exhibit.draw(surface, ox, oy, app, self._eids,
                           tile_px=tile_px, flags=flags)

        # ── Entities ─────────────────────────────────────────────────
        for eid in self._eids:
            if not app.world.alive(eid):
                continue
            pos = app.world.get(eid, Position)
            sprite = app.world.get(eid, Sprite)
            if not pos or not sprite:
                continue
            sx = ox + int(pos.x * tile_px)
            sy = oy + int(pos.y * tile_px)

            # Exhibit entity-specific overlay (LOD colouring etc.)
            override = self._exhibit.draw_entity_overlay(
                surface, sx, sy, eid, app)
            draw_color = override if override else sprite.color

            # Scale character font by zoom
            font = app.font_lg if self._zoom >= 0.7 else app.font_sm
            app.draw_text(surface, sprite.char,
                          sx + tile_px // 4, sy + tile_px // 8,
                          color=draw_color, font=font)

            # -- Name labels --
            if flags.names:
                ident = app.world.get(eid, Identity)
                if ident:
                    app.draw_text(surface, ident.name, sx - 8, sy - 14,
                                  color=(160, 160, 160), font=app.font_sm)

            # -- Brain / combat mode --
            if flags.brain:
                brain = app.world.get(eid, Brain)
                if brain:
                    cs = brain.state.get("combat", {})
                    mode = cs.get("mode") if cs else None
                    if mode:
                        mc = _BRAIN_COLORS.get(mode, (180, 180, 180))
                        app.draw_text(surface, mode, sx - 4,
                                      sy + tile_px + 4,
                                      color=mc, font=app.font_sm)

            # -- Health bars --
            if flags.health:
                hp = app.world.get(eid, Health)
                if hp and hp.current < hp.maximum:
                    bar_w = max(4, tile_px - 4)
                    bar_x = sx + 2
                    bar_y = sy - 5
                    ratio = max(0.0, hp.current / hp.maximum)
                    pygame.draw.rect(surface, (40, 40, 40),
                                     (bar_x, bar_y, bar_w, 3))
                    bc = ((50, 200, 50) if ratio > 0.5
                          else (220, 200, 50) if ratio > 0.25
                          else (220, 50, 50))
                    pygame.draw.rect(surface, bc,
                                     (bar_x, bar_y,
                                      max(1, int(bar_w * ratio)), 3))

            # -- Position labels --
            if flags.positions:
                app.draw_text(surface,
                              f"({pos.x:.1f},{pos.y:.1f})",
                              sx - 12, sy + tile_px + 18,
                              (120, 140, 120), app.font_sm)

            # -- Faction disposition --
            if flags.faction:
                fac = app.world.get(eid, Faction)
                if fac:
                    fc = ((255, 80, 80) if fac.disposition == "hostile"
                          else (80, 200, 80) if fac.disposition == "friendly"
                          else (180, 180, 100))
                    y_off = tile_px + (32 if flags.positions else 18)
                    app.draw_text(surface, fac.disposition,
                                  sx - 10, sy + y_off,
                                  fc, app.font_sm)

        # ── HUD (fixed screen space) ────────────────────────────────
        self._draw_exhibit_header(surface, app)
        self._draw_flag_bar(surface, app)

        # Status bar
        info = self._exhibit.info_text(app, self._eids)
        if info:
            app.draw_text_bg(surface, info, 8, sh - 30, (180, 180, 180))

        # Zoom indicator + scale bar
        self._draw_scale_bar(surface, app, tile_px)

        # Info/description panel
        if self._show_info:
            self._draw_info_panel(surface, app)

    # ── Exhibit header bar ───────────────────────────────────────────

    def _draw_exhibit_header(self, surface: pygame.Surface, app: App):
        sw = surface.get_width()
        bar_h = 28
        bar = pygame.Surface((sw, bar_h), pygame.SRCALPHA)
        bar.fill((0, 0, 0, 180))
        surface.blit(bar, (0, 0))

        ex = self._exhibit
        cat_color = _CAT_COLORS.get(ex.category, (180, 180, 180))

        # Category tag
        app.draw_text(surface, ex.category.upper(), 8, 7,
                      cat_color, app.font_sm)

        # Exhibit name
        cat_w = len(ex.category) * 7 + 16
        app.draw_text(surface, ex.name, cat_w, 7,
                      (255, 255, 255), app.font_sm)

        # Controls hint
        app.draw_text(surface, "[Tab]Picker  [I]Info  [Home]Cam  [Esc]Back",
                      sw - 300, 7, (80, 100, 90), app.font_sm)

    # ── Debug-flag bar ───────────────────────────────────────────────

    def _draw_flag_bar(self, surface: pygame.Surface, app: App):
        """Draw debug-flag toggle bar below the tab header."""
        sw = surface.get_width()
        bar_y = 28
        bar = pygame.Surface((sw, 18), pygame.SRCALPHA)
        bar.fill((0, 0, 0, 120))
        surface.blit(bar, (0, bar_y))

        x = 8
        for attr, label, key in FLAG_META:
            on = getattr(self._flags, attr)
            tag = f"{key}:{label}"
            color = (0, 220, 160) if on else (60, 70, 65)
            app.draw_text(surface, tag, x, bar_y + 2, color, app.font_sm)
            x += len(tag) * 7 + 10

        app.draw_text(surface, "WASD:pan  Scroll:zoom",
                      sw - 160, bar_y + 2, (80, 100, 90), app.font_sm)

    # ── Info panel ───────────────────────────────────────────────────

    def _draw_info_panel(self, surface: pygame.Surface, app: App):
        """Draw the exhibit description overlay."""
        sw, sh = surface.get_size()
        panel_w = min(340, sw - 40)
        panel_h = min(360, sh - 120)
        px = sw - panel_w - 12
        py = 52

        # Background
        bg = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        bg.fill((0, 0, 0, 200))
        surface.blit(bg, (px, py))
        pygame.draw.rect(surface, (0, 180, 140), (px, py, panel_w, panel_h), 1)

        ex = self._exhibit
        lines = ex.description.split("\n") if ex.description else []

        tx = px + 10
        ty = py + 8
        for line in lines:
            if ty > py + panel_h - 16:
                break
            # Title line (first non-empty)
            if line.strip() and lines and line == lines[0]:
                app.draw_text(surface, line, tx, ty, (0, 255, 200), app.font_sm)
            elif line.strip().startswith("What to observe:"):
                app.draw_text(surface, line, tx, ty, (255, 220, 100), app.font_sm)
            elif line.strip().startswith("Controls:") or line.strip().startswith("Systems:"):
                app.draw_text(surface, line, tx, ty, (100, 200, 160), app.font_sm)
            elif line.strip().startswith(" -") or line.strip().startswith(" "):
                app.draw_text(surface, line, tx, ty, (170, 190, 180), app.font_sm)
            else:
                app.draw_text(surface, line, tx, ty, (150, 160, 155), app.font_sm)
            ty += 14

        # Close hint
        app.draw_text(surface, "[I] close", px + panel_w - 60, py + panel_h - 16,
                      (80, 100, 90), app.font_sm)

    # ── Scale bar ────────────────────────────────────────────────────

    _NICE_METRES = (1, 2, 5, 10, 20, 50)

    def _draw_scale_bar(self, surface: pygame.Surface, app: App,
                        tile_px: int):
        """Draw a zoom indicator and metre-scale ruler at bottom-right."""
        sw, sh = surface.get_size()

        # Pick the largest "nice" metre value that fits ≤ 150 px
        bar_px = 0
        bar_m = 1
        for m in self._NICE_METRES:
            px = m * tile_px
            if px <= 150:
                bar_px = px
                bar_m = m
        if bar_px < 8:
            bar_px = tile_px
            bar_m = 1

        # Position: bottom-right, above the info bar
        rx = sw - bar_px - 16
        ry = sh - 26

        # Draw ruler
        c = (100, 180, 140)
        pygame.draw.line(surface, c, (rx, ry), (rx + bar_px, ry), 2)
        pygame.draw.line(surface, c, (rx, ry - 4), (rx, ry + 4), 1)
        pygame.draw.line(surface, c, (rx + bar_px, ry - 4),
                         (rx + bar_px, ry + 4), 1)

        label = f"{bar_m} m" if bar_m < 1000 else f"{bar_m/1000:.0f} km"
        app.draw_text(surface, label,
                      rx + bar_px // 2 - 8, ry - 14,
                      c, app.font_sm)

        # Zoom text
        app.draw_text(surface, f"\u00d7{self._zoom:.2f}",
                      rx - 50, ry - 4, (100, 140, 120), app.font_sm)

    # ── Helpers ──────────────────────────────────────────────────────

    def _mouse_to_tile(self, app: App) -> tuple[int, int] | None:
        mx, my = app.mouse_pos()
        sw, sh = app._virtual_size
        tile_px = max(1, int(TILE_SIZE * self._zoom))
        ox = sw // 2 - int(self._cam_x * tile_px)
        oy = sh // 2 - int(self._cam_y * tile_px)
        col = (mx - ox) // tile_px
        row = (my - oy) // tile_px
        if 0 <= row < self.map_h and 0 <= col < self.map_w:
            return row, col
        return None
