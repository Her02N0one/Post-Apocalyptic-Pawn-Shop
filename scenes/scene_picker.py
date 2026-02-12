"""scenes/scene_picker.py — Scene selector overlay (F3).

A minimal full-screen menu that lets you jump into test scenes:
  - Gym (Movement & Pathfinding)
  - Zoo (Entity Bestiary)
  - Museum (Interactive Exhibits)
  - Back to Game

Press F3 from the world scene to open this. Press Escape or F3 to close.
"""

from __future__ import annotations
import pygame
from core.scene import Scene
from core.app import App


_ENTRIES = [
    ("Gym",    "Movement & Pathfinding test arena",  "scenes.gym_scene",    "GymScene"),
    ("Zoo",    "Auto-populated entity bestiary",      "scenes.zoo_scene",    "ZooScene"),
    ("Museum", "Interactive system exhibits",         "scenes.museum_scene", "MuseumScene"),
]


class ScenePickerScene(Scene):
    """Overlay menu for selecting test/debug scenes."""

    def __init__(self):
        self.selected = 0  # 0..len(_ENTRIES)  (last is "Back")
        self._total = len(_ENTRIES) + 1  # +1 for "Back to Game"

    def handle_event(self, event: pygame.event.Event, app: App):
        if event.type != pygame.KEYDOWN:
            return

        if event.key in (pygame.K_ESCAPE, pygame.K_F3):
            app.pop_scene()
            return

        if event.key in (pygame.K_UP, pygame.K_w):
            self.selected = (self.selected - 1) % self._total
        elif event.key in (pygame.K_DOWN, pygame.K_s):
            self.selected = (self.selected + 1) % self._total
        elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
            if self.selected < len(_ENTRIES):
                _, _, module_path, class_name = _ENTRIES[self.selected]
                self._launch(app, module_path, class_name)
            else:
                # "Back to Game"
                app.pop_scene()

        # Number keys 1-3 for quick launch
        if event.key in (pygame.K_1, pygame.K_2, pygame.K_3):
            idx = event.key - pygame.K_1
            if idx < len(_ENTRIES):
                _, _, module_path, class_name = _ENTRIES[idx]
                self._launch(app, module_path, class_name)

    def _launch(self, app: App, module_path: str, class_name: str):
        """Import and push the target scene."""
        import importlib
        try:
            mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name)
            scene = cls()
            # Replace this picker with the target scene
            app.pop_scene()
            app.push_scene(scene)
        except Exception as ex:
            print(f"[PICKER] Failed to launch {module_path}.{class_name}: {ex}")
            import traceback; traceback.print_exc()

    def draw(self, surface: pygame.Surface, app: App):
        surface.fill((16, 20, 24))
        sw, sh = surface.get_size()

        # Title
        title = "SCENE PICKER"
        app.draw_text(surface, title, sw // 2 - 60, 30, (0, 255, 200), app.font_lg)
        app.draw_text(surface, "Select a test scene or press Escape to return",
                      sw // 2 - 160, 55, (120, 140, 130), app.font_sm)

        # Menu entries
        y = 100
        for i, (name, desc, _, _) in enumerate(_ENTRIES):
            is_sel = (i == self.selected)
            # Background highlight
            if is_sel:
                bg = pygame.Surface((400, 44), pygame.SRCALPHA)
                bg.fill((0, 80, 60, 100))
                surface.blit(bg, (sw // 2 - 200, y - 4))

            num_color = (0, 255, 200) if is_sel else (80, 140, 120)
            name_color = (255, 255, 255) if is_sel else (180, 180, 180)
            desc_color = (140, 180, 160) if is_sel else (90, 110, 100)

            marker = ">" if is_sel else " "
            app.draw_text(surface, f"{marker} [{i+1}] {name}", sw // 2 - 190, y,
                          num_color, app.font_lg)
            app.draw_text(surface, desc, sw // 2 - 140, y + 22,
                          desc_color, app.font_sm)
            y += 52

        # "Back to Game" entry
        is_sel = (self.selected == len(_ENTRIES))
        if is_sel:
            bg = pygame.Surface((400, 34), pygame.SRCALPHA)
            bg.fill((0, 80, 60, 100))
            surface.blit(bg, (sw // 2 - 200, y - 4))
        marker = ">" if is_sel else " "
        color = (255, 255, 255) if is_sel else (120, 120, 120)
        app.draw_text(surface, f"{marker}     Back to Game", sw // 2 - 190, y,
                      color, app.font_lg)

        # Footer
        app.draw_text(surface, "Up/Down = navigate   Enter/Space = select   F3/Esc = close",
                      sw // 2 - 200, sh - 30, (80, 100, 90), app.font_sm)
