"""core/zones.py — Zone loading and data.

A ``Zone`` is a named tile grid with an anchor point, portal definitions,
and entity descriptors.  Zones are loaded from JSON files in ``zones/``.

    from core.zones import load_zone, Zone
    zone = load_zone("playground")
    scene.tiles = zone.tiles
    for desc in zone.entities:
        spawn(world, desc, zone.name)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


ZONES_DIR = Path(__file__).resolve().parent.parent / "zones"


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
    tiles: list[list[int]]
    portals: list[Portal] = field(default_factory=list)
    entities: list[dict[str, Any]] = field(default_factory=list)
    first_person: bool = False  # True → zone can be viewed in first-person


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

    tiles: list[list[int]] = data.get("tiles", [])
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

    interior: bool = bool(data.get("interior", False))
    first_person: bool = bool(data.get("first_person", interior))

    return Zone(
        name=name,
        width=width,
        height=height,
        anchor=anchor,
        tiles=tiles,
        portals=portals,
        first_person=first_person,
        entities=entities,
    )


def list_zones() -> list[str]:
    """Return names of all available zone JSON files."""
    if not ZONES_DIR.exists():
        return []
    return sorted(p.stem for p in ZONES_DIR.glob("*.json"))
