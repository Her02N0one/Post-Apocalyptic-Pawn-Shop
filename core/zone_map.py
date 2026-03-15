"""core.zone_map — Zone tile/height/texture data container.

Extracted from ``core.session`` so the map layout is a self-contained,
independently passable data object rather than 12+ flat attributes on
Session.

Usage::

    zm = ZoneMap()
    zm.load_from_zone(some_zone_dataclass)
    assert zm.tiles[0][0] == "floor"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.zones import Zone


@dataclass
class ZoneMap:
    """Immutable-ish snapshot of a zone's tile grid and height layers.

    Populated by :meth:`load_from_zone` when the session loads a zone
    template.  Scenes read the fields directly.
    """

    zone_name: str = ""
    tiles: list[list[str]] = field(default_factory=list)
    rotations: list[list[int]] = field(default_factory=list)
    map_w: int = 0
    map_h: int = 0
    first_person: bool = False

    # Per-cell floor/ceiling heights
    floor_heights: list[list[float]] = field(default_factory=list)
    ceil_heights: list[list[float]] = field(default_factory=list)
    floor_textures: list[list[str]] = field(default_factory=list)
    ceil_textures: list[list[str]] = field(default_factory=list)

    # Layer-2 (secondary) floor/ceiling heights
    floor2_heights: list[list[float]] = field(default_factory=list)
    ceil2_heights: list[list[float]] = field(default_factory=list)

    def load_from_zone(self, zd: "Zone") -> None:
        """Populate all fields from a loaded :class:`Zone` dataclass."""
        self.zone_name = zd.name if hasattr(zd, 'name') else ""
        self.tiles = zd.tiles
        self.rotations = zd.rotations if zd.rotations else [
            [0] * (len(zd.tiles[0]) if zd.tiles else 0)
            for _ in range(len(zd.tiles))
        ]
        self.map_h = len(zd.tiles)
        self.map_w = len(zd.tiles[0]) if zd.tiles else 0
        self.first_person = zd.first_person
        self.floor_heights = zd.floor_heights
        self.ceil_heights = zd.ceil_heights
        self.floor_textures = zd.floor_textures
        self.ceil_textures = zd.ceil_textures
        self.floor2_heights = getattr(zd, 'floor2_heights', [])
        self.ceil2_heights = getattr(zd, 'ceil2_heights', [])
