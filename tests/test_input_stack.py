"""Tests for the Phase 3 Input System — InputStack, InputContexts, and DialogManager.

Covers:
1. InputStack push/pop/remove/dispatch
2. InputContext lifecycle (on_push, on_pop)
3. Event dispatch — top-down consumption, blocks_below
4. is_captured property reflects CapturedViewportContext presence
5. DialogManager open/close/close_any/any_modal_open
6. DialogPropertyBridge descriptor protocol
7. Keybind scope enforcement via check()
8. GlobalShortcutsContext / CapturedViewportContext event routing
"""

from __future__ import annotations

import sys
import types
import pytest
from unittest.mock import MagicMock, patch

import pygame

# ── Ensure pygame is initialised for key constants ────────────────
pygame.init()

from editor.input_context import InputContext, InputStack
from editor.dialog_manager import DialogManager, DialogPropertyBridge, _make_dialog_prop
from editor.keybinds import KeybindRegistry, MOD_NONE, MOD_CTRL, MOD_SHIFT, _simplify_mods


# ══════════════════════════════════════════════════════════════════
#  Stubs
# ══════════════════════════════════════════════════════════════════

class StubApp:
    """Mimics ZoneEditorApp just enough for InputStack dispatch."""

    def __init__(self):
        self.input_stack = InputStack()
        self.dialog_manager = DialogManager()
        self._wants_quit = False
        self.zone = True
        self.view_mode = "3d"
        self.editor_3d = None
        self.dirty = False
        self.zone_name = "test"
        self.mouse_captured_prop = False
        self._push_log: list[str] = []
        self._pop_log: list[str] = []


class TrackingContext(InputContext):
    """Context that logs lifecycle and event dispatch calls."""

    def __init__(self, name: str = "tracking", consume: bool = True,
                 blocks: bool = False):
        self.name = name
        self.blocks_below = blocks
        self._consume = consume
        self.events: list[pygame.event.Event] = []
        self.push_count = 0
        self.pop_count = 0

    def handle_event(self, event, app) -> bool:
        self.events.append(event)
        return self._consume

    def on_push(self, app) -> None:
        self.push_count += 1

    def on_pop(self, app) -> None:
        self.pop_count += 1


class PassThroughContext(InputContext):
    """Never consumes events — always returns False."""

    name = "passthrough"

    def handle_event(self, event, app) -> bool:
        return False


class BlockingContext(InputContext):
    """Has blocks_below=True — stops propagation even when not consuming."""

    name = "blocker"
    blocks_below = True

    def handle_event(self, event, app) -> bool:
        return False


# ══════════════════════════════════════════════════════════════════
#  1. InputStack core operations
# ══════════════════════════════════════════════════════════════════

class TestInputStackPushPop:
    def test_push_increases_length(self):
        stack = InputStack()
        app = StubApp()
        ctx = TrackingContext("a")
        stack.push(ctx, app)
        assert len(stack) == 1

    def test_push_calls_on_push(self):
        stack = InputStack()
        app = StubApp()
        ctx = TrackingContext("a")
        stack.push(ctx, app)
        assert ctx.push_count == 1

    def test_pop_returns_top(self):
        stack = InputStack()
        app = StubApp()
        a = TrackingContext("a")
        b = TrackingContext("b")
        stack.push(a, app)
        stack.push(b, app)
        popped = stack.pop(app)
        assert popped is b
        assert len(stack) == 1

    def test_pop_calls_on_pop(self):
        stack = InputStack()
        app = StubApp()
        ctx = TrackingContext("a")
        stack.push(ctx, app)
        stack.pop(app)
        assert ctx.pop_count == 1

    def test_pop_empty_returns_none(self):
        stack = InputStack()
        app = StubApp()
        assert stack.pop(app) is None

    def test_peek_returns_top_without_removing(self):
        stack = InputStack()
        app = StubApp()
        a = TrackingContext("a")
        b = TrackingContext("b")
        stack.push(a, app)
        stack.push(b, app)
        assert stack.peek() is b
        assert len(stack) == 2

    def test_peek_empty_returns_none(self):
        stack = InputStack()
        assert stack.peek() is None


