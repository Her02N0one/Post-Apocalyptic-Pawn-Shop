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

from core.tiles import (
    TILE_COLORS, TILE_NAMES, TILE_REGISTRY,
    tiles_by_type, TileDef, TF, TileType,
)
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
        self.panel_mode = "tiles"       # "tiles"|"entities"|"textures"|"portals"|"templates"|"zones"

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
            elif action == "panel:tiles" and self.panel_mode == "tiles":
                prefix = "\u2022 "
            elif action == "panel:zones" and self.panel_mode == "zones":
                prefix = "\u2022 "
            elif action == "panel:entities" and self.panel_mode == "entities":
                prefix = "\u2022 "
            elif action == "panel:textures" and self.panel_mode == "textures":
                prefix = "\u2022 "
            elif action == "panel:portals" and self.panel_mode == "portals":
                prefix = "\u2022 "
            elif action == "panel:templates" and self.panel_mode == "templates":
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
    """Left-side tile palette with grid-of-swatches layout grouped by
    :class:`TileType`.  Each type section is collapsible.  Tiles are
    displayed as thumbnail squares so more tiles are visible at once.
    """

    HEADER_H = 22         # type-group header row height
    SWATCH   = 32         # swatch square size (px)
    GAP      = 3          # gap between swatches
    FILTER_H = 22         # search filter bar height
    BTN_H    = 24         # bottom "Add Tile" button height
    ICON_COLLAPSED = "▸"
    ICON_EXPANDED  = "▾"

    # Accent tints per TileType for the header bar
    _TYPE_TINTS: dict[TileType, tuple[int, int, int]] = {
        TileType.FLOOR:     (60, 90, 50),
        TileType.WALL:      (90, 90, 100),
        TileType.HALF_WALL: (110, 100, 80),
        TileType.PLATFORM:  (120, 100, 60),
        TileType.DOOR:      (140, 80, 50),
        TileType.LIQUID:    (40, 70, 120),
    }

    def __init__(self, state: EditorState, ctx: UIContext,
                 atlas=None):
        self.state = state
        self.ctx = ctx
        self.atlas = atlas
        self.scroll_y: float = 0.0
        self._filter: str = ""
        self._collapsed: set[str] = set()  # collapsed type names
        self._add_tile_rect: pygame.Rect = pygame.Rect(0, 0, 0, 0)
        self._filter_rect: pygame.Rect = pygame.Rect(0, 0, 0, 0)
        self._filter_active: bool = False
        self._cache_size: int = 0
        self._type_groups: dict[TileType, list[TileDef]] = {}
        self._tex_cache: dict[str, pygame.Surface] = {}
        self._refresh_groups()

    # ── helpers ──────────────────────────────────────────────────

    def _refresh_groups(self):
        self._type_groups = tiles_by_type()
        self._cache_size = len(TILE_REGISTRY)
        self._tex_cache.clear()

    def _get_thumb(self, tile_id: str, size: int = 0) -> pygame.Surface | None:
        sz = size or self.SWATCH
        key = f"{tile_id}_{sz}"
        if key not in self._tex_cache:
            if self.atlas is None:
                return None
            try:
                full = self.atlas.get(tile_id)
                self._tex_cache[key] = pygame.transform.scale(full, (sz, sz))
            except Exception:
                return None
        return self._tex_cache.get(key)

    def _filtered_tiles(self, tiles: list[TileDef]) -> list[TileDef]:
        if not self._filter:
            return tiles
        q = self._filter.lower()
        return [t for t in tiles
                if q in t.name.lower() or q in t.id
                or (t.texture_key and q in t.texture_key.lower())]

    # ── drawing ──────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, font: pygame.font.Font,
             font_sm: pygame.font.Font):
        if len(TILE_REGISTRY) != self._cache_size:
            self._refresh_groups()

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

        # ── Search filter bar ────────────────────────────────────
        fy = top + 2
        self._filter_rect = pygame.Rect(left + 4, fy, pw - 8, self.FILTER_H)
        bg = Theme.FIELD_BG if not self._filter_active else (35, 35, 42)
        pygame.draw.rect(surface, bg, self._filter_rect, border_radius=3)
        pygame.draw.rect(surface, Theme.BORDER, self._filter_rect, 1,
                         border_radius=3)
        disp = self._filter if self._filter else "\U0001f50d Filter tiles..."
        color = Theme.TEXT if self._filter else Theme.TEXT_DIM
        draw_text(surface, disp, self._filter_rect.x + 4,
                  self._filter_rect.y + 4, color, font_sm)
        if self._filter_active:
            cx = self._filter_rect.x + 4 + font_sm.size(self._filter)[0]
            if pygame.time.get_ticks() % 1000 < 500:
                pygame.draw.line(surface, Theme.ACCENT,
                                 (cx, fy + 4), (cx, fy + self.FILTER_H - 4))

        # ── Tile grids by type ───────────────────────────────────
        content_top = fy + self.FILTER_H + 4
        btn_area = self.BTN_H + 8
        content_bot = sh - L.status_h - btn_area
        clip = pygame.Rect(left, content_top, pw, content_bot - content_top)
        surface.set_clip(clip)

        y = int(content_top - self.scroll_y)
        st = self.state
        mx, my = pygame.mouse.get_pos()
        pad_x = 6  # left padding inside the palette panel
        inner_w = pw - pad_x * 2
        cols = max(1, (inner_w + self.GAP) // (self.SWATCH + self.GAP))

        self._hit_areas: list[tuple[pygame.Rect, TileDef]] = []
        self._header_areas: list[tuple[pygame.Rect, TileType]] = []

        for tt, tiles in self._type_groups.items():
            filtered = self._filtered_tiles(tiles)
            if not filtered and self._filter:
                continue
            if not tiles:
                continue

            # Type header
            collapsed = tt.value in self._collapsed
            hr = pygame.Rect(left, y, pw, self.HEADER_H)

            if y + self.HEADER_H > clip.top and y < clip.bottom:
                hov = hr.collidepoint(mx, my)
                hbg = Theme.HIGHLIGHT if hov else Theme.PANEL_LITE
                pygame.draw.rect(surface, hbg, hr)
                tint = self._TYPE_TINTS.get(tt, Theme.ACCENT)
                pygame.draw.rect(surface, tint, (left, y, 3, self.HEADER_H))
                arrow = self.ICON_COLLAPSED if collapsed else self.ICON_EXPANDED
                label = tt.value.replace("_", " ").title()
                count = len(filtered) if self._filter else len(tiles)
                draw_text(surface, f"{arrow} {label} ({count})",
                          left + 8, y + 4, Theme.TEXT, font_sm)

            self._header_areas.append((hr, tt))
            y += self.HEADER_H

            if collapsed:
                continue

            # Grid of swatches
            gx = 0
            row_y = y
            for td in filtered:
                if gx >= cols:
                    gx = 0
                    row_y += self.SWATCH + self.GAP

                sx = left + pad_x + gx * (self.SWATCH + self.GAP)
                sy = row_y
                swatch_r = pygame.Rect(sx, sy, self.SWATCH, self.SWATCH)

                if sy + self.SWATCH >= clip.top and sy < clip.bottom:
                    # Selection highlight
                    if td.id == st.selected_tile:
                        sel_r = swatch_r.inflate(4, 4)
                        pygame.draw.rect(surface, Theme.ACCENT, sel_r,
                                         border_radius=3)

                    # Thumbnail or flat colour
                    thumb = self._get_thumb(td.id)
                    if thumb:
                        surface.blit(thumb, swatch_r.topleft)
                    else:
                        pygame.draw.rect(surface, td.color, swatch_r,
                                         border_radius=2)
                    pygame.draw.rect(surface, (80, 80, 80), swatch_r, 1,
                                     border_radius=2)

                    # Tooltip on hover
                    if swatch_r.collidepoint(mx, my):
                        # Draw tooltip below swatch
                        tip = f"{td.name}"
                        tw_px = font_sm.size(tip)[0] + 8
                        tip_r = pygame.Rect(sx, sy + self.SWATCH + 2,
                                            tw_px, 16)
                        # Keep tooltip inside panel
                        if tip_r.right > left + pw:
                            tip_r.right = left + pw - 2
                        pygame.draw.rect(surface, (30, 30, 36), tip_r,
                                         border_radius=2)
                        draw_text(surface, tip, tip_r.x + 4, tip_r.y + 2,
                                  Theme.TEXT, font_sm)

                self._hit_areas.append((swatch_r, td))
                gx += 1

            # Advance y past the last row of swatches
            if filtered:
                y = row_y + self.SWATCH + self.GAP + 4
            else:
                y += 4

        self._total_h = y + self.scroll_y - content_top
        surface.set_clip(None)

        # ── Scrollbar ────────────────────────────────────────────
        visible_h = content_bot - content_top
        if self._total_h > visible_h:
            sb_x = left + pw - 6
            sb_h = max(16, int(visible_h * visible_h / self._total_h))
            sb_y = content_top + int(self.scroll_y / self._total_h * visible_h)
            sb_y = min(sb_y, content_bot - sb_h)
            pygame.draw.rect(surface, Theme.SCROLLBAR,
                             (sb_x, content_top, 4, visible_h),
                             border_radius=2)
            pygame.draw.rect(surface, Theme.SCROLLTHUMB,
                             (sb_x, sb_y, 4, sb_h),
                             border_radius=2)

        # ── "Add Tile" button at bottom ──────────────────────────
        btn_y = sh - L.status_h - self.BTN_H - 4
        self._add_tile_rect = pygame.Rect(left + 6, btn_y,
                                           pw - 12, self.BTN_H)
        hov = self._add_tile_rect.collidepoint(mx, my)
        btn_bg = Theme.BTN_HOVER if hov else Theme.PANEL_LITE
        pygame.draw.rect(surface, btn_bg, self._add_tile_rect,
                         border_radius=4)
        pygame.draw.rect(surface, Theme.ACCENT, self._add_tile_rect, 1,
                         border_radius=4)
        draw_text(surface, "+ Add Tile",
                  self._add_tile_rect.x + 10, self._add_tile_rect.y + 5,
                  Theme.ACCENT, font_sm)

    # ── event handling ───────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event,
                     surface: pygame.Surface) -> str | None:
        L = Layout
        left = 0
        pw = L.palette_w
        top = L.canvas_y
        sh = surface.get_height()

        # Filter bar typing
        if self._filter_active:
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    self._filter_active = False
                    self._filter = ""
                    return "consumed"
                elif event.key == pygame.K_BACKSPACE:
                    self._filter = self._filter[:-1]
                    return "consumed"
                elif event.key == pygame.K_RETURN:
                    self._filter_active = False
                    return "consumed"
                elif event.unicode and event.unicode.isprintable():
                    self._filter += event.unicode
                    return "consumed"

        # Scroll
        if event.type == pygame.MOUSEWHEEL:
            mx, my = pygame.mouse.get_pos()
            if left <= mx < left + pw and my > top:
                self.scroll_y = max(0, self.scroll_y - event.y * 28)
                visible_h = sh - L.status_h - (top + self.FILTER_H + 4 + self.BTN_H + 8)
                max_scroll = max(0, getattr(self, '_total_h', 0) - visible_h)
                self.scroll_y = min(self.scroll_y, max_scroll)
                return "consumed"

        # Left click
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = event.pos
            if not (left <= mx < left + pw and my > top):
                if self._filter_active:
                    self._filter_active = False
                return None

            # Filter bar
            if self._filter_rect.collidepoint(mx, my):
                self._filter_active = True
                return "consumed"
            else:
                self._filter_active = False

            # Add Tile
            if self._add_tile_rect.collidepoint(mx, my):
                return "add_tile"

            # Type headers (collapse toggle)
            for hr, tt in getattr(self, '_header_areas', []):
                if hr.collidepoint(mx, my):
                    key = tt.value
                    if key in self._collapsed:
                        self._collapsed.discard(key)
                    else:
                        self._collapsed.add(key)
                    return "consumed"

            # Swatch click → select tile
            for swatch_r, td in getattr(self, '_hit_areas', []):
                if swatch_r.collidepoint(mx, my):
                    self.state.selected_tile = td.id
                    if self.state.tool not in (Tool.BRUSH, Tool.FILL,
                                               Tool.ERASER):
                        self.state.tool = Tool.BRUSH
                    return "consumed"

            return "consumed"

        # Right-click → edit tile
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
            mx, my = event.pos
            if not (left <= mx < left + pw and my > top):
                return None
            for swatch_r, td in getattr(self, '_hit_areas', []):
                if swatch_r.collidepoint(mx, my):
                    return f"edit_tile:{td.id}"

        return None


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
#  Entity Panel  (left panel — entities mode)
# ═════════════════════════════════════════════════════════════════════

