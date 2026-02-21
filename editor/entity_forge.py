"""editor/entity_forge.py — Entity Forge modal: no-code asset creation.

Provides a full-screen overlay where designers create, edit, and
delete **ForgeArchetype** entries (tiles, boxes, billboards) without
touching any code.  All data is persisted to ``data/custom_entities.toml``
via ``ForgeRegistry``.

Three archetype *kinds* have dedicated property sections:

* **tile** — wall/floor texture with floor_z / ceiling_z
* **box** — 3D box (width, depth, height) with face textures
* **billboard** — 2D sprite that faces the camera

Every archetype also has common fields: ``display_name``, ``dev_notes``,
``tags``.
"""

from __future__ import annotations

from typing import Any

import pygame

from core.fonts import get_font
from editor.ui import (
    Theme, UIContext, Button, TextField, NumberField, Dropdown,
    Checkbox, ColorField, ScrollPanel,
    draw_text, draw_text_centered,
)
from editor.forge_registry import ForgeArchetype, ForgeRegistry
from editor.state import EditorState
from editor.layout import Layout


# ═════════════════════════════════════════════════════════════════════
#  Constants
# ═════════════════════════════════════════════════════════════════════

_KIND_OPTIONS = ["tile", "box", "billboard"]
_KIND_LABELS = {"tile": "Tile (wall/floor)", "box": "Box (3D prism)",
                "billboard": "Billboard (2D sprite)"}
_TAG_PRESETS = ["furniture", "container", "decoration", "npc",
                "hostile", "loot_socket", "wall", "floor", "door"]


# ═════════════════════════════════════════════════════════════════════
#  Entity Forge modal
# ═════════════════════════════════════════════════════════════════════