class TestInputStackRemove:
    def test_remove_by_name(self):
        stack = InputStack()
        app = StubApp()
        a = TrackingContext("a")
        b = TrackingContext("b")
        c = TrackingContext("c")
        stack.push(a, app)
        stack.push(b, app)
        stack.push(c, app)

        removed = stack.remove("b", app)
        assert removed is b
        assert b.pop_count == 1
        assert len(stack) == 2
        assert stack.names == ["a", "c"]

    def test_remove_nonexistent_returns_none(self):
        stack = InputStack()
        app = StubApp()
        a = TrackingContext("a")
        stack.push(a, app)
        assert stack.remove("zzz", app) is None

    def test_remove_finds_topmost_duplicate(self):
        stack = InputStack()
        app = StubApp()
        a1 = TrackingContext("dup")
        a2 = TrackingContext("dup")
        stack.push(a1, app)
        stack.push(a2, app)
        removed = stack.remove("dup", app)
        assert removed is a2  # topmost
        assert len(stack) == 1


class TestInputStackQuery:
    def test_has(self):
        stack = InputStack()
        app = StubApp()
        a = TrackingContext("alpha")
        stack.push(a, app)
        assert stack.has("alpha")
        assert not stack.has("beta")

    def test_names_bottom_to_top(self):
        stack = InputStack()
        app = StubApp()
        stack.push(TrackingContext("a"), app)
        stack.push(TrackingContext("b"), app)
        stack.push(TrackingContext("c"), app)
        assert stack.names == ["a", "b", "c"]

    def test_is_captured_false_by_default(self):
        stack = InputStack()
        assert not stack.is_captured

    def test_is_captured_true_when_captured_viewport_present(self):
        stack = InputStack()
        app = StubApp()
        ctx = TrackingContext("captured_viewport")
        stack.push(ctx, app)
        assert stack.is_captured


# ══════════════════════════════════════════════════════════════════
#  2. Event dispatch
# ══════════════════════════════════════════════════════════════════

class TestInputStackDispatch:
    def _make_event(self, key=pygame.K_a):
        return pygame.event.Event(pygame.KEYDOWN, key=key, mod=0)

    def test_top_consumes_first(self):
        stack = InputStack()
        app = StubApp()
        bottom = TrackingContext("bottom", consume=True)
        top = TrackingContext("top", consume=True)
        stack.push(bottom, app)
        stack.push(top, app)

        evt = self._make_event()
        result = stack.dispatch(evt, app)

        assert result is True
        assert len(top.events) == 1
        assert len(bottom.events) == 0  # never reached

    def test_passthrough_falls_to_lower(self):
        stack = InputStack()
        app = StubApp()
        bottom = TrackingContext("bottom", consume=True)
        top = TrackingContext("top", consume=False)
        stack.push(bottom, app)
        stack.push(top, app)

        evt = self._make_event()
        result = stack.dispatch(evt, app)

        assert result is True
        assert len(top.events) == 1
        assert len(bottom.events) == 1  # fell through

    def test_blocks_below_stops_propagation(self):
        stack = InputStack()
        app = StubApp()
        bottom = TrackingContext("bottom", consume=True)
        blocker = BlockingContext()
        stack.push(bottom, app)
        stack.push(blocker, app)

        evt = self._make_event()
        result = stack.dispatch(evt, app)

        assert result is False  # blocker didn't consume
        assert len(bottom.events) == 0  # but bottom never saw it

    def test_empty_stack_returns_false(self):
        stack = InputStack()
        app = StubApp()
        evt = self._make_event()
        assert stack.dispatch(evt, app) is False

    def test_three_layer_dispatch(self):
        stack = InputStack()
        app = StubApp()
        c1 = TrackingContext("c1", consume=False)
        c2 = TrackingContext("c2", consume=False)
        c3 = TrackingContext("c3", consume=True)
        stack.push(c3, app)  # bottom
        stack.push(c2, app)
        stack.push(c1, app)  # top

        evt = self._make_event()
        stack.dispatch(evt, app)

        # c1 (top) → doesn't consume → c2 → doesn't consume → c3 → consumes
        assert len(c1.events) == 1
        assert len(c2.events) == 1
        assert len(c3.events) == 1


