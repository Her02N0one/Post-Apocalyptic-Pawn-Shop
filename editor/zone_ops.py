"""editor/zone_ops.py — Pure zone-mutation utilities.

This module provides standalone functions that mutate ``Zone`` grids.
They have **no editor dependency** — they take a ``Zone`` (or raw grids)
and positional arguments.  Command handlers import from here, which
avoids pulling in the full ``editor.view_3d`` package and its heavy
editor‐class import chain.

Domain constants that the mutation functions need (``DEFAULT_FLOOR``,
``SKY_HEIGHT``, ``LAYER_NONE``) are also defined here.  The canonical
copies in ``editor.view_3d.constants`` are kept in sync and may
eventually re‐export from this module.
"""

from __future__ import annotations

from core.tiles import tile_def


# ── Domain constants ──────────────────────────────────────────────

DEFAULT_FLOOR: float = 0.0
SKY_HEIGHT: float = 10.0        # sentinel: ceiling >= this = open sky
LAYER_NONE: float = -1000.0     # sentinel: no layer-2 data


# ── Cell-level operations ─────────────────────────────────────────

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

    # Layer 2
    if hasattr(zone, 'floor2_heights') and zone.floor2_heights and len(zone.floor2_heights) > r:
        zone.floor2_heights[r][c] = LAYER_NONE
    if hasattr(zone, 'ceil2_heights') and zone.ceil2_heights and len(zone.ceil2_heights) > r:
        zone.ceil2_heights[r][c] = LAYER_NONE
    if hasattr(zone, 'floor2_textures') and zone.floor2_textures and len(zone.floor2_textures) > r:
        zone.floor2_textures[r][c] = ""
    if hasattr(zone, 'ceil2_textures') and zone.ceil2_textures and len(zone.ceil2_textures) > r:
        zone.ceil2_textures[r][c] = ""
    if hasattr(zone, 'upper_wall_height2') and zone.upper_wall_height2 and len(zone.upper_wall_height2) > r:
        zone.upper_wall_height2[r][c] = 0.0


def clear_cell_textures(zone, r: int, c: int) -> None:
    """Clear all texture overrides on cell (r, c), keeping geometry.

    Covers L1 face/wall/floor/ceil textures, step textures,
    and L2 flat textures.
    """
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
    # Layer 2 flat textures
    f2t = getattr(zone, 'floor2_textures', None)
    if f2t and len(f2t) > r and len(f2t[r]) > c:
        f2t[r][c] = ""
    c2t = getattr(zone, 'ceil2_textures', None)
    if c2t and len(c2t) > r and len(c2t[r]) > c:
        c2t[r][c] = ""