class EntityPanel:
    """Left-panel entity browser with two sub-tabs: Prefabs and Forge.

    Clicking an entry sets the editor to Entity tool with that prefab
    ready to place on the next map click.
    """

    TAB_PREFABS = 0
    TAB_FORGE = 1
    TAB_H = 22
    ITEM_H = 34

    _KIND_ICONS = {
        "npc": "\u263A", "item": "\u2726", "container": "\u25A1",
        "door_trigger": "\u25A3", "beast": "\u2620",
        "tile": "\u25A3", "box": "\u25A1", "billboard": "\u263A",
    }

    def __init__(self, state: EditorState):
        self.state = state
        self._tab = self.TAB_PREFABS
        self.scroll_y: float = 0.0
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
        except Exception:
            self._prefab_cache = []
        try:
            from editor.forge_registry import ForgeRegistry
            reg = ForgeRegistry.instance()
            self._forge_cache = sorted(reg.all().values(),
                                       key=lambda a: a.id)
        except Exception:
            self._forge_cache = []

    def refresh(self):
        """Force refresh of cached data."""
        self._cache_ready = False

    def draw(self, surface: pygame.Surface, font: pygame.font.Font,
             font_sm: pygame.font.Font):
        self._ensure_cache()
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

        mx, my = pygame.mouse.get_pos()

        # Sub-tab bar
        self._tab_rects.clear()
        tx = left + 4
        tab_y = top + 2
        for label, tab_id in [("Prefabs", self.TAB_PREFABS),
                               ("Forge", self.TAB_FORGE)]:
            tw = font_sm.size(label)[0] + 14
            tr = pygame.Rect(tx, tab_y, tw, self.TAB_H)
            sel = self._tab == tab_id
            hov = tr.collidepoint(mx, my)
            bg = Theme.SELECTED if sel else (Theme.HIGHLIGHT if hov else Theme.PANEL)
            pygame.draw.rect(surface, bg, tr, border_radius=3)
            draw_text(surface, label, tx + 7, tab_y + 5,
                      Theme.ACCENT if sel else Theme.TEXT_DIM, font_sm)
            self._tab_rects.append((tab_id, tr))
            tx += tw + 3

        # Badge for forge count
        if self._forge_cache:
            draw_text(surface, f"({len(self._forge_cache)})",
                      tx + 2, tab_y + 5, Theme.TEXT_DIM, font_sm)

        # Content area
        content_top = tab_y + self.TAB_H + 4
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

        self._total_h = (y + self.scroll_y - content_top +
                         self.ITEM_H * 2)
        surface.set_clip(None)

    def _draw_prefab_list(self, surface, font_sm, left, pw, y,
                          clip, mx, my):
        st = self.state
        for name, pdef in self._prefab_cache:
            kind = pdef.get("identity", {}).get("kind", "")
            icon = self._KIND_ICONS.get(kind, "\u25CF")
            sprite = pdef.get("sprite", {})
            color = tuple(sprite.get("color", [200, 200, 200]))

            ir = pygame.Rect(left + 3, y, pw - 6, self.ITEM_H - 2)
            if ir.bottom >= clip.top and ir.top < clip.bottom:
                # Highlight if this is the pending prefab
                selected = (st.pending_prefab == name and
                            st.tool == Tool.ENTITY)
                hov = ir.collidepoint(mx, my)
                if selected:
                    pygame.draw.rect(surface, Theme.SELECTED, ir,
                                     border_radius=3)
                    pygame.draw.rect(surface, Theme.ACCENT, ir, 1,
                                     border_radius=3)
                elif hov:
                    pygame.draw.rect(surface, Theme.HIGHLIGHT, ir,
                                     border_radius=3)

                draw_text(surface, icon, ir.x + 4, ir.y + 3,
                          color, font_sm)
                draw_text(surface, name.replace("_", " ").title(),
                          ir.x + 18, ir.y + 3, Theme.TEXT, font_sm)
                draw_text(surface, kind,
                          ir.x + 18, ir.y + 17, Theme.TEXT_DIM, font_sm)

            self._item_rects.append((ir, "prefab", name))
            y += self.ITEM_H

    def _draw_forge_list(self, surface, font_sm, left, pw, y,
                         clip, mx, my):
        if not self._forge_cache:
            draw_text(surface, "No forge archetypes.",
                      left + 8, y + 4, Theme.TEXT_DIM, font_sm)
            draw_text(surface, "Editors \u2192 Entity Forge",
                      left + 8, y + 18, Theme.TEXT_DIM, font_sm)
            return

        st = self.state
        for arch in self._forge_cache:
            icon = self._KIND_ICONS.get(arch.kind, "\u25CF")
            color = tuple(getattr(arch, 'color', (200, 200, 200)))
            ir = pygame.Rect(left + 3, y, pw - 6, self.ITEM_H - 2)

            if ir.bottom >= clip.top and ir.top < clip.bottom:
                selected = (st.pending_prefab == f"forge:{arch.id}" and
                            st.tool == Tool.ENTITY)
                hov = ir.collidepoint(mx, my)
                if selected:
                    pygame.draw.rect(surface, Theme.SELECTED, ir,
                                     border_radius=3)
                    pygame.draw.rect(surface, Theme.ACCENT, ir, 1,
                                     border_radius=3)
                elif hov:
                    pygame.draw.rect(surface, Theme.HIGHLIGHT, ir,
                                     border_radius=3)

                draw_text(surface, icon, ir.x + 4, ir.y + 3,
                          color, font_sm)
                draw_text(surface, arch.display_name or arch.id,
                          ir.x + 18, ir.y + 3, Theme.TEXT, font_sm)
                draw_text(surface, arch.kind,
                          ir.x + 18, ir.y + 17, Theme.TEXT_DIM, font_sm)

            self._item_rects.append((ir, "forge", arch.id))
            y += self.ITEM_H

    def handle_event(self, event: pygame.event.Event,
                     surface: pygame.Surface) -> str | None:
        """Returns action string or None."""
        L = Layout
        left = 0
        pw = L.palette_w
        top = L.canvas_y

        # Tab clicks
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for tab_id, tr in self._tab_rects:
                if tr.collidepoint(event.pos):
                    self._tab = tab_id
                    self.scroll_y = 0
                    return "consumed"

        # Scroll
        if event.type == pygame.MOUSEWHEEL:
            mx, my = pygame.mouse.get_pos()
            if left <= mx < left + pw and my > top:
                self.scroll_y = max(0, self.scroll_y - event.y * 28)
                visible_h = surface.get_height() - L.status_h - top - self.TAB_H - 4
                max_scroll = max(0, getattr(self, '_total_h', 0) - visible_h)
                self.scroll_y = min(self.scroll_y, max_scroll)
                return "consumed"

        # Item click
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


