"""editor/panels.py — Menu bar, tile palette, zone panel, minimap
and status bar.

Provides a classic **application menu bar** at the top of the window
with dropdown menus (File, Edit, View, Tools, Editors).  Below it
sits the zone-navigation bar and the tile palette on the left.

All panels reference ``Layout`` for positioning so they adapt
automatically when the window is resized.
"""

from __future__ import annotations

import pygame

from core.tiles import TILE_COLORS, TILE_NAMES
from editor.ui import Theme, draw_text, UIContext
from editor.state import EditorState, Tool, list_zones
from editor.layout import Layout


# ═════════════════════════════════════════════════════════════════════
#  MenuBar  (standard File/Edit/View/Tools/Editors dropdown bar)
# ═════════════════════════════════════════════════════════════════════

# A menu item is (label, shortcut_hint, action | None).
# ``None`` action means it's a separator line (label is ignored).
_SEP = ("---", "", None)

_MENU_DEFS: list[tuple[str, list[tuple[str, str, str | None]]]] = [
    ("File", [
        ("New Zone",       "",    "new"),
        ("Open Zone...",   "",    "load"),
        ("Save",           "^S",  "save"),
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
        ("First Person",        "F",   "toggle_fp"),
        _SEP,
        ("Brush Size +",        "]",   "brush_inc"),
        ("Brush Size -",        "[",   "brush_dec"),
        _SEP,
        ("Tile Palette",        "",    "panel:tiles"),
        ("Zone List",           "",    "panel:zones"),
    ]),
    ("Tools", [
        ("Brush",    "B", "tool:brush"),
        ("Eraser",   "E", "tool:eraser"),
        ("Fill",     "", "tool:fill"),
        ("Picker",   "", "tool:picker"),
        ("Entity",   "", "tool:entity"),
        ("Portal",   "", "tool:portal"),
        ("Anchor",   "", "tool:anchor"),
    ]),
    ("Editors", [
        ("Room Templates",       "", "templates"),
        ("Loot Tables",          "", "loot"),
    ]),
]


