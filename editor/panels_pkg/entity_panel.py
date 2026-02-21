"""editor/panels_pkg/entity_panel.py — Entity browser panel.

Shows a single unified list of placeable entities: built-in prefabs
and custom Forge archetypes.  Forge items are marked with a ``[F]``
badge so designers can tell them apart at a glance.

Clicking an item sets ``state.pending_prefab`` and switches the tool
to Select mode so the next canvas click places the entity.
"""

from __future__ import annotations

import pygame

from editor.ui import (
    Theme, draw_text, draw_item_row, draw_empty_hint,
    clamp_scroll, two_line_offsets,
)
from editor.state import EditorState, Tool
from editor.layout import Layout
from editor.panels_pkg.base import PanelBase, PanelRegion


class EntityPanel(PanelBase):
    """Left-panel entity browser -- unified prefab + forge list."""

    title = ""  # drawn by PanelTabs, not here

    _KIND_ICONS = {
        "npc": "\u263A", "item": "\u2726", "container": "\u25A1",
        "door_trigger": "\u25A3", "beast": "\u2620", "dummy": "\u25CB",
        "prop": "\u25A0", "player": "\u263B",
        "tile": "\u25A3", "box": "\u25A1", "billboard": "\u263A",
    }

    def __init__(self, state: EditorState):
        super().__init__()
        self.state = state
        self._combined_cache: list[tuple[str, str, str, tuple, str]] = []
        # Each entry: (display_name, source, key, color, kind)
        #   source = "prefab" | "forge"
        #   key    = prefab name or "forge:<id>"
        self._cache_ready = False
        self._item_rects: list[tuple[pygame.Rect, str, str]] = []

    def _ensure_cache(self):
        if self._cache_ready:
            return
        self._cache_ready = True
        combined = []

        # Built-in prefabs
        try:
            from editor.canvas import get_prefab_defaults
            defaults = get_prefab_defaults()
            for name, pdef in sorted(defaults.items()):
                kind = pdef.get("identity", {}).get("kind", "")
                sprite = pdef.get("sprite", {})
                color = tuple(sprite.get("color", [200, 200, 200]))
                display = name.replace("_", " ").title()
                combined.append((display, "prefab", name, color, kind))
        except (ImportError, AttributeError):
            pass

        # Forge archetypes
        try:
            from editor.forge_registry import ForgeRegistry
            reg = ForgeRegistry.instance()
            for arch in sorted(reg.all().values(), key=lambda a: a.id):
                color = tuple(getattr(arch, 'color', (200, 200, 200)))
                display = arch.display_name or arch.id
                combined.append((display, "forge", arch.id, color, arch.kind))
        except (ImportError, AttributeError):
            pass

        self._combined_cache = combined

    def refresh(self):
        self._cache_ready = False

    # -- Drawing --------------------------------------------------

    def draw(self, surface: pygame.Surface, font: pygame.font.Font,
             font_sm: pygame.font.Font):
        self._ensure_cache()
        L = Layout
        left = 0
        pw = L.palette_w

        # Background is drawn by EditorChrome — NO draw_panel_bg here.

        mx, my = pygame.mouse.get_pos()

        content_top = L.lp_content_y + L.pad_sm
        content_bot = L.lp_bottom_y
        visible_h = content_bot - content_top
        clip = pygame.Rect(left, content_top, pw, visible_h)
        surface.set_clip(clip)

        self._item_rects.clear()
        ITEM_H = L.item_h
        br = L.border_r
        fh = font_sm.get_height()
        line1_off, line2_off = two_line_offsets(ITEM_H, fh)
        icon_x_off = L.pad_sm
        text_x_off = L.s(18)

        y = int(content_top - self.scroll_y)
        st = self.state

        if not self._combined_cache:
            draw_empty_hint(surface,
                            ["No entities available.",
                             "Check systems/spawner.py"],
                            left + L.pad_md, y + L.pad_sm, font_sm)
        else:
            for display, source, key, color, kind in self._combined_cache:
                icon = self._KIND_ICONS.get(kind, "\u25CF")
                ir = pygame.Rect(left + L.pad_sm, y, pw - L.pad_md,
                                 ITEM_H - 2)
                if ir.bottom >= clip.top and ir.top < clip.bottom:
                    pending = st.pending_prefab
                    sel_key = f"forge:{key}" if source == "forge" else key
                    selected = (pending == sel_key)
                    hov = ir.collidepoint(mx, my)
                    draw_item_row(surface, ir, hovered=hov,
                                  selected=selected,
                                  accent_border=True, br=br)

                    draw_text(surface, icon, ir.x + icon_x_off,
                              ir.y + line1_off, color, font_sm)
                    draw_text(surface, display,
                              ir.x + text_x_off, ir.y + line1_off,
                              Theme.TEXT, font_sm)

                    # Kind + optional forge badge
                    kind_label = kind
                    if source == "forge":
                        kind_label = f"[F] {kind}" if kind else "[F]"
                    draw_text(surface, kind_label,
                              ir.x + text_x_off, ir.y + line2_off,
                              Theme.TEXT_DIM, font_sm)

                self._item_rects.append((ir, source, key))
                y += ITEM_H

        self._total_h = len(self._combined_cache) * ITEM_H
        self.scroll_y = clamp_scroll(self.scroll_y, self._total_h, visible_h)

        surface.set_clip(None)

    # -- Events ---------------------------------------------------

    def handle_event(self, event: pygame.event.Event,
                     surface: pygame.Surface) -> str | None:
        L = Layout
        left = 0
        pw = L.palette_w

        if event.type == pygame.MOUSEWHEEL:
            mx, my = pygame.mouse.get_pos()
            if left <= mx < left + pw and L.lp_content_y <= my < L.lp_bottom_y:
                self.scroll_y = max(0,
                                    self.scroll_y - event.y * L.scroll_step)
                self.scroll_y = clamp_scroll(self.scroll_y,
                                             self._total_h, L.lp_content_h)
                return "consumed"

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = event.pos
            if not (left <= mx < left + pw and my >= L.lp_content_y):
                return None
            for ir, source, name in self._item_rects:
                # Skip items scrolled outside the visible content area
                if ir.bottom < L.lp_content_y or ir.top > L.lp_bottom_y:
                    continue
                if ir.collidepoint(mx, my):
                    if source == "prefab":
                        return f"select_prefab:{name}"
                    elif source == "forge":
                        return f"select_forge:{name}"
            return "consumed"

        return None
