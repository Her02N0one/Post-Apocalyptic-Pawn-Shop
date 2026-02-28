"""core.zones.zone — Zone loading and data.

A ``Zone`` is a named tile grid with an anchor point, portal definitions,
and entity descriptors.  Zones are loaded from binary ``.zone`` files in
``zones/`` using :mod:`core.zone_io`.

    from core.zones import load_zone, Zone
    zone = load_zone("playground")
    scene.tiles = zone.tiles   # list[list[str]]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from core.zones.game_registry import GameRegistry

from core.paths import ZONES_DIR


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
    # Two-sided quads (fences, barricades, thin decals).
    # Each entry: dict with keys cell, pos, angle, width, height,
    # base_y, texture, collision, two_sided.
    quads: list[dict[str, Any]] = field(default_factory=list)
    # Each entry: dict with keys x, y, z, w, h, d, yaw, textures, collision.
    boxes: list[dict[str, Any]] = field(default_factory=list)
    # Per-cell floor reflectivity (0=none, 1–255 = reflection opacity).
    reflect_map: list[list[int]] = field(default_factory=list)
    # Curved / cylindrical wall arcs.
    # Each entry: dict with keys cx, cy, radius, angle_start, angle_end,
    # height_scale, base_y, texture, flags.
    curves: list[dict[str, Any]] = field(default_factory=list)
    # Per-cell floor slope: slope_dx[r][c] and slope_dy[r][c] represent
    # height change per unit in X and Y directions across the cell.
    # The centre of the cell is at fheight[r][c]; edges differ by ±0.5*slope.
    floor_slope_dx: list[list[float]] = field(default_factory=list)
    floor_slope_dy: list[list[float]] = field(default_factory=list)
    # ── Multi-layer floor/ceiling (secondary layer per cell) ────
    # -1000.0 sentinel = no secondary surface at this cell.
    floor2_heights: list[list[float]] = field(default_factory=list)
    ceil2_heights: list[list[float]] = field(default_factory=list)
    floor2_textures: list[list[str]] = field(default_factory=list)
    ceil2_textures: list[list[str]] = field(default_factory=list)
    # ── Per-cell fog volume (density + colour) ─────────────────
    # fog_density[r][c] = 0.0..1.0, fog_color[r][c] = (R,G,B) 0–255.
    fog_density: list[list[float]] = field(default_factory=list)
    fog_color: list[list[tuple]] = field(default_factory=list)
    # ── Portal rendering (same-zone non-Euclidean geometry) ─────
    # Each entry: dict with keys cell (row,col), face (0..3),
    # dest_x, dest_y, angle_offset (radians, 0 = no rotation).
    render_portals: list[dict[str, Any]] = field(default_factory=list)
    # Compiled numpy arrays (populated when loaded from .zone binary).
    # Dict keys: navi_grid, floor_z, ceil_z, textures, light_levels.
    # None when the Zone was created in-memory (e.g. by the editor).
    compiled: dict | None = field(default=None, repr=False)

    # ── Persistence ───────────────────────────────────────────────

    def save_to_file(
        self,
        filepath: str | Path,
        registry: "GameRegistry",
    ) -> None:
        """Compile and write this zone to a binary ``.zone`` file.

        Parameters
        ----------
        filepath : str | Path
            Destination path (usually ``ZONES_DIR / "<name>.zone"``).
        registry : GameRegistry
            Game-wide asset registry.
        """
        from core.zones.io import save_binary_zone
        save_binary_zone(self, filepath, registry)

    @classmethod
    def load_from_file(
        cls,
        filepath: str | Path,
        sim_only: bool = False,
    ) -> "Zone":
        """Load a zone from a binary ``.zone`` file.

        If *sim_only* is ``True``, render data (textures, lighting) is
        skipped to save memory — suitable for background simulation.

        Returns a fully populated :class:`Zone` instance with the
        ``compiled`` dict set to any loaded numpy arrays.
        """
        from core.zones.io import load_binary_zone

        data = load_binary_zone(filepath, sim_only=sim_only)
        H, W = data["height"], data["width"]

        # ── Tiles from ENTY ──────────────────────────────────────
        tiles = data.get("tiles", [])
        if not tiles:
            tiles = [["void"] * W for _ in range(H)]

        # ── Heights from ELEV arrays → Python lists ──────────────
        floor_z = data["floor_z"]
        ceil_z = data["ceil_z"]
        floor_heights = floor_z.tolist()
        ceil_heights = ceil_z.tolist()

        # ── Rotations ────────────────────────────────────────────
        rotations = data.get("rotations", [])
        if not rotations or len(rotations) != H:
            rotations = [[0] * W for _ in range(H)]

        # ── Portals ──────────────────────────────────────────────
        portals: list[Portal] = []
        for pd in data.get("portals", []):
            tile_coords = []
            for t in pd.get("tiles", []):
                if isinstance(t, (list, tuple)) and len(t) >= 2:
                    tile_coords.append((int(t[0]), int(t[1])))
            portals.append(Portal(
                tiles=tile_coords,
                target_zone=pd.get("target_zone", ""),
                target_row=float(pd.get("target_row", 0)),
                target_col=float(pd.get("target_col", 0)),
                exit_direction=pd.get("exit_direction", "up"),
            ))

        # ── Overlay walls ────────────────────────────────────────
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

        # ── Anchor ───────────────────────────────────────────────
        a = data.get("anchor", [H / 2.0, W / 2.0])
        if not isinstance(a, (list, tuple)) or len(a) < 2:
            a = [H / 2.0, W / 2.0]
        anchor = (float(a[0]), float(a[1]))

        # ── Editor grid helpers ──────────────────────────────────
        def _grid_or_default(key, default_val, h, w):
            g = data.get(key, [])
            if g and len(g) == h:
                return g
            return [[default_val] * w for _ in range(h)]

        def _grid_4_or_default(key, default_val, h, w):
            g = data.get(key, [])
            if g and len(g) == h:
                return g
            return [[[default_val] * 4 for _ in range(w)] for _ in range(h)]

        def _grid_seg_or_default(key, h, w):
            g = data.get(key, [])
            if g and len(g) == h:
                return g
            return [[[[], [], [], []] for _ in range(w)] for _ in range(h)]

        light_levels = data.get("_light_levels_raw", [])
        if not light_levels or len(light_levels) != H:
            light_levels = [[1.0] * W for _ in range(H)]

        # ── Compiled array dict ──────────────────────────────────
        compiled: dict = {
            "navi_grid": data["navi_grid"],
            "floor_z": data["floor_z"],
            "ceil_z": data["ceil_z"],
        }
        if "textures" in data:
            compiled["textures"] = data["textures"]
        if "light_levels" in data:  # float32 array from RNDR
            compiled["light_levels"] = data["light_levels"]

        return cls(
            name=data.get("name", Path(filepath).stem),
            width=W,
            height=H,
            anchor=anchor,
            tiles=tiles,
            rotations=rotations,
            portals=portals,
            entities=data.get("entities", []),
            first_person=bool(data.get("first_person", False)),
            floor_heights=floor_heights,
            ceil_heights=ceil_heights,
            floor_textures=_grid_or_default("floor_textures", "", H, W),
            ceil_textures=_grid_or_default("ceil_textures", "", H, W),
            wall_textures=_grid_or_default("wall_textures", "", H, W),
            face_textures=_grid_4_or_default("face_textures", "", H, W),
            light_levels=light_levels,
            wall_segments=_grid_seg_or_default("wall_segments", H, W),
            floor_step_textures=_grid_4_or_default("floor_step_textures", "", H, W),
            ceil_step_textures=_grid_4_or_default("ceil_step_textures", "", H, W),
            floor_step_segments=_grid_seg_or_default("floor_step_segments", H, W),
            ceil_step_segments=_grid_seg_or_default("ceil_step_segments", H, W),
            upper_wall_height=_grid_or_default("upper_wall_height", 0.0, H, W),
            overlay_walls=overlay_walls,
            quads=data.get("quads", []),
            boxes=data.get("boxes", []),
            reflect_map=_grid_or_default("reflect_map", 0, H, W),
            curves=data.get("curves", []),
            floor_slope_dx=_grid_or_default("floor_slope_dx", 0.0, H, W),
            floor_slope_dy=_grid_or_default("floor_slope_dy", 0.0, H, W),
            floor2_heights=_grid_or_default("floor2_heights", -1000.0, H, W),
            ceil2_heights=_grid_or_default("ceil2_heights", -1000.0, H, W),
            floor2_textures=_grid_or_default("floor2_textures", "", H, W),
            ceil2_textures=_grid_or_default("ceil2_textures", "", H, W),
            fog_density=_grid_or_default("fog_density", 0.0, H, W),
            fog_color=data.get("fog_color", [[(128, 128, 128)] * W for _ in range(H)]),
            render_portals=data.get("render_portals", []),
            compiled=compiled,
        )


def load_zone(name: str) -> Zone:
    """Load a zone from ``zones/<name>.zone``.

    Raises ``FileNotFoundError`` if the file doesn't exist.
    """
    path = ZONES_DIR / f"{name}.zone"
    return Zone.load_from_file(path)


def list_zones() -> list[str]:
    """Return names of all available ``.zone`` files."""
    if not ZONES_DIR.exists():
        return []
    return sorted(p.stem for p in ZONES_DIR.glob("*.zone"))


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
