"""core.zones.cell_layer — Per-cell surface layer abstraction.

A ``CellLayer`` groups the co-varying per-cell grids that describe
one surface layer (floor or ceiling): elevation, texture, upper-wall
height, step-wall textures, and step-wall segments.

This eliminates the duplicated ``floor_heights / ceil_heights /
floor_textures / ceil_textures / floor2_heights / ceil2_heights / …``
pattern where every new surface attribute had to be added twice (or
four times with step-wall data).

Usage::

    layer = CellLayer.empty(16, 16, default_height=0.0)
    layer.heights[3][5] = 1.5
    layer.textures[3][5] = "stone"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CellLayer:
    """One floor-or-ceiling surface layer for every cell in a zone.

    Attributes
    ----------
    heights : list[list[float]]
        Per-cell elevation.  Sentinel ``-1000.0`` = "no surface here"
        (used for optional secondary layers).
    textures : list[list[str]]
        Per-cell texture key (``""`` = inherit from tile definition).
    upper_wall_height : list[list[float]]
        Per-cell upper-wall extension height.  ``0.0`` = auto.
    step_textures : list[list[list[str]]]
        Per-cell per-face ``[N, S, E, W]`` step-wall texture overrides.
        ``""`` = inherit from wall_textures.
    step_segments : list[list[list[list]]]
        Per-cell per-face stacked texture segments
        (same structure as ``wall_segments``).
    """
    heights: list[list[float]] = field(default_factory=list)
    textures: list[list[str]] = field(default_factory=list)
    upper_wall_height: list[list[float]] = field(default_factory=list)
    step_textures: list[list[list[str]]] = field(default_factory=list)
    step_segments: list[list[list[list]]] = field(default_factory=list)

    @classmethod
    def empty(
        cls,
        h: int,
        w: int,
        *,
        default_height: float = 0.0,
        default_texture: str = "",
    ) -> "CellLayer":
        """Create a layer with zeroed/empty grids of size ``h × w``."""
        return cls(
            heights=[[default_height] * w for _ in range(h)],
            textures=[[default_texture] * w for _ in range(h)],
            upper_wall_height=[[0.0] * w for _ in range(h)],
            step_textures=[[[""] * 4 for _ in range(w)] for _ in range(h)],
            step_segments=[[[[], [], [], []] for _ in range(w)] for _ in range(h)],
        )

    def to_dict(self, prefix: str) -> dict[str, Any]:
        """Serialize to a flat dict using ``prefix`` to namespace keys.

        For the primary floor layer, ``prefix="floor"`` produces::

            {"floor_heights": [...], "floor_textures": [...], ...}

        For the secondary ceiling layer, ``prefix="ceil2"`` produces::

            {"ceil2_heights": [...], "ceil2_textures": [...], ...}
        """
        return {
            f"{prefix}_heights": self.heights,
            f"{prefix}_textures": self.textures,
            f"upper_wall_height{'2' if prefix.endswith('2') else ''}": self.upper_wall_height,
            f"{prefix.rstrip('2')}_step_textures": self.step_textures,
            f"{prefix.rstrip('2')}_step_segments": self.step_segments,
        }

    @classmethod
    def from_grids(
        cls,
        heights: list[list[float]],
        textures: list[list[str]],
        upper_wall_height: list[list[float]] | None = None,
        step_textures: list[list[list[str]]] | None = None,
        step_segments: list[list[list[list]]] | None = None,
        h: int = 0,
        w: int = 0,
    ) -> "CellLayer":
        """Build a layer from existing grids, filling missing ones."""
        if not h:
            h = len(heights) if heights else 0
        if not w:
            w = len(heights[0]) if heights and heights[0] else 0

        return cls(
            heights=heights if heights else [[0.0] * w for _ in range(h)],
            textures=textures if textures else [[""] * w for _ in range(h)],
            upper_wall_height=upper_wall_height if upper_wall_height else [[0.0] * w for _ in range(h)],
            step_textures=step_textures if step_textures else [[[""] * 4 for _ in range(w)] for _ in range(h)],
            step_segments=step_segments if step_segments else [[[[], [], [], []] for _ in range(w)] for _ in range(h)],
        )
