"""editor/panels_pkg/splitter.py — Draggable panel resize handles."""

from __future__ import annotations

import pygame

from editor.ui import Theme
from editor.layout import Layout


class PanelSplitter:
    """Thin draggable dividers between the left panel / canvas and
    canvas / inspector.
    """

    HANDLE_W = 5  # overridden dynamically below

    @staticmethod
    def _handle_w() -> int:
        return max(4, Layout.s(5))

    def __init__(self):
        self._dragging: str | None = None   # "left" | "right" | None
        self._drag_start_x: int = 0
        self._drag_start_w: int = 0

    # ── drawing ─────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface):
        L = Layout
        top = L.canvas_y
        bot = surface.get_height() - L.status_h

        mx, my = pygame.mouse.get_pos()
        lx = L.palette_w
        rx = surface.get_width() - L.inspector_w

        for edge_x, side in ((lx, "left"), (rx, "right")):
            hw = self._handle_w()
            hit = pygame.Rect(edge_x - hw, top,
                              hw * 2, bot - top)
            hovering = hit.collidepoint(mx, my) or self._dragging == side
            color = Theme.ACCENT if hovering else Theme.BORDER
            pygame.draw.line(surface, color,
                             (edge_x, top), (edge_x, bot))
            if hovering:
                mid_y = (top + bot) // 2
                dot_gap = Layout.s(8)
                for i in range(-2, 3):
                    pygame.draw.circle(surface, Theme.TEXT_DIM,
                                       (edge_x, mid_y + i * dot_gap),
                                       max(1, Layout.s(2)))

    # ── events ──────────────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event) -> bool:
        L = Layout
        top = L.canvas_y
        bot = L.sh - L.status_h

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = event.pos
            if my < top or my > bot:
                return False

            lx = L.palette_w
            rx = L.sw - L.inspector_w
            hw = self._handle_w()

            if abs(mx - lx) <= hw:
                self._dragging = "left"
                self._drag_start_x = mx
                self._drag_start_w = L.palette_w
                return True
            if abs(mx - rx) <= hw:
                self._dragging = "right"
                self._drag_start_x = mx
                self._drag_start_w = L.inspector_w
                return True

        if event.type == pygame.MOUSEMOTION and self._dragging:
            mx, _my = event.pos
            dx = mx - self._drag_start_x
            if self._dragging == "left":
                Layout.set_palette_w(self._drag_start_w + dx)
            elif self._dragging == "right":
                Layout.set_inspector_w(self._drag_start_w - dx)
            return True

        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self._dragging:
                self._dragging = None
                return True

        return False

    @property
    def active(self) -> bool:
        return self._dragging is not None

    def cursor(self) -> int | None:
        if self._dragging:
            return pygame.SYSTEM_CURSOR_SIZEWE
        L = Layout
        mx, my = pygame.mouse.get_pos()
        top = L.canvas_y
        bot = L.sh - L.status_h
        if my < top or my > bot:
            return None
        lx = L.palette_w
        rx = L.sw - L.inspector_w
        hw = self._handle_w()
        if abs(mx - lx) <= hw or abs(mx - rx) <= hw:
            return pygame.SYSTEM_CURSOR_SIZEWE
        return None
