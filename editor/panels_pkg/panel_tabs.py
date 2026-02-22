"""editor/panels_pkg/panel_tabs.py — Horizontal mode-switching tab strip.

Drawn at the top of the left panel so users can switch between
Tiles / Entities / Textures / Portals / Templates / Zones without
going through the View menu.

Returns ``"panel:<mode>"`` action strings when a tab is clicked.
The EditorApp's ``_dispatch_action`` already handles those.
"""

from __future__ import annotations

import pygame

from editor.ui import draw_tab_button
from editor.layout import Layout

# Tab definitions  (label, panel-mode)
# Two rows of 3 so labels can be readable at any panel width.
_TABS_ROW1: list[tuple[str, str]] = [
    ("Tiles",    "tiles"),
    ("Entities", "entities"),
    ("Surfaces", "surfaces"),
]
_TABS_ROW2: list[tuple[str, str]] = [
    ("Textures", "textures"),
    ("Portals",   "portals"),
    ("Templates", "templates"),
    ("Zones",     "zones"),
]


class PanelTabs:
    """Compact tab strip drawn inside the left panel chrome.

    Caller must hold a reference and call:
      * ``draw(surface, font_sm, top_y, panel_mode)``
      * ``handle_event(event) -> str | None``

    Returns ``"panel:<mode>"`` when a tab is clicked.
    """

    def __init__(self):
        self._rects: list[tuple[str, pygame.Rect]] = []

    # ── Height helper ────────────────────────────────────────────

    @staticmethod
    def height() -> int:
        """Total pixel height of the tab strip (both rows + padding)."""
        row_h = Layout.s(26)
        return row_h * 2 + Layout.pad_sm * 2

    # ── Drawing ──────────────────────────────────────────────────

    def _draw_row(self, surface: pygame.Surface, font_sm: pygame.font.Font,
                  tabs: list[tuple[str, str]], row_y: int,
                  panel_mode: str):
        """Draw one row of equal-width tab buttons."""
        L = Layout
        pw = L.palette_w
        mx, my = pygame.mouse.get_pos()
        n = len(tabs)
        if n == 0:
            return

        tab_h = L.s(26)
        gap = L.pad_sm
        total_gap = gap * (n - 1) + L.pad_sm * 2  # edge padding
        tab_w = max(L.s(30), (pw - total_gap) // n)
        x = L.pad_sm

        for label, mode in tabs:
            tr = pygame.Rect(x, row_y, tab_w, tab_h)
            draw_tab_button(
                surface, tr, label, font_sm,
                selected=(mode == panel_mode),
                hovered=tr.collidepoint(mx, my),
                border_r=L.border_r,
            )
            self._rects.append((mode, tr))
            x += tab_w + gap

    def draw(self, surface: pygame.Surface, font_sm: pygame.font.Font,
             top_y: int, panel_mode: str):
        """Draw the two-row tab strip starting at *top_y*.

        NOTE: The background behind these buttons is drawn by
        ``EditorChrome.draw_left_tabs()`` — this method only draws the buttons.
        """
        L = Layout
        self._rects.clear()
        row_h = L.s(26)

        self._draw_row(surface, font_sm, _TABS_ROW1, top_y, panel_mode)
        self._draw_row(surface, font_sm, _TABS_ROW2,
                       top_y + row_h + L.pad_sm, panel_mode)

    # ── Events ───────────────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event) -> str | None:
        """Return ``"panel:<mode>"`` if a tab was clicked, else None."""
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for mode, tr in self._rects:
                if tr.collidepoint(event.pos):
                    return f"panel:{mode}"
        return None