class MenuBar:
    """Classic horizontal menu bar with dropdown menus.

    Returns action strings when the user clicks a menu item.
    """

    ITEM_PAD_X = 12          # horizontal padding per top-level label
    DROPDOWN_W = 200         # dropdown panel width
    ITEM_H = 22              # dropdown row height
    SEP_H = 8                # separator height

    def __init__(self, state: EditorState, ctx: UIContext):
        self.state = state
        self.ctx = ctx
        self.panel_mode = "tiles"       # "tiles" | "zones"

        self._open_menu: int | None = None    # index into _MENU_DEFS
        self._hover_item: int = -1            # hovered dropdown row
        self._top_rects: list[pygame.Rect] = []  # computed each draw

    # ── drawing ─────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface,
             font: pygame.font.Font, font_sm: pygame.font.Font):
        L = Layout
        sw = surface.get_width()
        h = L.menu_h

        # Bar background
        pygame.draw.rect(surface, Theme.PANEL, (0, 0, sw, h))
        pygame.draw.line(surface, Theme.BORDER, (0, h - 1), (sw, h - 1))

        # Top-level menu labels
        self._top_rects.clear()
        x = 4
        mx_mouse, my_mouse = pygame.mouse.get_pos()

        for idx, (label, _items) in enumerate(_MENU_DEFS):
            tw = font_sm.size(label)[0] + self.ITEM_PAD_X * 2
            r = pygame.Rect(x, 0, tw, h)
            self._top_rects.append(r)

            is_open = (self._open_menu == idx)
            hov = r.collidepoint(mx_mouse, my_mouse)
            if is_open:
                pygame.draw.rect(surface, Theme.SELECTED, r)
            elif hov:
                pygame.draw.rect(surface, Theme.HIGHLIGHT, r)
            draw_text(surface, label,
                      x + self.ITEM_PAD_X, 4,
                      Theme.ACCENT if is_open else Theme.TEXT,
                      font_sm)
            x += tw

        # Draw tool indicator on the right
        tool_label = f"Tool: {self.state.tool.title()}"
        tool_w = font_sm.size(tool_label)[0]
        draw_text(surface, tool_label, sw - tool_w - 8, 4,
                  Theme.ACCENT, font_sm)

        # Dropdown
        if self._open_menu is not None:
            self._draw_dropdown(surface, font_sm)

    def _draw_dropdown(self, surface: pygame.Surface,
                       font_sm: pygame.font.Font):
        idx = self._open_menu
        if idx is None or idx >= len(_MENU_DEFS):
            return
        _label, items = _MENU_DEFS[idx]
        top_r = self._top_rects[idx]

        # Compute total height
        total_h = 4
        for (lbl, _hint, action) in items:
            total_h += self.SEP_H if action is None else self.ITEM_H
        total_h += 4

        dx = top_r.x
        dy = top_r.bottom
        sw = surface.get_width()
        dw = self.DROPDOWN_W
        # Clamp to screen edge
        if dx + dw > sw:
            dx = sw - dw - 2

        # Shadow
        shadow = pygame.Surface((dw + 4, total_h + 4), pygame.SRCALPHA)
        shadow.fill((0, 0, 0, 60))
        surface.blit(shadow, (dx + 2, dy + 2))

        # Background
        pygame.draw.rect(surface, Theme.PANEL, (dx, dy, dw, total_h))
        pygame.draw.rect(surface, Theme.BORDER, (dx, dy, dw, total_h), 1)

        # Items
        mx, my = pygame.mouse.get_pos()
        y = dy + 2
        self._hover_item = -1

        for row_idx, (lbl, hint, action) in enumerate(items):
            if action is None:
                # Separator
                sep_y = y + self.SEP_H // 2
                pygame.draw.line(surface, Theme.BORDER,
                                 (dx + 6, sep_y), (dx + dw - 6, sep_y))
                y += self.SEP_H
                continue

            row_r = pygame.Rect(dx + 2, y, dw - 4, self.ITEM_H)
            hov = row_r.collidepoint(mx, my)
            if hov:
                self._hover_item = row_idx
                pygame.draw.rect(surface, Theme.HIGHLIGHT, row_r,
                                 border_radius=3)

            # Checkmark for toggleable items
            prefix = ""
            if action == "toggle_grid" and self.state.show_grid:
                prefix = "\u2713 "
            elif action == "toggle_minimap" and self.state.show_minimap:
                prefix = "\u2713 "
            elif action == "toggle_fp" and self.state.first_person:
                prefix = "\u2713 "
            elif action == "panel:tiles" and self.panel_mode == "tiles":
                prefix = "\u2022 "
            elif action == "panel:zones" and self.panel_mode == "zones":
                prefix = "\u2022 "
            elif action.startswith("tool:"):
                tool_name = action.split(":")[1]
                if self.state.tool == tool_name:
                    prefix = "\u2022 "

            draw_text(surface, prefix + lbl,
                      dx + 10, y + 3, Theme.TEXT, font_sm)
            if hint:
                hw = font_sm.size(hint)[0]
                draw_text(surface, hint,
                          dx + dw - hw - 10, y + 3,
                          Theme.TEXT_DIM, font_sm)
            y += self.ITEM_H

    # Sentinel returned when the menu consumed a click internally
    _CONSUMED = "_consumed"

    # ── events ──────────────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event) -> str | None:
        """Returns an action string, ``_CONSUMED``, or ``None``.

        Possible actions: ``save``, ``load``, ``new``, ``quit``,
        ``undo``, ``redo``, ``delete_entity``, ``toggle_grid``,
        ``toggle_minimap``, ``toggle_fp``, ``brush_inc``, ``brush_dec``,
        ``panel:tiles``, ``panel:zones``,
        ``tool:<name>``, ``templates``, ``loot``.
        Returns ``_CONSUMED`` for clicks the menu bar handled
        internally (open/close, tool switch, toggle) so the caller
        knows NOT to propagate the event.
        """
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = event.pos

            # Click on a top-level menu label?
            for idx, r in enumerate(self._top_rects):
                if r.collidepoint(mx, my):
                    if self._open_menu == idx:
                        self._open_menu = None    # toggle closed
                    else:
                        self._open_menu = idx
                    return self._CONSUMED

            # Click inside an open dropdown?
            if self._open_menu is not None:
                action = self._click_dropdown(mx, my)
                if action is not None:
                    self._open_menu = None
                    result = self._resolve_action(action)
                    # _resolve_action returns None for internally-
                    # handled items (tool, toggle).  Still consumed.
                    return result if result else self._CONSUMED
                # Click outside dropdown → close menu, consume click
                self._open_menu = None
                return self._CONSUMED

        # Hover over top-level while a menu is open → switch menu
        if event.type == pygame.MOUSEMOTION and self._open_menu is not None:
            mx, my = event.pos
            for idx, r in enumerate(self._top_rects):
                if r.collidepoint(mx, my) and idx != self._open_menu:
                    self._open_menu = idx
                    break

        return None

    def _click_dropdown(self, mx: int, my: int) -> str | None:
        """Check if (mx, my) hits a dropdown item.  Returns action."""
        idx = self._open_menu
        if idx is None or idx >= len(_MENU_DEFS):
            return None
        _label, items = _MENU_DEFS[idx]
        top_r = self._top_rects[idx]

        dx = top_r.x
        dy = top_r.bottom
        dw = self.DROPDOWN_W
        sw = Layout.sw
        if dx + dw > sw:
            dx = sw - dw - 2

        y = dy + 2
        for _row_idx, (lbl, hint, action) in enumerate(items):
            if action is None:
                y += self.SEP_H
                continue
            row_r = pygame.Rect(dx + 2, y, dw - 4, self.ITEM_H)
            if row_r.collidepoint(mx, my):
                return action
            y += self.ITEM_H
        return None

    def _resolve_action(self, action: str) -> str | None:
        """Handle immediate state changes, return action for app."""
        st = self.state

        # Tool selection
        if action.startswith("tool:"):
            tool_name = action.split(":")[1]
            st.tool = tool_name
            return None

        # Panel mode
        if action.startswith("panel:"):
            self.panel_mode = action.split(":")[1]
            return None

        # Toggles that can be handled here
        if action == "toggle_grid":
            st.show_grid = not st.show_grid
            return None
        if action == "toggle_minimap":
            st.show_minimap = not st.show_minimap
            return None
        if action == "toggle_fp":
            st.first_person = not st.first_person
            st.dirty = True
            st.toast(f"First Person: {'ON' if st.first_person else 'OFF'}")
            return None
        if action == "brush_inc":
            st.brush_size = min(9, st.brush_size + 1)
            return None
        if action == "brush_dec":
            st.brush_size = max(1, st.brush_size - 1)
            return None

        # Everything else → bubble up to app
        return action

    @property
    def is_open(self) -> bool:
        """True when any dropdown is visible."""
        return self._open_menu is not None

    def close(self):
        """Dismiss open dropdown."""
        self._open_menu = None


