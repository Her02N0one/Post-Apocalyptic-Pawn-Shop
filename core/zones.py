"""core/zones.py — Zone loading and data.

A ``Zone`` is a named tile grid with an anchor point, portal definitions,
and entity descriptors.  Zones are loaded from JSON files in ``zones/``.

Tile grids use **string IDs** (e.g. ``"grass"``, ``"wall"``).
Old integer grids are auto-migrated on load via ``migrate_int_grid``.

    from core.zones import load_zone, Zone
    zone = load_zone("playground")
    scene.tiles = zone.tiles   # list[list[str]]
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from core.paths import ZONES_DIR
from core.tiles import migrate_int_grid


@dataclass
class Portal:
    """A one-way link from tile(s) in this zone to a position in another."""
    tiles: list[tuple[int, int]]
    target_zone: str
    target_row: float
    target_col: float
    exit_direction: str = "up"  # direction player walks/faces when arriving here


@dataclass
class Zone:
    """Loaded zone data — tiles, anchor, portals, entity descriptors."""
    name: str
    width: int
    height: int
    anchor: tuple[float, float]
    tiles: list[list[str]]
    rotations: list[list[int]] = field(default_factory=list)
    portals: list[Portal] = field(default_factory=list)
    entities: list[dict[str, Any]] = field(default_factory=list)
    first_person: bool = False  # True → zone can be viewed in first-person
    # Per-cell Doom-style sector heights and textures
    floor_heights: list[list[float]] = field(default_factory=list)
    ceil_heights: list[list[float]] = field(default_factory=list)
    floor_textures: list[list[str]] = field(default_factory=list)
    ceil_textures: list[list[str]] = field(default_factory=list)


def load_zone(name: str) -> Zone:
    """Load a zone from ``zones/<name>.json``.

    Raises ``FileNotFoundError`` if the file doesn't exist.
    """
    path = ZONES_DIR / f"{name}.json"
    with open(path) as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Corrupt zone file '{name}': {exc}") from exc

    anchor_raw = data.get("anchor", [15.0, 15.0])
    if not isinstance(anchor_raw, list) or len(anchor_raw) < 2:
        anchor_raw = [15.0, 15.0]
    anchor = (float(anchor_raw[0]), float(anchor_raw[1]))

    raw_tiles = data.get("tiles", [])
    # Auto-migrate old integer grids to string IDs
    if raw_tiles and raw_tiles[0] and isinstance(raw_tiles[0][0], int):
        raw_tiles = migrate_int_grid(raw_tiles)
    tiles: list[list[str]] = raw_tiles
    height = len(tiles)
    width = len(tiles[0]) if tiles else 0

    portals: list[Portal] = []
    for p in data.get("portals", []):
        raw_tiles = p.get("tiles", [])
        tile_coords = []
        for t in raw_tiles:
            if isinstance(t, (list, tuple)) and len(t) >= 2:
                tile_coords.append((int(t[0]), int(t[1])))
        tp = p.get("target_pos", [0, 0])
        if not isinstance(tp, (list, tuple)) or len(tp) < 2:
            tp = [0, 0]
        portals.append(Portal(
            tiles=tile_coords,
            target_zone=p.get("target_zone", ""),
            target_row=float(tp[0]),
            target_col=float(tp[1]),
            exit_direction=p.get("exit_direction", "up"),
        ))

    entities: list[dict[str, Any]] = data.get("entities", [])

    # Rotation grid (parallel to tiles, default 0)
    raw_rot = data.get("rotations", [])
    if raw_rot and len(raw_rot) == height:
        rotations: list[list[int]] = raw_rot
    else:
        rotations = [[0] * width for _ in range(height)]

    interior: bool = bool(data.get("interior", False))
    first_person: bool = bool(data.get("first_person", interior))

    # Per-cell height / texture grids (Doom-style sector data)
    raw_fh = data.get("floor_heights", [])
    floor_heights: list[list[float]]
    if raw_fh and len(raw_fh) == height:
        floor_heights = [[float(v) for v in row] for row in raw_fh]
    else:
        floor_heights = [[0.0] * width for _ in range(height)]

    raw_ch = data.get("ceil_heights", [])
    ceil_heights: list[list[float]]
    if raw_ch and len(raw_ch) == height:
        ceil_heights = [[float(v) for v in row] for row in raw_ch]
    else:
        ceil_heights = [[1.0] * width for _ in range(height)]

    raw_ft = data.get("floor_textures", [])
    floor_textures: list[list[str]]
    if raw_ft and len(raw_ft) == height:
        floor_textures = [[str(v) for v in row] for row in raw_ft]
    else:
        floor_textures = [[""] * width for _ in range(height)]

    raw_ct = data.get("ceil_textures", [])
    ceil_textures: list[list[str]]
    if raw_ct and len(raw_ct) == height:
        ceil_textures = [[str(v) for v in row] for row in raw_ct]
    else:
        ceil_textures = [[""] * width for _ in range(height)]

    return Zone(
        name=name,
        width=width,
        height=height,
        anchor=anchor,
        tiles=tiles,
        rotations=rotations,
        portals=portals,
        first_person=first_person,
        entities=entities,
        floor_heights=floor_heights,
        ceil_heights=ceil_heights,
        floor_textures=floor_textures,
        ceil_textures=ceil_textures,
    )


def list_zones() -> list[str]:
    """Return names of all available zone JSON files."""
    if not ZONES_DIR.exists():
        return []
    return sorted(p.stem for p in ZONES_DIR.glob("*.json"))
