"""editor/contexts.py — Concrete InputContext implementations.

* :class:`GlobalShortcutsContext`  — always at the bottom of the stack
* :class:`CapturedViewportContext` — pushed/popped as the viewport grabs the mouse
* :class:`StampCaptureContext`     — modal: intercepts keys during preset naming
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pygame
from pygame.locals import (
    KEYDOWN, MOUSEBUTTONDOWN, MOUSEBUTTONUP, MOUSEWHEEL,
)

from editor.input_context import InputContext
from editor.keybinds import _simplify_mods, MOD_CTRL, MOD_SHIFT

if TYPE_CHECKING:
    from editor.app.app import ZoneEditorApp


# ── Helpers ───────────────────────────────────────────────────────

# Keybind actions handled exclusively by GlobalShortcutsContext.
# CapturedViewportContext lets these pass through (returns False)
# so they can bubble down the stack.
_GLOBAL_ACTIONS: frozenset[str] = frozenset({
    "file.save",
    "edit.undo",
    "edit.redo_cy",
    "edit.redo_cz",
    "view.toggle",
})

# Numpad-row pygame key → bookmark slot (0-based)
_NUM_KEYS: dict[int, int] = {
    pygame.K_1: 0, pygame.K_2: 1, pygame.K_3: 2,
    pygame.K_4: 3, pygame.K_5: 4, pygame.K_6: 5,
    pygame.K_7: 6, pygame.K_8: 7, pygame.K_9: 8,
}


def _is_global_shortcut(key: int, mods: int, app: ZoneEditorApp) -> bool:
    """Return True if *key* + simplified *mods* matches any action in
    :data:`_GLOBAL_ACTIONS` via the keybind registry, **or** is a
    hard-coded combo that GlobalShortcutsContext handles (Ctrl+Shift+S,
    Ctrl+N, Ctrl+F, bookmark combos)."""
    kb_reg = app.editor_3d.kb if app.editor_3d else None
    if kb_reg:
        for action in _GLOBAL_ACTIONS:
            if kb_reg.check(action, key, mods):
                return True

    flags = _simplify_mods(mods)
    # Ctrl+Shift+S  (save-as)
    if key == pygame.K_s and flags == (MOD_CTRL | MOD_SHIFT):
        return True
    # Ctrl+N  (new zone)
    if key == pygame.K_n and flags == MOD_CTRL:
        return True
    # Ctrl+F  (find/replace texture)
    if key == pygame.K_f and flags == MOD_CTRL:
        return True
    # Bookmark combos: Shift+1-9, Ctrl+Shift+1-9
    if key in _NUM_KEYS:
        if (flags & MOD_SHIFT) and not (flags & MOD_CTRL):
            return True
        if (flags & MOD_CTRL) and (flags & MOD_SHIFT):
            return True

    return False


# ══════════════════════════════════════════════════════════════════
#  GlobalShortcutsContext
# ══════════════════════════════════════════════════════════════════

class GlobalShortcutsContext(InputContext):
    """Bottom of the stack — catches events that bubble down from above.

    Handles global editor shortcuts that should work identically whether
    the viewport is captured or not:

    * Ctrl+S / Ctrl+Shift+S — save / save-as
    * Ctrl+Z / Ctrl+Y / Ctrl+Shift+Z — undo / redo
    * TAB — toggle 3D / preview
    * Ctrl+N — new zone
    * Ctrl+F — find / replace texture
    * Shift+1-9 / Ctrl+Shift+1-9 — camera bookmarks

    When the viewport is **not** captured, also handles:

    * Escape — close dialog or quit
    * Enter / F5 — enter captured mode
    * Left-click outside imgui — enter captured mode
    """

    name = "global_shortcuts"

    def handle_event(self, event: pygame.event.Event,
                     app: ZoneEditorApp) -> bool:

        if event.type == KEYDOWN:
            return self._handle_keydown(event, app)

        # Non-captured: click on viewport → capture
        if event.type == MOUSEBUTTONDOWN and event.button == 1:
            if not app.input_stack.is_captured:
                return self._try_capture_click(event, app)

        return False

    # ── Keydown routing ───────────────────────────────────────────

    def _handle_keydown(self, event: pygame.event.Event,
                        app: ZoneEditorApp) -> bool:
        key = event.key
        raw_mods = pygame.key.get_mods()
        flags = _simplify_mods(raw_mods)
        kb = app.editor_3d.kb if app.editor_3d else None

        # ── Global keybinds (via registry) ────────────────────────

        # File save
        if kb and kb.check("file.save", key, raw_mods):
            app._save_zone()
            return True

        # Ctrl+Shift+S → save-as  (not in registry)
        if key == pygame.K_s and flags == (MOD_CTRL | MOD_SHIFT):
            app.save_as_name = (
                app.zone_name if app.zone_name != "untitled" else ""
            )
            app.show_save_as = True
            return True

        # Undo
        if kb and kb.check("edit.undo", key, raw_mods):
            if app.editor_3d:
                app.editor_3d._undo()
            return True

        # Redo (Ctrl+Y or Ctrl+Shift+Z)
        if kb and kb.check("edit.redo_cz", key, raw_mods):
            if app.editor_3d:
                app.editor_3d._redo()
            return True
        if kb and kb.check("edit.redo_cy", key, raw_mods):
            if app.editor_3d:
                app.editor_3d._redo()
            return True

        # Ctrl+N → new zone  (not in registry)
        if key == pygame.K_n and flags == MOD_CTRL:
            if app._request_guarded("new"):
                app.show_new_zone = True
            return True

        # Ctrl+F → find/replace texture  (not in registry)
        if key == pygame.K_f and flags == MOD_CTRL:
            app.show_find_replace_tex = True
            app._frt_find = ""
            app._frt_replace = ""
            app._frt_result = ""
            return True

        # TAB → toggle view mode
        if kb and kb.check("view.toggle", key, raw_mods):
            if app.zone:
                app._toggle_view_mode()
            return True

        # Camera bookmarks: Ctrl+Shift+1-9 saves, Shift+1-9 recalls
        if key in _NUM_KEYS:
            slot = _NUM_KEYS[key]
            if (flags & MOD_CTRL) and (flags & MOD_SHIFT):
                app._save_camera_bookmark(slot)
                return True
            if (flags & MOD_SHIFT) and not (flags & MOD_CTRL):
                app._recall_camera_bookmark(slot)
                return True

        # ── Uncaptured-only shortcuts ─────────────────────────────

        if not app.input_stack.is_captured:
            return self._uncaptured_keydown(event, app)

        return False

    def _uncaptured_keydown(self, event: pygame.event.Event,
                            app: ZoneEditorApp) -> bool:
        """Handle keys that only apply when the viewport is NOT captured."""
        key = event.key

        # Escape → close dialog / quit
        if key == pygame.K_ESCAPE:
            if app.dialog_manager.close_any():
                return True
            if not app._should_keep_running_after_quit():
                app._wants_quit = True
            return True

        # Enter / F5 → capture viewport
        if (key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_F5)
                and app.zone
                and not app.dialog_manager.any_modal_open()):
            app._capture_mouse()
            return True

        return False

    # ── Click-to-capture ──────────────────────────────────────────

    @staticmethod
    def _try_capture_click(event: pygame.event.Event,
                           app: ZoneEditorApp) -> bool:
        """Left-click outside imgui → enter captured mode."""
        import imgui
        io = imgui.get_io()
        if not io.want_capture_mouse and app.zone:
            app._capture_mouse()
            return True
        return False


# ══════════════════════════════════════════════════════════════════
#  CapturedViewportContext
# ══════════════════════════════════════════════════════════════════

class CapturedViewportContext(InputContext):
    """Pushed when the viewport grabs the mouse.

    * Escape pops this context (via a priority chain).
    * Mouse / scroll events go straight to ``editor_3d``.
    * Key events that match a global shortcut are **not** consumed — they
      bubble down to :class:`GlobalShortcutsContext`.
    * All other key events are forwarded to ``editor_3d.handle_event()``.
    """

    name = "captured_viewport"

    # ── Lifecycle ─────────────────────────────────────────────────

    def on_push(self, app: ZoneEditorApp) -> None:
        app._do_capture_mouse()

    def on_pop(self, app: ZoneEditorApp) -> None:
        app._do_release_mouse()

    # ── Dispatch ──────────────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event,
                     app: ZoneEditorApp) -> bool:

        if event.type == KEYDOWN:
            return self._handle_keydown(event, app)

        if event.type in (MOUSEBUTTONDOWN, MOUSEBUTTONUP):
            if app.view_mode == "3d" and app.editor_3d:
                app.editor_3d.handle_event(event)
            return True  # always consume mouse in captured mode

        if event.type == MOUSEWHEEL:
            self._handle_scroll(event, app)
            return True

        return True  # consume everything else in captured mode

    # ── Key handling ──────────────────────────────────────────────

    def _handle_keydown(self, event: pygame.event.Event,
                        app: ZoneEditorApp) -> bool:
        key = event.key
        raw_mods = pygame.key.get_mods()

        # Escape priority chain:
        #   1. (StampCaptureContext handles stamp naming — sits above us)
        #   2. Deselect object-layer objects       (stay captured)
        #   3. Cancel active cell selection         (stay captured)
        #   4. Pop this context                     (release mouse)
        if key == pygame.K_ESCAPE:
            ed = app.editor_3d
            if app.view_mode == "3d" and ed:
                if ed.objects.any_selected():
                    ed.objects.deselect_all()
                    return True
                if (ed.selection.has_anything()
                        or ed.selection.rect_in_progress):
                    ed._sel_cancel()
                    return True
            app.input_stack.pop(app)  # pops self → on_pop releases mouse
            return True

        # Let global shortcuts bubble down to GlobalShortcutsContext
        if _is_global_shortcut(key, raw_mods, app):
            return False

        # Forward everything else to the active view
        if app.view_mode == "3d" and app.editor_3d:
            old_snap = app.editor_3d.snap_idx
            app.editor_3d.handle_event(event)
            # Flash transient if snap changed via G key
            if app.editor_3d.snap_idx != old_snap:
                snap_labels = ("1/16", "1/8", "1/4", "1/2", "1")
                idx = app.editor_3d.snap_idx
                app._flash_transient(
                    f"Snap: {snap_labels[idx]}",
                    1.2, (0.55, 0.75, 0.60, 1.0))
        elif app.view_mode == "2d":
            app._raycaster_key(event)

        return True  # consume — even if editor_3d didn't care

    # ── Scroll handling ───────────────────────────────────────────

    @staticmethod
    def _handle_scroll(event: pygame.event.Event,
                       app: ZoneEditorApp) -> None:
        """Forward scroll to editor and flash transient feedback."""
        from editor.view_3d import _ensure_palette

        ed = app.editor_3d
        if not ed:
            return
        old_tex = ed.tex_idx
        old_snap = ed.snap_idx
        old_stamp = getattr(ed, '_stamp_idx', -1)

        ed.handle_event(event)

        # Transient feedback
        if ed.tex_idx != old_tex:
            palette = _ensure_palette()
            idx = ed.tex_idx
            name = palette[idx] if idx < len(palette) else "?"
            app._flash_transient(
                f"{name}  ({idx + 1}/{len(palette)})",
                1.5, (0.75, 0.55, 0.85, 1.0))
        elif ed.snap_idx != old_snap:
            snap_labels = ("1/16", "1/8", "1/4", "1/2", "1")
            idx = ed.snap_idx
            app._flash_transient(
                f"Snap: {snap_labels[idx]}",
                1.2, (0.55, 0.75, 0.60, 1.0))
        elif getattr(ed, '_stamp_idx', -1) != old_stamp:
            preset = ed._stamp_current()
            pname = preset.name if preset else "?"
            app._flash_transient(
                f"Preset: {pname}",
                1.5, (0.70, 0.55, 1.0, 1.0))


# ══════════════════════════════════════════════════════════════════
#  StampCaptureContext
# ══════════════════════════════════════════════════════════════════

class StampCaptureContext(InputContext):
    """Modal key interception during stamp preset naming.

    Pushed by the per-event sync when ``editor_3d._capture_pending`` is
    ``True``.  Intercepts **all** ``KEYDOWN`` events for typing the preset
    name (Backspace, printable chars, Enter to commit, Escape to cancel).
    Non-key events (mouse, scroll) pass through to the contexts below so
    the viewport keeps rendering and the user can still look around.

    ``on_pop`` cancels the naming session if it hasn't already been committed.
    """

    name = "stamp_capture"

    def handle_event(self, event: pygame.event.Event,
                     app: ZoneEditorApp) -> bool:
        if event.type != KEYDOWN:
            return False  # mouse/scroll pass through

        ed = app.editor_3d
        if not ed:
            return True  # consume key with no editor (shouldn't happen)

        if event.key == pygame.K_ESCAPE:
            app.input_stack.pop(app)  # on_pop cancels naming
            return True

        # Forward the keystroke to the stamp mixin's key handler.
        ed._stamp_capture_key(event.key, event.unicode)

        # If the handler just committed (e.g. Enter key cleared
        # _capture_pending), pop ourselves so the stack is clean
        # without waiting for the next sync cycle.
        if not ed._capture_pending:
            app.input_stack.pop(app)

        return True

    def on_pop(self, app: ZoneEditorApp) -> None:
        ed = app.editor_3d
        if ed and getattr(ed, '_capture_pending', False):
            ed._capture_pending = False
            ed._capture_name = ""
