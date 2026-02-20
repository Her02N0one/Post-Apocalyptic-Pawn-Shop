"""editor/panels_pkg/zone_nav.py — Zone navigation bar."""

from __future__ import annotations

import pygame

from editor.ui import Theme, draw_text
from editor.state import EditorState
from editor.layout import Layout


class ZoneNav:
    """Thin bar across the top showing zone name, dirty indicator,
    back/forward navigation, and connected-zone tabs.
    """

    def __init__(self, state: EditorState):
        self.state = state
        self._back_rect = pygame.Rect(0, 0, 0, 0)
        self._fwd_rect = pygame.Rect(0, 0, 0, 0)
        self._target_rects: list[tuple[str, pygame.Rect]] = []

    def draw(self, surface: pygame.Surface, font_sm: pygame.font.Font):
        L = Layout
        _s = L.s
        sw = surface.get_width()
        h = L.nav_h
        top = L.menu_h
        fh = font_sm.get_height()
        text_y = top + max(1, (h - fh) // 2)

        pygame.draw.rect(surface, (36, 36, 42), (0, top, sw, h))
        pygame.draw.line(surface, Theme.BORDER,
                         (0, top + h - 1), (sw, top + h - 1))

        st = self.state
        x = L.pad_md
        btn_pad = L.pad_sm
        btn_w = _s(20)
        arr_w = _s(14)

        # Back / Forward arrows
        can_back = st.zone_history_idx > 0
        can_fwd = st.zone_history_idx < len(st.zone_history) - 1

        self._back_rect = pygame.Rect(x, top + btn_pad, btn_w, h - btn_pad * 2)
        bc = Theme.TEXT if can_back else (60, 60, 66)
        draw_text(surface, "\u25C0", x + L.pad_sm, text_y, bc, font_sm)
        x += btn_w + L.pad_sm

        self._fwd_rect = pygame.Rect(x, top + btn_pad, btn_w, h - btn_pad * 2)
        fc = Theme.TEXT if can_fwd else (60, 60, 66)
        draw_text(surface, "\u25B6", x + L.pad_sm, text_y, fc, font_sm)
        x += btn_w + L.pad_md

        # Zone name + dirty + FP flag
        label = f"{st.zone_name}{'*' if st.dirty else ''}"
        draw_text(surface, label, x, text_y, Theme.ACCENT, font_sm)
        x += max(_s(60), font_sm.size(label)[0] + arr_w)

        if st.first_person:
            draw_text(surface, "FP", x, text_y, Theme.SUCCESS, font_sm)
            x += _s(24)

        # Connected zones
        self._target_rects.clear()
        targets = st.connected_zones()
        if targets:
            draw_text(surface, "\u2192", x, text_y,
                      Theme.TEXT_DIM, font_sm)
            x += arr_w
        for tz in targets:
            tw = font_sm.size(tz)[0] + L.pad_lg
            if x + tw > sw - L.pad_lg:
                break
            r = pygame.Rect(x, top + btn_pad, tw, h - btn_pad * 2)
            mx, my = pygame.mouse.get_pos()
            hov = r.collidepoint(mx, my)
            if hov:
                pygame.draw.rect(surface, Theme.HIGHLIGHT, r,
                                 border_radius=L.border_r)
            draw_text(surface, tz, x + L.pad_md, text_y,
                      Theme.PORTAL if hov else Theme.TEXT_DIM, font_sm)
            self._target_rects.append((tz, r))
            x += tw + L.pad_sm

    def handle_event(self, event: pygame.event.Event) -> str | None:
        """Returns ``'nav:zone_name'`` or ``None``."""
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return None
        mx, my = event.pos
        nav_top = Layout.menu_h
        nav_bot = Layout.menu_h + Layout.nav_h
        if my < nav_top or my > nav_bot:
            return None

        if self._back_rect.collidepoint(mx, my):
            name = self.state.nav_back()
            if name:
                return f"nav:{name}"
        if self._fwd_rect.collidepoint(mx, my):
            name = self.state.nav_forward()
            if name:
                return f"nav:{name}"
        for tz, r in self._target_rects:
            if r.collidepoint(mx, my):
                return f"nav:{tz}"
        return None