# ═════════════════════════════════════════════════════════════════════
#  Texture Browser Panel  (left panel — textures mode)
# ═════════════════════════════════════════════════════════════════════

class TextureBrowserPanel:
    """Browse all imported texture PNGs as a grid of 32×32 thumbnails.

    Clicking a texture copies its key name for pasting into face
    texture fields.  Returns ``'copy_tex:{key}'`` on click.
    """

    THUMB = 32
    PAD = 3

    def __init__(self, state: EditorState, atlas=None):
        self.state = state
        self._atlas = atlas
        self.scroll_y: float = 0.0
        self._item_rects: list[tuple[pygame.Rect, str]] = []
        self._tex_list: list[str] = []
        self._cache_ready = False

    def _ensure_cache(self):
        if self._cache_ready:
            return
        self._cache_ready = True
        from core.tiles import TILE_TEX_DIR
        import os
        try:
            self._tex_list = sorted(
                os.path.splitext(f)[0]
                for f in os.listdir(TILE_TEX_DIR)
                if f.endswith(".png")
            )
        except Exception:
            self._tex_list = []

    def refresh(self):
        self._cache_ready = False

    def draw(self, surface: pygame.Surface, font: pygame.font.Font,
             font_sm: pygame.font.Font):
        self._ensure_cache()
        L = Layout
        sh = surface.get_height()
        top = L.canvas_y
        left = 0
        pw = L.palette_w
        panel_h = sh - top - L.status_h

        panel_surf = pygame.Surface((pw, panel_h), pygame.SRCALPHA)
        panel_surf.fill((*Theme.PANEL, 230))
        surface.blit(panel_surf, (left, top))
        pygame.draw.line(surface, Theme.BORDER,
                         (left + pw - 1, top),
                         (left + pw - 1, top + panel_h))

        draw_text(surface, "TEXTURES", left + 6, top + 4,
                  Theme.ACCENT, font_sm)

        cols = max(1, (pw - 6) // (self.THUMB + self.PAD))
        content_top = top + 20
        content_bot = sh - L.status_h
        clip = pygame.Rect(left, content_top, pw, content_bot - content_top)
        surface.set_clip(clip)

        self._item_rects.clear()
        mx, my = pygame.mouse.get_pos()
        y = int(content_top - self.scroll_y)

        for i, key in enumerate(self._tex_list):
            col = i % cols
            row_y = y + (i // cols) * (self.THUMB + self.PAD + 12)
            tx = left + 3 + col * (self.THUMB + self.PAD)
            ty = row_y

            ir = pygame.Rect(tx, ty, self.THUMB, self.THUMB)
            if ir.bottom >= clip.top and ir.top < clip.bottom:
                # Draw thumbnail
                if self._atlas:
                    try:
                        tex_surf = self._atlas.get_by_key(key)
                        thumb = pygame.transform.scale(
                            tex_surf, (self.THUMB, self.THUMB))
                        surface.blit(thumb, ir.topleft)
                    except Exception:
                        pygame.draw.rect(surface, (60, 60, 60), ir)
                else:
                    pygame.draw.rect(surface, (60, 60, 60), ir)
                if ir.collidepoint(mx, my):
                    pygame.draw.rect(surface, Theme.ACCENT, ir, 2)
                    # Show key name as tooltip
                    draw_text(surface, key, tx,
                              ty + self.THUMB + 1, Theme.TEXT, font_sm)

            self._item_rects.append((ir, key))

        self._total_h = ((len(self._tex_list) + cols - 1) // cols) * (
            self.THUMB + self.PAD + 12)
        surface.set_clip(None)

    def handle_event(self, event: pygame.event.Event,
                     surface: pygame.Surface) -> str | None:
        L = Layout
        left = 0
        pw = L.palette_w
        top = L.canvas_y

        if event.type == pygame.MOUSEWHEEL:
            mx, my = pygame.mouse.get_pos()
            if left <= mx < left + pw and my > top:
                self.scroll_y = max(0, self.scroll_y - event.y * 28)
                visible_h = surface.get_height() - L.status_h - top - 20
                max_scroll = max(0, getattr(self, '_total_h', 0) - visible_h)
                self.scroll_y = min(self.scroll_y, max_scroll)
                return "consumed"
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for ir, key in self._item_rects:
                if ir.collidepoint(event.pos):
                    return f"copy_tex:{key}"
        return None


# ═════════════════════════════════════════════════════════════════════
#  Portal Panel  (left panel — portals mode)
# ═════════════════════════════════════════════════════════════════════

class PortalPanel:
    """List and manage portal connections in the current zone.

    Shows each portal with its destination and tile count.
    Click to select/highlight a portal on the map.
    Returns ``'select_portal:{index}'`` on click.
    """

    ITEM_H = 38

    def __init__(self, state: EditorState):
        self.state = state
        self.scroll_y: float = 0.0
        self._item_rects: list[tuple[pygame.Rect, int]] = []

    def draw(self, surface: pygame.Surface, font: pygame.font.Font,
             font_sm: pygame.font.Font):
        L = Layout
        sh = surface.get_height()
        top = L.canvas_y
        left = 0
        pw = L.palette_w
        panel_h = sh - top - L.status_h

        panel_surf = pygame.Surface((pw, panel_h), pygame.SRCALPHA)
        panel_surf.fill((*Theme.PANEL, 230))
        surface.blit(panel_surf, (left, top))
        pygame.draw.line(surface, Theme.BORDER,
                         (left + pw - 1, top),
                         (left + pw - 1, top + panel_h))

        draw_text(surface, "PORTALS", left + 6, top + 4,
                  Theme.ACCENT, font_sm)

        st = self.state
        portals = st.portals
        if not portals:
            draw_text(surface, "No portals.", left + 8, top + 24,
                      Theme.TEXT_DIM, font_sm)
            draw_text(surface, "Use Portal tool", left + 8, top + 38,
                      Theme.TEXT_DIM, font_sm)
            return

        content_top = top + 20
        content_bot = sh - L.status_h
        clip = pygame.Rect(left, content_top, pw, content_bot - content_top)
        surface.set_clip(clip)

        self._item_rects.clear()
        mx, my = pygame.mouse.get_pos()
        y = int(content_top - self.scroll_y)

        for i, portal in enumerate(portals):
            dest = portal.get("dest_zone", "?")
            tiles = portal.get("tiles", [])
            tile_count = len(tiles)

            ir = pygame.Rect(left + 3, y, pw - 6, self.ITEM_H - 2)
            if ir.bottom >= clip.top and ir.top < clip.bottom:
                hov = ir.collidepoint(mx, my)
                bg = Theme.HIGHLIGHT if hov else Theme.PANEL
                pygame.draw.rect(surface, bg, ir, border_radius=3)
                pygame.draw.rect(surface, Theme.BORDER, ir, 1, border_radius=3)

                draw_text(surface, "\u25A3", ir.x + 4, ir.y + 3,
                          Theme.PORTAL, font_sm)
                dest_label = dest[:14] if pw < 160 else dest
                draw_text(surface, f"\u2192 {dest_label}",
                          ir.x + 18, ir.y + 3, Theme.TEXT, font_sm)
                draw_text(surface, f"{tile_count} tile(s)",
                          ir.x + 18, ir.y + 19, Theme.TEXT_DIM, font_sm)

            self._item_rects.append((ir, i))
            y += self.ITEM_H

        self._total_h = len(portals) * self.ITEM_H
        surface.set_clip(None)

    def handle_event(self, event: pygame.event.Event,
                     surface: pygame.Surface) -> str | None:
        L = Layout
        left = 0
        pw = L.palette_w
        top = L.canvas_y

        if event.type == pygame.MOUSEWHEEL:
            mx, my = pygame.mouse.get_pos()
            if left <= mx < left + pw and my > top:
                self.scroll_y = max(0, self.scroll_y - event.y * 28)
                return "consumed"
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for ir, idx in self._item_rects:
                if ir.collidepoint(event.pos):
                    return f"select_portal:{idx}"
        return None


# ═════════════════════════════════════════════════════════════════════
#  Room Templates Panel  (left panel — templates mode)
# ═════════════════════════════════════════════════════════════════════

class RoomTemplatePanel:
    """Browse and place room templates (JSON files from templates/).

    Click to select a template for stamp-placement on the canvas.
    Returns ``'select_template:{filename}'`` on click.
    """

    ITEM_H = 30

    def __init__(self, state: EditorState):
        self.state = state
        self.scroll_y: float = 0.0
        self._templates: list[str] = []
        self._cache_ready = False
        self._item_rects: list[tuple[pygame.Rect, str]] = []

    def _ensure_cache(self):
        if self._cache_ready:
            return
        self._cache_ready = True
        import os
        from editor.state import TEMPLATES_DIR
        dirs = [TEMPLATES_DIR]
        rooms_dir = TEMPLATES_DIR / "rooms"
        if rooms_dir.exists():
            dirs.append(rooms_dir)
        self._templates = []
        for d in dirs:
            if d.exists():
                for f in sorted(os.listdir(d)):
                    if f.endswith(".json"):
                        self._templates.append(f)

    def refresh(self):
        self._cache_ready = False

    def draw(self, surface: pygame.Surface, font: pygame.font.Font,
             font_sm: pygame.font.Font):
        self._ensure_cache()
        L = Layout
        sh = surface.get_height()
        top = L.canvas_y
        left = 0
        pw = L.palette_w
        panel_h = sh - top - L.status_h

        panel_surf = pygame.Surface((pw, panel_h), pygame.SRCALPHA)
        panel_surf.fill((*Theme.PANEL, 230))
        surface.blit(panel_surf, (left, top))
        pygame.draw.line(surface, Theme.BORDER,
                         (left + pw - 1, top),
                         (left + pw - 1, top + panel_h))

        draw_text(surface, "TEMPLATES", left + 6, top + 4,
                  Theme.ACCENT, font_sm)

        if not self._templates:
            draw_text(surface, "No templates.", left + 8, top + 24,
                      Theme.TEXT_DIM, font_sm)
            draw_text(surface, "Editors \u2192 Room Templates",
                      left + 8, top + 38, Theme.TEXT_DIM, font_sm)
            return

        content_top = top + 20
        content_bot = sh - L.status_h
        clip = pygame.Rect(left, content_top, pw, content_bot - content_top)
        surface.set_clip(clip)

        self._item_rects.clear()
        mx, my = pygame.mouse.get_pos()
        y = int(content_top - self.scroll_y)

        for fname in self._templates:
            label = os.path.splitext(fname)[0].replace("_", " ").title()
            ir = pygame.Rect(left + 3, y, pw - 6, self.ITEM_H - 2)
            if ir.bottom >= clip.top and ir.top < clip.bottom:
                hov = ir.collidepoint(mx, my)
                bg = Theme.HIGHLIGHT if hov else Theme.PANEL
                pygame.draw.rect(surface, bg, ir, border_radius=3)
                draw_text(surface, "\u2587", ir.x + 4, ir.y + 3,
                          Theme.ACCENT, font_sm)
                draw_text(surface, label[:18] if pw < 160 else label,
                          ir.x + 18, ir.y + 6, Theme.TEXT, font_sm)
            self._item_rects.append((ir, fname))
            y += self.ITEM_H

        self._total_h = len(self._templates) * self.ITEM_H
        surface.set_clip(None)

    def handle_event(self, event: pygame.event.Event,
                     surface: pygame.Surface) -> str | None:
        L = Layout
        left = 0
        pw = L.palette_w
        top = L.canvas_y

        if event.type == pygame.MOUSEWHEEL:
            mx, my = pygame.mouse.get_pos()
            if left <= mx < left + pw and my > top:
                self.scroll_y = max(0, self.scroll_y - event.y * 28)
                return "consumed"
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for ir, fname in self._item_rects:
                if ir.collidepoint(event.pos):
                    return f"select_template:{fname}"
        return None


import os  # needed by RoomTemplatePanel


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
