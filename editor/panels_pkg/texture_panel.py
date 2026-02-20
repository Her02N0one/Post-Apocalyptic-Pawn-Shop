"""editor/panels_pkg/texture_panel.py — Texture browser panel."""

from __future__ import annotations

import os

import pygame

from editor.ui import Theme, draw_text
from editor.state import EditorState
from editor.layout import Layout
from editor.panels_pkg.base import PanelBase, PanelRegion


class TextureBrowserPanel(PanelBase):
    """Browse imported texture PNGs as a thumbnail grid."""

    title = "TEXTURES"

    def __init__(self, state: EditorState, atlas=None):
        super().__init__()
        self.state = state
        self._atlas = atlas
        self._item_rects: list[tuple[pygame.Rect, str]] = []
        self._tex_list: list[str] = []
        self._cache_ready = False

    def _ensure_cache(self):
        if self._cache_ready:
            return
        self._cache_ready = True
        try:
            from core.tiles import TILE_TEX_DIR
            self._tex_list = sorted(
                os.path.splitext(f)[0]
                for f in os.listdir(TILE_TEX_DIR)
                if f.endswith(".png")
            )
        except (FileNotFoundError, OSError):
            self._tex_list = []

    def refresh(self):
        self._cache_ready = False

    # ── PanelBase hooks ──────────────────────────────────────────

    def draw_content(self, surface: pygame.Surface, font: pygame.font.Font,
                     font_sm: pygame.font.Font, region: PanelRegion):
        self._ensure_cache()
        L = Layout
        THUMB = L.thumb
        PAD = L.pad_sm
        cols = max(1, (region.pw - L.pad_md) // (THUMB + PAD))

        self._item_rects.clear()
        y = int(region.content_top - self.scroll_y)

        for i, key in enumerate(self._tex_list):
            col = i % cols
            row_y = y + (i // cols) * (THUMB + PAD + L.pad_lg)
            tx = region.left + L.pad_sm + col * (THUMB + PAD)
            ty = row_y

            ir = pygame.Rect(tx, ty, THUMB, THUMB)
            if ir.bottom >= region.clip.top and ir.top < region.clip.bottom:
                if self._atlas:
                    try:
                        tex_surf = self._atlas.get_by_key(key)
                        thumb = pygame.transform.scale(
                            tex_surf, (THUMB, THUMB))
                        surface.blit(thumb, ir.topleft)
                    except (KeyError, pygame.error):
                        pygame.draw.rect(surface, (60, 60, 60), ir)
                else:
                    pygame.draw.rect(surface, (60, 60, 60), ir)
                if ir.collidepoint(region.mx, region.my):
                    pygame.draw.rect(surface, Theme.ACCENT, ir, 2)
                    draw_text(surface, key, tx,
                              ty + THUMB + 1, Theme.TEXT, font_sm)

            self._item_rects.append((ir, key))

        self._total_h = (
            ((len(self._tex_list) + cols - 1) // max(1, cols))
            * (THUMB + PAD + L.pad_lg)
        )

    def on_item_click(self, event: pygame.event.Event,
                      region: PanelRegion) -> str | None:
        for ir, key in self._item_rects:
            if ir.collidepoint(event.pos):
                return f"copy_tex:{key}"
        return None
