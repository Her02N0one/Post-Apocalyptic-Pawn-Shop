"""editor/inspector_entries.py — Typed entry descriptors for the inspector.

Replaces the raw-tuple widget system (``("section", …)``) with proper
dataclasses. Each dataclass carries all the data needed to **draw** and
**hit-test** one row in the inspector.

Layout builders (``_build_zone_widgets``, etc.) create lists of
``InspectorEntry`` instances.  The draw loop and event loop iterate
over them with simple ``isinstance`` checks — no more stringly-typed
``if kind == "section"`` chains.

Usage example::

    entries: list[InspectorEntry] = []
    entries.append(LabelEntry(text="ZONE", x=px, y=y, color=Theme.ACCENT))
    entries.append(SectionEntry(text="Position", x=px, y=y, w=w))
    entries.append(KVEntry(label="ID:", value="floor", x=px, y=y))
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pygame


# ── Base ─────────────────────────────────────────────────────────

@dataclass(slots=True)
class InspectorEntry:
    """Base for every inspector row."""
    x: int
    y: int


# ── Concrete entry types ────────────────────────────────────────

@dataclass(slots=True)
class LabelEntry(InspectorEntry):
    """Bold / accent-coloured heading text."""
    text: str = ""
    color: tuple[int, int, int] = (220, 220, 220)


@dataclass(slots=True)
class SectionEntry(InspectorEntry):
    """Section divider — text + horizontal rule underneath."""
    text: str = ""
    w: int = 200


@dataclass(slots=True)
class KVEntry(InspectorEntry):
    """Read-only key: value pair."""
    label: str = ""
    value: str = ""


@dataclass(slots=True)
class LabeledWidgetEntry(InspectorEntry):
    """Dim label on the left, interactive widget on the right."""
    label: str = ""
    widget: Any = None          # TextField / NumberField / Dropdown / …


@dataclass(slots=True)
class WidgetEntry(InspectorEntry):
    """Standalone widget (e.g. Checkbox) that spans the full width."""
    widget: Any = None


@dataclass(slots=True)
class EntityRowEntry(InspectorEntry):
    """Clickable row in the entity list."""
    idx: int = -1
    name: str = ""
    prefab: str = ""


@dataclass(slots=True)
class ActionButtonEntry(InspectorEntry):
    """Clickable action button (e.g. "Add Component…")."""
    label: str = ""
    w: int = 200


@dataclass(slots=True)
class DeleteButtonEntry(InspectorEntry):
    """Red delete button."""
    label: str = ""
    w: int = 200


@dataclass(slots=True)
class TexPreviewEntry(InspectorEntry):
    """64×64 texture preview square."""
    tile_id: str = ""
    size: int = 64


@dataclass(slots=True)
class ColorSwatchEntry(InspectorEntry):
    """Small colour swatch square."""
    color: tuple[int, int, int] = (128, 128, 128)
    size: int = 18


# ── Renderer ─────────────────────────────────────────────────────

class EntryRenderer:
    """Draws and hit-tests ``InspectorEntry`` instances.

    Centralises all rendering into a single dispatch table so the
    inspector ``draw()`` and ``handle_event()`` methods become
    thin loops.
    """

    # Registry: entry type → (draw_fn, hit_fn | None)
    _draw_dispatch: dict[type, Any] = {}
    _hit_dispatch: dict[type, Any] = {}

    @classmethod
    def register(cls, entry_cls):
        """Decorator — register draw / hit functions for *entry_cls*."""
        def wrapper(fn):
            cls._draw_dispatch[entry_cls] = fn
            return fn
        return wrapper

    @classmethod
    def register_hit(cls, entry_cls):
        """Decorator — register a hit-test function for *entry_cls*."""
        def wrapper(fn):
            cls._hit_dispatch[entry_cls] = fn
            return fn
        return wrapper

    @classmethod
    def draw_entry(cls, surface: pygame.Surface, entry: InspectorEntry,
                   offset: int, **kwargs):
        """Dispatch to the registered draw function."""
        fn = cls._draw_dispatch.get(type(entry))
        if fn is not None:
            fn(surface, entry, offset, **kwargs)

    @classmethod
    def hit_test(cls, entry: InspectorEntry, event: pygame.event.Event,
                 offset: int, **kwargs) -> str | None:
        """Dispatch to the registered hit-test function. Returns action or None."""
        fn = cls._hit_dispatch.get(type(entry))
        if fn is not None:
            return fn(entry, event, offset, **kwargs)
        return None