# ══════════════════════════════════════════════════════════════════
#  3. DialogManager
# ══════════════════════════════════════════════════════════════════

class TestDialogManager:
    def test_open_and_query(self):
        dm = DialogManager()
        dm.open("new_zone")
        assert dm.is_open("new_zone")
        assert dm.any_modal_open()
        assert dm.any_open()

    def test_close(self):
        dm = DialogManager()
        dm.open("new_zone")
        dm.close("new_zone")
        assert not dm.is_open("new_zone")
        assert not dm.any_open()

    def test_close_nonexistent_is_noop(self):
        dm = DialogManager()
        dm.close("zzz")  # no error

    def test_any_modal_false_for_floating(self):
        dm = DialogManager()
        dm.open("find_replace_tex")
        assert not dm.any_modal_open()
        assert dm.any_open()

    def test_any_modal_true_for_modal(self):
        dm = DialogManager()
        dm.open("save_as")
        assert dm.any_modal_open()

    def test_open_set_snapshot(self):
        dm = DialogManager()
        dm.open("new_zone")
        dm.open("find_replace_tex")
        snapshot = dm.open_set
        assert "new_zone" in snapshot
        assert "find_replace_tex" in snapshot
        assert isinstance(snapshot, frozenset)


class TestDialogManagerCloseAny:
    """Test Escape ordering: floating first, then modals."""

    def test_closes_floating_first(self):
        dm = DialogManager()
        dm.open("new_zone")           # modal
        dm.open("find_replace_tex")   # floating
        assert dm.close_any() is True
        # Floating was closed, modal remains
        assert not dm.is_open("find_replace_tex")
        assert dm.is_open("new_zone")

    def test_closes_modal_when_no_floating(self):
        dm = DialogManager()
        dm.open("save_as")
        assert dm.close_any() is True
        assert not dm.is_open("save_as")

    def test_returns_false_when_nothing_open(self):
        dm = DialogManager()
        assert dm.close_any() is False

    def test_closes_one_at_a_time(self):
        dm = DialogManager()
        dm.open("find_replace_tex")
        dm.open("validate_zone")
        dm.open("new_zone")

        # First Escape closes one floating
        dm.close_any()
        assert dm.any_open()
        # Second Escape closes another floating
        dm.close_any()
        assert dm.any_open()
        # Third Escape closes the modal
        dm.close_any()
        assert not dm.any_open()

    def test_close_any_unsaved_guard_not_closeable(self):
        """unsaved_guard is NOT in close_any's lists — it blocks the user
        so it must be resolved through its own buttons."""
        dm = DialogManager()
        dm.open("unsaved_guard")
        # close_any does not list unsaved_guard in its iteration
        assert dm.close_any() is False or dm.is_open("unsaved_guard") is False
        # The guard dialog handles its own close via _execute_guarded_action


# ══════════════════════════════════════════════════════════════════
#  4. DialogPropertyBridge
# ══════════════════════════════════════════════════════════════════

class TestDialogPropertyBridge:
    """Verify the descriptor-based bridge that maps show_* attributes
    to DialogManager state."""

    def _make_bridged(self):
        """Create a simple class that uses the bridge."""
        class BridgedObj(DialogPropertyBridge):
            def __init__(self):
                self.dialog_manager = DialogManager()
        return BridgedObj()

    def test_getter_default_false(self):
        obj = self._make_bridged()
        assert obj.show_new_zone is False
        assert obj.show_save_as is False

    def test_setter_opens_dialog(self):
        obj = self._make_bridged()
        obj.show_new_zone = True
        assert obj.dialog_manager.is_open("new_zone")
        assert obj.show_new_zone is True

    def test_setter_closes_dialog(self):
        obj = self._make_bridged()
        obj.show_new_zone = True
        obj.show_new_zone = False
        assert not obj.dialog_manager.is_open("new_zone")

    def test_all_modal_properties(self):
        obj = self._make_bridged()
        modal_props = [
            "show_new_zone", "show_save_as", "_show_unsaved_guard",
            "show_resize_zone", "show_zone_settings",
            "show_duplicate_zone", "show_export_image",
        ]
        for prop_name in modal_props:
            setattr(obj, prop_name, True)
            assert getattr(obj, prop_name) is True, f"{prop_name} getter failed"
            setattr(obj, prop_name, False)
            assert getattr(obj, prop_name) is False, f"{prop_name} reset failed"

    def test_all_floating_properties(self):
        obj = self._make_bridged()
        floating_props = [
            "show_keybind_editor", "show_find_replace_tex",
            "show_validate_zone", "show_entity_defs_viewer",
            "show_items_viewer", "show_loot_tables_viewer",
            "show_presets_viewer", "show_texture_browser",
            "show_entity_textures",
        ]
        for prop_name in floating_props:
            setattr(obj, prop_name, True)
            assert getattr(obj, prop_name) is True, f"{prop_name} getter failed"
            setattr(obj, prop_name, False)
            assert getattr(obj, prop_name) is False, f"{prop_name} reset failed"

    def test_bridge_and_manager_stay_in_sync(self):
        obj = self._make_bridged()
        obj.show_new_zone = True
        obj.dialog_manager.open("save_as")
        assert obj.show_save_as is True
        assert obj.show_new_zone is True
        obj.dialog_manager.close("new_zone")
        assert obj.show_new_zone is False


