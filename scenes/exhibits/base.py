"""scenes/exhibits/base.py — Exhibit protocol for museum tabs.

Every museum tab is an Exhibit subclass that owns its own:
    * entity spawning  (setup)
    * per-frame logic  (update)
    * debug drawing    (draw)
    * input handling   (handle_event / on_space)
    * status text      (info_text)
    * cleanup          (teardown)

MuseumScene manages the tab bar, arena tiles, and shared entity
chrome (sprites, names, health bars).  Exhibits draw on top of that.
"""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pygame
    from core.app import App


class Exhibit:
    """Base class for a single museum tab."""

    name: str = ""

    # ── Lifecycle ────────────────────────────────────────────────────

    def setup(self, app: App, zone: str, tiles: list[list[int]]) -> list[int]:
        """Spawn entities for this exhibit.  Return list of entity IDs."""
        return []

    def teardown(self, app: App, eids: list[int]):
        """Kill owned entities (default: kill all eids)."""
        for eid in eids:
            if app.world.alive(eid):
                app.world.kill(eid)

    # ── Per-frame ────────────────────────────────────────────────────

    def update(self, app: App, dt: float, tiles: list[list[int]],
               eids: list[int]):
        """Per-frame simulation logic."""
        pass

    def handle_event(self, event: "pygame.event.Event", app: App,
                     mouse_to_tile) -> bool:
        """Handle tab-specific input.

        ``mouse_to_tile`` is a callable ``() -> (row, col) | None``.
        Return True if the event was consumed.
        """
        return False

    def on_space(self, app: App) -> str | None:
        """Handle Space key.  Return ``"reset"`` to re-setup the tab."""
        return "reset"

    # ── Drawing ──────────────────────────────────────────────────────

    def draw(self, surface: "pygame.Surface", ox: int, oy: int,
             app: App, eids: list[int]):
        """Draw tab-specific overlays (vision cones, rings, paths…)."""
        pass

    def draw_entity_overlay(self, surface: "pygame.Surface",
                            sx: int, sy: int, eid: int,
                            app: App) -> tuple[int, int, int] | None:
        """Optional per-entity overlay drawn on top of the sprite.

        Return an ``(r, g, b)`` tuple to override the sprite colour
        for this entity, or ``None`` to use the default.
        """
        return None

    def info_text(self, app: App, eids: list[int]) -> str:
        """Status-bar text for this exhibit."""
        return ""
