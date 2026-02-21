"""editor/modals.py — Overlay dialogs: zone picker, text input,
prefab picker, portal wizard, add-component dialog.
"""

from __future__ import annotations

from typing import Any, Callable

import pygame

from core.tiles import TILE_COLORS
from core.constants import TILE_SIZE
from core.constants import DIR_ARROWS, DIRECTIONS
from core.fonts import get_font
from editor.ui import (
    Theme, UIContext, Button, TextField, NumberField, Dropdown, Slider,
    Checkbox, draw_text, draw_text_centered,
)
from editor.state import EditorState, list_zones, ZONES_DIR
from editor.canvas import get_prefab_defaults
from editor.entity_factory import create_prefab_entity, create_forge_entity
from editor.layout import Layout as _L

import json


# ═════════════════════════════════════════════════════════════════════
#  Modal Manager — only one modal active at a time
# ═════════════════════════════════════════════════════════════════════

class ModalManager:
    def __init__(self, state: EditorState, ctx: UIContext):
        self.state = state
        self.ctx = ctx
        self._active: _BaseModal | None = None

    @property
    def active(self) -> bool:
        return self._active is not None

    def open(self, modal: "_BaseModal"):
        self._active = modal

    def close(self):
        self._active = None
        self.ctx.release_focus()

    def draw(self, surface: pygame.Surface, font: pygame.font.Font,
             font_sm: pygame.font.Font, dt: float = 0.016):
        if self._active:
            self._active.draw(surface, font, font_sm, dt)

    def handle_event(self, event: pygame.event.Event) -> bool:
        """Returns True if event was consumed."""
        if self._active:
            return self._active.handle_event(event)
        return False


# ═════════════════════════════════════════════════════════════════════
#  Base modal
# ═════════════════════════════════════════════════════════════════════