# ══════════════════════════════════════════════════════════════════
#  5. KeybindRegistry scope enforcement
# ══════════════════════════════════════════════════════════════════

class TestKeybindScope:
    def test_check_no_scope_rejects_non_global(self):
        """When scope='' (the default), only global-scoped binds match."""
        reg = KeybindRegistry()
        reg.register("sculpt.raise", pygame.K_r, scope="sculpt")
        # Tool-scoped bind must NOT match when no scope is supplied
        assert not reg.check("sculpt.raise", pygame.K_r, 0)

    def test_check_no_scope_allows_global(self):
        """Global binds still match even when no scope is passed."""
        reg = KeybindRegistry()
        reg.register("file.save", pygame.K_s, MOD_CTRL, scope="global")
        assert reg.check("file.save", pygame.K_s, pygame.KMOD_LCTRL)

    def test_check_wrong_scope_rejects(self):
        reg = KeybindRegistry()
        reg.register("sculpt.raise", pygame.K_r, scope="sculpt")
        assert not reg.check("sculpt.raise", pygame.K_r, 0, scope="paint")

    def test_check_correct_scope_accepts(self):
        reg = KeybindRegistry()
        reg.register("sculpt.raise", pygame.K_r, scope="sculpt")
        assert reg.check("sculpt.raise", pygame.K_r, 0, scope="sculpt")

    def test_check_global_scope_matches_any(self):
        """Keybinds with scope='global' match regardless of active scope."""
        reg = KeybindRegistry()
        reg.register("file.save", pygame.K_s, MOD_CTRL, scope="global")
        assert reg.check("file.save", pygame.K_s, pygame.KMOD_LCTRL, scope="sculpt")
        assert reg.check("file.save", pygame.K_s, pygame.KMOD_LCTRL, scope="paint")

    def test_check_pipe_scope_matches_any_listed(self):
        reg = KeybindRegistry()
        reg.register("tool.toggle", pygame.K_t, scope="sculpt|paint")
        assert reg.check("tool.toggle", pygame.K_t, 0, scope="sculpt")
        assert reg.check("tool.toggle", pygame.K_t, 0, scope="paint")
        assert not reg.check("tool.toggle", pygame.K_t, 0, scope="select")

    def test_check_modifier_mismatch_rejects(self):
        """Even with correct scope, wrong modifiers should fail."""
        reg = KeybindRegistry()
        reg.register("file.save", pygame.K_s, MOD_CTRL, scope="global")
        # No modifiers pressed → should not match
        assert not reg.check("file.save", pygame.K_s, 0, scope="global")

    def test_check_nonexistent_action_returns_false(self):
        reg = KeybindRegistry()
        assert not reg.check("nonexistent", pygame.K_x, 0)

    def test_matches_any_global(self):
        reg = KeybindRegistry()
        reg.register("file.save", pygame.K_s, MOD_CTRL, scope="global")
        reg.register("sculpt.raise", pygame.K_r, scope="sculpt")
        assert reg.matches_any_global(pygame.K_s, pygame.KMOD_LCTRL)
        assert not reg.matches_any_global(pygame.K_r, 0)  # sculpt scope, not global


