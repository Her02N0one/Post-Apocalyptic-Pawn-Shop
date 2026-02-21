"""editor/inspector.py — Tabbed inspector panel (Zone + Tile + Entity).

Three tabs at the top of the right panel:
  **Zone** — zone properties and entity list
  **Tile** — contextual tile info showing type, textures, and colour
  **Entity** — selected entity property editor

The Tile tab is populated from:
  1. ``core.tiles.tile_def()`` — tile type, flags, textures
  2. ``systems.textures.TextureAtlas`` — 64×64 texture Surfaces

Widget entries are **typed dataclasses** from ``inspector_entries``,
replacing the old raw-tuple system.  The draw loop and event loop
dispatch via ``isinstance`` — fully type-safe and IDE-friendly.
"""

from __future__ import annotations

from typing import Any

import pygame

from editor.ui import (
    Theme, UIContext, TextField, NumberField, Checkbox, Dropdown,
    ColorField, ScrollPanel, draw_text, draw_text_centered,
    draw_section_header, draw_label, draw_item_row, clamp_scroll,
    draw_tab_button,
)
from editor.entity_defs import (
    EntityDef, EDIdentity, EDSprite, EDCollider, EDHealth,
    EDTileEntity, EDWallSprite, EDInventory, EDFacing, EDDialogue,
    EDPortal,
)
from editor.inspector_entries import (
    InspectorEntry, LabelEntry, SectionEntry, KVEntry,
    LabeledWidgetEntry, WidgetEntry, EntityRowEntry,
    ActionButtonEntry, DeleteButtonEntry, TexPreviewEntry,
    ColorSwatchEntry,
)
from editor.state import (
    EditorState, Tool, list_loot_tables, load_item_ids,
)
from editor.canvas import get_prefab_defaults
from editor.layout import Layout
from core.tiles import tile_def, TILE_REGISTRY, TILE_NAMES, TILE_COLORS, TILE_CATEGORIES

# ── Tab constants ────────────────────────────────────────────────

TAB_ZONE   = "zone"
TAB_TILE   = "tile"
TAB_ENTITY = "entity"
_TAB_LABELS = {TAB_ZONE: "Zone", TAB_TILE: "Tile", TAB_ENTITY: "Entity"}
# Tab-bar height is computed dynamically via Layout.s(26).


