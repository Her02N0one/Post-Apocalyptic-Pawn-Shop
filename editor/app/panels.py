"""editor/app/panels.py — PanelsMixin: ImGui sidebar panels, status bar, overlays."""

from __future__ import annotations

import math

import pygame
import imgui

from core.tiles import tile_def, TILE_COLORS
from core.presets import PRESET_REGISTRY
from core.entity_defs import entity_palette as _entity_palette, get_entity_def, angle_to_label
from editor.view_3d import (
    TOOLS, UTIL_TOOLS, TOOL_LABELS, TOOL_COLORS,
    TOOL_HINTS, SNAP_Y_OPTIONS, _ensure_palette,
)
from editor.app.constants import MENU_BAR_H, STATUS_BAR_H


def _paint_target_label(part: str, face: str, is_wall_tile: bool = False) -> str:
    """Return a human-readable label describing the paint target face."""
    if face == "ground":
        return ""
    _DIR = {"north": "N", "south": "S", "east": "E", "west": "W"}
    if face in _DIR:
        d = _DIR[face]
        if part == "floor":
            return f"Floor {d} Step"
        elif part == "ceiling":
            return f"Ceil {d} Step"
        else:
            return f"{d} Wall Face"
    elif face == "top":
        if part == "floor":
            return "Floor Surface"
        elif part in ("wall", "ceiling"):
            return "Ceiling Top"
    elif face == "bot":
        if part == "ceiling":
            return "Ceiling Underside"
        elif part in ("wall", "floor"):
            return "Floor Bottom"
    return f"{part} ({face})"