# ═════════════════════════════════════════════════════════════════════
#  Zone Navigation Bar  (compact top bar)
# ═════════════════════════════════════════════════════════════════════

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
        sw = surface.get_width()
        h = L.nav_h
        top = L.menu_h          # nav bar starts below the menu bar

        # Full-width background
        pygame.draw.rect(surface, (36, 36, 42), (0, top, sw, h))
        pygame.draw.line(surface, Theme.BORDER,
                         (0, top + h - 1), (sw, top + h - 1))

        st = self.state
        x = 8

        # Back / Forward arrows
        can_back = st.zone_history_idx > 0
        can_fwd = st.zone_history_idx < len(st.zone_history) - 1

        self._back_rect = pygame.Rect(x, top + 3, 20, h - 6)
        bc = Theme.TEXT if can_back else (60, 60, 66)
        draw_text(surface, "\u25C0", x + 4, top + 5, bc, font_sm)
        x += 22

        self._fwd_rect = pygame.Rect(x, top + 3, 20, h - 6)
        fc = Theme.TEXT if can_fwd else (60, 60, 66)
        draw_text(surface, "\u25B6", x + 4, top + 5, fc, font_sm)
        x += 28

        # Zone name + dirty + FP flag
        label = f"{st.zone_name}{'*' if st.dirty else ''}"
        draw_text(surface, label, x, top + 6, Theme.ACCENT, font_sm)
        x += max(60, font_sm.size(label)[0] + 14)

        if st.first_person:
            draw_text(surface, "FP", x, top + 6, Theme.SUCCESS, font_sm)
            x += 24

        # Connected zones
        self._target_rects.clear()
        targets = st.connected_zones()
        if targets:
            draw_text(surface, "\u2192", x, top + 6,
                      Theme.TEXT_DIM, font_sm)
            x += 14
        for tz in targets:
            tw = font_sm.size(tz)[0] + 12
            if x + tw > sw - 10:
                break
            r = pygame.Rect(x, top + 3, tw, h - 6)
            mx, my = pygame.mouse.get_pos()
            hov = r.collidepoint(mx, my)
            if hov:
                pygame.draw.rect(surface, Theme.HIGHLIGHT, r,
                                 border_radius=3)
            draw_text(surface, tz, x + 6, top + 6,
                      Theme.PORTAL if hov else Theme.TEXT_DIM, font_sm)
            self._target_rects.append((tz, r))
            x += tw + 4

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


