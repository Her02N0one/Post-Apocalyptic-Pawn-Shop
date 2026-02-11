"""
core/scene.py — Scene interface

Every screen in the game is a Scene. The app holds a stack of them.
Only the top scene gets update/draw calls. Scenes below stay frozen.

To make a new scene:

    class MyScene(Scene):
        def on_enter(self, app):
            # setup, called when scene becomes active
            pass

        def handle_event(self, event, app):
            # pygame event
            pass

        def update(self, dt, app):
            # dt is seconds since last frame
            pass

        def draw(self, surface, app):
            # draw to the surface
            pass
"""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pygame
    from core.app import App


class Scene:
    def on_enter(self, app: App):
        """Called when this scene becomes active (pushed or revealed)."""
        pass

    def on_exit(self, app: App):
        """Called when this scene is removed or covered."""
        pass

    def handle_event(self, event: pygame.event.Event, app: App):
        """Process a single pygame event."""
        pass

    def update(self, dt: float, app: App):
        """Advance simulation. dt is seconds."""
        pass

    def draw(self, surface: pygame.Surface, app: App):
        """Draw to the screen surface."""
        pass
