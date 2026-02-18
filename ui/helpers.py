"""ui/helpers.py — Shared UI drawing helpers."""

from __future__ import annotations

import pygame
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.app import App

ROW_H = 24


def sorted_items(inv: dict[str, int]) -> list[tuple[str, int]]:
    """Return inventory items sorted by name, filtering out zero-count."""
    return sorted(
        ((k, v) for k, v in inv.items() if v > 0),
        key=lambda x: x[0],
    )


def draw_overlay(surface: pygame.Surface, alpha: int = 120) -> None:
    """Draw a semi-transparent dark overlay covering the whole screen."""
    overlay = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, alpha))
    surface.blit(overlay, (0, 0))


def draw_title_bar(
    surface: pygame.Surface,
    app: "App",
    x: int, y: int, w: int,
    title: str,
) -> None:
    """Draw a panel title bar."""
    pygame.draw.rect(surface, (50, 50, 75), (x, y, w, 28))
    app.draw_text(surface, title, x + 10, y + 6, (200, 200, 255), app.font)


def draw_item_row(
    surface: pygame.Surface,
    app: "App",
    x: int, y: int, w: int,
    *,
    char: str,
    color: tuple,
    name: str,
    qty: int,
    equipped: bool = False,
    selected: bool = False,
    hovered: bool = False,
) -> pygame.Rect:
    """Draw a single item row.  Returns the row ``Rect`` for hit-testing."""
    row_rect = pygame.Rect(x, y - 1, w, ROW_H - 2)

    if selected:
        pygame.draw.rect(surface, (60, 60, 90), row_rect)
    elif hovered:
        pygame.draw.rect(surface, (50, 50, 75), row_rect)

    prefix = "> " if selected else "  "
    app.draw_text(surface, prefix, x + 4, y, (255, 255, 100), font=app.font_sm)
    app.draw_text(surface, char, x + 24, y, color, font=app.font)

    qty_str = f" x{qty}" if qty > 1 else ""
    eq_tag = "  [E]" if equipped else ""
    app.draw_text(surface, f"{name}{qty_str}{eq_tag}", x + 46, y + 2,
                  (220, 220, 220), font=app.font_sm)

    return row_rect