class PanelsMixin:
    """ImGui sidebar panels, status bar, and overlays for :class:`ZoneEditorApp`."""

    _SNAP_LABELS = ("1/16", "1/8", "1/4", "1/2", "1")

    # ── UI entry point ────────────────────────────────────────────

    def _build_ui(self) -> None:
        self._menu_bar()
        self._left_panel()
        self._properties_panel()
        self._status_bar()
        self._draw_splitters()
        if self.show_new_zone:
            self._new_zone_dialog()
        if self.show_save_as:
            self._save_as_dialog()
        if self._show_unsaved_guard:
            self._unsaved_guard_dialog()
        if not self.mouse_captured:
            self._capture_hint()
        if self.mouse_captured and self._transient_time > 0:
            self._draw_transient_indicator()

    # ── Helpers ───────────────────────────────────────────────────

    @staticmethod
    def _section_header(label: str, r: float = 0.55, g: float = 0.65,
                        b: float = 0.85, pad_top: bool = True) -> None:
        """Draw a tinted section header with a subtle underline."""
        if pad_top:
            imgui.spacing()
        imgui.text_colored(label, r, g, b, 1.0)
        draw_list = imgui.get_window_draw_list()
        x = imgui.get_cursor_screen_pos()[0]
        y = imgui.get_cursor_screen_pos()[1] - 2
        w = imgui.get_content_region_available()[0]
        col32 = imgui.get_color_u32_rgba(r, g, b, 0.25)
        draw_list.add_line(x, y, x + w, y, col32, 1.0)
        imgui.spacing()

    # ── Draggable panel splitters ─────────────────────────────────

    def _draw_splitters(self) -> None:
        if self.mouse_captured:
            return
        win_w, win_h = self.win_size
        panel_h = win_h - MENU_BAR_H - STATUS_BAR_H
        GRIP = 8

        splitter_flags = (
            imgui.WINDOW_NO_TITLE_BAR | imgui.WINDOW_NO_RESIZE
            | imgui.WINDOW_NO_MOVE | imgui.WINDOW_NO_SCROLLBAR
            | imgui.WINDOW_NO_COLLAPSE | imgui.WINDOW_NO_SAVED_SETTINGS
            | imgui.WINDOW_NO_FOCUS_ON_APPEARING | imgui.WINDOW_NO_NAV
        )
        min_pw = 200
        max_pw = win_w // 2 - 50

        # Left splitter
        lx = self.left_panel_w - GRIP // 2
        imgui.set_next_window_position(lx, MENU_BAR_H)
        imgui.set_next_window_size(GRIP, panel_h)
        imgui.push_style_color(imgui.COLOR_WINDOW_BACKGROUND, 0, 0, 0, 0)
        imgui.push_style_color(imgui.COLOR_BORDER, 0, 0, 0, 0)
        imgui.push_style_var(imgui.STYLE_WINDOW_PADDING, (0, 0))
        imgui.begin("##LeftSplitter", flags=splitter_flags)
        imgui.invisible_button("##lsplit", GRIP, panel_h - 4)
        if imgui.is_item_active():
            mx = pygame.mouse.get_pos()[0]
            self.left_panel_w = max(min_pw, min(max_pw, mx))
            self._dragging_splitter = "left"
        elif self._dragging_splitter == "left":
            self._dragging_splitter = ""
        if imgui.is_item_hovered() or imgui.is_item_active():
            imgui.set_mouse_cursor(imgui.MOUSE_CURSOR_RESIZE_EW)
        imgui.end()
        imgui.pop_style_var()
        imgui.pop_style_color(2)

        # Right splitter
        rx = win_w - self.right_panel_w - GRIP // 2
        imgui.set_next_window_position(rx, MENU_BAR_H)
        imgui.set_next_window_size(GRIP, panel_h)
        imgui.push_style_color(imgui.COLOR_WINDOW_BACKGROUND, 0, 0, 0, 0)
        imgui.push_style_color(imgui.COLOR_BORDER, 0, 0, 0, 0)
        imgui.push_style_var(imgui.STYLE_WINDOW_PADDING, (0, 0))
        imgui.begin("##RightSplitter", flags=splitter_flags)
        imgui.invisible_button("##rsplit", GRIP, panel_h - 4)
        if imgui.is_item_active():
            mx = pygame.mouse.get_pos()[0]
            self.right_panel_w = max(min_pw, min(max_pw, win_w - mx))
            self._dragging_splitter = "right"
        elif self._dragging_splitter == "right":
            self._dragging_splitter = ""
        if imgui.is_item_hovered() or imgui.is_item_active():
            imgui.set_mouse_cursor(imgui.MOUSE_CURSOR_RESIZE_EW)
        imgui.end()
        imgui.pop_style_var()
        imgui.pop_style_color(2)

    # ── Capture hint overlay ──────────────────────────────────────

    def _capture_hint(self) -> None:
        if not self.zone:
            return
        win_w, win_h = self.win_size
        cx = (self.left_panel_w + win_w - self.right_panel_w) * 0.5
        cy = win_h * 0.5
        imgui.set_next_window_position(cx - 160, cy - 20)
        imgui.set_next_window_size(320, 0)
        flags = (imgui.WINDOW_NO_TITLE_BAR | imgui.WINDOW_NO_RESIZE
                 | imgui.WINDOW_NO_MOVE | imgui.WINDOW_ALWAYS_AUTO_RESIZE
                 | imgui.WINDOW_NO_FOCUS_ON_APPEARING | imgui.WINDOW_NO_NAV
                 | imgui.WINDOW_NO_INPUTS)
        imgui.push_style_color(imgui.COLOR_WINDOW_BACKGROUND, 0.0, 0.0, 0.0, 0.55)
        imgui.begin("##CaptureHint", flags=flags)
        imgui.text_colored("   Click viewport or Enter to edit  |  Esc = quit",
                           0.85, 0.85, 0.85, 1.0)
        imgui.end()
        imgui.pop_style_color()

    # ── Transient indicator ───────────────────────────────────────

    def _draw_transient_indicator(self) -> None:
        if self._transient_time <= 0 or not self._transient_text:
            return
        win_w, win_h = self.win_size
        cx = (self.left_panel_w + win_w - self.right_panel_w) * 0.5
        cy = win_h * 0.5 + 50

        alpha = min(1.0, self._transient_time / 0.4)
        r, g, b, _ = self._transient_color

        imgui.set_next_window_position(cx - 120, cy)
        imgui.set_next_window_size(240, 0)
        flags = (imgui.WINDOW_NO_TITLE_BAR | imgui.WINDOW_NO_RESIZE
                 | imgui.WINDOW_NO_MOVE | imgui.WINDOW_ALWAYS_AUTO_RESIZE
                 | imgui.WINDOW_NO_FOCUS_ON_APPEARING | imgui.WINDOW_NO_NAV
                 | imgui.WINDOW_NO_INPUTS)
        imgui.push_style_color(imgui.COLOR_WINDOW_BACKGROUND, 0.0, 0.0, 0.0, 0.65 * alpha)
        imgui.push_style_color(imgui.COLOR_BORDER, 0.0, 0.0, 0.0, 0.0)
        imgui.begin("##Transient", flags=flags)
        imgui.text_colored(f"  {self._transient_text}", r, g, b, alpha)
        imgui.end()
        imgui.pop_style_color(2)

    # ── Menu bar ──────────────────────────────────────────────────

    def _menu_bar(self) -> None:
        from pygame.locals import QUIT as PG_QUIT
        if imgui.begin_main_menu_bar():
            if imgui.begin_menu("File"):
                if imgui.menu_item("New Zone...")[0]:
                    self.show_new_zone = True
                imgui.separator()
                if imgui.menu_item("Save", "Ctrl+S")[0]:
                    self._save_zone()
                if imgui.menu_item("Save As...")[0]:
                    self.save_as_name = self.zone_name if self.zone_name != "untitled" else ""
                    self.show_save_as = True
                imgui.separator()
                if imgui.menu_item("Quit", "Escape")[0]:
                    pygame.event.post(pygame.event.Event(PG_QUIT))
                imgui.end_menu()

            if imgui.begin_menu("Edit"):
                if imgui.menu_item("Undo", "Ctrl+Z")[0]:
                    if self.editor_3d:
                        self.editor_3d._undo()
                if imgui.menu_item("Redo", "Ctrl+Y")[0]:
                    if self.editor_3d:
                        self.editor_3d._redo()
                imgui.end_menu()

            if imgui.begin_menu("View"):
                clicked_3d, _ = imgui.menu_item(
                    "3D Editor", "Tab", self.view_mode == "3d")
                if clicked_3d and self.view_mode != "3d":
                    self._toggle_view_mode()
                clicked_ray, _ = imgui.menu_item(
                    "Raycaster Preview", "Tab", self.view_mode == "2d")
                if clicked_ray and self.view_mode != "2d":
                    self._toggle_view_mode()

                imgui.separator()
                if self.editor_3d:
                    _, self.editor_3d.show_axes = imgui.menu_item(
                        "Show Axes", "F10", self.editor_3d.show_axes)
                    _, self.editor_3d.show_walls = imgui.menu_item(
                        "Show Walls", "V", self.editor_3d.show_walls)
                    _, self.editor_3d.show_floors = imgui.menu_item(
                        "Show Floors", "F", self.editor_3d.show_floors)
                    _, self.editor_3d.show_ceilings = imgui.menu_item(
                        "Show Ceilings", "J", self.editor_3d.show_ceilings)
                    _, self.editor_3d.show_entities = imgui.menu_item(
                        "Show Entities", "N", self.editor_3d.show_entities)
                    imgui.separator()
                    _, self.editor_3d.wireframe = imgui.menu_item(
                        "Wireframe", "\\", self.editor_3d.wireframe)
                imgui.end_menu()

            # Right-aligned FPS
            spacing = max(0.0, imgui.get_window_width() - 220)
            imgui.same_line(spacing)
            if self.frame_ms < 10:
                imgui.text_colored(f"{self.fps:.0f} FPS  {self.frame_ms:.1f}ms",
                                   0.4, 0.9, 0.4, 1.0)
            elif self.frame_ms < 20:
                imgui.text_colored(f"{self.fps:.0f} FPS  {self.frame_ms:.1f}ms",
                                   0.9, 0.9, 0.3, 1.0)
            else:
                imgui.text_colored(f"{self.fps:.0f} FPS  {self.frame_ms:.1f}ms",
                                   0.9, 0.3, 0.3, 1.0)

            imgui.end_main_menu_bar()

    # ── Left panel: toolbox ───────────────────────────────────────

    def _left_panel(self) -> None:  # noqa: C901
        win_w, win_h = self.win_size
        imgui.set_next_window_position(0, MENU_BAR_H)
        imgui.set_next_window_size(self.left_panel_w, win_h - MENU_BAR_H - STATUS_BAR_H)
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
        self._draw_display_section(ed)
        self._draw_view_mode_button()
        self._draw_zone_list()

        imgui.end()

    def _draw_tool_buttons(self, ed, spacing_x: float) -> None:
        """Draw core tool + utility mode button rows."""
        self._section_header("\u2581 TOOLS", 0.65, 0.75, 0.95, pad_top=False)
        avail_w = imgui.get_content_region_available()[0]

        # Core tools: 2 rows of 2 (4 tools)
        n_cols = 2
        btn_w = (avail_w - (n_cols - 1) * spacing_x) / n_cols
        fkey_labels = {0: "F5", 1: "F6", 2: "F7", 3: "F8"}
        for i, tool_name in enumerate(TOOLS):
            if i % n_cols != 0:
                imgui.same_line()
            is_active = ed.tool == tool_name
            r, g, b = [c / 255.0 for c in TOOL_COLORS[tool_name]]
            if is_active:
                imgui.push_style_color(imgui.COLOR_BUTTON, r, g, b, 0.55)
                imgui.push_style_color(imgui.COLOR_BUTTON_HOVERED, r, g, b, 0.75)
                imgui.push_style_color(imgui.COLOR_BUTTON_ACTIVE, r, g, b, 0.90)
                imgui.push_style_color(imgui.COLOR_TEXT, 1.0, 1.0, 1.0, 1.0)
            else:
                imgui.push_style_color(imgui.COLOR_TEXT, 0.65, 0.65, 0.70, 1.0)
            if imgui.button(f"{fkey_labels[i]} {TOOL_LABELS[tool_name]}##{tool_name}", btn_w, 28):
                if ed.tool == "select":
                    ed._sel_cancel()
                ed._leave_tool(ed.tool)
                ed.tool = tool_name
                ed._prev_tool = tool_name
            if is_active:
                imgui.pop_style_color(4)
            else:
                imgui.pop_style_color(1)

        # Utility mode row (2 buttons)
        btn_w2 = (avail_w - spacing_x) / 2.0
        util_keys_label = {"select": "B", "stamp": "P"}
        for i, tool_name in enumerate(UTIL_TOOLS):
            if i > 0:
                imgui.same_line()
            is_active = ed.tool == tool_name
            r, g, b = [c / 255.0 for c in TOOL_COLORS[tool_name]]
            if is_active:
                imgui.push_style_color(imgui.COLOR_BUTTON, r, g, b, 0.55)
                imgui.push_style_color(imgui.COLOR_BUTTON_HOVERED, r, g, b, 0.75)
                imgui.push_style_color(imgui.COLOR_BUTTON_ACTIVE, r, g, b, 0.90)
                imgui.push_style_color(imgui.COLOR_TEXT, 1.0, 1.0, 1.0, 1.0)
            else:
                imgui.push_style_color(imgui.COLOR_TEXT, 0.55, 0.55, 0.60, 1.0)
            if imgui.button(f"{util_keys_label[tool_name]} {TOOL_LABELS[tool_name]}##{tool_name}", btn_w2, 24):
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
            if ed._sel_start is not None and ed._sel_end is not None:
                ctx_key = "active"
            elif ed._sel_start is not None:
                ctx_key = "started"
            else:
                ctx_key = "none"
        elif ed.tool == "sculpt":
            part = ed.aimed.part if ed.aimed else None
            if part == "ceiling":
                ctx_key = "ceiling"
            elif part in ("floor", "wall", "ground"):
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

        extra = hint.get("keys", "")
        if extra:
            imgui.spacing()
            imgui.push_text_wrap_pos(wrap_x)
            imgui.text_colored(extra, 0.55, 0.55, 0.40, 1.0)
            imgui.pop_text_wrap_pos()

        # Select tool state
        if ed.tool == "select":
            imgui.spacing()
            ceil_mode = getattr(ed, '_sel_ceiling_mode', False)
            mode_label = "CEILING MODE" if ceil_mode else "FLOOR MODE"
            mode_col = (0.55, 0.70, 0.90, 1.0) if ceil_mode else (0.70, 0.90, 0.55, 1.0)
            imgui.text_colored(mode_label, *mode_col)
            imgui.same_line()
            imgui.text_disabled("(X to toggle)")
            if ed._sel_start is not None and ed._sel_end is not None:
                bounds = ed._sel_bounds()
                if bounds:
                    r1, c1, r2, c2 = bounds
                    area = (r2 - r1 + 1) * (c2 - c1 + 1)
                    imgui.text_disabled(f"\u25a1 {area} cells selected")

    def _draw_display_section(self, ed) -> None:
        self._section_header("\u2581 DISPLAY", 0.50, 0.60, 0.65)
        half_w = imgui.get_content_region_available()[0] * 0.5
        _, ed.show_walls = imgui.checkbox("Walls (V)", ed.show_walls)
        imgui.same_line(half_w)
        _, ed.show_floors = imgui.checkbox("Floors (F)", ed.show_floors)
        _, ed.show_ceilings = imgui.checkbox("Ceilings (J)", ed.show_ceilings)
        imgui.same_line(half_w)
        _, ed.show_axes = imgui.checkbox("Axes", ed.show_axes)
        _, ed.show_entities = imgui.checkbox("Entities (N)", ed.show_entities)
        imgui.same_line(half_w)
        _, ed.wireframe = imgui.checkbox("Wireframe (\\)", ed.wireframe)

        # FOV slider (visible in raycaster preview mode)
        if self.view_mode == "2d" and self.renderer:
            imgui.spacing()
            fov_deg = math.degrees(self.renderer.fov)
            changed, fov_deg = imgui.slider_float(
                "FOV", fov_deg, 45.0, 120.0, "%.0f\u00b0")
            if changed:
                self.renderer.fov = math.radians(fov_deg)

    def _draw_view_mode_button(self) -> None:
        imgui.spacing()
        full_w = imgui.get_content_region_available()[0]
        mode_label = "Preview" if self.view_mode == "3d" else "Editor"
        mode_icon = "\u25b6" if self.view_mode == "3d" else "\u270e"
        if imgui.button(f"{mode_icon} Switch to {mode_label} (Tab)", full_w, 26):
            self._toggle_view_mode()

    def _draw_zone_list(self) -> None:
        self._section_header("\u2581 ZONES", 0.85, 0.75, 0.45)
        if imgui.button("+ New Zone", imgui.get_content_region_available()[0], 24):
            if self._request_guarded("new"):
                self.show_new_zone = True
        for name in self.all_zones:
            is_loaded = (name == self.zone_name)
            if is_loaded:
                imgui.push_style_color(imgui.COLOR_TEXT, 1.0, 0.82, 0.25, 1.0)
            prefix = "\u25b8 " if is_loaded else "  "
            clicked, _ = imgui.selectable(f"{prefix}{name}", is_loaded)
            if clicked and name != self.zone_name:
                if self._request_guarded("switch", name):
                    self._load_zone(name)
            if is_loaded:
                imgui.pop_style_color()

    # ── Right panel: properties / inspector ───────────────────────

    def _properties_panel(self) -> None:  # noqa: C901
        win_w, win_h = self.win_size
        imgui.set_next_window_position(win_w - self.right_panel_w, MENU_BAR_H)
        imgui.set_next_window_size(self.right_panel_w, win_h - MENU_BAR_H - STATUS_BAR_H)
        flags = (imgui.WINDOW_NO_MOVE | imgui.WINDOW_NO_RESIZE
                 | imgui.WINDOW_NO_COLLAPSE | imgui.WINDOW_NO_SAVED_SETTINGS)
        imgui.begin("Inspector", flags=flags)

        if not self.zone:
            imgui.text_colored("No zone loaded", 0.5, 0.5, 0.5, 1.0)
            imgui.end()
            return

        zone = self.zone

        # Zone header
        dirty_mark = " *" if self.dirty else ""
        imgui.text_colored(f"{self.zone_name}{dirty_mark}", 1.0, 0.9, 0.5, 1.0)
        imgui.same_line()
        imgui.text_disabled(f"{zone.width} x {zone.height}")
        imgui.separator()

        # Entity inspector (when entity tool active and entity selected)
        if (self.editor_3d and self.editor_3d.tool == "entity"
                and self.editor_3d._ent_selected is not None
                and zone.entities):
            self._draw_entity_inspector(zone)

        # Cell inspector
        if self.editor_3d and self.editor_3d.aimed:
            self._draw_cell_inspector(zone)
        else:
            imgui.text_colored("Aim at a cell to inspect", 0.45, 0.45, 0.5, 1.0)

        # Zone settings
        imgui.spacing()
        self._section_header("\u2581 ZONE SETTINGS", 0.65, 0.60, 0.50)
        self._draw_zone_settings(zone)

        # Camera
        if self.editor_3d:
            self._draw_camera_info()

        imgui.end()

    def _draw_cell_inspector(self, zone) -> None:
        """Draw the cell inspector for the currently aimed cell."""
        hit = self.editor_3d.aimed
        r, c = hit.row, hit.col

        if not imgui.collapsing_header(f"Cell ({r}, {c})##cell",
                                       imgui.TREE_NODE_DEFAULT_OPEN)[0]:
            return

        td_obj = tile_def(zone.tiles[r][c])
        tile_name = zone.tiles[r][c]
        is_wall = td_obj and td_obj.wall

        imgui.text(tile_name)
        imgui.same_line()
        if is_wall:
            imgui.text_colored("WALL", 0.9, 0.4, 0.3, 1.0)
        else:
            imgui.text_colored("OPEN", 0.4, 0.8, 0.4, 1.0)

        fh = zone.floor_heights[r][c]
        ch = zone.ceil_heights[r][c]
        is_sky = ch >= 10.0 - 0.01
        gap = ch - fh

        imgui.columns(2, "##hcols", False)
        imgui.set_column_width(0, 55)

        imgui.text_disabled("Floor")
        imgui.next_column()
        if abs(fh) < 0.001:
            imgui.text_colored("0.00", 0.6, 0.8, 0.6, 1.0)
        elif fh < 0:
            imgui.text_colored(f"{fh:.2f}", 0.5, 0.6, 0.9, 1.0)
        else:
            imgui.text(f"{fh:.2f}")
        imgui.next_column()

        imgui.text_disabled("Ceil")
        imgui.next_column()
        if is_sky:
            imgui.text_colored("SKY", 0.4, 0.7, 1.0, 1.0)
        else:
            imgui.text(f"{ch:.2f}")
        imgui.next_column()

        imgui.text_disabled("Gap")
        imgui.next_column()
        if gap < 0.5:
            imgui.text_colored(f"{gap:.2f}", 0.9, 0.3, 0.3, 1.0)
        else:
            imgui.text(f"{gap:.2f}")
        imgui.columns(1)

        # Upper wall height
        if zone.upper_wall_height and len(zone.upper_wall_height) > r:
            uwh = zone.upper_wall_height[r][c]
            if uwh > 0.01:
                imgui.text_disabled("Upper wall")
                imgui.same_line(80)
                imgui.text(f"{uwh:.2f}")

        # Textures
        imgui.spacing()
        wt = zone.wall_textures[r][c] if zone.wall_textures else ""
        ft = zone.floor_textures[r][c] if zone.floor_textures else ""
        ct = zone.ceil_textures[r][c] if zone.ceil_textures else ""

        for lbl, tex in (("Wall", wt), ("Floor", ft), ("Ceil", ct)):
            imgui.text_disabled(lbl)
            imgui.same_line(55)
            if tex:
                imgui.text(tex)
            else:
                imgui.text_colored("\u2014", 0.4, 0.4, 0.45, 1.0)

        # Face overrides
        if zone.face_textures:
            faces = zone.face_textures[r][c]
            for i, d in enumerate("NSEW"):
                if faces[i]:
                    imgui.text_disabled(f"  {d}")
                    imgui.same_line(55)
                    imgui.text(faces[i])

        # Wall segments
        if zone.wall_segments:
            segs = zone.wall_segments[r][c]
            has_segs = any(face_segs for face_segs in segs)
            if has_segs and imgui.tree_node("Segments"):
                for fi, face_segs in enumerate(segs):
                    if face_segs:
                        fn = "NSEW"[fi]
                        for seg in face_segs:
                            imgui.text_disabled(f"  {fn}")
                            imgui.same_line(40)
                            imgui.text(f"{seg[0]} @ {seg[1]:.2f}")
                imgui.tree_pop()

        # Aimed target
        if hit.part:
            imgui.spacing()
            is_wall_a = td_obj and td_obj.wall
            face_label = _paint_target_label(hit.part, hit.face, is_wall_a)
            if hit.part == "floor":
                pc = (0.7, 0.9, 0.55, 1.0)
            elif hit.part == "ceiling":
                pc = (0.55, 0.7, 0.9, 1.0)
            else:
                pc = (0.95, 0.75, 0.35, 1.0)
            imgui.text_colored(f"> {face_label}", *pc)

            if self.editor_3d.tool == "paint":
                tex = self.editor_3d.current_texture or zone.tiles[r][c]
                cur = self._get_face_texture(zone, r, c, hit.part, hit.face)
                imgui.text_disabled("Brush")
                imgui.same_line(55)
                imgui.text(tex)
                imgui.text_disabled("Current")
                imgui.same_line(55)
                imgui.text(cur if cur else "\u2014")

    def _draw_entity_inspector(self, zone) -> None:
        """Draw inspector for the currently selected entity."""
        ed = self.editor_3d
        idx = ed._ent_selected
        if idx is None or idx < 0 or idx >= len(zone.entities):
            return
        ent = zone.entities[idx]
        etype = ent.get("type", "unknown")
        edef = get_entity_def(etype)

        opened, _ = imgui.collapsing_header(
            f"Entity: {etype}##entinsp", imgui.TREE_NODE_DEFAULT_OPEN)
        if not opened:
            return

        # Type + color
        if edef:
            r0, g0, b0 = edef.color[0] / 255.0, edef.color[1] / 255.0, edef.color[2] / 255.0
            imgui.color_button("##einsp_col", r0, g0, b0, 1.0, 0, 14, 14)
            imgui.same_line()
            imgui.text_colored(edef.display_name, 0.95, 0.90, 0.75, 1.0)
        else:
            imgui.text(etype)

        # ID
        imgui.text_disabled("ID")
        imgui.same_line(55)
        imgui.text(ent.get("id", "?"))

        # Position
        imgui.columns(2, "##einsp_pos", False)
        imgui.set_column_width(0, 55)
        imgui.text_disabled("X")
        imgui.next_column()
        imgui.text(f"{ent.get('x', 0):.3f}")
        imgui.next_column()
        imgui.text_disabled("Y")
        imgui.next_column()
        imgui.text(f"{ent.get('y', 0):.3f}")
        imgui.columns(1)

        # Angle
        angle = float(ent.get("angle", 0.0))
        deg = math.degrees(angle)
        label = angle_to_label(angle)
        imgui.text_disabled("Angle")
        imgui.same_line(55)
        imgui.text(f"{deg:.0f}\u00b0 ({label})")
        if edef and edef.directional:
            imgui.same_line()
            imgui.text_colored("\u27a4", 0.6, 0.8, 1.0, 1.0)

        # State
        state = ent.get("state", "default")
        imgui.text_disabled("State")
        imgui.same_line(55)
        imgui.text(state)
        if edef and len(edef.states) > 1:
            imgui.same_line()
            imgui.text_disabled(f"({'/'.join(edef.states)})")

        # Scale (from def)
        if edef:
            imgui.text_disabled("Scale")
            imgui.same_line(55)
            imgui.text(f"{edef.scale:.2f}")

        imgui.separator()

    def _draw_zone_settings(self, zone) -> None:
        if not imgui.collapsing_header("Zone Settings", imgui.TREE_NODE_DEFAULT_OPEN)[0]:
            return

        imgui.text_disabled("Size")
        imgui.same_line(55)
        imgui.text(f"{zone.width} x {zone.height}")
        imgui.spacing()

        ar, ac = zone.anchor if zone.anchor else (0.0, 0.0)
        imgui.text_disabled("Anchor")
        imgui.push_item_width(self.right_panel_w - 80)
        changed_r, new_ar = imgui.input_float("Row##anchor_r", ar, 0.5, 1.0)
        changed_c, new_ac = imgui.input_float("Col##anchor_c", ac, 0.5, 1.0)
        imgui.pop_item_width()
        if changed_r or changed_c:
            zone.anchor = (new_ar, new_ac)
            self.dirty = True
        if self.editor_3d and imgui.button("Set to Camera##anchor_cam"):
            zone.anchor = (self.editor_3d.cam_z, self.editor_3d.cam_x)
            self.dirty = True

        imgui.spacing()
        changed_fp, new_fp = imgui.checkbox("First Person", zone.first_person)
        if changed_fp:
            zone.first_person = new_fp
            self.dirty = True

    def _draw_camera_info(self) -> None:
        if not imgui.collapsing_header("Camera", imgui.TREE_NODE_DEFAULT_OPEN)[0]:
            return

        ed = self.editor_3d
        imgui.columns(2, "##cam_cols", False)
        imgui.set_column_width(0, 45)
        for lbl, val in (("X", ed.cam_x), ("Y", ed.cam_y), ("Z", ed.cam_z)):
            imgui.text_disabled(lbl)
            imgui.next_column()
            imgui.text(f"{val:.2f}")
            imgui.next_column()
        imgui.text_disabled("Yaw")
        imgui.next_column()
        imgui.text(f"{math.degrees(ed.yaw):.0f}\u00b0")
        imgui.next_column()
        imgui.text_disabled("Pitch")
        imgui.next_column()
        imgui.text(f"{math.degrees(ed.pitch):.0f}\u00b0")
        imgui.columns(1)

    def _get_face_texture(self, zone, r: int, c: int, part: str, face: str) -> str:
        """Return the currently applied texture string for a given face."""
        from editor.view_3d.constants import FACE_IDX
        if face in FACE_IDX:
            fi = FACE_IDX[face]
            td_obj = tile_def(zone.tiles[r][c])
            if td_obj and td_obj.wall:
                if zone.face_textures:
                    return zone.face_textures[r][c][fi]
            elif part == "floor" and hasattr(zone, "floor_step_textures") and zone.floor_step_textures:
                return zone.floor_step_textures[r][c][fi]
            elif part == "ceiling" and hasattr(zone, "ceil_step_textures") and zone.ceil_step_textures:
                return zone.ceil_step_textures[r][c][fi]
            elif zone.face_textures:
                return zone.face_textures[r][c][fi]
        elif face == "top":
            if part == "floor" and zone.floor_textures:
                return zone.floor_textures[r][c]
            elif part in ("wall", "ceiling") and zone.ceil_textures:
                return zone.ceil_textures[r][c]
        elif face == "bot":
            if part == "ceiling" and zone.ceil_textures:
                return zone.ceil_textures[r][c]
            elif part in ("wall", "floor") and zone.floor_textures:
                return zone.floor_textures[r][c]
        return ""

    # ── Status bar ────────────────────────────────────────────────

    def _status_bar(self) -> None:
        win_w, win_h = self.win_size
        imgui.set_next_window_position(0, win_h - STATUS_BAR_H)
        imgui.set_next_window_size(win_w, STATUS_BAR_H)
        flags = (imgui.WINDOW_NO_MOVE | imgui.WINDOW_NO_RESIZE
                 | imgui.WINDOW_NO_TITLE_BAR | imgui.WINDOW_NO_SCROLLBAR
                 | imgui.WINDOW_NO_SCROLL_WITH_MOUSE | imgui.WINDOW_NO_COLLAPSE)
        imgui.push_style_color(imgui.COLOR_WINDOW_BACKGROUND, 0.06, 0.06, 0.08, 0.98)
        imgui.begin("##StatusBar", flags=flags)

        if self.zone:
            dirty = " \u2022" if self.dirty else ""
            imgui.text_colored(f"{self.zone_name}{dirty}", 0.90, 0.85, 0.65, 1.0)

            imgui.same_line()
            imgui.text_disabled(f"  {self.zone.width}\u00d7{self.zone.height}")

            imgui.same_line()
            imgui.text("  ")
            imgui.same_line()
            mode = "3D EDITOR" if self.view_mode == "3d" else "RAYCASTER"
            imgui.text_colored(mode, 0.45, 0.75, 1.0, 1.0)

            if self.editor_3d and self.view_mode == "3d":
                ed = self.editor_3d
                imgui.same_line()
                imgui.text("  ")
                imgui.same_line()
                r, g, b = [c / 255.0 for c in TOOL_COLORS[ed.tool]]
                imgui.text_colored(TOOL_LABELS[ed.tool], r, g, b, 1.0)

                imgui.same_line()
                imgui.text_disabled(f"  Snap:{ed.snap_y}")

                if ed.tool in ("paint", "segment", "select"):
                    imgui.same_line()
                    imgui.text_disabled(f"  Tex:{ed.current_texture}")
                elif ed.tool == "stamp":
                    preset = ed._stamp_current()
                    pname = preset.name if preset else "?"
                    imgui.same_line()
                    imgui.text_disabled(f"  Preset:{pname}")
                elif ed.tool == "entity":
                    imgui.same_line()
                    imgui.text_disabled(f"  Ent:{ed._ent_current_type()}")
                    if ed._ent_selected is not None:
                        imgui.same_line()
                        imgui.text_colored("SEL", 0.3, 0.9, 1.0, 1.0)

                if ed.aimed:
                    imgui.same_line()
                    imgui.text_disabled(f"  Cell:({ed.aimed.col},{ed.aimed.row})")

            elif self.view_mode == "2d":
                imgui.same_line()
                imgui.text_disabled(f"  Pos:({self.px:.1f}, {self.py:.1f})")
                if self.noclip:
                    imgui.same_line()
                    imgui.text_colored(" NOCLIP", 0.9, 0.4, 0.4, 1.0)

            if self.mouse_captured:
                label = "\u25cf EDITING"
                label_w = imgui.calc_text_size(label)[0] + 16
                imgui.same_line(max(win_w - label_w, 500))
                imgui.text_colored(label, 0.3, 1.0, 0.4, 1.0)
        else:
            imgui.text_disabled("Select or create a zone to begin")

        imgui.end()
        imgui.pop_style_color()
