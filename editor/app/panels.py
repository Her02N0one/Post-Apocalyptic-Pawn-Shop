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
    MODES, MODE_LABELS, MODE_ICONS, MODE_COLORS,
    MODE_DESCRIPTIONS, MODE_TOOLS, MODE_SELECTION_TARGET,
    VIEW_LIT, VIEW_PATHING, VIEW_MODES, VIEW_LABELS,
    PASTE_MASK_ALL,
)
from editor.app.constants import MENU_BAR_H, STATE_BAR_H, STATUS_BAR_H
from editor.view_3d.constants import (
    PASTE_MASK_HEIGHTS, PASTE_MASK_TEXTURES, PASTE_MASK_ENTITIES,
    PASTE_MASK_SEGMENTS, PASTE_MASK_LIGHTING,
)


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


# ── Relative math parser ─────────────────────────────────────────

def _parse_relative_value(text: str, current_values: list[float]) -> list[float]:
    """Parse a relative math expression and apply it to a list of values.

    Supported prefixes:
        ``=N``  → set all to N (absolute)
        ``+N``  → add N to each
        ``-N``  → subtract N from each
        ``*N``  → multiply each by N

    A bare number (no prefix) is treated as ``=N`` (absolute set).
    Returns a new list of computed values (same length as *current_values*).
    """
    s = text.strip()
    if not s:
        return list(current_values)
    try:
        if s.startswith("="):
            n = float(s[1:])
            return [n] * len(current_values)
        elif s.startswith("+"):
            n = float(s[1:])
            return [v + n for v in current_values]
        elif s.startswith("-"):
            n = float(s[1:])
            return [v - n for v in current_values]
        elif s.startswith("*"):
            n = float(s[1:])
            return [v * n for v in current_values]
        else:
            n = float(s)
            return [n] * len(current_values)
    except (ValueError, IndexError):
        return list(current_values)


def _collect_cell_values(zone, cells, getter) -> list:
    """Collect a property value from each cell using *getter(zone, r, c)*.

    Returns a list of values, one per cell.
    """
    out = []
    for r, c in cells:
        try:
            out.append(getter(zone, r, c))
        except (IndexError, AttributeError):
            out.append(None)
    return out


def _summarise_values(values: list) -> tuple:
    """Return (display_str, is_mixed, common_value).

    - If all values are equal → (str(val), False, val)
    - If mixed                → ("<Mixed>", True, None)
    """
    unique = set()
    for v in values:
        if isinstance(v, float):
            unique.add(round(v, 4))
        else:
            unique.add(v)
    if len(unique) == 1:
        val = values[0]
        if isinstance(val, float):
            return f"{val:.3f}", False, val
        return str(val) if val else "\u2014", False, val
    return "<Mixed>", True, None


