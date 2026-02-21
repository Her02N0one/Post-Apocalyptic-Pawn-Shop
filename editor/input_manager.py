"""editor/input_manager.py — Composable input layer system.

Replaces the monolithic event waterfall in ``app.py`` with a
priority-ordered stack of input layers.  Each layer can *consume*
events, produce **action strings** for the app to dispatch, or
*pass through* to the next layer.

Global behaviours that the old waterfall lacked:

1. **Click-away unfocus** — on any left-click, if no widget re-takes
   focus during dispatch, the stale focus is released automatically.
2. **Action routing** — layers return action strings which are routed
   to ``EditorApp._dispatch_action`` via the *on_action* callback.

Usage::

    mgr = InputManager(ctx, on_action=app._dispatch_action)
    mgr.add("overlays",  100, is_overlay_active, handle_overlay)
    mgr.add("shortcuts",  90, lambda: True,      handle_shortcuts)
    ...
    # In the event loop:
    for event in pygame.event.get():
        mgr.dispatch(event)
"""

from __future__ import annotations

from typing import Callable

import pygame


# ── Layer ───────────────────────────────────────────────────────────

class InputLayer:
    """A named, prioritised event handler.

    Parameters
    ----------
    name : str
        Human-readable label (for debugging / logging).
    priority : int
        Higher values are dispatched first.
    active_fn : () -> bool
        Returns ``True`` when this layer should receive events.
    handler_fn : (event) -> str | bool | None
        Processes one ``pygame.event.Event``.  Return values:

        * ``str``  — an action string (consumed **and** dispatched)
        * ``True`` — consumed, no further action
        * ``None`` / ``False`` — not handled, pass to next layer
    """

    __slots__ = ("name", "priority", "_active_fn", "_handler_fn")

    def __init__(
        self,
        name: str,
        priority: int,
        active_fn: Callable[[], bool],
        handler_fn: Callable[[pygame.event.Event], str | bool | None],
    ):
        self.name = name
        self.priority = priority
        self._active_fn = active_fn
        self._handler_fn = handler_fn

    @property
    def active(self) -> bool:
        return self._active_fn()

    def handle_event(self, event: pygame.event.Event) -> str | bool | None:
        return self._handler_fn(event)


# ── Manager ─────────────────────────────────────────────────────────

class InputManager:
    """Priority-ordered event dispatch through input layers."""

    def __init__(self, ctx, on_action: Callable[[str], None] | None = None):
        self._ctx = ctx
        self._layers: list[InputLayer] = []
        self._on_action = on_action

    # ── Registration ────────────────────────────────────────────

    def add(
        self,
        name: str,
        priority: int,
        active_fn: Callable[[], bool],
        handler_fn: Callable[[pygame.event.Event], str | bool | None],
    ):
        """Register a new input layer (re-sorts by priority)."""
        layer = InputLayer(name, priority, active_fn, handler_fn)
        self._layers.append(layer)
        self._layers.sort(key=lambda ly: ly.priority, reverse=True)

    # ── Dispatch ────────────────────────────────────────────────

    def dispatch(self, event: pygame.event.Event) -> bool:
        """Push *event* through all active layers in priority order.

        Returns ``True`` if any layer consumed the event.
        """
        ctx = self._ctx

        # ── Click-away unfocus ──────────────────────────────────
        # Reset the "touched" flag before dispatch.  Any widget that
        # (re-)takes focus during dispatch sets it back to True.
        # After dispatch, if nobody touched focus and something was
        # focused, we release it — the user clicked elsewhere.
        is_lclick = (event.type == pygame.MOUSEBUTTONDOWN
                     and event.button == 1)
        if is_lclick:
            ctx._focus_touched = False

        # ── Layer cascade ───────────────────────────────────────
        consumed = False
        for layer in self._layers:
            if not layer.active:
                continue
            result = layer.handle_event(event)
            if result is None or result is False:
                continue
            # Action string → route to callback
            if isinstance(result, str):
                if self._on_action:
                    self._on_action(result)
            consumed = True
            break

        # ── Post-dispatch click-away ────────────────────────────
        if is_lclick and not ctx._focus_touched and ctx.any_focused():
            ctx.release_focus()

        return consumed
