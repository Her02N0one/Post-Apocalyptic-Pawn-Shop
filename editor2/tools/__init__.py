"""editor2/tools — Tool protocol and per-tool implementations."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Callable, Protocol, runtime_checkable


class OverlayMode(enum.Enum):
    """GL draw mode for an overlay primitive batch."""
    TRIS = "tris"        # triangle list (quads → 2 tris each)
    LINES = "lines"      # line list (pairs of verts)
    LINE_STRIP = "line_strip"


@dataclass()
class Overlay:
    """A batch of overlay geometry the viewport should draw.

    *verts* is a flat list of (x, y, z) tuples.
    The viewport interprets them according to *mode*.
    For TRIS, every 3 verts form a triangle.
    For LINES, every 2 verts form a segment.
    """
    mode: OverlayMode
    verts: list[tuple[float, float, float]]
    color: tuple[float, float, float, float]  # RGBA
    line_width: float = 2.0


def quad_to_tris(
    corners: list[tuple[float, float, float]],
    color: tuple[float, float, float, float],
) -> Overlay:
    """Convenience: build a TRIS overlay from 4 CCW corners."""
    v = corners
    return Overlay(
        mode=OverlayMode.TRIS,
        verts=[v[0], v[1], v[2], v[0], v[2], v[3]],
        color=color,
    )


@runtime_checkable
class Tool(Protocol):
    """Protocol that every editor tool implements."""

    @property
    def name(self) -> str: ...

    # Optional callback set by the main window for state-change notification.
    on_changed: Callable[[], None] | None

    def on_mouse_move(self, sx: float, sy: float,
                      vp_w: int, vp_h: int) -> None: ...

    def on_mouse_press(self, sx: float, sy: float,
                       vp_w: int, vp_h: int, button: int) -> None: ...

    def on_mouse_release(self, sx: float, sy: float,
                         vp_w: int, vp_h: int, button: int) -> None: ...

    def overlays(self) -> list[Overlay]: ...
