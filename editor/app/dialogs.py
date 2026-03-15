"""editor/app/dialogs.py — DialogsMixin: modal dialogs for ZoneEditorApp.

Dialogs: new zone, save-as, unsaved guard, resize zone, find/replace
texture, validate zone, zone settings, duplicate zone, export image.
"""

from __future__ import annotations

import imgui

from core.zones import list_zones


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

    # ── Resize zone ───────────────────────────────────────────────

    _ANCHOR_OPTIONS = (
        "top-left", "top-center", "top-right",
        "center-left", "center", "center-right",
        "bottom-left", "bottom-center", "bottom-right",
    )

    def _resize_zone_dialog(self) -> None:
        if not self.zone:
            self.show_resize_zone = False
            return

        imgui.open_popup("Resize Zone")

        win_w, win_h = self.win_size
        imgui.set_next_window_position(win_w / 2 - 195, win_h / 2 - 130)
        imgui.set_next_window_size(390, 0)

        if imgui.begin_popup_modal("Resize Zone",
                                   flags=imgui.WINDOW_ALWAYS_AUTO_RESIZE)[0]:
            zone = self.zone
            imgui.text(f"Current size: {zone.width} \u00d7 {zone.height}")
            imgui.spacing()

            _, self._resize_new_w = imgui.input_int("New Width", self._resize_new_w)
            _, self._resize_new_h = imgui.input_int("New Height", self._resize_new_h)
            self._resize_new_w = max(5, min(200, self._resize_new_w))
            self._resize_new_h = max(5, min(200, self._resize_new_h))

            imgui.spacing()
            imgui.text("Anchor old data at:")
            # Combo for anchor position
            try:
                cur_idx = list(self._ANCHOR_OPTIONS).index(self._resize_anchor)
            except ValueError:
                cur_idx = 0
            changed, new_idx = imgui.combo(
                "##anchor", cur_idx, list(self._ANCHOR_OPTIONS))
            if changed:
                self._resize_anchor = self._ANCHOR_OPTIONS[new_idx]

            # Preview description
            nw, nh = self._resize_new_w, self._resize_new_h
            ow, oh = zone.width, zone.height
            if nw != ow or nh != oh:
                imgui.spacing()
                if nw > ow:
                    imgui.text_colored(f"  +{nw - ow} columns", 0.4, 0.9, 0.5, 1.0)
                elif nw < ow:
                    imgui.text_colored(f"  -{ow - nw} columns (data will be cropped)",
                                       0.9, 0.5, 0.3, 1.0)
                if nh > oh:
                    imgui.text_colored(f"  +{nh - oh} rows", 0.4, 0.9, 0.5, 1.0)
                elif nh < oh:
                    imgui.text_colored(f"  -{oh - nh} rows (data will be cropped)",
                                       0.9, 0.5, 0.3, 1.0)
            else:
                imgui.spacing()
                imgui.text_colored("  Same size \u2014 nothing to do", 0.5, 0.5, 0.5, 1.0)

            imgui.spacing()
            imgui.separator()
            imgui.spacing()

            same_size = nw == ow and nh == oh
            if same_size:
                imgui.push_style_var(imgui.STYLE_ALPHA, 0.4)
            if imgui.button("Resize", 170, 30) and not same_size:
                self._do_resize_zone(nw, nh, self._resize_anchor)
                self.show_resize_zone = False
                imgui.close_current_popup()
            if same_size:
                imgui.pop_style_var()

            imgui.same_line()
            if imgui.button("Cancel", 170, 30):
                self.show_resize_zone = False
                imgui.close_current_popup()

            imgui.end_popup()
        else:
            self.show_resize_zone = False

    def _do_resize_zone(self, nw: int, nh: int, anchor: str) -> None:
        """Resize the current zone, preserving existing cell data."""
        zone = self.zone
        if not zone:
            return

        ow, oh = zone.width, zone.height

        # Compute offset: where old (0,0) lands in the new grid.
        # anchor describes where old data is placed in the new grid.
        row_off, col_off = _anchor_offset(oh, ow, nh, nw, anchor)

        # Push undo before mutating
        if self.editor_3d:
            self.editor_3d._push_undo()

        try:
            self._do_resize_zone_inner(zone, ow, oh, nw, nh, row_off, col_off)
        except Exception as exc:  # noqa: BLE001
            # Restore from undo on failure
            if self.editor_3d:
                self.editor_3d._undo()
            self._flash_transient(
                f"Resize failed: {exc}", 3.0, (1.0, 0.4, 0.4, 1.0))
            return

        # Rebuild editor and raycaster
        self._attach_zone(zone, self.zone_name)
        self.dirty = True
        self._flash_transient(
            f"Resized to {nw}\u00d7{nh}", 1.5, (0.5, 1.0, 0.6, 1.0))

    def _do_resize_zone_inner(self, zone, ow, oh, nw, nh, row_off, col_off):
        """Core resize logic — separated so the caller can wrap in try/except."""
        _2D_FIELDS = {
            "tiles": "grass", "floor_heights": 0.0, "ceil_heights": 10.0,
            "floor_textures": "", "ceil_textures": "", "wall_textures": "",
            "light_levels": 1.0, "rotations": 0,
            "upper_wall_height": 0.0, "reflect_map": 0,
            "floor_slope_dx": 0.0, "floor_slope_dy": 0.0,
            "floor_slope_div": 0,
            "floor2_heights": -1000.0, "ceil2_heights": -1000.0,
            "floor2_textures": "", "ceil2_textures": "",
            "upper_wall_height2": 0.0,
            "fog_density": 0.0,
        }
        for fname, default in _2D_FIELDS.items():
            old_grid = getattr(zone, fname)
            if not old_grid:
                continue
            setattr(zone, fname,
                    _resize_grid_2d(old_grid, oh, ow, nh, nw, row_off, col_off, default))

        # fog_color uses tuple default
        if zone.fog_color:
            zone.fog_color = _resize_grid_2d(
                zone.fog_color, oh, ow, nh, nw, row_off, col_off, (0, 0, 0))

        # 3D grids (per-face [r][c][4])
        _3D_FIELDS = ("face_textures", "floor_step_textures", "ceil_step_textures")
        for fname in _3D_FIELDS:
            old_grid = getattr(zone, fname)
            if not old_grid:
                continue
            setattr(zone, fname,
                    _resize_grid_3d(old_grid, oh, ow, nh, nw, row_off, col_off))

        # 4D grids (segments [r][c][4][...])
        _4D_FIELDS = ("wall_segments", "floor_step_segments", "ceil_step_segments")
        for fname in _4D_FIELDS:
            old_grid = getattr(zone, fname)
            if not old_grid:
                continue
            setattr(zone, fname,
                    _resize_grid_4d(old_grid, oh, ow, nh, nw, row_off, col_off))

        # Relocate entities
        if zone.entities:
            zone.entities = _relocate_objects(
                zone.entities, col_off, row_off, nw, nh, "x", "y")

        # Relocate boxes
        if zone.boxes:
            zone.boxes = _relocate_objects(
                zone.boxes, col_off, row_off, nw, nh, "x", "y")

        # Relocate quads
        if zone.quads:
            zone.quads = _relocate_objects(
                zone.quads, col_off, row_off, nw, nh, "x", "z")

        # Relocate curves
        if zone.curves:
            zone.curves = _relocate_objects(
                zone.curves, col_off, row_off, nw, nh, "cx", "cy")

        # Relocate render_portals
        if zone.render_portals:
            new_rp = []
            for p in zone.render_portals:
                cell = p.get("cell", [0, 0])
                nr = cell[0] + row_off
                nc = cell[1] + col_off
                if 0 <= nr < nh and 0 <= nc < nw:
                    p = dict(p)
                    p["cell"] = [nr, nc]
                    new_rp.append(p)
            zone.render_portals = new_rp

        # Update zone dimensions and anchor
        zone.width = nw
        zone.height = nh
        ar, ac = zone.anchor
        zone.anchor = (
            max(0.0, min(float(nh - 1), ar + row_off)),
            max(0.0, min(float(nw - 1), ac + col_off)),
        )

    # ── Find / Replace Texture ────────────────────────────────────

    def _find_replace_texture_dialog(self) -> None:
        if not self.zone:
            self.show_find_replace_tex = False
            return

        win_w, win_h = self.win_size
        imgui.set_next_window_position(
            win_w / 2 - 195, win_h / 2 - 80, imgui.FIRST_USE_EVER)
        imgui.set_next_window_size(390, 0, imgui.FIRST_USE_EVER)

        expanded, opened = imgui.begin("Find / Replace Texture", True,
                                       imgui.WINDOW_ALWAYS_AUTO_RESIZE
                                       | imgui.WINDOW_NO_SAVED_SETTINGS)
        if not opened:
            self.show_find_replace_tex = False
            imgui.end()
            return

        zone = self.zone
        imgui.text("Replace all occurrences of a texture key")
        imgui.text_disabled(f"Zone: {zone.width}\u00d7{zone.height} ({self.zone_name})")
        imgui.spacing()

        imgui.push_item_width(250)
        _, self._frt_find = imgui.input_text("Find##frt", self._frt_find, 128)
        _, self._frt_replace = imgui.input_text("Replace##frt", self._frt_replace, 128)
        imgui.pop_item_width()

        find_ok = bool(self._frt_find.strip())
        replace_ok = bool(self._frt_replace.strip())

        imgui.spacing()

        # Count occurrences button
        if imgui.button("Count", 100, 26) and find_ok:
            n = _count_texture(zone, self._frt_find.strip())
            self._frt_result = f"Found {n} occurrence{'s' if n != 1 else ''}"

        imgui.same_line()

        can_replace = find_ok and replace_ok
        if not can_replace:
            imgui.push_style_var(imgui.STYLE_ALPHA, 0.4)
        if imgui.button("Replace All", 130, 26) and can_replace:
            if self.editor_3d:
                self.editor_3d._push_undo()
            n = _replace_texture(zone, self._frt_find.strip(),
                                 self._frt_replace.strip())
            self._frt_result = f"Replaced {n} occurrence{'s' if n != 1 else ''}"
            if n > 0:
                self.dirty = True
                if self.editor_3d:
                    self.editor_3d.dirty = True
        if not can_replace:
            imgui.pop_style_var()

        if self._frt_result:
            imgui.spacing()
            imgui.text_colored(self._frt_result, 0.5, 0.9, 0.6, 1.0)

        # Eyedropper hint
        imgui.spacing()
        imgui.text_disabled("Tip: Use eyedropper (MMB in Paint) to grab a texture name")

        imgui.end()

    # ── Validate Zone ─────────────────────────────────────────────

    def _validate_zone_dialog(self) -> None:
        if not self.zone:
            self.show_validate_zone = False
            return

        win_w, win_h = self.win_size
        imgui.set_next_window_position(
            win_w / 2 - 220, win_h / 2 - 180, imgui.FIRST_USE_EVER)
        imgui.set_next_window_size(440, 360, imgui.FIRST_USE_EVER)

        expanded, opened = imgui.begin("Zone Validation", True,
                                       imgui.WINDOW_NO_SAVED_SETTINGS)
        if not opened:
            self.show_validate_zone = False
            imgui.end()
            return

        zone = self.zone

        if imgui.button("Run Validation", 160, 26):
            from core.zones.validation import validate_zone as _vz
            from core.entity_defs import entity_registry as _er
            from core.tiles import TILE_REGISTRY as _tr
            from core.paths import TILE_TEX_DIR as _td
            self._validate_results = _vz(
                zone,
                entity_registry=_er(),
                tile_registry=_tr,
                texture_dir=_td,
            )

        imgui.same_line()
        n = len(self._validate_results)
        if n == 0:
            imgui.text_colored("No issues \u2713", 0.4, 0.9, 0.4, 1.0)
        else:
            n_err = sum(1 for i in self._validate_results if i.severity == "error")
            n_warn = sum(1 for i in self._validate_results if i.severity == "warning")
            parts = []
            if n_err:
                parts.append(f"{n_err} error{'s' * (n_err > 1)}")
            if n_warn:
                parts.append(f"{n_warn} warning{'s' * (n_warn > 1)}")
            imgui.text_colored(", ".join(parts) if parts else f"{n} issue{'s' if n != 1 else ''}",
                               0.9, 0.5, 0.3, 1.0)

        imgui.separator()

        imgui.begin_child("##val_results", 0, 0, border=True)
        for iss in self._validate_results:
            loc = f" @ {iss.location}" if iss.location else ""
            msg = f"[{iss.severity.upper()}] {iss.message}{loc}"
            if iss.severity == "error":
                imgui.text_colored(msg, 0.95, 0.35, 0.30, 1.0)
            elif iss.severity == "warning":
                imgui.text_colored(msg, 0.95, 0.75, 0.30, 1.0)
            else:
                imgui.text_colored(msg, 0.55, 0.75, 0.95, 1.0)
        imgui.end_child()

        imgui.end()

    # ── Zone Settings ─────────────────────────────────────────────

    def _zone_settings_dialog(self) -> None:
        if not self.zone:
            self.show_zone_settings = False
            return

        imgui.open_popup("Zone Settings")

        win_w, win_h = self.win_size
        imgui.set_next_window_position(win_w / 2 - 200, win_h / 2 - 150)
        imgui.set_next_window_size(400, 0)

        if imgui.begin_popup_modal("Zone Settings",
                                   flags=imgui.WINDOW_ALWAYS_AUTO_RESIZE)[0]:
            zone = self.zone
            imgui.text_disabled(f"Zone: {self.zone_name}  "
                                f"({zone.width}\u00d7{zone.height})")
            imgui.spacing()

            # ── First person ──────────────────────────────────
            _, fp = imgui.checkbox("First Person", zone.first_person)
            if _ :
                zone.first_person = fp
                self.dirty = True

            imgui.spacing()

            # ── Skybox ────────────────────────────────────────
            imgui.text("Skybox:")
            imgui.same_line()
            changed, new_sky = imgui.input_text(
                "##skybox", self._zs_skybox, 128)
            if changed:
                self._zs_skybox = new_sky
            imgui.same_line()
            imgui.text_disabled('("" = procedural)')

            # ── Sky color ─────────────────────────────────────
            imgui.spacing()
            imgui.text("Sky Color (R,G,B 0-255):")
            changed_r, self._zs_sky_r = imgui.input_int(
                "R##sky", self._zs_sky_r)
            changed_g, self._zs_sky_g = imgui.input_int(
                "G##sky", self._zs_sky_g)
            changed_b, self._zs_sky_b = imgui.input_int(
                "B##sky", self._zs_sky_b)
            self._zs_sky_r = max(0, min(255, self._zs_sky_r))
            self._zs_sky_g = max(0, min(255, self._zs_sky_g))
            self._zs_sky_b = max(0, min(255, self._zs_sky_b))
            use_sky = self._zs_sky_r or self._zs_sky_g or self._zs_sky_b
            if use_sky:
                r, g, b = self._zs_sky_r, self._zs_sky_g, self._zs_sky_b
                imgui.color_button("##sky_preview",
                                   r / 255, g / 255, b / 255, 1.0,
                                   0, 20, 20)
                imgui.same_line()
                imgui.text_disabled("(0,0,0 = use default)")
            else:
                imgui.text_disabled("Using default sky color")

            # ── Anchor ────────────────────────────────────────
            imgui.spacing()
            imgui.text("Spawn Anchor:")
            changed_ar, self._zs_anchor_r = imgui.input_float(
                "Row##anc", self._zs_anchor_r, 0.5, 1.0, "%.1f")
            changed_ac, self._zs_anchor_c = imgui.input_float(
                "Col##anc", self._zs_anchor_c, 0.5, 1.0, "%.1f")
            self._zs_anchor_r = max(0.0, min(float(zone.height - 1),
                                              self._zs_anchor_r))
            self._zs_anchor_c = max(0.0, min(float(zone.width - 1),
                                              self._zs_anchor_c))

            imgui.spacing()
            imgui.separator()
            imgui.spacing()

            if imgui.button("Apply", 180, 30):
                if self.editor_3d:
                    self.editor_3d._push_undo()
                zone.skybox = self._zs_skybox.strip()
                if use_sky:
                    zone.sky_color = (self._zs_sky_r,
                                      self._zs_sky_g,
                                      self._zs_sky_b)
                else:
                    zone.sky_color = ()
                zone.anchor = (self._zs_anchor_r, self._zs_anchor_c)
                self.dirty = True
                self.show_zone_settings = False
                imgui.close_current_popup()
                self._flash_transient(
                    "Zone settings updated", 1.5, (0.5, 1.0, 0.6, 1.0))

            imgui.same_line()
            if imgui.button("Cancel", 180, 30):
                self.show_zone_settings = False
                imgui.close_current_popup()

            imgui.end_popup()
        else:
            self.show_zone_settings = False

    # ── Duplicate Zone ────────────────────────────────────────────

    def _duplicate_zone_dialog(self) -> None:
        if not self.zone:
            self.show_duplicate_zone = False
            return

        imgui.open_popup("Duplicate Zone")

        win_w, win_h = self.win_size
        imgui.set_next_window_position(win_w / 2 - 175, win_h / 2 - 60)
        imgui.set_next_window_size(350, 0)

        if imgui.begin_popup_modal("Duplicate Zone",
                                   flags=imgui.WINDOW_ALWAYS_AUTO_RESIZE)[0]:
            imgui.text("Save a copy of the current zone as:")
            imgui.spacing()

            _, self._dup_name = imgui.input_text(
                "Name##dup", self._dup_name, 64)

            name_clean = self._dup_name.strip()
            name_ok = bool(name_clean)
            exists = name_clean in self.all_zones
            same = name_clean == self.zone_name

            if not name_clean and self._dup_name:
                imgui.text_colored("Name cannot be blank", 0.9, 0.35, 0.35, 1.0)
            elif same:
                imgui.text_colored("Same as current \u2014 use Save instead",
                                   0.9, 0.7, 0.2, 1.0)
            elif exists:
                imgui.text_colored("Will overwrite existing zone",
                                   0.9, 0.7, 0.2, 1.0)

            imgui.spacing()
            imgui.separator()
            imgui.spacing()

            can_save = name_ok and not same
            if not can_save:
                imgui.push_style_var(imgui.STYLE_ALPHA, 0.4)
            if imgui.button("Duplicate", 150, 30) and can_save:
                # Save under new name WITHOUT changing current zone_name
                from core.paths import ZONES_DIR as _ZD
                import copy
                dup_zone = copy.deepcopy(self.zone)
                dup_zone.name = name_clean
                path = _ZD / f"{name_clean}.zone"
                dup_zone.save_to_file(path, self.registry)
                self.all_zones = list_zones()
                self.show_duplicate_zone = False
                self._dup_name = ""
                imgui.close_current_popup()
                self._flash_transient(
                    f"Duplicated \u2192 {name_clean}", 1.5,
                    (0.5, 1.0, 0.6, 1.0))
            if not can_save:
                imgui.pop_style_var()

            imgui.same_line()
            if imgui.button("Cancel##dup", 150, 30):
                self.show_duplicate_zone = False
                self._dup_name = ""
                imgui.close_current_popup()

            imgui.end_popup()
        else:
            self.show_duplicate_zone = False

    # ── Export Top-Down Image ─────────────────────────────────────

    def _export_image_dialog(self) -> None:
        if not self.zone:
            self.show_export_image = False
            return

        imgui.open_popup("Export Top-Down Image")

        win_w, win_h = self.win_size
        imgui.set_next_window_position(win_w / 2 - 175, win_h / 2 - 80)
        imgui.set_next_window_size(350, 0)

        if imgui.begin_popup_modal("Export Top-Down Image",
                                   flags=imgui.WINDOW_ALWAYS_AUTO_RESIZE)[0]:
            imgui.text("Export a tile-colour map as PNG")
            imgui.spacing()

            _, self._export_scale = imgui.input_int(
                "Pixels per tile", self._export_scale)
            self._export_scale = max(1, min(32, self._export_scale))

            _, self._export_entities = imgui.checkbox(
                "Mark entities", self._export_entities)

            zone = self.zone
            pw = zone.width * self._export_scale
            ph = zone.height * self._export_scale
            imgui.text_disabled(f"Output: {pw}\u00d7{ph} px")

            imgui.spacing()
            imgui.separator()
            imgui.spacing()

            if imgui.button("Export", 150, 30):
                path = _export_top_down(zone, self._export_scale,
                                        self._export_entities)
                self.show_export_image = False
                imgui.close_current_popup()
                if path:
                    self._flash_transient(
                        f"Saved {path.name}", 2.0, (0.5, 1.0, 0.6, 1.0))
                else:
                    self._flash_transient(
                        "Export failed", 2.0, (1.0, 0.4, 0.4, 1.0))

            imgui.same_line()
            if imgui.button("Cancel##exp", 150, 30):
                self.show_export_image = False
                imgui.close_current_popup()

            imgui.end_popup()
        else:
            self.show_export_image = False


