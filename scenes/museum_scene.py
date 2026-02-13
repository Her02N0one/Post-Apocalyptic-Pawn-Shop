"""scenes/museum_scene.py — Interactive Exhibit Museum.

Thin tab-bar host that delegates to Exhibit subclasses.

  [1] AI Brains   [2] Combat   [3] LOD Demo   [4] Pathfinding
  [5] Faction     [6] Stealth  [7] Particles  [8] Needs

Controls:
    1-8         — switch exhibit tab
    Space       — start / reset the active demo
    LMB / RMB   — interact (exhibit-specific)
    Escape / F3 — back to scene picker
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
from scenes.exhibits.base import Exhibit
from scenes.exhibits.ai_exhibit import AIExhibit
from scenes.exhibits.combat_exhibit import CombatExhibit
from scenes.exhibits.lod_exhibit import LODExhibit
from scenes.exhibits.pathfinding_exhibit import PathfindingExhibit
from scenes.exhibits.faction_exhibit import FactionExhibit
from scenes.exhibits.stealth_exhibit import StealthExhibit
from scenes.exhibits.particle_exhibit import ParticleExhibit
from scenes.exhibits.needs_exhibit import NeedsExhibit

_ARENA_W = 30
_ARENA_H = 20
_TILE_WALL = 1
_TILE_GRASS = 0

_SHORT = ["AI", "Combat", "LOD", "Path", "Faction", "Stealth", "FX", "Needs"]


def _make_arena() -> list[list[int]]:
    tiles = [[0] * _ARENA_W for _ in range(_ARENA_H)]
    for r in range(_ARENA_H):
        tiles[r][0] = _TILE_WALL
        tiles[r][_ARENA_W - 1] = _TILE_WALL
    for c in range(_ARENA_W):
        tiles[0][c] = _TILE_WALL
        tiles[_ARENA_H - 1][c] = _TILE_WALL
    return tiles


class MuseumScene(Scene):
    """Interactive Exhibit Museum — thin host for Exhibit tabs."""

    def __init__(self):
        self.zone = "__museum__"
        self.tab = 0
        self.tiles = _make_arena()
        self.map_w = _ARENA_W
        self.map_h = _ARENA_H

        self._eids: list[int] = []
        self._cam_x = _ARENA_W / 2.0
        self._cam_y = _ARENA_H / 2.0

        # Build the exhibit list — order matches tab indices
        self._exhibits: list[Exhibit] = [
            AIExhibit(),          # 0
            CombatExhibit(),      # 1
            LODExhibit(),         # 2
            PathfindingExhibit(), # 3
            FactionExhibit(),     # 4
            StealthExhibit(),     # 5
            ParticleExhibit(),    # 6
            NeedsExhibit(),       # 7
        ]

    @property
    def _exhibit(self) -> Exhibit:
        return self._exhibits[self.tab]

    # ── Lifecycle ────────────────────────────────────────────────────

    def on_enter(self, app: App):
        if not app.world.res(Camera):
            app.world.set_res(Camera())
        if not app.world.res(GameClock):
            app.world.set_res(GameClock())
        ZONE_MAPS[self.zone] = self.tiles
        self._setup_tab(app)

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
        self.tiles = _make_arena()
        ZONE_MAPS[self.zone] = self.tiles
        self._eids = self._exhibit.setup(app, self.zone, self.tiles)

    # ── Events ───────────────────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event, app: App):
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                app.pop_scene()
                return
            if event.key in (pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4,
                              pygame.K_5, pygame.K_6, pygame.K_7, pygame.K_8):
                new_tab = event.key - pygame.K_1
                if new_tab < len(self._exhibits):
                    self.tab = new_tab
                    self._setup_tab(app)
                return
            if event.key == pygame.K_SPACE:
                result = self._exhibit.on_space(app)
                if result == "reset":
                    self._setup_tab(app)
                return

        # Delegate to active exhibit
        self._exhibit.handle_event(event, app,
                                   lambda: self._mouse_to_tile(app))

    # ── Update ───────────────────────────────────────────────────────

    def update(self, dt: float, app: App):
        clock = app.world.res(GameClock)
        if clock:
            clock.time += dt
        self._exhibit.update(app, dt, self.tiles, self._eids)
        app.world.purge()

    # ── Draw ─────────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, app: App):
        surface.fill((16, 20, 24))
        sw, sh = surface.get_size()
        ox = sw // 2 - int(self._cam_x * TILE_SIZE)
        oy = sh // 2 - int(self._cam_y * TILE_SIZE)

        # Tiles
        for row in range(self.map_h):
            for col in range(self.map_w):
                tid = self.tiles[row][col]
                color = TILE_COLORS.get(tid, (255, 0, 255))
                rect = pygame.Rect(ox + col * TILE_SIZE, oy + row * TILE_SIZE,
                                   TILE_SIZE, TILE_SIZE)
                pygame.draw.rect(surface, color, rect)

        # Exhibit overlays (vision cones, rings, paths…)
        self._exhibit.draw(surface, ox, oy, app, self._eids)

        # Entities
        for eid in self._eids:
            if not app.world.alive(eid):
                continue
            pos = app.world.get(eid, Position)
            sprite = app.world.get(eid, Sprite)
            if not pos or not sprite:
                continue
            sx = ox + int(pos.x * TILE_SIZE)
            sy = oy + int(pos.y * TILE_SIZE)

            # Exhibit entity overlay (e.g. LOD colouring)
            override = self._exhibit.draw_entity_overlay(
                surface, sx, sy, eid, app)
            draw_color = override if override else sprite.color
            app.draw_text(surface, sprite.char, sx + 8, sy + 4,
                          color=draw_color, font=app.font_lg)

            # Name label
            ident = app.world.get(eid, Identity)
            if ident:
                app.draw_text(surface, ident.name, sx - 8, sy - 14,
                              color=(160, 160, 160), font=app.font_sm)

            # Brain state (for tabs that show combat modes)
            if self.tab in (0, 1, 4, 5):
                brain = app.world.get(eid, Brain)
                if brain:
                    cs = brain.state.get("combat", {})
                    mode = cs.get("mode") if cs else None
                    if mode:
                        mode_color = {
                            "idle": (150, 150, 150),
                            "chase": (255, 200, 80),
                            "attack": (255, 80, 80),
                            "flee": (80, 180, 255),
                            "return": (180, 120, 255),
                        }.get(mode, (180, 180, 180))
                        app.draw_text(surface, mode, sx - 4, sy + 20,
                                      color=mode_color, font=app.font_sm)

            # Health bar
            hp = app.world.get(eid, Health)
            if hp and hp.current < hp.maximum:
                bar_w = TILE_SIZE - 4
                bar_x = sx + 2
                bar_y = sy - 5
                ratio = max(0.0, hp.current / hp.maximum)
                pygame.draw.rect(surface, (40, 40, 40),
                                 (bar_x, bar_y, bar_w, 3))
                bc = ((50, 200, 50) if ratio > 0.5
                      else (220, 200, 50) if ratio > 0.25
                      else (220, 50, 50))
                pygame.draw.rect(surface, bc,
                                 (bar_x, bar_y, max(1, int(bar_w * ratio)), 3))

        # Tab header
        self._draw_tab_header(surface, app)
        # Status bar
        info = self._exhibit.info_text(app, self._eids)
        if info:
            app.draw_text_bg(surface, info, 8, sh - 30, (180, 180, 180))

    # ── Tab header ───────────────────────────────────────────────────

    def _draw_tab_header(self, surface: pygame.Surface, app: App):
        sw = surface.get_width()
        bar_h = 28
        bar = pygame.Surface((sw, bar_h), pygame.SRCALPHA)
        bar.fill((0, 0, 0, 180))
        surface.blit(bar, (0, 0))

        app.draw_text(surface, "MUSEUM", 8, 7, (0, 255, 200), app.font_sm)

        x = 60
        for i, short in enumerate(_SHORT):
            label = f"{i+1}:{short}"
            if i == self.tab:
                tw = len(label) * 7 + 8
                hl = pygame.Surface((tw, 18), pygame.SRCALPHA)
                hl.fill((0, 180, 140, 120))
                surface.blit(hl, (x - 4, 5))
                app.draw_text(surface, label, x, 7,
                              (255, 255, 255), app.font_sm)
            else:
                app.draw_text(surface, label, x, 7,
                              (120, 150, 140), app.font_sm)
            x += len(label) * 7 + 12

        app.draw_text(surface, "[Esc]", sw - 42, 7,
                      (80, 100, 90), app.font_sm)

    # ── Helpers ──────────────────────────────────────────────────────

    def _mouse_to_tile(self, app: App) -> tuple[int, int] | None:
        mx, my = app.mouse_pos()
        sw, sh = app._virtual_size
        ox = sw // 2 - int(self._cam_x * TILE_SIZE)
        oy = sh // 2 - int(self._cam_y * TILE_SIZE)
        col = (mx - ox) // TILE_SIZE
        row = (my - oy) // TILE_SIZE
        if 0 <= row < self.map_h and 0 <= col < self.map_w:
            return row, col
        return None
