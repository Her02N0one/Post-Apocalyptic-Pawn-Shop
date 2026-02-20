"""editor/panels_pkg/template_panel.py — Room template panel."""

from __future__ import annotations

import os

import pygame

from editor.ui import (
    Theme, draw_text, draw_item_row, draw_empty_hint,
)
from editor.state import EditorState, TEMPLATES_DIR
from editor.layout import Layout
from editor.panels_pkg.base import PanelBase, PanelRegion


class RoomTemplatePanel(PanelBase):
    """Browse and place room templates."""

    title = "TEMPLATES"

    def __init__(self, state: EditorState):
        super().__init__()
        self.state = state
        self._templates: list[str] = []
        self._cache_ready = False
        self._item_rects: list[tuple[pygame.Rect, str]] = []

    def _ensure_cache(self):
        if self._cache_ready:
            return
        self._cache_ready = True
        dirs = [TEMPLATES_DIR]
        rooms_dir = TEMPLATES_DIR / "rooms"
        if rooms_dir.exists():
            dirs.append(rooms_dir)
        self._templates = []
        for d in dirs:
            if d.exists():
                try:
                    for f in sorted(os.listdir(d)):
                        if f.endswith(".json"):
                            self._templates.append(f)
                except OSError:
                    pass

    def refresh(self):
        self._cache_ready = False

    # ── PanelBase hooks ──────────────────────────────────────────

    def draw_content(self, surface: pygame.Surface, font: pygame.font.Font,
                     font_sm: pygame.font.Font, region: PanelRegion):
        self._ensure_cache()
        L = Layout

        if not self._templates:
            draw_empty_hint(surface,
                            ["No templates.",
                             "Editors \u2192 Room Templates"],
                            region.left + L.pad_md,
                            region.content_top, font_sm)
            return

        ITEM_H = L.item_h
        br = L.border_r
        fh = font_sm.get_height()
        text_x_off = L.s(18)
        text_y_off = max(1, (ITEM_H - 2 - fh) // 2)

        self._item_rects.clear()
        y = int(region.content_top - self.scroll_y)

        for fname in self._templates:
            label = (os.path.splitext(fname)[0]
                     .replace("_", " ").title())
            ir = pygame.Rect(region.left + L.pad_sm, y,
                             region.pw - L.pad_md, ITEM_H - 2)
            if ir.bottom >= region.clip.top and ir.top < region.clip.bottom:
                hov = ir.collidepoint(region.mx, region.my)
                draw_item_row(surface, ir, hovered=hov, br=br)
                draw_text(surface, "\u2587", ir.x + L.pad_sm,
                          ir.y + L.pad_sm, Theme.ACCENT, font_sm)
                draw_text(surface,
                          (label[:18] if region.pw < L.s(160) else label),
                          ir.x + text_x_off, ir.y + text_y_off,
                          Theme.TEXT, font_sm)
            self._item_rects.append((ir, fname))
            y += ITEM_H

        self._total_h = len(self._templates) * ITEM_H

    def on_item_click(self, event: pygame.event.Event,
                      region: PanelRegion) -> str | None:
        for ir, fname in self._item_rects:
            if ir.collidepoint(event.pos):
                return f"select_template:{fname}"
        return None
