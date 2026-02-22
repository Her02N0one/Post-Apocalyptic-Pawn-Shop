"""editor/panels_pkg/surface_panel.py — Floor/ceiling surface editor panel.

A dedicated left-panel tab for editing per-cell floor and ceiling
properties:  height, texture, and bulk operations (fill, pick, reset).

Surface modes:
  FLOOR — Edits floor_heights and floor_textures grids
  CEIL  — Edits ceil_heights and ceil_textures grids

Tool sub-modes (independent of the main toolbar):
  HEIGHT — Paint height values with brush
  TEXTURE — Paint texture keys with brush
  FILL_H  — Flood-fill height
  FILL_T  — Flood-fill texture
  PICK    — Eyedrop height + texture from clicked cell
  RESET   — Reset cells to defaults
"""

from __future__ import annotations

import os
from typing import Callable

import pygame

from editor.ui import (
    Theme, UIContext, NumberField, Dropdown,
    draw_text, draw_text_centered, draw_tab_button, draw_section_header,
    draw_scrollbar, clamp_scroll,
)
from editor.state import EditorState
from editor.layout import Layout
from editor.panels_pkg.base import PanelBase, PanelRegion


# ── Surface mode ────────────────────────────────────────────────────

class SurfaceTarget:
    """Which surface grid we're editing."""
    FLOOR = "floor"
    CEIL = "ceil"


class SurfaceTool:
    """Sub-tool mode within the surface panel."""
    HEIGHT  = "height"     # paint height values
    TEXTURE = "texture"    # paint texture keys
    FILL_H  = "fill_h"    # flood-fill height
    FILL_T  = "fill_t"    # flood-fill texture
    PICK    = "pick"       # eyedropper
    RESET   = "reset"      # reset to defaults


# Sub-tool button definitions
_TOOL_DEFS: list[tuple[str, str, str]] = [
    ("Height",  SurfaceTool.HEIGHT,  "Paint height"),
    ("Texture", SurfaceTool.TEXTURE, "Paint texture"),
    ("Fill H",  SurfaceTool.FILL_H,  "Fill height"),
    ("Fill T",  SurfaceTool.FILL_T,  "Fill texture"),
    ("Pick",    SurfaceTool.PICK,    "Eyedropper"),
    ("Reset",   SurfaceTool.RESET,   "Reset to default"),
]