# ══════════════════════════════════════════════════════════════════
#  Free functions (used by dialog methods above)
# ══════════════════════════════════════════════════════════════════

def _anchor_offset(
    oh: int, ow: int, nh: int, nw: int, anchor: str,
) -> tuple[int, int]:
    """Return (row_offset, col_offset) for placing old data in the new grid."""
    parts = anchor.split("-") if "-" in anchor else [anchor]
    # Vertical
    if parts[0] == "top":
        row_off = 0
    elif parts[0] == "bottom":
        row_off = nh - oh
    else:  # center
        row_off = (nh - oh) // 2
    # Horizontal
    if len(parts) > 1:
        horz = parts[1]
    else:
        horz = "center"
    if horz == "left":
        col_off = 0
    elif horz == "right":
        col_off = nw - ow
    else:  # center
        col_off = (nw - ow) // 2
    return row_off, col_off


def _resize_grid_2d(old, oh, ow, nh, nw, row_off, col_off, default):
    """Resize a [H][W] grid, filling new cells with *default*."""
    new = [[default] * nw for _ in range(nh)]
    for r in range(oh):
        nr = r + row_off
        if nr < 0 or nr >= nh:
            continue
        for c in range(ow):
            nc = c + col_off
            if nc < 0 or nc >= nw:
                continue
            new[nr][nc] = old[r][c]
    return new


