"""scenes/exhibits/base.py — Exhibit protocol for museum tabs.

Every museum tab is an Exhibit subclass that owns its own:
    * entity spawning  (setup)
    * per-frame logic  (update)
    * debug drawing    (draw)
    * input handling   (handle_event / on_space)
    * status text      (info_text)
    * cleanup          (teardown)

MuseumScene manages the tab bar, arena tiles, camera, and shared
entity chrome (sprites, names, health bars).  Exhibits draw on top.

Debug Flags
-----------
``DebugFlags`` is a toggleable overlay control.  Each exhibit declares
*default_debug* — a dict of overrides applied when the tab activates.
Users toggle flags at runtime with F1–F8.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import TYPE_CHECKING

from core.constants import TILE_SIZE

if TYPE_CHECKING:
    import pygame
    from core.app import App


# ── Debug overlay flags ──────────────────────────────────────────────

# (attribute_name, short_label, key_label)  — order matches F-keys
FLAG_META: list[tuple[str, str, str]] = [
    ("names",     "Names",  "F1"),
    ("health",    "HP",     "F2"),
    ("brain",     "Brain",  "F3"),
    ("ranges",    "Range",  "F4"),
    ("vision",    "Vision", "F5"),
    ("grid",      "Grid",   "F6"),
    ("positions", "Pos",    "F7"),
    ("faction",   "Fac",    "F8"),
]


@dataclass
class DebugFlags:
    """Toggleable debug overlay flags for museum exhibits."""

    names: bool = True
    health: bool = True
    brain: bool = False
    ranges: bool = True
    vision: bool = True
    grid: bool = False
    positions: bool = False
    faction: bool = False

    def toggle(self, name: str):
        """Flip a flag by attribute name."""
        if hasattr(self, name):
            setattr(self, name, not getattr(self, name))

    @classmethod
    def from_defaults(cls, overrides: dict[str, bool]) -> "DebugFlags":
        """Create flags with per-exhibit default overrides applied."""
        flags = cls()
        for k, v in overrides.items():
            if hasattr(flags, k):
                setattr(flags, k, v)
        return flags


# ── Exhibit base class ───────────────────────────────────────────────

class Exhibit:
    """Base class for a single museum tab."""

    name: str = ""
    category: str = "General"          # group for picker grid
    description: str = ""              # multi-line explanatory text
    arena_w: int = 30    # tiles — overridable per exhibit
    arena_h: int = 20    # tiles

    # Override in subclasses to change which flags start ON/OFF.
    # Only flags listed here differ from DebugFlags() defaults.
    default_debug: dict[str, bool] = {}

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
             app: App, eids: list[int],
             tile_px: int = TILE_SIZE,
             flags: "DebugFlags | None" = None):
        """Draw tab-specific overlays (vision cones, rings, paths…).

        ``tile_px`` is the current pixel-size per tile (TILE_SIZE × zoom).
        ``flags`` carries the active debug-overlay toggles.
        """
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