class SurfacePanel(PanelBase):
    """Left-panel tab for floor/ceiling surface editing.

    Provides:
    - Floor/Ceiling target toggle
    - Sub-tool selection (height brush, texture brush, fill, pick, reset)
    - Height value slider
    - Texture grid browser (filtered to floor/ceiling-appropriate textures)
    - Current selection preview
    """

    title = "SURFACES"

    def __init__(self, state: EditorState, ctx: UIContext, atlas=None):
        super().__init__()
        self.state = state
        self.ctx = ctx
        self._atlas = atlas

        # Active editing target and tool
        self.target: str = SurfaceTarget.FLOOR
        self.tool: str = SurfaceTool.HEIGHT

        # Current brush values
        self.floor_height: float = 0.0
        self.ceil_height: float = 1.0
        self.floor_texture: str = ""
        self.ceil_texture: str = ""

        # Widget cache
        self._height_field: NumberField | None = None
        self._tex_list: list[str] = []
        self._tex_cache_ready = False
        self._tex_thumbs: dict[str, pygame.Surface] = {}
        self._tex_rects: list[tuple[pygame.Rect, str]] = []
        self._tool_rects: list[tuple[str, pygame.Rect]] = []
        self._target_rects: list[tuple[str, pygame.Rect]] = []

        # Last-known field value to detect external changes
        self._last_height_val: float = -999.0

    # ── Public read-only accessors ───────────────────────────────

    @property
    def active_height(self) -> float:
        """The height value to paint with."""
        if self.target == SurfaceTarget.FLOOR:
            return self.floor_height
        return self.ceil_height

    @active_height.setter
    def active_height(self, v: float):
        if self.target == SurfaceTarget.FLOOR:
            self.floor_height = max(0.0, min(1.0, v))
        else:
            self.ceil_height = max(0.0, min(2.0, v))

    @property
    def active_texture(self) -> str:
        """The texture key to paint with."""
        if self.target == SurfaceTarget.FLOOR:
            return self.floor_texture
        return self.ceil_texture

    @active_texture.setter
    def active_texture(self, v: str):
        if self.target == SurfaceTarget.FLOOR:
            self.floor_texture = v
        else:
            self.ceil_texture = v

    @property
    def is_height_tool(self) -> bool:
        return self.tool in (SurfaceTool.HEIGHT, SurfaceTool.FILL_H)

    @property
    def is_texture_tool(self) -> bool:
        return self.tool in (SurfaceTool.TEXTURE, SurfaceTool.FILL_T)

    # ── Texture list ─────────────────────────────────────────────

    def _ensure_tex_cache(self):
        if self._tex_cache_ready:
            return
        self._tex_cache_ready = True
        try:
            from core.tiles import TILE_TEX_DIR
            self._tex_list = sorted(
                os.path.splitext(f)[0]
                for f in os.listdir(TILE_TEX_DIR)
                if f.endswith(".png")
            )
        except (FileNotFoundError, OSError):
            self._tex_list = []

    def refresh(self):
        """Force rebuild of texture cache."""
        self._tex_cache_ready = False
        self._tex_thumbs.clear()

    def _get_thumb(self, key: str, size: int) -> pygame.Surface | None:
        cache_key = f"{key}_{size}"
        if cache_key not in self._tex_thumbs:
            if self._atlas is None:
                return None
            try:
                full = self._atlas.get_by_key(key)
                self._tex_thumbs[cache_key] = pygame.transform.scale(
                    full, (size, size))
            except (KeyError, pygame.error, AttributeError):
                return None
        return self._tex_thumbs.get(cache_key)

    # ── Drawing ──────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, font: pygame.font.Font,
             font_sm: pygame.font.Font):
        self._ensure_tex_cache()
        L = Layout
        _s = L.s
        left = 0
        pw = L.palette_w
        br = L.border_r
        pad_x = L.pad_md
        fh = font_sm.get_height()

        mx, my = pygame.mouse.get_pos()

        # ── Floor / Ceiling target toggle ────────────────────
        y = L.lp_content_y + L.pad_sm
        self._target_rects.clear()
        tab_h = _s(24)
        tab_w = (pw - L.pad_sm * 3) // 2

        for i, (label, tgt) in enumerate([("Floor", SurfaceTarget.FLOOR),
                                           ("Ceiling", SurfaceTarget.CEIL)]):
            tx = L.pad_sm + i * (tab_w + L.pad_sm)
            tr = pygame.Rect(tx, y, tab_w, tab_h)
            draw_tab_button(surface, tr, label, font_sm,
                            selected=(tgt == self.target),
                            hovered=tr.collidepoint(mx, my),
                            border_r=br)
            self._target_rects.append((tgt, tr))

        y += tab_h + L.pad_md

        # ── Sub-tool buttons (2 rows of 3) ──────────────────
        draw_section_header(surface, "Tool", L.pad_sm, y, pw - L.pad_sm * 2,
                            font_sm)
        y += L.header_h
        self._tool_rects.clear()
        btn_h = _s(22)
        cols = 3
        btn_gap = L.pad_sm
        btn_w = (pw - L.pad_sm * 2 - btn_gap * (cols - 1)) // cols

        for i, (label, tool_val, tip) in enumerate(_TOOL_DEFS):
            col = i % cols
            row = i // cols
            bx = L.pad_sm + col * (btn_w + btn_gap)
            by = y + row * (btn_h + btn_gap)
            btn_r = pygame.Rect(bx, by, btn_w, btn_h)
            draw_tab_button(surface, btn_r, label, font_sm,
                            selected=(tool_val == self.tool),
                            hovered=btn_r.collidepoint(mx, my),
                            border_r=br)
            self._tool_rects.append((tool_val, btn_r))

        n_rows = (len(_TOOL_DEFS) + cols - 1) // cols
        y += n_rows * (btn_h + btn_gap) + L.pad_md

        # ── Height value control ─────────────────────────────
        draw_section_header(surface, "Height", L.pad_sm, y,
                            pw - L.pad_sm * 2, font_sm)
        y += L.header_h

        # Determine current height and range
        if self.target == SurfaceTarget.FLOOR:
            cur_h = self.floor_height
            min_h, max_h = 0.0, 1.0
        else:
            cur_h = self.ceil_height
            min_h, max_h = 0.0, 2.0

        # Number field for height
        field_w = pw - L.pad_sm * 2 - _s(60)
        field_r = pygame.Rect(L.pad_sm + _s(55), y, field_w, L.field_h)

        # Recreate field if value changed externally or doesn't exist
        if (self._height_field is None
                or abs(cur_h - self._last_height_val) > 0.001):
            self._height_field = NumberField(
                field_r, self.ctx, value=round(cur_h, 2),
                min_val=min_h, max_val=max_h, step=0.05, decimals=2)
            self._height_field.on_change = self._on_height_change
            self._last_height_val = cur_h
        else:
            self._height_field.rect = field_r

        draw_text(surface, "Value:", L.pad_sm + L.pad_sm, y + 3,
                  Theme.TEXT_DIM, font_sm)
        self._height_field.draw(surface, font_sm)
        y += L.field_h + L.pad_sm

        # Quick-set height buttons
        presets = [0.0, 0.25, 0.5, 0.75, 1.0]
        if self.target == SurfaceTarget.CEIL:
            presets = [0.5, 0.75, 1.0, 1.5, 2.0]
        preset_w = (pw - L.pad_sm * 2 - btn_gap * (len(presets) - 1)) // len(presets)
        self._preset_rects: list[tuple[float, pygame.Rect]] = []
        for i, pv in enumerate(presets):
            px = L.pad_sm + i * (preset_w + btn_gap)
            pr = pygame.Rect(px, y, preset_w, _s(20))
            is_sel = abs(cur_h - pv) < 0.001
            is_hov = pr.collidepoint(mx, my)
            bg = Theme.ACCENT if is_sel else (Theme.BTN_HOVER if is_hov else Theme.PANEL_LITE)
            pygame.draw.rect(surface, bg, pr, border_radius=br)
            pygame.draw.rect(surface, Theme.BORDER, pr, 1, border_radius=br)
            draw_text_centered(surface, f"{pv:.2f}", pr, Theme.TEXT, font_sm)
            self._preset_rects.append((pv, pr))
        y += _s(20) + L.pad_md

        # ── Current texture display ──────────────────────────
        draw_section_header(surface, "Texture", L.pad_sm, y,
                            pw - L.pad_sm * 2, font_sm)
        y += L.header_h

        cur_tex = self.active_texture
        tex_display = cur_tex if cur_tex else "(default / none)"

        # Preview thumbnail
        thumb_sz = _s(48)
        thumb_r = pygame.Rect(L.pad_sm, y, thumb_sz, thumb_sz)
        if cur_tex:
            thumb = self._get_thumb(cur_tex, thumb_sz)
            if thumb:
                surface.blit(thumb, thumb_r.topleft)
            else:
                pygame.draw.rect(surface, (60, 60, 60), thumb_r, border_radius=br)
                draw_text_centered(surface, "?", thumb_r, Theme.TEXT_DIM, font_sm)
        else:
            pygame.draw.rect(surface, (40, 40, 44), thumb_r, border_radius=br)
            draw_text_centered(surface, "—", thumb_r, Theme.TEXT_DIM, font_sm)

        # Texture name
        draw_text(surface, tex_display[:20],
                  L.pad_sm + thumb_sz + L.pad_md, y + 2,
                  Theme.TEXT, font_sm)

        # Clear button
        clr_r = pygame.Rect(L.pad_sm + thumb_sz + L.pad_md,
                             y + fh + L.pad_sm,
                             _s(50), _s(18))
        clr_hov = clr_r.collidepoint(mx, my)
        pygame.draw.rect(surface, Theme.DANGER if clr_hov else Theme.PANEL_LITE,
                         clr_r, border_radius=br)
        draw_text_centered(surface, "Clear", clr_r, Theme.TEXT, font_sm)
        self._clear_tex_rect = clr_r

        y += thumb_sz + L.pad_md

        # ── Texture grid (scrollable) ────────────────────────
        draw_section_header(surface, f"Textures ({len(self._tex_list)})",
                            L.pad_sm, y, pw - L.pad_sm * 2, font_sm)
        y += L.header_h

        # The texture grid occupies the rest of the panel
        grid_top = y
        grid_bot = L.lp_bottom_y
        grid_clip = pygame.Rect(left, grid_top, pw, grid_bot - grid_top)
        surface.set_clip(grid_clip)

        THUMB = _s(32)
        PAD = L.pad_sm
        grid_cols = max(1, (pw - L.pad_md) // (THUMB + PAD))

        self._tex_rects.clear()
        gy = int(grid_top - self.scroll_y)

        for i, key in enumerate(self._tex_list):
            col = i % grid_cols
            row_y = gy + (i // grid_cols) * (THUMB + PAD)
            tx = L.pad_sm + col * (THUMB + PAD)
            ty = row_y

            ir = pygame.Rect(tx, ty, THUMB, THUMB)
            if ir.bottom >= grid_clip.top and ir.top < grid_clip.bottom:
                thumb = self._get_thumb(key, THUMB)
                if thumb:
                    surface.blit(thumb, ir.topleft)
                else:
                    pygame.draw.rect(surface, (60, 60, 60), ir,
                                     border_radius=max(1, br - 1))

                # Highlight if selected
                if key == self.active_texture:
                    pygame.draw.rect(surface, Theme.ACCENT, ir, 2,
                                     border_radius=max(1, br - 1))
                elif ir.collidepoint(mx, my):
                    pygame.draw.rect(surface, Theme.HIGHLIGHT, ir, 2,
                                     border_radius=max(1, br - 1))
                    # Tooltip
                    tw = font_sm.size(key)[0] + L.pad_md
                    tip_r = pygame.Rect(tx, ty + THUMB + 2, tw, fh + PAD)
                    if tip_r.right > pw:
                        tip_r.right = pw - 2
                    pygame.draw.rect(surface, (30, 30, 36), tip_r,
                                     border_radius=max(1, br - 1))
                    draw_text(surface, key, tip_r.x + PAD, tip_r.y + 1,
                              Theme.TEXT, font_sm)

            self._tex_rects.append((ir, key))

        n_tex_rows = (len(self._tex_list) + grid_cols - 1) // max(1, grid_cols)
        self._total_h = n_tex_rows * (THUMB + PAD)
        visible_h = grid_bot - grid_top
        self.scroll_y = clamp_scroll(self.scroll_y, self._total_h, visible_h)

        surface.set_clip(None)

        # ── Info bar at bottom ───────────────────────────────
        info_y = L.lp_bottom_y - _s(18)
        tgt_lbl = "FLOOR" if self.target == SurfaceTarget.FLOOR else "CEIL"
        info = f"{tgt_lbl}  H:{cur_h:.2f}  T:{cur_tex or '—'}"
        draw_text(surface, info, L.pad_sm, info_y, Theme.TEXT_DIM, font_sm)

    # ── Event handling ───────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event,
                     surface: pygame.Surface) -> str | None:
        L = Layout
        left = 0
        pw = L.palette_w

        # Height field events
        if self._height_field is not None:
            if self._height_field.handle_event(event):
                return "consumed"

        # Mouse button clicks
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = event.pos
            if not (left <= mx < left + pw):
                return None

            # Target toggle
            for tgt, tr in self._target_rects:
                if tr.collidepoint(mx, my):
                    self.target = tgt
                    self._height_field = None  # force rebuild
                    self._last_height_val = -999.0
                    return "consumed"

            # Sub-tool buttons
            for tool_val, btn_r in self._tool_rects:
                if btn_r.collidepoint(mx, my):
                    self.tool = tool_val
                    return "consumed"

            # Height presets
            if hasattr(self, '_preset_rects'):
                for pv, pr in self._preset_rects:
                    if pr.collidepoint(mx, my):
                        self.active_height = pv
                        self._height_field = None
                        self._last_height_val = -999.0
                        return "consumed"

            # Clear texture button
            if hasattr(self, '_clear_tex_rect'):
                if self._clear_tex_rect.collidepoint(mx, my):
                    self.active_texture = ""
                    return "consumed"

            # Texture grid click
            for ir, key in self._tex_rects:
                if ir.collidepoint(mx, my):
                    self.active_texture = key
                    # Auto-switch to texture tool
                    if self.tool in (SurfaceTool.HEIGHT, SurfaceTool.FILL_H):
                        self.tool = SurfaceTool.TEXTURE
                    return "consumed"

        # Scroll wheel in texture grid area
        if event.type == pygame.MOUSEWHEEL:
            mx, my = pygame.mouse.get_pos()
            if left <= mx < left + pw and my >= L.lp_content_y:
                self.scroll_y = max(0, self.scroll_y - event.y * L.scroll_step)
                return "consumed"

        return None

    # ── Callbacks ────────────────────────────────────────────────

    def _on_height_change(self, value: float):
        self.active_height = value
        self._last_height_val = value