class Inspector:
    """Right-side panel with **Zone**, **Tile**, and **Entity** tabs.

    Zone tab   — zone-level properties and entity list.
    Tile tab   — tile info, flags, face-model cube net with texture previews.
    Entity tab — editable properties for the selected entity.
    """

    def __init__(self, state: EditorState, ctx: UIContext,
                 atlas=None):
        self.state = state
        self.ctx = ctx
        self._atlas = atlas  # TextureAtlas or None
        self._tab: str = TAB_ZONE  # active tab
        self._scroll = ScrollPanel(pygame.Rect(0, 0, Layout.inspector_w, 600),
                                   content_height=800)
        # Zone-tab widget cache
        self._widgets: list[InspectorEntry] = []
        # Entity-tab widget cache
        self._entity_widgets: list[InspectorEntry] = []
        self._last_entity_idx: int = -2  # sentinel for zone tab
        self._last_entity_tab_idx: int = -2  # sentinel for entity tab
        # Tile-tab widget cache
        self._tile_widgets: list[InspectorEntry] = []
        self._last_tile_id: str = ""
        # Track panel geometry to force rebuild on resize
        self._last_panel_x: int = -1
        self._last_tab: str = ""  # detect tab switches
        # Lazy data
        self._prefab_list: list[str] = []
        self._loot_tables: list[str] = []
        self._item_ids: list[str] = []
        self._loaded_data = False

    def set_tab(self, tab: str) -> None:
        """Programmatically switch the active inspector tab."""
        if tab in _TAB_LABELS and tab != self._tab:
            self._tab = tab
            self._scroll.scroll_y = 0.0

    def _set_zone_name(self, st: EditorState, name: str):
        """Rename zone from the inspector name field."""
        name = name.strip()
        if name and name != st.zone_name:
            st.rename_zone(name)
            self.force_rebuild()

    def _ensure_data(self):
        if not self._loaded_data:
            self._loaded_data = True
            self._prefab_list = sorted(get_prefab_defaults().keys())
            self._loot_tables = list_loot_tables()
            self._item_ids = load_item_ids()

    def _rebuild_widgets(self, surface: pygame.Surface):
        """Rebuild zone-tab widget list."""
        self._ensure_data()
        self._widgets.clear()
        L = Layout
        px = L.rp_x + L.pad_md
        w = L.inspector_w - 3 * L.pad_md
        self._build_zone_widgets(px, w)

    def _rebuild_entity_widgets_list(self, surface: pygame.Surface):
        """Rebuild entity-tab widget list for the currently selected entity."""
        self._ensure_data()
        self._entity_widgets.clear()
        L = Layout
        px = L.rp_x + L.pad_md
        w = L.inspector_w - 3 * L.pad_md
        st = self.state
        idx = st.selected_entity
        if 0 <= idx < len(st.entities):
            self._build_entity_widgets(px, w, st.entities[idx],
                                       target=self._entity_widgets)
        else:
            # No entity selected — show hint
            y = L.rp_content_y + L.pad_md
            self._entity_widgets.append(
                LabelEntry(x=px, y=y, text="No entity selected",
                           color=Theme.TEXT_DIM))
            y += L.s(20)
            self._entity_widgets.append(
                LabelEntry(x=px, y=y,
                           text="Use Select tool to click an entity",
                           color=Theme.TEXT_DIM))
            self._scroll.content_height = y - L.rp_content_y + L.s(30)

    def _build_zone_widgets(self, px: int, w: int):
        """Build widgets for zone-level properties."""
        st = self.state
        L = Layout
        y = L.rp_content_y + L.pad_md
        add = self._widgets.append

        add(LabelEntry(x=px, y=y, text="ZONE PROPERTIES",
                        color=Theme.ACCENT))
        y += L.s(24)

        # Editable zone name
        name_field = TextField(
            pygame.Rect(px + L.label_col, y, w - L.label_col, L.field_h),
            self.ctx, value=st.zone_name)
        name_field.on_submit = lambda v, _st=st: self._set_zone_name(_st, v)
        add(LabeledWidgetEntry(x=px, y=y, label="Name:", widget=name_field))
        y += L.item_h

        # Editable width/height
        w_field = NumberField(
            pygame.Rect(px + L.label_col, y, (w - L.label_col) // 2 - L.pad_sm, L.field_h),
            self.ctx, value=st.map_w, min_val=5, max_val=200)
        w_field.on_change = lambda v, _st=st: _st.resize_zone(int(v), _st.map_h)
        add(LabeledWidgetEntry(x=px, y=y, label="Width:", widget=w_field))
        h_field = NumberField(
            pygame.Rect(px + L.label_col + (w - L.label_col) // 2, y,
                        (w - L.label_col) // 2, L.field_h),
            self.ctx, value=st.map_h, min_val=5, max_val=200)
        h_field.on_change = lambda v, _st=st: _st.resize_zone(_st.map_w, int(v))
        add(LabeledWidgetEntry(x=px, y=y, label="", widget=h_field))
        y += L.item_h

        cb = Checkbox(pygame.Rect(px, y, w, L.s(20)), "First Person",
                      checked=st.first_person,
                      on_change=lambda v: setattr(st, 'first_person', v))
        add(WidgetEntry(x=px, y=y, widget=cb))
        y += L.item_h

        add(KVEntry(x=px, y=y, label="Portals:",
                     value=str(len(st.portals))))
        y += L.field_h
        n_ents = sum(1 for e in st.entities if e.portal is None)
        add(KVEntry(x=px, y=y, label="Entities:",
                     value=str(n_ents)))
        y += L.item_h

        # Erase tile picker
        from core.tiles import TILE_REGISTRY as _TR
        erase_ids = sorted(_TR.keys())
        erase_idx = erase_ids.index(st.erase_tile) if st.erase_tile in erase_ids else 0
        erase_dd = Dropdown(
            pygame.Rect(px + L.label_col, y, w - L.label_col, L.field_h),
            erase_ids, selected=erase_idx,
            on_change=lambda i, _ids=erase_ids, _st=st: setattr(_st, 'erase_tile', _ids[i]))
        add(LabeledWidgetEntry(x=px, y=y, label="Erase Tile:", widget=erase_dd))
        y += L.item_h

        add(LabelEntry(x=px, y=y, text="ENTITY LIST",
                        color=Theme.ENTITY))
        y += L.s(20)

        for i, ent in enumerate(st.entities):
            name = st.entity_name(i)
            prefab = ent.prefab or "?"
            add(EntityRowEntry(x=px, y=y, idx=i, name=name, prefab=prefab))
            y += L.field_h

        self._scroll.content_height = y - L.rp_content_y

    def _build_entity_widgets(self, px: int, w: int, ent: EntityDef,
                              *, target: list | None = None):
        """Build widgets for a specific entity's properties."""
        st = self.state
        L = Layout
        lc = L.label_col
        fh = L.field_h
        y = L.rp_content_y + L.pad_md
        add = (target if target is not None else self._widgets).append

        # Header
        name = ent.display_name
        add(LabelEntry(x=px, y=y, text=f"ENTITY: {name[:20]}",
                        color=Theme.ENTITY))
        y += L.s(24)

        # ── ID & Prefab ────────────────────────────────────
        add(SectionEntry(x=px, y=y, text="Identity", w=w))
        y += L.header_h

        id_field = TextField(
            pygame.Rect(px + lc, y, w - lc, fh), self.ctx,
            value=ent.id)
        id_field.on_submit = lambda v, _e=ent: setattr(_e, "id", v)
        add(LabeledWidgetEntry(x=px, y=y, label="ID:", widget=id_field))
        y += L.item_h

        prefab_name = ent.prefab
        prefab_idx = (self._prefab_list.index(prefab_name)
                      if prefab_name in self._prefab_list else 0)
        prefab_dd = Dropdown(
            pygame.Rect(px + lc, y, w - lc, fh),
            options=["(none)"] + self._prefab_list,
            selected=prefab_idx + 1)
        prefab_dd.on_change = lambda i, v, _e=ent: (
            setattr(_e, "prefab", v if v != "(none)" else ""))
        add(LabeledWidgetEntry(x=px, y=y, label="Prefab:",
                                widget=prefab_dd))
        y += L.item_h

        # ── Identity component ─────────────────────────────
        if ent.identity is None:
            ent.identity = EDIdentity()
        ident = ent.identity
        name_field = TextField(
            pygame.Rect(px + lc, y, w - lc, fh), self.ctx,
            value=ident.name)
        name_field.on_change = lambda v, _d=ident: setattr(_d, "name", v)
        add(LabeledWidgetEntry(x=px, y=y, label="Name:",
                                widget=name_field))
        y += L.item_h

        kind_options = ["npc", "player", "item", "container", "dummy",
                        "prop", "beast", "ground_item", "crop"]
        kind_val = ident.kind
        kind_idx = (kind_options.index(kind_val)
                    if kind_val in kind_options else 0)
        kind_dd = Dropdown(
            pygame.Rect(px + lc, y, w - lc, fh),
            options=kind_options, selected=kind_idx)
        kind_dd.on_change = lambda i, v, _d=ident: setattr(_d, "kind", v)
        add(LabeledWidgetEntry(x=px, y=y, label="Kind:", widget=kind_dd))
        y += L.item_h

        # ── Dev Notes / Tags ──────────────────────────────
        forge_ref = ent.forge_archetype
        if forge_ref:
            add(KVEntry(x=px, y=y, label="Forge:", value=forge_ref))
            y += L.s(20)

        add(SectionEntry(x=px, y=y, text="Dev Notes", w=w))
        y += L.header_h
        notes_field = TextField(
            pygame.Rect(px + lc, y, w - lc, fh), self.ctx,
            value=ent.dev_notes)
        notes_field.on_change = lambda v, _e=ent: setattr(_e, "dev_notes", v)
        add(LabeledWidgetEntry(x=px, y=y, label="Notes:",
                                widget=notes_field))
        y += L.s(26)

        tags_val = ent.tags
        tags_str = ", ".join(tags_val) if tags_val else ""
        tags_field = TextField(
            pygame.Rect(px + lc, y, w - lc, fh), self.ctx,
            value=tags_str)
        def _set_tags(v, _e=ent):
            _e.tags = [t.strip() for t in v.split(",") if t.strip()]
        tags_field.on_change = _set_tags
        add(LabeledWidgetEntry(x=px, y=y, label="Tags:",
                                widget=tags_field))
        y += L.s(30)

        # ── Position ───────────────────────────────────────
        add(SectionEntry(x=px, y=y, text="Position", w=w))
        y += L.header_h

        pos = ent.position
        x_field = NumberField(
            pygame.Rect(px + lc, y, w - lc, fh), self.ctx,
            value=float(pos.x), min_val=-500, max_val=500,
            step=0.5, decimals=1)
        x_field.on_change = lambda v, _d=pos: setattr(_d, "x", v)
        add(LabeledWidgetEntry(x=px, y=y, label="X:", widget=x_field))
        y += L.item_h

        y_field = NumberField(
            pygame.Rect(px + lc, y, w - lc, fh), self.ctx,
            value=float(pos.y), min_val=-500, max_val=500,
            step=0.5, decimals=1)
        y_field.on_change = lambda v, _d=pos: setattr(_d, "y", v)
        add(LabeledWidgetEntry(x=px, y=y, label="Y:", widget=y_field))
        y += L.s(32)

        # ── Sprite ─────────────────────────────────────────
        add(SectionEntry(x=px, y=y, text="Sprite", w=w))
        y += L.header_h

        if ent.sprite is None:
            ent.sprite = EDSprite()
        sprite = ent.sprite
        char_w = L.s(40)
        char_field = TextField(
            pygame.Rect(px + lc, y, char_w, fh), self.ctx,
            value=sprite.char)
        char_field.on_change = (
            lambda v, _d=sprite: setattr(_d, "char", v[:1] if v else "?"))
        add(LabeledWidgetEntry(x=px, y=y, label="Char:",
                                widget=char_field))

        lyr_x = px + lc + char_w + L.pad_lg
        layer_field = NumberField(
            pygame.Rect(lyr_x, y, w - (lyr_x - px), fh), self.ctx,
            value=float(sprite.layer), min_val=0, max_val=20,
            step=1, is_int=True)
        layer_field.on_change = (
            lambda v, _d=sprite: setattr(_d, "layer", int(v)))
        add(LabeledWidgetEntry(x=lyr_x - lc, y=y, label="Lyr:",
                                widget=layer_field))
        y += L.item_h

        raw_color = sprite.color
        if not isinstance(raw_color, (list, tuple)) or len(raw_color) < 3:
            raw_color = [200, 200, 200]
        color_field = ColorField(
            pygame.Rect(px + lc, y, w - lc, fh), self.ctx,
            color=(int(raw_color[0]), int(raw_color[1]), int(raw_color[2])))
        color_field.on_change = (
            lambda c, _d=sprite: setattr(_d, "color", list(c)))
        add(LabeledWidgetEntry(x=px, y=y, label="Color:",
                                widget=color_field))
        y += L.s(32)

        # ── Collider ───────────────────────────────────────
        col = ent.collider
        if col is not None:
            add(SectionEntry(x=px, y=y, text="Collider", w=w))
            y += L.header_h

            half_w = (w - lc) // 2 - L.pad_sm
            col_w = NumberField(
                pygame.Rect(px + lc, y, half_w, fh), self.ctx,
                value=float(col.w), min_val=0.1, max_val=5,
                step=0.1, decimals=1)
            col_w.on_change = lambda v, _d=col: setattr(_d, "w", v)
            add(LabeledWidgetEntry(x=px, y=y, label="W:", widget=col_w))

            col_h = NumberField(
                pygame.Rect(px + lc + half_w + L.pad_sm, y,
                            half_w, fh), self.ctx,
                value=float(col.h), min_val=0.1, max_val=5,
                step=0.1, decimals=1)
            col_h.on_change = lambda v, _d=col: setattr(_d, "h", v)
            add(LabeledWidgetEntry(x=px + w // 2, y=y, label="H:",
                                    widget=col_h))
            y += L.item_h

            solid_cb = Checkbox(
                pygame.Rect(px, y, w, L.s(20)), "Solid",
                checked=bool(col.solid),
                on_change=lambda v, _d=col: setattr(_d, "solid", v))
            add(WidgetEntry(x=px, y=y, widget=solid_cb))
            y += L.item_h

        # ── Health ─────────────────────────────────────────
        hp = ent.health
        if hp is not None:
            add(SectionEntry(x=px, y=y, text="Health", w=w))
            y += L.header_h

            hp_cur = NumberField(
                pygame.Rect(px + lc, y, w - lc, fh), self.ctx,
                value=float(hp.current), min_val=0, max_val=9999,
                step=5, decimals=0, is_int=True)
            hp_cur.on_change = lambda v, _d=hp: setattr(_d, "current", v)
            add(LabeledWidgetEntry(x=px, y=y, label="Current:",
                                    widget=hp_cur))
            y += L.item_h

            hp_max = NumberField(
                pygame.Rect(px + lc, y, w - lc, fh), self.ctx,
                value=float(hp.maximum), min_val=1, max_val=9999,
                step=5, decimals=0, is_int=True)
            hp_max.on_change = lambda v, _d=hp: setattr(_d, "maximum", v)
            add(LabeledWidgetEntry(x=px, y=y, label="Max:", widget=hp_max))
            y += L.s(32)

        # ── TileEntity ─────────────────────────────────────
        te = ent.tile_entity
        if te is not None:
            add(SectionEntry(x=px, y=y, text="Tile Entity", w=w))
            y += L.header_h

            te_types = ["container", "crop", "ground_item"]
            tt_val = te.tile_type
            tt_idx = te_types.index(tt_val) if tt_val in te_types else 0
            tt_dd = Dropdown(
                pygame.Rect(px + lc, y, w - lc, fh),
                options=te_types, selected=tt_idx)
            tt_dd.on_change = (
                lambda i, v, _d=te: setattr(_d, "tile_type", v))
            add(LabeledWidgetEntry(x=px, y=y, label="Type:", widget=tt_dd))
            y += L.item_h

            loot_opts = ["(none)"] + self._loot_tables
            lt_val = te.loot_table
            lt_idx = (loot_opts.index(lt_val) if lt_val in loot_opts
                      else 0)
            lt_dd = Dropdown(
                pygame.Rect(px + lc, y, w - lc, fh),
                options=loot_opts, selected=lt_idx)
            lt_dd.on_change = lambda i, v, _d=te: setattr(
                _d, "loot_table", v if v != "(none)" else "")
            add(LabeledWidgetEntry(x=px, y=y, label="Loot:", widget=lt_dd))
            y += L.item_h

            if te.tile_type == "ground_item":
                item_opts = ["(none)"] + self._item_ids
                item_val = te.item_id
                item_idx = (item_opts.index(item_val)
                            if item_val in item_opts else 0)
                item_dd = Dropdown(
                    pygame.Rect(px + lc, y, w - lc, fh),
                    options=item_opts, selected=item_idx)
                item_dd.on_change = lambda i, v, _d=te: setattr(
                    _d, "item_id", v if v != "(none)" else "")
                add(LabeledWidgetEntry(x=px, y=y, label="Item:",
                                        widget=item_dd))
                y += L.item_h

                qty_field = NumberField(
                    pygame.Rect(px + lc, y, w - lc, fh), self.ctx,
                    value=float(te.item_qty), min_val=1,
                    max_val=999, step=1, is_int=True)
                qty_field.on_change = lambda v, _d=te: setattr(
                    _d, "item_qty", int(v))
                add(LabeledWidgetEntry(x=px, y=y, label="Qty:",
                                        widget=qty_field))
                y += L.item_h

            looted_cb = Checkbox(
                pygame.Rect(px, y, w, L.s(20)), "Already Looted",
                checked=bool(te.looted),
                on_change=lambda v, _d=te: setattr(_d, "looted", v))
            add(WidgetEntry(x=px, y=y, widget=looted_cb))
            y += L.s(32)

        # ── WallSprite ─────────────────────────────────────
        ws = ent.wall_sprite
        if ws is not None:
            add(SectionEntry(x=px, y=y, text="Wall Sprite", w=w))
            y += L.header_h

            tex_field = TextField(
                pygame.Rect(px + lc, y, w - lc, fh), self.ctx,
                value=ws.texture_key)
            tex_field.on_change = (
                lambda v, _d=ws: setattr(_d, "texture_key", v))
            add(LabeledWidgetEntry(x=px, y=y, label="Texture:",
                                    widget=tex_field))
            y += L.item_h

            for label, key, default in [
                ("Width:", "width", 1.0),
                ("Height:", "height", 1.0),
                ("Elev:", "elevation", 0.0),
            ]:
                nf = NumberField(
                    pygame.Rect(px + lc, y, w - lc, fh), self.ctx,
                    value=float(getattr(ws, key, default)),
                    min_val=0, max_val=10, step=0.05, decimals=2)
                nf.on_change = (
                    lambda v, _d=ws, _k=key: setattr(_d, _k, v))
                add(LabeledWidgetEntry(x=px, y=y, label=label, widget=nf))
                y += L.item_h
            y += L.pad_sm

        # ── Inventory ──────────────────────────────────────
        inv = ent.inventory
        if inv is not None:
            add(SectionEntry(x=px, y=y, text="Inventory", w=w))
            y += L.header_h

            items = inv.items
            for item_id, count in sorted(items.items()):
                add(KVEntry(x=px, y=y, label=f"  {item_id}:",
                             value=str(count)))
                y += L.s(18)
            if not items:
                add(KVEntry(x=px, y=y, label="  (empty)", value=""))
                y += L.s(18)
            y += L.pad_md

        # ── Facing ─────────────────────────────────────────
        face = ent.facing
        if face is not None:
            add(SectionEntry(x=px, y=y, text="Facing", w=w))
            y += L.header_h
            dirs = ["up", "down", "left", "right"]
            face_val = face.direction
            face_idx = dirs.index(face_val) if face_val in dirs else 1
            face_dd = Dropdown(
                pygame.Rect(px + lc, y, w - lc, fh),
                options=dirs, selected=face_idx)
            face_dd.on_change = (
                lambda i, v, _d=face: setattr(_d, "direction", v))
            add(LabeledWidgetEntry(x=px, y=y, label="Dir:", widget=face_dd))
            y += L.s(32)

        # ── Dialogue ───────────────────────────────────────
        dlg = ent.dialogue
        if dlg is not None:
            add(SectionEntry(x=px, y=y, text="Dialogue", w=w))
            y += L.header_h
            bark_field = TextField(
                pygame.Rect(px + lc, y, w - lc, fh), self.ctx,
                value=dlg.bark)
            bark_field.on_change = (
                lambda v, _d=dlg: setattr(_d, "bark", v))
            add(LabeledWidgetEntry(x=px, y=y, label="Bark:",
                                    widget=bark_field))
            y += L.s(32)

        # ── Portal ─────────────────────────────────────────
        ptl = ent.portal
        if ptl is not None:
            add(SectionEntry(x=px, y=y, text="Portal", w=w))
            y += L.header_h

            tz_field = TextField(
                pygame.Rect(px + lc, y, w - lc, fh), self.ctx,
                value=ptl.target_zone)
            tz_field.on_change = (
                lambda v, _d=ptl: setattr(_d, "target_zone", v))
            add(LabeledWidgetEntry(x=px, y=y, label="Target:",
                                    widget=tz_field))
            y += L.item_h

            tp = ptl.target_pos
            tp_r = NumberField(
                pygame.Rect(px + lc, y, w - lc, fh), self.ctx,
                value=float(tp[0]) if len(tp) > 0 else 0.0,
                min_val=-500, max_val=500, step=0.5, decimals=1)
            tp_r.on_change = lambda v, _d=ptl: (
                _d.target_pos.__setitem__(0, v))
            add(LabeledWidgetEntry(x=px, y=y, label="Tgt Row:",
                                    widget=tp_r))
            y += L.item_h

            tp_c = NumberField(
                pygame.Rect(px + lc, y, w - lc, fh), self.ctx,
                value=float(tp[1]) if len(tp) > 1 else 0.0,
                min_val=-500, max_val=500, step=0.5, decimals=1)
            tp_c.on_change = lambda v, _d=ptl: (
                _d.target_pos.__setitem__(1, v))
            add(LabeledWidgetEntry(x=px, y=y, label="Tgt Col:",
                                    widget=tp_c))
            y += L.item_h

            exit_dirs = ["up", "down", "left", "right"]
            exit_val = ptl.exit_direction
            exit_idx = (exit_dirs.index(exit_val)
                        if exit_val in exit_dirs else 0)
            exit_dd = Dropdown(
                pygame.Rect(px + lc, y, w - lc, fh),
                options=exit_dirs, selected=exit_idx)
            exit_dd.on_change = (
                lambda i, v, _d=ptl: setattr(_d, "exit_direction", v))
            add(LabeledWidgetEntry(x=px, y=y, label="Exit Dir:",
                                    widget=exit_dd))
            y += L.item_h

            # Portal tiles (read-only display)
            tile_str = ", ".join(
                f"[{t[0]},{t[1]}]" for t in ptl.tiles if len(t) >= 2)
            add(KVEntry(x=px, y=y, label="Tiles:",
                         value=tile_str[:40] if tile_str else "(none)"))
            y += L.s(32)

        # ── Extras (unknown/game-specific components) ─────
        if ent.extras:
            add(SectionEntry(x=px, y=y, text="Extra Data", w=w))
            y += L.header_h
            for key, val in sorted(ent.extras.items()):
                val_str = str(val)
                if len(val_str) > 40:
                    val_str = val_str[:37] + "..."
                add(KVEntry(x=px, y=y, label=f"  {key}:",
                             value=val_str))
                y += L.s(18)
            y += L.pad_md

        # ── Action buttons ─────────────────────────────────
        y += L.pad_lg
        add(ActionButtonEntry(x=px, y=y, label="Add Component...", w=w))
        y += L.s(30)
        add(DeleteButtonEntry(x=px, y=y, label="Delete Entity", w=w))
        y += L.s(30)

        self._scroll.content_height = y - L.rp_content_y

    # ── Tile tab builders ────────────────────────────────────────

    def _rebuild_tile_widgets(self, surface: pygame.Surface):
        """Rebuild the tile-tab widget list for the currently selected tile."""
        self._tile_widgets.clear()
        L = Layout
        px = L.rp_x + L.pad_md
        w = L.inspector_w - 3 * L.pad_md
        st = self.state
        tid = st.selected_tile
        td = tile_def(tid)
        y = L.rp_content_y + L.pad_md
        add = self._tile_widgets.append

        if td is None:
            add(LabelEntry(x=px, y=y, text="No tile selected",
                           color=Theme.TEXT_DIM))
            self._scroll.content_height = L.s(60)
            return

        # ── Header ─────────────────────────────────────────
        add(LabelEntry(x=px, y=y, text=f"TILE: {td.name[:22]}",
                        color=Theme.ACCENT))
        y += L.s(24)

        # ── Basic info ─────────────────────────────────────
        add(SectionEntry(x=px, y=y, text="Properties", w=w))
        y += L.header_h
        add(KVEntry(x=px, y=y, label="ID:", value=str(td.id)))
        y += L.s(20)
        add(KVEntry(x=px, y=y, label="Type:", value=td.type.value))
        y += L.s(20)
        add(KVEntry(x=px, y=y, label="Category:", value=td.category))
        y += L.s(20)

        # Flags
        flag_bits = []
        if td.solid:
            flag_bits.append("solid")
        if td.wall:
            flag_bits.append("wall")
        if td.transparent:
            flag_bits.append("transp")
        if td.half_wall:
            flag_bits.append("half")
        if td.platform:
            flag_bits.append("platform")
        if td.liquid:
            flag_bits.append("liquid")
        if td.farmland:
            flag_bits.append("farmland")
        flags_str = ", ".join(flag_bits) if flag_bits else "(none)"
        add(KVEntry(x=px, y=y, label="Flags:", value=flags_str))
        y += L.s(20)
        add(KVEntry(x=px, y=y, label="Height:",
                     value=f"{td.height_scale:.2f}"))
        y += L.s(20)
        if td.sound:
            add(KVEntry(x=px, y=y, label="Sound:", value=td.sound))
            y += L.s(20)

        # ── Cell rotation (hovered tile) ───────────────────
        _DIR_LABELS = ("N", "E", "S", "W")
        if st.hover_tile:
            hr, hc = st.hover_tile
            if 0 <= hr < st.map_h and 0 <= hc < st.map_w:
                cell_rot = 0
                if (st.rotations and 0 <= hr < len(st.rotations)
                        and 0 <= hc < len(st.rotations[0])):
                    cell_rot = st.rotations[hr][hc]
                add(KVEntry(x=px, y=y, label="Cell Rot:",
                             value=f"{_DIR_LABELS[cell_rot % 4]} ({cell_rot})"))
                y += L.s(20)
                # Show resolved textures for this rotation
                if td.has_directional_textures():
                    for face in ("north", "south", "east", "west"):
                        tex = td.tex_for_face(face, cell_rot)
                        if tex != td.wall_tex():
                            add(KVEntry(x=px, y=y, label=f"  {face}:",
                                         value=tex))
                            y += L.s(18)
        add(KVEntry(x=px, y=y, label="Pending:",
                     value=_DIR_LABELS[st.pending_rotation % 4]))
        y += L.item_h

        # ── Textures ──────────────────────────────────────
        add(SectionEntry(x=px, y=y, text="Textures", w=w))
        y += L.header_h
        add(KVEntry(x=px, y=y, label="Default:", value=td.wall_tex()))
        y += L.s(20)
        if td.texture_front:
            add(KVEntry(x=px, y=y, label="Front:", value=td.texture_front))
            y += L.s(20)
        if td.texture_back:
            add(KVEntry(x=px, y=y, label="Back:", value=td.texture_back))
            y += L.s(20)
        y += L.pad_md

        # ── Texture preview ────────────────────────────────
        tex_sz = L.s(64)
        if self._atlas:
            add(TexPreviewEntry(x=px, y=y, tile_id=td.id, size=tex_sz))
            y += tex_sz + L.pad_md

        # ── Tile colour swatch ─────────────────────────────
        swatch_sz = L.s(18)
        colour = TILE_COLORS.get(tid, (128, 128, 128))
        add(ColorSwatchEntry(x=px, y=y, color=colour, size=swatch_sz))
        add(KVEntry(x=px + swatch_sz + L.pad_md, y=y, label="Color:",
                     value=f"({colour[0]}, {colour[1]}, {colour[2]})"))
        y += L.item_h

        self._scroll.content_height = y - L.rp_content_y

    # ── Drawing ──────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface,
             font: pygame.font.Font, font_sm: pygame.font.Font,
             dt: float = 0.016):
        L = Layout
        panel_x = L.rp_x

        # Background + border drawn by EditorChrome

        # ── Tab bar ──────────────────────────────────────────
        self._draw_tab_bar(surface, font_sm, panel_x, L.rp_tabs_y,
                           L.inspector_w, L.rp_tabs_h)

        # ── Content area (below tabs) ───────────────────────
        content_y = L.rp_content_y
        content_h = L.rp_content_h
        self._scroll.rect = pygame.Rect(panel_x, content_y,
                                        L.inspector_w, content_h)

        st = self.state

        # Detect panel geometry change (window resize / maximize)
        geometry_changed = (panel_x != self._last_panel_x)
        if geometry_changed:
            self._last_panel_x = panel_x
        # Detect tab switch
        tab_changed = (self._tab != self._last_tab)
        if tab_changed:
            self._last_tab = self._tab

        if self._tab == TAB_ZONE:
            # Rebuild zone widgets if selection or geometry changed
            if (st.selected_entity != self._last_entity_idx
                    or geometry_changed or tab_changed):
                self._last_entity_idx = st.selected_entity
                self._rebuild_widgets(surface)
            widgets = self._widgets
        elif self._tab == TAB_ENTITY:
            # Rebuild entity widgets if selected entity changed
            if (st.selected_entity != self._last_entity_tab_idx
                    or geometry_changed or tab_changed):
                self._last_entity_tab_idx = st.selected_entity
                self._rebuild_entity_widgets_list(surface)
            widgets = self._entity_widgets
        else:
            # Rebuild tile widgets if selected tile or geometry changed
            if (st.selected_tile != self._last_tile_id
                    or geometry_changed or tab_changed):
                self._last_tile_id = st.selected_tile
                self._rebuild_tile_widgets(surface)
            widgets = self._tile_widgets

        offset = int(self._scroll.scroll_y)

        # Clamp scroll after potential resize (visible area may have grown)
        max_scroll = self._scroll.max_scroll
        if self._scroll.scroll_y > max_scroll:
            self._scroll.scroll_y = max_scroll
            offset = int(max_scroll)

        surface.set_clip(pygame.Rect(panel_x, content_y,
                                     L.inspector_w, content_h))

        for entry in widgets:
            if isinstance(entry, LabelEntry):
                draw_text(surface, entry.text, entry.x,
                          entry.y - offset, entry.color, font)

            elif isinstance(entry, SectionEntry):
                draw_section_header(surface, entry.text, entry.x,
                                    entry.y - offset, entry.w, font_sm)

            elif isinstance(entry, KVEntry):
                draw_text(surface, entry.label, entry.x,
                          entry.y - offset, Theme.TEXT_DIM, font_sm)
                draw_text(surface, entry.value,
                          entry.x + L.label_col, entry.y - offset,
                          Theme.TEXT, font_sm)

            elif isinstance(entry, LabeledWidgetEntry):
                draw_label(surface, entry.label, entry.x,
                           entry.y - offset, font_sm)
                w = entry.widget
                orig_y = w.rect.y
                w.rect.y -= offset
                try:
                    if hasattr(w, 'draw'):
                        if isinstance(w, (NumberField, TextField, ColorField)):
                            w.draw(surface, font_sm, dt)
                        else:
                            w.draw(surface, font_sm)
                finally:
                    w.rect.y = orig_y

            elif isinstance(entry, WidgetEntry):
                w = entry.widget
                orig_y = w.rect.y
                w.rect.y -= offset
                try:
                    w.draw(surface, font_sm)
                finally:
                    w.rect.y = orig_y

            elif isinstance(entry, EntityRowEntry):
                ry = entry.y - offset
                is_sel = (entry.idx == st.selected_entity)
                row_rect = pygame.Rect(entry.x, ry,
                                       L.inspector_w - L.s(20), L.s(20))
                hov = row_rect.collidepoint(pygame.mouse.get_pos())
                draw_item_row(surface, row_rect, hovered=hov,
                              selected=is_sel, br=L.border_r)
                draw_text(surface,
                          f"{entry.prefab[:8]}: {entry.name[:14]}",
                          entry.x + L.pad_sm, ry + L.pad_sm,
                          Theme.TEXT, font_sm)

            elif isinstance(entry, DeleteButtonEntry):
                rect = pygame.Rect(entry.x, entry.y - offset,
                                   entry.w, L.btn_h)
                hov = rect.collidepoint(pygame.mouse.get_pos())
                bg = (100, 40, 40) if hov else (70, 30, 30)
                pygame.draw.rect(surface, bg, rect,
                                 border_radius=L.border_r)
                pygame.draw.rect(surface, Theme.DANGER, rect, 1,
                                 border_radius=L.border_r)
                draw_text_centered(surface, entry.label, rect,
                                   Theme.DANGER, font_sm)

            elif isinstance(entry, ActionButtonEntry):
                rect = pygame.Rect(entry.x, entry.y - offset,
                                   entry.w, L.btn_h)
                hov = rect.collidepoint(pygame.mouse.get_pos())
                bg = Theme.BTN_HOVER if hov else Theme.PANEL_LITE
                pygame.draw.rect(surface, bg, rect,
                                 border_radius=L.border_r)
                pygame.draw.rect(surface, Theme.BORDER, rect, 1,
                                 border_radius=L.border_r)
                draw_text_centered(surface, entry.label, rect,
                                   Theme.TEXT, font_sm)

            elif isinstance(entry, TexPreviewEntry):
                rect = pygame.Rect(entry.x, entry.y - offset,
                                   entry.size, entry.size)
                pygame.draw.rect(surface, (30, 30, 35), rect)
                if self._atlas:
                    try:
                        tex_surf = self._atlas.get(entry.tile_id)
                        thumb = pygame.transform.scale(
                            tex_surf, (entry.size, entry.size))
                        surface.blit(thumb, rect.topleft)
                    except (KeyError, AttributeError, pygame.error):
                        pass
                pygame.draw.rect(surface, Theme.BORDER, rect, 1)

            elif isinstance(entry, ColorSwatchEntry):
                rect = pygame.Rect(entry.x, entry.y - offset,
                                   entry.size, entry.size)
                pygame.draw.rect(surface, entry.color, rect)
                pygame.draw.rect(surface, Theme.BORDER, rect, 1)

        surface.set_clip(None)

        # Draw scrollbar
        self._scroll.draw_scrollbar(surface)

        # Draw any open dropdowns ON TOP of everything
        for entry in widgets:
            if isinstance(entry, LabeledWidgetEntry):
                w = entry.widget
                if isinstance(w, Dropdown) and w.is_open:
                    orig_y = w.rect.y
                    w.rect.y -= offset
                    try:
                        w.draw_dropdown(surface, font_sm)
                    finally:
                        w.rect.y = orig_y

    def _draw_tab_bar(self, surface: pygame.Surface,
                      font: pygame.font.Font,
                      x: int, y: int, w: int, h: int):
        """Draw the Zone / Tile / Entity tab bar at the top of the inspector."""
        tabs = [TAB_ZONE, TAB_TILE, TAB_ENTITY]
        n = len(tabs)
        gap = 2
        tab_w = (w - gap * (n - 1)) // n
        mouse_pos = pygame.mouse.get_pos()

        for i, tab_id in enumerate(tabs):
            tx = x + i * (tab_w + gap)
            rect = pygame.Rect(tx, y, tab_w, h)
            active = (self._tab == tab_id)
            hov = rect.collidepoint(mouse_pos)
            draw_tab_button(surface, rect, _TAB_LABELS[tab_id], font,
                            selected=active, hovered=hov, border_r=2)

    # ── Event handling ───────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event,
                     surface: pygame.Surface) -> str | None:
        """Returns action string or None.
        Actions: 'delete_entity', 'add_component', 'select_entity:N'
        """
        sw, sh = surface.get_size()
        L = Layout
        panel_x = L.rp_x

        # Only handle events in inspector area
        if event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP,
                          pygame.MOUSEMOTION, pygame.MOUSEWHEEL):
            pos = getattr(event, 'pos', pygame.mouse.get_pos())
            if pos[0] < panel_x:
                return None

        # ── Tab clicks ───────────────────────────────────────
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            tabs = [TAB_ZONE, TAB_TILE, TAB_ENTITY]
            tab_w = L.inspector_w // len(tabs)
            mx, my = event.pos
            if L.rp_tabs_y <= my < L.rp_tabs_y + L.rp_tabs_h and mx >= panel_x:
                idx = (mx - panel_x) // tab_w
                if 0 <= idx < len(tabs):
                    new_tab = tabs[idx]
                    if new_tab != self._tab:
                        self._tab = new_tab
                        self._scroll.scroll_y = 0.0
                    return None

        # Scrolling
        if self._scroll.handle_event(event):
            return None

        offset = int(self._scroll.scroll_y)
        st = self.state

        # --- Zone tab events ---
        if self._tab == TAB_ZONE:
            return self._handle_zone_events(event, offset, st, panel_x)

        # --- Entity tab events ---
        if self._tab == TAB_ENTITY:
            return self._handle_entity_events(event, offset, st, panel_x)

        # --- Tile tab events ---
        # (read-only for now — no interactive widgets)
        return None

    def _handle_zone_events(self, event, offset, st, panel_x):
        """Process events for the zone/entity tab."""
        result = self._dispatch_widget_events(
            self._widgets, event, offset, st)
        if result is not None:
            return result
        # Entity row clicks (zone tab only — shows entity list)
        L = Layout
        for entry in self._widgets:
            if isinstance(entry, EntityRowEntry):
                if (event.type == pygame.MOUSEBUTTONDOWN
                        and event.button == 1):
                    ry = entry.y - offset
                    row_rect = pygame.Rect(entry.x, ry,
                                           L.inspector_w - L.s(20),
                                           L.s(20))
                    if row_rect.collidepoint(event.pos):
                        st.selected_entity = entry.idx
                        st.tool = Tool.SELECT
                        self.set_tab(TAB_ENTITY)
                        return f"select_entity:{entry.idx}"
        return None

    def _handle_entity_events(self, event, offset, st, panel_x):
        """Process events for the entity tab (interactive entity widgets)."""
        return self._dispatch_widget_events(
            self._entity_widgets, event, offset, st)

    def _dispatch_widget_events(self, widgets, event, offset, st):
        """Shared event dispatch for a scrollable widget list.

        Returns an action string if a button was pressed, or *None*.
        Handles LabeledWidgetEntry, WidgetEntry, DeleteButtonEntry,
        ActionButtonEntry, and deferred keyboard forwarding.
        """
        L = Layout
        for entry in widgets:
            if isinstance(entry, LabeledWidgetEntry):
                w = entry.widget
                orig_y = w.rect.y
                w.rect.y -= offset
                try:
                    result = w.handle_event(event)
                finally:
                    w.rect.y = orig_y
                if result:
                    st.dirty = True
                    return None

            elif isinstance(entry, WidgetEntry):
                w = entry.widget
                orig_y = w.rect.y
                w.rect.y -= offset
                try:
                    result = w.handle_event(event)
                finally:
                    w.rect.y = orig_y
                if result:
                    st.dirty = True
                    return None

            elif isinstance(entry, DeleteButtonEntry):
                if (event.type == pygame.MOUSEBUTTONDOWN
                        and event.button == 1):
                    rect = pygame.Rect(entry.x, entry.y - offset,
                                       entry.w, L.btn_h)
                    if rect.collidepoint(event.pos):
                        return "delete_entity"

            elif isinstance(entry, ActionButtonEntry):
                if (event.type == pygame.MOUSEBUTTONDOWN
                        and event.button == 1):
                    rect = pygame.Rect(entry.x, entry.y - offset,
                                       entry.w, L.btn_h)
                    if rect.collidepoint(event.pos):
                        return "add_component"

        # Keyboard events go to focused widget regardless of position
        if event.type == pygame.KEYDOWN and self.ctx.any_focused():
            for entry in widgets:
                if isinstance(entry, LabeledWidgetEntry):
                    w = entry.widget
                    orig_y = w.rect.y
                    w.rect.y -= offset
                    try:
                        w.handle_event(event)
                    finally:
                        w.rect.y = orig_y

        return None

    def force_rebuild(self):
        """Force widget rebuild on next draw."""
        self._last_entity_idx = -2
        self._last_entity_tab_idx = -2
        self._last_tile_id = "__invalid__"
        self._last_tab = ""
        self._loaded_data = False
