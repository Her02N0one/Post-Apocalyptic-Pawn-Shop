"""editor/app/dialogs.py — DialogsMixin: modal dialogs (new zone, save-as, unsaved guard)."""

from __future__ import annotations

import imgui


class DialogsMixin:
    """Modal dialog windows for :class:`ZoneEditorApp`."""

    # ── Unsaved-changes guard ─────────────────────────────────────

    def _unsaved_guard_dialog(self) -> None:
        """Modal dialog: Save / Discard / Cancel when about to lose unsaved changes."""
        imgui.open_popup("Unsaved Changes")

        win_w, win_h = self.win_size
        imgui.set_next_window_position(win_w / 2 - 190, win_h / 2 - 70)
        imgui.set_next_window_size(380, 0)

        if imgui.begin_popup_modal("Unsaved Changes",
                                   flags=imgui.WINDOW_ALWAYS_AUTO_RESIZE)[0]:
            imgui.text("You have unsaved changes to")
            imgui.text_colored(f'"{self.zone_name}"', 1.0, 0.9, 0.5, 1.0)
            imgui.text("What would you like to do?")
            imgui.spacing()
            imgui.separator()
            imgui.spacing()

            btn_w = 110

            # Save
            if imgui.button("Save", btn_w, 30):
                self._save_zone()
                if not self.dirty:
                    self._show_unsaved_guard = False
                    self._execute_guarded_action()
                    imgui.close_current_popup()

            imgui.same_line()

            # Discard
            imgui.push_style_color(imgui.COLOR_BUTTON, 0.55, 0.18, 0.18, 1.0)
            imgui.push_style_color(imgui.COLOR_BUTTON_HOVERED, 0.70, 0.25, 0.25, 1.0)
            imgui.push_style_color(imgui.COLOR_BUTTON_ACTIVE, 0.80, 0.30, 0.30, 1.0)
            if imgui.button("Discard", btn_w, 30):
                self.dirty = False
                self._show_unsaved_guard = False
                self._execute_guarded_action()
                imgui.close_current_popup()
            imgui.pop_style_color(3)

            imgui.same_line()

            # Cancel
            if imgui.button("Cancel", btn_w, 30):
                self._show_unsaved_guard = False
                self._guard_action = ""
                self._guard_payload = ""
                imgui.close_current_popup()

            imgui.end_popup()
        else:
            self._show_unsaved_guard = False

    # ── New zone ──────────────────────────────────────────────────

    def _new_zone_dialog(self) -> None:
        imgui.open_popup("New Zone")

        win_w, win_h = self.win_size
        imgui.set_next_window_position(win_w / 2 - 175, win_h / 2 - 100)
        imgui.set_next_window_size(350, 0)

        if imgui.begin_popup_modal("New Zone",
                                   flags=imgui.WINDOW_ALWAYS_AUTO_RESIZE)[0]:
            imgui.text("Create a new blank zone:")
            imgui.text_colored("You can name it when you save.",
                               0.5, 0.5, 0.55, 1.0)
            imgui.spacing()

            _, self.new_zone_w = imgui.input_int("Width", self.new_zone_w)
            _, self.new_zone_h = imgui.input_int("Height", self.new_zone_h)

            self.new_zone_w = max(5, min(100, self.new_zone_w))
            self.new_zone_h = max(5, min(100, self.new_zone_h))

            imgui.spacing()
            imgui.separator()
            imgui.spacing()

            if imgui.button("Create", 150, 30):
                self._create_new_zone(self.new_zone_w, self.new_zone_h)
                self.show_new_zone = False
                imgui.close_current_popup()

            imgui.same_line()
            if imgui.button("Cancel", 150, 30):
                self.show_new_zone = False
                imgui.close_current_popup()

            imgui.end_popup()
        else:
            self.show_new_zone = False

    # ── Save-as ───────────────────────────────────────────────────

    def _save_as_dialog(self) -> None:
        imgui.open_popup("Save As")

        win_w, win_h = self.win_size
        imgui.set_next_window_position(win_w / 2 - 175, win_h / 2 - 60)
        imgui.set_next_window_size(350, 0)

        if imgui.begin_popup_modal("Save As",
                                   flags=imgui.WINDOW_ALWAYS_AUTO_RESIZE)[0]:
            imgui.text("Save zone as:")
            imgui.spacing()

            _, self.save_as_name = imgui.input_text(
                "Name", self.save_as_name, 64)

            name_clean = self.save_as_name.strip()
            name_ok = bool(name_clean)
            exists = name_clean in self.all_zones
            name_err = ""
            if not name_clean and self.save_as_name:
                name_err = "Name cannot be blank"

            if name_err:
                imgui.text_colored(name_err, 0.9, 0.35, 0.35, 1.0)
            elif exists:
                imgui.text_colored("Will overwrite existing zone",
                                   0.9, 0.7, 0.2, 1.0)

            imgui.spacing()
            imgui.separator()
            imgui.spacing()

            if not name_ok:
                imgui.push_style_var(imgui.STYLE_ALPHA, 0.4)
            if imgui.button("Save", 150, 30) and name_ok:
                self._do_save(name_clean)
                self.show_save_as = False
                self.save_as_name = ""
                imgui.close_current_popup()
            if not name_ok:
                imgui.pop_style_var()

            imgui.same_line()
            if imgui.button("Cancel", 150, 30):
                self.show_save_as = False
                self.save_as_name = ""
                imgui.close_current_popup()

            imgui.end_popup()
        else:
            self.show_save_as = False
