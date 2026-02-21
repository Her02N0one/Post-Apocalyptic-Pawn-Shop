"""editor/panels_pkg/tile_palette.py — Left-panel tile swatch grid."""

from __future__ import annotations

import pygame

from core.tiles import (
    TILE_REGISTRY, tiles_by_type, TileDef, TileType,
)
from editor.ui import (
    Theme, draw_text, clamp_scroll, draw_scrollbar,
)
from editor.state import EditorState, Tool
from editor.layout import Layout
from editor.panels_pkg.base import PanelBase


class TilePalette(PanelBase):
    """Left-side tile palette with grid-of-swatches layout grouped by
    :class:`TileType`.  Each type section is collapsible.

    Overrides ``draw`` and ``handle_event`` completely because of the
    filter bar and "Add Tile" button that sit outside the scroll area.
    Inherits ``scroll_y`` / ``_total_h`` from ``PanelBase``.
    """

    ICON_COLLAPSED = "▸"
    ICON_EXPANDED  = "▾"

    # These are now read from Layout each frame via properties
    @staticmethod
    def _header_h(): return Layout.header_h
    @staticmethod
    def _swatch():   return Layout.swatch
    @staticmethod
    def _gap():      return Layout.pad_sm
    @staticmethod
    def _filter_h(): return Layout.field_h
    @staticmethod
    def _btn_h():    return Layout.btn_h

    _TYPE_TINTS: dict[TileType, tuple[int, int, int]] = {
        TileType.FLOOR:     (60, 90, 50),
        TileType.WALL:      (90, 90, 100),
        TileType.HALF_WALL: (110, 100, 80),
        TileType.PLATFORM:  (120, 100, 60),
        TileType.DOOR:      (140, 80, 50),
        TileType.LIQUID:    (40, 70, 120),
    }

    def __init__(self, state: EditorState, ctx, atlas=None):
        super().__init__()
        self.state = state
        self.ctx = ctx
        self.atlas = atlas
        self._filter: str = ""
        self._collapsed: set[str] = set()
        self._add_tile_rect: pygame.Rect = pygame.Rect(0, 0, 0, 0)
        self._filter_rect: pygame.Rect = pygame.Rect(0, 0, 0, 0)
        self._filter_active: bool = False
        self._cache_size: int = 0
        self._type_groups: dict[TileType, list[TileDef]] = {}
        self._tex_cache: dict[str, pygame.Surface] = {}
        self._hit_areas: list[tuple[pygame.Rect, TileDef]] = []
        self._header_areas: list[tuple[pygame.Rect, TileType]] = []
        self._hover_td: TileDef | None = None
        self._hover_rect: pygame.Rect | None = None
        self._refresh_groups()

    # ── helpers ──────────────────────────────────────────────────

    def _refresh_groups(self):
        self._type_groups = tiles_by_type()
        self._cache_size = len(TILE_REGISTRY)
        self._tex_cache.clear()

    def _get_thumb(self, tile_id: str, size: int = 0) -> pygame.Surface | None:
        sz = size or self._swatch()
        key = f"{tile_id}_{sz}"
        if key not in self._tex_cache:
            if self.atlas is None:
                return None
            try:
                full = self.atlas.get(tile_id)
                self._tex_cache[key] = pygame.transform.scale(full, (sz, sz))
            except (KeyError, pygame.error):
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
        _s = L.s
        left = 0
        pw = L.palette_w

        # Local scaled sizes for this frame
        HEADER_H = self._header_h()
        SWATCH   = self._swatch()
        GAP      = self._gap()
        FILTER_H = self._filter_h()
        BTN_H    = self._btn_h()
        br       = L.border_r
        pad_x    = L.pad_md
        fh       = font_sm.get_height()

        # Background is drawn by EditorChrome — NO draw_panel_bg here.

        # Reset hover state for this frame
        self._hover_td = None
        self._hover_rect = None

        # Search filter bar — positioned at top of content region
        fy = L.lp_content_y + L.pad_sm
        self._filter_rect = pygame.Rect(left + L.pad_sm, fy,
                                        pw - L.pad_sm * 2, FILTER_H)
        bg = Theme.FIELD_BG if not self._filter_active else (35, 35, 42)
        pygame.draw.rect(surface, bg, self._filter_rect, border_radius=br)
        pygame.draw.rect(surface, Theme.BORDER, self._filter_rect, 1,
                         border_radius=br)
        disp = self._filter if self._filter else "\U0001f50d Filter tiles..."
        color = Theme.TEXT if self._filter else Theme.TEXT_DIM
        text_off = max(1, (FILTER_H - fh) // 2)
        draw_text(surface, disp, self._filter_rect.x + L.pad_sm,
                  self._filter_rect.y + text_off, color, font_sm)
        if self._filter_active:
            cx = self._filter_rect.x + L.pad_sm + font_sm.size(self._filter)[0]
            if pygame.time.get_ticks() % 1000 < 500:
                pygame.draw.line(surface, Theme.ACCENT,
                                 (cx, fy + L.pad_sm),
                                 (cx, fy + FILTER_H - L.pad_sm))

        # Tile grids by type — content region below filter, above button
        content_top = fy + FILTER_H + L.pad_sm
        btn_area = BTN_H + L.pad_md
        content_bot = L.lp_bottom_y - btn_area
        clip = pygame.Rect(left, content_top, pw, content_bot - content_top)
        surface.set_clip(clip)

        y = int(content_top - self.scroll_y)
        st = self.state
        mx, my = pygame.mouse.get_pos()
        inner_w = pw - pad_x * 2
        cols = max(1, (inner_w + GAP) // (SWATCH + GAP))

        self._hit_areas.clear()
        self._header_areas.clear()

        for tt, tiles in self._type_groups.items():
            filtered = self._filtered_tiles(tiles)
            if not filtered and self._filter:
                continue
            if not tiles:
                continue

            collapsed = tt.value in self._collapsed
            hr = pygame.Rect(left, y, pw, HEADER_H)

            if y + HEADER_H > clip.top and y < clip.bottom:
                hov = hr.collidepoint(mx, my)
                hbg = Theme.HIGHLIGHT if hov else Theme.PANEL_LITE
                pygame.draw.rect(surface, hbg, hr)
                tint = self._TYPE_TINTS.get(tt, Theme.ACCENT)
                pygame.draw.rect(surface, tint, (left, y, _s(3), HEADER_H))
                arrow = self.ICON_COLLAPSED if collapsed else self.ICON_EXPANDED
                label = tt.value.replace("_", " ").title()
                count = len(filtered) if self._filter else len(tiles)
                draw_text(surface, f"{arrow} {label} ({count})",
                          left + L.pad_md, y + text_off, Theme.TEXT, font_sm)

            self._header_areas.append((hr, tt))
            y += HEADER_H

            if collapsed:
                continue

            gx = 0
            row_y = y
            for td in filtered:
                if gx >= cols:
                    gx = 0
                    row_y += SWATCH + GAP

                sx = left + pad_x + gx * (SWATCH + GAP)
                sy = row_y
                swatch_r = pygame.Rect(sx, sy, SWATCH, SWATCH)

                if sy + SWATCH >= clip.top and sy < clip.bottom:
                    if td.id == st.selected_tile:
                        sel_r = swatch_r.inflate(L.pad_sm, L.pad_sm)
                        pygame.draw.rect(surface, Theme.ACCENT, sel_r,
                                         border_radius=br)
                    thumb = self._get_thumb(td.id)
                    if thumb:
                        surface.blit(thumb, swatch_r.topleft)
                    else:
                        pygame.draw.rect(surface, td.color, swatch_r,
                                         border_radius=max(1, br - 1))
                    pygame.draw.rect(surface, (80, 80, 80), swatch_r, 1,
                                     border_radius=max(1, br - 1))

                    if swatch_r.collidepoint(mx, my):
                        self._hover_td = td
                        self._hover_rect = swatch_r

                self._hit_areas.append((swatch_r, td))
                gx += 1

            if filtered:
                y = row_y + SWATCH + GAP + L.pad_sm
            else:
                y += L.pad_sm

        self._total_h = y + self.scroll_y - content_top
        visible_h = content_bot - content_top
        self.scroll_y = clamp_scroll(self.scroll_y, self._total_h, visible_h)
        surface.set_clip(None)

        # Hover tooltip — drawn OUTSIDE the clip rect so it's not cut off
        if self._hover_td is not None and self._hover_rect is not None:
            hr = self._hover_rect
            tip = self._hover_td.name
            tw_px = font_sm.size(tip)[0] + L.pad_md
            tip_h = fh + L.pad_sm
            tip_r = pygame.Rect(hr.x, hr.y + SWATCH + 2, tw_px, tip_h)
            if tip_r.right > left + pw:
                tip_r.right = left + pw - 2
            # Draw above if it would go below the visible area
            if tip_r.bottom > content_bot:
                tip_r.y = hr.y - tip_h - 2
            pygame.draw.rect(surface, (30, 30, 36), tip_r,
                             border_radius=max(1, br - 1))
            pygame.draw.rect(surface, Theme.BORDER, tip_r, 1,
                             border_radius=max(1, br - 1))
            draw_text(surface, tip, tip_r.x + L.pad_sm,
                      tip_r.y + L.pad_sm // 2,
                      Theme.TEXT, font_sm)

        # Scrollbar
        draw_scrollbar(surface, left + pw - L.pad_md, content_top,
                       content_bot - content_top, self._total_h,
                       self.scroll_y, bar_w=_s(4), br=max(1, br - 1))

        # "Add Tile" button
        btn_y = L.lp_bottom_y - BTN_H - L.pad_sm
        self._add_tile_rect = pygame.Rect(left + pad_x, btn_y,
                                           pw - pad_x * 2, BTN_H)
        hov = self._add_tile_rect.collidepoint(mx, my)
        btn_bg = Theme.BTN_HOVER if hov else Theme.PANEL_LITE
        pygame.draw.rect(surface, btn_bg, self._add_tile_rect,
                         border_radius=br + 1)
        pygame.draw.rect(surface, Theme.ACCENT, self._add_tile_rect, 1,
                         border_radius=br + 1)
        btn_text_off = max(1, (BTN_H - fh) // 2)
        draw_text(surface, "+ Add Tile",
                  self._add_tile_rect.x + L.pad_lg,
                  self._add_tile_rect.y + btn_text_off,
                  Theme.ACCENT, font_sm)

    # ── event handling ───────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event,
                     surface: pygame.Surface) -> str | None:
        L = Layout
        left = 0
        pw = L.palette_w

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

        # Scroll — only inside content region
        if event.type == pygame.MOUSEWHEEL:
            mx, my = pygame.mouse.get_pos()
            if left <= mx < left + pw and L.lp_content_y <= my < L.lp_bottom_y:
                self.scroll_y = max(0, self.scroll_y - event.y * L.scroll_step)
                FILTER_H = self._filter_h()
                BTN_H = self._btn_h()
                visible_h = L.lp_content_h - FILTER_H - L.pad_sm * 2 - BTN_H - L.pad_md
                max_scroll = max(0, self._total_h - visible_h)
                self.scroll_y = min(self.scroll_y, max_scroll)
                return "consumed"

        # Left click
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = event.pos
            if not (left <= mx < left + pw and my >= L.lp_content_y):
                if self._filter_active:
                    self._filter_active = False
                return None

            if self._filter_rect.collidepoint(mx, my):
                self._filter_active = True
                return "consumed"
            else:
                self._filter_active = False

            if self._add_tile_rect.collidepoint(mx, my):
                return "add_tile"

            for hr, tt in self._header_areas:
                if hr.collidepoint(mx, my):
                    key = tt.value
                    if key in self._collapsed:
                        self._collapsed.discard(key)
                    else:
                        self._collapsed.add(key)
                    return "consumed"

            for swatch_r, td in self._hit_areas:
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
            if not (left <= mx < left + pw and my >= L.lp_content_y):
                return None
            for swatch_r, td in self._hit_areas:
                if swatch_r.collidepoint(mx, my):
                    return f"edit_tile:{td.id}"

        return None