class EntityForgeModal:
    """Full-screen Entity Forge overlay.

    Lifecycle::

        forge = EntityForgeModal(ctx)
        forge.open()
        # each frame:
        forge.handle_event(event)
        forge.draw(surface, font, font_sm, dt)
    """

    @staticmethod
    def _s_list_w():  return Layout.s(220)
    @staticmethod
    def _s_field_h(): return Layout.s(28)
    @staticmethod
    def _s_row_h():   return Layout.s(34)
    @staticmethod
    def _s_pad():     return Layout.s(10)

    def __init__(self, ctx: UIContext, state: EditorState):
        self.ctx = ctx
        self.state = state
        self.registry = ForgeRegistry.instance()
        self.active = False

        # ── List state ──
        self._list_scroll = 0
        self._selected_id: str | None = None
        self._filter_kind: str = ""     # "" = all

        # ── Edit form widgets (created lazily on selection) ──
        self._form_widgets: dict[str, Any] = {}
        self._form_scroll = 0
        self._dirty = False

    # ── Open / close ────────────────────────────────────────────

    def open(self):
        self.active = True
        self.registry.reload()
        ids = self.registry.ids()
        self._selected_id = ids[0] if ids else None
        self._rebuild_form()
        self.state.toast("Entity Forge opened")

    def close(self):
        if self._dirty:
            self._apply_form()
            self.registry.save()
            self.state.toast("Forge: saved")
        self.active = False
        self.ctx.release_focus()

    @property
    def selected_id(self) -> str | None:
        return self._selected_id

    # ── Form rebuild ────────────────────────────────────────────

    def _rebuild_form(self):
        """Create widgets that match the currently selected archetype."""
        self._form_widgets.clear()
        self._form_scroll = 0
        arch = self._current()
        if arch is None:
            return

        W = 260  # field width

        self._form_widgets["id_field"] = TextField(
            pygame.Rect(0, 0, W, self._s_field_h()), self.ctx, value=arch.id)
        self._form_widgets["name_field"] = TextField(
            pygame.Rect(0, 0, W, self._s_field_h()), self.ctx,
            value=arch.display_name)
        self._form_widgets["notes_field"] = TextField(
            pygame.Rect(0, 0, W, self._s_field_h()), self.ctx,
            value=arch.dev_notes)
        self._form_widgets["tags_field"] = TextField(
            pygame.Rect(0, 0, W, self._s_field_h()), self.ctx,
            value=", ".join(arch.tags))

        # Kind dropdown
        kind_idx = _KIND_OPTIONS.index(arch.kind) if arch.kind in _KIND_OPTIONS else 0
        self._form_widgets["kind_dd"] = Dropdown(
            pygame.Rect(0, 0, W, self._s_field_h()),
            options=_KIND_OPTIONS, selected=kind_idx)

        # Solid checkbox
        self._form_widgets["solid_cb"] = Checkbox(
            pygame.Rect(0, 0, 20, 20), "Solid", checked=arch.solid)
        self._form_widgets["transparent_cb"] = Checkbox(
            pygame.Rect(0, 0, 20, 20), "Transparent", checked=arch.transparent)

        # ── Tile props ──
        self._form_widgets["texture_key"] = TextField(
            pygame.Rect(0, 0, W, self._s_field_h()), self.ctx,
            value=arch.texture_key)
        self._form_widgets["floor_z"] = NumberField(
            pygame.Rect(0, 0, 80, self._s_field_h()), self.ctx,
            value=arch.floor_z, min_val=0.0, max_val=10.0, step=0.05)
        self._form_widgets["ceiling_z"] = NumberField(
            pygame.Rect(0, 0, 80, self._s_field_h()), self.ctx,
            value=arch.ceiling_z, min_val=0.0, max_val=10.0, step=0.05)

        # ── Box props ──
        self._form_widgets["box_w"] = NumberField(
            pygame.Rect(0, 0, 80, self._s_field_h()), self.ctx,
            value=arch.width, min_val=0.05, max_val=4.0, step=0.05)
        self._form_widgets["box_d"] = NumberField(
            pygame.Rect(0, 0, 80, self._s_field_h()), self.ctx,
            value=arch.depth, min_val=0.05, max_val=4.0, step=0.05)
        self._form_widgets["box_h"] = NumberField(
            pygame.Rect(0, 0, 80, self._s_field_h()), self.ctx,
            value=arch.height, min_val=0.05, max_val=4.0, step=0.05)
        self._form_widgets["z_offset"] = NumberField(
            pygame.Rect(0, 0, 80, self._s_field_h()), self.ctx,
            value=arch.z_offset, min_val=0.0, max_val=4.0, step=0.05)
        self._form_widgets["color_field"] = ColorField(
            pygame.Rect(0, 0, W, self._s_field_h()), self.ctx,
            color=arch.color)

        # ── Billboard props ──
        self._form_widgets["sprite_char"] = TextField(
            pygame.Rect(0, 0, 60, self._s_field_h()), self.ctx,
            value=arch.sprite_char)
        self._form_widgets["sprite_color"] = ColorField(
            pygame.Rect(0, 0, W, self._s_field_h()), self.ctx,
            color=arch.sprite_color)
        self._form_widgets["scale"] = NumberField(
            pygame.Rect(0, 0, 80, self._s_field_h()), self.ctx,
            value=arch.scale, min_val=0.1, max_val=4.0, step=0.1)
        self._form_widgets["directional_cb"] = Checkbox(
            pygame.Rect(0, 0, 20, 20), "Directional", checked=arch.directional)
        self._form_widgets["sprite_sheet"] = TextField(
            pygame.Rect(0, 0, W, self._s_field_h()), self.ctx,
            value=arch.sprite_sheet)

    def _current(self) -> ForgeArchetype | None:
        if self._selected_id:
            return self.registry.get(self._selected_id)
        return None

    # ── Apply form → archetype ──────────────────────────────────

    def _apply_form(self):
        """Read widget values and update the archetype in the registry."""
        arch = self._current()
        if arch is None:
            return

        w = self._form_widgets
        new_id = w["id_field"].value.strip().replace(" ", "_").lower()
        if not new_id:
            new_id = arch.id

        kind_dd: Dropdown = w["kind_dd"]
        kind = _KIND_OPTIONS[kind_dd.selected]

        tags_raw = w["tags_field"].value
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()]

        updated = ForgeArchetype(
            id=new_id,
            kind=kind,
            display_name=w["name_field"].value.strip(),
            dev_notes=w["notes_field"].value.strip(),
            tags=tags,
            # tile
            texture_key=w["texture_key"].value.strip(),
            floor_z=w["floor_z"].value,
            ceiling_z=w["ceiling_z"].value,
            solid=w["solid_cb"].checked,
            transparent=w["transparent_cb"].checked,
            # box
            width=w["box_w"].value,
            depth=w["box_d"].value,
            height=w["box_h"].value,
            z_offset=w["z_offset"].value,
            color=w["color_field"].color,
            # billboard
            sprite_char=w["sprite_char"].value.strip() or "?",
            sprite_color=w["sprite_color"].color,
            directional=w["directional_cb"].checked,
            sprite_sheet=w["sprite_sheet"].value.strip(),
            scale=w["scale"].value,
        )

        # If ID changed, remove old entry
        if new_id != arch.id:
            self.registry.delete(arch.id)

        self.registry.upsert(updated)
        self._selected_id = new_id
        self._dirty = True

    # ── New / Delete ────────────────────────────────────────────

    def _new_archetype(self):
        """Create a blank archetype with a unique ID."""
        base = "new_entity"
        idx = 0
        while self.registry.get(f"{base}_{idx}"):
            idx += 1
        aid = f"{base}_{idx}"
        arch = ForgeArchetype(id=aid, kind="box",
                              display_name=f"New Entity {idx}")
        self.registry.upsert(arch)
        self._selected_id = aid
        self._rebuild_form()
        self._dirty = True

    def _delete_current(self):
        """Delete the selected archetype."""
        if self._selected_id:
            self.registry.delete(self._selected_id)
            ids = self.registry.ids()
            self._selected_id = ids[0] if ids else None
            self._rebuild_form()
            self._dirty = True

    def _duplicate_current(self):
        """Clone the selected archetype with a new ID."""
        arch = self._current()
        if arch is None:
            return
        idx = 0
        while self.registry.get(f"{arch.id}_copy{idx}"):
            idx += 1
        from dataclasses import asdict
        d = asdict(arch)
        d["id"] = f"{arch.id}_copy{idx}"
        d["display_name"] = f"{arch.display_name} (Copy)"
        clone = ForgeArchetype(**d)
        self.registry.upsert(clone)
        self._selected_id = clone.id
        self._rebuild_form()
        self._dirty = True

    # ── Drawing ─────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, font: pygame.font.Font,
             font_sm: pygame.font.Font, dt: float = 0.016):
        if not self.active:
            return
        sw, sh = surface.get_size()

        # Full background
        surface.fill((25, 25, 30))

        # Title bar
        pygame.draw.rect(surface, Theme.PANEL, (0, 0, sw, 36))
        draw_text(surface, "\u2692  Entity Forge", 12, 8, Theme.ACCENT, font)
        # Close button
        close_r = pygame.Rect(sw - 80, 4, 70, 28)
        mx, my = pygame.mouse.get_pos()
        close_hov = close_r.collidepoint(mx, my)
        pygame.draw.rect(surface, Theme.DANGER if close_hov else Theme.PANEL_LITE,
                         close_r, border_radius=4)
        draw_text_centered(surface, "Close", close_r, Theme.TEXT, font_sm)

        # Save button
        save_r = pygame.Rect(sw - 160, 4, 70, 28)
        save_hov = save_r.collidepoint(mx, my)
        pygame.draw.rect(surface, Theme.SUCCESS if save_hov else Theme.PANEL_LITE,
                         save_r, border_radius=4)
        draw_text_centered(surface, "Save", save_r, Theme.TEXT, font_sm)

        # Place on Map button
        place_r = pygame.Rect(sw - 260, 4, 90, 28)
        place_hov = place_r.collidepoint(mx, my)
        has_sel = self._selected_id is not None
        place_bg = Theme.ACCENT if (place_hov and has_sel) else Theme.PANEL_LITE
        pygame.draw.rect(surface, place_bg, place_r, border_radius=4)
        draw_text_centered(surface, "\u25B6 Place",
                           place_r,
                           Theme.TEXT if has_sel else Theme.TEXT_DIM,
                           font_sm)
        self._place_rect = place_r

        # Left: archetype list panel
        list_top = 38
        list_h = sh - list_top
        self._draw_list(surface, font, font_sm, list_top, list_h)

        # Right: property editor
        prop_x = self._s_list_w() + 1
        prop_w = sw - self._s_list_w()
        self._draw_props(surface, font, font_sm, prop_x, list_top,
                         prop_w, list_h)

        # Dropdown overlays on top of everything
        self._draw_dropdown_overlays(surface, font_sm)

    def _draw_list(self, surface: pygame.Surface,
                   font: pygame.font.Font, font_sm: pygame.font.Font,
                   top: int, height: int):
        """Draw the left-side archetype list."""
        lw = self._s_list_w()
        pygame.draw.rect(surface, Theme.PANEL, (0, top, lw, height))
        pygame.draw.line(surface, Theme.BORDER, (lw, top), (lw, top + height))

        # Filter row
        fx = 4
        fy = top + 4
        filters = ["All", "tile", "box", "billboard"]
        mx, my = pygame.mouse.get_pos()
        for label in filters:
            tw = font_sm.size(label)[0] + 10
            r = pygame.Rect(fx, fy, tw, 20)
            fval = "" if label == "All" else label
            is_sel = (self._filter_kind == fval)
            hov = r.collidepoint(mx, my)
            bg = Theme.SELECTED if is_sel else (Theme.HIGHLIGHT if hov else Theme.PANEL)
            pygame.draw.rect(surface, bg, r, border_radius=3)
            draw_text(surface, label, fx + 5, fy + 3,
                      Theme.ACCENT if is_sel else Theme.TEXT_DIM, font_sm)
            fx += tw + 3

        # New + Dup + Del buttons
        btn_y = fy + 24
        btn_specs = [
            ("+ New", Theme.SUCCESS),
            ("Dup", Theme.ACCENT),
            ("Del", Theme.DANGER),
        ]
        bx = 4
        self._btn_rects: dict[str, pygame.Rect] = {}
        for label, color in btn_specs:
            bw = font_sm.size(label)[0] + 16
            br = pygame.Rect(bx, btn_y, bw, 22)
            self._btn_rects[label] = br
            hov = br.collidepoint(mx, my)
            pygame.draw.rect(surface, color if hov else Theme.PANEL_LITE,
                             br, border_radius=4)
            draw_text_centered(surface, label, br, Theme.TEXT, font_sm)
            bx += bw + 4

        # Archetype list
        list_y = btn_y + 30
        item_h = 36
        clip = pygame.Rect(0, list_y, lw, top + height - list_y)
        surface.set_clip(clip)

        archetypes = self.registry.all()
        filtered = sorted(
            (a for a in archetypes.values()
             if not self._filter_kind or a.kind == self._filter_kind),
            key=lambda a: a.id,
        )

        for i, arch in enumerate(filtered):
            iy = list_y + i * item_h - self._list_scroll
            if iy + item_h < list_y or iy > top + height:
                continue
            ir = pygame.Rect(2, iy, lw - 4, item_h - 2)
            is_sel = (arch.id == self._selected_id)
            hov = ir.collidepoint(mx, my)
            bg = Theme.SELECTED if is_sel else (Theme.HIGHLIGHT if hov else Theme.PANEL)
            pygame.draw.rect(surface, bg, ir, border_radius=4)

            # Kind icon
            kind_icons = {"tile": "\u25A3", "box": "\u25A1", "billboard": "\u263A"}
            icon = kind_icons.get(arch.kind, "?")
            draw_text(surface, icon, ir.x + 6, ir.y + 4, Theme.ACCENT2, font)

            # Name + ID
            draw_text(surface, arch.display_name[:18], ir.x + 26, ir.y + 2,
                      Theme.TEXT, font_sm)
            draw_text(surface, f"{arch.kind}  {arch.id}",
                      ir.x + 26, ir.y + 16, Theme.TEXT_DIM, font_sm)

        surface.set_clip(None)

    def _draw_props(self, surface: pygame.Surface,
                    font: pygame.font.Font, font_sm: pygame.font.Font,
                    x: int, top: int, w: int, h: int):
        """Draw the right-side property editor."""
        arch = self._current()
        if arch is None:
            draw_text(surface, "No archetype selected",
                      x + 20, top + 40, Theme.TEXT_DIM, font)
            draw_text(surface, "Click '+ New' to create one.",
                      x + 20, top + 64, Theme.TEXT_DIM, font_sm)
            return

        form = self._form_widgets
        if not form:
            return

        # Clip to property area
        clip = pygame.Rect(x, top, w, h)
        surface.set_clip(clip)
        try:
            PAD = self._s_pad()
            ROW = self._s_row_h()
            col1 = x + PAD                     # labels
            col2 = x + Layout.s(130)           # fields
            fw = min(Layout.s(260), w - Layout.s(150))  # field width
            y = top + PAD - self._form_scroll

            # ── Section: Identity ──
            y = self._section_header(surface, font_sm, "IDENTITY", col1, y)
            y = self._field_row(surface, font_sm, "ID", form["id_field"],
                                col1, col2, y, fw)
            y = self._field_row(surface, font_sm, "Name", form["name_field"],
                                col1, col2, y, fw)
            y = self._field_row(surface, font_sm, "Kind", form["kind_dd"],
                                col1, col2, y, fw)
            y = self._field_row(surface, font_sm, "Tags", form["tags_field"],
                                col1, col2, y, fw)

            # ── Section: Dev Notes (stub) ──
            y += 6
            y = self._section_header(surface, font_sm, "DEV NOTES (Stub)",
                                     col1, y)
            y = self._field_row(surface, font_sm, "Notes",
                                form["notes_field"], col1, col2, y, fw)

            # ── Section: Kind-specific ──
            kind_dd: Dropdown = form["kind_dd"]
            kind = _KIND_OPTIONS[kind_dd.selected]

            y += 6
            if kind == "tile":
                y = self._section_header(surface, font_sm,
                                         "TILE PROPERTIES", col1, y)
                y = self._field_row(surface, font_sm, "Texture",
                                    form["texture_key"], col1, col2, y, fw)
                y = self._field_row(surface, font_sm, "Floor Z",
                                    form["floor_z"], col1, col2, y, 80)
                y = self._field_row(surface, font_sm, "Ceiling Z",
                                    form["ceiling_z"], col1, col2, y, 80)
                y = self._field_row(surface, font_sm, "Solid",
                                    form["solid_cb"], col1, col2, y, 24)
                y = self._field_row(surface, font_sm, "Transparent",
                                    form["transparent_cb"], col1, col2, y, 24)

            elif kind == "box":
                y = self._section_header(surface, font_sm,
                                         "BOX PROPERTIES", col1, y)
                y = self._field_row(surface, font_sm, "Width",
                                    form["box_w"], col1, col2, y, 80)
                y = self._field_row(surface, font_sm, "Depth",
                                    form["box_d"], col1, col2, y, 80)
                y = self._field_row(surface, font_sm, "Height",
                                    form["box_h"], col1, col2, y, 80)
                y = self._field_row(surface, font_sm, "Z Offset",
                                    form["z_offset"], col1, col2, y, 80)
                y = self._field_row(surface, font_sm, "Color",
                                    form["color_field"], col1, col2, y, fw)
                y = self._field_row(surface, font_sm, "Solid",
                                    form["solid_cb"], col1, col2, y, 24)
                y = self._field_row(surface, font_sm, "Texture",
                                    form["texture_key"], col1, col2, y, fw)

            elif kind == "billboard":
                y = self._section_header(surface, font_sm,
                                         "BILLBOARD PROPERTIES", col1, y)
                y = self._field_row(surface, font_sm, "Char",
                                    form["sprite_char"], col1, col2, y, 60)
                y = self._field_row(surface, font_sm, "Color",
                                    form["sprite_color"], col1, col2, y, fw)
                y = self._field_row(surface, font_sm, "Scale",
                                    form["scale"], col1, col2, y, 80)
                y = self._field_row(surface, font_sm, "Directional",
                                    form["directional_cb"], col1, col2, y, 24)
                y = self._field_row(surface, font_sm, "Sheet",
                                    form["sprite_sheet"], col1, col2, y, fw)

            # ── Preview box ──
            y += 12
            y = self._section_header(surface, font_sm, "PREVIEW", col1, y)
            self._draw_preview(surface, font, arch, kind, col1, y,
                               fw + Layout.s(120))
        finally:
            surface.set_clip(None)

    # ── Drawing helpers ─────────────────────────────────────────

    @staticmethod
    def _section_header(surface, font_sm, label, x, y) -> int:
        draw_text(surface, label, x, y, Theme.ACCENT, font_sm)
        y += 18
        pygame.draw.line(surface, Theme.BORDER, (x, y), (x + 300, y))
        return y + 4

    def _field_row(self, surface, font_sm, label, widget,
                   col1, col2, y, fw) -> int:
        """Draw one label + widget row.  Repositions widget and its
        sub-widgets so NumberField/ColorField render correctly."""
        draw_text(surface, label, col1, y + 6, Theme.TEXT_DIM, font_sm)
        new_rect = pygame.Rect(col2, y, fw, self._s_field_h())
        # Reposition sub-widgets when rect changes
        if widget.rect != new_rect:
            dx = new_rect.x - widget.rect.x
            dy = new_rect.y - widget.rect.y
            widget.rect = new_rect
            # NumberField has _text, _btn_up, _btn_dn
            if isinstance(widget, NumberField):
                widget._text.rect.move_ip(dx, dy)
                widget._btn_up.move_ip(dx, dy)
                widget._btn_dn.move_ip(dx, dy)
            # ColorField has _r, _g, _b (each a NumberField)
            elif isinstance(widget, ColorField):
                for nf in (widget._r, widget._g, widget._b):
                    nf.rect.move_ip(dx, dy)
                    nf._text.rect.move_ip(dx, dy)
                    nf._btn_up.move_ip(dx, dy)
                    nf._btn_dn.move_ip(dx, dy)
        widget.draw(surface, font_sm)
        return y + self._s_row_h()

    @staticmethod
    def _draw_preview(surface: pygame.Surface, font: pygame.font.Font,
                      arch: ForgeArchetype, kind: str,
                      x: int, y: int, w: int):
        """Draw a small visual preview of the archetype."""
        pw, ph = min(w, 200), 120
        pr = pygame.Rect(x, y, pw, ph)
        pygame.draw.rect(surface, Theme.FIELD_BG, pr, border_radius=6)
        pygame.draw.rect(surface, Theme.BORDER, pr, 1, border_radius=6)

        cx, cy = pr.centerx, pr.centery

        if kind == "tile":
            # Draw a colored swatch with texture key label
            swatch = pygame.Rect(cx - 30, cy - 30, 60, 60)
            pygame.draw.rect(surface, (100, 100, 100), swatch)
            draw_text_centered(surface, arch.texture_key or "?", swatch,
                               Theme.TEXT, font)

        elif kind == "box":
            # Simple isometric box
            bw = int(arch.width * 40)
            bh = int(arch.height * 40)
            bd = int(arch.depth * 20)
            color = arch.color

            # Front face
            front = pygame.Rect(cx - bw // 2, cy - bh // 2 + bd // 2,
                                bw, bh)
            pygame.draw.rect(surface, color, front)
            pygame.draw.rect(surface, (255, 255, 255), front, 1)

            # Top face (darker shade)
            dark = tuple(max(0, c - 40) for c in color)
            top_pts = [
                (front.left, front.top),
                (front.left + bd, front.top - bd),
                (front.right + bd, front.top - bd),
                (front.right, front.top),
            ]
            pygame.draw.polygon(surface, dark, top_pts)
            pygame.draw.polygon(surface, (255, 255, 255), top_pts, 1)

            # Right face (lighter shade)
            light = tuple(min(255, c + 20) for c in color)
            right_pts = [
                (front.right, front.top),
                (front.right + bd, front.top - bd),
                (front.right + bd, front.bottom - bd),
                (front.right, front.bottom),
            ]
            pygame.draw.polygon(surface, light, right_pts)
            pygame.draw.polygon(surface, (255, 255, 255), right_pts, 1)

        elif kind == "billboard":
            # Draw sprite char large
            big_font = get_font(max(24, round(36 * Layout.scale)))
            glyph = big_font.render(arch.sprite_char, True,
                                    arch.sprite_color)
            surface.blit(glyph, (cx - glyph.get_width() // 2,
                                 cy - glyph.get_height() // 2))

    def _draw_dropdown_overlays(self, surface: pygame.Surface,
                                font_sm: pygame.font.Font):
        """Draw open dropdown lists on top of everything."""
        for widget in self._form_widgets.values():
            if isinstance(widget, Dropdown) and widget.is_open:
                widget.draw_dropdown(surface, font_sm)

    # ── Event handling ──────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event) -> str | None:
        """Returns action string or None.

        Possible returns: ``'place'`` (request map placement),
        ``None`` (event consumed internally).
        """
        if not self.active:
            return None

        # Escape → close
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.close()
            return None

        # Ctrl+S → save
        if (event.type == pygame.KEYDOWN and event.key == pygame.K_s
                and event.mod & pygame.KMOD_CTRL):
            self._apply_form()
            self.registry.save()
            self._dirty = False
            self.state.toast("Forge: saved")
            return None

        sw = pygame.display.get_surface().get_width()

        # Mouse wheel scrolling
        if event.type == pygame.MOUSEWHEEL:
            mx, _ = pygame.mouse.get_pos()
            if mx < self._s_list_w():
                self._list_scroll = max(0,
                                        self._list_scroll - event.y * 30)
            else:
                self._form_scroll = max(0,
                                        self._form_scroll - event.y * 30)
            return None

        # Mouse click
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = event.pos

            # Title bar buttons
            if my < 36:
                # Close
                close_r = pygame.Rect(sw - 80, 4, 70, 28)
                if close_r.collidepoint(mx, my):
                    self.close()
                    return None
                # Save
                save_r = pygame.Rect(sw - 160, 4, 70, 28)
                if save_r.collidepoint(mx, my):
                    self._apply_form()
                    self.registry.save()
                    self._dirty = False
                    self.state.toast("Forge: saved")
                    return None
                # Place on Map
                if hasattr(self, '_place_rect') and self._place_rect.collidepoint(mx, my):
                    if self._selected_id:
                        self._apply_form()
                        self.registry.save()
                        self._dirty = False
                        return "place"
                    return None

            # List area
            if mx < self._s_list_w() and my >= 38:
                self._handle_list_click(mx, my)
                return None

        # Forward to form widgets
        if self._form_widgets:
            for widget in self._form_widgets.values():
                if hasattr(widget, "handle_event"):
                    widget.handle_event(event)

        return None

    def _handle_list_click(self, mx: int, my: int):
        """Handle clicks in the left list panel."""
        # Filter row
        top = 38
        fy = top + 4
        fx = 4
        font_sm = get_font(max(10, round(12 * Layout.scale)))
        filters = ["All", "tile", "box", "billboard"]
        for label in filters:
            tw = font_sm.size(label)[0] + 10
            r = pygame.Rect(fx, fy, tw, 20)
            if r.collidepoint(mx, my):
                self._filter_kind = "" if label == "All" else label
                return True
            fx += tw + 3

        # New / Dup / Del buttons
        for label, rect in self._btn_rects.items():
            if rect.collidepoint(mx, my):
                if "+ New" in label:
                    self._new_archetype()
                elif "Dup" in label:
                    self._duplicate_current()
                elif "Del" in label:
                    self._delete_current()
                return True

        # Archetype selection
        btn_y = fy + 24
        list_y = btn_y + 30
        item_h = 36

        archetypes = self.registry.all()
        filtered = sorted(
            (a for a in archetypes.values()
             if not self._filter_kind or a.kind == self._filter_kind),
            key=lambda a: a.id,
        )
        for i, arch in enumerate(filtered):
            iy = list_y + i * item_h - self._list_scroll
            ir = pygame.Rect(2, iy, self._s_list_w() - 4, item_h - 2)
            if ir.collidepoint(mx, my):
                # Apply current form before switching
                if self._selected_id:
                    self._apply_form()
                self._selected_id = arch.id
                self._rebuild_form()
                return True

        return True
