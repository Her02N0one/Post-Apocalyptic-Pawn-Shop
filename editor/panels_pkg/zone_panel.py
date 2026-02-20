"""editor/panels_pkg/zone_panel.py — Zone list panel."""

from __future__ import annotations

import pygame

from editor.ui import Theme, draw_text, draw_item_row
from editor.state import EditorState, list_zones
from editor.layout import Layout
from editor.panels_pkg.base import PanelBase, PanelRegion


class ZonePanel(PanelBase):
    """Zone list panel — browse, load, create zones without modals."""

    title = "ZONES"

    def __init__(self, state: EditorState):
        super().__init__()
        self.state = state
        self._zone_list: list[str] = []
        self._refresh_timer: float = 0.0

    # ── PanelBase hooks ──────────────────────────────────────────

    def draw_content(self, surface: pygame.Surface, font: pygame.font.Font,
                     font_sm: pygame.font.Font, region: PanelRegion):
        self._refresh_timer -= 0.016
        if self._refresh_timer <= 0:
            self._zone_list = list_zones()
            self._refresh_timer = 2.0

        L = Layout
        item_h = L.item_h
        fh = font_sm.get_height()
        text_off = max(1, (item_h - fh) // 2)
        st = self.state

        y = int(region.content_top - self.scroll_y)

        for zname in self._zone_list:
            ir = pygame.Rect(region.left + 2, y,
                             region.pw - 4, item_h - 2)
            if ir.bottom >= region.clip.top and ir.top < region.clip.bottom:
                is_cur = (zname == st.zone_name)
                hov = ir.collidepoint(region.mx, region.my)
                draw_item_row(surface, ir, hovered=hov, selected=is_cur,
                              br=L.border_r)
                color = Theme.ACCENT2 if is_cur else Theme.TEXT
                name_display = (zname[:16] if region.pw < L.s(150)
                                else zname)
                draw_text(surface, name_display, ir.x + L.pad_md,
                          ir.y + text_off, color, font_sm)
            y += item_h

        self._total_h = len(self._zone_list) * item_h

    def on_item_click(self, event: pygame.event.Event,
                      region: PanelRegion) -> str | None:
        L = Layout
        item_h = L.item_h
        idx = int((event.pos[1] - region.content_top + self.scroll_y)
                  / item_h)
        if 0 <= idx < len(self._zone_list):
            return f"load:{self._zone_list[idx]}"
        return None