class _BaseModal:
    def __init__(self, manager: ModalManager):
        self.manager = manager
        self.state = manager.state
        self.ctx = manager.ctx
        self._overlay: pygame.Surface | None = None
        self._overlay_size: tuple[int, int] = (0, 0)

    def draw(self, surface, font, font_sm, dt):
        # Darken background — reuse cached surface to avoid per-frame alloc
        sw, sh = surface.get_size()
        if self._overlay is None or self._overlay_size != (sw, sh):
            self._overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
            self._overlay.fill((0, 0, 0, 180))
            self._overlay_size = (sw, sh)
        surface.blit(self._overlay, (0, 0))

    def handle_event(self, event) -> bool:
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.manager.close()
            return True
        return False

    def _centered_rect(self, surface, width, height) -> pygame.Rect:
        from editor.layout import Layout
        w = Layout.s(width)
        h = Layout.s(height)
        sw, sh = surface.get_size()
        # Clamp to screen so modal never overflows
        w = min(w, sw - 20)
        h = min(h, sh - 20)
        return pygame.Rect((sw - w) // 2, (sh - h) // 2, w, h)

    def _draw_panel(self, surface, rect, title="",
                    border_color=Theme.ACCENT):
        from editor.layout import Layout
        br = Layout.s(10)
        pygame.draw.rect(surface, Theme.PANEL, rect, border_radius=br)
        pygame.draw.rect(surface, border_color, rect, 2, border_radius=br)
        if title:
            font = get_font(max(11, round(14 * Layout.scale)))
            draw_text(surface, title, rect.x + Layout.s(16),
                      rect.y + Layout.s(12), border_color, font)


# ═════════════════════════════════════════════════════════════════════
#  TextInputModal
# ═════════════════════════════════════════════════════════════════════

class TextInputModal(_BaseModal):
    def __init__(self, manager: ModalManager, label: str,
                 initial: str, callback: Callable[[str], None]):
        super().__init__(manager)
        self.label = label
        self.callback = callback
        self.field = TextField(
            pygame.Rect(0, 0, 380, 28), self.ctx, value=initial)
        self.ctx.take_focus(self.field.uid)

    def draw(self, surface, font, font_sm, dt):
        super().draw(surface, font, font_sm, dt)
        rect = self._centered_rect(surface, 420, 100)
        self._draw_panel(surface, rect, "")

        draw_text(surface, self.label, rect.x + 16, rect.y + 14,
                  Theme.TEXT_DIM, font_sm)
        self.field.rect = pygame.Rect(rect.x + 16, rect.y + 38, 388, 28)
        self.field.draw(surface, font, dt)
        draw_text(surface, "Enter = confirm  |  Esc = cancel",
                  rect.x + 16, rect.y + 74, Theme.TEXT_DIM, font_sm)

    def handle_event(self, event) -> bool:
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_RETURN:
                val = self.field.value.strip()
                if val:
                    self.callback(val)
                self.manager.close()
                return True
            if event.key == pygame.K_ESCAPE:
                self.manager.close()
                return True
        self.field.handle_event(event)
        return True


# ═════════════════════════════════════════════════════════════════════
#  NewZoneModal — name + dimensions
# ═════════════════════════════════════════════════════════════════════

class NewZoneModal(_BaseModal):
    """Create a new zone with user-chosen name and dimensions."""

    def __init__(self, manager: ModalManager,
                 callback: "Callable[[str, int, int], None]"):
        super().__init__(manager)
        self.callback = callback
        self.name_field = TextField(
            pygame.Rect(0, 0, 250, 28), self.ctx, value="untitled")
        self.w_field = NumberField(
            pygame.Rect(0, 0, 80, 28), self.ctx, value=30,
            min_val=5, max_val=200)
        self.h_field = NumberField(
            pygame.Rect(0, 0, 80, 28), self.ctx, value=20,
            min_val=5, max_val=200)
        self.ctx.take_focus(self.name_field.uid)

    def draw(self, surface, font, font_sm, dt):
        super().draw(surface, font, font_sm, dt)
        rect = self._centered_rect(surface, 420, 160)
        self._draw_panel(surface, rect, "New Zone")

        y0 = rect.y + _L.s(36)
        lx = rect.x + _L.s(16)
        fx = rect.x + _L.s(100)

        draw_text(surface, "Name:", lx, y0 + 4, Theme.TEXT_DIM, font_sm)
        self.name_field.rect = pygame.Rect(fx, y0, _L.s(250), _L.s(28))
        self.name_field.draw(surface, font, dt)
        y0 += _L.s(38)

        draw_text(surface, "Width:", lx, y0 + 4, Theme.TEXT_DIM, font_sm)
        self.w_field.rect = pygame.Rect(fx, y0, _L.s(80), _L.s(28))
        self.w_field.draw(surface, font_sm, dt)

        draw_text(surface, "Height:", fx + _L.s(100), y0 + 4,
                  Theme.TEXT_DIM, font_sm)
        self.h_field.rect = pygame.Rect(fx + _L.s(160), y0, _L.s(80), _L.s(28))
        self.h_field.draw(surface, font_sm, dt)
        y0 += _L.s(38)

        draw_text(surface, "Enter = create  |  Esc = cancel",
                  lx, y0 + 4, Theme.TEXT_DIM, font_sm)

    def handle_event(self, event) -> bool:
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_RETURN:
                name = self.name_field.value.strip()
                if name:
                    self.callback(name, int(self.w_field.value),
                                  int(self.h_field.value))
                self.manager.close()
                return True
            if event.key == pygame.K_ESCAPE:
                self.manager.close()
                return True
        self.name_field.handle_event(event)
        self.w_field.handle_event(event)
        self.h_field.handle_event(event)
        return True


# ═════════════════════════════════════════════════════════════════════
#  ZonePickerModal
# ═════════════════════════════════════════════════════════════════════

class ZonePickerModal(_BaseModal):
    def __init__(self, manager: ModalManager):
        super().__init__(manager)
        self.zones = list_zones()
        self.scroll = 0

    def draw(self, surface, font, font_sm, dt):
        super().draw(surface, font, font_sm, dt)
        sw, sh = surface.get_size()
        rect = self._centered_rect(surface, 500, sh - 120)
        self._draw_panel(surface, rect, "Select Zone")

        item_h = _L.s(32)
        list_y = rect.y + _L.s(40)
        clip = pygame.Rect(rect.x + _L.pad_md, list_y,
                           rect.w - 2 * _L.pad_md, rect.h - _L.s(60))
        surface.set_clip(clip)
        mx, my = pygame.mouse.get_pos()

        for i, z in enumerate(self.zones):
            iy = list_y + i * item_h - self.scroll
            if iy + item_h < clip.y or iy > clip.bottom:
                continue
            is_current = (z == self.state.zone_name)
            ir = pygame.Rect(rect.x + _L.pad_lg, iy,
                             rect.w - 2 * _L.pad_lg, item_h - 2)
            is_hov = ir.collidepoint(mx, my)
            if is_hov:
                pygame.draw.rect(surface, Theme.HIGHLIGHT, ir,
                                 border_radius=_L.border_r)
            elif is_current:
                pygame.draw.rect(surface, Theme.SELECTED, ir,
                                 border_radius=_L.border_r)
            color = Theme.ACCENT if is_current else Theme.TEXT
            draw_text(surface, z, ir.x + _L.pad_lg,
                      ir.y + _L.pad_md, color, font)

        surface.set_clip(None)

    def handle_event(self, event) -> bool:
        if event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE,
                                                           pygame.K_TAB):
            self.manager.close()
            return True
        if event.type == pygame.MOUSEWHEEL:
            self.scroll = max(0, self.scroll - event.y * 30)
            return True
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            sw, sh = pygame.display.get_surface().get_size()
            rect = self._centered_rect(pygame.display.get_surface(),
                                       500, sh - 120)
            item_h = _L.s(32)
            list_y = rect.y + _L.s(40)
            for i, z in enumerate(self.zones):
                iy = list_y + i * item_h - self.scroll
                ir = pygame.Rect(rect.x + _L.pad_lg, iy,
                                 rect.w - 2 * _L.pad_lg, item_h)
                if ir.collidepoint(event.pos):
                    self.state.load_zone(z)
                    self.manager.close()
                    return True
        return True


# ═════════════════════════════════════════════════════════════════════
#  AddComponentModal
# ═════════════════════════════════════════════════════════════════════

