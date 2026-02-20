"""editor/panels_pkg/status_bar.py — Bottom status bar."""

from __future__ import annotations

import pygame

from core.tiles import TILE_NAMES
from editor.ui import Theme, draw_text
from editor.state import EditorState, Tool
from editor.layout import Layout


class StatusBar:
    def __init__(self, state: EditorState):
        self.state = state

    def draw(self, surface: pygame.Surface, font_sm: pygame.font.Font):
        L = Layout
        sw, sh = surface.get_size()
        bar_y = sh - L.status_h
        fh = font_sm.get_height()
        text_y = bar_y + max(1, (L.status_h - fh) // 2)
        pygame.draw.rect(surface, Theme.PANEL,
                         (0, bar_y, sw, L.status_h))

        st = self.state
        if st.hover_tile:
            r, c = st.hover_tile
            # Bounds-check before accessing tiles array
            if 0 <= r < st.map_h and 0 <= c < st.map_w:
                tid = st.tiles[r][c]
                tname = TILE_NAMES.get(tid, "?")
                ent_info = ""
                if st.tool == Tool.ENTITY:
                    eidx = st.entity_at(r, c)
                    if eidx >= 0:
                        ent_info = f" ent={st.entity_name(eidx)}"
                info = (f"({c},{r}) tile={tid}({tname}) "
                        f"{st.map_w}x{st.map_h} "
                        f"z={st.zoom:.1f}x{ent_info}")
                draw_text(surface, info, L.pad_md, text_y,
                          Theme.TEXT_DIM, font_sm)

        # Toast
        if st.toast_timer > 0:
            alpha = min(1.0, st.toast_timer * 2) * 255
            toast_surf = font_sm.render(st.toast_msg, True, Theme.ACCENT2)
            toast_surf.set_alpha(int(alpha))
            surface.blit(toast_surf,
                         (sw // 2 - toast_surf.get_width() // 2,
                          bar_y - L.s(26)))

        # Keyboard hints (right side)
        hints = "^S ^Z ^Y  G:Grid M:Map [:- ]:+ F:FP"
        hw = font_sm.size(hints)[0]
        draw_text(surface, hints, sw - hw - L.pad_md, text_y,
                  Theme.TEXT_DIM, font_sm)
