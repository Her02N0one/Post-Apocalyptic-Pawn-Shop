"""editor/actions.py — Action dispatch tables for the editor.

Provides ``ActionsMixin``, mixed into ``EditorApp`` so the dispatch
tables and their handlers live in a dedicated module instead of
bloating app.py.
"""

from __future__ import annotations

from editor.state import Tool

# Valid panel mode identifiers (same set used by app.py)
PANEL_MODES = frozenset(
    {"tiles", "entities", "textures", "portals", "templates", "zones"}
)


class ActionsMixin:
    """Action dispatch — exact-match and prefix:value handlers."""

    # ── Dispatch entry-point ────────────────────────────────────

    def _dispatch_action(self, action: str):
        """Route any action string from menus, inspector, or modals.

        Uses a dispatch table for exact-match actions and a prefix
        table for parameterised ``prefix:value`` actions so new
        actions can be added in one place.
        """
        handler = self._ACTION_TABLE.get(action)
        if handler is not None:
            handler(self)
            return

        if ":" in action:
            prefix, value = action.split(":", 1)
            prefix_handler = self._PREFIX_TABLE.get(prefix)
            if prefix_handler is not None:
                prefix_handler(self, value)

    # ── Exact-match handlers ────────────────────────────────────

    def _act_save(self):
        if not self.state.zone_name:
            self._act_save_as()
            return
        self.state.save_zone()

    def _act_quit(self):
        self._running = False

    def _act_load(self):
        from editor.modals import ZonePickerModal
        self.modals.open(ZonePickerModal(self.modals))

    def _act_new(self):
        from editor.modals import NewZoneModal
        self.modals.open(NewZoneModal(self.modals, self._on_new_zone))

    def _on_new_zone(self, name: str, width: int, height: int):
        self.state.new_zone(name, width, height)
        self.inspector.force_rebuild()

    def _act_save_as(self):
        from editor.modals import TextInputModal
        def _on_name(name: str):
            self.state.zone_name = name
            self.state.save_zone()
            self.inspector.force_rebuild()
        default = self.state.zone_name or "untitled"
        self.modals.open(
            TextInputModal(self.modals, "Save zone as:",
                           default, _on_name))

    def _act_rename(self):
        from editor.modals import TextInputModal
        def _on_name(name: str):
            old = self.state.zone_name
            self.state.rename_zone(name)
            self.inspector.force_rebuild()
        self.modals.open(
            TextInputModal(self.modals, "Rename zone to:",
                           self.state.zone_name, _on_name))

    def _act_loot(self):
        self.loot_editor.open()

    def _act_templates(self):
        self.template_editor.open()

    def _act_forge(self):
        self.forge.open()

    def _act_export_mpz(self):
        self._export_current_mpz()

    def _act_export_all_mpz(self):
        self._export_all_mpz()

    def _act_import_texture(self):
        from systems.textures import browse_and_import
        dest = browse_and_import()
        if dest:
            from core.tiles import TILE_REGISTRY as _reg
            key = dest.stem
            for td in _reg.values():
                tk = td.texture_key or td.id
                if tk == key:
                    self.atlas.invalidate(td.id)
            self.state.toast(f"Imported texture: {dest.name}")

    def _act_add_component(self):
        from editor.modals import AddComponentModal
        st = self.state
        if 0 <= st.selected_entity < len(st.entities):
            self.modals.open(AddComponentModal(self.modals))

    def _act_toggle_grid(self):
        self.state.show_grid = not self.state.show_grid

    def _act_toggle_minimap(self):
        self.state.show_minimap = not self.state.show_minimap

    def _act_fp_preview(self):
        self._do_fp_preview()

    def _act_fp_edit(self):
        self._do_fp_edit()

    def _act_brush_inc(self):
        self.state.brush_size = min(9, self.state.brush_size + 1)

    def _act_brush_dec(self):
        self.state.brush_size = max(1, self.state.brush_size - 1)

    _ACTION_TABLE: dict[str, callable] = {
        "save":            _act_save,
        "quit":            _act_quit,
        "undo":            lambda self: self._do_undo(),
        "redo":            lambda self: self._do_redo(),
        "delete_entity":   lambda self: self._do_delete_entity(),
        "load":            _act_load,
        "new":             _act_new,
        "loot":            _act_loot,
        "templates":       _act_templates,
        "forge":           _act_forge,
        "save_as":         _act_save_as,
        "rename":          _act_rename,
        "export_mpz":      _act_export_mpz,
        "export_all_mpz":  _act_export_all_mpz,
        "import_texture":  _act_import_texture,
        "add_component":   _act_add_component,
        "toggle_grid":     _act_toggle_grid,
        "toggle_minimap":  _act_toggle_minimap,
        "fp_preview":      _act_fp_preview,
        "fp_edit":         _act_fp_edit,
        "brush_inc":       _act_brush_inc,
        "brush_dec":       _act_brush_dec,
    }

    # ── Prefix handlers (prefix:value) ──────────────────────────

    def _pfx_select_entity(self, value: str):
        try:
            idx = int(value)
        except ValueError:
            return
        self.state.selected_entity = idx
        self.state.tool = Tool.SELECT
        self.inspector.set_tab("entity")
        self.inspector.force_rebuild()

    def _pfx_panel(self, mode: str):
        if mode in PANEL_MODES:
            self.menu_bar.panel_mode = mode

    def _pfx_copy_tex(self, key: str):
        self.state.toast(f"Texture key: {key}")

    def _pfx_select_template(self, fname: str):
        self.state.toast(f"Template: {fname} (stamp placement TBD)")

    def _pfx_select_prefab(self, name: str):
        self.state.pending_prefab = name
        self.state.tool = Tool.SELECT
        self.state.toast(f"Prefab: {name} \u2014 click canvas to place")

    def _pfx_select_forge(self, fid: str):
        self.state.pending_prefab = f"forge:{fid}"
        self.state.tool = Tool.SELECT
        self.state.toast(f"Forge: {fid} \u2014 click canvas to place")

    def _pfx_tool(self, tool_name: str):
        st = self.state
        if hasattr(Tool, tool_name.upper()):
            st.tool = getattr(Tool, tool_name.upper())
        else:
            st.tool = tool_name

    _PREFIX_TABLE: dict[str, callable] = {
        "select_entity":   _pfx_select_entity,
        "panel":           _pfx_panel,
        "copy_tex":        _pfx_copy_tex,
        "select_template": _pfx_select_template,
        "select_prefab":   _pfx_select_prefab,
        "select_forge":    _pfx_select_forge,
        "tool":            _pfx_tool,
    }
