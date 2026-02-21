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
        portal_ents = st.portals  # property: entities with portal component
        ITEM_H = self._item_h()
        br = L.border_r
        fh = font_sm.get_height()
        line1_off, line2_off = two_line_offsets(ITEM_H, fh)
        text_x_off = L.s(18)

        if not portal_ents:
            draw_empty_hint(surface, ["No portals.", "Use Portal tool"],
                            region.left + L.pad_md,
                            region.content_top, font_sm)
            return

        self._item_rects.clear()
        y = int(region.content_top - self.scroll_y)

        for pent in portal_ents:
            ptl = pent.portal
            dest = ptl.target_zone or "?"
            tile_count = len(ptl.tiles)
            # Find the entity's index in the full entities list
            try:
                eidx = st.entities.index(pent)
            except ValueError:
                continue

            ir = pygame.Rect(region.left + L.pad_sm, y,
                             region.pw - L.pad_md, ITEM_H - 2)
            if ir.bottom >= region.clip.top and ir.top < region.clip.bottom:
                hov = ir.collidepoint(region.mx, region.my)
                sel = (eidx == st.selected_entity)
                draw_item_row(surface, ir, hovered=hov, selected=sel,
                              border=True, br=br)

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

            self._item_rects.append((ir, eidx))
            y += ITEM_H

        self._total_h = len(portal_ents) * ITEM_H

    def on_item_click(self, event: pygame.event.Event,
                      region: PanelRegion) -> str | None:
        for ir, idx in self._item_rects:
            if ir.collidepoint(event.pos):
                return f"select_entity:{idx}"
        return None
