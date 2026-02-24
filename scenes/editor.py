"""scenes/editor.py — Stub that redirects to the standalone zone editor.

Launch the 3D zone editor with::

    python zone_editor.py [zone_name]
"""

from __future__ import annotations

import pygame

from core.scene import Scene
from core.app import App


class MapEditor(Scene):
    """Placeholder — redirects user to the standalone editor."""

    def __init__(self, zone_name: str = "playground") -> None:
        self.zone_name = zone_name
        self._font: pygame.font.Font | None = None

    def handle_event(self, app: App, event: pygame.event.Event) -> None:
        if event.type == pygame.KEYDOWN:
            app.pop_scene()

    def update(self, app: App, dt: float) -> None:
        pass

    def draw(self, app: App, surface: pygame.Surface) -> None:
        if self._font is None:
            self._font = pygame.font.SysFont("monospace", 18)

        surface.fill((30, 30, 34))
        sw, sh = surface.get_size()
        cx, cy = sw // 2, sh // 2

        lines = [
            "The in-game editor has moved.",
            "",
            "Launch the standalone 3D zone editor:",
            "    python zone_editor.py " + self.zone_name,
            "",
            "Press any key to go back.",
        ]
        for i, line in enumerate(lines):
            col = (255, 200, 80) if i == 0 else (200, 200, 200)
            surf = self._font.render(line, True, col)
            surface.blit(surf, (cx - surf.get_width() // 2,
                                cy - 60 + i * 28))
