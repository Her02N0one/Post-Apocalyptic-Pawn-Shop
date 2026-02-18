"""scenes/pause_menu.py — In-game pause overlay.

Pushed on top of the gameplay scene when Escape is pressed.
The gameplay scene stays frozen underneath.

Options:
  - Resume
  - Save Game
  - Settings
  - Main Menu (returns to title screen, discards unsaved state)
  - Quit to Desktop
"""

from __future__ import annotations

import pygame

from core.scene import Scene

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.app import App
    from core.session import Session


# ── Visual tuning ────────────────────────────────────────────────────
_OVERLAY_ALPHA = 160
_TITLE_COL     = (220, 200, 140)
_NORMAL_COL    = (180, 180, 180)
_HOVER_COL     = (255, 240, 120)
_DIM_COL       = (90, 90, 90)


class PauseMenu(Scene):
    """In-game pause screen — drawn over the frozen gameplay scene."""

    _ITEMS: list[tuple[str, str]] = [
        ("Resume",          "resume"),
        ("Save Game",       "save"),
        ("Settings",        "settings"),
        ("Debug",           "debug"),
        ("Main Menu",       "main_menu"),
        ("Quit to Desktop", "quit"),
    ]

    def __init__(self, session: "Session") -> None:
        self.session = session
        self._cursor: int = 0
        self._item_rects: list[pygame.Rect] = []
        self._status: str = ""
        self._status_timer: float = 0.0

    def handle_event(self, event: pygame.event.Event, app: "App") -> None:
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                app.pop_scene()  # resume
            elif event.key in (pygame.K_UP, pygame.K_w):
                self._cursor = (self._cursor - 1) % len(self._ITEMS)
            elif event.key in (pygame.K_DOWN, pygame.K_s):
                self._cursor = (self._cursor + 1) % len(self._ITEMS)
            elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
                self._select(app)

        elif event.type == pygame.MOUSEMOTION:
            self._update_hover(app)

        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self._update_hover(app)
            self._select(app)

    def update(self, dt: float, app: "App") -> None:
        if self._status_timer > 0:
            self._status_timer -= dt
            if self._status_timer <= 0:
                self._status = ""

    def draw(self, surface: pygame.Surface, app: "App") -> None:
        sw, sh = surface.get_size()

        # Semi-transparent overlay (the game scene is still beneath us)
        overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, _OVERLAY_ALPHA))
        surface.blit(overlay, (0, 0))

        # Title
        title = app.font_lg.render("PAUSED", True, _TITLE_COL)
        surface.blit(title, ((sw - title.get_width()) // 2, sh // 4))

        # Menu items
        menu_y = sh // 2 - (len(self._ITEMS) * 30) // 2
        self._item_rects = []
        for i, (label, _) in enumerate(self._ITEMS):
            col = _HOVER_COL if i == self._cursor else _NORMAL_COL
            prefix = "> " if i == self._cursor else "  "
            img = app.font_lg.render(f"{prefix}{label}", True, col)
            x = (sw - img.get_width()) // 2
            y = menu_y + i * 30
            rect = surface.blit(img, (x, y))
            self._item_rects.append(rect)

        # Status flash (e.g. "Game saved")
        if self._status:
            msg = app.font.render(self._status, True, (120, 255, 120))
            surface.blit(msg, ((sw - msg.get_width()) // 2, menu_y + len(self._ITEMS) * 30 + 16))

        # Hint
        hint = app.font_sm.render("[Esc] Resume", True, _DIM_COL)
        surface.blit(hint, ((sw - hint.get_width()) // 2, sh - 28))

    # ── Internal ──────────────────────────────────────────────────

    def _update_hover(self, app: "App") -> None:
        mx, my = app.mouse_pos()
        for i, rect in enumerate(self._item_rects):
            if rect.collidepoint(mx, my):
                self._cursor = i
                return

    def _select(self, app: "App") -> None:
        _, action = self._ITEMS[self._cursor]

        if action == "resume":
            app.pop_scene()

        elif action == "save":
            self.session.save()
            self._status = "Game saved!"
            self._status_timer = 1.5

        elif action == "settings":
            from scenes.settings_menu import SettingsMenu
            app.push_scene(SettingsMenu())

        elif action == "debug":
            from scenes.debug_menu import DebugMenu
            app.push_scene(DebugMenu(self.session))

        elif action == "main_menu":
            self._return_to_main(app)

        elif action == "quit":
            app.running = False

    def _return_to_main(self, app: "App") -> None:
        """Pop all scenes back to (and including) this one, then push MainMenu."""
        app.clear_scenes()
        from scenes.main_menu import MainMenu
        app.push_scene(MainMenu())
