"""editor/app/events.py — EventsMixin: input routing and escape chains."""

from __future__ import annotations

import pygame
from pygame.locals import (
    QUIT, KEYDOWN, MOUSEBUTTONDOWN, MOUSEBUTTONUP, MOUSEWHEEL, VIDEORESIZE,
)

from editor.view_3d import _ensure_palette


class EventsMixin:
    """Pygame event routing mixin for :class:`ZoneEditorApp`.

    Handles the captured / uncaptured split, escape priority chains,
    global shortcuts, and transient flash indicators.
    """

    # ── Transient indicator (near-crosshair flash) ────────────────

    def _flash_transient(self, text: str, duration: float = 1.5,
                         color: tuple = (0.95, 0.90, 0.75, 1.0)) -> None:
        """Show a brief text indicator near the crosshair."""
        self._transient_text = text
        self._transient_time = duration
        self._transient_color = color

    # ── Quit / guard helper ───────────────────────────────────────

    def _should_keep_running_after_quit(self) -> bool:
        """Handle a quit request.  Returns True if the app should keep
        running (unsaved-changes guard was shown), False if it should exit."""
        if self.dirty:
            # _request_guarded returns True when clean → proceed immediately
            if self._request_guarded("quit"):
                return False   # not dirty after all — exit now
            return True        # guard dialog is now visible — stay alive
        return False           # nothing unsaved — exit now

    # ── Main event pump ───────────────────────────────────────────

    def _process_events(self) -> bool:  # noqa: C901 — complex but linear
        import imgui
        io = imgui.get_io()

        for event in pygame.event.get():
            if event.type == QUIT:
                if not self._should_keep_running_after_quit():
                    return False
                continue
            if event.type == VIDEORESIZE:
                old_w = self.win_size[0]
                self.win_size = (event.w, event.h)
                if old_w > 0:
                    ratio = event.w / old_w
                    self.left_panel_w = max(200, min(event.w // 2 - 50,
                                                     int(self.left_panel_w * ratio)))
                    self.right_panel_w = max(200, min(event.w // 2 - 50,
                                                      int(self.right_panel_w * ratio)))
                self._vp_surface = None
                self._vp_tex = 0
                self._vp_dirty = True
                self.imgui_impl.process_event(event)
                continue

            if self.mouse_captured:
                self._handle_captured_event(event)
            else:
                result = self._handle_uncaptured_event(event, io)
                if result is False:
                    return False

        return True

    # ── Captured-mode input (viewport owns everything) ────────────

    def _handle_captured_event(self, event: pygame.event.Event) -> None:
        if event.type == KEYDOWN:
            self._captured_keydown(event)
        elif event.type == MOUSEBUTTONDOWN:
            if self.view_mode == "3d" and self.editor_3d:
                self.editor_3d.handle_event(event)
        elif event.type == MOUSEBUTTONUP:
            if self.view_mode == "3d" and self.editor_3d:
                self.editor_3d.handle_event(event)
        elif event.type == MOUSEWHEEL:
            if self.view_mode == "3d" and self.editor_3d:
                self._captured_scroll(event)

    def _captured_keydown(self, event: pygame.event.Event) -> None:
        """Handle a keypress while mouse is captured (viewport focus)."""
        # Escape priority chain:
        #   1. Cancel stamp capture-naming mode (stay captured)
        #   2. Cancel active selection (stay captured)
        #   3. Release mouse (return to panel mode)
        if event.key == pygame.K_ESCAPE:
            if (self.view_mode == "3d" and self.editor_3d
                    and self.editor_3d.tool == "stamp"
                    and getattr(self.editor_3d, '_capture_pending', False)):
                self.editor_3d._capture_pending = False
                self.editor_3d._capture_name = ""
            elif (self.view_mode == "3d" and self.editor_3d
                    and self.editor_3d.tool == "select"
                    and (self.editor_3d.selection.has_cells()
                         or self.editor_3d.selection.rect_in_progress)):
                self.editor_3d._sel_cancel()
            else:
                self._release_mouse()
            return

        # Global shortcuts
        if event.key == pygame.K_TAB and self.zone:
            if not (pygame.key.get_mods() & pygame.KMOD_SHIFT):
                self._toggle_view_mode()
                return
        if event.key == pygame.K_s and (pygame.key.get_mods() & pygame.KMOD_CTRL):
            self._save_zone()
            return

        # Camera bookmarks: Ctrl+Shift+1–9 saves, Shift+1–9 recalls
        _NUM_KEYS = {
            pygame.K_1: 0, pygame.K_2: 1, pygame.K_3: 2,
            pygame.K_4: 3, pygame.K_5: 4, pygame.K_6: 5,
            pygame.K_7: 6, pygame.K_8: 7, pygame.K_9: 8,
        }
        if event.key in _NUM_KEYS:
            mods = pygame.key.get_mods()
            slot = _NUM_KEYS[event.key]
            if (mods & pygame.KMOD_CTRL) and (mods & pygame.KMOD_SHIFT):
                self._save_camera_bookmark(slot)
                return
            elif (mods & pygame.KMOD_SHIFT) and not (mods & pygame.KMOD_CTRL):
                self._recall_camera_bookmark(slot)
                return

        # Forward to active view
        if self.view_mode == "3d" and self.editor_3d:
            old_snap = self.editor_3d.snap_idx
            self.editor_3d.handle_event(event)
            # Flash transient if snap changed via G key
            if self.editor_3d.snap_idx != old_snap:
                snap_labels = ("1/16", "1/8", "1/4", "1/2", "1")
                idx = self.editor_3d.snap_idx
                self._flash_transient(
                    f"Snap: {snap_labels[idx]}",
                    1.2, (0.55, 0.75, 0.60, 1.0))
        elif self.view_mode == "2d":
            self._raycaster_key(event)

    def _captured_scroll(self, event: pygame.event.Event) -> None:
        """Handle mouse-wheel while captured (palette / snap / preset cycle)."""
        ed = self.editor_3d
        old_tex = ed.tex_idx
        old_snap = ed.snap_idx
        old_stamp = getattr(ed, '_stamp_idx', -1)

        ed.handle_event(event)

        # Flash transient feedback
        if ed.tex_idx != old_tex:
            palette = _ensure_palette()
            idx = ed.tex_idx
            name = palette[idx] if idx < len(palette) else "?"
            self._flash_transient(
                f"{name}  ({idx + 1}/{len(palette)})",
                1.5, (0.75, 0.55, 0.85, 1.0))
        elif ed.snap_idx != old_snap:
            snap_labels = ("1/16", "1/8", "1/4", "1/2", "1")
            idx = ed.snap_idx
            self._flash_transient(
                f"Snap: {snap_labels[idx]}",
                1.2, (0.55, 0.75, 0.60, 1.0))
        elif getattr(ed, '_stamp_idx', -1) != old_stamp:
            preset = ed._stamp_current()
            pname = preset.name if preset else "?"
            self._flash_transient(
                f"Preset: {pname}",
                1.5, (0.70, 0.55, 1.0, 1.0))

    # ── Uncaptured-mode input (imgui owns everything) ─────────────

    def _handle_uncaptured_event(self, event: pygame.event.Event, io) -> bool | None:
        """Handle events when mouse is not captured.

        Returns ``False`` if the app should quit, ``None`` otherwise.
        """
        self.imgui_impl.process_event(event)

        if event.type == KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                # Escape chain: close open dialogs first, then quit-guard
                if self._close_any_dialog():
                    pass  # dialog was closed — consume the keypress
                elif not self._should_keep_running_after_quit():
                    return False

            # Enter / F5 → enter edit mode
            elif (event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_F5)
                    and self.zone
                    and not self._any_modal_open()):
                self._capture_mouse()

            # Global shortcuts still work from panels
            elif event.key == pygame.K_TAB and self.zone:
                if not (pygame.key.get_mods() & pygame.KMOD_SHIFT):
                    self._toggle_view_mode()
            elif event.key == pygame.K_s and (pygame.key.get_mods() & pygame.KMOD_CTRL):
                if pygame.key.get_mods() & pygame.KMOD_SHIFT:
                    # Ctrl+Shift+S → Save As
                    self.save_as_name = self.zone_name if self.zone_name != "untitled" else ""
                    self.show_save_as = True
                else:
                    self._save_zone()
            elif event.key == pygame.K_z and (pygame.key.get_mods() & pygame.KMOD_CTRL):
                if self.editor_3d:
                    self.editor_3d._undo()
            elif event.key == pygame.K_y and (pygame.key.get_mods() & pygame.KMOD_CTRL):
                if self.editor_3d:
                    self.editor_3d._redo()
            elif event.key == pygame.K_n and (pygame.key.get_mods() & pygame.KMOD_CTRL):
                if self._request_guarded("new"):
                    self.show_new_zone = True
            elif event.key == pygame.K_f and (pygame.key.get_mods() & pygame.KMOD_CTRL):
                self.show_find_replace_tex = True
                self._frt_find = ""
                self._frt_replace = ""
                self._frt_result = ""

        elif event.type == MOUSEBUTTONDOWN and event.button == 1:
            if not io.want_capture_mouse and self.zone:
                self._capture_with_first_click(event)

        return None

    def _capture_with_first_click(self, event: pygame.event.Event) -> None:
        """Capture the mouse without performing any tool action."""
        self._capture_mouse()

    # ── Dialog helpers ────────────────────────────────────────────

    def _any_modal_open(self) -> bool:
        """Return True if any modal dialog is currently shown."""
        return (self.show_save_as or self.show_new_zone
                or self._show_unsaved_guard or self.show_resize_zone
                or self.show_zone_settings or self.show_duplicate_zone
                or self.show_export_image)

    def _close_any_dialog(self) -> bool:
        """Close the first open dialog/window and return True, or False."""
        # Close non-modal floating windows first
        for attr in ("show_find_replace_tex", "show_validate_zone",
                     "show_entity_defs_viewer", "show_items_viewer",
                     "show_loot_tables_viewer", "show_presets_viewer",
                     "show_keybind_editor", "show_texture_browser"):
            if getattr(self, attr, False):
                setattr(self, attr, False)
                return True
        # Then close modal dialogs
        for attr in ("show_resize_zone", "show_zone_settings",
                     "show_duplicate_zone", "show_export_image",
                     "show_save_as", "show_new_zone"):
            if getattr(self, attr, False):
                setattr(self, attr, False)
                return True
        return False