def _resize_grid_3d(old, oh, ow, nh, nw, row_off, col_off):
    """Resize a [H][W][4] grid (face textures)."""
    new = [[[""] * 4 for _ in range(nw)] for _ in range(nh)]
    for r in range(oh):
        nr = r + row_off
        if nr < 0 or nr >= nh:
            continue
        for c in range(ow):
            nc = c + col_off
            if nc < 0 or nc >= nw:
                continue
            new[nr][nc] = old[r][c][:]
    return new


def _resize_grid_4d(old, oh, ow, nh, nw, row_off, col_off):
    """Resize a [H][W][4][segs...] grid (segments)."""
    new = [[[[], [], [], []] for _ in range(nw)] for _ in range(nh)]
    for r in range(oh):
        nr = r + row_off
        if nr < 0 or nr >= nh:
            continue
        for c in range(ow):
            nc = c + col_off
            if nc < 0 or nc >= nw:
                continue
            new[nr][nc] = [[seg[:] for seg in face] for face in old[r][c]]
    return new


def _relocate_objects(objs, col_off, row_off, nw, nh, x_key, y_key):
    """Shift objects by offset, drop any that fall outside bounds."""
    result = []
    for obj in objs:
        o = dict(obj)
        o[x_key] = float(o.get(x_key, 0.0)) + col_off
        o[y_key] = float(o.get(y_key, 0.0)) + row_off
        if 0 <= o[x_key] < nw and 0 <= o[y_key] < nh:
            result.append(o)
    return result


