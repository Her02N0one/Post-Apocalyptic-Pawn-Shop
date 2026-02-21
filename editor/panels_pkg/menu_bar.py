"""editor/panels_pkg/menu_bar.py — Application menu bar with dropdowns."""

from __future__ import annotations

import pygame

from editor.ui import Theme, draw_text, UIContext
from editor.state import EditorState, Tool
from editor.layout import Layout


# ── Menu definition data ─────────────────────────────────────────────

# A menu item is (label, shortcut_hint, action | None).
# ``None`` action means it's a separator line.
_SEP = ("---", "", None)

_MENU_DEFS: list[tuple[str, list[tuple[str, str, str | None]]]] = [
    ("File", [
        ("New Zone...",     "",    "new"),
        ("Open Zone...",   "",    "load"),
        ("Save",           "^S",  "save"),
        ("Save As...",     "",    "save_as"),
        ("Rename Zone...", "",    "rename"),
        _SEP,
        ("Quit",           "",    "quit"),
    ]),
    ("Edit", [
        ("Undo",                "^Z",  "undo"),
        ("Redo",                "^Y",  "redo"),
        _SEP,
        ("Delete Entity",       "Del", "delete_entity"),
    ]),
    ("View", [
        ("Toggle Grid",         "G",   "toggle_grid"),
        ("Toggle Minimap",      "M",   "toggle_minimap"),
        _SEP,
        ("FP Preview",          "P",   "fp_preview"),
        ("FP Edit Mode",        "F",   "fp_edit"),
        _SEP,
        ("Brush Size +",        "]",   "brush_inc"),
        ("Brush Size -",        "[",   "brush_dec"),
        _SEP,
        ("Tile Palette",        "",    "panel:tiles"),
        ("Entity Presets",       "",    "panel:entities"),
        ("Texture Browser",     "",    "panel:textures"),
        ("Portals",             "",    "panel:portals"),
        ("Room Templates",      "",    "panel:templates"),
        ("Zone List",           "",    "panel:zones"),
    ]),
    ("Tools", [
        ("Select",   "V", "tool:select"),
        ("Brush",    "B", "tool:brush"),
        ("Eraser",   "E", "tool:eraser"),
        ("Fill",     "I", "tool:fill"),
        ("Picker",   "",  "tool:picker"),
    ]),
    ("Editors", [
        ("Room Templates",       "", "templates"),
        ("Loot Tables",          "", "loot"),
        _SEP,
        ("Entity Forge",         "", "forge"),
    ]),
    ("Export", [
        ("Import Texture...",    "", "import_texture"),
        _SEP,
        ("Export .mpz (bin)",    "", "export_mpz"),
        ("Export All .mpz",     "", "export_all_mpz"),
    ]),
]

# Valid panel modes (used for bullet-mark detection)
_PANEL_MODES = frozenset(
    {"tiles", "entities", "textures", "portals", "templates", "zones"}
)