# ═════════════════════════════════════════════════════════════════════
#  Tile Palette  (left panel — tiles mode)
# ═════════════════════════════════════════════════════════════════════

class TilePalette:
    def __init__(self, state: EditorState):
        self.state = state
        self.scroll_y: float = 0.0

    def draw(self, surface: pygame.Surface, font: pygame.font.Font,
             font_sm: pygame.font.Font):
        L = Layout
        sh = surface.get_height()
        top = L.canvas_y
        left = 0
        pw = L.palette_w
        panel_h = sh - top - L.status_h

        # Panel background
        panel_surf = pygame.Surface((pw, panel_h), pygame.SRCALPHA)
        panel_surf.fill((*Theme.PANEL, 230))
        surface.blit(panel_surf, (left, top))
        pygame.draw.line(surface, Theme.BORDER,
                         (left + pw - 1, top),
                         (left + pw - 1, top + panel_h))

        st = self.state
        item_h = 28
        y = int(top + 6 - self.scroll_y)

        for tid in sorted(TILE_NAMES.keys()):
            if y + item_h < top or y > sh - L.status_h:
                y += item_h
                continue
            color = TILE_COLORS.get(tid, (120, 120, 120))
            sx = left + 4
            swatch = pygame.Rect(sx, y, 20, 20)
            if tid == st.selected_tile:
                sel_rect = pygame.Rect(left + 2, y - 2, pw - 4, 24)
                pygame.draw.rect(surface, Theme.ACCENT, sel_rect, 2,
                                 border_radius=3)
            pygame.draw.rect(surface, color, swatch, border_radius=3)
            pygame.draw.rect(surface, (80, 80, 80), swatch, 1,
                             border_radius=3)
            name_text = TILE_NAMES[tid]
            if pw < 140:
                name_text = name_text[:6]
            elif pw < 160:
                name_text = name_text[:10]
            draw_text(surface, f"{tid}:{name_text}",
                      sx + 24, y + 4, Theme.TEXT, font_sm)
            y += item_h

        # Tool info at bottom
        y = max(y + 4, sh - L.status_h - 42)
        draw_text(surface, f"Brush:{st.brush_size}",
                  left + 4, y, Theme.TEXT_DIM, font_sm)
        y += 14
        draw_text(surface, f"Tool:{st.tool.title()}",
                  left + 4, y, Theme.ACCENT, font_sm)

    def handle_event(self, event: pygame.event.Event,
                     surface: pygame.Surface) -> bool:
        L = Layout
        left = 0
        pw = L.palette_w
        top = L.canvas_y

        if event.type == pygame.MOUSEWHEEL:
            mx, my = pygame.mouse.get_pos()
            if left <= mx < left + pw and my > top:
                self.scroll_y = max(0, self.scroll_y - event.y * 24)
                return True
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = event.pos
            if left <= mx < left + pw and my > top:
                item_h = 28
                idx = int((my - top - 6 + self.scroll_y) / item_h)
                tile_ids = sorted(TILE_NAMES.keys())
                if 0 <= idx < len(tile_ids):
                    self.state.selected_tile = tile_ids[idx]
                    if self.state.tool not in (Tool.BRUSH, Tool.FILL,
                                               Tool.ERASER):
                        self.state.tool = Tool.BRUSH
                return True
        return False