class AddComponentModal(_BaseModal):
    """Let user add a missing component to the selected entity."""

    COMPONENTS = [
        "collider", "health", "tile_entity", "wall_sprite",
        "inventory", "facing", "dialogue", "sprite", "combat_stats",
    ]

    def __init__(self, manager: ModalManager):
        super().__init__(manager)
        # Filter to only missing components
        st = self.state
        ent = st.entities[st.selected_entity] if 0 <= st.selected_entity < len(st.entities) else None
        self.available: list[str] = []
        if ent:
            for comp_name in self.COMPONENTS:
                if getattr(ent, comp_name, None) is None:
                    self.available.append(comp_name)

    def draw(self, surface, font, font_sm, dt):
        super().draw(surface, font, font_sm, dt)
        row = _L.s(30)
        rect = self._centered_rect(surface, 300,
                                    _L.s(40) + len(self.available) * row + row)
        self._draw_panel(surface, rect, "Add Component")

        for i, comp_name in enumerate(self.available):
            iy = rect.y + _L.s(40) + i * row
            ir = pygame.Rect(rect.x + _L.pad_lg, iy,
                             rect.w - 2 * _L.pad_lg, _L.btn_h)
            hov = ir.collidepoint(pygame.mouse.get_pos())
            bg = Theme.HIGHLIGHT if hov else Theme.PANEL
            pygame.draw.rect(surface, bg, ir, border_radius=_L.border_r)
            draw_text(surface, comp_name.replace("_", " ").title(),
                      ir.x + _L.pad_lg, ir.y + _L.pad_md,
                      Theme.TEXT, font_sm)

        if not self.available:
            draw_text(surface, "All components present",
                      rect.x + _L.s(16), rect.y + _L.s(44),
                      Theme.TEXT_DIM, font_sm)

    def handle_event(self, event) -> bool:
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.manager.close()
            return True
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            surf = pygame.display.get_surface()
            row = _L.s(30)
            rect = self._centered_rect(surf, 300,
                                       _L.s(40) + len(self.available) * row + row)
            for i, comp_name in enumerate(self.available):
                iy = rect.y + _L.s(40) + i * row
                ir = pygame.Rect(rect.x + _L.pad_lg, iy,
                                 rect.w - 2 * _L.pad_lg, _L.btn_h)
                if ir.collidepoint(event.pos):
                    st = self.state
                    ent = st.entities[st.selected_entity]
                    ent.add_component(comp_name)
                    st.push_undo()
                    st.toast(f"Added: {comp_name}")
                    self.manager.close()
                    return True
        return True


# ═════════════════════════════════════════════════════════════════════
#  TileEditorModal — create / edit ANY tile definition
# ═════════════════════════════════════════════════════════════════════

import os as _os
from pathlib import Path as _Path

from core.tiles import (
    TF, TileDef, TileType, TILE_REGISTRY, TILE_CATEGORIES, TC_CUSTOM,
    register_tile, update_tile, delete_tile, save_tiles,
    add_category, TILE_TEX_DIR,
    _TYPE_FLAGS, _TYPE_DEFAULT_HEIGHT,
    # Backward-compat aliases so old call-sites don't break
    register_custom_tile, delete_custom_tile, save_custom_tiles,
)

_TILE_TYPES = list(TileType)
_TILE_TYPE_LABELS = [t.value for t in _TILE_TYPES]


