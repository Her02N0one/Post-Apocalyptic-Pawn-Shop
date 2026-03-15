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
from core.zones.objects import (
    EntityDescriptor, Box, Quad, Curve, RenderPortal,
)


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
    base_y: float = 0.0             # vertical offset (0 = floor-anchored)
    transparent: bool = False   # color-key: magenta pixels see through
    blocks: bool = True         # blocks player movement
    uid: int = 0                # persistent object ID (assigned by Zone)


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
    # fheight[r][c] is the base corner (col, row); the slope rises
    # toward the opposite corner: h(fx,fy) = fh + dx*fx + dy*fy  (fx,fy in [0,1)).
    floor_slope_dx: list[list[float]] = field(default_factory=list)
    floor_slope_dy: list[list[float]] = field(default_factory=list)
    # Per-cell slope subdivision count (stair steps per tile).
    # 0 = use default (4), otherwise N = number of discrete steps.
    floor_slope_div: list[list[int]] = field(default_factory=list)
    # ── Multi-layer floor/ceiling (secondary layer per cell) ────
    # -1000.0 sentinel = no secondary surface at this cell.
    floor2_heights: list[list[float]] = field(default_factory=list)
    ceil2_heights: list[list[float]] = field(default_factory=list)
    floor2_textures: list[list[str]] = field(default_factory=list)
    ceil2_textures: list[list[str]] = field(default_factory=list)
    # Per-cell upper wall height for ceiling2 (same role as upper_wall_height
    # but for the secondary ceiling layer).  0.0 = no extension.
    upper_wall_height2: list[list[float]] = field(default_factory=list)
    # ── Per-cell fog volume (density + colour) ─────────────────
    # fog_density[r][c] = 0.0..1.0, fog_color[r][c] = (R,G,B) 0–255.
    fog_density: list[list[float]] = field(default_factory=list)
    fog_color: list[list[tuple]] = field(default_factory=list)
    # ── Sky / skybox ────────────────────────────────────────────
    # skybox: filename (without dir) of a panoramic image in
    # assets/textures/skyboxes/, or "" for procedural gradient.
    skybox: str = ""
    # sky_color: optional override (R,G,B) 0-255 for the gradient
    # top colour.  Empty tuple = use default.  Only used when
    # skybox is "" and the zone is exterior.
    sky_color: tuple = ()
    # ── Portal rendering (same-zone non-Euclidean geometry) ─────
    # Each entry: dict with keys cell (row,col), face (0..3),
    # dest_x, dest_y, angle_offset (radians, 0 = no rotation).
    render_portals: list[dict[str, Any]] = field(default_factory=list)
    # Compiled numpy arrays (populated when loaded from .zone binary).
    # Dict keys: navi_grid, floor_z, ceil_z, textures, light_levels.
    # None when the Zone was created in-memory (e.g. by the editor).
    compiled: dict | None = field(default=None, repr=False)

    # ── Persistent UID counter for placeable objects ──────────────
    # Monotonically increasing; persisted in the zone file so UIDs
    # are stable across save/load cycles.
    _next_uid: int = field(default=1, repr=False)

    # ── Change-detection generation counter ───────────────────────
    # Bumped on every mutation; the renderer checks this to skip
    # redundant buffer rebuilds.  Not persisted.
    _generation: int = field(default=0, repr=False)

    def bump_generation(self) -> None:
        """Signal that zone data has changed and buffers need rebuilding."""
        self._generation += 1

    # ── CellLayer property bridges ────────────────────────────────
    # These return CellLayer *views* wrapping the existing raw fields.
    # Mutations through the layer propagate to the Zone because they
    # share the same underlying lists (no copy).

    @property
    def floor_layer(self) -> "CellLayer":
        """Primary floor surface as a :class:`CellLayer`."""
        from core.zones.cell_layer import CellLayer
        return CellLayer(
            heights=self.floor_heights,
            textures=self.floor_textures,
            upper_wall_height=self.upper_wall_height,
            step_textures=self.floor_step_textures,
            step_segments=self.floor_step_segments,
        )

    @property
    def ceil_layer(self) -> "CellLayer":
        """Primary ceiling surface as a :class:`CellLayer`."""
        from core.zones.cell_layer import CellLayer
        return CellLayer(
            heights=self.ceil_heights,
            textures=self.ceil_textures,
            upper_wall_height=self.upper_wall_height,
            step_textures=self.ceil_step_textures,
            step_segments=self.ceil_step_segments,
        )

    @property
    def floor2_layer(self) -> "CellLayer":
        """Secondary floor surface as a :class:`CellLayer`."""
        from core.zones.cell_layer import CellLayer
        return CellLayer(
            heights=self.floor2_heights,
            textures=self.floor2_textures,
            upper_wall_height=self.upper_wall_height2,
            step_textures=[],
            step_segments=[],
        )

    @property
    def ceil2_layer(self) -> "CellLayer":
        """Secondary ceiling surface as a :class:`CellLayer`."""
        from core.zones.cell_layer import CellLayer
        return CellLayer(
            heights=self.ceil2_heights,
            textures=self.ceil2_textures,
            upper_wall_height=self.upper_wall_height2,
            step_textures=[],
            step_segments=[],
        )

    def next_uid(self) -> int:
        """Allocate and return the next unique object ID."""
        uid = self._next_uid
        self._next_uid = uid + 1
        return uid

    def ensure_uids(self) -> None:
        """Assign UIDs to any zone objects that lack them.

        Called after loading old zone files that predate the UID system.
        Idempotent — objects that already have a non-zero uid keep it.
        """
        for ent in self.entities:
            if not ent.get("uid"):
                ent["uid"] = self.next_uid()
        for b in self.boxes:
            if not b.get("uid"):
                b["uid"] = self.next_uid()
        for q in self.quads:
            if not q.get("uid"):
                q["uid"] = self.next_uid()
        for rp in self.render_portals:
            if not rp.get("uid"):
                rp["uid"] = self.next_uid()
        for cv in self.curves:
            if not cv.get("uid"):
                cv["uid"] = self.next_uid()
        for ow in self.overlay_walls:
            if not ow.uid:
                ow.uid = self.next_uid()

    # ── UID-based object lookup ───────────────────────────────────

    def _uid_of(self, obj) -> int:
        """Extract UID from a dict or dataclass object."""
        if isinstance(obj, dict):
            return obj.get("uid", 0)
        return getattr(obj, "uid", 0)

    def object_by_uid(self, uid: int) -> tuple[str, int, Any] | None:
        """Find a zone object by UID across all object lists.

        Returns ``(type_tag, index, obj)`` or ``None``.
        ``type_tag`` is one of ``"entity"``, ``"prism"``, ``"quad"``,
        ``"portal"``, ``"curve"``, ``"overlay"``.
        """
        _LISTS: list[tuple[str, list]] = [
            ("entity", self.entities),
            ("prism", self.boxes),
            ("quad", self.quads),
            ("portal", self.render_portals),
            ("curve", self.curves),
            ("overlay", self.overlay_walls),
        ]
        for tag, lst in _LISTS:
            for i, obj in enumerate(lst):
                if self._uid_of(obj) == uid:
                    return (tag, i, obj)
        return None

    def index_of_uid(self, type_tag: str, uid: int) -> int | None:
        """Return the list index of an object with *uid* in the named list.

        ``type_tag`` is ``"entity"`` | ``"prism"`` | ``"quad"`` |
        ``"portal"`` | ``"curve"`` | ``"overlay"``.

        Returns ``None`` if not found.
        """
        _TAG_TO_LIST: dict[str, list] = {
            "entity": self.entities,
            "prism": self.boxes,
            "quad": self.quads,
            "portal": self.render_portals,
            "curve": self.curves,
            "overlay": self.overlay_walls,
        }
        lst = _TAG_TO_LIST.get(type_tag)
        if lst is None:
            return None
        for i, obj in enumerate(lst):
            if self._uid_of(obj) == uid:
                return i
        return None

    def uid_at(self, type_tag: str, index: int) -> int:
        """Return the UID of the object at *index* in the named list.

        Returns ``0`` if out of bounds or the object has no UID.
        """
        _TAG_TO_LIST: dict[str, list] = {
            "entity": self.entities,
            "prism": self.boxes,
            "quad": self.quads,
            "portal": self.render_portals,
            "curve": self.curves,
            "overlay": self.overlay_walls,
        }
        lst = _TAG_TO_LIST.get(type_tag)
        if lst is None or index < 0 or index >= len(lst):
            return 0
        return self._uid_of(lst[index])

    # ── Validation ─────────────────────────────────────────────────

    def validate(self, **kwargs: Any) -> list:
        """Run the structured validation pass and return a list of issues.

        Keyword arguments are forwarded to
        :func:`core.zones.validation.validate_zone` — pass
        ``entity_registry``, ``tile_registry``, and/or ``texture_dir``
        to enable the corresponding optional checks.
        """
        from core.zones.validation import validate_zone
        return validate_zone(self, **kwargs)

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
                base_y=float(ow.get("base_y", 0.0)),
                transparent=bool(ow.get("transparent", False)),
                blocks=bool(ow.get("blocks", True)),
                uid=int(ow.get("uid", 0)),
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

        zone = cls(
            name=data.get("name", Path(filepath).stem),
            width=W,
            height=H,
            anchor=anchor,
            tiles=tiles,
            rotations=rotations,
            portals=portals,
            entities=[EntityDescriptor.from_dict(d) for d in data.get("entities", [])],
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
            quads=[Quad.from_dict(d) for d in data.get("quads", [])],
            boxes=[Box.from_dict(d) for d in data.get("boxes", [])],
            reflect_map=_grid_or_default("reflect_map", 0, H, W),
            curves=[Curve.from_dict(d) for d in data.get("curves", [])],
            floor_slope_dx=_grid_or_default("floor_slope_dx", 0.0, H, W),
            floor_slope_dy=_grid_or_default("floor_slope_dy", 0.0, H, W),
            floor_slope_div=_grid_or_default("floor_slope_div", 0, H, W),
            floor2_heights=_grid_or_default("floor2_heights", -1000.0, H, W),
            ceil2_heights=_grid_or_default("ceil2_heights", -1000.0, H, W),
            floor2_textures=_grid_or_default("floor2_textures", "", H, W),
            ceil2_textures=_grid_or_default("ceil2_textures", "", H, W),
            upper_wall_height2=_grid_or_default("upper_wall_height2", 0.0, H, W),
            fog_density=_grid_or_default("fog_density", 0.0, H, W),
            fog_color=data.get("fog_color", [[(128, 128, 128)] * W for _ in range(H)]),
            render_portals=[RenderPortal.from_dict(d) for d in data.get("render_portals", [])],
            skybox=data.get("skybox", ""),
            sky_color=tuple(data.get("sky_color", ())),
            compiled=compiled,
            _next_uid=data.get("next_uid", 1),
        )
        zone.ensure_uids()
        return zone


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