# ═════════════════════════════════════════════════════════════════════
#  Zone Panel  (left panel — zones mode)
# ═════════════════════════════════════════════════════════════════════

class ZonePanel:
    """Zone list panel — browse, load, create zones without modals."""

    def __init__(self, state: EditorState):
        self.state = state
        self.scroll_y: float = 0.0
        self._zone_list: list[str] = []
        self._refresh_timer: float = 0.0

    def draw(self, surface: pygame.Surface, font: pygame.font.Font,
             font_sm: pygame.font.Font):
        L = Layout
        sh = surface.get_height()
        top = L.canvas_y
        left = 0
        pw = L.palette_w
        panel_h = sh - top - L.status_h

        # Background
        panel_surf = pygame.Surface((pw, panel_h), pygame.SRCALPHA)
        panel_surf.fill((*Theme.PANEL, 230))
        surface.blit(panel_surf, (left, top))
        pygame.draw.line(surface, Theme.BORDER,
                         (left + pw - 1, top),
                         (left + pw - 1, top + panel_h))

        # Refresh zone list periodically
        self._refresh_timer -= 0.016
        if self._refresh_timer <= 0:
            self._zone_list = list_zones()
            self._refresh_timer = 2.0

        # Header
        draw_text(surface, "ZONES", left + 6, top + 4,
                  Theme.ACCENT, font_sm)

        st = self.state
        item_h = 24
        y = int(top + 22 - self.scroll_y)
        mx, my = pygame.mouse.get_pos()

        for zname in self._zone_list:
            if y + item_h < top + 20 or y > sh - L.status_h:
                y += item_h
                continue
            ir = pygame.Rect(left + 2, y, pw - 4, item_h - 2)
            is_cur = (zname == st.zone_name)
            hov = ir.collidepoint(mx, my)
            if is_cur:
                pygame.draw.rect(surface, Theme.SELECTED, ir,
                                 border_radius=3)
            elif hov:
                pygame.draw.rect(surface, Theme.HIGHLIGHT, ir,
                                 border_radius=3)
            color = Theme.ACCENT2 if is_cur else Theme.TEXT
            name_display = zname[:16] if pw < 150 else zname
            draw_text(surface, name_display, ir.x + 6, ir.y + 4,
                      color, font_sm)
            y += item_h

    def handle_event(self, event: pygame.event.Event,
                     surface: pygame.Surface) -> str | None:
        """Returns ``'load:zone_name'`` or ``None``."""
        L = Layout
        left = 0
        pw = L.palette_w
        top = L.canvas_y

        if event.type == pygame.MOUSEWHEEL:
            mx, my = pygame.mouse.get_pos()
            if left <= mx < left + pw and my > top:
                self.scroll_y = max(0, self.scroll_y - event.y * 22)
                return None
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = event.pos
            if left <= mx < left + pw and my > top + 20:
                item_h = 24
                idx = int((my - top - 22 + self.scroll_y) / item_h)
                if 0 <= idx < len(self._zone_list):
                    return f"load:{self._zone_list[idx]}"
        return None


# ═════════════════════════════════════════════════════════════════════
#  Minimap
# ═════════════════════════════════════════════════════════════════════