class TileEditorModal(_BaseModal):
    """Full tile editor — create, edit, or delete ANY tile.

    Shows a 64x64 texture preview, lets the user browse for a
    texture PNG, export the procedural texture, and manage categories.
    """

    # Extra flag options (not covered by type)
    EXTRA_FLAG_OPTIONS = [
        ("TRANSPARENT", TF.TRANSPARENT, "See-through wall"),
        ("FARMLAND", TF.FARMLAND, "Tillable soil"),
    ]

    def __init__(self, manager: ModalManager,
                 edit_tile: TileDef | None = None,
                 atlas=None):
        super().__init__(manager)
        self._editing = edit_tile
        self._atlas = atlas
        # Form state
        self._name = edit_tile.name if edit_tile else ""
        self._color = list(edit_tile.color) if edit_tile else [120, 120, 120]
        self._tile_type: TileType = edit_tile.type if edit_tile else TileType.FLOOR
        self._extra_flags: TF = TF.NONE
        if edit_tile:
            if edit_tile.transparent:
                self._extra_flags |= TF.TRANSPARENT
            if edit_tile.farmland:
                self._extra_flags |= TF.FARMLAND
        self._texture_key = edit_tile.texture_key or "" if edit_tile else ""
        # Directional texture overrides (front / back)
        self._texture_front = edit_tile.texture_front if edit_tile else ""
        self._texture_back = edit_tile.texture_back if edit_tile else ""
        self._height_scale = edit_tile.height_scale if edit_tile else 1.0
        self._category = edit_tile.category if edit_tile else TC_CUSTOM
        # UI state
        self._name_active = False
        self._tex_active = False
        self._cat_active = False   # free-text category input
        self._cat_open = False
        self._cat_text = ""        # typed category (for "new category")
        self._error: str = ""
        self._tex_preview: pygame.Surface | None = None
        self._build_preview()

    def _build_preview(self):
        """Build the 64x64 texture preview from the atlas."""
        if self._atlas and self._editing:
            try:
                self._tex_preview = self._atlas.get(self._editing.id).copy()
            except (KeyError, AttributeError, pygame.error):
                self._tex_preview = None
        else:
            self._tex_preview = None

    def _tex_file_path(self) -> str:
        """Return the expected texture PNG path for current texture_key."""
        key = self._texture_key.strip()
        if not key:
            return ""
        return _os.path.join(TILE_TEX_DIR, f"{key}.png")

    def _tex_file_exists(self) -> bool:
        p = self._tex_file_path()
        return bool(p and _os.path.exists(p))

    # ── drawing ──────────────────────────────────────────────────

    def draw(self, surface, font, font_sm, dt):
        super().draw(surface, font, font_sm, dt)
        W, H = 400, 620
        rect = self._centered_rect(surface, W, H)
        title = f"Edit Tile (ID {self._editing.id})" if self._editing else "New Tile"
        self._draw_panel(surface, rect, title)

        x0 = rect.x + 16
        y = rect.y + 38
        rw = rect.w - 32
        mx, my = pygame.mouse.get_pos()

        # ── Texture preview (64x64) ─────────────────────────────
        prev_r = pygame.Rect(x0, y, 64, 64)
        pygame.draw.rect(surface, (30, 30, 35), prev_r)
        if self._tex_preview:
            surface.blit(self._tex_preview, prev_r.topleft)
        else:
            # Fallback: draw colour swatch
            pygame.draw.rect(surface, tuple(self._color),
                             prev_r.inflate(-4, -4))
        pygame.draw.rect(surface, Theme.BORDER, prev_r, 1)

        # File path info beside preview
        tx = x0 + 72
        key = self._texture_key.strip() or "—"
        exists = self._tex_file_exists()
        file_col = Theme.SUCCESS if exists else Theme.TEXT_DIM
        draw_text(surface, f"tex: {key}.png", tx, y + 2, file_col, font_sm)
        status = "found" if exists else "not found (procedural)"
        draw_text(surface, status, tx, y + 16, file_col, font_sm)

        self._export_rect = pygame.Rect(0, 0, 0, 0)  # disabled

        # Import button
        imp_r = pygame.Rect(tx, y + 34, 110, 22)
        ihov = imp_r.collidepoint(mx, my)
        pygame.draw.rect(surface, Theme.BTN_HOVER if ihov else Theme.PANEL_LITE,
                         imp_r, border_radius=3)
        pygame.draw.rect(surface, Theme.ACCENT2 if Theme.ACCENT2 else Theme.ACCENT,
                         imp_r, 1, border_radius=3)
        draw_text(surface, "Import PNG", imp_r.x + 8, imp_r.y + 5,
                  Theme.ACCENT2 if Theme.ACCENT2 else Theme.ACCENT, font_sm)
        self._import_rect = imp_r

        y += 72

        # ── Name ────────────────────────────────────────────────
        draw_text(surface, "Name:", x0, y, Theme.TEXT_DIM, font_sm)
        y += 16
        name_r = pygame.Rect(x0, y, rw, 22)
        bg = (35, 35, 42) if self._name_active else Theme.FIELD_BG
        pygame.draw.rect(surface, bg, name_r, border_radius=3)
        pygame.draw.rect(surface, Theme.BORDER, name_r, 1, border_radius=3)
        disp_name = self._name or "e.g. Mossy Stone"
        nc = Theme.TEXT if self._name else Theme.TEXT_DIM
        draw_text(surface, disp_name, name_r.x + 4, name_r.y + 4, nc, font_sm)
        if self._name_active and pygame.time.get_ticks() % 1000 < 500:
            cx = name_r.x + 4 + font_sm.size(self._name)[0]
            pygame.draw.line(surface, Theme.ACCENT,
                             (cx, name_r.y + 3), (cx, name_r.y + 19))
        self._name_rect = name_r
        y += 28

        # ── Colour preview + RGB sliders ────────────────────────
        draw_text(surface, "Color:", x0, y, Theme.TEXT_DIM, font_sm)
        swatch_r = pygame.Rect(x0 + 50, y - 2, 24, 18)
        pygame.draw.rect(surface, tuple(self._color), swatch_r,
                         border_radius=3)
        pygame.draw.rect(surface, (80, 80, 80), swatch_r, 1,
                         border_radius=3)
        y += 18
        self._color_slider_rects = []
        for i, label in enumerate(("R", "G", "B")):
            lbl_color = [(200, 80, 80), (80, 200, 80), (80, 80, 200)][i]
            draw_text(surface, label, x0, y + 2, lbl_color, font_sm)
            bar_r = pygame.Rect(x0 + 16, y + 2, rw - 60, 12)
            pygame.draw.rect(surface, Theme.FIELD_BG, bar_r, border_radius=3)
            frac = self._color[i] / 255.0
            fill_r = pygame.Rect(bar_r.x, bar_r.y,
                                 int(bar_r.w * frac), bar_r.h)
            pygame.draw.rect(surface, lbl_color, fill_r, border_radius=3)
            draw_text(surface, str(self._color[i]),
                      bar_r.right + 4, y + 1, Theme.TEXT, font_sm)
            self._color_slider_rects.append((bar_r, i))
            y += 18

        # ── Tile Type (dropdown) ─────────────────────────────────
        y += 4
        draw_text(surface, "Type:", x0, y, Theme.TEXT_DIM, font_sm)
        y += 16
        type_r = pygame.Rect(x0, y, rw, 22)
        pygame.draw.rect(surface, Theme.FIELD_BG, type_r, border_radius=3)
        pygame.draw.rect(surface, Theme.BORDER, type_r, 1, border_radius=3)
        draw_text(surface, self._tile_type.value, type_r.x + 6, type_r.y + 4,
                  Theme.TEXT, font_sm)
        draw_text(surface, "\u25BE", type_r.right - 16, type_r.y + 4,
                  Theme.TEXT_DIM, font_sm)
        self._type_rect = type_r
        # Type dropdown items (rendered when open)
        if getattr(self, '_type_open', False):
            for ti, tt in enumerate(_TILE_TYPES):
                ir = pygame.Rect(type_r.x, type_r.bottom + ti * 22,
                                 type_r.w, 22)
                bg = Theme.BTN_HOVER if ir.collidepoint(mx, my) else Theme.PANEL_LITE
                pygame.draw.rect(surface, bg, ir)
                pygame.draw.rect(surface, Theme.BORDER, ir, 1)
                draw_text(surface, tt.value, ir.x + 6, ir.y + 4,
                          Theme.TEXT, font_sm)
        y += 28

        # ── Extra flags (TRANSPARENT, FARMLAND) ─────────────────
        self._flag_rects = []
        col_w = rw // 2
        for idx, (fname, fval, fdesc) in enumerate(self.EXTRA_FLAG_OPTIONS):
            col = idx % 2
            if col == 0:
                row_y = y
            fx = x0 + col * col_w
            fy = row_y
            cb_r = pygame.Rect(fx, fy, 14, 14)
            checked = bool(self._extra_flags & fval)
            bg = Theme.ACCENT if checked else Theme.FIELD_BG
            pygame.draw.rect(surface, bg, cb_r, border_radius=2)
            pygame.draw.rect(surface, Theme.BORDER, cb_r, 1, border_radius=2)
            if checked:
                draw_text(surface, "\u2713", cb_r.x + 2, cb_r.y, (255, 255, 255), font_sm)
            draw_text(surface, fname, fx + 18, fy + 1, Theme.TEXT, font_sm)
            self._flag_rects.append((cb_r, fval))
            if col == 1:
                y += 20
        if len(self.EXTRA_FLAG_OPTIONS) % 2 == 1:
            y += 20
        y += 4

        # ── Texture key ─────────────────────────────────────────
        draw_text(surface, "Texture Key:", x0, y, Theme.TEXT_DIM, font_sm)
        y += 16
        tex_r = pygame.Rect(x0, y, rw, 22)
        bg = (35, 35, 42) if self._tex_active else Theme.FIELD_BG
        pygame.draw.rect(surface, bg, tex_r, border_radius=3)
        pygame.draw.rect(surface, Theme.BORDER, tex_r, 1, border_radius=3)
        disp_tex = self._texture_key or "e.g. mossy_stone"
        tc = Theme.TEXT if self._texture_key else Theme.TEXT_DIM
        draw_text(surface, disp_tex, tex_r.x + 4, tex_r.y + 4, tc, font_sm)
        if self._tex_active and pygame.time.get_ticks() % 1000 < 500:
            cx = tex_r.x + 4 + font_sm.size(self._texture_key)[0]
            pygame.draw.line(surface, Theme.ACCENT,
                             (cx, tex_r.y + 3), (cx, tex_r.y + 19))
        self._tex_rect = tex_r
        y += 26

        # ── Directional textures (front / back) ─────────────────
        if not hasattr(self, '_front_rect'):
            self._front_rect: pygame.Rect = pygame.Rect(0, 0, 0, 0)
            self._back_rect: pygame.Rect = pygame.Rect(0, 0, 0, 0)
            self._front_active: bool = False
            self._back_active: bool = False

        draw_text(surface, "Front Tex:", x0, y, Theme.TEXT_DIM, font_sm)
        fr = pygame.Rect(x0 + 75, y - 2, rw - 75, 20)
        bg = (35, 35, 42) if self._front_active else Theme.FIELD_BG
        pygame.draw.rect(surface, bg, fr, border_radius=3)
        pygame.draw.rect(surface, Theme.BORDER, fr, 1, border_radius=3)
        val_f = self._texture_front or "(none)"
        tc_f = Theme.TEXT if self._texture_front else Theme.TEXT_DIM
        draw_text(surface, val_f, fr.x + 4, fr.y + 3, tc_f, font_sm)
        if self._front_active and pygame.time.get_ticks() % 1000 < 500:
            cx = fr.x + 4 + font_sm.size(self._texture_front)[0]
            pygame.draw.line(surface, Theme.ACCENT,
                             (cx, fr.y + 2), (cx, fr.y + 17))
        self._front_rect = fr
        y += 22

        draw_text(surface, "Back Tex:", x0, y, Theme.TEXT_DIM, font_sm)
        br = pygame.Rect(x0 + 75, y - 2, rw - 75, 20)
        bg = (35, 35, 42) if self._back_active else Theme.FIELD_BG
        pygame.draw.rect(surface, bg, br, border_radius=3)
        pygame.draw.rect(surface, Theme.BORDER, br, 1, border_radius=3)
        val_b = self._texture_back or "(none)"
        tc_b = Theme.TEXT if self._texture_back else Theme.TEXT_DIM
        draw_text(surface, val_b, br.x + 4, br.y + 3, tc_b, font_sm)
        if self._back_active and pygame.time.get_ticks() % 1000 < 500:
            cx = br.x + 4 + font_sm.size(self._texture_back)[0]
            pygame.draw.line(surface, Theme.ACCENT,
                             (cx, br.y + 2), (cx, br.y + 17))
        self._back_rect = br
        y += 26

        # ── Height scale ────────────────────────────────────────
        draw_text(surface, "Height:", x0, y, Theme.TEXT_DIM, font_sm)
        hs_bar = pygame.Rect(x0 + 60, y + 2, rw - 100, 12)
        pygame.draw.rect(surface, Theme.FIELD_BG, hs_bar, border_radius=3)
        frac = min(1.0, self._height_scale)
        fill_r = pygame.Rect(hs_bar.x, hs_bar.y,
                             int(hs_bar.w * frac), hs_bar.h)
        pygame.draw.rect(surface, Theme.ACCENT, fill_r, border_radius=3)
        draw_text(surface, f"{self._height_scale:.2f}",
                  hs_bar.right + 4, y, Theme.TEXT, font_sm)
        self._hs_rect = hs_bar
        y += 22

        # ── Category (dropdown + free-text for new) ─────────────
        draw_text(surface, "Category:", x0, y, Theme.TEXT_DIM, font_sm)
        cat_r = pygame.Rect(x0 + 80, y - 2, rw - 80, 22)
        hov = cat_r.collidepoint(mx, my)
        pygame.draw.rect(surface, Theme.BTN_HOVER if hov else Theme.FIELD_BG,
                         cat_r, border_radius=3)
        pygame.draw.rect(surface, Theme.BORDER, cat_r, 1, border_radius=3)
        if self._cat_active:
            disp_cat = self._cat_text or "type new category..."
            cc = Theme.TEXT if self._cat_text else Theme.TEXT_DIM
            draw_text(surface, disp_cat, cat_r.x + 6, cat_r.y + 4, cc, font_sm)
            if pygame.time.get_ticks() % 1000 < 500:
                cx = cat_r.x + 6 + font_sm.size(self._cat_text)[0]
                pygame.draw.line(surface, Theme.ACCENT,
                                 (cx, cat_r.y + 3), (cx, cat_r.y + 19))
        else:
            draw_text(surface, self._category, cat_r.x + 6, cat_r.y + 4,
                      Theme.TEXT, font_sm)
            draw_text(surface, "\u25be", cat_r.right - 14, cat_r.y + 4,
                      Theme.TEXT_DIM, font_sm)
        self._cat_rect = cat_r
        y += 28

        # Category dropdown overlay
        if self._cat_open:
            cat_items = list(TILE_CATEGORIES) + ["+ New Category..."]
            dy = cat_r.bottom
            for ci, cname in enumerate(cat_items):
                cr = pygame.Rect(cat_r.x, dy + ci * 22, cat_r.w, 22)
                chov = cr.collidepoint(mx, my)
                pygame.draw.rect(surface,
                                 Theme.HIGHLIGHT if chov else Theme.PANEL, cr)
                pygame.draw.rect(surface, Theme.BORDER, cr, 1)
                if cname.startswith("+"):
                    col = Theme.ACCENT2
                else:
                    col = Theme.ACCENT if cname == self._category else Theme.TEXT
                draw_text(surface, cname, cr.x + 6, cr.y + 4, col, font_sm)

        # ── Error message ───────────────────────────────────────
        if self._error:
            draw_text(surface, self._error, x0, y, Theme.DANGER, font_sm)
            y += 16

        # ── Action buttons ──────────────────────────────────────
        y = rect.bottom - 40
        # Save/Create button
        save_r = pygame.Rect(x0, y, 100, 28)
        hov = save_r.collidepoint(mx, my)
        pygame.draw.rect(surface, Theme.BTN_HOVER if hov else Theme.PANEL_LITE,
                         save_r, border_radius=5)
        pygame.draw.rect(surface, Theme.SUCCESS, save_r, 1, border_radius=5)
        save_label = "Update" if self._editing else "Create"
        draw_text(surface, save_label,
                  save_r.x + 20, save_r.y + 7, Theme.SUCCESS, font_sm)
        self._save_rect = save_r

        # Delete button (available for ANY tile when editing)
        if self._editing:
            del_r = pygame.Rect(save_r.right + 12, y, 80, 28)
            hov = del_r.collidepoint(mx, my)
            pygame.draw.rect(surface, Theme.BTN_HOVER if hov else Theme.PANEL_LITE,
                             del_r, border_radius=5)
            pygame.draw.rect(surface, Theme.DANGER, del_r, 1, border_radius=5)
            draw_text(surface, "Delete",
                      del_r.x + 16, del_r.y + 7, Theme.DANGER, font_sm)
            self._del_rect = del_r
        else:
            self._del_rect = pygame.Rect(0, 0, 0, 0)

        # Cancel
        cancel_r = pygame.Rect(rect.right - 90, y, 74, 28)
        hov = cancel_r.collidepoint(mx, my)
        pygame.draw.rect(surface, Theme.BTN_HOVER if hov else Theme.PANEL_LITE,
                         cancel_r, border_radius=5)
        pygame.draw.rect(surface, Theme.BORDER, cancel_r, 1, border_radius=5)
        draw_text(surface, "Cancel",
                  cancel_r.x + 14, cancel_r.y + 7, Theme.TEXT, font_sm)
        self._cancel_rect = cancel_r

    # ── events ───────────────────────────────────────────────────

    def handle_event(self, event) -> bool:
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                if getattr(self, '_type_open', False):
                    self._type_open = False
                    return True
                if self._cat_open:
                    self._cat_open = False
                    return True
                if self._cat_active:
                    self._cat_active = False
                    return True
                self.manager.close()
                return True

            # Category free-text input
            if self._cat_active:
                if event.key == pygame.K_BACKSPACE:
                    self._cat_text = self._cat_text[:-1]
                elif event.key == pygame.K_RETURN:
                    if self._cat_text.strip():
                        new_cat = self._cat_text.strip()
                        add_category(new_cat)
                        self._category = new_cat
                    self._cat_active = False
                    self._cat_text = ""
                elif event.key == pygame.K_TAB:
                    self._cat_active = False
                elif event.unicode and event.unicode.isprintable():
                    self._cat_text += event.unicode
                return True

            # Text input for name / texture / front / floor fields
            if self._name_active:
                if event.key == pygame.K_BACKSPACE:
                    self._name = self._name[:-1]
                elif event.key == pygame.K_RETURN:
                    self._name_active = False
                elif event.key == pygame.K_TAB:
                    self._name_active = False
                    self._tex_active = True
                elif event.unicode and event.unicode.isprintable():
                    self._name += event.unicode
                return True

            if self._tex_active:
                if event.key == pygame.K_BACKSPACE:
                    self._texture_key = self._texture_key[:-1]
                elif event.key == pygame.K_RETURN:
                    self._tex_active = False
                elif event.key == pygame.K_TAB:
                    self._tex_active = False
                    self._front_active = True
                elif event.unicode and event.unicode.isprintable():
                    self._texture_key += event.unicode
                return True

            if getattr(self, '_front_active', False):
                if event.key == pygame.K_BACKSPACE:
                    self._texture_front = self._texture_front[:-1]
                elif event.key == pygame.K_TAB:
                    self._front_active = False
                    self._back_active = True
                elif event.key in (pygame.K_RETURN,):
                    self._front_active = False
                elif event.unicode and event.unicode.isprintable():
                    self._texture_front += event.unicode
                return True

            if getattr(self, '_back_active', False):
                if event.key == pygame.K_BACKSPACE:
                    self._texture_back = self._texture_back[:-1]
                elif event.key in (pygame.K_RETURN, pygame.K_TAB):
                    self._back_active = False
                elif event.unicode and event.unicode.isprintable():
                    self._texture_back += event.unicode
                return True

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = event.pos
            self._error = ""

            # Type dropdown items
            if getattr(self, '_type_open', False):
                type_r = self._type_rect
                for ti, tt in enumerate(_TILE_TYPES):
                    ir = pygame.Rect(type_r.x, type_r.bottom + ti * 22,
                                     type_r.w, 22)
                    if ir.collidepoint(mx, my):
                        self._tile_type = tt
                        # Update height default when type changes
                        self._height_scale = _TYPE_DEFAULT_HEIGHT.get(tt, 1.0)
                        self._type_open = False
                        return True
                self._type_open = False
                return True

            # Category dropdown
            if self._cat_open:
                cat_items = list(TILE_CATEGORIES) + ["+ New Category..."]
                cat_r = self._cat_rect
                dy = cat_r.bottom
                for ci, cname in enumerate(cat_items):
                    cr = pygame.Rect(cat_r.x, dy + ci * 22, cat_r.w, 22)
                    if cr.collidepoint(mx, my):
                        if cname.startswith("+"):
                            self._cat_active = True
                            self._cat_text = ""
                        else:
                            self._category = cname
                        self._cat_open = False
                        return True
                self._cat_open = False
                return True

            # Type dropdown toggle
            if hasattr(self, '_type_rect') and self._type_rect.collidepoint(mx, my):
                self._type_open = not getattr(self, '_type_open', False)
                return True

            # Name field
            if hasattr(self, '_name_rect') and self._name_rect.collidepoint(mx, my):
                self._name_active = True
                self._tex_active = False
                self._cat_active = False
                return True
            else:
                self._name_active = False

            # Texture field
            if hasattr(self, '_tex_rect') and self._tex_rect.collidepoint(mx, my):
                self._tex_active = True
                self._name_active = False
                self._front_active = False
                self._back_active = False
                self._cat_active = False
                return True
            else:
                self._tex_active = False

            # Front / Back texture fields
            dir_clicked = False
            if hasattr(self, '_front_rect') and self._front_rect.collidepoint(mx, my):
                self._front_active = True
                self._back_active = False
                self._name_active = False
                self._tex_active = False
                self._cat_active = False
                dir_clicked = True
            elif hasattr(self, '_back_rect') and self._back_rect.collidepoint(mx, my):
                self._back_active = True
                self._front_active = False
                self._name_active = False
                self._tex_active = False
                self._cat_active = False
                dir_clicked = True
            if dir_clicked:
                return True
            else:
                self._front_active = False
                self._back_active = False

            # Colour sliders
            for bar_r, ci in getattr(self, '_color_slider_rects', []):
                if bar_r.collidepoint(mx, my):
                    frac = (mx - bar_r.x) / max(1, bar_r.w)
                    self._color[ci] = max(0, min(255, int(frac * 255)))
                    return True

            # Height scale slider
            if hasattr(self, '_hs_rect') and self._hs_rect.collidepoint(mx, my):
                frac = (mx - self._hs_rect.x) / max(1, self._hs_rect.w)
                self._height_scale = round(max(0.05, min(1.0, frac)), 2)
                return True

            # Extra flag checkboxes (TRANSPARENT, FARMLAND)
            for cb_r, fval in getattr(self, '_flag_rects', []):
                if cb_r.collidepoint(mx, my):
                    self._extra_flags ^= fval
                    return True

            # Category dropdown toggle
            if hasattr(self, '_cat_rect') and self._cat_rect.collidepoint(mx, my):
                if not self._cat_active:
                    self._cat_open = not self._cat_open
                return True

            # Import PNG button
            if hasattr(self, '_import_rect') and self._import_rect.collidepoint(mx, my):
                self._do_import()
                return True

            # Save / Create
            if hasattr(self, '_save_rect') and self._save_rect.collidepoint(mx, my):
                return self._do_save()

            # Delete
            if hasattr(self, '_del_rect') and self._del_rect.collidepoint(mx, my):
                if self._editing:
                    delete_tile(self._editing.id)
                    self.state.toast(f"Deleted tile: {self._editing.name}")
                    self.manager.close()
                return True

            # Cancel
            if hasattr(self, '_cancel_rect') and self._cancel_rect.collidepoint(mx, my):
                self.manager.close()
                return True

        # Dragging on colour sliders
        if event.type == pygame.MOUSEMOTION and pygame.mouse.get_pressed()[0]:
            mx, my = event.pos
            for bar_r, ci in getattr(self, '_color_slider_rects', []):
                if bar_r.collidepoint(mx, my):
                    frac = (mx - bar_r.x) / max(1, bar_r.w)
                    self._color[ci] = max(0, min(255, int(frac * 255)))
                    return True
            if hasattr(self, '_hs_rect') and self._hs_rect.collidepoint(mx, my):
                frac = (mx - self._hs_rect.x) / max(1, self._hs_rect.w)
                self._height_scale = round(max(0.05, min(1.0, frac)), 2)
                return True

        return True  # consume all events while modal is open

    def _do_import(self):
        """Open file dialog to import an image as the tile's texture."""
        tile_id = self._editing.id if self._editing else None
        key = self._texture_key.strip() or None
        try:
            from systems.textures import browse_and_import
            dest = browse_and_import(tile_id=tile_id, key=key)
            if dest:
                self.state.toast(f"Imported: {_os.path.basename(str(dest))}")
                # If no texture key was set, pre-fill from imported filename
                if not self._texture_key.strip():
                    self._texture_key = dest.stem
                # Invalidate atlas cache and rebuild preview
                if self._atlas and tile_id:
                    self._atlas.invalidate(tile_id)
                self._build_preview()
            # else: user cancelled — no-op
        except Exception as exc:
            self._error = f"Import failed: {exc}"

    def _do_save(self) -> bool:
        name = self._name.strip()
        if not name:
            self._error = "Name is required."
            return True
        color = (self._color[0], self._color[1], self._color[2])
        tex = self._texture_key.strip() or name.lower().replace(" ", "_")
        # Compute flags: base from type + extra toggles
        flags = _TYPE_FLAGS.get(self._tile_type, TF.NONE) | self._extra_flags

        # Build directional texture overrides
        tfr = self._texture_front.strip()
        tbk = self._texture_back.strip()

        if self._editing:
            # Update existing tile (works for ANY tile)
            update_tile(
                self._editing.id,
                name=name, color=color,
                type=self._tile_type, flags=flags,
                texture_key=tex,
                texture_front=tfr,
                texture_back=tbk,
                height_scale=self._height_scale,
                category=self._category,
            )
            # Invalidate atlas cache for this tile
            if self._atlas:
                self._atlas.invalidate(self._editing.id)
            self.state.toast(f"Updated tile: {name} (ID {self._editing.id})")
        else:
            td = register_tile(
                name=name, color=color,
                tile_type=self._tile_type, flags=flags,
                texture_key=tex,
                texture_front=tfr,
                texture_back=tbk,
                height_scale=self._height_scale,
                category=self._category,
            )
            self.state.toast(f"Created tile: {name} (ID {td.id})")

        self.manager.close()
        return True


