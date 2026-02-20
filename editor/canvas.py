"""editor/canvas.py — Map canvas: tile rendering, coordinate transforms,
painting, entity markers, cursor preview.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pygame

# Add project root so imports work when running standalone
_root = str(Path(__file__).resolve().parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

from core.tiles import TILE_COLORS, TILE_NAMES, TILE_REGISTRY
from core.constants import TILE_SIZE
from editor.ui import Theme, draw_text
from editor.state import EditorState, Tool
from editor.layout import Layout

# Direction helpers
DIR_ARROWS = {"up": "\u25B2", "down": "\u25BC",
              "left": "\u25C0", "right": "\u25B6"}


class Canvas:
    """Handles the main tile map area — rendering and interaction."""

    def __init__(self, state: EditorState):
        self.state = state

    # ── Coordinate transforms ────────────────────────────────────

    def viewport_rect(self, surface: pygame.Surface) -> pygame.Rect:
        """Return the pixel rect of the map viewport."""
        L = Layout
        return pygame.Rect(L.canvas_x, L.canvas_y,
                           L.canvas_w, L.canvas_h)

    def screen_to_world(self, sx: int, sy: int,
                        surface: pygame.Surface) -> tuple[float, float]:
        vp = self.viewport_rect(surface)
        cx = vp.x + vp.w / 2
        cy = vp.y + vp.h / 2
        st = self.state
        wx = (sx - cx) / st.zoom - st.cam_x
        wy = (sy - cy) / st.zoom - st.cam_y
        return wx, wy

    def world_to_screen(self, wx: float, wy: float,
                        surface: pygame.Surface) -> tuple[int, int]:
        vp = self.viewport_rect(surface)
        cx = vp.x + vp.w / 2
        cy = vp.y + vp.h / 2
        st = self.state
        sx = int((wx + st.cam_x) * st.zoom + cx)
        sy = int((wy + st.cam_y) * st.zoom + cy)
        return sx, sy

    def screen_to_tile(self, sx: int, sy: int,
                       surface: pygame.Surface) -> tuple[int, int] | None:
        wx, wy = self.screen_to_world(sx, sy, surface)
        c = int(wx / TILE_SIZE)
        r = int(wy / TILE_SIZE)
        st = self.state
        if 0 <= r < st.map_h and 0 <= c < st.map_w:
            return r, c
        return None

    # ── Drawing ──────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, font: pygame.font.Font,
             font_sm: pygame.font.Font):
        vp = self.viewport_rect(surface)
        # Clip to viewport
        surface.set_clip(vp)
        # Background
        pygame.draw.rect(surface, Theme.BG, vp)

        st = self.state
        ts = int(TILE_SIZE * st.zoom)
        if ts < 1:
            surface.set_clip(None)
            return

        sw, sh = surface.get_size()

        # Draw tiles
        for r in range(st.map_h):
            for c in range(st.map_w):
                sx, sy = self.world_to_screen(c * TILE_SIZE, r * TILE_SIZE,
                                              surface)
                if sx + ts < vp.x or sy + ts < vp.y or sx > vp.right or sy > vp.bottom:
                    continue
                tid = st.tiles[r][c]
                color = TILE_COLORS.get(tid, (120, 120, 120))
                rect = pygame.Rect(sx, sy, ts, ts)
                pygame.draw.rect(surface, color, rect)
                if st.show_grid and ts >= 8:
                    pygame.draw.rect(surface, Theme.GRID, rect, 1)

        # Draw portals
        for p in st.portals:
            for tile in p["tiles"]:
                r, c = tile
                sx, sy = self.world_to_screen(c * TILE_SIZE, r * TILE_SIZE,
                                              surface)
                center = (sx + ts // 2, sy + ts // 2)
                radius = max(4, ts // 3)
                pygame.draw.circle(surface, Theme.PORTAL, center, radius)
                pygame.draw.circle(surface, (255, 255, 255), center, radius, 1)
                if ts >= 16:
                    draw_text(surface, p["target_zone"][:8],
                              sx + 2, sy + ts + 1, Theme.TEXT_DIM, font_sm)
                    d = p.get("exit_direction", "up")
                    arrow = DIR_ARROWS.get(d, "?")
                    draw_text(surface, arrow, center[0] - 4, center[1] - 6,
                              (255, 255, 255), font_sm)

        # Draw anchor
        ax, ay = st.anchor
        asx, asy = self.world_to_screen(ax * TILE_SIZE, ay * TILE_SIZE,
                                        surface)
        _ar = Layout.s(8)
        _al = Layout.s(10)
        pygame.draw.circle(surface, Theme.ANCHOR, (asx, asy), _ar, 2)
        pygame.draw.line(surface, Theme.ANCHOR,
                         (asx - _al, asy), (asx + _al, asy), 1)
        pygame.draw.line(surface, Theme.ANCHOR,
                         (asx, asy - _al), (asx, asy + _al), 1)

        # Draw entities
        self._draw_entities(surface, font, font_sm, ts)

        # Draw cursor
        self._draw_cursor(surface, ts)

        surface.set_clip(None)

    def _draw_entities(self, surface: pygame.Surface,
                       font: pygame.font.Font,
                       font_sm: pygame.font.Font,
                       ts: int):
        st = self.state
        for i, ent in enumerate(st.entities):
            ex, ey = ent.position.x, ent.position.y
            sx, sy = self.world_to_screen(ex * TILE_SIZE, ey * TILE_SIZE,
                                          surface)

            sprite = ent.sprite
            if sprite is None:
                # Try prefab defaults
                _try_import_prefabs()
                if _PREFAB_DEFAULTS:
                    defaults = _PREFAB_DEFAULTS.get(ent.prefab, {})
                    sprite_d = defaults.get("sprite", {})
                    char = sprite_d.get("char", "?")
                    color = tuple(sprite_d.get("color", [200, 200, 200]))
                else:
                    char = "?"
                    color = (200, 200, 200)
            else:
                char = sprite.char
                color = tuple(sprite.color)

            name = ent.display_name

            radius = max(Layout.s(6), ts // 3)
            is_sel = (i == st.selected_entity)

            if ent.tile_entity is not None:
                ring_col = Theme.ACCENT if is_sel else Theme.ACCENT2
                half = radius
                pygame.draw.rect(surface, ring_col,
                                 (sx - half, sy - half,
                                  half * 2, half * 2), 2)
            else:
                ring_col = Theme.ACCENT if is_sel else Theme.ENTITY
                pygame.draw.circle(surface, ring_col, (sx, sy), radius, 2)

            if ts >= 12:
                glyph = font.render(char, True, color)
                surface.blit(glyph, (sx - glyph.get_width() // 2,
                                     sy - glyph.get_height() // 2))
            if ts >= 16 and name:
                label = name[:14]
                draw_text(surface, label,
                          sx - len(label) * 3, sy + radius + 2,
                          Theme.TEXT_DIM, font_sm)

    def _draw_cursor(self, surface: pygame.Surface, ts: int):
        st = self.state
        if st.hover_tile is None:
            return
        r, c = st.hover_tile
        half = st.brush_size // 2

        if st.tool in (Tool.BRUSH, Tool.ERASER, Tool.FILL):
            for rr in range(r - half, r - half + st.brush_size):
                for cc in range(c - half, c - half + st.brush_size):
                    if 0 <= rr < st.map_h and 0 <= cc < st.map_w:
                        sx, sy = self.world_to_screen(
                            cc * TILE_SIZE, rr * TILE_SIZE, surface)
                        rect = pygame.Rect(sx, sy, ts, ts)
                        cursor_surf = pygame.Surface((ts, ts), pygame.SRCALPHA)
                        if st.tool == Tool.ERASER:
                            cursor_surf.fill((255, 80, 80, 60))
                        else:
                            color = TILE_COLORS.get(st.selected_tile,
                                                    (200, 200, 200))
                            cursor_surf.fill((*color, 80))
                        surface.blit(cursor_surf, (sx, sy))
                        pygame.draw.rect(surface, (255, 255, 255), rect, 1)
        elif st.tool in (Tool.ENTITY, Tool.PORTAL, Tool.ANCHOR):
            sx, sy = self.world_to_screen(c * TILE_SIZE, r * TILE_SIZE,
                                          surface)
            rect = pygame.Rect(sx, sy, ts, ts)
            pygame.draw.rect(surface, (255, 255, 255), rect, 1)


# ── Lazy import of prefab defaults ──────────────────────────────────

_PREFAB_DEFAULTS: dict = {}
_prefabs_loaded = False


def _try_import_prefabs():
    global _PREFAB_DEFAULTS, _prefabs_loaded
    if _prefabs_loaded:
        return
    _prefabs_loaded = True
    try:
        from systems.spawner import _PREFAB_DEFAULTS as pd
        _PREFAB_DEFAULTS.update(pd)
    except ImportError:
        pass


def get_prefab_defaults() -> dict:
    _try_import_prefabs()
    return _PREFAB_DEFAULTS
