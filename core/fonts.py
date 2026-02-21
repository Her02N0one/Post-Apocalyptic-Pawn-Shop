"""core/fonts.py — Global monospace font cache.

Avoids re-creating ``pygame.font.SysFont`` objects every frame.
Import ``get_font`` anywhere you need a monospace font at a given size.

    from core.fonts import get_font
    font = get_font(14)
    img  = font.render("Hello", True, (255, 255, 255))
"""

from __future__ import annotations

import pygame

_cache: dict[int, pygame.font.Font] = {}


def get_font(size: int, *, family: str = "monospace") -> pygame.font.Font:
    """Return a cached ``SysFont`` at *size* px (clamped 8–72, even)."""
    size = max(8, min(72, size))
    size = (size // 2) * 2          # snap to even for sharper rendering
    key = (family, size) if family != "monospace" else size  # type: ignore[assignment]
    if key not in _cache:
        _cache[key] = pygame.font.SysFont(family, size)  # type: ignore[arg-type]
    return _cache[key]  # type: ignore[return-value]


def clear_cache() -> None:
    """Drop all cached fonts (e.g. after display mode change)."""
    _cache.clear()