class PanelsMixin:
    """ImGui sidebar panels, status bar, and overlays for :class:`ZoneEditorApp`."""

    _SNAP_LABELS = ("1/16", "1/8", "1/4", "1/2", "1")

    # ── UI entry point ────────────────────────────────────────────

    def _build_ui(self) -> None:
        self._menu_bar()
        self._global_state_bar()
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
        # Keyboard shortcut help overlay (? key)
        if self.editor_3d and getattr(self.editor_3d, '_show_help', False):
            self._draw_help_overlay()
        # Keybind editor window
        if getattr(self, 'show_keybind_editor', False) and self.editor_3d:
            self._draw_keybind_editor()

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
        panel_h = win_h - MENU_BAR_H - STATE_BAR_H - STATUS_BAR_H
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
        imgui.set_next_window_position(lx, MENU_BAR_H + STATE_BAR_H)
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
        imgui.set_next_window_position(rx, MENU_BAR_H + STATE_BAR_H)
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
                imgui.separator()
                if imgui.menu_item("Keybinds...")[0]:
                    self.show_keybind_editor = not getattr(self, 'show_keybind_editor', False)
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

    # ── Global state bar (Layer + View mode) ──────────────────────

    def _global_state_bar(self) -> None:
        """Draw the global state bar: Layer selector + View mode toggle.

        This is the Z-Plane Authority — the user must always know which
        elevation layer they are manipulating.
        """
        win_w, _ = self.win_size
        imgui.set_next_window_position(0, MENU_BAR_H)
        imgui.set_next_window_size(win_w, STATE_BAR_H)
        flags = (imgui.WINDOW_NO_MOVE | imgui.WINDOW_NO_RESIZE
                 | imgui.WINDOW_NO_TITLE_BAR | imgui.WINDOW_NO_SCROLLBAR
                 | imgui.WINDOW_NO_COLLAPSE | imgui.WINDOW_NO_SAVED_SETTINGS)
        imgui.push_style_color(imgui.COLOR_WINDOW_BACKGROUND, 0.08, 0.08, 0.12, 0.98)
        imgui.begin("##StateBar", flags=flags)

        ed = self.editor_3d

        # ── Layer selector ────────────────────────────────────────
        imgui.text_colored("\u2756", 0.9, 0.75, 0.3, 1.0)  # ❖
        imgui.same_line()
        imgui.text_colored("LAYER:", 0.7, 0.7, 0.75, 1.0)
        imgui.same_line()

        active_layer = ed.active_layer if ed else 1
        isolate = ed.isolate_layer if ed else False

        # Layer 1 button
        is_l1 = active_layer == 1
        if is_l1:
            imgui.push_style_color(imgui.COLOR_BUTTON, 0.22, 0.55, 0.30, 1.0)
            imgui.push_style_color(imgui.COLOR_BUTTON_HOVERED, 0.28, 0.65, 0.38, 1.0)
        if imgui.button("1: Ground##layer1", 90, 22):
            if ed:
                ed.active_layer = 1
        if is_l1:
            imgui.pop_style_color(2)
        imgui.same_line()

        # Layer 2 button
        is_l2 = active_layer == 2
        if is_l2:
            imgui.push_style_color(imgui.COLOR_BUTTON, 0.50, 0.35, 0.70, 1.0)
            imgui.push_style_color(imgui.COLOR_BUTTON_HOVERED, 0.60, 0.42, 0.80, 1.0)
        if imgui.button("2: Upper##layer2", 90, 22):
            if ed:
                ed.active_layer = 2
        if is_l2:
            imgui.pop_style_color(2)

        imgui.same_line()
        imgui.text("  ")
        imgui.same_line()

        # Isolate toggle
        if isolate:
            imgui.push_style_color(imgui.COLOR_BUTTON, 0.70, 0.25, 0.25, 1.0)
            imgui.push_style_color(imgui.COLOR_BUTTON_HOVERED, 0.80, 0.35, 0.35, 1.0)
        if imgui.button("Iso Alt+I##iso", 80, 22):
            if ed:
                ed.isolate_layer = not ed.isolate_layer
        if isolate:
            imgui.pop_style_color(2)

        # ── Separator ─────────────────────────────────────────────
        imgui.same_line()
        imgui.text_colored("|", 0.3, 0.3, 0.35, 1.0)
        imgui.same_line()

        # ── View mode ─────────────────────────────────────────────
        imgui.text_colored("\U0001f441", 0.5, 0.7, 0.9, 1.0)  # 👁
        imgui.same_line()
        imgui.text_colored("VIEW:", 0.7, 0.7, 0.75, 1.0)
        imgui.same_line()

        view_3d = ed.view_mode_3d if ed else VIEW_LIT
        for vm in VIEW_MODES:
            is_active = view_3d == vm
            if is_active:
                imgui.push_style_color(imgui.COLOR_BUTTON, 0.25, 0.45, 0.65, 1.0)
                imgui.push_style_color(imgui.COLOR_BUTTON_HOVERED, 0.30, 0.55, 0.75, 1.0)
            if imgui.button(f"{VIEW_LABELS[vm]}##vm_{vm}", 70, 22):
                if ed:
                    ed.view_mode_3d = vm
            if is_active:
                imgui.pop_style_color(2)
            imgui.same_line()

        # ── Right side: clipboard indicator ───────────────────────
        if ed and ed._clipboard:
            spacing = max(0.0, win_w - 200)
            imgui.same_line(spacing)
            imgui.text_colored("\U0001f4cb Clipboard", 0.6, 0.6, 0.5, 1.0)

        imgui.end()
        imgui.pop_style_color()

    # ── Left panel: toolbox ───────────────────────────────────────

    def _left_panel(self) -> None:  # noqa: C901
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
        self._draw_display_section(ed)
        self._draw_view_mode_button()
        self._draw_zone_list()

        imgui.end()

    def _draw_tool_buttons(self, ed, spacing_x: float) -> None:
        """Draw 4 primary mode buttons + mode-specific sub-tools.

        State machine: Mode → Tool → Selection → Operation.
        Modes: F1=Architecture  F2=Surface  F3=Props  F4=Logic
        """
        self._section_header("\u2581 MODE", 0.65, 0.75, 0.95, pad_top=False)
        avail_w = imgui.get_content_region_available()[0]

        # ── 4 primary mode buttons (2×2 grid) ────────────────────
        n_cols = 2
        btn_w = (avail_w - (n_cols - 1) * spacing_x) / n_cols
        fkey_label = {0: "F1", 1: "F2", 2: "F3", 3: "F4"}
        active_mode = getattr(ed, 'mode', MODES[0])

        for i, mode in enumerate(MODES):
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
            label = MODE_LABELS[mode]
            if imgui.button(f"{fkey_label[i]} {label}##{mode}", btn_w, 30):
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
                if imgui.button(f"{ti + 1} {tool_label}##{tool}", sub_w, 24):
                    self._switch_tool(ed, tool)
                if is_tool_active:
                    imgui.pop_style_color(4)
                else:
                    imgui.pop_style_color(1)

        # ── Cross-cutting utility tools ───────────────────────────
        imgui.spacing()
        imgui.separator()
        imgui.text_colored("\u2581 UTILITY", 0.50, 0.55, 0.50, 1.0)
        _util = [
            ("select", "B"), ("stamp", "P"),
            ("quad", "I"), ("portal", "O"), ("curve", ";"),
        ]
        n_util_cols = 2
        btn_w2 = (avail_w - spacing_x) / float(n_util_cols)
        for i, (tool_name, key_lbl) in enumerate(_util):
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
            if imgui.button(f"{key_lbl} {tool_label}##{tool_name}", btn_w2, 24):
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
        from editor.view_3d.constants import MODE_TOOLS as MT, MODES as _MODES
        if ed.tool == "select":
            ed._sel_cancel()
        ed._leave_tool(ed.tool)
        ed.mode = mode
        sub_tools = MT.get(mode, ())
        if sub_tools:
            ed.tool = sub_tools[0]
            ed._prev_tool = sub_tools[0]

    def _switch_tool(self, ed, tool: str) -> None:
        """Switch to a sub-tool within the current mode."""
        if ed.tool == "select":
            ed._sel_cancel()
        ed._leave_tool(ed.tool)
        ed.tool = tool
        ed._prev_tool = tool

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

            ceil_mode = getattr(ed, '_sel_ceiling_mode', False)
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
            ed._sel_start = None
            ed._sel_end = None
            if objs:
                objs.deselect_all()
        imgui.same_line()
        if imgui.button("Ct+A##sel_all", btn_w, 0):
            zone = ed.zone
            if zone:
                sel.select_all_cells(zone.width, zone.height)
                ed._sel_start = (0, 0)
                ed._sel_end = (zone.height - 1, zone.width - 1)
        imgui.same_line()
        if imgui.button("Del##sel_del", btn_w, 0):
            if n_objs > 0 and objs:
                objs.delete_selected()
            elif n_cells > 0:
                ed._sel_reset_cells()

    def _draw_help_overlay(self) -> None:
        """Floating keyboard shortcut reference (toggled with ? key)."""
        win_w, win_h = self.win_size
        ow, oh = min(480, win_w - 100), min(600, win_h - 100)
        imgui.set_next_window_position(
            (win_w - ow) / 2, (win_h - oh) / 2, imgui.FIRST_USE_EVER)
        imgui.set_next_window_size(ow, oh, imgui.FIRST_USE_EVER)

        expanded, opened = imgui.begin("Keyboard Shortcuts  (?)", True,
                                       imgui.WINDOW_NO_SAVED_SETTINGS)
        if not opened:
            self.editor_3d._show_help = False
            imgui.end()
            return

        _HELP = [
            ("MODES", [
                ("F1",        "Architecture mode (sculpt, segment)"),
                ("F2",        "Surface mode (paint)"),
                ("F3",        "Props mode (prism, quad, curve)"),
                ("F4",        "Logic mode (entity, portal)"),
            ]),
            ("LAYERS", [
                ("PgUp/PgDn", "Switch active layer (1/2)"),
                ("Alt+I",     "Isolate active layer"),
            ]),
            ("SELECTION", [
                ("B",         "Enter/exit select mode"),
                ("LMB+LMB",  "Rectangle select (two clicks)"),
                ("Sh+LMB",   "Line select / add to selection"),
                ("Ct+LMB",   "Toggle individual cell"),
                ("Ct+A",     "Select all cells"),
                ("Sh+G",     "Select similar (match properties)"),
                ("Esc",      "Clear selection"),
                ("X",        "Toggle floor/ceiling mode"),
            ]),
            ("CLIPBOARD", [
                ("Ct+C",     "Copy cell state to clipboard"),
                ("Ct+V",     "Paste clipboard (respects paste mask)"),
            ]),
            ("DISPLAY", [
                ("Ct+1 / V",  "Toggle walls"),
                ("Ct+2 / F",  "Toggle floors"),
                ("Ct+3 / J",  "Toggle ceilings"),
                ("Ct+4 / N",  "Toggle entities"),
                ("Ct+5 / \\", "Toggle wireframe"),
                ("F10",       "Toggle axes"),
            ]),
            ("GLOBAL", [
                ("Ct+S",     "Save"),
                ("Ct+Z",     "Undo"),
                ("Ct+Y",     "Redo"),
                ("?",        "This help overlay"),
                ("Esc",      "Deselect / cancel / release mouse"),
            ]),
            ("HOTBAR", [
                ("6-0",       "Texture slots 6-10"),
                ("Alt+1-0",   "Texture slots 1-10"),
            ]),
            ("SCULPT", [
                ("LMB/RMB",     "Raise/lower floor"),
                ("Sh+LMB/RMB",  "Lower/raise ceiling"),
                ("Scroll",       "Extend / adjust"),
                ("T / Sh+T",     "Add / remove ceiling"),
                ("H / Sh+H",     "Make wall / open"),
                ("L / Sh+L",     "Flatten floor / ceiling"),
                ("U / Sh+U",     "Raise / lower upper wall"),
                ("Ct+U",         "Reset upper wall height"),
                ("R",            "Reset height"),
                ("G",            "Cycle snap grid"),
            ]),
            ("PAINT", [
                ("LMB",         "Paint face"),
                ("Sh+LMB",      "Paint whole cell"),
                ("Ct+LMB",      "Flood fill"),
                ("RMB",         "Erase texture"),
                ("MMB",         "Eyedropper"),
                ("Scroll",      "Cycle palette"),
            ]),
            ("OBJECTS", [
                ("LMB",          "Place / select"),
                ("Ct+LMB",       "Toggle multi-select"),
                ("Sh+LMB",       "Add to selection"),
                ("RMB",          "Deselect / delete"),
                ("Del",          "Delete selected (any tool)"),
                ("R",            "Rotate 90\u00b0 (prism)"),
                ("Scroll",       "Type-specific adjust"),
            ]),
        ]

        for section, binds in _HELP:
            if imgui.collapsing_header(section, imgui.TREE_NODE_DEFAULT_OPEN)[0]:
                for key, desc in binds:
                    imgui.push_style_color(imgui.COLOR_TEXT, 0.90, 0.80, 0.45, 1.0)
                    imgui.text(f"  {key:14s}")
                    imgui.pop_style_color()
                    imgui.same_line(140)
                    imgui.text(desc)

        imgui.end()

    # ── Keybind editor window ─────────────────────────────────────

    def _draw_keybind_editor(self) -> None:
        """Floating keybind editor with conflict detection and rebinding."""
        import pygame
        from editor.keybinds import _simplify_mods, _key_label

        ed = self.editor_3d
        if not ed:
            return
        kb_reg = ed.kb

        win_w, win_h = self.win_size
        imgui.set_next_window_position(
            win_w * 0.15, win_h * 0.1, imgui.FIRST_USE_EVER)
        imgui.set_next_window_size(
            min(680, win_w * 0.7), min(620, win_h * 0.8), imgui.FIRST_USE_EVER)

        expanded, opened = imgui.begin("Keybind Editor", True)
        if not opened:
            self.show_keybind_editor = False
            self._kb_capturing = ""
            imgui.end()
            return

        # ── Toolbar row ───────────────────────────────────────────
        conflict_set = kb_reg.conflict_set()
        n_conflicts = len(conflict_set) // 2  # each pair counted once

        # Search filter
        changed, self._kb_filter = imgui.input_text(
            "Filter", self._kb_filter or "", 64)
        imgui.same_line()

        # Conflict filter toggle
        if n_conflicts > 0:
            imgui.push_style_color(imgui.COLOR_TEXT, 1.0, 0.4, 0.4, 1.0)
            _, self._kb_show_conflicts = imgui.checkbox(
                f"Conflicts ({n_conflicts})", self._kb_show_conflicts)
            imgui.pop_style_color()
        else:
            imgui.text_colored("No conflicts", 0.4, 0.9, 0.4, 1.0)

        imgui.same_line(imgui.get_window_width() - 160)
        if imgui.button("Reset All", 70, 0):
            kb_reg.reset_all()
        imgui.same_line()
        if imgui.button("Save", 70, 0):
            import os
            path = os.path.join(os.path.dirname(__file__), '..', '..', 'keybinds.json')
            kb_reg.save_overrides(path)

        imgui.separator()

        # ── Capture mode overlay ──────────────────────────────────
        capturing = getattr(self, '_kb_capturing', "")
        if capturing:
            imgui.push_style_color(imgui.COLOR_CHILD_BACKGROUND, 0.15, 0.10, 0.25, 0.95)
            imgui.begin_child("##capture_overlay", 0, 50, border=True)
            bind = kb_reg.get(capturing)
            imgui.text_colored(
                f"  Press any key combo for: {bind.description if bind else capturing}",
                1.0, 0.9, 0.5, 1.0)
            imgui.text_colored("  Press Escape to cancel", 0.6, 0.6, 0.6, 1.0)
            imgui.end_child()
            imgui.pop_style_color()

            # Check for key capture (poll all events isn't possible here,
            # so we check get_pressed + mods)
            io = imgui.get_io()
            # Use imgui input to detect the most recent key press
            for ki in range(512):
                if io.keys_down[ki]:
                    # Map imgui key index to pygame key
                    pg_key = ki
                    if pg_key == pygame.K_ESCAPE:
                        self._kb_capturing = ""
                        break
                    # Skip pure modifier keys
                    if pg_key in (pygame.K_LSHIFT, pygame.K_RSHIFT,
                                  pygame.K_LCTRL, pygame.K_RCTRL,
                                  pygame.K_LALT, pygame.K_RALT):
                        continue
                    mods = _simplify_mods(pygame.key.get_mods())
                    kb_reg.rebind(capturing, pg_key, mods)
                    self._kb_capturing = ""
                    break

            imgui.separator()

        # ── Keybind table ─────────────────────────────────────────
        filter_text = (self._kb_filter or "").lower()
        show_conflicts_only = getattr(self, '_kb_show_conflicts', False)

        imgui.begin_child("##keybind_list", 0, 0, border=False)

        categories = kb_reg.by_category()
        # Define display order
        _CAT_ORDER = [
            "Camera", "File", "Selection", "Display", "Layer", "Mode",
            "Tool Switch", "Hotbar", "Selection Ops", "Sculpt", "Select",
            "Entity", "Box", "Quad", "Stamp", "General",
        ]
        ordered_cats = []
        for cat in _CAT_ORDER:
            if cat in categories:
                ordered_cats.append((cat, categories[cat]))
        # Append any remaining categories not in the order list
        for cat, binds in categories.items():
            if cat not in _CAT_ORDER:
                ordered_cats.append((cat, binds))

        for cat_name, binds in ordered_cats:
            # Pre-filter: skip category if no binds match filter
            visible_binds = []
            for bind in binds:
                if show_conflicts_only and bind.action not in conflict_set:
                    continue
                if filter_text:
                    searchable = (
                        bind.action + bind.description + bind.key_label()
                        + bind.scope + bind.condition
                    ).lower()
                    if filter_text not in searchable:
                        continue
                visible_binds.append(bind)

            if not visible_binds:
                continue

            if imgui.collapsing_header(f"{cat_name}  ({len(visible_binds)})",
                                       imgui.TREE_NODE_DEFAULT_OPEN)[0]:
                # Column headers
                imgui.columns(4, f"##kb_{cat_name}", border=True)
                imgui.set_column_width(0, 170)
                imgui.set_column_width(1, 110)
                imgui.set_column_width(2, 100)
                # header row
                imgui.text_colored("Action", 0.6, 0.7, 0.8, 1.0)
                imgui.next_column()
                imgui.text_colored("Key", 0.6, 0.7, 0.8, 1.0)
                imgui.next_column()
                imgui.text_colored("Scope", 0.6, 0.7, 0.8, 1.0)
                imgui.next_column()
                imgui.text_colored("", 0.6, 0.7, 0.8, 1.0)
                imgui.next_column()
                imgui.separator()

                for bind in visible_binds:
                    is_conflict = bind.action in conflict_set
                    is_rebound = bind.is_rebound

                    # Description
                    if is_conflict:
                        imgui.text_colored(bind.description, 1.0, 0.45, 0.40, 1.0)
                    elif is_rebound:
                        imgui.text_colored(bind.description, 0.5, 0.85, 1.0, 1.0)
                    else:
                        imgui.text(bind.description)
                    imgui.next_column()

                    # Key binding (clickable to rebind)
                    label = bind.key_label()
                    btn_id = f"{label}##{bind.action}"
                    if is_conflict:
                        imgui.push_style_color(imgui.COLOR_BUTTON, 0.5, 0.15, 0.15, 0.8)
                    elif is_rebound:
                        imgui.push_style_color(imgui.COLOR_BUTTON, 0.15, 0.3, 0.5, 0.8)
                    else:
                        imgui.push_style_color(imgui.COLOR_BUTTON, 0.2, 0.2, 0.25, 0.6)

                    if imgui.button(btn_id, 95, 0):
                        self._kb_capturing = bind.action

                    imgui.pop_style_color()
                    imgui.next_column()

                    # Scope + condition
                    scope_text = bind.scope
                    if bind.condition:
                        scope_text += f" [{bind.condition}]"
                    imgui.text_colored(scope_text, 0.55, 0.55, 0.55, 1.0)
                    imgui.next_column()

                    # Reset button (only if rebound)
                    if is_rebound:
                        if imgui.small_button(f"Reset##{bind.action}"):
                            kb_reg.reset(bind.action)
                    elif is_conflict:
                        imgui.text_colored("!", 1.0, 0.4, 0.3, 1.0)
                    imgui.next_column()

                imgui.columns(1)

        imgui.end_child()
        imgui.end()

    def _draw_display_section(self, ed) -> None:
        self._section_header("\u2581 DISPLAY", 0.50, 0.60, 0.65)
        half_w = imgui.get_content_region_available()[0] * 0.5
        _, ed.show_walls = imgui.checkbox("Walls (Ct+1)", ed.show_walls)
        imgui.same_line(half_w)
        _, ed.show_floors = imgui.checkbox("Floors (Ct+2)", ed.show_floors)
        _, ed.show_ceilings = imgui.checkbox("Ceilings (Ct+3)", ed.show_ceilings)
        imgui.same_line(half_w)
        _, ed.show_axes = imgui.checkbox("Axes", ed.show_axes)
        _, ed.show_entities = imgui.checkbox("Entities (Ct+4)", ed.show_entities)
        imgui.same_line(half_w)
        _, ed.wireframe = imgui.checkbox("Wire (Ct+5)", ed.wireframe)

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
        imgui.set_next_window_position(win_w - self.right_panel_w, MENU_BAR_H + STATE_BAR_H)
        imgui.set_next_window_size(self.right_panel_w, win_h - MENU_BAR_H - STATE_BAR_H - STATUS_BAR_H)
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

        # Object inspectors — visible in ANY tool when an object is selected
        ed = self.editor_3d
        if ed:
            if ed._ent_selected is not None and zone.entities:
                self._draw_entity_inspector(zone)
            if ed._box_selected is not None and zone.boxes:
                self._draw_prism_inspector(zone)
            if ed._quad_selected is not None and zone.quads:
                self._draw_quad_inspector(zone)
            if ed._portal_selected is not None and zone.render_portals:
                self._draw_portal_inspector(zone)
            if ed._curve_selected is not None and zone.curves:
                self._draw_curve_inspector(zone)

        # Cell inspector — bulk mode for multi-selection, single mode for aimed
        sel = getattr(self.editor_3d, 'selection', None)
        sel_count = sel.cell_count() if sel and sel.has_cells() else 0
        if sel_count > 1:
            self._draw_bulk_inspector(zone, sel_count)
        elif self.editor_3d and self.editor_3d.aimed:
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
        """Draw the cell inspector for the currently aimed cell.

        All height / texture fields are **editable**.  When a selection
        is active the header shows a cell count and edits propagate to
        every selected cell.

        The inspector is **layer-stateful**: only active-layer data is
        shown.  PageUp/PageDown switches active layer.
        """
        ed = self.editor_3d
        hit = ed.aimed
        r, c = hit.row, hit.col
        active_layer = getattr(ed, 'active_layer', 1)
        pw = self.right_panel_w
        has_sel = ed._has_selection()
        sel_count = ed.selection.cell_count() if hasattr(ed, 'selection') and ed.selection.has_cells() else 0

        # ── Header ─────────────────────────────────────────────────
        if has_sel and sel_count > 0:
            hdr = f"{sel_count} Cells Selected  (aimed {r},{c})"
        else:
            hdr = f"Cell ({r}, {c})"
        if not imgui.collapsing_header(f"{hdr}##cell",
                                       imgui.TREE_NODE_DEFAULT_OPEN)[0]:
            return

        # ── Layer indicator badge ──────────────────────────────────
        if active_layer == 2:
            imgui.text_colored("[LAYER 2]", 0.78, 0.63, 1.0, 1.0)
        else:
            imgui.text_colored("[LAYER 1]", 0.55, 0.80, 0.55, 1.0)
        imgui.same_line()
        imgui.text_disabled("PgUp/PgDn")

        # "Apply Aimed Cell to Selection" button
        if has_sel:
            imgui.push_style_color(imgui.COLOR_BUTTON, 0.25, 0.55, 0.35, 1.0)
            imgui.push_style_color(imgui.COLOR_BUTTON_HOVERED, 0.30, 0.65, 0.40, 1.0)
            imgui.push_style_color(imgui.COLOR_BUTTON_ACTIVE, 0.20, 0.45, 0.30, 1.0)
            if imgui.button("Clone Aimed \u2192 Selection", pw - 30, 22):
                ed._apply_cell_to_selection()
                self.dirty = True
            imgui.pop_style_color(3)
            imgui.spacing()

        # ── Tile type ──────────────────────────────────────────────
        td_obj = tile_def(zone.tiles[r][c])
        tile_name = zone.tiles[r][c]
        is_wall = td_obj and td_obj.wall

        if active_layer == 1:
            # ── Layer 1: full tile type + geometry + textures ──────

            if is_wall:
                imgui.text_colored("WALL", 0.9, 0.4, 0.3, 1.0)
            else:
                imgui.text_colored("OPEN", 0.4, 0.8, 0.4, 1.0)
            imgui.same_line(65)
            if imgui.small_button("Toggle##wall_toggle"):
                ed._push_undo()
                ed._ensure_face_textures()
                if is_wall:
                    self._batch_set_cell_prop(
                        lambda _r, _c: ed._make_open_at(_r, _c), has_sel)
                else:
                    self._batch_set_cell_prop(
                        lambda _r, _c: ed._make_wall_at(_r, _c), has_sel)
                self.dirty = True

            # ── Geometry — Editable Heights ────────────────────────
            imgui.spacing()
            self._section_header("\u2581 GEOMETRY", 0.65, 0.80, 0.55, pad_top=False)
            imgui.push_item_width(pw - 90)

            fh = zone.floor_heights[r][c]
            ch = zone.ceil_heights[r][c]
            is_sky = ch >= 10.0 - 0.01

            # Floor height — editable
            changed_fh, new_fh = imgui.input_float(
                "Floor##insp_fh", fh, 0.25, 0.5, "%.3f")
            if changed_fh:
                new_fh = round(max(-5.0, min(10.0, new_fh)), 3)
                ed._push_undo()
                ed._ensure_face_textures()
                def _set_fh(rr, cc):
                    zone.floor_heights[rr][cc] = new_fh
                    ed._sync_tile_type(rr, cc)
                    return True
                self._batch_set_cell_prop(_set_fh, has_sel)
                self.dirty = True

            # Ceiling height — editable
            ceil_display = 10.0 if is_sky else ch
            changed_ch, new_ch = imgui.input_float(
                "Ceil##insp_ch", ceil_display, 0.25, 0.5, "%.3f")
            if changed_ch:
                new_ch = round(max(-5.0, min(10.0, new_ch)), 3)
                ed._push_undo()
                ed._ensure_face_textures()
                def _set_ch(rr, cc):
                    zone.ceil_heights[rr][cc] = new_ch
                    ed._sync_tile_type(rr, cc)
                    return True
                self._batch_set_cell_prop(_set_ch, has_sel)
                self.dirty = True

            # Sky toggle
            imgui.same_line()
            sky_label = "\u2600" if is_sky else "\u25a3"
            if imgui.small_button(f"{sky_label}##sky_toggle"):
                ed._push_undo()
                if is_sky:
                    def _add_ceil(rr, cc):
                        return ed._add_ceiling_at(rr, cc)
                    self._batch_set_cell_prop(_add_ceil, has_sel)
                else:
                    def _rem_ceil(rr, cc):
                        return ed._remove_ceiling_at(rr, cc)
                    self._batch_set_cell_prop(_rem_ceil, has_sel)
                self.dirty = True

            # Gap display (read-only)
            gap = ch - fh
            gap_col = (0.9, 0.3, 0.3, 1.0) if gap < 0.5 else (0.6, 0.6, 0.6, 1.0)
            imgui.text_disabled("Gap")
            imgui.same_line(55)
            imgui.text_colored(f"{gap:.2f}", *gap_col)

            # Upper wall height — editable
            uwh = 0.0
            if zone.upper_wall_height and len(zone.upper_wall_height) > r:
                uwh = zone.upper_wall_height[r][c]
            changed_uwh, new_uwh = imgui.input_float(
                "Upper Wall##insp_uwh", uwh, 0.25, 0.5, "%.3f")
            if changed_uwh:
                new_uwh = round(max(0.0, min(10.0, new_uwh)), 3)
                ed._push_undo()
                ed._ensure_face_textures()
                def _set_uwh(rr, cc):
                    if zone.upper_wall_height and len(zone.upper_wall_height) > rr:
                        zone.upper_wall_height[rr][cc] = new_uwh
                    return True
                self._batch_set_cell_prop(_set_uwh, has_sel)
                self.dirty = True

            imgui.pop_item_width()

            # ── Textures ───────────────────────────────────────────
            imgui.spacing()
            self._section_header("\u2581 TEXTURES", 0.75, 0.55, 0.85, pad_top=False)

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

            # Quick-paint buttons: apply current brush texture
            brush = ed.current_texture
            if brush:
                imgui.spacing()
                btn_w = (pw - 40) / 3.0
                if imgui.button(f"Set Floor##{brush}_sf", btn_w, 20):
                    ed._push_undo()
                    ed._ensure_face_textures()
                    def _set_ft(rr, cc):
                        if zone.floor_textures:
                            zone.floor_textures[rr][cc] = brush
                        return True
                    self._batch_set_cell_prop(_set_ft, has_sel)
                    self.dirty = True
                imgui.same_line()
                if imgui.button(f"Set Ceil##{brush}_sc", btn_w, 20):
                    ed._push_undo()
                    ed._ensure_face_textures()
                    def _set_ct(rr, cc):
                        if zone.ceil_textures:
                            zone.ceil_textures[rr][cc] = brush
                        return True
                    self._batch_set_cell_prop(_set_ct, has_sel)
                    self.dirty = True
                imgui.same_line()
                if imgui.button(f"Set Wall##{brush}_sw", btn_w, 20):
                    ed._push_undo()
                    ed._ensure_face_textures()
                    def _set_wt(rr, cc):
                        if zone.wall_textures and len(zone.wall_textures) > rr:
                            zone.wall_textures[rr][cc] = brush
                        for fi in range(4):
                            if zone.face_textures and len(zone.face_textures) > rr:
                                zone.face_textures[rr][cc][fi] = brush
                        return True
                    self._batch_set_cell_prop(_set_wt, has_sel)
                    self.dirty = True
                imgui.text_disabled(f"Brush: {brush}")

            # Face overrides (read-only list — use paint tool for per-face)
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

        else:
            # ── Layer 2: secondary floor/ceil geometry ─────────────
            imgui.spacing()
            self._section_header("\u2581 LAYER 2 GEOMETRY", 0.78, 0.63, 1.0, pad_top=False)
            imgui.push_item_width(pw - 90)

            LAYER_NONE = -1000.0
            f2 = getattr(zone, 'floor2_heights', None)
            c2 = getattr(zone, 'ceil2_heights', None)
            f2v = f2[r][c] if f2 and r < len(f2) and c < len(f2[r]) else LAYER_NONE
            c2v = c2[r][c] if c2 and r < len(c2) and c < len(c2[r]) else LAYER_NONE
            has_f2 = f2v > LAYER_NONE + 1.0
            has_c2 = c2v > LAYER_NONE + 1.0

            # Floor2 height — editable
            f2_display = f2v if has_f2 else 0.0
            changed_f2, new_f2 = imgui.input_float(
                "Floor2##insp_f2", f2_display, 0.25, 0.5, "%.3f")
            if changed_f2:
                new_f2 = round(max(-5.0, min(10.0, new_f2)), 3)
                ed._push_undo()
                ed._layer2_ensure_grids()
                def _set_f2(rr, cc):
                    zone.floor2_heights[rr][cc] = new_f2
                    return True
                self._batch_set_cell_prop(_set_f2, has_sel)
                self.dirty = True
            imgui.same_line()
            if has_f2:
                if imgui.small_button("\u2716##del_f2"):
                    ed._push_undo()
                    ed._layer2_ensure_grids()
                    zone.floor2_heights[r][c] = LAYER_NONE
                    zone.floor2_textures[r][c] = ""
                    self.dirty = True
            else:
                if imgui.small_button("+##add_f2"):
                    ed._push_undo()
                    ed._layer2_ensure_grids()
                    base = zone.floor_heights[r][c] if zone.floor_heights else 0.0
                    zone.floor2_heights[r][c] = round(base + 0.5, 3)
                    self.dirty = True

            # Ceil2 height — editable
            c2_display = c2v if has_c2 else 0.0
            changed_c2, new_c2 = imgui.input_float(
                "Ceil2##insp_c2", c2_display, 0.25, 0.5, "%.3f")
            if changed_c2:
                new_c2 = round(max(-5.0, min(10.0, new_c2)), 3)
                ed._push_undo()
                ed._layer2_ensure_grids()
                def _set_c2(rr, cc):
                    zone.ceil2_heights[rr][cc] = new_c2
                    return True
                self._batch_set_cell_prop(_set_c2, has_sel)
                self.dirty = True
            imgui.same_line()
            if has_c2:
                if imgui.small_button("\u2716##del_c2"):
                    ed._push_undo()
                    ed._layer2_ensure_grids()
                    zone.ceil2_heights[r][c] = LAYER_NONE
                    zone.ceil2_textures[r][c] = ""
                    self.dirty = True
            else:
                if imgui.small_button("+##add_c2"):
                    ed._push_undo()
                    ed._layer2_ensure_grids()
                    ch_val = zone.ceil_heights[r][c] if zone.ceil_heights else 1.0
                    zone.ceil2_heights[r][c] = round(ch_val - 0.25, 3)
                    self.dirty = True

            # Gap display
            if has_f2 and has_c2:
                gap2 = c2v - f2v
                gap_col = (0.9, 0.3, 0.3, 1.0) if gap2 < 0.5 else (0.6, 0.6, 0.6, 1.0)
                imgui.text_disabled("Gap")
                imgui.same_line(55)
                imgui.text_colored(f"{gap2:.2f}", *gap_col)

            imgui.pop_item_width()

            # ── Layer 2 Textures ───────────────────────────────────
            imgui.spacing()
            self._section_header("\u2581 TEXTURES", 0.75, 0.55, 0.85, pad_top=False)
            f2t = zone.floor2_textures[r][c] if getattr(zone, 'floor2_textures', None) else ""
            c2t = zone.ceil2_textures[r][c] if getattr(zone, 'ceil2_textures', None) else ""
            for lbl, tex in (("Floor2", f2t), ("Ceil2", c2t)):
                imgui.text_disabled(lbl)
                imgui.same_line(55)
                if tex:
                    imgui.text(tex)
                else:
                    imgui.text_colored("\u2014", 0.4, 0.4, 0.45, 1.0)
            brush = ed.current_texture
            if brush:
                imgui.spacing()
                btn_w = (pw - 40) / 2.0
                if imgui.button(f"Set F2##{brush}_sf2", btn_w, 20):
                    ed._push_undo()
                    ed._layer2_ensure_grids()
                    def _set_f2t(rr, cc):
                        zone.floor2_textures[rr][cc] = brush
                        return True
                    self._batch_set_cell_prop(_set_f2t, has_sel)
                    self.dirty = True
                imgui.same_line()
                if imgui.button(f"Set C2##{brush}_sc2", btn_w, 20):
                    ed._push_undo()
                    ed._layer2_ensure_grids()
                    def _set_c2t(rr, cc):
                        zone.ceil2_textures[rr][cc] = brush
                        return True
                    self._batch_set_cell_prop(_set_c2t, has_sel)
                    self.dirty = True
                imgui.text_disabled(f"Brush: {brush}")

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

            if ed.tool == "paint":
                tex = ed.current_texture or zone.tiles[r][c]
                cur = self._get_face_texture(zone, r, c, hit.part, hit.face)
                imgui.text_disabled("Brush")
                imgui.same_line(55)
                imgui.text(tex)
                imgui.text_disabled("Current")
                imgui.same_line(55)
                imgui.text(cur if cur else "\u2014")

        # ── Per-cell property sections ────────────────────────────
        self._draw_cell_properties(zone, r, c)

    # ── Bulk inspector (multi-cell selection) ─────────────────────

    def _draw_bulk_inspector(self, zone, sel_count: int) -> None:
        """Inspector for multi-cell selections: aggregated values, mixed detection,
        relative math inputs (+N, -N, =N, *N), paste masking."""
        ed = self.editor_3d
        pw = self.right_panel_w
        active_layer = getattr(ed, 'active_layer', 1)
        cells = list(ed.selection.cells)

        hdr = f"{sel_count} Cells Selected"
        if not imgui.collapsing_header(f"{hdr}##bulk",
                                       imgui.TREE_NODE_DEFAULT_OPEN)[0]:
            return

        # Layer badge
        if active_layer == 2:
            imgui.text_colored("[LAYER 2]", 0.78, 0.63, 1.0, 1.0)
        else:
            imgui.text_colored("[LAYER 1]", 0.55, 0.80, 0.55, 1.0)
        imgui.same_line()
        imgui.text_disabled("PgUp/PgDn")

        # ── Quick actions ─────────────────────────────────────────
        full_w = imgui.get_content_region_available()[0]
        btn_w3 = (full_w - imgui.get_style().item_spacing.x * 2) / 3
        if imgui.button("Clear##bulk_clr", btn_w3, 22):
            ed.selection.clear()
            ed._sel_start = None
            ed._sel_end = None
        imgui.same_line()
        if imgui.button("Ct+C##bulk_copy", btn_w3, 22):
            ed._clipboard_copy()
        imgui.same_line()
        if imgui.button("Ct+V##bulk_paste", btn_w3, 22):
            ed._clipboard_paste()

        imgui.spacing()

        if active_layer == 1:
            self._draw_bulk_layer1(zone, ed, cells, pw)
        else:
            self._draw_bulk_layer2(zone, ed, cells, pw)

        # ── Paste Mask ────────────────────────────────────────────
        imgui.spacing()
        self._section_header("\u2581 PASTE MASK", 0.55, 0.55, 0.65, pad_top=True)
        imgui.text_disabled("Controls which data Ctrl+V pastes:")
        mask = ed._paste_mask
        for flag, label in [
            (PASTE_MASK_HEIGHTS, "Heights"),
            (PASTE_MASK_TEXTURES, "Textures"),
            (PASTE_MASK_ENTITIES, "Entities"),
            (PASTE_MASK_SEGMENTS, "Segments"),
            (PASTE_MASK_LIGHTING, "Lighting"),
        ]:
            is_on = flag in mask
            changed, new_val = imgui.checkbox(f"{label}##pm_{flag}", is_on)
            if changed:
                if new_val:
                    mask.add(flag)
                else:
                    mask.discard(flag)

    def _draw_bulk_layer1(self, zone, ed, cells, pw) -> None:
        """Bulk inspector fields for Layer 1."""
        # ── Geometry ──────────────────────────────────────────────
        self._section_header("\u2581 GEOMETRY", 0.65, 0.80, 0.55, pad_top=False)
        imgui.push_item_width(pw - 90)

        # Floor heights
        floor_vals = _collect_cell_values(
            zone, cells, lambda z, r, c: z.floor_heights[r][c])
        fh_str, fh_mixed, fh_common = _summarise_values(floor_vals)
        if fh_mixed:
            imgui.text_disabled("Floor")
            imgui.same_line(55)
            imgui.text_colored("<Mixed>", 0.9, 0.7, 0.3, 1.0)
        else:
            imgui.text_disabled("Floor")
            imgui.same_line(55)
            imgui.text(fh_str)

        # Relative math input for floor
        fh_input = getattr(self, '_bulk_fh_input', "")
        changed, fh_input = imgui.input_text("##bulk_fh", fh_input, 32)
        if changed:
            self._bulk_fh_input = fh_input
        imgui.same_line()
        if imgui.small_button("Apply##bulk_fh_go"):
            vals = _parse_relative_value(
                getattr(self, '_bulk_fh_input', ''),
                [v for v in floor_vals if v is not None])
            if vals:
                ed._push_undo()
                ed._ensure_face_textures()
                idx = 0
                for r, c in cells:
                    if idx < len(vals):
                        zone.floor_heights[r][c] = round(
                            max(-5.0, min(10.0, vals[idx])), 3)
                        ed._sync_tile_type(r, c)
                    idx += 1
                self.dirty = True
                self._bulk_fh_input = ""

        # Ceiling heights
        ceil_vals = _collect_cell_values(
            zone, cells, lambda z, r, c: z.ceil_heights[r][c])
        ch_str, ch_mixed, ch_common = _summarise_values(ceil_vals)
        if ch_mixed:
            imgui.text_disabled("Ceil")
            imgui.same_line(55)
            imgui.text_colored("<Mixed>", 0.9, 0.7, 0.3, 1.0)
        else:
            imgui.text_disabled("Ceil")
            imgui.same_line(55)
            imgui.text(ch_str)

        ch_input = getattr(self, '_bulk_ch_input', "")
        changed, ch_input = imgui.input_text("##bulk_ch", ch_input, 32)
        if changed:
            self._bulk_ch_input = ch_input
        imgui.same_line()
        if imgui.small_button("Apply##bulk_ch_go"):
            vals = _parse_relative_value(
                getattr(self, '_bulk_ch_input', ''),
                [v for v in ceil_vals if v is not None])
            if vals:
                ed._push_undo()
                ed._ensure_face_textures()
                idx = 0
                for r, c in cells:
                    if idx < len(vals):
                        zone.ceil_heights[r][c] = round(
                            max(-5.0, min(10.0, vals[idx])), 3)
                        ed._sync_tile_type(r, c)
                    idx += 1
                self.dirty = True
                self._bulk_ch_input = ""

        imgui.pop_item_width()
        imgui.text_disabled("Syntax: +N  -N  *N  =N  or bare N")

        # ── Textures ──────────────────────────────────────────────
        imgui.spacing()
        self._section_header("\u2581 TEXTURES", 0.75, 0.55, 0.85, pad_top=False)

        wall_vals = _collect_cell_values(
            zone, cells, lambda z, r, c: z.wall_textures[r][c] if z.wall_textures else "")
        floor_tex = _collect_cell_values(
            zone, cells, lambda z, r, c: z.floor_textures[r][c] if z.floor_textures else "")
        ceil_tex = _collect_cell_values(
            zone, cells, lambda z, r, c: z.ceil_textures[r][c] if z.ceil_textures else "")

        for lbl, vals in [("Wall", wall_vals), ("Floor", floor_tex), ("Ceil", ceil_tex)]:
            disp, mixed, _ = _summarise_values(vals)
            imgui.text_disabled(lbl)
            imgui.same_line(55)
            if mixed:
                imgui.text_colored("<Mixed>", 0.9, 0.7, 0.3, 1.0)
            else:
                imgui.text(disp)

        # Quick-paint all selected
        brush = ed.current_texture
        if brush:
            imgui.spacing()
            btn_w = (pw - 40) / 3.0
            if imgui.button(f"Set Floor##{brush}_bf", btn_w, 20):
                ed._push_undo()
                ed._ensure_face_textures()
                for r, c in cells:
                    if zone.floor_textures:
                        zone.floor_textures[r][c] = brush
                self.dirty = True
            imgui.same_line()
            if imgui.button(f"Set Ceil##{brush}_bc", btn_w, 20):
                ed._push_undo()
                ed._ensure_face_textures()
                for r, c in cells:
                    if zone.ceil_textures:
                        zone.ceil_textures[r][c] = brush
                self.dirty = True
            imgui.same_line()
            if imgui.button(f"Set Wall##{brush}_bw", btn_w, 20):
                ed._push_undo()
                ed._ensure_face_textures()
                for r, c in cells:
                    if zone.wall_textures:
                        zone.wall_textures[r][c] = brush
                    if zone.face_textures:
                        for fi in range(4):
                            zone.face_textures[r][c][fi] = brush
                self.dirty = True
            imgui.text_disabled(f"Brush: {brush}")

        # ── Bulk light level ──────────────────────────────────────
        imgui.spacing()
        self._section_header("\u2581 LIGHTING", 0.60, 0.60, 0.50, pad_top=False)
        light_vals = _collect_cell_values(
            zone, cells,
            lambda z, r, c: z.light_levels[r][c]
            if z.light_levels and len(z.light_levels) > r and len(z.light_levels[r]) > c
            else 1.0)
        ll_str, ll_mixed, ll_common = _summarise_values(light_vals)
        imgui.text_disabled("Light")
        imgui.same_line(55)
        if ll_mixed:
            imgui.text_colored("<Mixed>", 0.9, 0.7, 0.3, 1.0)
        else:
            imgui.text(ll_str)

        imgui.push_item_width(pw - 90)
        ll_input = getattr(self, '_bulk_ll_input', "")
        changed, ll_input = imgui.input_text("##bulk_ll", ll_input, 32)
        if changed:
            self._bulk_ll_input = ll_input
        imgui.same_line()
        if imgui.small_button("Apply##bulk_ll_go"):
            vals = _parse_relative_value(
                getattr(self, '_bulk_ll_input', ''),
                [v for v in light_vals if v is not None])
            if vals:
                ed._push_undo()
                idx = 0
                for r, c in cells:
                    if (idx < len(vals) and zone.light_levels
                            and len(zone.light_levels) > r):
                        zone.light_levels[r][c] = round(
                            max(0.0, min(1.0, vals[idx])), 3)
                    idx += 1
                self.dirty = True
                self._bulk_ll_input = ""
        imgui.pop_item_width()

    def _draw_bulk_layer2(self, zone, ed, cells, pw) -> None:
        """Bulk inspector fields for Layer 2."""
        LAYER_NONE = -1000.0
        self._section_header("\u2581 LAYER 2 GEOMETRY", 0.78, 0.63, 1.0, pad_top=False)
        imgui.push_item_width(pw - 90)

        f2_vals = _collect_cell_values(
            zone, cells,
            lambda z, r, c: z.floor2_heights[r][c]
            if getattr(z, 'floor2_heights', None) and len(z.floor2_heights) > r
            else LAYER_NONE)
        c2_vals = _collect_cell_values(
            zone, cells,
            lambda z, r, c: z.ceil2_heights[r][c]
            if getattr(z, 'ceil2_heights', None) and len(z.ceil2_heights) > r
            else LAYER_NONE)

        for lbl, vals, attr in [("Floor2", f2_vals, "floor2_heights"),
                                ("Ceil2", c2_vals, "ceil2_heights")]:
            disp, mixed, common = _summarise_values(vals)
            imgui.text_disabled(lbl)
            imgui.same_line(55)
            if mixed:
                imgui.text_colored("<Mixed>", 0.9, 0.7, 0.3, 1.0)
            else:
                v = common if common is not None else LAYER_NONE
                if v <= LAYER_NONE + 1.0:
                    imgui.text_colored("(none)", 0.4, 0.4, 0.45, 1.0)
                else:
                    imgui.text(f"{v:.3f}")

            inp_key = f'_bulk_{attr}_input'
            inp_val = getattr(self, inp_key, "")
            changed, inp_val = imgui.input_text(f"##{attr}_bi", inp_val, 32)
            if changed:
                setattr(self, inp_key, inp_val)
            imgui.same_line()
            if imgui.small_button(f"Apply##{attr}_go"):
                raw = getattr(self, inp_key, '')
                numeric_vals = [v for v in vals if v is not None and v > LAYER_NONE + 1.0]
                if not numeric_vals:
                    numeric_vals = [0.0] * len(cells)
                new_vals = _parse_relative_value(raw, numeric_vals)
                if new_vals:
                    ed._push_undo()
                    ed._layer2_ensure_grids()
                    idx = 0
                    for r, c in cells:
                        if idx < len(new_vals):
                            getattr(zone, attr)[r][c] = round(
                                max(-5.0, min(10.0, new_vals[idx])), 3)
                        idx += 1
                    self.dirty = True
                    setattr(self, inp_key, "")

        imgui.pop_item_width()
        imgui.text_disabled("Syntax: +N  -N  *N  =N  or bare N")

    def _batch_set_cell_prop(self, fn, has_sel: bool) -> None:
        """Apply *fn(r, c)* to selection cells or aimed cell only."""
        ed = self.editor_3d
        if has_sel:
            ed._apply_to_selection(fn)
        else:
            hit = ed.aimed
            if hit:
                fn(hit.row, hit.col)

    def _draw_cell_properties(self, zone, r: int, c: int) -> None:
        """Draw per-cell property sections (light, reflect, layer2, fog).

        Light / reflect / fog sliders are always available so the user
        can tweak per-cell properties directly from the Inspector
        without needing a dedicated tool mode.
        """
        pw = self.right_panel_w

        # ── Light Level ───────────────────────────────────────────
        if zone.light_levels and len(zone.light_levels) > r and len(zone.light_levels[r]) > c:
            ll = zone.light_levels[r][c]
            imgui.spacing()
            imgui.text_disabled("Light")
            imgui.same_line(55)
            bright = min(1.0, ll)
            imgui.text_colored(f"{ll:.2f}", bright, bright, 0.4 + 0.6 * bright, 1.0)
            imgui.push_item_width(pw - 80)
            changed, new_ll = imgui.slider_float(
                "##light_slider", ll, 0.0, 1.0, "%.2f")
            imgui.pop_item_width()
            if changed:
                self.editor_3d._push_undo()
                zone.light_levels[r][c] = round(new_ll, 3)
                self.dirty = True

        # ── Reflectivity ──────────────────────────────────────────
        if zone.reflect_map and len(zone.reflect_map) > r and len(zone.reflect_map[r]) > c:
            rv = zone.reflect_map[r][c]
            imgui.spacing()
            imgui.text_disabled("Reflect")
            imgui.same_line(55)
            pct = rv / 255.0
            imgui.text_colored(f"{rv}", 0.4 + 0.6 * pct, 0.7 + 0.3 * pct, 1.0, 1.0)
            imgui.push_item_width(pw - 80)
            changed, new_rv = imgui.slider_int(
                "##reflect_slider", rv, 0, 255)
            imgui.pop_item_width()
            if changed:
                self.editor_3d._push_undo()
                zone.reflect_map[r][c] = new_rv
                self.dirty = True

        # ── Secondary Layer (floor2 / ceil2) ──────────────────────
        LAYER_NONE = -1000.0
        has_f2 = (zone.floor2_heights and len(zone.floor2_heights) > r
                  and zone.floor2_heights[r][c] > LAYER_NONE + 1.0)
        has_c2 = (zone.ceil2_heights and len(zone.ceil2_heights) > r
                  and zone.ceil2_heights[r][c] > LAYER_NONE + 1.0)
        show_l2 = has_f2 or has_c2 or (self.editor_3d and getattr(self.editor_3d, '_sculpt_layer2', False))
        if show_l2:
            imgui.spacing()
            imgui.text_disabled("Layer 2")
            if has_f2:
                f2h = zone.floor2_heights[r][c]
                f2t = zone.floor2_textures[r][c] if zone.floor2_textures else ""
                imgui.text_disabled("  F2")
                imgui.same_line(40)
                imgui.text(f"{f2h:.2f}")
                if f2t:
                    imgui.same_line()
                    imgui.text_disabled(f"({f2t})")
            if has_c2:
                c2h = zone.ceil2_heights[r][c]
                c2t = zone.ceil2_textures[r][c] if zone.ceil2_textures else ""
                imgui.text_disabled("  C2")
                imgui.same_line(40)
                imgui.text(f"{c2h:.2f}")
                if c2t:
                    imgui.same_line()
                    imgui.text_disabled(f"({c2t})")
            if self.editor_3d and getattr(self.editor_3d, '_sculpt_layer2', False):
                tgt = self.editor_3d._layer2_target
                imgui.text_disabled("  Target")
                imgui.same_line(60)
                imgui.text_colored(tgt, 0.8, 0.6, 1.0, 1.0)

        # ── Fog ───────────────────────────────────────────────────
        if hasattr(zone, "fog_density") and zone.fog_density and len(zone.fog_density) > r:
            fd = zone.fog_density[r][c]
            imgui.spacing()
            imgui.text_disabled("Fog")
            imgui.same_line(55)
            imgui.text(f"{fd:.2f}")
            imgui.push_item_width(pw - 80)
            changed, new_fd = imgui.slider_float(
                "##fog_slider", fd, 0.0, 1.0, "%.2f")
            imgui.pop_item_width()
            if changed:
                self.editor_3d._push_undo()
                zone.fog_density[r][c] = round(new_fd, 3)
                self.dirty = True

    def _draw_entity_inspector(self, zone) -> None:
        """Draw editable inspector for the currently selected entity."""
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

        # ID (read-only)
        imgui.text_disabled("ID")
        imgui.same_line(55)
        imgui.text(ent.get("id", "?"))

        # ── Editable Position ──
        imgui.push_item_width(self.right_panel_w - 80)

        ex = float(ent.get("x", 0.0))
        changed_x, new_x = imgui.input_float("X##einsp_x", ex, 0.1, 0.5, "%.3f")
        if changed_x:
            ent["x"] = round(max(0.1, min(zone.width - 0.1, new_x)), 3)
            self.dirty = True

        ey = float(ent.get("y", 0.0))
        changed_y, new_y = imgui.input_float("Z##einsp_y", ey, 0.1, 0.5, "%.3f")
        if changed_y:
            ent["y"] = round(max(0.1, min(zone.height - 0.1, new_y)), 3)
            self.dirty = True

        # ── Editable Angle ──
        angle = float(ent.get("angle", 0.0))
        deg = math.degrees(angle)
        label = angle_to_label(angle)
        changed_a, new_deg = imgui.slider_float(
            f"Angle ({label})##einsp_angle", deg, 0.0, 360.0, "%.0f\u00b0")
        if changed_a:
            from core.entity_defs import snap_angle_8dir
            ent["angle"] = snap_angle_8dir(math.radians(new_deg))
            self.dirty = True
        if edef and edef.directional:
            imgui.same_line()
            imgui.text_colored("\u27a4", 0.6, 0.8, 1.0, 1.0)

        # ── Editable State ──
        state = ent.get("state", "default")
        if edef and len(edef.states) > 1:
            states_list = list(edef.states)
            try:
                cur_idx = states_list.index(state)
            except ValueError:
                cur_idx = 0
            changed_s, new_idx = imgui.combo(
                "State##einsp_state", cur_idx, states_list)
            if changed_s:
                ent["state"] = states_list[new_idx]
                self.dirty = True
        else:
            imgui.text_disabled("State")
            imgui.same_line(55)
            imgui.text(state)

        # ── Editable Scale Override ──
        def_scale = edef.scale if edef else 0.5
        props = ent.setdefault("properties", {})
        cur_scale = float(props.get("scale", def_scale))
        changed_sc, new_scale = imgui.slider_float(
            "Scale##einsp_scale", cur_scale, 0.1, 3.0, "%.2f")
        if changed_sc:
            props["scale"] = round(new_scale, 2)
            self.dirty = True
        imgui.same_line()
        if imgui.small_button("Reset##einsp_scale_reset"):
            props.pop("scale", None)
            self.dirty = True

        imgui.pop_item_width()

        # ── Action buttons ──
        imgui.spacing()
        if imgui.button("Deselect##einsp_desel"):
            ed._ent_deselect()
        imgui.same_line()
        imgui.push_style_color(imgui.COLOR_BUTTON, 0.6, 0.15, 0.15, 1.0)
        if imgui.button("Delete##einsp_del"):
            ed._ent_delete(idx)
        imgui.pop_style_color()

        imgui.separator()

    def _draw_prism_inspector(self, zone) -> None:
        """Draw editable inspector for the currently selected prism."""
        ed = self.editor_3d
        idx = ed._box_selected
        if idx is None or idx < 0 or idx >= len(zone.boxes):
            return
        b = zone.boxes[idx]

        opened, _ = imgui.collapsing_header(
            f"Prism #{idx}##boxinsp", imgui.TREE_NODE_DEFAULT_OPEN)
        if not opened:
            return

        imgui.push_item_width(self.right_panel_w - 80)

        # Position
        bx = float(b.get("x", 0.0))
        changed, new_x = imgui.input_float("X##binsp_x", bx, 0.1, 0.5, "%.3f")
        if changed:
            ed._push_undo()
            b["x"] = round(max(0.1, min(zone.width - 0.1, new_x)), 3)
            self.dirty = True

        bz = float(b.get("y", 0.0))
        changed, new_z = imgui.input_float("Z##binsp_z", bz, 0.1, 0.5, "%.3f")
        if changed:
            ed._push_undo()
            b["y"] = round(max(0.1, min(zone.height - 0.1, new_z)), 3)
            self.dirty = True

        by = float(b.get("z", 0.0))
        changed, new_y = imgui.input_float("Base Y##binsp_by", by, 0.1, 0.5, "%.3f")
        if changed:
            ed._push_undo()
            b["z"] = round(new_y, 3)
            self.dirty = True

        # Dimensions
        bw = float(b.get("w", 1.0))
        changed, new_w = imgui.slider_float("Width##binsp_w", bw, 0.25, 8.0, "%.2f")
        if changed:
            b["w"] = round(new_w, 3)
            self.dirty = True

        bh = float(b.get("h", 1.0))
        changed, new_h = imgui.slider_float("Height##binsp_h", bh, 0.25, 8.0, "%.2f")
        if changed:
            b["h"] = round(new_h, 3)
            self.dirty = True

        bd = float(b.get("d", 1.0))
        changed, new_d = imgui.slider_float("Depth##binsp_d", bd, 0.25, 8.0, "%.2f")
        if changed:
            b["d"] = round(new_d, 3)
            self.dirty = True

        # Yaw
        yaw = float(b.get("yaw", 0.0))
        deg = math.degrees(yaw)
        changed, new_deg = imgui.slider_float("Yaw##binsp_yaw", deg, 0.0, 360.0, "%.0f\u00b0")
        if changed:
            b["yaw"] = round(math.radians(new_deg), 4)
            self.dirty = True

        # Collision
        col = bool(b.get("collision", True))
        changed, new_col = imgui.checkbox("Collision##binsp_col", col)
        if changed:
            b["collision"] = new_col
            self.dirty = True

        # Per-face textures
        textures = b.get("textures", {})
        if textures:
            imgui.spacing()
            imgui.text_disabled("Textures:")
            for face_key in ("N", "S", "E", "W", "top", "bot"):
                tex = textures.get(face_key, "")
                imgui.text_disabled(f"  {face_key:3s}")
                imgui.same_line(50)
                imgui.text(tex if tex else "\u2014")

        imgui.pop_item_width()

        imgui.spacing()
        if imgui.button("Deselect##binsp_desel"):
            ed._box_deselect()
        imgui.same_line()
        imgui.push_style_color(imgui.COLOR_BUTTON, 0.6, 0.15, 0.15, 1.0)
        if imgui.button("Delete##binsp_del"):
            ed._box_delete(idx)
        imgui.pop_style_color()

        imgui.separator()

    def _draw_quad_inspector(self, zone) -> None:
        """Draw editable inspector for the currently selected quad."""
        ed = self.editor_3d
        idx = ed._quad_selected
        if idx is None or idx < 0 or idx >= len(zone.quads):
            return
        q = zone.quads[idx]

        opened, _ = imgui.collapsing_header(
            f"Quad #{idx}##quadinsp", imgui.TREE_NODE_DEFAULT_OPEN)
        if not opened:
            return

        imgui.push_item_width(self.right_panel_w - 80)

        qx = float(q.get("x", 0.0))
        changed, new_x = imgui.input_float("X##qinsp_x", qx, 0.1, 0.5, "%.3f")
        if changed:
            q["x"] = round(max(0.1, min(zone.width - 0.1, new_x)), 3)
            self.dirty = True

        qz = float(q.get("z", 0.0))
        changed, new_z = imgui.input_float("Z##qinsp_z", qz, 0.1, 0.5, "%.3f")
        if changed:
            q["z"] = round(max(0.1, min(zone.height - 0.1, new_z)), 3)
            self.dirty = True

        by = float(q.get("base_y", 0.0))
        changed, new_by = imgui.input_float("Base Y##qinsp_by", by, 0.1, 0.5, "%.3f")
        if changed:
            q["base_y"] = round(new_by, 3)
            self.dirty = True

        w = float(q.get("width", 1.0))
        changed, new_w = imgui.slider_float("Width##qinsp_w", w, 0.25, 5.0, "%.2f")
        if changed:
            q["width"] = round(new_w, 3)
            self.dirty = True

        h = float(q.get("height", 1.0))
        changed, new_h = imgui.slider_float("Height##qinsp_h", h, 0.25, 5.0, "%.2f")
        if changed:
            q["height"] = round(new_h, 3)
            self.dirty = True

        angle = float(q.get("angle", 0.0))
        deg = math.degrees(angle)
        changed, new_deg = imgui.slider_float("Angle##qinsp_a", deg, 0.0, 360.0, "%.0f\u00b0")
        if changed:
            q["angle"] = round(math.radians(new_deg), 4)
            self.dirty = True

        tex = q.get("texture", "")
        imgui.text_disabled("Tex")
        imgui.same_line(55)
        imgui.text(tex if tex else "\u2014")

        ts = bool(q.get("two_sided", True))
        changed, new_ts = imgui.checkbox("Two-sided##qinsp_ts", ts)
        if changed:
            q["two_sided"] = new_ts
            self.dirty = True

        col = bool(q.get("collision", False))
        changed, new_col = imgui.checkbox("Collision##qinsp_col", col)
        if changed:
            q["collision"] = new_col
            self.dirty = True

        imgui.pop_item_width()

        imgui.spacing()
        if imgui.button("Deselect##qinsp_desel"):
            ed._quad_deselect()
        imgui.same_line()
        imgui.push_style_color(imgui.COLOR_BUTTON, 0.6, 0.15, 0.15, 1.0)
        if imgui.button("Delete##qinsp_del"):
            ed._quad_delete(idx)
        imgui.pop_style_color()
        imgui.separator()

    def _draw_portal_inspector(self, zone) -> None:
        """Draw editable inspector for the currently selected render portal."""
        ed = self.editor_3d
        idx = ed._portal_selected
        if idx is None or idx < 0 or idx >= len(zone.render_portals):
            return
        p = zone.render_portals[idx]

        opened, _ = imgui.collapsing_header(
            f"Portal #{idx}##pinsp", imgui.TREE_NODE_DEFAULT_OPEN)
        if not opened:
            return

        cell = p.get("cell", [0, 0])
        face = int(p.get("face", 0))
        face_names = ["N", "S", "E", "W"]
        fn = face_names[face] if 0 <= face < 4 else "?"
        imgui.text_disabled("Source")
        imgui.same_line(55)
        imgui.text(f"({cell[0]},{cell[1]}) {fn}")

        imgui.push_item_width(self.right_panel_w - 80)

        dx = float(p.get("dest_x", 0.0))
        changed, new_dx = imgui.input_float("Dest X##pinsp_dx", dx, 0.5, 1.0, "%.2f")
        if changed:
            ed._push_undo()
            p["dest_x"] = round(new_dx, 2)
            self.dirty = True

        dy = float(p.get("dest_y", 0.0))
        changed, new_dy = imgui.input_float("Dest Y##pinsp_dy", dy, 0.5, 1.0, "%.2f")
        if changed:
            ed._push_undo()
            p["dest_y"] = round(new_dy, 2)
            self.dirty = True

        ao = float(p.get("angle_offset", 0.0))
        deg = math.degrees(ao)
        changed, new_deg = imgui.slider_float(
            "Angle Off##pinsp_ao", deg, -180.0, 180.0, "%.0f\u00b0")
        if changed:
            ed._push_undo()
            p["angle_offset"] = round(math.radians(new_deg), 4)
            self.dirty = True

        imgui.pop_item_width()

        imgui.spacing()
        if imgui.button("Deselect##pinsp_desel"):
            ed._portal_deselect()
        imgui.same_line()
        imgui.push_style_color(imgui.COLOR_BUTTON, 0.6, 0.15, 0.15, 1.0)
        if imgui.button("Delete##pinsp_del"):
            ed._push_undo()
            zone.render_portals.pop(idx)
            ed._portal_selected = None
            self.dirty = True
        imgui.pop_style_color()
        imgui.separator()

    def _draw_curve_inspector(self, zone) -> None:
        """Draw editable inspector for the currently selected curve."""
        ed = self.editor_3d
        idx = ed._curve_selected
        if idx is None or idx < 0 or idx >= len(zone.curves):
            return
        cv = zone.curves[idx]

        opened, _ = imgui.collapsing_header(
            f"Curve #{idx}##cinsp", imgui.TREE_NODE_DEFAULT_OPEN)
        if not opened:
            return

        imgui.push_item_width(self.right_panel_w - 80)

        cx = float(cv.get("cx", 0.0))
        changed, new_cx = imgui.input_float("CX##cinsp_cx", cx, 0.1, 0.5, "%.3f")
        if changed:
            cv["cx"] = round(new_cx, 3)
            self.dirty = True

        cy = float(cv.get("cy", 0.0))
        changed, new_cy = imgui.input_float("CY##cinsp_cy", cy, 0.1, 0.5, "%.3f")
        if changed:
            cv["cy"] = round(new_cy, 3)
            self.dirty = True

        rad = float(cv.get("radius", 1.0))
        changed, new_rad = imgui.slider_float("Radius##cinsp_r", rad, 0.25, 10.0, "%.2f")
        if changed:
            cv["radius"] = round(new_rad, 3)
            self.dirty = True

        a_s = math.degrees(float(cv.get("angle_start", 0.0)))
        changed, new_as = imgui.slider_float("Arc Start##cinsp_as", a_s, 0.0, 360.0, "%.0f\u00b0")
        if changed:
            cv["angle_start"] = round(math.radians(new_as), 4)
            self.dirty = True

        a_e = math.degrees(float(cv.get("angle_end", 180.0)))
        changed, new_ae = imgui.slider_float("Arc End##cinsp_ae", a_e, 0.0, 360.0, "%.0f\u00b0")
        if changed:
            cv["angle_end"] = round(math.radians(new_ae), 4)
            self.dirty = True

        hs = float(cv.get("height_scale", 1.0))
        changed, new_hs = imgui.slider_float("Height##cinsp_h", hs, 0.25, 5.0, "%.2f")
        if changed:
            cv["height_scale"] = round(new_hs, 3)
            self.dirty = True

        by = float(cv.get("base_y", 0.0))
        changed, new_by = imgui.input_float("Base Y##cinsp_by", by, 0.1, 0.5, "%.3f")
        if changed:
            cv["base_y"] = round(new_by, 3)
            self.dirty = True

        tex = cv.get("texture", "")
        imgui.text_disabled("Tex")
        imgui.same_line(55)
        imgui.text(tex if tex else "\u2014")

        imgui.pop_item_width()

        imgui.spacing()
        if imgui.button("Deselect##cinsp_desel"):
            ed._curve_deselect()
        imgui.same_line()
        imgui.push_style_color(imgui.COLOR_BUTTON, 0.6, 0.15, 0.15, 1.0)
        if imgui.button("Delete##cinsp_del"):
            ed._curve_delete(idx)
        imgui.pop_style_color()
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

                # Mode indicator
                mode = getattr(ed, 'mode', 'arch')
                mode_lbl = MODE_LABELS.get(mode, mode.upper())
                _mc = MODE_COLORS.get(mode, (128, 128, 128))
                mr, mg, mb = _mc[0] / 255.0, _mc[1] / 255.0, _mc[2] / 255.0
                imgui.text_colored(mode_lbl, mr, mg, mb, 1.0)
                imgui.same_line()
                imgui.text_colored("\u2022", 0.3, 0.3, 0.35, 1.0)
                imgui.same_line()

                # Tool indicator
                r, g, b = [c / 255.0 for c in TOOL_COLORS[ed.tool]]
                imgui.text_colored(TOOL_LABELS[ed.tool], r, g, b, 1.0)

                # Layer indicator
                imgui.same_line()
                active_l = getattr(ed, 'active_layer', 1)
                if active_l == 2:
                    imgui.text_colored("  L2", 0.78, 0.63, 1.0, 1.0)
                else:
                    imgui.text_colored("  L1", 0.55, 0.80, 0.55, 1.0)

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