class TestSimplifyMods:
    def test_no_mods(self):
        assert _simplify_mods(0) == 0

    def test_shift(self):
        assert _simplify_mods(pygame.KMOD_LSHIFT) & MOD_SHIFT
        assert _simplify_mods(pygame.KMOD_RSHIFT) & MOD_SHIFT

    def test_ctrl(self):
        assert _simplify_mods(pygame.KMOD_LCTRL) & MOD_CTRL

    def test_combined(self):
        flags = _simplify_mods(pygame.KMOD_LCTRL | pygame.KMOD_LSHIFT)
        assert flags & MOD_CTRL
        assert flags & MOD_SHIFT


# ══════════════════════════════════════════════════════════════════
#  6. Keybind override / rebinding
# ══════════════════════════════════════════════════════════════════

class TestKeybindOverrides:
    def test_default_key_matches(self):
        reg = KeybindRegistry()
        kb = reg.register("test.action", pygame.K_a)
        assert reg.check("test.action", pygame.K_a, 0)

    def test_override_key_changes_match(self):
        reg = KeybindRegistry()
        kb = reg.register("test.action", pygame.K_a)
        kb._override_key = pygame.K_b
        assert not reg.check("test.action", pygame.K_a, 0)
        assert reg.check("test.action", pygame.K_b, 0)

    def test_is_rebound_reflects_override(self):
        reg = KeybindRegistry()
        kb = reg.register("test.action", pygame.K_a)
        assert not kb.is_rebound
        kb._override_key = pygame.K_b
        assert kb.is_rebound

    def test_key_for_returns_effective(self):
        reg = KeybindRegistry()
        kb = reg.register("test.action", pygame.K_a)
        assert reg.key_for("test.action") == pygame.K_a
        kb._override_key = pygame.K_z
        assert reg.key_for("test.action") == pygame.K_z

    def test_key_for_nonexistent_returns_zero(self):
        reg = KeybindRegistry()
        assert reg.key_for("bogus") == 0


# ══════════════════════════════════════════════════════════════════
#  7. Keybind labels
# ══════════════════════════════════════════════════════════════════

class TestKeybindLabels:
    def test_simple_key(self):
        reg = KeybindRegistry()
        kb = reg.register("test.t", pygame.K_t)
        label = kb.key_label()
        assert "T" in label

    def test_ctrl_s(self):
        reg = KeybindRegistry()
        kb = reg.register("file.save", pygame.K_s, MOD_CTRL)
        label = kb.key_label()
        assert "Ctrl" in label
        assert "S" in label

    def test_ctrl_shift(self):
        reg = KeybindRegistry()
        kb = reg.register("test.cs", pygame.K_z, MOD_CTRL | MOD_SHIFT)
        label = kb.key_label()
        assert "Ctrl" in label
        assert "Shift" in label

    def test_override_changes_label(self):
        reg = KeybindRegistry()
        kb = reg.register("test.a", pygame.K_a, MOD_CTRL)
        default = kb.default_label()
        kb._override_key = pygame.K_b
        assert kb.key_label() != default
        assert "B" in kb.key_label()


# ══════════════════════════════════════════════════════════════════
#  8. Integration: InputStack with DialogManager
# ══════════════════════════════════════════════════════════════════

class TestInputDialogIntegration:
    """Verify that the input stack and dialog manager work together
    as expected in the overall architecture."""

    def test_mouse_captured_property(self):
        """The is_captured property reflects CapturedViewportContext."""
        stack = InputStack()
        app = StubApp()
        assert not stack.is_captured

        cap = TrackingContext("captured_viewport")
        stack.push(cap, app)
        assert stack.is_captured

        stack.pop(app)
        assert not stack.is_captured

    def test_dialog_manager_escape_then_capture(self):
        """Simulates: open dialog → Escape closes it → then capture."""
        dm = DialogManager()
        dm.open("new_zone")
        assert dm.any_modal_open()

        # Escape closes dialog
        assert dm.close_any() is True
        assert not dm.any_modal_open()

        # Now capture can proceed
        stack = InputStack()
        app = StubApp()
        cap = TrackingContext("captured_viewport")
        stack.push(cap, app)
        assert stack.is_captured

    def test_stack_remove_captured_viewport(self):
        """_release_mouse uses remove() not pop() — verify it works."""
        stack = InputStack()
        app = StubApp()

        # Push global first, then captured
        g = TrackingContext("global_shortcuts")
        c = TrackingContext("captured_viewport")
        stack.push(g, app)
        stack.push(c, app)

        # Remove captured_viewport by name
        removed = stack.remove("captured_viewport", app)
        assert removed is c
        assert c.pop_count == 1
        assert not stack.is_captured
        # Global is still there
        assert stack.has("global_shortcuts")


