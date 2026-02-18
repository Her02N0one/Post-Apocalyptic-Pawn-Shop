"""scenes/main_menu.py — Title screen and main menu.

The very first scene the player sees.  Offers:
  - New Game
  - Continue  (only if a save exists)
  - Settings
  - Quit

Navigation is keyboard-driven (Up/Down + Enter) or mouse click.
"""

from __future__ import annotations

import pygame

from core.scene import Scene
from core.save import has_save

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.app import App


# ── Visual tuning ────────────────────────────────────────────────────
_BG          = (18, 12, 20)
_TITLE_COL   = (220, 180, 80)
_NORMAL_COL  = (180, 180, 180)
_HOVER_COL   = (255, 240, 120)
_DIM_COL     = (80, 80, 80)
_VERSION_COL = (90, 90, 90)

VERSION_STR = "v0.1-alpha"
TITLE_STR   = "POST-APOCALYPTIC PAWN SHOP"


class MainMenu(Scene):
    """Title screen — entry point for the game."""

    def __init__(self) -> None:
        self._cursor: int = 0
        self._items: list[tuple[str, str]] = []   # (label, action)
        self._rebuild_items()

    # ── Helpers ───────────────────────────────────────────────────

    def _rebuild_items(self) -> None:
        """Refresh the menu list (continue may appear/disappear)."""
        self._items = []
        if has_save(0):
            self._items.append(("Continue", "continue"))
        self._items.append(("New Game", "new_game"))
        self._items.append(("Settings", "settings"))
        self._items.append(("Quit", "quit"))
        self._cursor = min(self._cursor, len(self._items) - 1)

    # ── Scene interface ──────────────────────────────────────────

    def on_enter(self, app: "App") -> None:
        self._rebuild_items()

    def handle_event(self, event: pygame.event.Event, app: "App") -> None:
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_UP, pygame.K_w):
                self._cursor = (self._cursor - 1) % len(self._items)
            elif event.key in (pygame.K_DOWN, pygame.K_s):
                self._cursor = (self._cursor + 1) % len(self._items)
            elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
                self._select(app)
            elif event.key == pygame.K_ESCAPE:
                app.running = False

        elif event.type == pygame.MOUSEMOTION:
            self._update_hover(app)

        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self._update_hover(app)
            self._select(app)

    def update(self, dt: float, app: "App") -> None:
        pass

    def draw(self, surface: pygame.Surface, app: "App") -> None:
        surface.fill(_BG)
        sw, sh = surface.get_size()

        # Title
        title_font = app.font_lg
        title_img = title_font.render(TITLE_STR, True, _TITLE_COL)
        tx = (sw - title_img.get_width()) // 2
        ty = sh // 4 - title_img.get_height() // 2
        surface.blit(title_img, (tx, ty))

        # Subtitle
        sub = app.font_sm.render("A Scavenging Survival RPG", True, _DIM_COL)
        surface.blit(sub, ((sw - sub.get_width()) // 2, ty + title_img.get_height() + 6))

        # Menu items
        menu_y = sh // 2 - (len(self._items) * 32) // 2
        self._item_rects: list[pygame.Rect] = []
        for i, (label, _action) in enumerate(self._items):
            col = _HOVER_COL if i == self._cursor else _NORMAL_COL
            prefix = "> " if i == self._cursor else "  "
            img = app.font_lg.render(f"{prefix}{label}", True, col)
            x = (sw - img.get_width()) // 2
            y = menu_y + i * 32
            rect = surface.blit(img, (x, y))
            self._item_rects.append(rect)

        # Version in bottom-right
        ver = app.font_sm.render(VERSION_STR, True, _VERSION_COL)
        surface.blit(ver, (sw - ver.get_width() - 8, sh - ver.get_height() - 6))

        # Controls hint
        hint = app.font_sm.render("[W/S or Arrows] Navigate   [Enter] Select", True, _DIM_COL)
        surface.blit(hint, ((sw - hint.get_width()) // 2, sh - 28))

    # ── Internal ──────────────────────────────────────────────────

    def _update_hover(self, app: "App") -> None:
        mx, my = app.mouse_pos()
        for i, rect in enumerate(getattr(self, "_item_rects", [])):
            if rect.collidepoint(mx, my):
                self._cursor = i
                return

    def _select(self, app: "App") -> None:
        _, action = self._items[self._cursor]

        if action == "quit":
            app.running = False

        elif action == "new_game":
            from scenes.save_slots import SaveSlotMenu
            app.push_scene(SaveSlotMenu(mode="new"))

        elif action == "continue":
            self._start_game(app, slot=0)

        elif action == "settings":
            from scenes.settings_menu import SettingsMenu
            app.push_scene(SettingsMenu())

    def _start_game(self, app: "App", slot: int = 0) -> None:
        """Load a save and enter gameplay."""
        from core.session import Session
        from scenes.world import TopDown

        session = Session(app.world)
        if not session.load(slot):
            session.new_game("playground")

        app.push_scene(TopDown(session))
