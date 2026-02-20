"""editor/panels_pkg/entity_panel.py — Entity browser panel."""

from __future__ import annotations

import pygame

from editor.ui import (
    Theme, draw_text, draw_panel_bg, draw_item_row, draw_empty_hint,
    clamp_scroll, two_line_offsets,
)
from editor.state import EditorState, Tool
from editor.layout import Layout
from editor.panels_pkg.base import PanelBase, PanelRegion


class EntityPanel(PanelBase):
    """Left-panel entity browser with two sub-tabs: Prefabs and Forge.

    Overrides ``draw`` and ``handle_event`` completely because the
    sub-tab bar lives above the scroll content, requiring custom
    chrome.  Still inherits ``scroll_y`` / ``_total_h`` from
    ``PanelBase``.
    """

    title = ""  # drawn manually because of sub-tabs

    TAB_PREFABS = 0
    TAB_FORGE = 1

    _KIND_ICONS = {
        "npc": "\u263A", "item": "\u2726", "container": "\u25A1",
        "door_trigger": "\u25A3", "beast": "\u2620",
        "tile": "\u25A3", "box": "\u25A1", "billboard": "\u263A",
    }

    def __init__(self, state: EditorState):
        super().__init__()
        self.state = state
        self._tab = self.TAB_PREFABS
        self._prefab_cache: list[tuple[str, dict]] = []
        self._forge_cache: list = []
        self._cache_ready = False
        self._tab_rects: list[tuple[int, pygame.Rect]] = []
        self._item_rects: list[tuple[pygame.Rect, str, str]] = []

    def _ensure_cache(self):
        if self._cache_ready:
            return
        self._cache_ready = True
        try:
            from editor.canvas import get_prefab_defaults
            defaults = get_prefab_defaults()
            self._prefab_cache = sorted(defaults.items())
        except (ImportError, AttributeError):
            self._prefab_cache = []
        try:
            from editor.forge_registry import ForgeRegistry
            reg = ForgeRegistry.instance()
            self._forge_cache = sorted(reg.all().values(),
                                       key=lambda a: a.id)
        except (ImportError, AttributeError):
            self._forge_cache = []

    def refresh(self):
        self._cache_ready = False

    # ── Drawing ──────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, font: pygame.font.Font,
             font_sm: pygame.font.Font):
        self._ensure_cache()
        L = Layout
        sh = surface.get_height()
        top = L.canvas_y
        left = 0
        pw = L.palette_w
        panel_h = sh - top - L.status_h

        draw_panel_bg(surface, left, top, pw, panel_h)

        mx, my = pygame.mouse.get_pos()

        # Sub-tab bar
        TAB_H = L.header_h
        ITEM_H = L.item_h
        br = L.border_r
        fh = font_sm.get_height()
        tab_text_off = max(1, (TAB_H - fh) // 2)
        self._tab_rects.clear()
        tx = left + L.pad_sm
        tab_y = top + L.pad_sm
        for label, tab_id in [("Prefabs", self.TAB_PREFABS),
                               ("Forge", self.TAB_FORGE)]:
            tw = font_sm.size(label)[0] + L.pad_lg + L.pad_sm
            tr = pygame.Rect(tx, tab_y, tw, TAB_H)
            sel = self._tab == tab_id
            hov = tr.collidepoint(mx, my)
            bg = Theme.SELECTED if sel else (
                Theme.HIGHLIGHT if hov else Theme.PANEL)
            pygame.draw.rect(surface, bg, tr, border_radius=br)
            draw_text(surface, label, tx + L.pad_md, tab_y + tab_text_off,
                      Theme.ACCENT if sel else Theme.TEXT_DIM, font_sm)
            self._tab_rects.append((tab_id, tr))
            tx += tw + L.pad_sm

        if self._forge_cache:
            draw_text(surface, f"({len(self._forge_cache)})",
                      tx + L.pad_sm, tab_y + tab_text_off,
                      Theme.TEXT_DIM, font_sm)

        content_top = tab_y + TAB_H + L.pad_sm
        content_bot = sh - L.status_h
        clip = pygame.Rect(left, content_top, pw, content_bot - content_top)
        surface.set_clip(clip)

        self._item_rects.clear()
        y = int(content_top - self.scroll_y)

        if self._tab == self.TAB_PREFABS:
            self._draw_prefab_list(surface, font_sm, left, pw, y,
                                   clip, mx, my)
        else:
            self._draw_forge_list(surface, font_sm, left, pw, y,
                                  clip, mx, my)

        if self._tab == self.TAB_PREFABS:
            self._total_h = len(self._prefab_cache) * ITEM_H
        else:
            self._total_h = max(ITEM_H, len(self._forge_cache) * ITEM_H)
        self.scroll_y = clamp_scroll(self.scroll_y, self._total_h,
                                     content_bot - content_top)
        surface.set_clip(None)

    def _draw_prefab_list(self, surface, font_sm, left, pw, y,
                          clip, mx, my):
        st = self.state
        L = Layout
        ITEM_H = L.item_h
        br = L.border_r
        fh = font_sm.get_height()
        line1_off, line2_off = two_line_offsets(ITEM_H, fh)
        icon_x_off = L.pad_sm
        text_x_off = L.s(18)
        for name, pdef in self._prefab_cache:
            kind = pdef.get("identity", {}).get("kind", "")
            icon = self._KIND_ICONS.get(kind, "\u25CF")
            sprite = pdef.get("sprite", {})
            color = tuple(sprite.get("color", [200, 200, 200]))

            ir = pygame.Rect(left + L.pad_sm, y, pw - L.pad_md, ITEM_H - 2)
            if ir.bottom >= clip.top and ir.top < clip.bottom:
                selected = (st.pending_prefab == name and
                            st.tool == Tool.ENTITY)
                hov = ir.collidepoint(mx, my)
                draw_item_row(surface, ir, hovered=hov, selected=selected,
                              accent_border=True, br=br)

                draw_text(surface, icon, ir.x + icon_x_off,
                          ir.y + line1_off, color, font_sm)
                draw_text(surface, name.replace("_", " ").title(),
                          ir.x + text_x_off, ir.y + line1_off,
                          Theme.TEXT, font_sm)
                draw_text(surface, kind,
                          ir.x + text_x_off, ir.y + line2_off,
                          Theme.TEXT_DIM, font_sm)

            self._item_rects.append((ir, "prefab", name))
            y += ITEM_H

    def _draw_forge_list(self, surface, font_sm, left, pw, y,
                         clip, mx, my):
        L = Layout
        ITEM_H = L.item_h
        br = L.border_r
        fh = font_sm.get_height()
        line1_off, line2_off = two_line_offsets(ITEM_H, fh)
        icon_x_off = L.pad_sm
        text_x_off = L.s(18)
        if not self._forge_cache:
            draw_empty_hint(surface,
                            ["No forge archetypes.",
                             "Editors \u2192 Entity Forge"],
                            left + L.pad_md, y + L.pad_sm, font_sm)
            return

        st = self.state
        for arch in self._forge_cache:
            icon = self._KIND_ICONS.get(arch.kind, "\u25CF")
            color = tuple(getattr(arch, 'color', (200, 200, 200)))
            ir = pygame.Rect(left + L.pad_sm, y, pw - L.pad_md, ITEM_H - 2)

            if ir.bottom >= clip.top and ir.top < clip.bottom:
                selected = (st.pending_prefab == f"forge:{arch.id}" and
                            st.tool == Tool.ENTITY)
                hov = ir.collidepoint(mx, my)
                draw_item_row(surface, ir, hovered=hov, selected=selected,
                              accent_border=True, br=br)

                draw_text(surface, icon, ir.x + icon_x_off,
                          ir.y + line1_off, color, font_sm)
                draw_text(surface, arch.display_name or arch.id,
                          ir.x + text_x_off, ir.y + line1_off,
                          Theme.TEXT, font_sm)
                draw_text(surface, arch.kind,
                          ir.x + text_x_off, ir.y + line2_off,
                          Theme.TEXT_DIM, font_sm)

            self._item_rects.append((ir, "forge", arch.id))
            y += ITEM_H

    # ── Events ───────────────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event,
                     surface: pygame.Surface) -> str | None:
        L = Layout
        left = 0
        pw = L.palette_w
        top = L.canvas_y

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for tab_id, tr in self._tab_rects:
                if tr.collidepoint(event.pos):
                    self._tab = tab_id
                    self.scroll_y = 0
                    return "consumed"

        if event.type == pygame.MOUSEWHEEL:
            mx, my = pygame.mouse.get_pos()
            if left <= mx < left + pw and my > top:
                self.scroll_y = max(0,
                                    self.scroll_y - event.y * L.scroll_step)
                visible_h = (surface.get_height() - L.status_h
                             - top - L.header_h - L.pad_sm)
                self.scroll_y = clamp_scroll(self.scroll_y,
                                             self._total_h, visible_h)
                return "consumed"

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = event.pos
            if not (left <= mx < left + pw and my > top):
                return None
            for ir, source, name in self._item_rects:
                if ir.collidepoint(mx, my):
                    if source == "prefab":
                        return f"select_prefab:{name}"
                    elif source == "forge":
                        return f"select_forge:{name}"
            return "consumed"

        return None
