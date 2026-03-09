"""editor/input_context.py — Input context stack for the zone editor.

Replaces the ``mouse_captured`` boolean and Escape-chain with a
priority-ordered stack of :class:`InputContext` objects.  The top of
the stack gets first dibs on every event; if it consumes the event
propagation stops, otherwise the event falls through to the next
context below.

Typical stack (bottom → top):

* :class:`GlobalShortcutsContext` — always present; Ctrl+S, Ctrl+Z, TAB, …
* :class:`CapturedViewportContext` — pushed on mouse capture; Escape pops it
* (future) ModalDialogContext — pushed when a modal dialog is open
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

import pygame

if TYPE_CHECKING:
    from editor.app.app import ZoneEditorApp


# ── Base class ────────────────────────────────────────────────────

class InputContext(ABC):
    """A layer in the input dispatch stack.

    Subclass and override :meth:`handle_event`.  Return ``True`` from
    that method to consume an event and stop propagation.
    """

    name: str = ""

    # If True, events that are *not* consumed by this context still
    # do not propagate to contexts below.  Useful for modal overlays.
    blocks_below: bool = False

    def handle_event(self, event: pygame.event.Event,
                     app: ZoneEditorApp) -> bool:
        """Process *event*.  Return ``True`` to consume it."""
        return False

    def on_push(self, app: ZoneEditorApp) -> None:
        """Called immediately after this context is pushed onto the stack."""

    def on_pop(self, app: ZoneEditorApp) -> None:
        """Called immediately after this context is popped from the stack."""


# ── Stack ─────────────────────────────────────────────────────────

class InputStack:
    """Priority-ordered stack of :class:`InputContext` objects.

    * :meth:`push` / :meth:`pop` manage the stack.
    * :meth:`dispatch` walks **top → bottom**, giving each context a
      chance to consume the event.
    """

    def __init__(self) -> None:
        self._stack: list[InputContext] = []

    # ── Mutation ──────────────────────────────────────────────────

    def push(self, ctx: InputContext, app: ZoneEditorApp) -> None:
        """Push *ctx* onto the top of the stack."""
        self._stack.append(ctx)
        ctx.on_push(app)

    def pop(self, app: ZoneEditorApp) -> InputContext | None:
        """Pop and return the top context, or ``None`` if the stack is
        empty.  Calls :meth:`InputContext.on_pop` on the removed context."""
        if not self._stack:
            return None
        ctx = self._stack.pop()
        ctx.on_pop(app)
        return ctx

    def remove(self, name: str, app: ZoneEditorApp) -> InputContext | None:
        """Remove the first context with *name* (top-down) and call its
        ``on_pop``.  Returns the removed context or ``None``."""
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i].name == name:
                ctx = self._stack.pop(i)
                ctx.on_pop(app)
                return ctx
        return None

    # ── Query ─────────────────────────────────────────────────────

    def peek(self) -> InputContext | None:
        """Return the top context without removing it."""
        return self._stack[-1] if self._stack else None

    def has(self, name: str) -> bool:
        """Return ``True`` if a context with *name* is anywhere in the stack."""
        return any(c.name == name for c in self._stack)

    @property
    def is_captured(self) -> bool:
        """``True`` when the viewport owns all input (replaces
        ``mouse_captured``)."""
        return self.has("captured_viewport")

    @property
    def names(self) -> list[str]:
        """Return context names bottom → top (for debugging)."""
        return [c.name for c in self._stack]

    def __len__(self) -> int:
        return len(self._stack)

    # ── Dispatch ──────────────────────────────────────────────────

    def dispatch(self, event: pygame.event.Event,
                 app: ZoneEditorApp) -> bool:
        """Walk the stack **top → bottom**.

        * If a context's :meth:`~InputContext.handle_event` returns
          ``True`` the event is consumed and dispatch stops.
        * If a context has ``blocks_below == True`` dispatch stops even
          when the event was not consumed (modal barrier).

        Returns ``True`` if the event was consumed by any context.
        """
        for ctx in reversed(self._stack):
            if ctx.handle_event(event, app):
                return True
            if ctx.blocks_below:
                return False
        return False
