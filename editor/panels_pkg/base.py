"""editor/panels_pkg/base.py — Base class for left-side editor panels.

Provides the common lifecycle shared by every left panel:

1. Clip-region setup / teardown using Layout's authoritative regions
2. Scroll-wheel handling with clamping
3. Content-region geometry helpers

**Background and tab-strip rendering is handled by EditorChrome** —
individual panels must NOT draw their own background.

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

from editor.ui import Theme, draw_text, clamp_scroll
from editor.layout import Layout


# ── Region info passed to subclass draw_content / on_item_click ──

@dataclass()
class PanelRegion:
    """Pre-computed geometry for the scrollable content area.

    All values come from ``Layout.lp_*`` fields — the single source
    of truth for left-panel geometry.
    """

    left: int           # panel left edge x (always 0)
    top: int            # panel top edge y (canvas_y)
    pw: int             # panel width (palette_w)
    panel_h: int        # total panel height (canvas_y → status bar)
    content_top: int    # first y pixel for scrollable content (lp_content_y)
    content_bot: int    # last y pixel (lp_bottom_y)
    clip: pygame.Rect   # clip rect for scrollable content
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

    Handles clip, scroll-wheel, and scroll clamping so every subclass
    is free to focus on content drawing and hit-testing.

    **Background rendering is handled by EditorChrome** — panels
    must NOT call ``draw_panel_bg`` or fill the panel area.

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
        region = self._make_region(surface)

        # Title drawn above content clip
        if self.title:
            L = Layout
            draw_text(surface, self.title,
                      region.left + L.pad_md,
                      region.content_top + L.pad_sm,
                      Theme.ACCENT, font_sm)

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

        # Scroll wheel — only inside content region
        if event.type == pygame.MOUSEWHEEL:
            mx, my = pygame.mouse.get_pos()
            if left <= mx < left + pw and L.lp_content_y <= my < L.lp_bottom_y:
                self.scroll_y = max(0,
                                    self.scroll_y - event.y * L.scroll_step)
                self.scroll_y = clamp_scroll(self.scroll_y,
                                             self._total_h,
                                             L.lp_content_h)
                return "consumed"

        # Delegate to subclass for clicks — only inside content region
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = event.pos
            if left <= mx < left + pw and my >= L.lp_content_y:
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
        mx, my = pygame.mouse.get_pos()
        clip = pygame.Rect(0, L.lp_content_y, L.palette_w, L.lp_content_h)
        return PanelRegion(
            left=0, top=L.canvas_y, pw=L.palette_w,
            panel_h=L.lp_bottom_y - L.canvas_y,
            content_top=L.lp_content_y, content_bot=L.lp_bottom_y,
            clip=clip, scroll_y=self.scroll_y, mx=mx, my=my,
        )