class MenuBar:
    """Classic horizontal menu bar with dropdown menus.

    Returns action strings when the user clicks a menu item.
    """

    # Sentinel returned when the menu consumed a click internally
    _CONSUMED = "_consumed"

    def __init__(self, state: EditorState, ctx: UIContext):
        self.state = state
        self.ctx = ctx
        self.panel_mode: str = "tiles"

        self._open_menu: int | None = None
        self._hover_item: int = -1
        self._top_rects: list[pygame.Rect] = []

    # Scaled helpers (read each frame so they follow current scale)
    @staticmethod
    def _item_pad_x() -> int:  return Layout.s(12)
    @staticmethod
    def _dropdown_w() -> int:  return Layout.s(200)
    @staticmethod
    def _item_h() -> int:      return Layout.row_h
    @staticmethod
    def _sep_h() -> int:       return Layout.s(8)

    # ── drawing ─────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface,
             font: pygame.font.Font, font_sm: pygame.font.Font):
        L = Layout
        sw = surface.get_width()
        h = L.menu_h
        pad_x = self._item_pad_x()
        text_y = max(1, (h - font_sm.get_height()) // 2)

        # Background + border drawn by EditorChrome

        self._top_rects.clear()
        x = L.pad_sm
        mx_mouse, my_mouse = pygame.mouse.get_pos()

        for idx, (label, _items) in enumerate(_MENU_DEFS):
            tw = font_sm.size(label)[0] + pad_x * 2
            r = pygame.Rect(x, 0, tw, h)
            self._top_rects.append(r)

            is_open = (self._open_menu == idx)
            hov = r.collidepoint(mx_mouse, my_mouse)
            if is_open:
                pygame.draw.rect(surface, Theme.SELECTED, r)
            elif hov:
                pygame.draw.rect(surface, Theme.HIGHLIGHT, r)
            draw_text(surface, label,
                      x + pad_x, text_y,
                      Theme.ACCENT if is_open else Theme.TEXT,
                      font_sm)
            x += tw

        if self._open_menu is not None:
            self._draw_dropdown(surface, font_sm)

    def _draw_dropdown(self, surface: pygame.Surface,
                       font_sm: pygame.font.Font):
        idx = self._open_menu
        if idx is None or idx >= len(_MENU_DEFS):
            return
        _label, items = _MENU_DEFS[idx]
        top_r = self._top_rects[idx]
        ITEM_H = self._item_h()
        SEP_H = self._sep_h()
        br = Layout.border_r

        total_h = Layout.pad_sm
        for (_lbl, _hint, action) in items:
            total_h += SEP_H if action is None else ITEM_H
        total_h += Layout.pad_sm

        dx = top_r.x
        dy = top_r.bottom
        sw = surface.get_width()
        dw = self._dropdown_w()
        if dx + dw > sw:
            dx = sw - dw - 2

        # Shadow
        shoff = Layout.pad_sm
        shadow = pygame.Surface((dw + shoff, total_h + shoff), pygame.SRCALPHA)
        shadow.fill((0, 0, 0, 60))
        surface.blit(shadow, (dx + shoff // 2, dy + shoff // 2))

        pygame.draw.rect(surface, Theme.PANEL, (dx, dy, dw, total_h))
        pygame.draw.rect(surface, Theme.BORDER, (dx, dy, dw, total_h), 1)

        mx, my = pygame.mouse.get_pos()
        y = dy + 2
        self._hover_item = -1
        text_off_y = max(1, (ITEM_H - font_sm.get_height()) // 2)

        for row_idx, (lbl, hint, action) in enumerate(items):
            if action is None:
                sep_y = y + SEP_H // 2
                pygame.draw.line(surface, Theme.BORDER,
                                 (dx + Layout.pad_md, sep_y),
                                 (dx + dw - Layout.pad_md, sep_y))
                y += SEP_H
                continue

            row_r = pygame.Rect(dx + 2, y, dw - 4, ITEM_H)
            hov = row_r.collidepoint(mx, my)
            if hov:
                self._hover_item = row_idx
                pygame.draw.rect(surface, Theme.HIGHLIGHT, row_r,
                                 border_radius=br)

            prefix = self._item_prefix(action)
            draw_text(surface, prefix + lbl,
                      dx + Layout.pad_lg, y + text_off_y,
                      Theme.TEXT, font_sm)
            if hint:
                hw = font_sm.size(hint)[0]
                draw_text(surface, hint,
                          dx + dw - hw - Layout.pad_lg, y + text_off_y,
                          Theme.TEXT_DIM, font_sm)
            y += ITEM_H

    def _item_prefix(self, action: str) -> str:
        """Return a check/bullet prefix for toggled items."""
        st = self.state
        if action == "toggle_grid" and st.show_grid:
            return "\u2713 "
        if action == "toggle_minimap" and st.show_minimap:
            return "\u2713 "
        if action.startswith("panel:"):
            mode = action.split(":")[1]
            if mode == self.panel_mode:
                return "\u2022 "
        if action.startswith("tool:"):
            if st.tool == action.split(":")[1]:
                return "\u2022 "
        return ""

    # ── events ──────────────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event) -> str | None:
        """Returns an action string, ``_CONSUMED``, or ``None``."""
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = event.pos

            for idx, r in enumerate(self._top_rects):
                if r.collidepoint(mx, my):
                    if self._open_menu == idx:
                        self._open_menu = None
                    else:
                        self._open_menu = idx
                    return self._CONSUMED

            if self._open_menu is not None:
                action = self._click_dropdown(mx, my)
                if action is not None:
                    self._open_menu = None
                    result = self._resolve_action(action)
                    return result if result else self._CONSUMED
                self._open_menu = None
                return self._CONSUMED

        if event.type == pygame.MOUSEMOTION and self._open_menu is not None:
            mx, my = event.pos
            for idx, r in enumerate(self._top_rects):
                if r.collidepoint(mx, my) and idx != self._open_menu:
                    self._open_menu = idx
                    break

        return None

    def _click_dropdown(self, mx: int, my: int) -> str | None:
        idx = self._open_menu
        if idx is None or idx >= len(_MENU_DEFS):
            return None
        _label, items = _MENU_DEFS[idx]
        top_r = self._top_rects[idx]

        dx = top_r.x
        dy = top_r.bottom
        dw = self._dropdown_w()
        sw = Layout.sw
        if dx + dw > sw:
            dx = sw - dw - 2

        ITEM_H = self._item_h()
        SEP_H = self._sep_h()
        y = dy + 2
        for _row_idx, (lbl, hint, action) in enumerate(items):
            if action is None:
                y += SEP_H
                continue
            row_r = pygame.Rect(dx + 2, y, dw - 4, ITEM_H)
            if row_r.collidepoint(mx, my):
                return action
            y += ITEM_H
        return None

    def _resolve_action(self, action: str) -> str | None:
        """Handle immediate state changes, return action for app."""
        st = self.state

        if action.startswith("tool:"):
            st.tool = action.split(":")[1]
            return None
        if action.startswith("panel:"):
            self.panel_mode = action.split(":")[1]
            return None
        if action == "toggle_grid":
            st.show_grid = not st.show_grid
            return None
        if action == "toggle_minimap":
            st.show_minimap = not st.show_minimap
            return None
        if action == "brush_inc":
            st.brush_size = min(9, st.brush_size + 1)
            return None
        if action == "brush_dec":
            st.brush_size = max(1, st.brush_size - 1)
            return None

        return action

    @property
    def is_open(self) -> bool:
        return self._open_menu is not None

    def close(self):
        self._open_menu = None
