"""editor2/tools/paint.py — Face texture paint tool."""

from __future__ import annotations

import collections
from dataclasses import replace
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from core.zones import Zone
from editor2.camera import Camera
from editor2.core import CommandBus, SetCellFieldCmd, SetFaceFieldCmd
from editor2.mesh import compute_cell_boxes, _get_face_tex_keys
from editor2.picking import CellHit, Face, pick_cell
from editor2.tools import Overlay, quad_to_tris

# Highlight colour: semi-transparent cyan
_HIGHLIGHT = (0.0, 1.0, 1.0, 0.25)


class PaintTool:
    """Paints face textures onto zone geometry."""

    def __init__(self, zone: Zone, bus: CommandBus, camera: Camera) -> None:
        self._zone = zone
        self._bus = bus
        self._camera = camera

        # Exposed state (read by panel)
        self._current_texture: str = "wall"
        self.hover_hit: CellHit | None = None
        self.on_changed: Callable[[], None] | None = None

        # Drag state
        self._dragging = False
        self._shift_mode = False
        self._last_drag_cell: tuple[int, int, str] | None = None

    @property
    def name(self) -> str:
        return "Paint"

    @property
    def current_texture(self) -> str:
        return self._current_texture

    @current_texture.setter
    def current_texture(self, value: str) -> None:
        self._current_texture = value
        if self.on_changed:
            self.on_changed()

    # ── Input events ──────────────────────────────────────────────

    def on_mouse_move(self, sx: float, sy: float,
                      vp_w: int, vp_h: int) -> None:
        self.hover_hit = pick_cell(sx, sy, vp_w, vp_h,
                                   self._camera, self._zone)
        # Drag-paint: apply texture continuously while dragging
        if self._dragging and self.hover_hit is not None:
            cell_key = (self.hover_hit.row, self.hover_hit.col,
                        self.hover_hit.part)
            if cell_key != self._last_drag_cell:
                self._last_drag_cell = cell_key
                if self._shift_mode:
                    self._paint_all_faces(self.hover_hit)
                    self._bus.zone_changed.emit()
                else:
                    self._paint(self.hover_hit)

    def on_mouse_press(self, sx: float, sy: float,
                       vp_w: int, vp_h: int, button: int) -> None:
        if button == 3:  # middle click — eyedropper
            hit = pick_cell(sx, sy, vp_w, vp_h, self._camera, self._zone)
            if hit is not None:
                tex = self._sample_face_texture(hit)
                if tex:
                    self.current_texture = tex
            return
        if button != 1:  # left click only
            return
        hit = pick_cell(sx, sy, vp_w, vp_h, self._camera, self._zone)
        if hit is None:
            return
        mods = QApplication.queryKeyboardModifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)

        if ctrl:
            self._flood_fill(hit)
            return

        self._shift_mode = shift
        self._bus.begin_batch("Paint all" if shift else "Paint drag",
                              defer_signal=shift)
        self._dragging = True
        self._last_drag_cell = (hit.row, hit.col, hit.part)
        if shift:
            self._paint_all_faces(hit)
            self._bus.zone_changed.emit()
        else:
            self._paint(hit)

    def on_mouse_release(self, sx: float, sy: float,
                         vp_w: int, vp_h: int, button: int) -> None:
        if button == 1 and self._dragging:
            self._dragging = False
            self._bus.commit_batch()

    # ── Painting logic ────────────────────────────────────────────

    def _paint(self, hit: CellHit) -> None:
        """Issue the appropriate texture command for the hit face."""
        tex = self._current_texture
        r, c = hit.row, hit.col
        face = hit.face

        if face.face_tex_idx is not None:
            # Side wall face — set per-face texture
            self._bus.execute(
                SetFaceFieldCmd(r, c, face.face_tex_idx, "face_textures", tex))
        elif hit.part == "floor" and face in (Face.TOP, Face.GROUND):
            self._bus.execute(SetCellFieldCmd(r, c, "floor_textures", tex))
        elif hit.part == "floor" and face == Face.BOT:
            self._bus.execute(SetCellFieldCmd(r, c, "floor_textures", tex))
        elif hit.part == "ceiling" and face in (Face.BOT, Face.TOP):
            self._bus.execute(SetCellFieldCmd(r, c, "ceil_textures", tex))
        elif hit.part == "wall":
            self._bus.execute(SetCellFieldCmd(r, c, "wall_textures", tex))
        else:
            # Side face on a floor/ceiling mass — treat as wall texture
            if face.face_tex_idx is not None:
                self._bus.execute(
                    SetFaceFieldCmd(r, c, face.face_tex_idx,
                                   "face_textures", tex))
            else:
                self._bus.execute(SetCellFieldCmd(r, c, "wall_textures", tex))

    def _paint_all_faces(self, hit: CellHit) -> None:
        """Paint every face of the hit block to the current texture."""
        tex = self._current_texture
        r, c = hit.row, hit.col
        # Side faces
        for face_idx in range(4):  # N=0, S=1, E=2, W=3
            self._bus.execute(
                SetFaceFieldCmd(r, c, face_idx, "face_textures", tex))
        # Horizontal faces depend on part type
        if hit.part == "floor":
            self._bus.execute(SetCellFieldCmd(r, c, "floor_textures", tex))
        elif hit.part == "ceiling":
            self._bus.execute(SetCellFieldCmd(r, c, "ceil_textures", tex))
        else:
            self._bus.execute(SetCellFieldCmd(r, c, "wall_textures", tex))

    # ── Flood fill ─────────────────────────────────────────────────

    def _flood_fill(self, hit: CellHit) -> None:
        """BFS flood fill from the hit cell, replacing matching textures."""
        tex = self._current_texture
        zone = self._zone

        # Determine fill mode and field based on what face was hit
        mode, field = self._classify_fill(hit)
        if field is None:
            return

        # Read the origin texture
        origin_tex = self._read_fill_tex(hit.row, hit.col, mode)
        if origin_tex == tex:
            return  # already the target texture

        # Reference height for spread
        ref_height = self._fill_height(hit.row, hit.col, mode)

        self._bus.begin_batch("Flood fill", defer_signal=True)

        visited: set[tuple[int, int]] = set()
        queue: collections.deque[tuple[int, int]] = collections.deque()
        queue.append((hit.row, hit.col))
        visited.add((hit.row, hit.col))

        while queue:
            r, c = queue.popleft()
            # Apply texture
            self._apply_fill_tex(r, c, mode, tex)
            # Spread to 4-connected neighbours
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nr, nc = r + dr, c + dc
                if (nr, nc) in visited:
                    continue
                if nr < 0 or nr >= zone.height or nc < 0 or nc >= zone.width:
                    continue
                # Check height match (±0.01 tolerance)
                nh = self._fill_height(nr, nc, mode)
                if abs(nh - ref_height) > 0.01:
                    continue
                # Check same source texture
                nt = self._read_fill_tex(nr, nc, mode)
                if nt != origin_tex:
                    continue
                visited.add((nr, nc))
                queue.append((nr, nc))

        self._bus.commit_batch()
        self._bus.zone_changed.emit()

    @staticmethod
    def _classify_fill(hit: CellHit) -> tuple[str, str | None]:
        """Return (fill_mode, zone_field) for the hit."""
        face = hit.face
        part = hit.part
        if part == "floor" and face in (Face.TOP, Face.GROUND, Face.BOT):
            return ("floor", "floor_textures")
        if part == "ceiling" and face in (Face.TOP, Face.BOT):
            return ("ceiling", "ceil_textures")
        if part == "wall":
            return ("wall", "wall_textures")
        # Side face on floor/ceiling slab — treat as wall
        return ("wall", "wall_textures")

    def _read_fill_tex(self, r: int, c: int, mode: str) -> str:
        zone = self._zone
        if mode == "floor":
            return (zone.floor_textures[r][c]
                    if zone.floor_textures else "")
        if mode == "ceiling":
            return (zone.ceil_textures[r][c]
                    if zone.ceil_textures else "")
        # wall
        return (zone.wall_textures[r][c]
                if zone.wall_textures else "")

    def _fill_height(self, r: int, c: int, mode: str) -> float:
        zone = self._zone
        if mode == "floor":
            return zone.floor_heights[r][c] if zone.floor_heights else 0.0
        if mode == "ceiling":
            return zone.ceil_heights[r][c] if zone.ceil_heights else 10.0
        # wall: use floor height as reference
        return zone.floor_heights[r][c] if zone.floor_heights else 0.0

    def _apply_fill_tex(self, r: int, c: int, mode: str, tex: str) -> None:
        if mode == "floor":
            self._bus.execute(SetCellFieldCmd(r, c, "floor_textures", tex))
        elif mode == "ceiling":
            self._bus.execute(SetCellFieldCmd(r, c, "ceil_textures", tex))
        else:
            self._bus.execute(SetCellFieldCmd(r, c, "wall_textures", tex))

    # ── Eyedropper ─────────────────────────────────────────────────

    # _get_face_tex_keys returns [top, bot, N, S, W, E]
    _FACE_TO_KEY_IDX = {
        Face.TOP: 0, Face.GROUND: 0,
        Face.BOT: 1,
        Face.NORTH: 2, Face.SOUTH: 3,
        Face.WEST: 4, Face.EAST: 5,
    }

    def _sample_face_texture(self, hit: CellHit) -> str | None:
        """Return the texture key currently rendered on the hit face."""
        keys = _get_face_tex_keys(self._zone, hit.row, hit.col, hit.part)
        idx = self._FACE_TO_KEY_IDX.get(hit.face)
        if idx is not None:
            return keys[idx]
        return None

    # ── Overlays ──────────────────────────────────────────────────

    @staticmethod
    def _is_shift_held() -> bool:
        return bool(QApplication.queryKeyboardModifiers()
                    & Qt.KeyboardModifier.ShiftModifier)

    _ALL_BOX_FACES = [Face.TOP, Face.BOT, Face.NORTH,
                      Face.SOUTH, Face.EAST, Face.WEST]

    def overlays(self) -> list[Overlay]:
        hit = self.hover_hit
        if hit is None:
            return []
        if self._is_shift_held():
            out: list[Overlay] = []
            for face in self._ALL_BOX_FACES:
                q = self._compute_face_quad(replace(hit, face=face))
                if q:
                    out.append(quad_to_tris(q, _HIGHLIGHT))
            return out
        quad = self._compute_face_quad(hit)
        if quad is None:
            return []
        return [quad_to_tris(quad, _HIGHLIGHT)]

    def _compute_face_quad(self, hit: CellHit
                           ) -> list[tuple[float, float, float]] | None:
        """Compute the 4 corners of the highlighted face."""
        c, r = hit.col, hit.row
        x0, z0 = float(c), float(r)
        x1, z1 = x0 + 1.0, z0 + 1.0

        # Get this cell's box extents for the hit part
        boxes = compute_cell_boxes(self._zone, r, c)
        y0, y1 = 0.0, 1.0
        for part, yb, yt in boxes:
            if part == hit.part:
                y0, y1 = yb, yt
                break

        f = hit.face
        # Epsilon push outward so overlay sits in front of the face
        E = 0.002

        if f == Face.TOP or f == Face.GROUND:
            y = y1 + E
            return [(x0, y, z0), (x1, y, z0), (x1, y, z1), (x0, y, z1)]
        elif f == Face.BOT:
            y = y0 - E
            return [(x0, y, z0), (x0, y, z1), (x1, y, z1), (x1, y, z0)]
        elif f == Face.NORTH:
            z = z0 - E
            return [(x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z)]
        elif f == Face.SOUTH:
            z = z1 + E
            return [(x1, y0, z), (x0, y0, z), (x0, y1, z), (x1, y1, z)]
        elif f == Face.WEST:
            x = x0 - E
            return [(x, y0, z1), (x, y0, z0), (x, y1, z0), (x, y1, z1)]
        elif f == Face.EAST:
            x = x1 + E
            return [(x, y0, z0), (x, y0, z1), (x, y1, z1), (x, y1, z0)]
        return None
