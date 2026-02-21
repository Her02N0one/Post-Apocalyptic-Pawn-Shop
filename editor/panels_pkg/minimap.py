"""editor/panels_pkg/minimap.py — Minimap overlay."""

from __future__ import annotations

import pygame

from core.tiles import TILE_COLORS
from editor.ui import Theme
from editor.state import EditorState
from editor.layout import Layout


class Minimap:
    @staticmethod
    def _width():  return Layout.s(150)
    @staticmethod
    def _height(): return Layout.s(110)

    def __init__(self, state: EditorState):
        self.state = state

    def draw(self, surface: pygame.Surface, font_sm: pygame.font.Font):
        if not self.state.show_minimap:
            return
        L = Layout
        WIDTH = self._width()
        HEIGHT = self._height()
        sw, sh = surface.get_size()
        margin = L.pad_md
        mm_x = sw - L.inspector_w - WIDTH - margin
        mm_y = sh - HEIGHT - L.status_h - margin

        bg = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        bg.fill((20, 20, 24, 200))
        surface.blit(bg, (mm_x, mm_y))
        pygame.draw.rect(surface, Theme.PANEL_LITE,
                         (mm_x, mm_y, WIDTH, HEIGHT), 1)

        st = self.state
        if st.map_w == 0 or st.map_h == 0:
            return

        # Clip all minimap drawing to the minimap bounds
        mm_clip = pygame.Rect(mm_x, mm_y, WIDTH, HEIGHT)
        surface.set_clip(mm_clip)
        try:
            sx = (WIDTH - 4) / st.map_w
            sy = (HEIGHT - 4) / st.map_h
            scale = min(sx, sy)
            ox = mm_x + 2 + int((WIDTH - 4 - st.map_w * scale) / 2)
            oy = mm_y + 2 + int((HEIGHT - 4 - st.map_h * scale) / 2)
            pw = max(1, int(scale))

            for r in range(st.map_h):
                for c in range(st.map_w):
                    tid = st.tiles[r][c]
                    color = TILE_COLORS.get(tid, (80, 80, 80))
                    tx = ox + int(c * scale)
                    ty = oy + int(r * scale)
                    if pw <= 1:
                        surface.set_at((tx, ty), color)
                    else:
                        pygame.draw.rect(surface, color, (tx, ty, pw, pw))

            # Portal dots
            for ent in st.portals:
                ptl = ent.portal
                if ptl is None:
                    continue
                for tile in ptl.tiles:
                    if not isinstance(tile, (list, tuple)) or len(tile) < 2:
                        continue
                    pr, pc = tile[0], tile[1]
                    tx = ox + int(pc * scale) + pw // 2
                    ty = oy + int(pr * scale) + pw // 2
                    pygame.draw.circle(surface, Theme.PORTAL, (tx, ty),
                                       max(2, pw))

            # Entity dots
            for ent in st.entities:
                ex, ey = ent.position.x, ent.position.y
                tx = ox + int(ex * scale)
                ty = oy + int(ey * scale)
                pygame.draw.circle(surface, Theme.ENTITY, (tx, ty),
                                   max(1, pw))
        finally:
            surface.set_clip(None)
