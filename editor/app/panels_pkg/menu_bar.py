"""editor/app/panels_pkg/menu_bar.py — Main menu bar."""

from __future__ import annotations

from pathlib import Path

import pygame
import imgui


class MenuBarMixin:
    """Top-level menu bar: File | Edit | View | Zone | Data | Window."""

    def _menu_bar(self) -> None:
        from pygame.locals import QUIT as PG_QUIT
        if imgui.begin_main_menu_bar():
            # ── File ──────────────────────────────────────────────
            if imgui.begin_menu("File"):
                if imgui.menu_item("New Zone...", "Ctrl+N")[0]:
                    if self._request_guarded("new"):
                        self.show_new_zone = True
                imgui.separator()
                if imgui.menu_item("Save", "Ctrl+S")[0]:
                    self._save_zone()
                if imgui.menu_item("Save As...", "Ctrl+Shift+S")[0]:
                    self.save_as_name = self.zone_name if self.zone_name != "untitled" else ""
                    self.show_save_as = True
                imgui.separator()
                # Recent zones sub-menu
                recent = getattr(self, '_session', {}).get('recent_zones', [])
                if imgui.begin_menu("Recent Zones", bool(recent)):
                    for rname in recent:
                        if rname not in self.all_zones:
                            continue
                        is_cur = (rname == self.zone_name)
                        if imgui.menu_item(rname, "", is_cur)[0] and not is_cur:
                            if self._request_guarded("switch", rname):
                                self._load_zone(rname)
                    imgui.end_menu()
                imgui.separator()
                if imgui.menu_item("Quit", "Escape")[0]:
                    pygame.event.post(pygame.event.Event(PG_QUIT))
                imgui.end_menu()

            # ── Edit ──────────────────────────────────────────────
            if imgui.begin_menu("Edit"):
                if imgui.menu_item("Undo", "Ctrl+Z")[0]:
                    if self.editor_3d:
                        self.editor_3d._undo()
                if imgui.menu_item("Redo", "Ctrl+Y")[0]:
                    if self.editor_3d:
                        self.editor_3d._redo()
                imgui.separator()
                if imgui.menu_item("Select All", "Ctrl+A")[0]:
                    if self.editor_3d and self.zone:
                        self.editor_3d.selection.select_all_cells(
                            self.zone.width, self.zone.height)
                imgui.separator()
                if imgui.menu_item("Find / Replace Texture...", "Ctrl+F")[0]:
                    self.show_find_replace_tex = True
                    self._frt_find = ""
                    self._frt_replace = ""
                    self._frt_result = ""
                imgui.end_menu()

            # ── View ──────────────────────────────────────────────
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
                alive = getattr(self, '_preview_alive', False)
                label = "Close Preview Window" if alive else "Preview Window"
                if imgui.menu_item(label, "")[0]:
                    if alive:
                        self._kill_preview()
                    else:
                        self._launch_preview()

                imgui.separator()
                if self.editor_3d:
                    _, self.editor_3d.show_axes = imgui.menu_item(
                        "Show Axes", "F10", self.editor_3d.show_axes)
                    _, self.editor_3d.show_walls = imgui.menu_item(
                        "Show Walls", "Ctrl+1", self.editor_3d.show_walls)
                    _, self.editor_3d.show_floors = imgui.menu_item(
                        "Show Floors", "Ctrl+2", self.editor_3d.show_floors)
                    _, self.editor_3d.show_ceilings = imgui.menu_item(
                        "Show Ceilings", "Ctrl+3", self.editor_3d.show_ceilings)
                    _, self.editor_3d.show_entities = imgui.menu_item(
                        "Show Entities", "Ctrl+4", self.editor_3d.show_entities)
                    imgui.separator()
                    _, self.editor_3d.wireframe = imgui.menu_item(
                        "Wireframe", "Ctrl+5", self.editor_3d.wireframe)
                imgui.end_menu()

            # ── Zone ──────────────────────────────────────────────
            if imgui.begin_menu("Zone"):
                if imgui.menu_item("Zone Settings...")[0]:
                    if self.zone:
                        self._zs_skybox = self.zone.skybox
                        sc = self.zone.sky_color
                        self._zs_sky_r = sc[0] if sc else 0
                        self._zs_sky_g = sc[1] if sc else 0
                        self._zs_sky_b = sc[2] if sc else 0
                        self._zs_anchor_r = self.zone.anchor[0]
                        self._zs_anchor_c = self.zone.anchor[1]
                        self.show_zone_settings = True
                if imgui.menu_item("Resize Zone...")[0]:
                    if self.zone:
                        self._resize_new_w = self.zone.width
                        self._resize_new_h = self.zone.height
                        self._resize_anchor = "top-left"
                        self.show_resize_zone = True
                imgui.separator()
                if imgui.menu_item("Validate Zone")[0]:
                    self.show_validate_zone = True
                    self._validate_results = []
                if imgui.menu_item("Export Top-Down Image...")[0]:
                    self.show_export_image = True
                imgui.separator()
                if imgui.menu_item("Duplicate Zone...")[0]:
                    self._dup_name = (self.zone_name + "_copy"
                                      if self.zone_name != "untitled"
                                      else "")
                    self.show_duplicate_zone = True
                imgui.end_menu()

            # ── Data ──────────────────────────────────────────────
            if imgui.begin_menu("Data"):
                if imgui.menu_item("Entity Definitions")[0]:
                    self.show_entity_defs_viewer = True
                if imgui.menu_item("Items")[0]:
                    self.show_items_viewer = True
                if imgui.menu_item("Loot Tables")[0]:
                    self.show_loot_tables_viewer = True
                imgui.separator()
                if imgui.menu_item("Presets")[0]:
                    self.show_presets_viewer = True
                imgui.separator()
                if imgui.menu_item("Entity Textures")[0]:
                    self.show_entity_textures = True
                if imgui.menu_item("New Entity Type")[0]:
                    self._ec_open_new()
                imgui.separator()
                if imgui.menu_item("Open Data Folder")[0]:
                    self._open_data_folder()
                imgui.end_menu()

            # ── Window ────────────────────────────────────────────
            if imgui.begin_menu("Window"):
                clicked_tb, _ = imgui.menu_item(
                    "Texture Browser", "",
                    self.show_texture_browser)
                if clicked_tb:
                    self.show_texture_browser = not self.show_texture_browser
                clicked_kb, _ = imgui.menu_item(
                    "Keybind Editor", "",
                    self.show_keybind_editor)
                if clicked_kb:
                    self.show_keybind_editor = not self.show_keybind_editor
                imgui.separator()

                # Camera Bookmarks sub-menu
                bms = getattr(self, '_camera_bookmarks', [])
                if imgui.begin_menu("Camera Bookmarks"):
                    if not bms:
                        imgui.text_disabled("No bookmarks saved")
                        imgui.text_disabled("Ctrl+Shift+1\u20139 to save")
                        imgui.text_disabled("Shift+1\u20139 to recall")
                    else:
                        for bm in sorted(bms, key=lambda b: b.get("slot", 0)):
                            slot = bm.get("slot", 0)
                            zn = bm.get("zone", "?")
                            lbl = f"[{slot + 1}] {zn} ({bm.get('cam_x', 0):.0f}, {bm.get('cam_z', 0):.0f})"
                            if imgui.menu_item(lbl, f"Shift+{slot + 1}")[0]:
                                self._recall_camera_bookmark(slot)
                        imgui.separator()
                        if imgui.menu_item("Clear All Bookmarks")[0]:
                            self._camera_bookmarks.clear()
                    imgui.end_menu()
                imgui.separator()

                clicked_help, _ = imgui.menu_item(
                    "Help Overlay", "?",
                    self.editor_3d._show_help if self.editor_3d else False)
                if clicked_help and self.editor_3d:
                    self.editor_3d._show_help = not self.editor_3d._show_help
                imgui.end_menu()

            # ── Right-aligned FPS ─────────────────────────────────
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

    # ── Helpers ───────────────────────────────────────────────────

    @staticmethod
    def _open_data_folder() -> None:
        """Open the data/ directory in the system file manager."""
        import subprocess
        data_dir = str(Path(__file__).resolve().parent.parent.parent.parent / "data")
        try:
            subprocess.Popen(["xdg-open", data_dir])
        except FileNotFoundError:
            pass  # non-Linux or xdg-open not available
