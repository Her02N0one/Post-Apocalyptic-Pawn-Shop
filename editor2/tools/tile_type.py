"""editor2/tools/tile_type.py — Tile type assignment tool."""

from __future__ import annotations

from typing import Callable

from core.tiles import tile_def
from core.zones import Zone
from editor2.camera import Camera
from editor2.core import CommandBus, SetCellFieldCmd
from editor2.mesh import SKY_HEIGHT, compute_cell_boxes
from editor2.picking import CellHit, Face, pick_cell
from editor2.tools import Overlay, OverlayMode, quad_to_tris

# Overlay: orange = tile type highlight
_HIGHLIGHT = (1.0, 0.6, 0.0, 0.30)


class TileTypeTool:
    """Assigns tile IDs to zone cells.

    Left-click sets ``zone.tiles[r][c]`` to the currently selected tile ID.
    Drag-paint supported with same-cell skip.
    Middle-click eyedrops the tile ID from the hit cell.
    """

    def __init__(self, zone: Zone, bus: CommandBus, camera: Camera) -> None:
        self._zone = zone
        self._bus = bus
        self._camera = camera

        self._current_tile: str = "grass"
        self.hover_hit: CellHit | None = None
        self.on_changed: Callable[[], None] | None = None

        self._dragging = False
        self._last_drag_cell: tuple[int, int] | None = None

    @property
    def name(self) -> str:
        return "Tile Type"

    @property
    def current_tile(self) -> str:
        return self._current_tile

    @current_tile.setter
    def current_tile(self, value: str) -> None:
        self._current_tile = value
        if self.on_changed:
            self.on_changed()

    # ── Input events ──────────────────────────────────────────────

    def on_mouse_move(self, sx: float, sy: float,
                      vp_w: int, vp_h: int) -> None:
        self.hover_hit = pick_cell(sx, sy, vp_w, vp_h,
                                   self._camera, self._zone)
        if self._dragging and self.hover_hit is not None:
            cell_key = (self.hover_hit.row, self.hover_hit.col)
            if cell_key != self._last_drag_cell:
                self._last_drag_cell = cell_key
                self._set_tile(self.hover_hit)
        if self.on_changed:
            self.on_changed()

    def on_mouse_press(self, sx: float, sy: float,
                       vp_w: int, vp_h: int, button: int) -> None:
        if button == 3:  # middle click — eyedropper
            hit = pick_cell(sx, sy, vp_w, vp_h, self._camera, self._zone)
            if hit is not None:
                self.current_tile = self._zone.tiles[hit.row][hit.col]
            return
        if button != 1:
            return
        hit = pick_cell(sx, sy, vp_w, vp_h, self._camera, self._zone)
        if hit is None:
            return
        self._bus.begin_batch("Set tile type")
        self._dragging = True
        self._last_drag_cell = (hit.row, hit.col)
        self._set_tile(hit)

    def on_mouse_release(self, sx: float, sy: float,
                         vp_w: int, vp_h: int, button: int) -> None:
        if button == 1 and self._dragging:
            self._dragging = False
            self._bus.commit_batch()

    # ── Tile assignment ───────────────────────────────────────────

    def _set_tile(self, hit: CellHit) -> None:
        r, c = hit.row, hit.col
        old_id = self._zone.tiles[r][c]
        new_id = self._current_tile
        if old_id == new_id:
            return

        old_td = tile_def(old_id)
        new_td = tile_def(new_id)
        self._bus.execute(SetCellFieldCmd(r, c, "tiles", new_id))

        fh = self._zone.floor_heights[r][c] if self._zone.floor_heights else 0.0
        ch = self._zone.ceil_heights[r][c] if self._zone.ceil_heights else SKY_HEIGHT

        if new_td and new_td.wall:
            # Placing wall on sky cell → give it a real ceiling at the
            # tile's default height so sculpting can adjust it.
            if ch >= SKY_HEIGHT:
                self._bus.execute(SetCellFieldCmd(
                    r, c, "ceil_heights",
                    round(fh + new_td.height_scale, 4)))
        elif old_td and old_td.wall:
            # Converting wall → non-wall: restore sky ceiling so we
            # don't leave a phantom low ceiling on a floor tile.
            self._bus.execute(SetCellFieldCmd(
                r, c, "ceil_heights", SKY_HEIGHT))

    # ── Overlays ──────────────────────────────────────────────────

    def overlays(self) -> list[Overlay]:
        hit = self.hover_hit
        if hit is None:
            return []
        # Highlight all visible faces of the cell — tile type is per-cell
        c, r = hit.col, hit.row
        x0, z0 = float(c), float(r)
        x1, z1 = x0 + 1.0, z0 + 1.0

        boxes = compute_cell_boxes(self._zone, r, c)
        y0, y1 = 0.0, 1.0
        for part, yb, yt in boxes:
            if part == hit.part:
                y0, y1 = yb, yt
                break

        E = 0.002
        out: list[Overlay] = []
        faces = [
            [(x0, y1+E, z0), (x1, y1+E, z0), (x1, y1+E, z1), (x0, y1+E, z1)],  # top
            [(x0, y0-E, z0), (x0, y0-E, z1), (x1, y0-E, z1), (x1, y0-E, z0)],  # bot
            [(x0, y0, z0-E), (x1, y0, z0-E), (x1, y1, z0-E), (x0, y1, z0-E)],  # north
            [(x1, y0, z1+E), (x0, y0, z1+E), (x0, y1, z1+E), (x1, y1, z1+E)],  # south
            [(x0-E, y0, z1), (x0-E, y0, z0), (x0-E, y1, z0), (x0-E, y1, z1)],  # west
            [(x1+E, y0, z0), (x1+E, y0, z1), (x1+E, y1, z1), (x1+E, y1, z0)],  # east
        ]
        for quad in faces:
            out.append(quad_to_tris(quad, _HIGHLIGHT))
        return out
