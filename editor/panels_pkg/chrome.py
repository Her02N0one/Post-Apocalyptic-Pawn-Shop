"""editor/panels_pkg/chrome.py — Editor-wide chrome (backgrounds + borders).

This is the **single owner** of every panel's non-content pixels:
menu bar bg, zone nav bg, toolbar bg, left panel bg + tabs,
right panel (inspector) bg, status bar bg, and all border lines.

Individual panels MUST NOT draw their own backgrounds or borders.
They receive pre-computed region rects from Layout and draw only
their content (text, buttons, scrollable items) inside those regions.

Usage (in EditorApp._draw)::

    chrome.draw_backgrounds(screen)     # all opaque fills + borders
    chrome.draw_left_tabs(screen, …)    # left panel tab buttons
    panel_widget.draw(screen, …)        # left panel content
    inspector.draw(screen, …)           # right panel content
    chrome.draw_overlays(screen)        # tooltips, deferred layers
"""

from __future__ import annotations

import pygame

from editor.ui import Theme
from editor.layout import Layout
from editor.panels_pkg.panel_tabs import PanelTabs


# ── Hardcoded chrome tints (formerly scattered across panels) ────────
# Slightly different shades distinguish the horizontal bars from each
# other while remaining consistent with the dark theme.
_NAV_BG = (36, 36, 42)
_TOOLBAR_BG = (42, 42, 48)


class EditorChrome:
    """Owns every background fill and border line in the editor.

    Call sequence each frame::

        chrome.draw_backgrounds(surface)     # step 1: all bg + borders
        chrome.draw_left_tabs(surface, …)    # step 2: left panel tabs
        # … draw panel content, canvas, inspector, etc. …
        chrome.draw_overlays(surface)        # final: deferred overlays
    """

    def __init__(self, panel_tabs: PanelTabs):
        self._tabs = panel_tabs
        self._overlays: list[tuple[pygame.Surface, tuple[int, int]]] = []

    # ── Step 1: All backgrounds + borders ────────────────────────

    def draw_backgrounds(self, surface: pygame.Surface):
        """Draw every panel's opaque background and border lines.

        After this call, the screen has all chrome painted.  Content
        drawing can proceed in any order without z-fighting.
        """
        L = Layout
        sw, sh = surface.get_size()
        self._overlays.clear()

        # ── Menu bar ────────────────────────────────────────────
        pygame.draw.rect(surface, Theme.PANEL,
                         (0, L.menu_y, sw, L.menu_h))
        pygame.draw.line(surface, Theme.BORDER,
                         (0, L.menu_h - 1), (sw, L.menu_h - 1))

        # ── Zone nav ────────────────────────────────────────────
        pygame.draw.rect(surface, _NAV_BG,
                         (0, L.nav_y, sw, L.nav_h))
        pygame.draw.line(surface, Theme.BORDER,
                         (0, L.nav_y + L.nav_h - 1),
                         (sw, L.nav_y + L.nav_h - 1))

        # ── Toolbar ─────────────────────────────────────────────
        pygame.draw.rect(surface, _TOOLBAR_BG,
                         (0, L.toolbar_y, sw, L.toolbar_h))
        pygame.draw.line(surface, Theme.BORDER,
                         (0, L.toolbar_y + L.toolbar_h - 1),
                         (sw, L.toolbar_y + L.toolbar_h - 1))

        # ── Left panel (palette area) ───────────────────────────
        lp_h = L.lp_bottom_y - L.canvas_y
        pygame.draw.rect(surface, Theme.PANEL,
                         (0, L.canvas_y, L.palette_w, lp_h))
        # Right border of left panel
        pygame.draw.line(surface, Theme.BORDER,
                         (L.palette_w - 1, L.canvas_y),
                         (L.palette_w - 1, L.lp_bottom_y))
        # Separator below tab strip
        sep_y = L.lp_content_y - 1
        pygame.draw.line(surface, Theme.BORDER,
                         (0, sep_y), (L.palette_w - 1, sep_y))

        # ── Right panel (inspector) ─────────────────────────────
        rp_h = L.rp_bottom_y - L.canvas_y
        pygame.draw.rect(surface, Theme.PANEL,
                         (L.rp_x, L.canvas_y, L.inspector_w, rp_h))
        # Left border of inspector
        pygame.draw.line(surface, Theme.BORDER,
                         (L.rp_x, L.canvas_y),
                         (L.rp_x, L.rp_bottom_y))

        # ── Status bar ──────────────────────────────────────────
        pygame.draw.rect(surface, Theme.PANEL,
                         (0, L.status_y, sw, L.status_h))
        # Top border of status bar
        pygame.draw.line(surface, Theme.BORDER,
                         (0, L.status_y), (sw, L.status_y))

    # ── Step 2: Left panel tab buttons ───────────────────────────

    def draw_left_tabs(self, surface: pygame.Surface,
                       font_sm: pygame.font.Font, panel_mode: str):
        """Draw the left panel's mode-switching tab buttons."""
        self._tabs.draw(surface, font_sm, Layout.lp_tabs_y, panel_mode)

    # ── Overlay API ──────────────────────────────────────────────

    def queue_overlay(self, surf: pygame.Surface, pos: tuple[int, int]):
        """Queue a surface to be drawn in the overlay pass."""
        self._overlays.append((surf, pos))

    def draw_overlays(self, surface: pygame.Surface):
        """Draw deferred overlays (tooltips, drag previews, etc.)."""
        for overlay_surf, pos in self._overlays:
            surface.blit(overlay_surf, pos)
        self._overlays.clear()