# ── Find / Replace Texture helpers ────────────────────────────────

def _count_texture(zone, tex: str) -> int:
    """Count occurrences of *tex* across all texture-bearing fields."""
    n = 0
    for field_name in _TEXTURE_2D_FIELDS:
        grid = getattr(zone, field_name, None)
        if not grid:
            continue
        for row in grid:
            for cell in row:
                if cell == tex:
                    n += 1
    for field_name in _TEXTURE_3D_FIELDS:
        grid = getattr(zone, field_name, None)
        if not grid:
            continue
        for row in grid:
            for cell in row:
                for face in cell:
                    if face == tex:
                        n += 1
    for field_name in _SEGMENT_FIELDS:
        grid = getattr(zone, field_name, None)
        if not grid:
            continue
        for row in grid:
            for cell in row:
                for face_segs in cell:
                    for seg in face_segs:
                        if seg and seg[0] == tex:
                            n += 1
    return n


def _replace_texture(zone, find: str, replace: str) -> int:
    """Replace *find* with *replace* in all texture fields.  Returns count."""
    n = 0
    for field_name in _TEXTURE_2D_FIELDS:
        grid = getattr(zone, field_name, None)
        if not grid:
            continue
        for r, row in enumerate(grid):
            for c, cell in enumerate(row):
                if cell == find:
                    row[c] = replace
                    n += 1
    for field_name in _TEXTURE_3D_FIELDS:
        grid = getattr(zone, field_name, None)
        if not grid:
            continue
        for row in grid:
            for cell in row:
                for fi in range(len(cell)):
                    if cell[fi] == find:
                        cell[fi] = replace
                        n += 1
    for field_name in _SEGMENT_FIELDS:
        grid = getattr(zone, field_name, None)
        if not grid:
            continue
        for row in grid:
            for cell in row:
                for face_segs in cell:
                    for seg in face_segs:
                        if seg and seg[0] == find:
                            seg[0] = replace
                            n += 1
    return n


