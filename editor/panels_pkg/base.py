"""editor/panels_pkg/base.py — Base class for left-side editor panels.

Provides the common lifecycle shared by every left panel:

1. Background / chrome drawing
2. Scroll-region clip setup / teardown
3. Scroll-wheel handling with clamping
4. Content-region geometry helpers

Subclasses override two methods:

    draw_content(surface, font, font_sm, region)
        Draw your scrollable items into *region*.

    on_item_click(mx, my, region) -> str | None
        Return an action string when a list item is clicked,
        or *None* to let the event fall through.

The ``PanelRegion`` dataclass bundles all the layout values a
subclass needs so panels never have to compute clip rects themselves.
"""

from __future__ import annotations

from dataclasses import dataclass

import pygame

from editor.ui import Theme, draw_text, draw_panel_bg, clamp_scroll
from editor.layout import Layout


# ── Region info passed to subclass draw_content / on_item_click ──

@dataclass(slots=True)
class PanelRegion:
    """Pre-computed geometry for the scrollable content area."""

    left: int           # panel left edge x
    top: int            # panel top edge y (canvas_y)
    pw: int             # panel width
    panel_h: int        # total panel height (top → status bar)
    content_top: int    # first y pixel for scrollable content
    content_bot: int    # last y pixel (just above status bar)
    clip: pygame.Rect   # clip rect to apply before drawing items
    scroll_y: float     # current scroll offset
    mx: int             # current mouse x
    my: int             # current mouse y

    @property
    def visible_h(self) -> int:
        """Pixel height of the visible content window."""
        return self.content_bot - self.content_top

    def item_y(self, index: int, item_h: int) -> int:
        """Top-y for item *index*, adjusted for scroll."""
        return int(self.content_top - self.scroll_y) + index * item_h


# ── PanelBase ────────────────────────────────────────────────────

class PanelBase:
    """Abstract base for scrollable left-side panels.

    Handles background, clip, scroll-wheel, and scroll clamping so
    every subclass is free to focus on content drawing and hit-testing.

    Subclass API
    -------------
    ``title``       — panel header string (e.g. ``"ZONES"``)
    ``draw_content(surface, font, font_sm, region)``
        Draw the scrollable list / grid.  Must set
        ``self._total_h`` to the total content height.
    ``on_item_click(event, region) -> str | None``
        Handle a left-click inside the content area.
    """

    title: str = ""

    def __init__(self):
        self.scroll_y: float = 0.0
        self._total_h: float = 0.0

    # ── Public API (called by EditorApp) ─────────────────────────

    def draw(self, surface: pygame.Surface, font: pygame.font.Font,
             font_sm: pygame.font.Font):
        region = self._begin_draw(surface, font_sm)

        surface.set_clip(region.clip)
        self.draw_content(surface, font, font_sm, region)
        self.scroll_y = clamp_scroll(self.scroll_y, self._total_h,
                                     region.visible_h)
        surface.set_clip(None)

    def handle_event(self, event: pygame.event.Event,
                     surface: pygame.Surface) -> str | None:
        L = Layout
        left = 0
        pw = L.palette_w
        top = L.canvas_y
        sh = surface.get_height()

        # Scroll wheel
        if event.type == pygame.MOUSEWHEEL:
            mx, my = pygame.mouse.get_pos()
            if left <= mx < left + pw and my > top:
                self.scroll_y = max(0,
                                    self.scroll_y - event.y * L.scroll_step)
                content_top = top + L.header_h
                content_bot = sh - L.status_h
                visible_h = content_bot - content_top
                self.scroll_y = clamp_scroll(self.scroll_y,
                                             self._total_h, visible_h)
                return "consumed"

        # Delegate to subclass for clicks
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = event.pos
            if left <= mx < left + pw and my > top + L.header_h:
                region = self._make_region(surface)
                return self.on_item_click(event, region)

        return None

    # ── Subclass hooks ───────────────────────────────────────────

    def draw_content(self, surface: pygame.Surface,
                     font: pygame.font.Font,
                     font_sm: pygame.font.Font,
                     region: PanelRegion):
        """Override: draw scrollable items into *region*."""

    def on_item_click(self, event: pygame.event.Event,
                      region: PanelRegion) -> str | None:
        """Override: return an action string when items are clicked."""
        return None

    # ── Internal helpers ─────────────────────────────────────────

    def _make_region(self, surface: pygame.Surface) -> PanelRegion:
        L = Layout
        sh = surface.get_height()
        top = L.canvas_y
        left = 0
        pw = L.palette_w
        panel_h = sh - top - L.status_h
        content_top = top + L.header_h
        content_bot = sh - L.status_h
        mx, my = pygame.mouse.get_pos()
        clip = pygame.Rect(left, content_top, pw, content_bot - content_top)
        return PanelRegion(
            left=left, top=top, pw=pw, panel_h=panel_h,
            content_top=content_top, content_bot=content_bot,
            clip=clip, scroll_y=self.scroll_y, mx=mx, my=my,
        )

    def _begin_draw(self, surface: pygame.Surface,
                    font_sm: pygame.font.Font) -> PanelRegion:
        """Draw shared chrome and return the content region."""
        region = self._make_region(surface)
        draw_panel_bg(surface, region.left, region.top,
                      region.pw, region.panel_h)
        if self.title:
            L = Layout
            draw_text(surface, self.title,
                      region.left + L.pad_md,
                      region.top + L.pad_sm,
                      Theme.ACCENT, font_sm)
        return region
