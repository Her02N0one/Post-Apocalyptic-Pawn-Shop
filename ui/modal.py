"""ui.modal — Abstract Modal base class and ModalStack manager.

Every UI overlay (inventory, transfer, shop, dialog, confirm prompt, …)
is a ``Modal`` subclass.  ``ModalStack`` keeps them layered and routes
events / updates / draws to the topmost one.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

import pygame

if TYPE_CHECKING:
    from ui.commands import UICommand


class Modal(ABC):
    """Base class for all UI modals."""

    # ── lifecycle ───────────────────────────────────────────────────

    def on_open(self) -> None:
        """Called when this modal is pushed onto the stack."""

    def on_close(self) -> None:
        """Called when this modal is popped from the stack."""

    # ── per-frame ───────────────────────────────────────────────────

    @abstractmethod
    def update(self, dt: float) -> None:
        """Tick timers, animations, etc.  Called once per frame."""

    @abstractmethod
    def handle_event(self, event: pygame.event.Event) -> list[UICommand]:
        """Process one pygame event.

        Returns a (possibly empty) list of commands for the scene to
        execute.  The modal should *not* mutate state that lives outside
        its own scope — use a command instead.
        """

    @abstractmethod
    def draw(self, surface: pygame.Surface, app) -> None:
        """Render the modal onto *surface*."""


# ────────────────────────────────────────────────────────────────────
# Modal stack
# ────────────────────────────────────────────────────────────────────

class ModalStack:
    """Manages an ordered stack of ``Modal`` overlays.

    Events, updates, and draws are routed to every modal in the stack
    (bottom → top for draw, top-only for events/update).
    """

    __slots__ = ("_stack",)

    def __init__(self) -> None:
        self._stack: list[Modal] = []

    # ── queries ─────────────────────────────────────────────────────

    @property
    def active(self) -> Modal | None:
        """The topmost modal, or *None* if the stack is empty."""
        return self._stack[-1] if self._stack else None

    @property
    def is_open(self) -> bool:
        return bool(self._stack)

    def __len__(self) -> int:
        return len(self._stack)

    # ── mutation ────────────────────────────────────────────────────

    def push(self, modal: Modal) -> None:
        self._stack.append(modal)
        modal.on_open()

    def pop(self) -> Modal | None:
        if not self._stack:
            return None
        modal = self._stack.pop()
        modal.on_close()
        return modal

    def clear(self) -> None:
        while self._stack:
            self.pop()

    # ── per-frame dispatch ──────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event) -> list:
        """Route *event* to the topmost modal."""
        if self._stack:
            return self._stack[-1].handle_event(event)
        return []

    def update(self, dt: float) -> None:
        """Tick the topmost modal."""
        if self._stack:
            self._stack[-1].update(dt)

    def draw(self, surface: pygame.Surface, app) -> None:
        """Draw all modals bottom-to-top (for layered overlays)."""
        for modal in self._stack:
            modal.draw(surface, app)