_TEXTURE_2D_FIELDS = (
    "tiles", "wall_textures", "floor_textures", "ceil_textures",
    "floor2_textures", "ceil2_textures",
)
_TEXTURE_3D_FIELDS = (
    "face_textures", "floor_step_textures", "ceil_step_textures",
)
_SEGMENT_FIELDS = (
    "wall_segments", "floor_step_segments", "ceil_step_segments",
)


# ── Export top-down ───────────────────────────────────────────────

def _export_top_down(zone, scale: int, mark_entities: bool):
    """Render a top-down tile-color PNG and return the Path (or None)."""
    try:
        return _export_top_down_inner(zone, scale, mark_entities)
    except Exception:  # noqa: BLE001
        return None


def _export_top_down_inner(zone, scale: int, mark_entities: bool):
    import pygame
    from core.tiles import TILE_COLORS

    w, h = zone.width, zone.height
    surf = pygame.Surface((w * scale, h * scale))
    surf.fill((30, 30, 30))

    fallback = (80, 80, 80)
    for r in range(h):
        for c in range(w):
            tid = zone.tiles[r][c] if zone.tiles else ""
            color = TILE_COLORS.get(tid, fallback)
            # Darken by light level if available
            if zone.light_levels and r < len(zone.light_levels) \
                    and c < len(zone.light_levels[r]):
                ll = zone.light_levels[r][c]
                color = (int(color[0] * ll),
                         int(color[1] * ll),
                         int(color[2] * ll))
            rect = pygame.Rect(c * scale, r * scale, scale, scale)
            surf.fill(color, rect)

    # Mark entity positions
    if mark_entities and zone.entities:
        ent_color = (255, 50, 50)
        for ent in zone.entities:
            ex = int(float(ent.get("x", 0)))
            ey = int(float(ent.get("y", 0)))
            if 0 <= ex < w and 0 <= ey < h:
                rect = pygame.Rect(ex * scale, ey * scale, scale, scale)
                # Draw a small cross
                cx = ex * scale + scale // 2
                cy = ey * scale + scale // 2
                hs = max(1, scale // 3)
                pygame.draw.line(surf, ent_color,
                                 (cx - hs, cy), (cx + hs, cy))
                pygame.draw.line(surf, ent_color,
                                 (cx, cy - hs), (cx, cy + hs))

    # Mark anchor
    ar, ac = zone.anchor
    ax = int(ac) * scale + scale // 2
    ay = int(ar) * scale + scale // 2
    pygame.draw.circle(surf, (50, 255, 50), (ax, ay), max(2, scale // 2), 1)

    # Save
    from pathlib import Path as _P
    out_dir = _P(__file__).resolve().parent.parent.parent / "debug_renders"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"{zone.name}_topdown.png"
    try:
        pygame.image.save(surf, str(out_path))
        return out_path
    except Exception:  # noqa: BLE001
        return None