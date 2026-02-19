"""scenes/settings_menu.py — Settings overlay.

Pushable from both the main menu and the pause menu.
Currently exposes:
  - FPS cap  (30 / 60 / uncapped)
  - Fullscreen toggle
  - Debug HUD default (on / off)
  - Back

All changes take effect immediately.  Settings are stored on the
``App`` instance and persist for the session.  Disk persistence can
be added later via a ``settings.json`` file.
"""

from __future__ import annotations

import pygame

from core.scene import Scene

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.app import App


_BG_ALPHA    = 180
_TITLE_COL   = (200, 200, 220)
_NORMAL_COL  = (180, 180, 180)
_HOVER_COL   = (255, 240, 120)
_VALUE_COL   = (120, 220, 160)
_DIM_COL     = (90, 90, 90)

_FPS_OPTIONS = [30, 60, 100, 0]  # 0 = uncapped


class SettingsMenu(Scene):
    """Settings screen — pushed on top of whatever called it."""

    def __init__(self) -> None:
        self._cursor: int = 0
        self._item_rects: list[pygame.Rect] = []

    # We build lines dynamically so values stay current.

    def _items(self, app: "App") -> list[tuple[str, str, str]]:
        """Return (label, value_display, action) for each setting row."""
        fps_label = "Uncapped" if app.fps == 0 else str(app.fps)
        fs_label = "On" if app.fullscreen else "Off"
        return [
            ("FPS Cap",       fps_label, "fps"),
            ("Fullscreen",    fs_label,  "fullscreen"),
            ("Back",          "",        "back"),
        ]

    def handle_event(self, event: pygame.event.Event, app: "App") -> None:
        items = self._items(app)
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                app.pop_scene()
            elif event.key in (pygame.K_UP, pygame.K_w):
                self._cursor = (self._cursor - 1) % len(items)
            elif event.key in (pygame.K_DOWN, pygame.K_s):
                self._cursor = (self._cursor + 1) % len(items)
            elif event.key in (pygame.K_RETURN, pygame.K_SPACE,
                               pygame.K_LEFT, pygame.K_RIGHT,
                               pygame.K_a, pygame.K_d):
                self._toggle(app, items)

        elif event.type == pygame.MOUSEMOTION:
            self._update_hover(app)

        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self._update_hover(app)
            self._toggle(app, items)

    def update(self, dt: float, app: "App") -> None:
        pass

    def draw(self, surface: pygame.Surface, app: "App") -> None:
        sw, sh = surface.get_size()

        # Darken whatever is behind
        overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, _BG_ALPHA))
        surface.blit(overlay, (0, 0))

        # Title
        title = app.font_lg.render("SETTINGS", True, _TITLE_COL)
        surface.blit(title, ((sw - title.get_width()) // 2, sh // 4))

        # Items
        items = self._items(app)
        menu_y = sh // 2 - (len(items) * 30) // 2
        self._item_rects = []
        for i, (label, value, _action) in enumerate(items):
            col = _HOVER_COL if i == self._cursor else _NORMAL_COL
            prefix = "> " if i == self._cursor else "  "
            text = f"{prefix}{label}"
            if value:
                text += f":  < {value} >"
            img = app.font_lg.render(text, True, col)
            x = (sw - img.get_width()) // 2
            y = menu_y + i * 30
            rect = surface.blit(img, (x, y))
            self._item_rects.append(rect)

        # Hint
        hint = app.font_sm.render("[Enter/Arrows] Change   [Esc] Back", True, _DIM_COL)
        surface.blit(hint, ((sw - hint.get_width()) // 2, sh - 28))

    # ── Internal ──────────────────────────────────────────────────

    def _update_hover(self, app: "App") -> None:
        mx, my = app.mouse_pos()
        for i, rect in enumerate(self._item_rects):
            if rect.collidepoint(mx, my):
                self._cursor = i
                return

    def _toggle(self, app: "App", items: list[tuple[str, str, str]]) -> None:
        _, _, action = items[self._cursor]

        if action == "back":
            app.pop_scene()

        elif action == "fps":
            # Cycle through FPS options
            try:
                idx = _FPS_OPTIONS.index(app.fps)
            except ValueError:
                idx = -1
            app.fps = _FPS_OPTIONS[(idx + 1) % len(_FPS_OPTIONS)]

        elif action == "fullscreen":
            app.toggle_fullscreen()
