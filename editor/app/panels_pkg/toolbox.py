"""editor/app/panels_pkg/toolbox.py — Left-panel toolbox & palettes."""

from __future__ import annotations

import imgui

from core.tiles import TILE_COLORS
from core.presets import PRESET_REGISTRY
from core.entity_defs import entity_palette as _entity_palette, get_entity_def
from editor.view_3d import (
    TOOLS, UTIL_TOOLS, TOOL_LABELS, TOOL_COLORS,
    TOOL_HINTS, SNAP_Y_OPTIONS, _ensure_palette,
    MODES, MODE_LABELS, MODE_ICONS, MODE_COLORS,
    MODE_DESCRIPTIONS, MODE_TOOLS, MODE_SELECTION_TARGET,
)


class ToolboxMixin:
    """Left panel: mode buttons, sub-tools, snap, palettes, controls."""

    def _left_panel(self) -> None:  # noqa: C901
        from editor.app.constants import MENU_BAR_H, STATE_BAR_H, STATUS_BAR_H
        win_w, win_h = self.win_size
        imgui.set_next_window_position(0, MENU_BAR_H + STATE_BAR_H)
        imgui.set_next_window_size(self.left_panel_w, win_h - MENU_BAR_H - STATE_BAR_H - STATUS_BAR_H)
        flags = (imgui.WINDOW_NO_MOVE | imgui.WINDOW_NO_RESIZE
                 | imgui.WINDOW_NO_COLLAPSE | imgui.WINDOW_NO_SAVED_SETTINGS
                 | imgui.WINDOW_ALWAYS_VERTICAL_SCROLLBAR)
        imgui.begin("Toolbox", flags=flags)

        if not self.editor_3d:
            imgui.text_colored("No zone loaded", 0.5, 0.5, 0.5, 1.0)
            imgui.end()
            return

        ed = self.editor_3d
        spacing_x = imgui.get_style().item_spacing.x

        self._draw_tool_buttons(ed, spacing_x)
        self._draw_snap_buttons(ed, spacing_x)
        self._draw_brush_or_preset(ed)
        self._draw_controls_section(ed)
        self._draw_selection_info(ed)

        imgui.end()

    def _draw_tool_buttons(self, ed, spacing_x: float) -> None:
        """Draw 4 primary mode buttons + mode-specific sub-tools."""
        self._section_header("\u2581 MODE", 0.65, 0.75, 0.95, pad_top=False)
        avail_w = imgui.get_content_region_available()[0]

        # ── 4 primary mode buttons (2x2 grid) ────────────────────
        n_cols = 2
        btn_w = (avail_w - (n_cols - 1) * spacing_x) / n_cols
        _mode_actions_lp = [
            (MODES[0], "mode.arch"), (MODES[1], "mode.surface"),
            (MODES[2], "mode.props"), (MODES[3], "mode.logic"),
        ]
        active_mode = getattr(ed, 'mode', MODES[0])

        for i, (mode, m_action) in enumerate(_mode_actions_lp):
            if i % n_cols != 0:
                imgui.same_line()
            is_active = active_mode == mode
            r, g, b = [v / 255.0 for v in MODE_COLORS[mode]]
            if is_active:
                imgui.push_style_color(imgui.COLOR_BUTTON, r * 0.45, g * 0.45, b * 0.45, 0.90)
                imgui.push_style_color(imgui.COLOR_BUTTON_HOVERED, r * 0.55, g * 0.55, b * 0.55, 0.95)
                imgui.push_style_color(imgui.COLOR_BUTTON_ACTIVE, r * 0.6, g * 0.6, b * 0.6, 1.0)
                imgui.push_style_color(imgui.COLOR_TEXT, 1.0, 1.0, 1.0, 1.0)
            else:
                imgui.push_style_color(imgui.COLOR_TEXT, 0.60, 0.60, 0.65, 1.0)
            _fk = self._kb_label(m_action)
            label = MODE_LABELS[mode]
            if imgui.button(f"{_fk} {label}##{mode}", btn_w, 30):
                self._switch_mode(ed, mode)
            if is_active:
                imgui.pop_style_color(4)
            else:
                imgui.pop_style_color(1)

        # ── Mode description ──────────────────────────────────────
        imgui.text_colored(MODE_DESCRIPTIONS.get(active_mode, ""), 0.5, 0.5, 0.55, 1.0)

        # ── Sub-tools for active mode ─────────────────────────────
        tools = MODE_TOOLS.get(active_mode, ())
        if len(tools) > 1:
            imgui.spacing()
            imgui.text_colored("\u2581 SUB-TOOL", 0.55, 0.65, 0.80, 1.0)
            sub_w = avail_w
            for ti, tool in enumerate(tools):
                is_tool_active = ed.tool == tool
                r2, g2, b2 = [c / 255.0 for c in TOOL_COLORS.get(tool, (128, 128, 128))]
                if is_tool_active:
                    imgui.push_style_color(imgui.COLOR_BUTTON, r2 * 0.45, g2 * 0.45, b2 * 0.45, 0.90)
                    imgui.push_style_color(imgui.COLOR_BUTTON_HOVERED, r2 * 0.55, g2 * 0.55, b2 * 0.55, 0.95)
                    imgui.push_style_color(imgui.COLOR_BUTTON_ACTIVE, r2 * 0.6, g2 * 0.6, b2 * 0.6, 1.0)
                    imgui.push_style_color(imgui.COLOR_TEXT, 1.0, 1.0, 1.0, 1.0)
                else:
                    imgui.push_style_color(imgui.COLOR_TEXT, 0.65, 0.65, 0.70, 1.0)
                tool_label = TOOL_LABELS.get(tool, tool.upper())
                _stk = self._kb_label(f"subtool.{ti + 1}")
                if imgui.button(f"{_stk} {tool_label}##{tool}", sub_w, 24):
                    self._switch_tool(ed, tool)
                if is_tool_active:
                    imgui.pop_style_color(4)
                else:
                    imgui.pop_style_color(1)

        # ── Cross-cutting utility tools ───────────────────────────
        imgui.spacing()
        imgui.separator()
        imgui.text_colored("\u2581 UTILITY", 0.50, 0.55, 0.50, 1.0)
        _util_general = [
            ("select", "tool.select"), ("stamp", "tool.stamp"),
        ]
        n_util_cols = 2
        btn_w2 = (avail_w - spacing_x) / float(n_util_cols)
        for i, (tool_name, kb_action) in enumerate(_util_general):
            if i % n_util_cols != 0:
                imgui.same_line()
            is_active = ed.tool == tool_name
            r3, g3, b3 = [c / 255.0 for c in TOOL_COLORS.get(tool_name, (128, 128, 128))]
            if is_active:
                imgui.push_style_color(imgui.COLOR_BUTTON, r3 * 0.45, g3 * 0.45, b3 * 0.45, 0.90)
                imgui.push_style_color(imgui.COLOR_BUTTON_HOVERED, r3 * 0.55, g3 * 0.55, b3 * 0.55, 0.95)
                imgui.push_style_color(imgui.COLOR_BUTTON_ACTIVE, r3 * 0.6, g3 * 0.6, b3 * 0.6, 1.0)
                imgui.push_style_color(imgui.COLOR_TEXT, 1.0, 1.0, 1.0, 1.0)
            else:
                imgui.push_style_color(imgui.COLOR_TEXT, 0.55, 0.55, 0.60, 1.0)
            tool_label = TOOL_LABELS.get(tool_name, tool_name.upper())
            _utk = self._kb_label(kb_action)
            if imgui.button(f"{_utk} {tool_label}##{tool_name}", btn_w2, 24):
                if ed.tool == tool_name:
                    if tool_name == "select":
                        ed._sel_cancel()
                    ed._leave_tool(ed.tool)
                    ed.tool = ed._prev_tool
                else:
                    if ed.tool in TOOLS:
                        ed._prev_tool = ed.tool
                    if ed.tool == "select":
                        ed._sel_cancel()
                    ed._leave_tool(ed.tool)
                    ed.tool = tool_name
            if is_active:
                imgui.pop_style_color(4)
            else:
                imgui.pop_style_color(1)

    def _switch_mode(self, ed, mode: str) -> None:
        """Switch to a primary editor mode and activate its first tool."""
        from editor.view_3d.constants import MODE_TOOLS as MT, MODES as _MODES, MODE_LABELS
        if ed.tool == "select":
            ed._sel_cancel()
        ed._leave_tool(ed.tool)
        ed.mode = mode
        sub_tools = MT.get(mode, ())
        if sub_tools:
            ed.tool = sub_tools[0]
            ed._prev_tool = sub_tools[0]
        ed._flash(f"{MODE_LABELS.get(mode, mode)}", 0.8, (0.85, 0.9, 1.0, 1.0))

    def _switch_tool(self, ed, tool: str) -> None:
        """Switch to a sub-tool within the current mode."""
        if ed.tool == "select":
            ed._sel_cancel()
        ed._leave_tool(ed.tool)
        ed.tool = tool
        ed._prev_tool = tool
        from editor.view_3d.constants import TOOL_LABELS
        ed._flash(f"{TOOL_LABELS.get(tool, tool)}", 0.6, (0.85, 0.9, 1.0, 1.0))

    def _draw_snap_buttons(self, ed, spacing_x: float) -> None:
        self._section_header("\u2581 SNAP", 0.55, 0.75, 0.60)
        avail_w = imgui.get_content_region_available()[0]
        n_snap = len(SNAP_Y_OPTIONS)
        snap_btn_w = (avail_w - (n_snap - 1) * spacing_x) / n_snap
        for i, snap in enumerate(SNAP_Y_OPTIONS):
            if i > 0:
                imgui.same_line()
            is_sel = abs(ed.snap_y - snap) < 0.001
            if is_sel:
                imgui.push_style_color(imgui.COLOR_BUTTON, 0.22, 0.55, 0.35, 1.0)
                imgui.push_style_color(imgui.COLOR_BUTTON_HOVERED, 0.28, 0.65, 0.42, 1.0)
                imgui.push_style_color(imgui.COLOR_TEXT, 1.0, 1.0, 1.0, 1.0)
            if imgui.button(f"{self._SNAP_LABELS[i]}##snap{i}", snap_btn_w, 22):
                ed.snap_y = snap
                ed.snap_idx = i
            if is_sel:
                imgui.pop_style_color(3)

    def _draw_brush_or_preset(self, ed) -> None:
        """Draw texture palette or preset list depending on active tool."""
        tool_name = ed.tool
        uses_texture = tool_name in ("paint", "segment", "select")
        uses_preset = tool_name == "stamp"
        uses_entity = tool_name == "entity"

        if uses_texture:
            self._draw_texture_palette(ed)
        elif uses_preset:
            self._draw_preset_palette(ed)
        elif uses_entity:
            self._draw_entity_palette(ed)

    def _draw_texture_palette(self, ed) -> None:
        self._section_header("\u2581 BRUSH", 0.75, 0.55, 0.85)
        palette = _ensure_palette()
        cur_tex = ed.current_texture
        cur_idx = ed.tex_idx

        tc = TILE_COLORS.get(cur_tex, (128, 128, 128))
        r0, g0, b0 = tc[0] / 255.0, tc[1] / 255.0, tc[2] / 255.0
        imgui.color_button("##curtex_big", r0, g0, b0, 1.0, 0, 20, 20)
        imgui.same_line()
        imgui.text_colored(cur_tex, 0.95, 0.90, 0.75, 1.0)
        imgui.same_line()
        imgui.text_disabled(f"({cur_idx + 1}/{len(palette)})")

        remaining = imgui.get_content_region_available()[1]
        list_h = max(80, min(220, remaining - 200))
        child_w = imgui.get_content_region_available()[0]
        imgui.begin_child("##texlist", child_w, list_h, border=True)
        for pi, pname in enumerate(palette):
            tc2 = TILE_COLORS.get(pname, (128, 128, 128))
            pr, pg, pb = tc2[0] / 255.0, tc2[1] / 255.0, tc2[2] / 255.0
            imgui.color_button(f"##p{pi}", pr, pg, pb, 1.0, 0, 12, 12)
            imgui.same_line()
            is_sel = pi == cur_idx
            clicked, _ = imgui.selectable(f"{pname}##pal{pi}", is_sel)
            if clicked:
                ed.tex_idx = pi
                ed.current_texture = pname
            if is_sel and (self.mouse_captured or imgui.is_window_appearing()):
                imgui.set_scroll_here_y(0.5)
        imgui.end_child()

    def _draw_preset_palette(self, ed) -> None:
        self._section_header("\u2581 PRESET", 0.70, 0.55, 1.0)
        pal = sorted(PRESET_REGISTRY.keys())
        preset = ed._stamp_current()
        pname = preset.name if preset else "(none)"
        pidx = ed._stamp_idx if pal else 0

        imgui.text_colored("\u25a0", 0.70, 0.55, 1.0, 1.0)
        imgui.same_line()
        imgui.text_colored(pname, 0.90, 0.80, 1.0, 1.0)
        if pal:
            imgui.same_line()
            imgui.text_disabled(f"({pidx + 1}/{len(pal)})")
        if preset and preset.category:
            imgui.text_disabled(f"  Category: {preset.category}")

        if pal:
            remaining = imgui.get_content_region_available()[1]
            list_h = max(60, min(160, remaining - 200))
            child_w = imgui.get_content_region_available()[0]
            imgui.begin_child("##presetlist", child_w, list_h, border=True)
            for pi, pid in enumerate(pal):
                p = PRESET_REGISTRY.get(pid)
                label = p.name if p else pid
                is_sel = pi == pidx
                clicked, _ = imgui.selectable(f"{label}##preset{pi}", is_sel)
                if clicked:
                    ed._stamp_idx = pi
                    ed._stamp_preset_id = pid
                if is_sel and (self.mouse_captured or imgui.is_window_appearing()):
                    imgui.set_scroll_here_y(0.5)
            imgui.end_child()
        else:
            imgui.text_colored("No presets loaded", 0.5, 0.5, 0.5, 1.0)

    def _draw_entity_palette(self, ed) -> None:
        """Draw entity type palette for the entity tool."""
        self._section_header("\u2581 ENTITY", 0.25, 0.78, 1.0)
        pal = _entity_palette()
        if not pal:
            imgui.text_colored("No entity defs loaded", 0.5, 0.5, 0.5, 1.0)
            return

        cur_type = ed._ent_current_type()
        edef = get_entity_def(cur_type)
        cur_idx = ed._ent_type_idx % len(pal) if pal else 0

        # Current entity preview
        if edef:
            r0, g0, b0 = edef.color[0] / 255.0, edef.color[1] / 255.0, edef.color[2] / 255.0
            imgui.color_button("##curent_big", r0, g0, b0, 1.0, 0, 20, 20)
            imgui.same_line()
            imgui.text_colored(edef.display_name, 0.95, 0.90, 0.75, 1.0)
            imgui.same_line()
            imgui.text_disabled(f"({cur_idx + 1}/{len(pal)})")
            imgui.text_disabled(f"  {edef.category}")
            if edef.directional:
                imgui.same_line()
                imgui.text_colored("\u27a4", 0.6, 0.8, 1.0, 1.0)
        else:
            imgui.text(cur_type)

        # Selected entity quick info
        if ed._ent_selected is not None and self.zone and self.zone.entities:
            idx = ed._ent_selected
            if 0 <= idx < len(self.zone.entities):
                ent = self.zone.entities[idx]
                imgui.spacing()
                imgui.text_colored("\u25b8 Selected", 0.3, 0.9, 1.0, 1.0)
                imgui.same_line()
                imgui.text_disabled(ent.get("type", "?"))

        # Scrollable palette list
        remaining = imgui.get_content_region_available()[1]
        list_h = max(80, min(220, remaining - 200))
        child_w = imgui.get_content_region_available()[0]
        imgui.begin_child("##entlist", child_w, list_h, border=True)
        prev_cat = None
        for pi, etype in enumerate(pal):
            ed2 = get_entity_def(etype)
            if not ed2:
                continue
            # Category separator
            if ed2.category != prev_cat:
                if prev_cat is not None:
                    imgui.separator()
                imgui.text_disabled(ed2.category.upper())
                prev_cat = ed2.category
            # Color swatch + name
            pr, pg, pb = ed2.color[0] / 255.0, ed2.color[1] / 255.0, ed2.color[2] / 255.0
            imgui.color_button(f"##e{pi}", pr, pg, pb, 1.0, 0, 12, 12)
            imgui.same_line()
            is_sel = pi == cur_idx
            clicked, _ = imgui.selectable(f"{ed2.display_name}##ent{pi}", is_sel)
            if clicked:
                ed._ent_type_idx = pi
            if is_sel and (self.mouse_captured or imgui.is_window_appearing()):
                imgui.set_scroll_here_y(0.5)
        imgui.end_child()

        # Entity count
        if self.zone:
            n = len(self.zone.entities) if self.zone.entities else 0
            imgui.text_disabled(f"{n} entities in zone")

    def _draw_controls_section(self, ed) -> None:
        hint = TOOL_HINTS.get(ed.tool, {})
        if not hint:
            return

        self._section_header("\u2581 CONTROLS", 0.55, 0.60, 0.55)
        actions_dict = hint.get("actions", {})

        # Pick context key
        if ed.tool == "select":
            if ed.selection.has_cells():
                ctx_key = "active"
            elif ed.selection.rect_in_progress:
                ctx_key = "started"
            else:
                ctx_key = "none"
        elif ed.tool == "sculpt":
            part = ed.aimed.part if ed.aimed else None
            if ed._has_selection():
                ctx_key = "selection"
            elif ed._sculpt_layer2:
                ctx_key = "layer2"
            else:
                p = {"floor2": "floor", "ceiling2": "ceiling"}.get(part, part)
                if p == "ceiling":
                    ctx_key = "ceiling"
                elif p in ("floor", "wall", "ground"):
                    ctx_key = "floor"
                else:
                    ctx_key = "none"
        else:
            ctx_key = "any"

        actions = actions_dict.get(ctx_key, actions_dict.get("any", {}))
        wrap_x = imgui.get_cursor_pos_x() + imgui.get_content_region_available()[0]

        for key, desc in actions.items():
            imgui.push_style_color(imgui.COLOR_TEXT, 0.80, 0.75, 0.50, 1.0)
            imgui.text(key)
            imgui.pop_style_color()
            imgui.same_line(72)
            imgui.push_text_wrap_pos(wrap_x)
            imgui.text(desc)
            imgui.pop_text_wrap_pos()

        extra_key = "keys_layer2" if (ed.tool == "sculpt" and ed._sculpt_layer2) else "keys"
        extra = hint.get(extra_key, hint.get("keys", ""))
        if extra:
            imgui.spacing()
            imgui.push_text_wrap_pos(wrap_x)
            imgui.text_colored(extra, 0.55, 0.55, 0.40, 1.0)
            imgui.pop_text_wrap_pos()

        # Select tool state
        if ed.tool == "select":
            imgui.spacing()
            ceil_mode = ed.selection.ceiling_mode
            mode_label = "CEILING MODE" if ceil_mode else "FLOOR MODE"
            mode_col = (0.55, 0.70, 0.90, 1.0) if ceil_mode else (0.70, 0.90, 0.55, 1.0)
            imgui.text_colored(mode_label, *mode_col)
            imgui.same_line()
            imgui.text_disabled("(X to toggle)")
            if ed.selection.has_cells():
                bounds = ed._sel_bounds()
                if bounds:
                    r1, c1, r2, c2 = bounds
                    area = (r2 - r1 + 1) * (c2 - c1 + 1)
                    imgui.text_disabled(f"\u25a1 {area} cells selected")

    def _draw_selection_info(self, ed) -> None:
        """Show current selection status (cells + objects)."""
        sel = getattr(ed, 'selection', None)
        objs = getattr(ed, 'objects', None)
        if not sel and not objs:
            return

        n_cells = sel.cell_count() if sel else 0
        n_objs = objs.selected_count() if objs else 0

        if n_cells == 0 and n_objs == 0:
            return

        self._section_header("\u2581 SELECTION", 0.70, 0.85, 0.50)

        if n_cells > 0:
            bounds = sel.bounds()
            if bounds:
                r1, c1, r2, c2 = bounds
                w = c2 - c1 + 1
                h = r2 - r1 + 1
                imgui.text_colored(
                    f"\u25a1 {n_cells} cells  ({w}\u00d7{h})",
                    0.85, 0.85, 0.50, 1.0)
            else:
                imgui.text_colored(f"\u25a1 {n_cells} cells", 0.85, 0.85, 0.50, 1.0)

            ceil_mode = ed.selection.ceiling_mode
            mode_label = "CEILING" if ceil_mode else "FLOOR"
            mode_col = (0.55, 0.70, 0.90, 1.0) if ceil_mode else (0.70, 0.90, 0.55, 1.0)
            imgui.same_line()
            imgui.text_colored(mode_label, *mode_col)

        if n_objs > 0:
            imgui.text_colored(
                f"\u25cb {n_objs} object{'s' if n_objs != 1 else ''}",
                0.50, 0.85, 0.85, 1.0)

        # Action buttons
        full_w = imgui.get_content_region_available()[0]
        btn_w = (full_w - imgui.get_style().item_spacing.x * 2) / 3
        if imgui.button("Clear##sel_clr", btn_w, 0):
            sel.clear()
            if objs:
                objs.deselect_all()
        imgui.same_line()
        if imgui.button("Ct+A##sel_all", btn_w, 0):
            zone = ed.zone
            if zone:
                sel.select_all_cells(zone.width, zone.height)
        imgui.same_line()
        if imgui.button("Del##sel_del", btn_w, 0):
            if n_objs > 0 and objs:
                objs.delete_selected()
            elif n_cells > 0:
                ed._sel_reset_cells()
