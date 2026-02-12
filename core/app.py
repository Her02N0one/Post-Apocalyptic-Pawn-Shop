"""
core/app.py — Pygame application shell

Handles the window, main loop, and scene stack.
You don't edit this file to build your game.
You write Scenes and push/pop them.

    app = App(title="Shopkeeper", width=960, height=640)
    app.push_scene(MyScene())
    app.run()
"""

from __future__ import annotations
import pygame
from core.scene import Scene
from core.ecs import World


class App:
    def __init__(self, title: str = "Shopkeeper", width: int = 960, height: int = 640):
        pygame.init()
        self._windowed_size = (width, height)
        self.screen = pygame.display.set_mode((width, height), pygame.RESIZABLE)
        pygame.display.set_caption(title)
        self.clock = pygame.time.Clock()
        self.running = True
        self.fullscreen = False
        self.fps = 60
        self.dt = 0.0

        # Scene stack — only the top scene is active
        self._scenes: list[Scene] = []

        # The ECS world — shared across all scenes
        self.world = World()

        # Debug font (available to any scene)
        self.font = pygame.font.SysFont("monospace", 14)
        self.font_sm = pygame.font.SysFont("monospace", 11)
        self.font_lg = pygame.font.SysFont("monospace", 18)

    # -- Scene management --

    @property
    def scene(self) -> Scene | None:
        return self._scenes[-1] if self._scenes else None

    def push_scene(self, scene: Scene):
        if self._scenes:
            self._scenes[-1].on_exit(self)
        self._scenes.append(scene)
        scene.on_enter(self)

    def pop_scene(self):
        if self._scenes:
            self._scenes[-1].on_exit(self)
            self._scenes.pop()
        if self._scenes:
            self._scenes[-1].on_enter(self)

    # -- Main loop --

    def run(self):
        while self.running:
            self.dt = self.clock.tick(self.fps) / 1000.0

            # Events
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_F11:
                    self.toggle_fullscreen()
                elif event.type == pygame.VIDEORESIZE and not self.fullscreen:
                    self._windowed_size = (event.w, event.h)
                    self.screen = pygame.display.set_mode(
                        (event.w, event.h), pygame.RESIZABLE)
                elif self.scene:
                    self.scene.handle_event(event, self)

            # Update
            if self.scene:
                self.scene.update(self.dt, self)

            # Draw
            if self.scene:
                self.scene.draw(self.screen, self)

            pygame.display.flip()

        pygame.quit()

    def toggle_fullscreen(self):
        """Switch between windowed and fullscreen (F11)."""
        self.fullscreen = not self.fullscreen
        if self.fullscreen:
            self.screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        else:
            self.screen = pygame.display.set_mode(
                self._windowed_size, pygame.RESIZABLE)

    # -- Convenience --

    def draw_text(self, surface: pygame.Surface, text: str, x: int, y: int,
                  color=(255, 255, 255), font=None):
        """Quick text draw. Returns the rect for layout chaining."""
        f = font or self.font
        img = f.render(text, True, color)
        rect = surface.blit(img, (x, y))
        return rect
