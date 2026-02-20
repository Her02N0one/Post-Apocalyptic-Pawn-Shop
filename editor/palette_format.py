"""editor/palette_format.py — Palette-pattern map representation.

Converts the editor's 2D tile grid into the compressed **Palette
Pattern**: a flat 1D grid of palette indices + a palette dictionary.

Old format (JSON, per-zone)::

    { "tiles": [[6, 1, 1, 6], [6, 5, 5, 6], ...],
      "entities": [...], "portals": [...] }

New palette format::

    { "palette": {
          0: {"tile_id": 6, "floor_z": 0.0, "ceiling_z": 1.0,
              "texture_key": "brick_wall"},
          1: {"tile_id": 1, "floor_z": 0.0, "ceiling_z": 0.0,
              "texture_key": "grass"},
          ...
      },
      "grid": [0, 1, 1, 0, 0, 3, 3, 0, ...],   # flat row-major
      "width": 4,
      "height": 2,
    }

This is a pure data-conversion module — no Pygame dependency.
"""

from __future__ import annotations

from typing import Any

from core.tiles import tile_def, TileDef


# ═════════════════════════════════════════════════════════════════════
#  Palette entry
# ═════════════════════════════════════════════════════════════════════

def _tile_to_palette_entry(tile_id: str) -> dict[str, Any]:
    """Build a palette dict entry for a built-in tile ID."""
    td: TileDef | None = tile_def(tile_id)
    if td is None:
        return {
            "tile_id": tile_id,
            "texture_key": "",
            "floor_z": 0.0,
            "ceiling_z": 0.0,
            "solid": False,
        }
    return {
        "tile_id": td.id,
        "texture_key": td.texture_key,
        "floor_z": 0.0,
        "ceiling_z": td.height_scale,
        "solid": td.solid,
        "wall": td.wall,
        "half_wall": td.half_wall,
        "name": td.name,
    }


# ═════════════════════════════════════════════════════════════════════
#  Convert 2D tile grid → palette + flat grid
# ═════════════════════════════════════════════════════════════════════

def tiles_to_palette(
    tiles: list[list[str]],
) -> tuple[dict[int, dict[str, Any]], list[int], int, int]:
    """Convert a 2D ``tiles[row][col]`` grid into palette format.

    Returns ``(palette, flat_grid, width, height)``.
    """
    if not tiles:
        return {}, [], 0, 0

    height = len(tiles)
    width = len(tiles[0]) if tiles else 0

    # Discover unique tile IDs and assign palette indices
    unique: dict[int, int] = {}
    for row in tiles:
        for tid in row:
            if tid not in unique:
                unique[tid] = len(unique)

    # Build palette dict (palette_index → entry)
    palette: dict[int, dict[str, Any]] = {}
    for tid, pidx in unique.items():
        palette[pidx] = _tile_to_palette_entry(tid)

    # Build flat grid (row-major palette indices)
    flat: list[int] = []
    for row in tiles:
        for tid in row:
            flat.append(unique[tid])

    return palette, flat, width, height


# ═════════════════════════════════════════════════════════════════════
#  Reverse: palette + flat grid → 2D tile grid
# ═════════════════════════════════════════════════════════════════════

def palette_to_tiles(
    palette: dict[int, dict[str, Any]],
    flat_grid: list[int],
    width: int,
    height: int,
) -> list[list[str]]:
    """Reconstruct the 2D tile grid from palette format.

    Each palette entry must have a ``tile_id`` key.
    """
    # Build reverse map: palette_index → tile_id
    idx_to_tid: dict[int, str] = {}
    for pidx, entry in palette.items():
        idx_to_tid[int(pidx)] = entry.get("tile_id", "void")

    tiles: list[list[str]] = []
    for r in range(height):
        row: list[str] = []
        base = r * width
        for c in range(width):
            flat_idx = base + c
            if flat_idx < len(flat_grid):
                pidx = flat_grid[flat_idx]
                row.append(idx_to_tid.get(pidx, "void"))
            else:
                row.append("void")
        tiles.append(row)
    return tiles


# ═════════════════════════════════════════════════════════════════════
#  Full zone dict conversion (JSON-compat ↔ palette)
# ═════════════════════════════════════════════════════════════════════

def zone_to_palette_dict(zone_data: dict[str, Any]) -> dict[str, Any]:
    """Convert a classic zone dict into palette-format zone dict.

    Preserves all non-tile fields (entities, portals, anchor, etc.).
    """
    tiles = zone_data.get("tiles", [])
    palette, flat_grid, w, h = tiles_to_palette(tiles)

    out = dict(zone_data)
    del out["tiles"]
    out.pop("width", None)
    out.pop("height", None)
    out["palette"] = palette
    out["grid"] = flat_grid
    out["width"] = w
    out["height"] = h
    return out


def palette_dict_to_zone(pal_data: dict[str, Any]) -> dict[str, Any]:
    """Convert a palette-format zone dict back to classic format."""
    palette = pal_data.get("palette", {})
    # Keys may be strings (from JSON/msgpack); normalise to int
    palette = {int(k): v for k, v in palette.items()}
    flat = pal_data.get("grid", [])
    w = int(pal_data.get("width", 0))
    h = int(pal_data.get("height", 0))

    tiles = palette_to_tiles(palette, flat, w, h)

    out = dict(pal_data)
    for drop in ("palette", "grid"):
        out.pop(drop, None)
    out["tiles"] = tiles
    out["width"] = w
    out["height"] = h
    return out
