"""editor2/tools/sculpt.py — Floor / ceiling height sculpting tool."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from core.zones import Zone
from core.tiles import tile_def
from editor2.camera import Camera
from editor2.core import CommandBus, SetCellFieldCmd
from editor2.mesh import SKY_HEIGHT
from editor2.picking import CellHit, Face, pick_cell
from editor2.tools import Overlay, OverlayMode, quad_to_tris
from editor2.tools._surface import compute_face_quad as _compute_face_quad

# Height limits (matching original)
FLOOR_MIN = -5.0
FLOOR_MAX = 10.0
CEIL_MIN = -5.0
DEFAULT_FLOOR = 0.0
DEFAULT_CEIL = 1.0
MIN_GAP = 0.12

# Overlay colours
_RAISE_COLOR = (0.2, 1.0, 0.2, 0.30)   # green = raise
_LOWER_COLOR = (1.0, 0.2, 0.2, 0.30)   # red   = lower
_NEUTRAL_COLOR = (1.0, 1.0, 0.0, 0.25)  # yellow = hover

# Snap presets matching the original editor
SNAP_PRESETS: tuple[float, ...] = (0.0625, 0.125, 0.25, 0.5, 1.0)
SNAP_LABELS: tuple[str, ...] = ("1/16", "1/8", "1/4", "1/2", "1")
DEFAULT_SNAP_IDX = 2  # 0.25


class SculptTool:
    """Raise/lower floor and ceiling heights by clicking faces.

    Left-click raises, Shift+left-click lowers.
    Clicking a floor top/ground face adjusts ``floor_heights``.
    Clicking a ceiling bottom face adjusts ``ceil_heights``.
    """

    def __init__(self, zone: Zone, bus: CommandBus, camera: Camera) -> None:
        self._zone = zone
        self._bus = bus
        self._camera = camera

        self.hover_hit: CellHit | None = None
        self.on_changed: Callable[[], None] | None = None

        self._snap_idx: int = DEFAULT_SNAP_IDX
        self._dragging = False
        self._lower_mode = False
        self._last_drag_cell: tuple[int, int, str] | None = None

    @property
    def name(self) -> str:
        return "Sculpt"

    @property
    def step(self) -> float:
        return SNAP_PRESETS[self._snap_idx]

    @property
    def snap_idx(self) -> int:
        return self._snap_idx

    @snap_idx.setter
    def snap_idx(self, value: int) -> None:
        self._snap_idx = value % len(SNAP_PRESETS)
        if self.on_changed:
            self.on_changed()

    def cycle_snap(self) -> None:
        """Advance to the next snap preset."""
        self.snap_idx = self._snap_idx + 1

    # ── Input events ──────────────────────────────────────────────

    def on_mouse_move(self, sx: float, sy: float,
                      vp_w: int, vp_h: int) -> None:
        self.hover_hit = pick_cell(sx, sy, vp_w, vp_h,
                                   self._camera, self._zone)
        if self._dragging and self.hover_hit is not None:
            cell_key = (self.hover_hit.row, self.hover_hit.col,
                        self.hover_hit.part)
            if cell_key != self._last_drag_cell:
                self._last_drag_cell = cell_key
                self._sculpt(self.hover_hit)

    def on_mouse_press(self, sx: float, sy: float,
                       vp_w: int, vp_h: int, button: int) -> None:
        if button != 1:
            return
        hit = pick_cell(sx, sy, vp_w, vp_h, self._camera, self._zone)
        if hit is None:
            return
        shift = bool(QApplication.queryKeyboardModifiers()
                     & Qt.KeyboardModifier.ShiftModifier)
        self._lower_mode = shift
        self._bus.begin_batch("Sculpt lower" if shift else "Sculpt raise")
        self._dragging = True
        self._last_drag_cell = (hit.row, hit.col, hit.part)
        self._sculpt(hit)

    def on_mouse_release(self, sx: float, sy: float,
                         vp_w: int, vp_h: int, button: int) -> None:
        if button == 1 and self._dragging:
            self._dragging = False
            self._bus.commit_batch()

    # ── Sculpting logic ───────────────────────────────────────────

    def _sculpt(self, hit: CellHit) -> None:
        """Raise or lower the appropriate height field."""
        r, c = hit.row, hit.col
        delta = -self.step if self._lower_mode else self.step
        zone = self._zone

        field = self._field_for_hit(hit)
        if field is None:
            return

        grid = getattr(zone, field)
        old_val = grid[r][c]
        fh = zone.floor_heights[r][c]
        ch = zone.ceil_heights[r][c]

        if field == "floor_heights":
            is_sky = ch >= SKY_HEIGHT
            max_fh = FLOOR_MAX if is_sky else min(FLOOR_MAX, ch - MIN_GAP)
            new_val = round(old_val + delta, 4)
            new_val = max(FLOOR_MIN, min(new_val, max_fh))
            # Push ceiling up if needed to preserve gap
            if not is_sky and new_val > ch - MIN_GAP:
                new_ch = round(new_val + MIN_GAP, 4)
                new_ch = min(new_ch, SKY_HEIGHT)
                self._bus.execute(SetCellFieldCmd(r, c, "ceil_heights", new_ch))
        elif field == "ceil_heights":
            min_ch = max(CEIL_MIN, fh + MIN_GAP)
            new_val = round(old_val + delta, 4)
            new_val = max(min_ch, min(new_val, SKY_HEIGHT))
        else:
            new_val = round(old_val + delta, 4)

        if new_val == old_val:
            return

        self._bus.execute(SetCellFieldCmd(r, c, field, new_val))

    # ── Cell operations (keyboard shortcuts) ──────────────────────

    def make_wall(self) -> None:
        """H: Convert aimed cell to wall (set wall tile, clear gap)."""
        hit = self.hover_hit
        if hit is None:
            return
        r, c = hit.row, hit.col
        zone = self._zone
        td = tile_def(zone.tiles[r][c])
        if td and td.tile_type.name == "WALL":
            return  # already a wall
        self._bus.begin_batch("Make wall")
        self._bus.execute(SetCellFieldCmd(r, c, "tiles", "wall"))
        self._bus.commit_batch()

    def make_open(self) -> None:
        """Shift+H: Convert aimed cell to open (set grass tile)."""
        hit = self.hover_hit
        if hit is None:
            return
        r, c = hit.row, hit.col
        self._bus.begin_batch("Make open")
        self._bus.execute(SetCellFieldCmd(r, c, "tiles", "grass"))
        # clear wall textures
        self._bus.execute(SetCellFieldCmd(r, c, "wall_textures", ""))
        self._bus.commit_batch()

    def toggle_ceiling(self) -> None:
        """T: Toggle ceiling on/off for aimed cell."""
        hit = self.hover_hit
        if hit is None:
            return
        r, c = hit.row, hit.col
        zone = self._zone
        ch = zone.ceil_heights[r][c]
        fh = zone.floor_heights[r][c]
        self._bus.begin_batch("Toggle ceiling")
        if ch >= SKY_HEIGHT:
            # Add ceiling
            new_ch = fh + DEFAULT_CEIL
            self._bus.execute(SetCellFieldCmd(r, c, "ceil_heights", new_ch))
        else:
            # Remove ceiling (set to sky)
            self._bus.execute(SetCellFieldCmd(r, c, "ceil_heights", SKY_HEIGHT))
        self._bus.commit_batch()

    def reset_height(self) -> None:
        """R: Reset floor or ceiling for aimed cell."""
        hit = self.hover_hit
        if hit is None:
            return
        r, c = hit.row, hit.col
        field = self._field_for_hit(hit)
        if field is None:
            return
        self._bus.begin_batch("Reset height")
        if field == "ceil_heights":
            self._bus.execute(SetCellFieldCmd(r, c, "ceil_heights",
                                             DEFAULT_FLOOR + DEFAULT_CEIL))
        else:
            self._bus.execute(SetCellFieldCmd(r, c, "floor_heights",
                                             DEFAULT_FLOOR))
        self._bus.commit_batch()

    def clear_cell(self) -> None:
        """Del: Reset aimed cell to defaults."""
        hit = self.hover_hit
        if hit is None:
            return
        r, c = hit.row, hit.col
        self._bus.begin_batch("Clear cell", defer_signal=True)
        self._bus.execute(SetCellFieldCmd(r, c, "tiles", "grass"))
        self._bus.execute(SetCellFieldCmd(r, c, "floor_heights", DEFAULT_FLOOR))
        self._bus.execute(SetCellFieldCmd(r, c, "ceil_heights", SKY_HEIGHT))
        self._bus.execute(SetCellFieldCmd(r, c, "floor_textures", ""))
        self._bus.execute(SetCellFieldCmd(r, c, "ceil_textures", ""))
        self._bus.execute(SetCellFieldCmd(r, c, "wall_textures", ""))
        if self._zone.upper_wall_height:
            self._bus.execute(SetCellFieldCmd(r, c, "upper_wall_height", 0.0))
        for fi in range(4):
            from editor2.core import SetFaceFieldCmd
            self._bus.execute(SetFaceFieldCmd(r, c, fi, "face_textures", ""))
        self._bus.commit_batch()
        # Note: commit_batch with defer_signal=True already emits zone_changed

    # ── Upper wall height ─────────────────────────────────────────

    _SLAB = 0.08
    _CEIL_MAX = 10.0

    def adjust_upper_wall_height(self, mode: str = "raise") -> None:
        """U: raise upper-wall.  Shift+U: lower.  Ctrl+U: reset.

        *mode* is one of 'raise', 'lower', 'reset'.
        """
        hit = self.hover_hit
        if hit is None:
            return
        r, c = hit.row, hit.col
        zone = self._zone
        td = tile_def(zone.tiles[r][c])
        if td and td.wall:
            return
        if not zone.upper_wall_height:
            return
        ch = zone.ceil_heights[r][c]
        uwh = zone.upper_wall_height[r][c]
        snap = self.step

        if mode == "reset":
            self._bus.execute(SetCellFieldCmd(r, c, "upper_wall_height", 0.0))
            return

        if mode == "lower":
            if uwh <= ch:
                return
            new = uwh - snap
            new_val = round(new, 4) if new > ch + 0.01 else 0.0
        else:
            # raise
            if uwh <= ch:
                uwh = ch + self._SLAB
            new = uwh + snap
            new_val = round(min(self._CEIL_MAX, new), 4)

        self._bus.execute(SetCellFieldCmd(r, c, "upper_wall_height", new_val))

    @staticmethod
    def _field_for_hit(hit: CellHit) -> str | None:
        """Determine which zone field to modify based on the hit."""
        face = hit.face
        part = hit.part

        if part == "floor":
            if face in (Face.TOP, Face.GROUND):
                return "floor_heights"
            if face == Face.BOT:
                return "floor_heights"
            # Side faces of a floor slab → still floor height
            return "floor_heights"

        if part == "ceiling":
            if face == Face.BOT:
                return "ceil_heights"
            if face == Face.TOP:
                return "ceil_heights"
            # Side faces of ceiling mass → ceiling height
            return "ceil_heights"

        if part == "wall":
            # Wall blocks: top face → ceiling, bottom → floor
            if face in (Face.TOP, Face.GROUND):
                return "ceil_heights"
            if face == Face.BOT:
                return "floor_heights"
            # Side faces of wall — default to floor
            return "floor_heights"

        return None

    # ── Overlays ──────────────────────────────────────────────────

    def overlays(self) -> list[Overlay]:
        hit = self.hover_hit
        if hit is None:
            return []

        field = self._field_for_hit(hit)
        if field is None:
            return []

        shift = bool(QApplication.queryKeyboardModifiers()
                     & Qt.KeyboardModifier.ShiftModifier)
        color = _LOWER_COLOR if shift else _RAISE_COLOR

        quad = _compute_face_quad(hit, self._zone)
        if quad is None:
            return []
        return [quad_to_tris(quad, color)]

    # _compute_face_quad extracted to editor2.tools._surface
