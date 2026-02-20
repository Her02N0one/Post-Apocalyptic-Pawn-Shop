"""editor/panels_pkg/portal_panel.py — Portal list panel."""

from __future__ import annotations

import pygame

from editor.ui import (
    Theme, draw_text, draw_item_row, draw_empty_hint,
    two_line_offsets,
)
from editor.state import EditorState
from editor.layout import Layout
from editor.panels_pkg.base import PanelBase, PanelRegion


class PortalPanel(PanelBase):
    """List and manage portal connections in the current zone."""

    title = "PORTALS"

    @staticmethod
    def _item_h(): return Layout.s(38)

    def __init__(self, state: EditorState):
        super().__init__()
        self.state = state
        self._item_rects: list[tuple[pygame.Rect, int]] = []

    # ── PanelBase hooks ──────────────────────────────────────────

    def draw_content(self, surface: pygame.Surface, font: pygame.font.Font,
                     font_sm: pygame.font.Font, region: PanelRegion):
        L = Layout
        st = self.state
        portals = st.portals
        ITEM_H = self._item_h()
        br = L.border_r
        fh = font_sm.get_height()
        line1_off, line2_off = two_line_offsets(ITEM_H, fh)
        text_x_off = L.s(18)

        if not portals:
            draw_empty_hint(surface, ["No portals.", "Use Portal tool"],
                            region.left + L.pad_md,
                            region.content_top, font_sm)
            return

        self._item_rects.clear()
        y = int(region.content_top - self.scroll_y)

        for i, portal in enumerate(portals):
            dest = portal.get("dest_zone",
                              portal.get("target_zone", "?"))
            tiles = portal.get("tiles", [])
            tile_count = len(tiles)

            ir = pygame.Rect(region.left + L.pad_sm, y,
                             region.pw - L.pad_md, ITEM_H - 2)
            if ir.bottom >= region.clip.top and ir.top < region.clip.bottom:
                hov = ir.collidepoint(region.mx, region.my)
                draw_item_row(surface, ir, hovered=hov, border=True, br=br)

                draw_text(surface, "\u25A3", ir.x + L.pad_sm,
                          ir.y + line1_off, Theme.PORTAL, font_sm)
                dest_label = (dest[:14] if region.pw < L.s(160)
                              else dest)
                draw_text(surface, f"\u2192 {dest_label}",
                          ir.x + text_x_off, ir.y + line1_off,
                          Theme.TEXT, font_sm)
                draw_text(surface, f"{tile_count} tile(s)",
                          ir.x + text_x_off, ir.y + line2_off,
                          Theme.TEXT_DIM, font_sm)

            self._item_rects.append((ir, i))
            y += ITEM_H

        self._total_h = len(portals) * ITEM_H

    def on_item_click(self, event: pygame.event.Event,
                      region: PanelRegion) -> str | None:
        for ir, idx in self._item_rects:
            if ir.collidepoint(event.pos):
                return f"select_portal:{idx}"
        return None
