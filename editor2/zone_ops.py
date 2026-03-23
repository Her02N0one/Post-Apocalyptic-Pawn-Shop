"""editor2/zone_ops.py — Zone-level operations (resize, validate, export, etc.).

Free functions that operate on a ``Zone`` object.  Each function takes
the zone (and any other needed parameters) and returns a result or
mutates the zone in place.  They do NOT depend on the editor window —
all UI feedback (status messages, dialogs) is handled by the caller.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.zones import Zone


def create_empty_zone(w: int = 20, h: int = 20):
    """Create a blank in-memory zone (not saved to disk)."""
    from core.zones import Zone
    return Zone(
        name="untitled", width=w, height=h,
        anchor=(h / 2.0, w / 2.0),
        first_person=True,
        tiles=[["grass"] * w for _ in range(h)],
        floor_heights=[[0.0] * w for _ in range(h)],
        ceil_heights=[[10.0] * w for _ in range(h)],
        floor_textures=[[""] * w for _ in range(h)],
        ceil_textures=[[""] * w for _ in range(h)],
        wall_textures=[[""] * w for _ in range(h)],
        face_textures=[[[""] * 4 for _ in range(w)] for _ in range(h)],
        light_levels=[[1.0] * w for _ in range(h)],
        rotations=[[0] * w for _ in range(h)],
        wall_segments=[[[[], [], [], []] for _ in range(w)] for _ in range(h)],
        floor_step_textures=[[[""] * 4 for _ in range(w)] for _ in range(h)],
        ceil_step_textures=[[[""] * 4 for _ in range(w)] for _ in range(h)],
        floor_step_segments=[[[[], [], [], []] for _ in range(w)] for _ in range(h)],
        ceil_step_segments=[[[[], [], [], []] for _ in range(w)] for _ in range(h)],
        upper_wall_height=[[0.0] * w for _ in range(h)],
    )


def resize_zone(zone: Zone, nw: int, nh: int) -> None:
    """Resize *zone* in place, preserving existing cell data where it overlaps."""
    ow, oh = zone.width, zone.height

    def _resize_grid(grid, default):
        new = [[default] * nw for _ in range(nh)]
        for r in range(min(oh, nh)):
            for c in range(min(ow, nw)):
                new[r][c] = grid[r][c]
        return new

    def _resize_4face(grid, default=""):
        new = [[[default] * 4 for _ in range(nw)] for _ in range(nh)]
        for r in range(min(oh, nh)):
            for c in range(min(ow, nw)):
                new[r][c] = list(grid[r][c])
        return new

    def _resize_4seg(grid):
        new = [[[[], [], [], []] for _ in range(nw)] for _ in range(nh)]
        for r in range(min(oh, nh)):
            for c in range(min(ow, nw)):
                new[r][c] = [list(s) for s in grid[r][c]]
        return new

    zone.width = nw
    zone.height = nh
    zone.tiles = _resize_grid(zone.tiles, "grass")
    zone.floor_heights = _resize_grid(zone.floor_heights, 0.0)
    zone.ceil_heights = _resize_grid(zone.ceil_heights, 10.0)
    zone.floor_textures = _resize_grid(zone.floor_textures, "")
    zone.ceil_textures = _resize_grid(zone.ceil_textures, "")
    zone.wall_textures = _resize_grid(zone.wall_textures, "")
    zone.light_levels = _resize_grid(zone.light_levels, 1.0)
    zone.rotations = _resize_grid(zone.rotations, 0)
    zone.face_textures = _resize_4face(zone.face_textures)
    zone.wall_segments = _resize_4seg(zone.wall_segments)
    zone.floor_step_textures = _resize_4face(zone.floor_step_textures)
    zone.ceil_step_textures = _resize_4face(zone.ceil_step_textures)
    zone.floor_step_segments = _resize_4seg(zone.floor_step_segments)
    zone.ceil_step_segments = _resize_4seg(zone.ceil_step_segments)
    zone.upper_wall_height = _resize_grid(
        zone.upper_wall_height if zone.upper_wall_height else
        [[0.0] * ow for _ in range(oh)], 0.0)


def zone_info_text(zone: Zone, zone_name: str) -> str:
    """Return a multi-line summary string for a zone info dialog."""
    from core.tiles import tile_def
    wall_count = sum(
        1 for r in range(zone.height) for c in range(zone.width)
        if tile_def(zone.tiles[r][c]) and tile_def(zone.tiles[r][c]).wall
    )
    return (
        f"Name: {zone_name}\n"
        f"Size: {zone.width} × {zone.height}\n"
        f"Cells: {zone.width * zone.height}\n"
        f"Walls: {wall_count}\n"
        f"Entities: {len(zone.entities)}"
    )


def duplicate_zone(zone: Zone, new_name: str) -> "Zone":
    """Deep-copy a zone and rename it.  Does NOT save to disk."""
    dup = copy.deepcopy(zone)
    dup.name = new_name
    return dup


def validate_zone_issues(zone: Zone) -> list:
    """Run zone validation, return list of Issue objects."""
    from core.zones.validation import validate_zone
    from core.entity_defs import entity_registry
    return validate_zone(zone, entity_registry=entity_registry())


def find_replace_texture(zone: Zone, find: str, replace: str, bus) -> int:
    """Replace all occurrences of *find* texture with *replace* across all grids.

    Executes via the command bus for undo support.  Returns the number
    of individual field changes made.
    """
    from editor2.core import BatchCmd, SetCellFieldCmd, SetFaceFieldCmd
    cmds: list = []
    for r in range(zone.height):
        for c in range(zone.width):
            if zone.tiles[r][c] == find:
                cmds.append(SetCellFieldCmd(r, c, "tiles", replace))
            if zone.floor_textures and zone.floor_textures[r][c] == find:
                cmds.append(SetCellFieldCmd(r, c, "floor_textures", replace))
            if zone.ceil_textures and zone.ceil_textures[r][c] == find:
                cmds.append(SetCellFieldCmd(r, c, "ceil_textures", replace))
            if zone.wall_textures and zone.wall_textures[r][c] == find:
                cmds.append(SetCellFieldCmd(r, c, "wall_textures", replace))
            if zone.face_textures and zone.face_textures[r][c]:
                for i in range(4):
                    if zone.face_textures[r][c][i] == find:
                        cmds.append(SetFaceFieldCmd(r, c, i, "face_textures", replace))
    if cmds:
        bus.execute(BatchCmd(cmds, f"Replace '{find}' → '{replace}'"))
    return len(cmds)


def export_topdown(zone: Zone, zone_name: str) -> Path:
    """Export a top-down tile-colour PNG.  Returns the output path."""
    from PIL import Image
    from core.tiles import tile_def

    w, h = zone.width, zone.height
    scale = 8  # pixels per cell
    img = Image.new("RGB", (w * scale, h * scale), (30, 30, 30))

    for r in range(h):
        for c in range(w):
            td = tile_def(zone.tiles[r][c])
            if td:
                color = td.color if hasattr(td, 'color') and td.color else (80, 80, 80)
            else:
                color = (80, 80, 80)
            ll = zone.light_levels[r][c] if zone.light_levels else 1.0
            rc = tuple(max(0, min(255, int(ch * ll))) for ch in color)
            for py in range(scale):
                for px in range(scale):
                    img.putpixel((c * scale + px, r * scale + py), rc)

    # Mark entities with red crosses
    for ent in zone.entities:
        ex, ey = int(ent.x * scale), int(ent.y * scale)
        for d in range(-2, 3):
            for xy in [(ex + d, ey), (ex, ey + d)]:
                if 0 <= xy[0] < w * scale and 0 <= xy[1] < h * scale:
                    img.putpixel(xy, (255, 50, 50))

    # Mark anchor with green circle
    if zone.anchor:
        ar, ac = zone.anchor
        ax, ay = int(ac * scale), int(ar * scale)
        for d in range(-3, 4):
            for xy in [(ax + d, ay), (ax, ay + d)]:
                if 0 <= xy[0] < w * scale and 0 <= xy[1] < h * scale:
                    img.putpixel(xy, (50, 255, 50))

    out_dir = Path("debug_renders")
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"{zone_name}_topdown.png"
    img.save(str(out_path))
    return out_path
