"""editor/panels_pkg/toolbar.py — Horizontal tool-selection strip.

Drawn between the zone-nav bar and the canvas so the user can switch
between editing modes (Select, Brush, Eraser, Fill, Picker) with a
single click.

Returns ``"tool:<name>"`` action strings that the existing
``_pfx_tool`` handler in EditorApp already understands.
"""

from __future__ import annotations

import pygame

from editor.ui import draw_tab_button
from editor.state import Tool
from editor.layout import Layout


# (label, Tool constant)
_TOOL_DEFS: list[tuple[str, str]] = [
    ("Select",  Tool.SELECT),
    ("Brush",   Tool.BRUSH),
    ("Eraser",  Tool.ERASER),
    ("Fill",    Tool.FILL),
    ("Picker",  Tool.PICKER),
]


class Toolbar:
    """Clickable horizontal tool strip rendered below the zone nav bar.

    The caller should:
      * ``draw(surface, font_sm, current_tool)``  each frame
      * ``handle_event(event) -> str | None``     in the event loop
    """

    def __init__(self):
        self._rects: list[tuple[str, pygame.Rect]] = []

    # ── Height helper ────────────────────────────────────────────

    @staticmethod
    def height() -> int:
        """Pixel height of the toolbar strip."""
        return Layout.s(24)

    # ── Drawing ──────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, font_sm: pygame.font.Font,
             current_tool: str):
        L = Layout
        sw = surface.get_width()
        bar_y = L.toolbar_y
        h = L.toolbar_h

        # Background + border drawn by EditorChrome

        self._rects.clear()
        mx, my = pygame.mouse.get_pos()

        pad = L.pad_sm
        btn_h = h - pad * 2
        n = len(_TOOL_DEFS)
        # Equal-width buttons that fill the toolbar
        total_gap = pad * (n - 1) + L.pad_md * 2  # edge padding
        btn_w = max(L.s(40), (sw - total_gap) // n)
        x = L.pad_md

        for label, tool_val in _TOOL_DEFS:
            tr = pygame.Rect(x, bar_y + pad, btn_w, btn_h)
            draw_tab_button(
                surface, tr, label, font_sm,
                selected=(tool_val == current_tool),
                hovered=tr.collidepoint(mx, my),
                border_r=L.border_r,
            )
            self._rects.append((tool_val, tr))
            x += btn_w + pad

    # ── Events ───────────────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event) -> str | None:
        """Return ``"tool:<name>"`` if a button was clicked, else None."""
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for tool_val, tr in self._rects:
                if tr.collidepoint(event.pos):
                    return f"tool:{tool_val}"
        return None