class Minimap:
    WIDTH = 150
    HEIGHT = 110

    def __init__(self, state: EditorState):
        self.state = state

    def draw(self, surface: pygame.Surface, font_sm: pygame.font.Font):
        if not self.state.show_minimap:
            return
        L = Layout
        sw, sh = surface.get_size()
        mm_x = sw - L.inspector_w - self.WIDTH - 6
        mm_y = sh - self.HEIGHT - L.status_h - 6

        bg = pygame.Surface((self.WIDTH, self.HEIGHT), pygame.SRCALPHA)
        bg.fill((20, 20, 24, 200))
        surface.blit(bg, (mm_x, mm_y))
        pygame.draw.rect(surface, Theme.PANEL_LITE,
                         (mm_x, mm_y, self.WIDTH, self.HEIGHT), 1)

        st = self.state
        if st.map_w == 0 or st.map_h == 0:
            return

        sx = (self.WIDTH - 4) / st.map_w
        sy = (self.HEIGHT - 4) / st.map_h
        scale = min(sx, sy)
        ox = mm_x + 2 + int((self.WIDTH - 4 - st.map_w * scale) / 2)
        oy = mm_y + 2 + int((self.HEIGHT - 4 - st.map_h * scale) / 2)
        pw = max(1, int(scale))

        for r in range(st.map_h):
            for c in range(st.map_w):
                tid = st.tiles[r][c]
                color = TILE_COLORS.get(tid, (80, 80, 80))
                tx = ox + int(c * scale)
                ty = oy + int(r * scale)
                if pw <= 1:
                    surface.set_at((tx, ty), color)
                else:
                    pygame.draw.rect(surface, color, (tx, ty, pw, pw))

        # Portal dots
        for p in st.portals:
            for tile in p["tiles"]:
                pr, pc = tile
                tx = ox + int(pc * scale) + pw // 2
                ty = oy + int(pr * scale) + pw // 2
                pygame.draw.circle(surface, Theme.PORTAL, (tx, ty),
                                   max(2, pw))

        # Entity dots
        for ent in st.entities:
            pos = ent.get("position", {})
            ex, ey = pos.get("x", 0.0), pos.get("y", 0.0)
            tx = ox + int(ex * scale)
            ty = oy + int(ey * scale)
            pygame.draw.circle(surface, Theme.ENTITY, (tx, ty),
                               max(1, pw))


# ═════════════════════════════════════════════════════════════════════
#  Status Bar
# ═════════════════════════════════════════════════════════════════════

class StatusBar:
    def __init__(self, state: EditorState):
        self.state = state

    def draw(self, surface: pygame.Surface, font_sm: pygame.font.Font):
        L = Layout
        sw, sh = surface.get_size()
        bar_y = sh - L.status_h
        pygame.draw.rect(surface, Theme.PANEL,
                         (0, bar_y, sw, L.status_h))

        st = self.state
        if st.hover_tile:
            r, c = st.hover_tile
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
            draw_text(surface, info, 6, bar_y + 4,
                      Theme.TEXT_DIM, font_sm)

        # Toast
        if st.toast_timer > 0:
            alpha = min(1.0, st.toast_timer * 2) * 255
            toast_surf = font_sm.render(st.toast_msg, True, Theme.ACCENT2)
            toast_surf.set_alpha(int(alpha))
            surface.blit(toast_surf,
                         (sw // 2 - toast_surf.get_width() // 2,
                          bar_y - 26))

        # Keyboard hints (right side)
        hints = "^S ^Z ^Y  G:Grid M:Map [:- ]:+ F:FP"
        hw = font_sm.size(hints)[0]
        draw_text(surface, hints, sw - hw - 8, bar_y + 4,
                  Theme.TEXT_DIM, font_sm)


# ═════════════════════════════════════════════════════════════════════
#  Backward-compat aliases
# ═════════════════════════════════════════════════════════════════════

Sidebar = MenuBar       # so imports that do ``from panels import Sidebar``
                        # still work without changes everywhere
Toolbar = MenuBar
