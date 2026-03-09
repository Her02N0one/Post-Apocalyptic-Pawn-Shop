"""editor/app/events.py — EventsMixin: input routing via InputStack.

All event-dispatch logic now lives in the :class:`~editor.input_context.InputStack`
and its concrete :class:`~editor.contexts.InputContext` implementations.
This mixin retains framework-level helpers (transient flash, quit guard)
and the main event pump that feeds events into the stack.

A per-event **sync** step ensures that transient editor sub-states
(stamp-capture naming, etc.) are reflected as stack contexts *before*
the event is dispatched, so that Escape always pops the right one.
"""

from __future__ import annotations

import pygame
from pygame.locals import QUIT, VIDEORESIZE

from editor.contexts import StampCaptureContext


class EventsMixin:
    """Pygame event routing mixin for :class:`ZoneEditorApp`.

    The heavy lifting is done by :attr:`input_stack` — this mixin just
    drives the per-frame event pump and provides a few shared helpers.
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
            if self._request_guarded("quit"):
                return False   # not dirty after all — exit now
            return True        # guard dialog is now visible — stay alive
        return False           # nothing unsaved — exit now

    # ── Input context sync ────────────────────────────────────────

    def _sync_input_contexts(self) -> None:
        """Push or remove sub-state contexts so the stack reflects reality.

        Called **before every event** in the pump so that state changes
        from the previous event (e.g. ``_stamp_capture_begin`` setting
        ``_capture_pending = True``) produce the matching context in
        time for the very next event.
        """
        stack = self.input_stack

        # Nothing to manage when the viewport is not captured.
        if not stack.is_captured:
            if stack.has("stamp_capture"):
                stack.remove("stamp_capture", self)
            return

        ed = self.editor_3d
        if not ed or self.view_mode != "3d":
            if stack.has("stamp_capture"):
                stack.remove("stamp_capture", self)
            return

        # ── Stamp-capture naming mode ─────────────────────────────
        want_stamp = (ed.tool == "stamp"
                      and getattr(ed, '_capture_pending', False))
        has_stamp = stack.has("stamp_capture")

        if want_stamp and not has_stamp:
            stack.push(StampCaptureContext(), self)
        elif not want_stamp and has_stamp:
            stack.remove("stamp_capture", self)

    # ── Main event pump ───────────────────────────────────────────

    def _process_events(self) -> bool:
        import imgui

        for event in pygame.event.get():
            # ── Window close ──────────────────────────────────────
            if event.type == QUIT:
                if not self._should_keep_running_after_quit():
                    return False
                continue

            # ── Window resize ─────────────────────────────────────
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

            # ── ImGui gets events when viewport is NOT captured ───
            if not self.input_stack.is_captured:
                self.imgui_impl.process_event(event)

            # ── Sync sub-state contexts before dispatch ───────────
            self._sync_input_contexts()

            # ── Dispatch through the InputStack (top → bottom) ────
            self.input_stack.dispatch(event, self)

            # ── Check if GlobalShortcutsContext signalled quit ─────
            if getattr(self, '_wants_quit', False):
                return False

        return True

    # ── Dialog helpers (delegate to DialogManager) ────────────────

    def _any_modal_open(self) -> bool:
        """Return True if any modal dialog is currently shown."""
        return self.dialog_manager.any_modal_open()

    def _close_any_dialog(self) -> bool:
        """Close the first open dialog/window and return True, or False."""
        return self.dialog_manager.close_any()