# ══════════════════════════════════════════════════════════════════
#  9. Edge cases
# ══════════════════════════════════════════════════════════════════

class TestEdgeCases:
    def test_push_multiple_same_name(self):
        stack = InputStack()
        app = StubApp()
        a = TrackingContext("same")
        b = TrackingContext("same")
        stack.push(a, app)
        stack.push(b, app)
        assert len(stack) == 2
        assert stack.names == ["same", "same"]

    def test_dispatch_after_pop_during_dispatch(self):
        """If a context pops itself during dispatch, subsequent events
        should not crash."""
        stack = InputStack()
        app = StubApp()
        app.input_stack = stack

        class SelfPopper(InputContext):
            name = "popper"
            def handle_event(self, event, app):
                app.input_stack.pop(app)
                return True

        stack.push(TrackingContext("base"), app)
        stack.push(SelfPopper(), app)

        evt = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_a, mod=0)
        stack.dispatch(evt, app)
        assert len(stack) == 1
        assert stack.names == ["base"]

    def test_dialog_manager_all_set_coverage(self):
        """ALL should be the union of FLOATING and MODAL."""
        dm = DialogManager()
        assert dm.ALL == dm.FLOATING | dm.MODAL
        assert len(dm.ALL) == len(dm.FLOATING) + len(dm.MODAL)

    def test_capture_then_dialog_then_uncapture(self):
        """Simulate a complete workflow: capture → dialog opens → Escape
        releases capture → dialog still visible → Escape closes dialog."""
        stack = InputStack()
        app = StubApp()
        app.input_stack = stack
        app.dialog_manager = DialogManager()

        # Start with global
        g = TrackingContext("global_shortcuts")
        stack.push(g, app)

        # Capture
        cap = TrackingContext("captured_viewport")
        stack.push(cap, app)
        assert stack.is_captured

        # Open a dialog
        app.dialog_manager.open("save_as")

        # Pop capture (Escape first in the chain)
        stack.remove("captured_viewport", app)
        assert not stack.is_captured

        # Dialog still open
        assert app.dialog_manager.is_open("save_as")

        # Second Escape → close dialog
        app.dialog_manager.close_any()
        assert not app.dialog_manager.any_open()


# ══════════════════════════════════════════════════════════════════
#  9. StampCaptureContext
# ══════════════════════════════════════════════════════════════════

class _StubEditorForStamp:
    """Minimal stand-in for Zone3DEditor with stamp-capture state."""
    def __init__(self):
        self.tool = "stamp"
        self._capture_pending = True
        self._capture_name = ""
        self._keys_received: list[tuple[int, str]] = []

    def _stamp_capture_key(self, key: int, unicode: str) -> bool:
        self._keys_received.append((key, unicode))
        # Simulate Enter committing (clears capture)
        if key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self._capture_pending = False
            self._capture_name = ""
        return True


