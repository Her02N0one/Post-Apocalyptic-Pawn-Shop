"""scenes/debug_menu.py — Debug exhibits selection screen.

Accessible from the pause menu's "Debug" option.  Lists all
available debug/developer exhibits as a simple menu.

Current exhibits:
  - **LOD Exhibit** — standalone sandbox demonstrating dual-resolution
    simulation (spawns its own world, not tied to any save)
  - **Live LOD Viewer** — read-only visualiser showing the LOD state
    of the *currently loaded* game session
  - **Map Editor** — tile editor for the current zone
"""

from __future__ import annotations

import pygame

from core.scene import Scene

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.app import App
    from core.session import Session


_BG_ALPHA   = 180
_TITLE_COL  = (180, 220, 255)
_NORMAL_COL = (180, 180, 180)
_HOVER_COL  = (255, 240, 120)
_DIM_COL    = (90, 90, 90)
_DESC_COL   = (130, 130, 150)


class DebugMenu(Scene):
    """Select a debug exhibit to launch."""

    # (label, description, action_key)
    _ITEMS: list[tuple[str, str, str]] = [
        ("LOD Exhibit",     "Standalone LOD sandbox (own world)",  "exhibit_lod"),
        ("Live LOD Viewer", "View LOD state of current save",     "live_lod"),
        ("Map Editor",      "Edit tiles in the current zone",     "editor"),
        ("Back",            "",                                    "back"),
    ]

    def __init__(self, session: "Session") -> None:
        self.session = session
        self._cursor: int = 0
        self._item_rects: list[pygame.Rect] = []

    def handle_event(self, event: pygame.event.Event, app: "App") -> None:
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                app.pop_scene()
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
        pass

    def draw(self, surface: pygame.Surface, app: "App") -> None:
        sw, sh = surface.get_size()

        # Darken background
        overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, _BG_ALPHA))
        surface.blit(overlay, (0, 0))

        # Title
        title = app.font_lg.render("DEBUG EXHIBITS", True, _TITLE_COL)
        surface.blit(title, ((sw - title.get_width()) // 2, sh // 5))

        # Items
        menu_y = sh // 2 - (len(self._ITEMS) * 40) // 2
        self._item_rects = []
        for i, (label, desc, _action) in enumerate(self._ITEMS):
            is_sel = (i == self._cursor)
            col = _HOVER_COL if is_sel else _NORMAL_COL
            prefix = "> " if is_sel else "  "
            img = app.font_lg.render(f"{prefix}{label}", True, col)
            x = (sw - 300) // 2
            y = menu_y + i * 40
            rect = surface.blit(img, (x, y))
            self._item_rects.append(rect)

            # Description line
            if desc:
                desc_img = app.font_sm.render(f"    {desc}", True, _DESC_COL)
                surface.blit(desc_img, (x + 20, y + 20))

        # Hint
        hint = app.font_sm.render("[Enter] Launch   [Esc] Back", True, _DIM_COL)
        surface.blit(hint, ((sw - hint.get_width()) // 2, sh - 28))

    # ── Internal ──────────────────────────────────────────────────

    def _update_hover(self, app: "App") -> None:
        mx, my = app.mouse_pos()
        for i, rect in enumerate(self._item_rects):
            if rect.collidepoint(mx, my):
                self._cursor = i
                return

    def _select(self, app: "App") -> None:
        _, _, action = self._ITEMS[self._cursor]

        if action == "back":
            app.pop_scene()

        elif action == "exhibit_lod":
            from scenes.exhibit_lod import ExhibitLOD
            app.push_scene(ExhibitLOD())

        elif action == "live_lod":
            from scenes.live_lod import LiveLOD
            app.push_scene(LiveLOD(self.session))

        elif action == "editor":
            from scenes.editor import MapEditor
            app.push_scene(MapEditor(self.session.zone_name))
