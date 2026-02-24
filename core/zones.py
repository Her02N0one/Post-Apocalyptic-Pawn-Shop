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
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

from core.paths import ZONES_DIR
from core.tiles import migrate_int_grid


@dataclass
class OverlayWall:
    """A free-form wall segment not bound to the tile grid.

    Endpoints (x1,y1)→(x2,y2) are in tile-coordinate space.
    Supports fences, diagonal walls, partial walls, and
    transparent surfaces that the standard tile grid cannot express.
    """
    x1: float
    y1: float
    x2: float
    y2: float
    texture: str = "brick_wall"
    height_scale: float = 1.0
    transparent: bool = False   # color-key: magenta pixels see through
    blocks: bool = True         # blocks player movement


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
    # Per-cell wall texture override ("" = use tile default texture)
    # Set by the 3D voxel editor so the block's chosen texture carries
    # through to the 2.5D renderer even if the tile type doesn't match.
    wall_textures: list[list[str]] = field(default_factory=list)
    # Per-cell per-face wall texture overrides: face_textures[r][c] = [N,S,E,W]
    # Higher priority than wall_textures.  Empty string = use wall_textures or default.
    face_textures: list[list[list[str]]] = field(default_factory=list)
    # Per-tile spatial lighting (0.0=dark .. 1.0=full bright)
    light_levels: list[list[float]] = field(default_factory=list)
    # Per-face stacked texture segments:
    # wall_segments[r][c][face] = [[tex_key, y_top], ...]
    # Sorted bottom-to-top.  Bottom of first = floor_height.
    # Empty list [] = no segments (use face_textures single-texture).
    wall_segments: list[list[list[list]]] = field(default_factory=list)
    # ── Step-wall data (floor/ceiling mass side faces) ──────────
    # Per-cell per-face textures for floor mass cardinal faces (visible
    # when this cell's floor is higher than a neighbour).
    # floor_step_textures[r][c] = [N, S, E, W].  "" = inherit wall_textures.
    floor_step_textures: list[list[list[str]]] = field(default_factory=list)
    # Per-cell per-face textures for ceiling mass cardinal faces (visible
    # when this cell's ceiling is lower than a neighbour or has no ceiling).
    ceil_step_textures: list[list[list[str]]] = field(default_factory=list)
    # Per-face stacked segments for floor/ceiling step walls.
    # Same structure as wall_segments.
    floor_step_segments: list[list[list[list]]] = field(default_factory=list)
    ceil_step_segments: list[list[list[list]]] = field(default_factory=list)
    # Per-cell upper wall height override.  0.0 = auto (derived from the
    # tallest neighbouring ceiling).  Any value > ceil_height overrides.
    upper_wall_height: list[list[float]] = field(default_factory=list)
    # Free-form wall segments (fences, partitions, diagonal walls)
    overlay_walls: list[OverlayWall] = field(default_factory=list)


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
        ceil_heights = [[10.0] * width for _ in range(height)]

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
    raw_wt = data.get("wall_textures", [])
    wall_textures: list[list[str]]
    if raw_wt and len(raw_wt) == height:
        wall_textures = [[str(v) for v in row] for row in raw_wt]
    else:
        wall_textures = [[""]*width for _ in range(height)]

    raw_ft = data.get("face_textures", [])
    face_textures: list[list[list[str]]]
    if raw_ft and len(raw_ft) == height:
        face_textures = []
        for row in raw_ft:
            frow: list[list[str]] = []
            for cell in row:
                if isinstance(cell, list) and len(cell) == 4:
                    frow.append([str(v) for v in cell])
                elif isinstance(cell, str) and cell:
                    frow.append([cell, cell, cell, cell])  # migrate single → 4
                else:
                    frow.append(["", "", "", ""])
            face_textures.append(frow)
    else:
        face_textures = [[[""]*4 for _ in range(width)] for _ in range(height)]
    raw_ll = data.get("light_levels", [])
    light_levels: list[list[float]]
    if raw_ll and len(raw_ll) == height:
        light_levels = [[float(v) for v in row] for row in raw_ll]
    else:
        light_levels = [[1.0] * width for _ in range(height)]

    # ── Per-face stacked wall segments ──
    raw_ws = data.get("wall_segments", [])
    wall_segments: list[list[list[list]]]
    if raw_ws and len(raw_ws) == height:
        wall_segments = []
        for row in raw_ws:
            wsrow: list[list[list]] = []
            for cell in row:
                if isinstance(cell, list) and len(cell) == 4:
                    # cell = [ face0_segs, face1_segs, face2_segs, face3_segs ]
                    wsrow.append([
                        [[str(s[0]), float(s[1])] for s in (face or [])]
                        for face in cell
                    ])
                else:
                    wsrow.append([[], [], [], []])
            wall_segments.append(wsrow)
    else:
        wall_segments = [[[[], [], [], []] for _ in range(width)]
                         for _ in range(height)]

    # ── Step-wall textures & segments ──
    def _load_step_tex(key: str) -> list[list[list[str]]]:
        raw = data.get(key, [])
        if raw and len(raw) == height:
            result = []
            for row in raw:
                frow: list[list[str]] = []
                for cell in row:
                    if isinstance(cell, list) and len(cell) == 4:
                        frow.append([str(v) for v in cell])
                    else:
                        frow.append(["", "", "", ""])
                result.append(frow)
            return result
        return [[["", "", "", ""] for _ in range(width)] for _ in range(height)]

    def _load_step_seg(key: str) -> list[list[list[list]]]:
        raw = data.get(key, [])
        if raw and len(raw) == height:
            result = []
            for row in raw:
                wsrow: list[list[list]] = []
                for cell in row:
                    if isinstance(cell, list) and len(cell) == 4:
                        wsrow.append([
                            [[str(s[0]), float(s[1])] for s in (face or [])]
                            for face in cell
                        ])
                    else:
                        wsrow.append([[], [], [], []])
                result.append(wsrow)
            return result
        return [[[[], [], [], []] for _ in range(width)] for _ in range(height)]

    floor_step_textures = _load_step_tex("floor_step_textures")
    ceil_step_textures = _load_step_tex("ceil_step_textures")
    floor_step_segments = _load_step_seg("floor_step_segments")
    ceil_step_segments = _load_step_seg("ceil_step_segments")

    raw_uwh = data.get("upper_wall_height", [])
    upper_wall_height: list[list[float]]
    if raw_uwh and len(raw_uwh) == height:
        upper_wall_height = [[float(v) for v in row] for row in raw_uwh]
    else:
        upper_wall_height = [[0.0] * width for _ in range(height)]

    # ── Overlay walls (free-form segments) ──
    overlay_walls: list[OverlayWall] = []
    for ow in data.get("overlay_walls", []):
        overlay_walls.append(OverlayWall(
            x1=float(ow.get("x1", 0)), y1=float(ow.get("y1", 0)),
            x2=float(ow.get("x2", 0)), y2=float(ow.get("y2", 0)),
            texture=str(ow.get("texture", "brick_wall")),
            height_scale=float(ow.get("height_scale", 1.0)),
            transparent=bool(ow.get("transparent", False)),
            blocks=bool(ow.get("blocks", True)),
        ))

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
        wall_textures=wall_textures,
        face_textures=face_textures,
        light_levels=light_levels,
        wall_segments=wall_segments,
        floor_step_textures=floor_step_textures,
        ceil_step_textures=ceil_step_textures,
        floor_step_segments=floor_step_segments,
        ceil_step_segments=ceil_step_segments,
        upper_wall_height=upper_wall_height,
        overlay_walls=overlay_walls,
    )


def list_zones() -> list[str]:
    """Return names of all available zone JSON files."""
    if not ZONES_DIR.exists():
        return []
    return sorted(p.stem for p in ZONES_DIR.glob("*.json"))


def find_spawn(zone: "Zone",
               is_solid_fn: "Callable[[float, float], bool]"
               ) -> tuple[float, float]:
    """Find a walkable spawn position in *zone*.

    Tries the zone anchor first, then scans every cell.
    Falls back to the zone centre if nothing is walkable.
    """
    px, py = float(zone.anchor[1]), float(zone.anchor[0])
    if not is_solid_fn(px, py):
        return px, py
    for r in range(zone.height):
        for c in range(zone.width):
            if not is_solid_fn(c + 0.5, r + 0.5):
                return c + 0.5, r + 0.5
    return zone.width / 2.0, zone.height / 2.0