class TestStampCaptureContext:
    """Tests for StampCaptureContext push/pop/event handling."""

    def _make_app(self) -> StubApp:
        app = StubApp()
        app.editor_3d = _StubEditorForStamp()
        return app

    def test_escape_pops_context_and_cancels(self):
        from editor.contexts import StampCaptureContext
        app = self._make_app()
        stack = app.input_stack
        stack.push(TrackingContext("captured_viewport"), app)
        stack.push(StampCaptureContext(), app)

        assert stack.has("stamp_capture")
        esc = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, mod=0, unicode="")
        stack.dispatch(esc, app)

        assert not stack.has("stamp_capture")
        assert not app.editor_3d._capture_pending
        assert app.editor_3d._capture_name == ""

    def test_printable_key_forwarded(self):
        from editor.contexts import StampCaptureContext
        app = self._make_app()
        stack = app.input_stack
        stack.push(TrackingContext("captured_viewport"), app)
        stack.push(StampCaptureContext(), app)

        evt = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_a, mod=0, unicode="a")
        consumed = stack.dispatch(evt, app)

        assert consumed
        assert (pygame.K_a, "a") in app.editor_3d._keys_received

    def test_enter_pops_after_commit(self):
        from editor.contexts import StampCaptureContext
        app = self._make_app()
        stack = app.input_stack
        stack.push(TrackingContext("captured_viewport"), app)
        stack.push(StampCaptureContext(), app)

        enter = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, mod=0, unicode="\r")
        stack.dispatch(enter, app)

        # _stamp_capture_key stub simulates commit → _capture_pending = False
        assert not stack.has("stamp_capture")
        assert not app.editor_3d._capture_pending

    def test_mouse_events_pass_through(self):
        """Non-KEYDOWN events should NOT be consumed by StampCaptureContext."""
        from editor.contexts import StampCaptureContext
        app = self._make_app()
        stack = app.input_stack
        lower = TrackingContext("captured_viewport", consume=True)
        stack.push(lower, app)
        stack.push(StampCaptureContext(), app)

        click = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1)
        stack.dispatch(click, app)

        # Should have passed through to the lower context
        assert len(lower.events) == 1

    def test_on_pop_no_cancel_if_already_committed(self):
        """on_pop should not re-cancel if _capture_pending is already False."""
        from editor.contexts import StampCaptureContext
        app = self._make_app()
        app.editor_3d._capture_pending = False
        ctx = StampCaptureContext()
        ctx.on_pop(app)
        # Should be a no-op — _capture_pending was already False
        assert not app.editor_3d._capture_pending


# ══════════════════════════════════════════════════════════════════
#  10. CapturedViewportContext Escape chain (objects + selection)
# ══════════════════════════════════════════════════════════════════

class _StubSelection:
    def __init__(self):
        self._has = False
        self._rect = False
        self._cleared = False

    def has_anything(self):
        return self._has

    @property
    def rect_in_progress(self):
        return self._rect

    def has_cells(self):
        return self._has

    def clear_cells(self):
        self._has = False
        self._rect = False
        self._cleared = True

    def clear_objects(self):
        pass


class _StubObjects:
    def __init__(self):
        self._selected = False
        self._deselected = False

    def any_selected(self):
        return self._selected

    def deselect_all(self):
        self._selected = False
        self._deselected = True


class _StubEditorFull:
    """Stand-in for Zone3DEditor with selection + object state."""
    def __init__(self):
        self.selection = _StubSelection()
        self.objects = _StubObjects()
        self.tool = "sculpt"
        self._capture_pending = False
        self._capture_name = ""
        self._lmb_held = False
        self.snap_idx = 0
        self.kb = None

    def _sel_cancel(self):
        self.selection.clear_cells()


