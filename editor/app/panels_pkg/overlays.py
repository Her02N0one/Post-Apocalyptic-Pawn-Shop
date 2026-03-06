"""editor/app/panels_pkg/overlays.py — Help overlay and keybind editor."""

from __future__ import annotations

import math

import pygame
import imgui


class OverlaysMixin:
    """Floating overlays: keyboard shortcuts, keybind editor."""

    def _draw_help_overlay(self) -> None:
        """Floating keyboard shortcut reference (toggled with ? key).

        All key labels are pulled dynamically from the keybind registry
        so they stay correct even after rebinding.
        """
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

        k = self._kb_label  # shorthand

        _HELP = [
            ("MODES", [
                (k("mode.arch"),    "Architecture mode (sculpt, segment)"),
                (k("mode.surface"), "Surface mode (paint)"),
                (k("mode.props"),   "Props mode (prism, quad, curve)"),
                (k("mode.logic"),   "Logic mode (entity, portal)"),
            ]),
            ("LAYERS", [
                (f"{k('layer.down')}/{k('layer.up')}", "Switch active layer (1/2)"),
                (k("display.isolate"), "Isolate active layer"),
            ]),
            ("SELECTION", [
                (k("tool.select"),     "Enter/exit select mode"),
                ("LMB+LMB",           "Rectangle select (two clicks)"),
                ("Sh+LMB",            "Line select / add to selection"),
                ("Ct+LMB",            "Toggle individual cell"),
                (k("select.all"),      "Select all cells"),
                (k("select.similar"),  "Select similar (match properties)"),
                ("Esc",               "Clear selection"),
                (k("sel.ceil_mode"),   "Toggle floor/ceiling mode"),
            ]),
            ("CLIPBOARD", [
                (k("edit.copy"),  "Copy cell state to clipboard"),
                (k("edit.paste"), "Paste clipboard (respects paste mask)"),
            ]),
            ("DISPLAY", [
                (k("display.walls_c"),     "Toggle walls"),
                (k("display.floors_c"),    "Toggle floors"),
                (k("display.ceilings_c"),  "Toggle ceilings"),
                (k("display.entities_c"),  "Toggle entities"),
                (k("display.wireframe_c"), "Toggle wireframe"),
                (k("display.axes"),        "Toggle axes"),
                (k("display.isolate"),     "Isolate layer"),
            ]),
            ("GLOBAL", [
                (k("file.save"),  "Save"),
                (k("edit.undo"),  "Undo"),
                (k("edit.redo_cy"), "Redo"),
                (k("view.toggle"), "Toggle 3D / Preview"),
                ("?",             "This help overlay"),
                ("Esc",          "Deselect / cancel / release mouse"),
            ]),
            ("SCULPT", [
                ("LMB/RMB",         "Raise/lower floor"),
                ("Sh+LMB/RMB",      "Lower/raise ceiling"),
                ("Scroll",           "Extend / adjust"),
                (f"{k('sculpt.toggle_ceiling')}/Sh+{k('sculpt.toggle_ceiling')}", "Add / remove ceiling"),
                (f"{k('sculpt.make_wall')}/{k('sculpt.make_open')}", "Make wall / open"),
                (f"{k('sel.flatten_floors')}/{k('sel.flatten_ceilings')}", "Flatten floor / ceiling (sel)"),
                (f"{k('sculpt.raise_upper_wall')}/{k('sculpt.lower_upper_wall')}", "Raise / lower upper wall"),
                (k("sculpt.reset_upper_wall"), "Reset upper wall height"),
                (k("sculpt.reset_floor"),      "Reset height"),
                (k("sculpt.cycle_grid"),       "Cycle snap grid"),
            ]),
            ("PAINT", [
                ("LMB",             "Paint face"),
                ("Sh+LMB",          "Paint whole cell"),
                ("Ct+LMB",          "Flood fill"),
                ("RMB",             "Erase texture"),
                ("MMB",             "Eyedropper"),
                ("Scroll",          "Cycle palette"),
            ]),
            ("OBJECTS", [
                ("LMB",              "Place / select"),
                ("Ct+LMB",           "Toggle multi-select"),
                ("Sh+LMB",           "Add to selection"),
                ("RMB",              "Deselect / delete"),
                ("Del",              "Delete selected (any tool)"),
                ("R",                "Rotate 90\u00b0 (prism)"),
                ("Scroll",           "Type-specific adjust"),
            ]),
        ]

        for section, binds in _HELP:
            if imgui.collapsing_header(section, imgui.TREE_NODE_DEFAULT_OPEN)[0]:
                for key, desc in binds:
                    if not key:         # skip if registry returned ""
                        continue
                    imgui.push_style_color(imgui.COLOR_TEXT, 0.90, 0.80, 0.45, 1.0)
                    imgui.text(f"  {key:14s}")
                    imgui.pop_style_color()
                    imgui.same_line(140)
                    imgui.text(desc)

        imgui.end()

    # ── Keybind editor window ─────────────────────────────────────

    def _draw_keybind_editor(self) -> None:
        """Floating keybind editor with conflict detection and rebinding."""
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
        capturing = self._kb_capturing
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
        show_conflicts_only = self._kb_show_conflicts

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
