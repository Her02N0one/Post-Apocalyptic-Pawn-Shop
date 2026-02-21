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
        "portal",
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
    _TYPE_FLAGS, _TYPE_DEFAULT_HEIGHT, _next_tile_key,
    # Backward-compat aliases so old call-sites don't break
    register_custom_tile, delete_custom_tile, save_custom_tiles,
)

_TILE_TYPES = list(TileType)
_TILE_TYPE_LABELS = [t.value for t in _TILE_TYPES]
_KNOWN_SOUNDS = ["stone", "grass", "water", "sand", "wood",
                 "glass", "gravel", "metal", "cloth"]


class TileEditorModal(_BaseModal):
    """Full tile editor — create, edit, duplicate, or delete ANY tile.

    Scrollable body with all TileDef fields exposed.  Uses safe widgets
    (TextField, Slider, Dropdown) exclusively — no manual text handling.
    All pixel values go through ``Layout.s()`` for DPI scaling.
    """

    EXTRA_FLAG_OPTIONS = [
        ("Transparent", TF.TRANSPARENT, "See-through wall"),
        ("Farmland", TF.FARMLAND, "Tillable soil"),
        ("Thin Wall", TF.THIN_WALL, "Mid-cell fence/railing"),
        ("Tall Wall", TF.TALL_WALL, "Extends upward with alt texture"),
    ]

    @staticmethod
    def _key_filter(text: str) -> str:
        """Allow only filename-safe characters for texture keys."""
        return "".join(c for c in text
                       if c.isalnum() or c in ("_", "-", "."))

    # ── init ─────────────────────────────────────────────────────

    def __init__(self, manager: ModalManager,
                 edit_tile: TileDef | None = None,
                 atlas=None,
                 *,
                 duplicate: bool = False):
        super().__init__(manager)
        self._editing: TileDef | None = None if duplicate else edit_tile
        self._atlas = atlas
        self._error: str = ""
        self._tex_preview: pygame.Surface | None = None
        self._type_open: bool = False
        self._confirm_delete: bool = False

        src = edit_tile  # source tile (for edit OR duplicate)
        z = pygame.Rect(0, 0, 0, 0)  # repositioned in draw

        # Scroll state (body only — not header/buttons)
        self._scroll_y: float = 0.0
        self._content_h: int = 0  # set each frame in draw

        # ── Text fields ──────────────────────────────────────────
        self._name_field = TextField(
            z, self.ctx,
            value=(src.name + " (copy)" if duplicate else src.name) if src else "",
            placeholder="e.g. Mossy Stone", maxlen=48)

        self._tex_field = TextField(
            z, self.ctx,
            value=(src.texture_key or "") if src else "",
            placeholder="e.g. mossy_stone", maxlen=64,
            filter_fn=self._key_filter)

        self._front_field = TextField(
            z, self.ctx,
            value=src.texture_front if src else "",
            placeholder="(none)", maxlen=64,
            filter_fn=self._key_filter)

        self._back_field = TextField(
            z, self.ctx,
            value=src.texture_back if src else "",
            placeholder="(none)", maxlen=64,
            filter_fn=self._key_filter)

        # Per-face texture override fields (N/S/E/W)
        self._tex_n_field = TextField(
            z, self.ctx,
            value=src.tex_n if src else "",
            placeholder="(none)", maxlen=64,
            filter_fn=self._key_filter)
        self._tex_s_field = TextField(
            z, self.ctx,
            value=src.tex_s if src else "",
            placeholder="(none)", maxlen=64,
            filter_fn=self._key_filter)
        self._tex_e_field = TextField(
            z, self.ctx,
            value=src.tex_e if src else "",
            placeholder="(none)", maxlen=64,
            filter_fn=self._key_filter)
        self._tex_w_field = TextField(
            z, self.ctx,
            value=src.tex_w if src else "",
            placeholder="(none)", maxlen=64,
            filter_fn=self._key_filter)

        # Alt texture (tall wall extension texture)
        self._alt_tex_field = TextField(
            z, self.ctx,
            value=src.alt_texture if src else "",
            placeholder="(none)", maxlen=64,
            filter_fn=self._key_filter)

        self._cat_field = TextField(
            z, self.ctx, value="",
            placeholder="type category name...", maxlen=32)

        self.ctx.take_focus(self._name_field.uid)

        # ── Color sliders ────────────────────────────────────────
        col = list(src.color) if src else [120, 120, 120]
        _scolors = [(200, 80, 80), (80, 200, 80), (80, 80, 200)]
        self._color_sliders: list[Slider] = [
            Slider(z, value=float(col[i]), min_val=0, max_val=255,
                   step=1, bar_color=_scolors[i], fmt="{:.0f}")
            for i in range(3)]

        # ── Height slider ────────────────────────────────────────
        self._height_slider = Slider(
            z, value=src.height_scale if src else 1.0,
            min_val=0.05, max_val=1.0, step=0.01,
            bar_color=Theme.ACCENT, fmt="{:.2f}")

        # ── Tile type ────────────────────────────────────────────
        self._tile_type: TileType = src.type if src else TileType.FLOOR

        # ── Extra flags ──────────────────────────────────────────
        self._extra_flags: TF = TF.NONE
        if src:
            if src.transparent:
                self._extra_flags |= TF.TRANSPARENT
            if src.farmland:
                self._extra_flags |= TF.FARMLAND
            if src.thin_wall:
                self._extra_flags |= TF.THIN_WALL
            if src.tall_wall:
                self._extra_flags |= TF.TALL_WALL

        # ── Sound ────────────────────────────────────────────────
        self._sound: str = src.sound if src else "stone"
        self._sound_open: bool = False

        # ── Category ─────────────────────────────────────────────
        self._category = src.category if src else TC_CUSTOM
        self._cat_open: bool = False
        self._cat_active: bool = False

        # ── Hit-test rects (set each frame) ──────────────────────
        self._type_rect = z
        self._flag_rects: list[tuple[pygame.Rect, TF]] = []
        self._sound_rect = z
        self._cat_rect = z
        self._save_rect = z
        self._del_rect = z
        self._dup_rect = z
        self._cancel_rect = z
        self._import_rect = z
        self._import_front_rect = z
        self._import_back_rect = z

        self._build_preview()

    def _build_preview(self):
        if self._atlas and self._editing:
            try:
                self._tex_preview = self._atlas.get(self._editing.id).copy()
            except (KeyError, AttributeError, pygame.error):
                self._tex_preview = None
        else:
            self._tex_preview = None

    def _tex_exists(self, key: str) -> bool:
        if not key:
            return False
        p = _os.path.join(TILE_TEX_DIR, f"{key}.png")
        return _os.path.exists(p)

    def _predicted_id(self) -> str:
        """Show what the tile key *would* be for a new tile."""
        name = self._name_field.value.strip()
        if not name:
            return "\u2014"
        return _next_tile_key(name)

    def _name_collision(self) -> bool:
        """Return True if another tile already has this display name."""
        name = self._name_field.value.strip().lower()
        if not name:
            return False
        for tid, td in TILE_REGISTRY.items():
            if self._editing and tid == self._editing.id:
                continue
            if td.name.lower() == name:
                return True
        return False

    # ── draw ─────────────────────────────────────────────────────

    def draw(self, surface, font, font_sm, dt):
        super().draw(surface, font, font_sm, dt)
        s = _L.s
        rect = self._centered_rect(surface, 440, 680)
        title = (f"Edit Tile ({self._editing.id})" if self._editing
                 else "New Tile")
        self._draw_panel(surface, rect, title)

        pad = s(16)
        x0 = rect.x + pad
        rw = rect.w - pad * 2
        field_h = s(24)
        row = s(20)
        gap = s(6)
        mx, my = pygame.mouse.get_pos()

        # Fixed header zone (title already drawn by _draw_panel)
        header_bottom = rect.y + s(36)

        # Fixed button zone at bottom
        btn_zone_h = s(44)
        btn_top = rect.bottom - btn_zone_h

        # Scrollable body area between header and buttons
        body_r = pygame.Rect(rect.x, header_bottom, rect.w,
                             btn_top - header_bottom)

        # ── begin scroll clip ────────────────────────────────────
        surface.set_clip(body_r)
        y = body_r.y - int(self._scroll_y)

        # ── Texture preview ──────────────────────────────────────
        psz = s(64)
        prev_r = pygame.Rect(x0, y, psz, psz)
        pygame.draw.rect(surface, (30, 30, 35), prev_r)
        col = [int(sl.value) for sl in self._color_sliders]
        if self._tex_preview:
            try:
                preview = pygame.transform.scale(
                    self._tex_preview, (psz, psz))
                surface.blit(preview, prev_r.topleft)
            except (pygame.error, ValueError):
                pygame.draw.rect(surface, tuple(col),
                                 prev_r.inflate(-4, -4))
        else:
            pygame.draw.rect(surface, tuple(col), prev_r.inflate(-4, -4))
        pygame.draw.rect(surface, Theme.BORDER, prev_r, 1)

        # File info beside preview
        tx = x0 + psz + s(8)
        key = self._tex_field.value.strip() or "\u2014"
        exists = self._tex_exists(self._tex_field.value.strip())
        file_col = Theme.SUCCESS if exists else Theme.TEXT_DIM
        draw_text(surface, f"tex: {key}.png", tx, y + s(2),
                  file_col, font_sm)
        status = "\u2713 found" if exists else "not found (procedural)"
        draw_text(surface, status, tx, y + s(16), file_col, font_sm)

        # Import main-tex button
        imp_w = s(110)
        imp_r = pygame.Rect(tx, y + s(34), imp_w, field_h)
        ihov = imp_r.collidepoint(mx, my)
        pygame.draw.rect(surface,
                         Theme.BTN_HOVER if ihov else Theme.PANEL_LITE,
                         imp_r, border_radius=3)
        pygame.draw.rect(surface, Theme.ACCENT2, imp_r, 1,
                         border_radius=3)
        draw_text_centered(surface, "Import PNG", imp_r,
                           Theme.ACCENT2, font_sm)
        self._import_rect = imp_r
        y += psz + gap

        # ── Tile ID preview (new tiles) / ID display (existing) ──
        if self._editing:
            draw_text(surface, f"ID: {self._editing.id}",
                      x0, y + s(2), Theme.TEXT_DIM, font_sm)
        else:
            pid = self._predicted_id()
            draw_text(surface, f"ID will be: {pid}",
                      x0, y + s(2), Theme.TEXT_DIM, font_sm)
        y += s(16)

        # ── Name ────────────────────────────────────────────────
        draw_text(surface, "Name:", x0, y + s(2), Theme.TEXT_DIM, font_sm)
        y += s(16)
        self._name_field.rect = pygame.Rect(x0, y, rw, field_h)
        self._name_field.draw(surface, font_sm, dt)
        y += field_h
        # Name collision warning
        if self._name_collision():
            draw_text(surface, "\u26A0 A tile with this name exists",
                      x0, y + s(1), Theme.ACCENT2, font_sm)
            y += s(14)
        y += gap

        # ── Color + swatch ──────────────────────────────────────
        draw_text(surface, "Color:", x0, y + s(2), Theme.TEXT_DIM, font_sm)
        swatch_r = pygame.Rect(x0 + s(50), y, s(24), s(18))
        pygame.draw.rect(surface, tuple(col), swatch_r, border_radius=3)
        pygame.draw.rect(surface, Theme.BORDER, swatch_r, 1,
                         border_radius=3)
        y += row
        _clabels = ["R", "G", "B"]
        _clcolors = [(200, 80, 80), (80, 200, 80), (80, 80, 200)]
        bar_w = rw - s(60)
        for i in range(3):
            draw_text(surface, _clabels[i], x0, y + s(2),
                      _clcolors[i], font_sm)
            self._color_sliders[i].rect = pygame.Rect(
                x0 + s(16), y + s(2), bar_w, s(12))
            self._color_sliders[i].draw(surface, font_sm)
            y += s(18)

        # ── Tile Type ────────────────────────────────────────────
        y += s(4)
        draw_text(surface, "Type:", x0, y + s(2), Theme.TEXT_DIM, font_sm)
        y += s(16)
        type_r = pygame.Rect(x0, y, rw, field_h)
        hov = type_r.collidepoint(mx, my)
        pygame.draw.rect(surface,
                         Theme.BTN_HOVER if hov else Theme.FIELD_BG,
                         type_r, border_radius=3)
        pygame.draw.rect(surface,
                         Theme.ACCENT if self._type_open else Theme.BORDER,
                         type_r, 1, border_radius=3)
        draw_text(surface, self._tile_type.value, type_r.x + s(6),
                  type_r.y + s(4), Theme.TEXT, font_sm)
        draw_text(surface, "\u25BE", type_r.right - s(16),
                  type_r.y + s(4), Theme.TEXT_DIM, font_sm)
        self._type_rect = type_r
        y += field_h + gap

        # ── Extra flags ─────────────────────────────────────────
        self._flag_rects.clear()
        col_w = rw // 2
        for idx, (fname, fval, _fdesc) in enumerate(self.EXTRA_FLAG_OPTIONS):
            col_i = idx % 2
            if col_i == 0:
                row_y = y
            fx = x0 + col_i * col_w
            fy = row_y
            cb_sz = s(14)
            cb_r = pygame.Rect(fx, fy, cb_sz, cb_sz)
            checked = bool(self._extra_flags & fval)
            bg = Theme.ACCENT if checked else Theme.FIELD_BG
            pygame.draw.rect(surface, bg, cb_r, border_radius=2)
            pygame.draw.rect(surface, Theme.BORDER, cb_r, 1,
                             border_radius=2)
            if checked:
                draw_text(surface, "\u2713", cb_r.x + s(2), cb_r.y,
                          (255, 255, 255), font_sm)
            draw_text(surface, fname, fx + cb_sz + s(4), fy + s(1),
                      Theme.TEXT, font_sm)
            self._flag_rects.append((cb_r, fval))
            if col_i == 1:
                y += row
        if len(self.EXTRA_FLAG_OPTIONS) % 2 == 1:
            y += row
        y += s(4)

        # ── Sound ───────────────────────────────────────────────
        draw_text(surface, "Sound:", x0, y + s(2), Theme.TEXT_DIM, font_sm)
        snd_r = pygame.Rect(x0 + s(60), y, rw - s(60), field_h)
        shov = snd_r.collidepoint(mx, my)
        pygame.draw.rect(surface,
                         Theme.BTN_HOVER if shov else Theme.FIELD_BG,
                         snd_r, border_radius=3)
        pygame.draw.rect(surface,
                         Theme.ACCENT if self._sound_open else Theme.BORDER,
                         snd_r, 1, border_radius=3)
        draw_text(surface, self._sound, snd_r.x + s(6),
                  snd_r.y + s(4), Theme.TEXT, font_sm)
        draw_text(surface, "\u25BE", snd_r.right - s(14),
                  snd_r.y + s(4), Theme.TEXT_DIM, font_sm)
        self._sound_rect = snd_r
        y += field_h + gap

        # ── Texture key ─────────────────────────────────────────
        draw_text(surface, "Texture Key:", x0, y + s(2),
                  Theme.TEXT_DIM, font_sm)
        draw_text(surface, "(a-z 0-9 _ - .)", x0 + s(100), y + s(2),
                  (100, 100, 110), font_sm)
        y += s(16)
        self._tex_field.rect = pygame.Rect(x0, y, rw, field_h)
        self._tex_field.draw(surface, font_sm, dt)
        y += field_h + gap

        # ── Front texture ───────────────────────────────────────
        draw_text(surface, "Front Tex:", x0, y + s(2),
                  Theme.TEXT_DIM, font_sm)
        fval = self._front_field.value.strip()
        if fval:
            fcol = Theme.SUCCESS if self._tex_exists(fval) else Theme.DANGER
            fmark = "\u2713" if self._tex_exists(fval) else "\u2717"
            draw_text(surface, fmark, x0 + s(75), y + s(2), fcol, font_sm)
        # Small import button
        ib_w = s(18)
        ifr = pygame.Rect(x0 + rw - ib_w, y, ib_w, s(16))
        ihov_f = ifr.collidepoint(mx, my)
        pygame.draw.rect(surface,
                         Theme.BTN_HOVER if ihov_f else Theme.PANEL_LITE,
                         ifr, border_radius=2)
        draw_text(surface, "\U0001F4C2", ifr.x + s(2), ifr.y,
                  Theme.ACCENT2, font_sm)
        self._import_front_rect = ifr
        y += s(16)
        self._front_field.rect = pygame.Rect(x0, y, rw, field_h)
        self._front_field.draw(surface, font_sm, dt)
        y += field_h + gap

        # ── Back texture ────────────────────────────────────────
        draw_text(surface, "Back Tex:", x0, y + s(2),
                  Theme.TEXT_DIM, font_sm)
        bval = self._back_field.value.strip()
        if bval:
            bcol = Theme.SUCCESS if self._tex_exists(bval) else Theme.DANGER
            bmark = "\u2713" if self._tex_exists(bval) else "\u2717"
            draw_text(surface, bmark, x0 + s(75), y + s(2), bcol, font_sm)
        ibr = pygame.Rect(x0 + rw - ib_w, y, ib_w, s(16))
        ibhov = ibr.collidepoint(mx, my)
        pygame.draw.rect(surface,
                         Theme.BTN_HOVER if ibhov else Theme.PANEL_LITE,
                         ibr, border_radius=2)
        draw_text(surface, "\U0001F4C2", ibr.x + s(2), ibr.y,
                  Theme.ACCENT2, font_sm)
        self._import_back_rect = ibr
        y += s(16)
        self._back_field.rect = pygame.Rect(x0, y, rw, field_h)
        self._back_field.draw(surface, font_sm, dt)
        y += field_h + gap

        # ── Per-face texture overrides (N/S/E/W) ───────────────
        draw_text(surface, "Per-Face Textures:", x0, y + s(2),
                  Theme.TEXT_DIM, font_sm)
        draw_text(surface, "(override texture per compass face)",
                  x0 + s(130), y + s(2), (90, 90, 100), font_sm)
        y += s(16)

        half_rw = (rw - s(8)) // 2
        _face_fields = [
            ("N:", self._tex_n_field),
            ("S:", self._tex_s_field),
            ("E:", self._tex_e_field),
            ("W:", self._tex_w_field),
        ]
        for fi, (flabel, ffield) in enumerate(_face_fields):
            col_i = fi % 2
            if col_i == 0:
                _fy = y
            fx = x0 + col_i * (half_rw + s(8))
            draw_text(surface, flabel, fx, _fy + s(4),
                      Theme.TEXT_DIM, font_sm)
            ffield.rect = pygame.Rect(
                fx + s(18), _fy, half_rw - s(18), field_h)
            ffield.draw(surface, font_sm, dt)
            if col_i == 1:
                y += field_h + s(4)
        if len(_face_fields) % 2 == 1:
            y += field_h + s(4)
        y += gap

        # ── Alt texture (tall wall extension) ───────────────────
        draw_text(surface, "Alt Tex:", x0, y + s(2),
                  Theme.TEXT_DIM, font_sm)
        draw_text(surface, "(tall wall upper texture)",
                  x0 + s(65), y + s(2), (90, 90, 100), font_sm)
        y += s(16)
        self._alt_tex_field.rect = pygame.Rect(x0, y, rw, field_h)
        self._alt_tex_field.draw(surface, font_sm, dt)
        y += field_h + gap

        # ── Height scale ────────────────────────────────────────
        draw_text(surface, "Height:", x0, y + s(2),
                  Theme.TEXT_DIM, font_sm)
        self._height_slider.rect = pygame.Rect(
            x0 + s(60), y + s(2), rw - s(100), s(12))
        self._height_slider.draw(surface, font_sm)
        y += row + gap

        # ── Category ────────────────────────────────────────────
        draw_text(surface, "Category:", x0, y + s(2),
                  Theme.TEXT_DIM, font_sm)
        cat_r = pygame.Rect(x0 + s(80), y, rw - s(80), field_h)
        if self._cat_active:
            self._cat_field.rect = cat_r
            self._cat_field.draw(surface, font_sm, dt)
        else:
            chov = cat_r.collidepoint(mx, my)
            pygame.draw.rect(surface,
                             Theme.BTN_HOVER if chov else Theme.FIELD_BG,
                             cat_r, border_radius=3)
            pygame.draw.rect(surface,
                             Theme.ACCENT if self._cat_open
                             else Theme.BORDER,
                             cat_r, 1, border_radius=3)
            draw_text(surface, self._category, cat_r.x + s(6),
                      cat_r.y + s(4), Theme.TEXT, font_sm)
            draw_text(surface, "\u25BE", cat_r.right - s(14),
                      cat_r.y + s(4), Theme.TEXT_DIM, font_sm)
        self._cat_rect = cat_r
        y += field_h + gap

        # ── Error message ───────────────────────────────────────
        if self._error:
            draw_text(surface, self._error, x0, y, Theme.DANGER, font_sm)
            y += s(16)

        # Record content height and body height for scroll
        self._content_h = int((y + self._scroll_y) - body_r.y) + s(8)
        self._body_h = body_r.h

        # End body clip
        surface.set_clip(None)

        # ── Scrollbar ───────────────────────────────────────────
        max_scroll = max(0, self._content_h - body_r.h)
        if max_scroll > 0:
            thumb_h = max(s(20), int(body_r.h * body_r.h /
                                     max(1, self._content_h)))
            track_range = body_r.h - thumb_h
            if max_scroll > 0:
                thumb_y = body_r.y + int(track_range *
                                         self._scroll_y / max_scroll)
            else:
                thumb_y = body_r.y
            sb_x = rect.right - s(10)
            pygame.draw.rect(surface, Theme.SCROLLBAR,
                             (sb_x, body_r.y, s(6), body_r.h),
                             border_radius=3)
            pygame.draw.rect(surface, Theme.SCROLLTHUMB,
                             (sb_x, thumb_y, s(6), thumb_h),
                             border_radius=3)

        # ── Delete confirmation overlay ─────────────────────────
        if self._confirm_delete:
            ov = pygame.Surface((rect.w, btn_zone_h + s(40)),
                                pygame.SRCALPHA)
            ov.fill((30, 30, 34, 230))
            surface.blit(ov, (rect.x, btn_top - s(40)))
            draw_text(surface, "Delete this tile permanently?",
                      x0, btn_top - s(32), Theme.DANGER, font_sm)
            yes_r = pygame.Rect(x0, btn_top - s(10), s(80), s(26))
            no_r = pygame.Rect(x0 + s(100), btn_top - s(10),
                               s(80), s(26))
            for r, label, c in [(yes_r, "Yes, Delete", Theme.DANGER),
                                (no_r, "Cancel", Theme.TEXT)]:
                rhov = r.collidepoint(mx, my)
                pygame.draw.rect(surface,
                                 Theme.BTN_HOVER if rhov
                                 else Theme.PANEL_LITE,
                                 r, border_radius=4)
                pygame.draw.rect(surface, c, r, 1, border_radius=4)
                draw_text_centered(surface, label, r, c, font_sm)
            self._del_yes_rect = yes_r
            self._del_no_rect = no_r
            return  # skip normal button rendering

        # ── Action buttons (fixed at bottom) ─────────────────────
        btn_y = btn_top + s(8)
        btn_h = s(28)

        # Save / Create
        save_r = pygame.Rect(x0, btn_y, s(100), btn_h)
        hov = save_r.collidepoint(mx, my)
        pygame.draw.rect(surface,
                         Theme.BTN_HOVER if hov else Theme.PANEL_LITE,
                         save_r, border_radius=5)
        pygame.draw.rect(surface, Theme.SUCCESS, save_r, 1,
                         border_radius=5)
        save_label = "Update" if self._editing else "Create"
        draw_text_centered(surface, save_label, save_r,
                           Theme.SUCCESS, font_sm)
        self._save_rect = save_r

        bx = save_r.right + s(8)

        # Duplicate (only when editing)
        if self._editing:
            dup_r = pygame.Rect(bx, btn_y, s(80), btn_h)
            hov = dup_r.collidepoint(mx, my)
            pygame.draw.rect(surface,
                             Theme.BTN_HOVER if hov else Theme.PANEL_LITE,
                             dup_r, border_radius=5)
            pygame.draw.rect(surface, Theme.ACCENT, dup_r, 1,
                             border_radius=5)
            draw_text_centered(surface, "Duplicate", dup_r,
                               Theme.ACCENT, font_sm)
            self._dup_rect = dup_r
            bx = dup_r.right + s(8)
        else:
            self._dup_rect = pygame.Rect(0, 0, 0, 0)

        # Delete (only when editing)
        if self._editing:
            del_r = pygame.Rect(bx, btn_y, s(70), btn_h)
            hov = del_r.collidepoint(mx, my)
            pygame.draw.rect(surface,
                             Theme.BTN_HOVER if hov else Theme.PANEL_LITE,
                             del_r, border_radius=5)
            pygame.draw.rect(surface, Theme.DANGER, del_r, 1,
                             border_radius=5)
            draw_text_centered(surface, "Delete", del_r,
                               Theme.DANGER, font_sm)
            self._del_rect = del_r
        else:
            self._del_rect = pygame.Rect(0, 0, 0, 0)

        # Cancel
        cancel_r = pygame.Rect(rect.right - s(80), btn_y, s(64), btn_h)
        hov = cancel_r.collidepoint(mx, my)
        pygame.draw.rect(surface,
                         Theme.BTN_HOVER if hov else Theme.PANEL_LITE,
                         cancel_r, border_radius=5)
        pygame.draw.rect(surface, Theme.BORDER, cancel_r, 1,
                         border_radius=5)
        draw_text_centered(surface, "Cancel", cancel_r,
                           Theme.TEXT, font_sm)
        self._cancel_rect = cancel_r

        # ── Deferred dropdown overlays (rendered AFTER scroll clip) ──
        # These float above all body content and action buttons so
        # they are never clipped by the scroll region.
        _dbr = _L.s(4)

        if self._type_open:
            n = len(_TILE_TYPES)
            dr = pygame.Rect(self._type_rect.x,
                             self._type_rect.bottom,
                             self._type_rect.w, n * field_h)
            pygame.draw.rect(surface, Theme.PANEL, dr,
                             border_radius=_dbr)
            pygame.draw.rect(surface, Theme.BORDER, dr, 1,
                             border_radius=_dbr)
            for ti, tt in enumerate(_TILE_TYPES):
                ir = pygame.Rect(dr.x + 2, dr.y + ti * field_h,
                                 dr.w - 4, field_h)
                ihov = ir.collidepoint(mx, my)
                if ihov:
                    pygame.draw.rect(surface, Theme.HIGHLIGHT,
                                     ir, border_radius=2)
                elif tt == self._tile_type:
                    pygame.draw.rect(surface, Theme.SELECTED,
                                     ir, border_radius=2)
                tc = (Theme.ACCENT if tt == self._tile_type
                      else Theme.TEXT)
                draw_text(surface, tt.value, ir.x + s(6),
                          ir.y + s(4), tc, font_sm)

        if self._sound_open:
            n = len(_KNOWN_SOUNDS)
            dr = pygame.Rect(self._sound_rect.x,
                             self._sound_rect.bottom,
                             self._sound_rect.w, n * field_h)
            pygame.draw.rect(surface, Theme.PANEL, dr,
                             border_radius=_dbr)
            pygame.draw.rect(surface, Theme.BORDER, dr, 1,
                             border_radius=_dbr)
            for si, sname in enumerate(_KNOWN_SOUNDS):
                ir = pygame.Rect(dr.x + 2, dr.y + si * field_h,
                                 dr.w - 4, field_h)
                ihov = ir.collidepoint(mx, my)
                if ihov:
                    pygame.draw.rect(surface, Theme.HIGHLIGHT,
                                     ir, border_radius=2)
                elif sname == self._sound:
                    pygame.draw.rect(surface, Theme.SELECTED,
                                     ir, border_radius=2)
                tc = (Theme.ACCENT if sname == self._sound
                      else Theme.TEXT)
                draw_text(surface, sname, ir.x + s(6),
                          ir.y + s(4), tc, font_sm)

        if self._cat_open:
            cat_items = list(TILE_CATEGORIES) + ["+ New Category..."]
            n = len(cat_items)
            dr = pygame.Rect(self._cat_rect.x,
                             self._cat_rect.bottom,
                             self._cat_rect.w, n * field_h)
            pygame.draw.rect(surface, Theme.PANEL, dr,
                             border_radius=_dbr)
            pygame.draw.rect(surface, Theme.BORDER, dr, 1,
                             border_radius=_dbr)
            for ci, cname in enumerate(cat_items):
                ir = pygame.Rect(dr.x + 2, dr.y + ci * field_h,
                                 dr.w - 4, field_h)
                ihov = ir.collidepoint(mx, my)
                if ihov:
                    pygame.draw.rect(surface, Theme.HIGHLIGHT,
                                     ir, border_radius=2)
                elif cname == self._category:
                    pygame.draw.rect(surface, Theme.SELECTED,
                                     ir, border_radius=2)
                if cname.startswith("+"):
                    ct = Theme.ACCENT2
                else:
                    ct = (Theme.ACCENT if cname == self._category
                          else Theme.TEXT)
                draw_text(surface, cname, ir.x + s(6),
                          ir.y + s(4), ct, font_sm)

    # ── events ───────────────────────────────────────────────────

    def _all_fields(self) -> list[TextField]:
        return [self._name_field, self._tex_field,
                self._front_field, self._back_field,
                self._tex_n_field, self._tex_s_field,
                self._tex_e_field, self._tex_w_field,
                self._alt_tex_field]

    def handle_event(self, event) -> bool:
        # ── Delete confirmation mode ─────────────────────────────
        if self._confirm_delete:
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    self._confirm_delete = False
                    return True
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mx, my = event.pos
                if (hasattr(self, '_del_yes_rect')
                        and self._del_yes_rect.collidepoint(mx, my)):
                    delete_tile(self._editing.id)
                    self.state.toast(
                        f"Deleted tile: {self._editing.name}")
                    self.manager.close()
                    return True
                if (hasattr(self, '_del_no_rect')
                        and self._del_no_rect.collidepoint(mx, my)):
                    self._confirm_delete = False
                    return True
            return True  # consume

        # ── Scroll ───────────────────────────────────────────────
        if event.type == pygame.MOUSEWHEEL:
            body_h = getattr(self, '_body_h', 400)
            self._scroll_y = max(0.0, min(
                self._scroll_y - event.y * 30,
                max(0, self._content_h - body_h)))
            return True

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                if self._type_open:
                    self._type_open = False
                    return True
                if self._sound_open:
                    self._sound_open = False
                    return True
                if self._cat_open:
                    self._cat_open = False
                    return True
                if self._cat_active:
                    self._cat_active = False
                    return True
                self.manager.close()
                return True

            # Tab order
            if event.key == pygame.K_TAB:
                fields = self._all_fields()
                for i, f in enumerate(fields):
                    if f.focused:
                        self.ctx.release_focus(f.uid)
                        nxt = fields[(i + 1) % len(fields)]
                        self.ctx.take_focus(nxt.uid)
                        return True

            # Category free-text
            if self._cat_active:
                if event.key == pygame.K_RETURN:
                    val = self._cat_field.value.strip()
                    if val:
                        add_category(val)
                        self._category = val
                    self._cat_active = False
                    return True
                self._cat_field.handle_event(event)
                return True

        # Text fields
        for field in self._all_fields():
            if field.handle_event(event):
                return True

        # Category free-text events
        if self._cat_active:
            self._cat_field.handle_event(event)
            return True

        # Sliders
        for sl in self._color_sliders:
            if sl.handle_event(event):
                return True
        if self._height_slider.handle_event(event):
            return True

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = event.pos
            self._error = ""

            # Type dropdown items
            if self._type_open:
                for ti, tt in enumerate(_TILE_TYPES):
                    ir = pygame.Rect(
                        self._type_rect.x,
                        self._type_rect.bottom + ti * _L.s(24),
                        self._type_rect.w, _L.s(24))
                    if ir.collidepoint(mx, my):
                        self._tile_type = tt
                        self._height_slider.value = \
                            _TYPE_DEFAULT_HEIGHT.get(tt, 1.0)
                        self._type_open = False
                        return True
                self._type_open = False
                return True

            # Sound dropdown items
            if self._sound_open:
                for si, sname in enumerate(_KNOWN_SOUNDS):
                    sr = pygame.Rect(
                        self._sound_rect.x,
                        self._sound_rect.bottom + si * _L.s(24),
                        self._sound_rect.w, _L.s(24))
                    if sr.collidepoint(mx, my):
                        self._sound = sname
                        self._sound_open = False
                        return True
                self._sound_open = False
                return True

            # Category dropdown
            if self._cat_open:
                cat_items = list(TILE_CATEGORIES) + ["+ New Category..."]
                fh = _L.s(24)
                for ci, cname in enumerate(cat_items):
                    cr = pygame.Rect(self._cat_rect.x,
                                     self._cat_rect.bottom + ci * fh,
                                     self._cat_rect.w, fh)
                    if cr.collidepoint(mx, my):
                        if cname.startswith("+"):
                            self._cat_active = True
                            self._cat_field.value = ""
                            self._cat_field._cursor_pos = 0
                            self.ctx.take_focus(self._cat_field.uid)
                        else:
                            self._category = cname
                        self._cat_open = False
                        return True
                self._cat_open = False
                return True

            # Type toggle
            if self._type_rect.collidepoint(mx, my):
                self._type_open = not self._type_open
                self._sound_open = False
                self._cat_open = False
                return True

            # Sound toggle
            if self._sound_rect.collidepoint(mx, my):
                self._sound_open = not self._sound_open
                self._type_open = False
                self._cat_open = False
                return True

            # Flag checkboxes
            for cb_r, fval in self._flag_rects:
                if cb_r.collidepoint(mx, my):
                    self._extra_flags ^= fval
                    return True

            # Category toggle
            if self._cat_rect.collidepoint(mx, my) and not self._cat_active:
                self._cat_open = not self._cat_open
                self._type_open = False
                self._sound_open = False
                return True

            # Import main texture
            if self._import_rect.collidepoint(mx, my):
                self._do_import(target="main")
                return True

            # Import front texture
            if self._import_front_rect.collidepoint(mx, my):
                self._do_import(target="front")
                return True

            # Import back texture
            if self._import_back_rect.collidepoint(mx, my):
                self._do_import(target="back")
                return True

            # Save / Create
            if self._save_rect.collidepoint(mx, my):
                return self._do_save()

            # Duplicate
            if (self._dup_rect.w > 0
                    and self._dup_rect.collidepoint(mx, my)):
                self._do_duplicate()
                return True

            # Delete (with confirmation)
            if (self._del_rect.w > 0
                    and self._del_rect.collidepoint(mx, my)
                    and self._editing):
                self._confirm_delete = True
                return True

            # Cancel
            if self._cancel_rect.collidepoint(mx, my):
                self.manager.close()
                return True

        return True  # consume all events while modal is open

    # ── actions ──────────────────────────────────────────────────

    def _do_import(self, *, target: str = "main"):
        """Import a PNG texture for the given target field."""
        tile_id = self._editing.id if self._editing else None
        if target == "front":
            key = self._front_field.value.strip() or None
        elif target == "back":
            key = self._back_field.value.strip() or None
        else:
            key = self._tex_field.value.strip() or None
        try:
            from systems.textures import browse_and_import
            dest = browse_and_import(tile_id=tile_id, key=key)
            if dest:
                self.state.toast(
                    f"Imported: {_os.path.basename(str(dest))}")
                if target == "front":
                    if not self._front_field.value.strip():
                        self._front_field.value = dest.stem
                        self._front_field._cursor_pos = len(
                            self._front_field.value)
                elif target == "back":
                    if not self._back_field.value.strip():
                        self._back_field.value = dest.stem
                        self._back_field._cursor_pos = len(
                            self._back_field.value)
                else:
                    if not self._tex_field.value.strip():
                        self._tex_field.value = dest.stem
                        self._tex_field._cursor_pos = len(
                            self._tex_field.value)
                if self._atlas and tile_id:
                    self._atlas.invalidate(tile_id)
                self._build_preview()
        except Exception as exc:
            self._error = f"Import failed: {exc}"

    def _do_duplicate(self):
        """Re-open the modal in duplicate mode from the current tile."""
        if not self._editing:
            return
        src = self._editing
        dup_modal = TileEditorModal(
            self.manager, edit_tile=src, atlas=self._atlas,
            duplicate=True)
        # Copy current form state that may differ from saved
        dup_modal._name_field.value = self._name_field.value.strip()
        if not dup_modal._name_field.value.endswith(" (copy)"):
            dup_modal._name_field.value += " (copy)"
        dup_modal._name_field._cursor_pos = len(
            dup_modal._name_field.value)
        for i in range(3):
            dup_modal._color_sliders[i].value = \
                self._color_sliders[i].value
        dup_modal._tile_type = self._tile_type
        dup_modal._extra_flags = self._extra_flags
        dup_modal._sound = self._sound
        dup_modal._height_slider.value = self._height_slider.value
        dup_modal._tex_field.value = self._tex_field.value
        dup_modal._front_field.value = self._front_field.value
        dup_modal._back_field.value = self._back_field.value
        dup_modal._tex_n_field.value = self._tex_n_field.value
        dup_modal._tex_s_field.value = self._tex_s_field.value
        dup_modal._tex_e_field.value = self._tex_e_field.value
        dup_modal._tex_w_field.value = self._tex_w_field.value
        dup_modal._alt_tex_field.value = self._alt_tex_field.value
        dup_modal._category = self._category
        self.manager.open(dup_modal)

    def _do_save(self) -> bool:
        name = self._name_field.value.strip()
        if not name:
            self._error = "Name is required."
            return True
        if any(c in name for c in ("/", "\\", "\x00")):
            self._error = "Name contains invalid characters."
            return True

        color = tuple(int(sl.value) for sl in self._color_sliders)
        tex = (self._tex_field.value.strip()
               or name.lower().replace(" ", "_"))
        flags = (_TYPE_FLAGS.get(self._tile_type, TF.NONE)
                 | self._extra_flags)
        tfr = self._front_field.value.strip()
        tbk = self._back_field.value.strip()
        t_n = self._tex_n_field.value.strip()
        t_s = self._tex_s_field.value.strip()
        t_e = self._tex_e_field.value.strip()
        t_w = self._tex_w_field.value.strip()
        alt_tex = self._alt_tex_field.value.strip()
        height = self._height_slider.value
        sound = self._sound

        if self._editing:
            update_tile(
                self._editing.id,
                name=name, color=color,
                type=self._tile_type, flags=flags,
                texture_key=tex,
                texture_front=tfr,
                texture_back=tbk,
                tex_n=t_n, tex_s=t_s, tex_e=t_e, tex_w=t_w,
                alt_texture=alt_tex,
                height_scale=height,
                category=self._category,
                sound=sound,
            )
            if self._atlas:
                self._atlas.invalidate(self._editing.id)
            self.state.toast(
                f"Updated tile: {name} ({self._editing.id})")
        else:
            td = register_tile(
                name=name, color=color,
                tile_type=self._tile_type, flags=flags,
                texture_key=tex,
                texture_front=tfr,
                texture_back=tbk,
                tex_n=t_n, tex_s=t_s, tex_e=t_e, tex_w=t_w,
                alt_texture=alt_tex,
                height_scale=height,
                category=self._category,
                sound=sound,
            )
            self.state.toast(f"Created tile: {name} ({td.id})")

        self.manager.close()
        return True


