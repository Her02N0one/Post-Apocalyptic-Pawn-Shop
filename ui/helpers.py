"""ui.helpers — Shared drawing utilities for modal panels."""

from __future__ import annotations
import pygame


def sorted_items(inv: dict[str, int]) -> list[tuple[str, int]]:
    """Return [(item_id, qty), …] sorted alphabetically."""
    return sorted(inv.items(), key=lambda kv: kv[0])


def draw_overlay(surface: pygame.Surface, alpha: int = 200) -> None:
    """Full-screen semi-transparent dark overlay."""
    overlay = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, alpha))
    surface.blit(overlay, (0, 0))


def draw_title_bar(
    surface: pygame.Surface, app,
    x: int, y: int, w: int, text: str,
) -> None:
    """Draw a 30 px title bar at the top of a panel."""
    pygame.draw.rect(surface, (50, 50, 75), (x, y, w, 30))
    app.draw_text(surface, text, x + 12, y + 7,
                  (200, 200, 255), font=app.font_lg)


# ── item rows ──────────────────────────────────────────────────────

ROW_H = 24  # pixel height of one item row


def draw_item_row(
    surface: pygame.Surface,
    app,
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
    app.draw_text(surface, prefix, x + 4, y,
                  (255, 255, 100), font=app.font_sm)
    app.draw_text(surface, char, x + 24, y, color, font=app.font_lg)

    qty_str = f" x{qty}" if qty > 1 else ""
    eq_tag = "  [E]" if equipped else ""
    app.draw_text(surface, f"{name}{qty_str}{eq_tag}", x + 46, y + 2,
                  (220, 220, 220), font=app.font_sm)

    return row_rect
