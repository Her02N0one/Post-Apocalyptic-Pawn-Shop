"""editor/view_3d/cell_ops.py — Shared cell-level operations.

Provides helpers used by multiple tool mixins so that cell reset,
texture clearing, etc. are defined in exactly one place.
"""

from __future__ import annotations

from core.tiles import tile_def
from editor.view_3d.constants import DEFAULT_FLOOR, SKY_HEIGHT


def reset_cell(zone, r: int, c: int, open_tile: str) -> None:
    """Reset cell (r, c) to default state: flat ground, open sky, no textures.

    Parameters
    ----------
    zone : Zone
        The zone whose cell is being reset.
    r, c : int
        Row and column of the cell.
    open_tile : str
        Tile key to use for open (non-wall) cells.
    """
    td = tile_def(zone.tiles[r][c])
    if td and td.wall:
        zone.tiles[r][c] = open_tile

    zone.floor_heights[r][c] = DEFAULT_FLOOR
    zone.ceil_heights[r][c] = SKY_HEIGHT

    if zone.upper_wall_height and len(zone.upper_wall_height) > r:
        zone.upper_wall_height[r][c] = 0.0

    # Textures
    if zone.face_textures and len(zone.face_textures) > r:
        zone.face_textures[r][c] = ["", "", "", ""]
    if zone.wall_textures and len(zone.wall_textures) > r:
        zone.wall_textures[r][c] = ""
    if zone.floor_textures and len(zone.floor_textures) > r:
        zone.floor_textures[r][c] = ""
    if zone.ceil_textures and len(zone.ceil_textures) > r:
        zone.ceil_textures[r][c] = ""
    if zone.floor_step_textures and len(zone.floor_step_textures) > r:
        zone.floor_step_textures[r][c] = ["", "", "", ""]
    if zone.ceil_step_textures and len(zone.ceil_step_textures) > r:
        zone.ceil_step_textures[r][c] = ["", "", "", ""]

    # Segments
    if zone.wall_segments and len(zone.wall_segments) > r:
        zone.wall_segments[r][c] = [[], [], [], []]
    if zone.floor_step_segments and len(zone.floor_step_segments) > r:
        zone.floor_step_segments[r][c] = [[], [], [], []]
    if zone.ceil_step_segments and len(zone.ceil_step_segments) > r:
        zone.ceil_step_segments[r][c] = [[], [], [], []]
