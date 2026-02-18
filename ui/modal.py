"""ui/modal.py — Abstract modal base and modal stack manager.

A *modal* is a self-contained overlay (inventory screen, dialogue box,
transfer panel, etc.) that captures input while open.

``ModalStack`` manages a push/pop stack of modals with event routing
and layered drawing.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

import pygame

if TYPE_CHECKING:
    from core.app import App
    from ui.commands import UICommand


class Modal(ABC):
    """Abstract modal overlay."""

    @abstractmethod
    def update(self, dt: float) -> None:
        """Tick timers, animation, etc."""

    @abstractmethod
    def handle_event(self, event: pygame.event.Event) -> list["UICommand"]:
        """Process one pygame event.  Return a list of UI commands."""

    @abstractmethod
    def draw(self, surface: pygame.Surface, app: "App") -> None:
        """Draw this modal overlay onto *surface*."""


class ModalStack:
    """Push/pop stack of ``Modal`` instances.

    Behaviour:
    - Events go to the **topmost** modal only.
    - Draw iterates bottom → top so that earlier modals show behind later ones.
    - ``is_open`` indicates whether any modal is active.
    """

    def __init__(self) -> None:
        self._stack: list[Modal] = []

    @property
    def is_open(self) -> bool:
        return len(self._stack) > 0

    def push(self, modal: Modal) -> None:
        self._stack.append(modal)

    def pop(self) -> Modal | None:
        return self._stack.pop() if self._stack else None

    def clear(self) -> None:
        self._stack.clear()

    def top(self) -> Modal | None:
        return self._stack[-1] if self._stack else None

    # ── Delegation ─────────────────────────────────────────────────

    def update(self, dt: float) -> None:
        if self._stack:
            self._stack[-1].update(dt)

    def handle_event(self, event: pygame.event.Event) -> list["UICommand"]:
        if self._stack:
            return self._stack[-1].handle_event(event)
        return []

    def draw(self, surface: pygame.Surface, app: "App") -> None:
        for modal in self._stack:
            modal.draw(surface, app)
