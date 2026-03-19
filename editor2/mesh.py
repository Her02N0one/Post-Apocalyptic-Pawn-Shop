"""editor2/mesh.py — Zone mesh builder: cell geometry → GL vertex data."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from core.zones import Zone
from core.tiles import tile_def
from core.tiles.registry import TILE_COLORS

if TYPE_CHECKING:
    from editor2.atlas import TileAtlas

# ── Constants ────────────────────────────────────────────────────

# Face brightness multipliers matching the old editor:
# Order: top(+Y), bottom(-Y), north(-Z), south(+Z), west(-X), east(+X)
_FACE_BRIGHTNESS = [1.00, 0.55, 0.65, 0.80, 0.50, 0.70]

COL_DEFAULT = (200, 80, 180)

_SLAB = 0.04
SKY_HEIGHT = 10.0

# Box faces: (triangle_indices, outward_normal, brightness_index, uv_per_corner)
# UV per corner maps each of the 8 box corners to (u, v) for that face.
# Corners:  0=(x0,y0,z0) 1=(x1,y0,z0) 2=(x1,y0,z1) 3=(x0,y0,z1)
#           4=(x0,y1,z0) 5=(x1,y1,z0) 6=(x1,y1,z1) 7=(x0,y1,z1)
_BOX_FACES = [
    # top (+Y):    project onto XZ plane, y=y1
    ([4, 5, 6, 4, 6, 7], ( 0,  1,  0), 0,
     {4: (0, 0), 5: (1, 0), 6: (1, 1), 7: (0, 1)}),
    # bottom (-Y): project onto XZ plane, y=y0
    ([0, 3, 2, 0, 2, 1], ( 0, -1,  0), 1,
     {0: (0, 0), 3: (0, 1), 2: (1, 1), 1: (1, 0)}),
    # north (-Z):  project onto XY plane, z=z0
    ([0, 1, 5, 0, 5, 4], ( 0,  0, -1), 2,
     {0: (0, 0), 1: (1, 0), 5: (1, 1), 4: (0, 1)}),
    # south (+Z):  project onto XY plane, z=z1
    ([2, 3, 7, 2, 7, 6], ( 0,  0,  1), 3,
     {2: (0, 0), 3: (1, 0), 7: (1, 1), 6: (0, 1)}),
    # west (-X):   project onto ZY plane, x=x0
    ([0, 4, 7, 0, 7, 3], (-1,  0,  0), 4,
     {0: (0, 0), 4: (0, 1), 7: (1, 1), 3: (1, 0)}),
    # east (+X):   project onto ZY plane, x=x1
    ([1, 2, 6, 1, 6, 5], ( 1,  0,  0), 5,
     {1: (0, 0), 2: (1, 0), 6: (1, 1), 5: (0, 1)}),
]

# ── Colour Helpers ───────────────────────────────────────────────


def _tile_color(tex_key: str) -> tuple[int, int, int]:
    c = TILE_COLORS.get(tex_key)
    if c:
        return (min(255, c[0] + 60),
                min(255, c[1] + 60),
                min(255, c[2] + 60))
    return COL_DEFAULT


def _darken(color: tuple[int, int, int], factor: float
            ) -> tuple[int, int, int]:
    return (int(color[0] * factor),
            int(color[1] * factor),
            int(color[2] * factor))


def _resolve_floor_tex(zone: Zone, r: int, c: int) -> str:
    if zone.floor_textures and zone.floor_textures[r][c]:
        return zone.floor_textures[r][c]
    return zone.tiles[r][c]


def _resolve_ceil_tex(zone: Zone, r: int, c: int) -> str:
    if zone.ceil_textures and zone.ceil_textures[r][c]:
        return zone.ceil_textures[r][c]
    return "concrete"


def _cell_color(zone: Zone, r: int, c: int, part: str) -> tuple[int, int, int]:
    if part == "wall":
        if zone.face_textures and zone.face_textures[r][c]:
            ft = zone.face_textures[r][c]
            tex = ft[0] or ft[1] or ft[2] or ft[3]
            if tex:
                return _tile_color(tex)
        if zone.wall_textures and zone.wall_textures[r][c]:
            return _tile_color(zone.wall_textures[r][c])
        return _tile_color(zone.tiles[r][c])
    elif part == "floor":
        return _tile_color(_resolve_floor_tex(zone, r, c))
    elif part == "ceiling":
        return _tile_color(_resolve_ceil_tex(zone, r, c))
    return COL_DEFAULT


# ── Geometry ─────────────────────────────────────────────────────


def compute_cell_boxes(zone: Zone, r: int, c: int
                       ) -> list[tuple[str, float, float]]:
    """Compute visual boxes for a cell: list of (part, y_bot, y_top)."""
    td = tile_def(zone.tiles[r][c])
    fh = zone.floor_heights[r][c] if zone.floor_heights else 0.0
    ch = zone.ceil_heights[r][c] if zone.ceil_heights else 1.0

    if td and td.wall:
        # Use ceil_heights as wall top (sculpt-adjustable).
        # Fall back to height_scale default only for sky/outdoor cells.
        if ch < SKY_HEIGHT:
            wall_top = ch
        else:
            wall_top = fh + td.height_scale
        return [("wall", min(0.0, fh), max(wall_top, fh + 0.05))]

    if fh >= ch - 0.01:
        return [("wall", min(0.0, fh), max(fh + _SLAB, ch + _SLAB))]

    result: list[tuple[str, float, float]] = []
    W, H = zone.width, zone.height

    # Floor mass
    min_adj_fh = 0.0
    for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        nr, nc = r + dr, c + dc
        if 0 <= nr < H and 0 <= nc < W:
            nfh = zone.floor_heights[nr][nc] if zone.floor_heights else 0.0
            if nfh < min_adj_fh:
                min_adj_fh = nfh
    floor_bot = min(0.0, fh - _SLAB, min_adj_fh - _SLAB)
    result.append(("floor", floor_bot, fh + _SLAB))

    # Ceiling mass
    if ch < SKY_HEIGHT:
        uwh_val = 0.0
        if zone.upper_wall_height and len(zone.upper_wall_height) > r:
            uwh_val = zone.upper_wall_height[r][c]
        if uwh_val > ch:
            ceil_top = min(uwh_val + _SLAB, 10.0)
        else:
            ceil_top = ch + _SLAB

        max_adj_ch = ch
        sky_adj = False
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nr, nc = r + dr, c + dc
            if 0 <= nr < H and 0 <= nc < W:
                ntd = tile_def(zone.tiles[nr][nc])
                if ntd and ntd.wall:
                    continue
                nch = zone.ceil_heights[nr][nc] if zone.ceil_heights else 1.0
                if nch >= SKY_HEIGHT:
                    sky_adj = True
                elif nch > max_adj_ch:
                    max_adj_ch = nch
            else:
                sky_adj = True

        if max_adj_ch > ch:
            ceil_top = max(ceil_top, max_adj_ch + _SLAB)
        if sky_adj:
            ceil_top = max(ceil_top, ch + 0.2)
        ceil_top = min(ceil_top, SKY_HEIGHT)
        result.append(("ceiling", ch - _SLAB, ceil_top))

    return result


def _get_face_colors(zone: Zone, r: int, c: int, part: str
                     ) -> list[tuple[int, int, int]]:
    """Return 6 per-face colours in face order (top, bot, N, S, W, E)."""
    base = _cell_color(zone, r, c, part)
    cols = [base] * 6

    td = tile_def(zone.tiles[r][c])
    is_wall = td is not None and td.wall

    if part == "floor":
        ftex = _resolve_floor_tex(zone, r, c)
        cols[0] = _tile_color(ftex)
        cols[1] = _darken(_tile_color(ftex), 0.65)
    elif part == "ceiling":
        ctex = _resolve_ceil_tex(zone, r, c)
        cols[0] = _darken(_tile_color(ctex), 0.65)
        cols[1] = _tile_color(ctex)
    elif part == "wall" and not is_wall:
        pass

    # Per-face wall textures for side faces
    if zone.face_textures and zone.face_textures[r][c]:
        ft = zone.face_textures[r][c]
        # face_textures[r][c] = [N, S, E, W]
        if ft[0]:
            cols[2] = _tile_color(ft[0])  # north
        if ft[1]:
            cols[3] = _tile_color(ft[1])  # south
        if ft[2]:
            cols[5] = _tile_color(ft[2])  # east
        if ft[3]:
            cols[4] = _tile_color(ft[3])  # west

    return cols


def _get_face_tex_keys(zone: Zone, r: int, c: int, part: str
                       ) -> list[str]:
    """Return 6 texture keys in face order (top, bot, N, S, W, E)."""
    # Default: main tile key for every face
    base_key = zone.tiles[r][c]

    if part == "floor":
        ftex = _resolve_floor_tex(zone, r, c)
        keys = [ftex, ftex, base_key, base_key, base_key, base_key]
    elif part == "ceiling":
        ctex = _resolve_ceil_tex(zone, r, c)
        keys = [ctex, ctex, base_key, base_key, base_key, base_key]
    else:
        # wall or solid-fill part
        wt = base_key
        if zone.wall_textures and zone.wall_textures[r][c]:
            wt = zone.wall_textures[r][c]
        keys = [wt, wt, wt, wt, wt, wt]

    # Per-face wall textures override side faces
    if zone.face_textures and zone.face_textures[r][c]:
        ft = zone.face_textures[r][c]
        # face_textures[r][c] = [N, S, E, W]
        if ft[0]:
            keys[2] = ft[0]
        if ft[1]:
            keys[3] = ft[1]
        if ft[2]:
            keys[5] = ft[2]
        if ft[3]:
            keys[4] = ft[3]

    return keys


# ── Mesh Builder ─────────────────────────────────────────────────


def build_zone_mesh(zone: Zone, atlas: TileAtlas,
                    *,
                    show_walls: bool = True,
                    show_floors: bool = True,
                    show_ceilings: bool = True,
                    ) -> tuple[np.ndarray, int]:
    """Build vertex data for the zone: interleaved (pos3, color3, uv2, texLayer1).

    Returns (vertex_data, vertex_count).
    """
    verts: list[float] = []
    W, H = zone.width, zone.height

    for r in range(H):
        for c in range(W):
            for part, yb, yt in compute_cell_boxes(zone, r, c):
                if part == "wall" and not show_walls:
                    continue
                if part == "floor" and not show_floors:
                    continue
                if part == "ceiling" and not show_ceilings:
                    continue
                x0, z0 = float(c), float(r)
                x1, z1 = c + 1.0, r + 1.0
                y0, y1 = yb, yt
                box_h = y1 - y0

                corners = [
                    (x0, y0, z0), (x1, y0, z0),
                    (x1, y0, z1), (x0, y0, z1),
                    (x0, y1, z0), (x1, y1, z0),
                    (x1, y1, z1), (x0, y1, z1),
                ]

                face_keys = _get_face_tex_keys(zone, r, c, part)

                for fi, (tri_indices, _normal, bright_idx, uv_map) in enumerate(_BOX_FACES):
                    brightness = _FACE_BRIGHTNESS[bright_idx]

                    tex_layer = float(atlas.layer(face_keys[bright_idx]))

                    # Tile UVs vertically on side faces so textures
                    # repeat instead of stretching over tall surfaces.
                    v_scale = box_h if fi >= 2 else 1.0

                    for vi in tri_indices:
                        px, py, pz = corners[vi]
                        u, v = uv_map[vi]
                        verts.extend([px, py, pz,
                                      brightness, brightness, brightness,
                                      u, v * v_scale, tex_layer])

    data = np.array(verts, dtype=np.float32)
    count = len(verts) // 9
    return data, count
