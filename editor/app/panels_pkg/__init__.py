"""editor/app/panels_pkg — Split PanelsMixin into focused sub-modules.

Public API
----------
``from editor.app.panels_pkg import PanelsMixin``

Sub-modules
-----------
- menu_bar   — top menu bar (File / Edit / View / Assets)
- toolbox    — left panel (modes, tools, palettes, snap, controls)
- inspectors — right panel cell + object inspectors
- overlays   — help overlay, keybind editor
"""

from __future__ import annotations

import math

import pygame
import imgui

from core.tiles import TILE_COLORS
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

from editor.app.panels_pkg.menu_bar import MenuBarMixin
from editor.app.panels_pkg.toolbox import ToolboxMixin
from editor.app.panels_pkg.inspectors import InspectorMixin
from editor.app.panels_pkg.overlays import OverlaysMixin


class PanelsMixin(MenuBarMixin, ToolboxMixin, InspectorMixin, OverlaysMixin):
    """ImGui sidebar panels, status bar, and overlays for :class:`ZoneEditorApp`.

    This class composes the four focused sub-mixins and retains the
    shared layout / utility methods that are called from multiple
    sub-modules.
    """

    _SNAP_LABELS = ("1/16", "1/8", "1/4", "1/2", "1")

    # ── UI entry point ────────────────────────────────────────────

    def _build_ui(self) -> None:
        self._menu_bar()
        self._global_state_bar()
        self._left_panel()
        self._properties_panel()
        self._status_bar()
        self._draw_validation_hud()
        self._draw_splitters()
        if self.show_new_zone:
            self._new_zone_dialog()
        if self.show_save_as:
            self._save_as_dialog()
        if self._show_unsaved_guard:
            self._unsaved_guard_dialog()
        if not self.mouse_captured:
            self._capture_hint()
        if self._transient_time > 0:
            self._draw_transient_indicator()
        # Keyboard shortcut help overlay (? key)
        if self.editor_3d and self.editor_3d._show_help:
            self._draw_help_overlay()
        # Keybind editor window
        if self.show_keybind_editor and self.editor_3d:
            self._draw_keybind_editor()
        # Texture browser window
        if self.show_texture_browser:
            self._draw_texture_browser()
        # Resize zone dialog
        if self.show_resize_zone:
            self._resize_zone_dialog()
        # Find / Replace texture window
        if self.show_find_replace_tex:
            self._find_replace_texture_dialog()
        # Validate zone window
        if self.show_validate_zone:
            self._validate_zone_dialog()
        # Zone settings dialog
        if self.show_zone_settings:
            self._zone_settings_dialog()
        # Duplicate zone dialog
        if self.show_duplicate_zone:
            self._duplicate_zone_dialog()
        # Export top-down image dialog
        if self.show_export_image:
            self._export_image_dialog()
        # Data viewer windows
        if self.show_entity_defs_viewer:
            self._draw_entity_defs_viewer()
        if self.show_items_viewer:
            self._draw_items_viewer()
        if self.show_loot_tables_viewer:
            self._draw_loot_tables_viewer()
        if self.show_presets_viewer:
            self._draw_presets_viewer()
        if self.show_entity_textures:
            self._draw_entity_textures()
        if self.show_entity_creator:
            self._draw_entity_creator()

    # ── Shared helpers ────────────────────────────────────────────

    def _kb_label(self, action: str) -> str:
        """Return the effective keybind label for *action* from the registry."""
        ed = self.editor_3d
        if not ed:
            return ""
        kb = ed.kb.get(action)
        return kb.key_label() if kb else ""

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

    # ── Persistent validation HUD ─────────────────────────────────

    _VALIDATION_HUD_H = 26

    def _draw_validation_hud(self) -> None:
        """Persistent bar above the status-bar showing last-save validation issues."""
        issues = getattr(self, "_save_issues", None)
        if not issues:
            return
        n_err = sum(1 for i in issues if i.severity == "error")
        n_warn = sum(1 for i in issues if i.severity == "warning")
        if n_err == 0 and n_warn == 0:
            return

        win_w, win_h = self.win_size
        bar_y = win_h - STATUS_BAR_H - self._VALIDATION_HUD_H
        imgui.set_next_window_position(0, bar_y)
        imgui.set_next_window_size(win_w, self._VALIDATION_HUD_H)
        flags = (imgui.WINDOW_NO_MOVE | imgui.WINDOW_NO_RESIZE
                 | imgui.WINDOW_NO_TITLE_BAR | imgui.WINDOW_NO_SCROLLBAR
                 | imgui.WINDOW_NO_SCROLL_WITH_MOUSE | imgui.WINDOW_NO_COLLAPSE
                 | imgui.WINDOW_NO_FOCUS_ON_APPEARING | imgui.WINDOW_NO_NAV)
        bg = (0.20, 0.08, 0.04, 0.97) if n_err else (0.18, 0.14, 0.03, 0.97)
        imgui.push_style_color(imgui.COLOR_WINDOW_BACKGROUND, *bg)
        imgui.begin("##ValidationHUD", flags=flags)

        # Icon + summary
        parts: list[str] = []
        if n_err:
            parts.append(f"{n_err} error{'s' * (n_err > 1)}")
        if n_warn:
            parts.append(f"{n_warn} warning{'s' * (n_warn > 1)}")
        summary = "\u26a0  " + ", ".join(parts)
        col = (1.0, 0.45, 0.25, 1.0) if n_err else (0.95, 0.78, 0.30, 1.0)
        imgui.text_colored(summary, *col)

        # "Details" button opens the validate-zone dialog
        imgui.same_line()
        if imgui.small_button("Details"):
            # Pass ZoneIssue list directly to the validate dialog
            self._validate_results = list(issues)
            self.show_validate_zone = True

        # Dismiss button
        imgui.same_line()
        if imgui.small_button("\u00d7"):
            self._save_issues = []

        imgui.end()
        imgui.pop_style_color()

    # ── Global state bar (Layer + View mode) ──────────────────────

    def _global_state_bar(self) -> None:
        """Draw the global state bar — single row:

        Layer selector | Isolate | View | Tab switch | Undo/Redo/Save | Keybinds | Help | Clipboard
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
        active_layer = ed.active_layer if ed else 1
        isolate = ed.isolate_layer if ed else False

        is_l1 = active_layer == 1
        if is_l1:
            imgui.push_style_color(imgui.COLOR_BUTTON, 0.22, 0.55, 0.30, 1.0)
            imgui.push_style_color(imgui.COLOR_BUTTON_HOVERED, 0.28, 0.65, 0.38, 1.0)
        _l1k = self._kb_label("layer.down")
        if imgui.button(f"{_l1k} L1##layer1", 0, 20):
            if ed:
                ed.active_layer = 1
        if is_l1:
            imgui.pop_style_color(2)
        imgui.same_line()

        is_l2 = active_layer == 2
        if is_l2:
            imgui.push_style_color(imgui.COLOR_BUTTON, 0.50, 0.35, 0.70, 1.0)
            imgui.push_style_color(imgui.COLOR_BUTTON_HOVERED, 0.60, 0.42, 0.80, 1.0)
        _l2k = self._kb_label("layer.up")
        if imgui.button(f"{_l2k} L2##layer2", 0, 20):
            if ed:
                ed.active_layer = 2
        if is_l2:
            imgui.pop_style_color(2)
        imgui.same_line()

        if isolate:
            imgui.push_style_color(imgui.COLOR_BUTTON, 0.70, 0.25, 0.25, 1.0)
            imgui.push_style_color(imgui.COLOR_BUTTON_HOVERED, 0.80, 0.35, 0.35, 1.0)
        _iso_k = self._kb_label("display.isolate")
        if imgui.button(f"{_iso_k} Iso##iso", 0, 20):
            if ed:
                ed.isolate_layer = not ed.isolate_layer
        if isolate:
            imgui.pop_style_color(2)

        # ── Separator ─────────────────────────────────────────────
        imgui.same_line()
        imgui.text_colored("|", 0.3, 0.3, 0.35, 1.0)
        imgui.same_line()

        # ── View mode (Lit / Pathing) ─────────────────────────────
        view_3d = ed.view_mode_3d if ed else VIEW_LIT
        for vm in VIEW_MODES:
            is_active = view_3d == vm
            if is_active:
                imgui.push_style_color(imgui.COLOR_BUTTON, 0.25, 0.45, 0.65, 1.0)
                imgui.push_style_color(imgui.COLOR_BUTTON_HOVERED, 0.30, 0.55, 0.75, 1.0)
            if imgui.button(f"{VIEW_LABELS[vm]}##vm_{vm}", 0, 20):
                if ed:
                    ed.view_mode_3d = vm
            if is_active:
                imgui.pop_style_color(2)
            imgui.same_line()

        # ── View switch (Tab) ─────────────────────────────────────
        imgui.text_colored("|", 0.3, 0.3, 0.35, 1.0)
        imgui.same_line()
        _tab_k = self._kb_label("view.toggle")
        mode_label = "\u25b6 Preview" if self.view_mode == "3d" else "\u270e Editor"
        if imgui.button(f"{_tab_k} {mode_label}##viewswitch", 0, 20):
            self._toggle_view_mode()

        # ── Separator ─────────────────────────────────────────────
        imgui.same_line()
        imgui.text_colored("|", 0.3, 0.3, 0.35, 1.0)
        imgui.same_line()

        # ── Quick actions: Undo / Redo / Save ─────────────────────
        imgui.push_style_color(imgui.COLOR_BUTTON, 0.15, 0.15, 0.20, 0.7)
        imgui.push_style_color(imgui.COLOR_BUTTON_HOVERED, 0.25, 0.25, 0.32, 0.9)
        _undo_k = self._kb_label("edit.undo")
        if imgui.button(f"{_undo_k} \u21b6##undo", 0, 20):
            if ed:
                ed._undo()
        imgui.same_line()
        _redo_k = self._kb_label("edit.redo_cy")
        if imgui.button(f"{_redo_k} \u21b7##redo", 0, 20):
            if ed:
                ed._redo()
        imgui.same_line()
        imgui.pop_style_color(2)

        if self.dirty:
            imgui.push_style_color(imgui.COLOR_BUTTON, 0.55, 0.35, 0.10, 0.9)
            imgui.push_style_color(imgui.COLOR_BUTTON_HOVERED, 0.65, 0.45, 0.15, 1.0)
        else:
            imgui.push_style_color(imgui.COLOR_BUTTON, 0.15, 0.15, 0.20, 0.7)
            imgui.push_style_color(imgui.COLOR_BUTTON_HOVERED, 0.25, 0.25, 0.32, 0.9)
        _save_k = self._kb_label("file.save")
        if imgui.button(f"{_save_k} \U0001f4be##save", 0, 20):
            self._save_zone()
        imgui.pop_style_color(2)

        # ── Separator ─────────────────────────────────────────────
        imgui.same_line()
        imgui.text_colored("|", 0.3, 0.3, 0.35, 1.0)
        imgui.same_line()

        # ── Keybind editor + Help ─────────────────────────────────
        kb_open = self.show_keybind_editor
        if kb_open:
            imgui.push_style_color(imgui.COLOR_BUTTON, 0.35, 0.25, 0.55, 0.9)
            imgui.push_style_color(imgui.COLOR_BUTTON_HOVERED, 0.45, 0.35, 0.65, 1.0)
        else:
            imgui.push_style_color(imgui.COLOR_BUTTON, 0.15, 0.15, 0.20, 0.7)
            imgui.push_style_color(imgui.COLOR_BUTTON_HOVERED, 0.25, 0.25, 0.32, 0.9)
        if imgui.button("\u2699##kbbtn", 0, 20):
            self.show_keybind_editor = not kb_open
        imgui.pop_style_color(2)

        imgui.same_line()
        if imgui.button("?##helpbtn", 0, 20):
            if ed:
                ed._show_help = not ed._show_help

        # ── Right side: clipboard indicator ───────────────────────
        if ed and ed._clipboard:
            imgui.same_line()
            clip_w = imgui.calc_text_size("\U0001f4cb")[0] + 8
            imgui.same_line(max(0.0, win_w - clip_w - 8))
            imgui.text_colored("\U0001f4cb", 0.6, 0.6, 0.5, 1.0)

        imgui.end()
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
            ow_sel = getattr(ed, '_ow_selected', None)
            if ow_sel is not None and zone.overlay_walls:
                self._draw_overlay_wall_inspector(zone)

        # Cell inspector — bulk mode for multi-selection, single mode for aimed
        sel = getattr(self.editor_3d, 'selection', None)
        sel_count = sel.cell_count() if sel and sel.has_cells() else 0
        if sel_count > 1:
            self._draw_bulk_inspector(zone, sel_count)
        elif self.editor_3d and self.editor_3d.aimed:
            self._draw_cell_inspector(zone)
        else:
            imgui.text_colored("Aim at a cell to inspect", 0.45, 0.45, 0.5, 1.0)

        # Display options (FOV, visibility toggles)
        imgui.spacing()
        if self.editor_3d:
            self._draw_display_section(self.editor_3d)

        # Zone settings
        imgui.spacing()
        self._section_header("\u2581 ZONE SETTINGS", 0.65, 0.60, 0.50)
        self._draw_zone_settings(zone)

        # Camera
        if self.editor_3d:
            self._draw_camera_info()

        imgui.end()

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

                # World position
                imgui.same_line()
                imgui.text_disabled(
                    f"  Pos:({ed.cam_x:.1f}, {ed.cam_y:.1f}, {ed.cam_z:.1f})")

                # Selection count
                sel = getattr(ed, 'selection', None)
                sc = sel.cell_count() if sel and sel.has_cells() else 0
                if sc > 0:
                    imgui.same_line()
                    imgui.text_colored(f"  Sel:{sc}", 0.3, 0.9, 1.0, 1.0)

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
