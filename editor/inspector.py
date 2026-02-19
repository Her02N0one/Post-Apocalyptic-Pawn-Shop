"""editor/inspector.py — Entity property inspector panel.

When an entity is selected, shows ALL its component properties as
editable fields.  Also shows zone-level properties when no entity
is selected.
"""

from __future__ import annotations

from typing import Any

import pygame

from editor.ui import (
    Theme, UIContext, TextField, NumberField, Checkbox, Dropdown,
    ColorField, ScrollPanel, draw_text, draw_section_header,
    draw_label,
)
from editor.state import (
    EditorState, Tool, list_loot_tables, load_item_ids,
)
from editor.canvas import get_prefab_defaults
from editor.layout import Layout


class Inspector:
    """Right-side panel showing editable properties of the selected
    entity, or zone properties when nothing is selected.
    """

    def __init__(self, state: EditorState, ctx: UIContext):
        self.state = state
        self.ctx = ctx
        self._scroll = ScrollPanel(pygame.Rect(0, 0, Layout.inspector_w, 600),
                                   content_height=800)
        # Cached widget instances — rebuilt when selection changes
        self._widgets: list[Any] = []
        self._last_entity_idx: int = -2  # sentinel
        self._prefab_list: list[str] = []
        self._loot_tables: list[str] = []
        self._item_ids: list[str] = []
        self._loaded_data = False

    def _ensure_data(self):
        if not self._loaded_data:
            self._loaded_data = True
            self._prefab_list = sorted(get_prefab_defaults().keys())
            self._loot_tables = list_loot_tables()
            self._item_ids = load_item_ids()

    def _rebuild_widgets(self, surface: pygame.Surface):
        """Rebuild widget list when selection changes."""
        self._ensure_data()
        self._widgets.clear()
        sw, sh = surface.get_size()
        L = Layout
        px = sw - L.inspector_w + 8
        w = L.inspector_w - 24

        st = self.state
        idx = st.selected_entity

        if idx < 0 or idx >= len(st.entities):
            # Zone properties mode
            self._build_zone_widgets(px, w)
        else:
            self._build_entity_widgets(px, w, st.entities[idx])

    def _build_zone_widgets(self, px: int, w: int):
        """Build widgets for zone-level properties."""
        st = self.state
        y = Layout.canvas_y + 8

        # Zone name (read-only label for now)
        self._widgets.append(("label", "ZONE PROPERTIES", px, y, Theme.ACCENT))
        y += 24

        self._widgets.append(("kv", "Name:", st.zone_name, px, y))
        y += 22
        self._widgets.append(("kv", "Size:",
                              f"{st.map_w} x {st.map_h}", px, y))
        y += 22
        self._widgets.append(("kv", "Anchor:",
                              f"({st.anchor[0]:.1f}, {st.anchor[1]:.1f})",
                              px, y))
        y += 22

        cb = Checkbox(pygame.Rect(px, y, w, 20), "First Person",
                      checked=st.first_person,
                      on_change=lambda v: setattr(st, 'first_person', v))
        self._widgets.append(("widget", cb))
        y += 28

        self._widgets.append(("kv", "Portals:",
                              str(len(st.portals)), px, y))
        y += 22
        self._widgets.append(("kv", "Entities:",
                              str(len(st.entities)), px, y))
        y += 30

        self._widgets.append(("label", "ENTITY LIST", px, y, Theme.ENTITY))
        y += 20

        for i, ent in enumerate(st.entities):
            name = st.entity_name(i)
            prefab = ent.get("prefab", "?")
            self._widgets.append(("entity_row", i, name, prefab, px, y))
            y += 22

        self._scroll.content_height = y - Layout.canvas_y

    def _build_entity_widgets(self, px: int, w: int, ent: dict):
        """Build widgets for a specific entity's properties."""
        st = self.state
        y = Layout.canvas_y + 8

        # Header
        name = ent.get("identity", {}).get("name",
                                           ent.get("id", "unnamed"))
        self._widgets.append(("label", f"ENTITY: {name[:20]}", px, y,
                              Theme.ENTITY))
        y += 24

        # ── ID & Prefab ────────────────────────────────────
        self._widgets.append(("section", "Identity", px, y, w))
        y += 22

        # ID field
        id_field = TextField(
            pygame.Rect(px + 70, y, w - 70, 22), self.ctx,
            value=ent.get("id", ""), placeholder="entity_id")
        id_field.on_submit = lambda v, _e=ent: _e.__setitem__("id", v)
        self._widgets.append(("labeled_widget", "ID:", id_field, px, y))
        y += 28

        # Prefab dropdown
        prefab_name = ent.get("prefab", "")
        prefab_idx = (self._prefab_list.index(prefab_name)
                      if prefab_name in self._prefab_list else 0)
        prefab_dd = Dropdown(
            pygame.Rect(px + 70, y, w - 70, 22),
            options=["(none)"] + self._prefab_list,
            selected=prefab_idx + 1)
        prefab_dd.on_change = lambda i, v, _e=ent: (
            _e.__setitem__("prefab", v if v != "(none)" else ""))
        self._widgets.append(("labeled_widget", "Prefab:", prefab_dd, px, y))
        y += 28

        # ── Identity component ─────────────────────────────
        ident = ent.setdefault("identity", {})
        name_field = TextField(
            pygame.Rect(px + 70, y, w - 70, 22), self.ctx,
            value=ident.get("name", ""), placeholder="Name")
        name_field.on_change = lambda v, _d=ident: _d.__setitem__("name", v)
        self._widgets.append(("labeled_widget", "Name:", name_field, px, y))
        y += 28

        kind_options = ["npc", "player", "item", "container", "dummy",
                        "beast", "ground_item", "crop"]
        kind_val = ident.get("kind", "npc")
        kind_idx = kind_options.index(kind_val) if kind_val in kind_options else 0
        kind_dd = Dropdown(
            pygame.Rect(px + 70, y, w - 70, 22),
            options=kind_options, selected=kind_idx)
        kind_dd.on_change = lambda i, v, _d=ident: _d.__setitem__("kind", v)
        self._widgets.append(("labeled_widget", "Kind:", kind_dd, px, y))
        y += 32

        # ── Position ───────────────────────────────────────
        self._widgets.append(("section", "Position", px, y, w))
        y += 22

        pos = ent.setdefault("position", {"x": 0.0, "y": 0.0})
        x_field = NumberField(
            pygame.Rect(px + 70, y, w - 70, 22), self.ctx,
            value=float(pos.get("x", 0)), min_val=-500, max_val=500,
            step=0.5, decimals=1)
        x_field.on_change = lambda v, _d=pos: _d.__setitem__("x", v)
        self._widgets.append(("labeled_widget", "X:", x_field, px, y))
        y += 28

        y_field = NumberField(
            pygame.Rect(px + 70, y, w - 70, 22), self.ctx,
            value=float(pos.get("y", 0)), min_val=-500, max_val=500,
            step=0.5, decimals=1)
        y_field.on_change = lambda v, _d=pos: _d.__setitem__("y", v)
        self._widgets.append(("labeled_widget", "Y:", y_field, px, y))
        y += 32

        # ── Sprite ─────────────────────────────────────────
        self._widgets.append(("section", "Sprite", px, y, w))
        y += 22

        sprite = ent.setdefault("sprite", {"char": "?",
                                           "color": [200, 200, 200]})
        char_field = TextField(
            pygame.Rect(px + 70, y, 40, 22), self.ctx,
            value=sprite.get("char", "?"))
        char_field.on_change = lambda v, _d=sprite: _d.__setitem__("char", v[:1] if v else "?")
        self._widgets.append(("labeled_widget", "Char:", char_field, px, y))

        layer_field = NumberField(
            pygame.Rect(px + 140, y, w - 140, 22), self.ctx,
            value=float(sprite.get("layer", 5)), min_val=0, max_val=20,
            step=1, is_int=True)
        layer_field.on_change = lambda v, _d=sprite: _d.__setitem__("layer", int(v))
        self._widgets.append(("labeled_widget", "Lyr:", layer_field,
                              px + 110, y))
        y += 28

        raw_color = sprite.get("color", [200, 200, 200])
        if not isinstance(raw_color, (list, tuple)) or len(raw_color) < 3:
            raw_color = [200, 200, 200]
        color_field = ColorField(
            pygame.Rect(px + 10, y, w - 10, 22), self.ctx,
            color=(int(raw_color[0]), int(raw_color[1]), int(raw_color[2])))
        color_field.on_change = lambda c, _d=sprite: _d.__setitem__(
            "color", list(c))
        self._widgets.append(("labeled_widget", "Color:", color_field,
                              px - 40, y))
        y += 32

        # ── Collider ───────────────────────────────────────
        col = ent.get("collider")
        if col is not None:
            self._widgets.append(("section", "Collider", px, y, w))
            y += 22

            col_w = NumberField(
                pygame.Rect(px + 70, y, (w - 70) // 2 - 4, 22), self.ctx,
                value=float(col.get("w", 0.6)), min_val=0.1, max_val=5,
                step=0.1, decimals=1)
            col_w.on_change = lambda v, _d=col: _d.__setitem__("w", v)
            self._widgets.append(("labeled_widget", "W:", col_w, px, y))

            col_h = NumberField(
                pygame.Rect(px + 70 + (w - 70) // 2, y,
                            (w - 70) // 2 - 4, 22), self.ctx,
                value=float(col.get("h", 0.6)), min_val=0.1, max_val=5,
                step=0.1, decimals=1)
            col_h.on_change = lambda v, _d=col: _d.__setitem__("h", v)
            self._widgets.append(("labeled_widget", "H:", col_h,
                                  px + (w) // 2, y))
            y += 28

            solid_cb = Checkbox(
                pygame.Rect(px, y, w, 20), "Solid",
                checked=bool(col.get("solid", True)),
                on_change=lambda v, _d=col: _d.__setitem__("solid", v))
            self._widgets.append(("widget", solid_cb))
            y += 28

        # ── Health ─────────────────────────────────────────
        hp = ent.get("health")
        if hp is not None:
            self._widgets.append(("section", "Health", px, y, w))
            y += 22

            hp_cur = NumberField(
                pygame.Rect(px + 70, y, w - 70, 22), self.ctx,
                value=float(hp.get("current", 100)), min_val=0, max_val=9999,
                step=5, decimals=0, is_int=True)
            hp_cur.on_change = lambda v, _d=hp: _d.__setitem__("current", v)
            self._widgets.append(("labeled_widget", "Current:", hp_cur,
                                  px, y))
            y += 28

            hp_max = NumberField(
                pygame.Rect(px + 70, y, w - 70, 22), self.ctx,
                value=float(hp.get("maximum", 100)), min_val=1, max_val=9999,
                step=5, decimals=0, is_int=True)
            hp_max.on_change = lambda v, _d=hp: _d.__setitem__("maximum", v)
            self._widgets.append(("labeled_widget", "Max:", hp_max, px, y))
            y += 32

        # ── TileEntity ─────────────────────────────────────
        te = ent.get("tile_entity")
        if te is not None:
            self._widgets.append(("section", "Tile Entity", px, y, w))
            y += 22

            te_types = ["container", "crop", "ground_item"]
            tt_val = te.get("tile_type", "container")
            tt_idx = te_types.index(tt_val) if tt_val in te_types else 0
            tt_dd = Dropdown(
                pygame.Rect(px + 70, y, w - 70, 22),
                options=te_types, selected=tt_idx)
            tt_dd.on_change = lambda i, v, _d=te: _d.__setitem__("tile_type", v)
            self._widgets.append(("labeled_widget", "Type:", tt_dd, px, y))
            y += 28

            # Loot table
            loot_opts = ["(none)"] + self._loot_tables
            lt_val = te.get("loot_table", "")
            lt_idx = (loot_opts.index(lt_val) if lt_val in loot_opts
                      else 0)
            lt_dd = Dropdown(
                pygame.Rect(px + 70, y, w - 70, 22),
                options=loot_opts, selected=lt_idx)
            lt_dd.on_change = lambda i, v, _d=te: _d.__setitem__(
                "loot_table", v if v != "(none)" else "")
            self._widgets.append(("labeled_widget", "Loot:", lt_dd, px, y))
            y += 28

            # Item ID (for ground items)
            if te.get("tile_type") == "ground_item":
                item_opts = ["(none)"] + self._item_ids
                item_val = te.get("item_id", "")
                item_idx = (item_opts.index(item_val)
                            if item_val in item_opts else 0)
                item_dd = Dropdown(
                    pygame.Rect(px + 70, y, w - 70, 22),
                    options=item_opts, selected=item_idx)
                item_dd.on_change = lambda i, v, _d=te: _d.__setitem__(
                    "item_id", v if v != "(none)" else "")
                self._widgets.append(("labeled_widget", "Item:",
                                      item_dd, px, y))
                y += 28

                qty_field = NumberField(
                    pygame.Rect(px + 70, y, w - 70, 22), self.ctx,
                    value=float(te.get("item_qty", 1)), min_val=1,
                    max_val=999, step=1, is_int=True)
                qty_field.on_change = lambda v, _d=te: _d.__setitem__(
                    "item_qty", int(v))
                self._widgets.append(("labeled_widget", "Qty:",
                                      qty_field, px, y))
                y += 28

            looted_cb = Checkbox(
                pygame.Rect(px, y, w, 20), "Already Looted",
                checked=bool(te.get("looted", False)),
                on_change=lambda v, _d=te: _d.__setitem__("looted", v))
            self._widgets.append(("widget", looted_cb))
            y += 32

        # ── WallSprite ─────────────────────────────────────
        ws = ent.get("wall_sprite")
        if ws is not None:
            self._widgets.append(("section", "Wall Sprite", px, y, w))
            y += 22

            tex_field = TextField(
                pygame.Rect(px + 70, y, w - 70, 22), self.ctx,
                value=ws.get("texture_key", ""))
            tex_field.on_change = lambda v, _d=ws: _d.__setitem__(
                "texture_key", v)
            self._widgets.append(("labeled_widget", "Texture:", tex_field,
                                  px, y))
            y += 28

            for label, key, default in [
                ("Width:", "width", 1.0),
                ("Height:", "height", 1.0),
                ("Elev:", "elevation", 0.0),
            ]:
                nf = NumberField(
                    pygame.Rect(px + 70, y, w - 70, 22), self.ctx,
                    value=float(ws.get(key, default)),
                    min_val=0, max_val=10, step=0.05, decimals=2)
                nf.on_change = lambda v, _d=ws, _k=key: _d.__setitem__(_k, v)
                self._widgets.append(("labeled_widget", label, nf, px, y))
                y += 28
            y += 4

        # ── Inventory ──────────────────────────────────────
        inv = ent.get("inventory")
        if inv is not None:
            self._widgets.append(("section", "Inventory", px, y, w))
            y += 22

            items = inv.get("items", {})
            for item_id, count in sorted(items.items()):
                self._widgets.append(("kv", f"  {item_id}:", str(count),
                                      px, y))
                y += 18
            if not items:
                self._widgets.append(("kv", "  (empty)", "", px, y))
                y += 18
            y += 8

        # ── Facing ─────────────────────────────────────────
        face = ent.get("facing")
        if face is not None:
            self._widgets.append(("section", "Facing", px, y, w))
            y += 22
            dirs = ["up", "down", "left", "right"]
            face_val = face.get("direction", "down")
            face_idx = dirs.index(face_val) if face_val in dirs else 1
            face_dd = Dropdown(
                pygame.Rect(px + 70, y, w - 70, 22),
                options=dirs, selected=face_idx)
            face_dd.on_change = lambda i, v, _d=face: _d.__setitem__(
                "direction", v)
            self._widgets.append(("labeled_widget", "Dir:", face_dd, px, y))
            y += 32

        # ── Dialogue ───────────────────────────────────────
        dlg = ent.get("dialogue")
        if dlg is not None:
            self._widgets.append(("section", "Dialogue", px, y, w))
            y += 22
            bark_field = TextField(
                pygame.Rect(px + 10, y, w - 10, 22), self.ctx,
                value=dlg.get("bark", ""))
            bark_field.on_change = lambda v, _d=dlg: _d.__setitem__("bark", v)
            self._widgets.append(("labeled_widget", "Bark:", bark_field,
                                  px, y))
            y += 32

        # ── Action buttons ─────────────────────────────────
        y += 10
        self._widgets.append(("action_btn", "Add Component...", px, y, w))
        y += 30
        self._widgets.append(("delete_btn", "Delete Entity", px, y, w))
        y += 30

        self._scroll.content_height = y - Layout.canvas_y

    # ── Drawing ──────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface,
             font: pygame.font.Font, font_sm: pygame.font.Font,
             dt: float = 0.016):
        L = Layout
        sw, sh = surface.get_size()
        panel_x = sw - L.inspector_w
        panel_h = sh - L.canvas_y - L.status_h

        # Background
        pygame.draw.rect(surface, Theme.PANEL,
                         (panel_x, L.canvas_y, L.inspector_w, panel_h))
        pygame.draw.line(surface, Theme.BORDER,
                         (panel_x, L.canvas_y), (panel_x, sh - L.status_h))

        # Header
        st = self.state
        if st.selected_entity != self._last_entity_idx:
            self._last_entity_idx = st.selected_entity
            self._rebuild_widgets(surface)

        # Draw widgets
        self._scroll.rect = pygame.Rect(panel_x, L.canvas_y,
                                        L.inspector_w, panel_h)
        offset = int(self._scroll.scroll_y)

        surface.set_clip(pygame.Rect(panel_x, L.canvas_y,
                                     L.inspector_w, panel_h))

        for entry in self._widgets:
            kind = entry[0]

            if kind == "label":
                _, text, x, y, color = entry
                draw_text(surface, text, x, y - offset, color, font)

            elif kind == "section":
                _, text, x, y, w = entry
                draw_section_header(surface, text, x, y - offset, w, font_sm)

            elif kind == "kv":
                _, label, value, x, y = entry
                draw_text(surface, label, x, y - offset, Theme.TEXT_DIM,
                          font_sm)
                draw_text(surface, value, x + 70, y - offset, Theme.TEXT,
                          font_sm)

            elif kind == "labeled_widget":
                _, label, widget, x, y = entry
                draw_label(surface, label, x, y - offset, font_sm)
                # Offset the widget rect for scrolling
                orig_y = widget.rect.y
                widget.rect.y -= offset
                if hasattr(widget, 'draw'):
                    if isinstance(widget, (NumberField, TextField, ColorField)):
                        widget.draw(surface, font_sm, dt)
                    else:
                        widget.draw(surface, font_sm)
                widget.rect.y = orig_y

            elif kind == "widget":
                _, widget = entry
                orig_y = widget.rect.y
                widget.rect.y -= offset
                widget.draw(surface, font_sm)
                widget.rect.y = orig_y

            elif kind == "entity_row":
                _, idx, name, prefab, x, y = entry
                ry = y - offset
                is_sel = (idx == st.selected_entity)
                row_rect = pygame.Rect(x, ry, L.inspector_w - 20, 20)
                if is_sel:
                    pygame.draw.rect(surface, Theme.SELECTED, row_rect,
                                     border_radius=3)
                elif row_rect.collidepoint(pygame.mouse.get_pos()):
                    pygame.draw.rect(surface, Theme.HIGHLIGHT, row_rect,
                                     border_radius=3)
                draw_text(surface, f"{prefab[:8]}: {name[:14]}",
                          x + 4, ry + 2, Theme.TEXT, font_sm)

            elif kind == "delete_btn":
                _, label, x, y, w = entry
                rect = pygame.Rect(x, y - offset, w, 24)
                hov = rect.collidepoint(pygame.mouse.get_pos())
                bg = (100, 40, 40) if hov else (70, 30, 30)
                pygame.draw.rect(surface, bg, rect, border_radius=4)
                pygame.draw.rect(surface, Theme.DANGER, rect, 1,
                                 border_radius=4)
                draw_text_centered = font_sm.render(label, True, Theme.DANGER)
                surface.blit(draw_text_centered,
                             (rect.centerx - draw_text_centered.get_width() // 2,
                              rect.centery - draw_text_centered.get_height() // 2))

            elif kind == "action_btn":
                _, label, x, y, w = entry
                rect = pygame.Rect(x, y - offset, w, 24)
                hov = rect.collidepoint(pygame.mouse.get_pos())
                bg = Theme.BTN_HOVER if hov else Theme.PANEL_LITE
                pygame.draw.rect(surface, bg, rect, border_radius=4)
                pygame.draw.rect(surface, Theme.BORDER, rect, 1,
                                 border_radius=4)
                rendered = font_sm.render(label, True, Theme.TEXT)
                surface.blit(rendered,
                             (rect.centerx - rendered.get_width() // 2,
                              rect.centery - rendered.get_height() // 2))

        surface.set_clip(None)

        # Draw scrollbar
        self._scroll.draw_scrollbar(surface)

        # Draw any open dropdowns ON TOP of everything
        for entry in self._widgets:
            if entry[0] == "labeled_widget":
                widget = entry[2]
                if isinstance(widget, Dropdown) and widget.is_open:
                    orig_y = widget.rect.y
                    widget.rect.y -= offset
                    widget.draw_dropdown(surface, font_sm)
                    widget.rect.y = orig_y

    # ── Event handling ───────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event,
                     surface: pygame.Surface) -> str | None:
        """Returns action string or None.
        Actions: 'delete_entity', 'add_component', 'select_entity:N'
        """
        sw, sh = surface.get_size()
        L = Layout
        panel_x = sw - L.inspector_w

        # Only handle events in inspector area
        if event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP,
                          pygame.MOUSEMOTION, pygame.MOUSEWHEEL):
            pos = getattr(event, 'pos', pygame.mouse.get_pos())
            if pos[0] < panel_x:
                return None

        # Scrolling
        if self._scroll.handle_event(event):
            return None

        offset = int(self._scroll.scroll_y)
        st = self.state

        # Handle widget events
        for entry in self._widgets:
            kind = entry[0]

            if kind == "labeled_widget":
                _, label, widget, x, y = entry
                orig_y = widget.rect.y
                widget.rect.y -= offset
                result = widget.handle_event(event)
                widget.rect.y = orig_y
                if result:
                    st.dirty = True
                    return None

            elif kind == "widget":
                _, widget = entry
                orig_y = widget.rect.y
                widget.rect.y -= offset
                result = widget.handle_event(event)
                widget.rect.y = orig_y
                if result:
                    st.dirty = True
                    return None

            elif kind == "entity_row":
                _, idx, name, prefab, x, y = entry
                if (event.type == pygame.MOUSEBUTTONDOWN
                        and event.button == 1):
                    ry = y - offset
                    row_rect = pygame.Rect(x, ry, L.inspector_w - 20, 20)
                    if row_rect.collidepoint(event.pos):
                        st.selected_entity = idx
                        st.tool = Tool.ENTITY
                        return f"select_entity:{idx}"

            elif kind == "delete_btn":
                _, label, x, y, w = entry
                if (event.type == pygame.MOUSEBUTTONDOWN
                        and event.button == 1):
                    rect = pygame.Rect(x, y - offset, w, 24)
                    if rect.collidepoint(event.pos):
                        return "delete_entity"

            elif kind == "action_btn":
                _, label, x, y, w = entry
                if (event.type == pygame.MOUSEBUTTONDOWN
                        and event.button == 1):
                    rect = pygame.Rect(x, y - offset, w, 24)
                    if rect.collidepoint(event.pos):
                        return "add_component"

        # Keyboard events go to focused widget regardless of position
        if event.type == pygame.KEYDOWN and self.ctx.any_focused():
            for entry in self._widgets:
                if entry[0] == "labeled_widget":
                    widget = entry[2]
                    orig_y = widget.rect.y
                    widget.rect.y -= offset
                    widget.handle_event(event)
                    widget.rect.y = orig_y

        return None

    def force_rebuild(self):
        """Force widget rebuild on next draw."""
        self._last_entity_idx = -2
        self._loaded_data = False