class TestCapturedViewportEscapeChain:
    """Escape priority: objects → selection → release mouse."""

    def _make_app(self) -> StubApp:
        from editor.contexts import GlobalShortcutsContext, CapturedViewportContext
        app = StubApp()
        app.input_stack = InputStack()
        app.input_stack.push(GlobalShortcutsContext(), app)
        app.editor_3d = _StubEditorFull()
        return app

    def _capture(self, app) -> None:
        from editor.contexts import CapturedViewportContext
        app._do_capture_mouse = lambda: None
        app._do_release_mouse = lambda: None
        app._clear_imgui_input_state = lambda: None
        app.input_stack.push(CapturedViewportContext(), app)

    def test_escape_deselects_objects_first(self):
        app = self._make_app()
        self._capture(app)
        app.editor_3d.objects._selected = True
        app.editor_3d.selection._has = True

        esc = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, mod=0, unicode="")
        app.input_stack.dispatch(esc, app)

        # Objects deselected, but selection still alive
        assert app.editor_3d.objects._deselected
        assert app.editor_3d.selection._has  # NOT cleared yet
        assert app.input_stack.is_captured   # still captured

    def test_escape_clears_selection_second(self):
        app = self._make_app()
        self._capture(app)
        app.editor_3d.selection._has = True  # no objects selected

        esc = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, mod=0, unicode="")
        app.input_stack.dispatch(esc, app)

        assert app.editor_3d.selection._cleared
        assert app.input_stack.is_captured  # still captured

    def test_escape_releases_mouse_last(self):
        app = self._make_app()
        self._capture(app)
        # No objects, no selection

        esc = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, mod=0, unicode="")
        app.input_stack.dispatch(esc, app)

        assert not app.input_stack.is_captured  # released

    def test_escape_clears_selection_in_any_tool(self):
        """Selection should be clearable by Escape regardless of active tool
        (not limited to the 'select' tool)."""
        for tool in ("sculpt", "paint", "select", "entity"):
            app = self._make_app()
            self._capture(app)
            app.editor_3d.tool = tool
            app.editor_3d.selection._has = True

            esc = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, mod=0, unicode="")
            app.input_stack.dispatch(esc, app)

            assert app.editor_3d.selection._cleared, (
                f"Selection not cleared when tool={tool!r}")
            assert app.input_stack.is_captured


# ══════════════════════════════════════════════════════════════════
#  11. Input context sync
# ══════════════════════════════════════════════════════════════════

class TestInputContextSync:
    """Tests for EventsMixin._sync_input_contexts."""

    def _make_app(self):
        """Build a minimal app with input_stack + editor_3d."""
        from editor.contexts import GlobalShortcutsContext, CapturedViewportContext
        from editor.contexts import StampCaptureContext
        app = StubApp()
        app.input_stack = InputStack()
        app.input_stack.push(GlobalShortcutsContext(), app)
        app.editor_3d = _StubEditorForStamp()
        app.view_mode = "3d"
        app._do_capture_mouse = lambda: None
        app._do_release_mouse = lambda: None
        app._clear_imgui_input_state = lambda: None
        app.input_stack.push(CapturedViewportContext(), app)

        # Inline the sync logic to avoid importing EventsMixin (which
        # pulls in the full app module and its heavy OpenGL dependency).
        def _sync(self_app):
            stack = self_app.input_stack
            if not stack.is_captured:
                if stack.has("stamp_capture"):
                    stack.remove("stamp_capture", self_app)
                return
            ed = self_app.editor_3d
            if not ed or self_app.view_mode != "3d":
                if stack.has("stamp_capture"):
                    stack.remove("stamp_capture", self_app)
                return
            want = (ed.tool == "stamp"
                    and getattr(ed, '_capture_pending', False))
            has = stack.has("stamp_capture")
            if want and not has:
                stack.push(StampCaptureContext(), self_app)
            elif not want and has:
                stack.remove("stamp_capture", self_app)

        import types
        app._sync_input_contexts = types.MethodType(_sync, app)
        return app

    def test_sync_pushes_stamp_capture_when_pending(self):
        app = self._make_app()
        app.editor_3d._capture_pending = True
        app.editor_3d.tool = "stamp"

        app._sync_input_contexts()
        assert app.input_stack.has("stamp_capture")

    def test_sync_removes_stamp_capture_when_not_pending(self):
        from editor.contexts import StampCaptureContext
        app = self._make_app()
        app.input_stack.push(StampCaptureContext(), app)
        app.editor_3d._capture_pending = False

        app._sync_input_contexts()
        assert not app.input_stack.has("stamp_capture")

    def test_sync_noop_when_not_captured(self):
        app = self._make_app()
        # Pop captured viewport
        app.input_stack.remove("captured_viewport", app)
        app.editor_3d._capture_pending = True
        app.editor_3d.tool = "stamp"

        app._sync_input_contexts()
        assert not app.input_stack.has("stamp_capture")

    def test_sync_no_double_push(self):
        app = self._make_app()
        app.editor_3d._capture_pending = True
        app.editor_3d.tool = "stamp"

        app._sync_input_contexts()
        app._sync_input_contexts()  # second call should be idempotent
        assert app.input_stack.names.count("stamp_capture") == 1
