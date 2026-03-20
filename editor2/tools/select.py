"""editor2/tools/select.py — Rectangle and cell selection tool.

Click once to set first corner, click again to complete rectangle.
Ctrl+click toggles individual cells.  Shift+click does line selection.
Escape clears.

Once a selection exists, batch operations are available via the
inspector panel and keyboard shortcuts.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from core.tiles import tile_def
from core.zones import Zone
from editor2.camera import Camera
from editor2.core import CommandBus, SetCellFieldCmd, SetFaceFieldCmd, BatchCmd
from editor2.mesh import compute_cell_boxes, SKY_HEIGHT
from editor2.picking import CellHit, Face, pick_cell
from editor2.selection import SelectionState
from editor2.tools import Overlay, OverlayMode

# Overlay colours
_SEL_COLOR = (0.2, 0.6, 1.0, 0.3)    # selection fill
_SEL_BORDER = (0.3, 0.7, 1.0, 0.8)   # selection border
_ANCHOR = (1.0, 1.0, 0.0, 0.45)      # pending first-corner marker

DEFAULT_FLOOR = 0.0
DEFAULT_CEIL = 1.0
MIN_GAP = 0.12


class SelectTool:
    """Rectangle / cell selection with batch operations."""

    def __init__(self, zone: Zone, bus: CommandBus, camera: Camera,
                 selection: SelectionState) -> None:
        self._zone = zone
        self._bus = bus
        self._camera = camera
        self.selection = selection

        self.hover_hit: CellHit | None = None
        self.on_changed: Callable[[], None] | None = None

        # Cached overlays — rebuilt only when selection changes
        self._ovl_cache: list[Overlay] | None = None
        self._ovl_sel_snapshot: frozenset[tuple[int, int]] = frozenset()
        self._last_preview_cell: tuple[int, int] | None = None

    @property
    def name(self) -> str:
        return "Select"

    # ── Input events ──────────────────────────────────────────────

    def on_mouse_move(self, sx: float, sy: float,
                      vp_w: int, vp_h: int) -> None:
        self.hover_hit = pick_cell(sx, sy, vp_w, vp_h,
                                   self._camera, self._zone)
        # Live-preview rectangle while dragging from anchor
        if self.selection.rect_in_progress and self.hover_hit:
            cell = (self.hover_hit.row, self.hover_hit.col)
            if cell != self._last_preview_cell:
                self._last_preview_cell = cell
                self.selection.preview_rect(*cell)
                self._notify()

    def on_mouse_press(self, sx: float, sy: float,
                       vp_w: int, vp_h: int, button: int) -> None:
        if button != 1:
            return
        hit = pick_cell(sx, sy, vp_w, vp_h, self._camera, self._zone)
        if hit is None:
            return

        r, c = hit.row, hit.col
        app = QApplication.instance()
        mods = app.keyboardModifiers() if app else Qt.KeyboardModifier.NoModifier
        sel = self.selection

        # Ctrl+click: toggle individual cell
        if mods & Qt.KeyboardModifier.ControlModifier:
            sel.toggle_cell(r, c)
            self._notify()
            return

        # Shift+click: line selection from anchor
        if mods & Qt.KeyboardModifier.ShiftModifier:
            anchor = sel.anchor
            if anchor is not None:
                sel.select_line(anchor[0], anchor[1], r, c)
                self._notify()
                return

        # No pending rect → start one
        if not sel.rect_in_progress and not sel.has_cells():
            sel.begin_rect(r, c)
            self._last_preview_cell = (r, c)
            self._notify()
            return

        # Pending rect → finish it
        if sel.rect_in_progress:
            sel.finish_rect(r, c)
            self._last_preview_cell = None
            self._notify()
            return

        # Already have a selection → start fresh
        sel.clear()
        sel.begin_rect(r, c)
        self._last_preview_cell = (r, c)
        self._notify()

    def on_mouse_release(self, sx: float, sy: float,
                         vp_w: int, vp_h: int, button: int) -> None:
        pass

    # ── Batch operations (called from main.py key handler) ────────

    def fill_texture(self, texture: str) -> int:
        """Fill all selected cells' floor texture."""
        sel = self.selection
        if not sel.has_cells():
            return 0
        zone = self._zone
        cmds: list = []
        for r, c in sel.iter_cells():
            td = tile_def(zone.tiles[r][c])
            if td and td.wall:
                for fi in range(4):
                    old = zone.face_textures[r][c][fi] if zone.face_textures else ""
                    if old != texture:
                        cmds.append(SetFaceFieldCmd(r, c, fi, "face_textures", texture))
                old_wt = zone.wall_textures[r][c] if zone.wall_textures else ""
                if old_wt != texture:
                    cmds.append(SetCellFieldCmd(r, c, "wall_textures", texture))
            else:
                old_ft = zone.floor_textures[r][c] if zone.floor_textures else ""
                if old_ft != texture:
                    cmds.append(SetCellFieldCmd(r, c, "floor_textures", texture))
        if cmds:
            self._bus.execute(BatchCmd(cmds, f"Fill selection with '{texture}'"))
        return len(cmds)

    def clear_textures(self) -> int:
        """Clear all textures in selection."""
        sel = self.selection
        if not sel.has_cells():
            return 0
        zone = self._zone
        cmds: list = []
        for r, c in sel.iter_cells():
            if zone.face_textures:
                for fi in range(4):
                    if zone.face_textures[r][c][fi]:
                        cmds.append(SetFaceFieldCmd(r, c, fi, "face_textures", ""))
            if zone.wall_textures and zone.wall_textures[r][c]:
                cmds.append(SetCellFieldCmd(r, c, "wall_textures", ""))
            if zone.floor_textures and zone.floor_textures[r][c]:
                cmds.append(SetCellFieldCmd(r, c, "floor_textures", ""))
            if zone.ceil_textures and zone.ceil_textures[r][c]:
                cmds.append(SetCellFieldCmd(r, c, "ceil_textures", ""))
        if cmds:
            self._bus.execute(BatchCmd(cmds, "Clear selection textures"))
        return len(cmds)

    def reset_cells(self) -> int:
        """Reset all selected cells to defaults."""
        sel = self.selection
        if not sel.has_cells():
            return 0
        zone = self._zone
        cmds: list = []
        for r, c in sel.iter_cells():
            if zone.tiles[r][c] != "grass":
                cmds.append(SetCellFieldCmd(r, c, "tiles", "grass"))
            if zone.floor_heights and zone.floor_heights[r][c] != 0.0:
                cmds.append(SetCellFieldCmd(r, c, "floor_heights", 0.0))
            if zone.ceil_heights and zone.ceil_heights[r][c] != SKY_HEIGHT:
                cmds.append(SetCellFieldCmd(r, c, "ceil_heights", SKY_HEIGHT))
            if zone.floor_textures and zone.floor_textures[r][c]:
                cmds.append(SetCellFieldCmd(r, c, "floor_textures", ""))
            if zone.ceil_textures and zone.ceil_textures[r][c]:
                cmds.append(SetCellFieldCmd(r, c, "ceil_textures", ""))
            if zone.wall_textures and zone.wall_textures[r][c]:
                cmds.append(SetCellFieldCmd(r, c, "wall_textures", ""))
            if zone.face_textures:
                for fi in range(4):
                    if zone.face_textures[r][c][fi]:
                        cmds.append(SetFaceFieldCmd(r, c, fi, "face_textures", ""))
        if cmds:
            self._bus.execute(BatchCmd(cmds, "Reset selection"))
            self._ovl_cache = None
        return len(cmds)

    def raise_lower(self, direction: int, snap: float) -> None:
        """Raise or lower selected cells' floor or ceiling heights."""
        sel = self.selection
        if not sel.has_cells():
            return
        zone = self._zone
        cmds: list = []

        for r, c in sel.iter_cells():
            fh = zone.floor_heights[r][c] if zone.floor_heights else 0.0
            ch = zone.ceil_heights[r][c] if zone.ceil_heights else SKY_HEIGHT
            is_sky = ch >= SKY_HEIGHT

            if sel.ceiling_mode:
                if direction > 0:
                    if ch >= SKY_HEIGHT:
                        continue
                    new_ch = min(ch + snap, SKY_HEIGHT)
                else:
                    if ch >= SKY_HEIGHT:
                        new_ch = fh + DEFAULT_CEIL
                    else:
                        new_ch = max(ch - snap, fh + MIN_GAP)
                if abs(new_ch - ch) < 0.001:
                    continue
                cmds.append(SetCellFieldCmd(r, c, "ceil_heights", new_ch))
            else:
                if direction > 0:
                    max_fh = 10.0 if is_sky else min(10.0, ch - MIN_GAP)
                    new_fh = min(fh + snap, max_fh)
                else:
                    new_fh = max(-5.0, fh - snap)
                if abs(new_fh - fh) < 0.001:
                    continue
                cmds.append(SetCellFieldCmd(r, c, "floor_heights", new_fh))
                # Push ceiling when needed
                if not is_sky and new_fh > ch - MIN_GAP:
                    cmds.append(SetCellFieldCmd(r, c, "ceil_heights",
                                                new_fh + MIN_GAP))

        if cmds:
            label = "ceiling" if sel.ceiling_mode else "floor"
            verb = "Raise" if direction > 0 else "Lower"
            self._bus.execute(BatchCmd(cmds, f"{verb} selection {label}"))
            self._ovl_cache = None

    def flatten(self) -> None:
        """Flatten selected cells to the average height."""
        sel = self.selection
        if not sel.has_cells():
            return
        zone = self._zone
        field = "ceil_heights" if sel.ceiling_mode else "floor_heights"
        heights = [getattr(zone, field)[r][c] for r, c in sel.iter_cells()]
        avg = sum(heights) / len(heights)
        cmds = [SetCellFieldCmd(r, c, field, avg) for r, c in sel.iter_cells()
                if abs(getattr(zone, field)[r][c] - avg) > 0.001]
        if cmds:
            self._bus.execute(BatchCmd(cmds, f"Flatten selection {field}"))
            self._ovl_cache = None

    def make_wall(self) -> None:
        """Set all selected cells to wall tile."""
        self._set_tile("wall")

    def make_open(self) -> None:
        """Set all selected cells to grass (open)."""
        self._set_tile("grass")

    def _set_tile(self, tile: str) -> None:
        sel = self.selection
        if not sel.has_cells():
            return
        zone = self._zone
        cmds = [SetCellFieldCmd(r, c, "tiles", tile)
                for r, c in sel.iter_cells()
                if zone.tiles[r][c] != tile]
        if cmds:
            self._bus.execute(BatchCmd(cmds, f"Set selection to '{tile}'"))

    # ── Overlays ──────────────────────────────────────────────────

    def overlays(self) -> list[Overlay]:
        sel = self.selection
        current = frozenset(sel.cells)

        # Rebuild cache only when selection actually changed
        if self._ovl_cache is not None and current == self._ovl_sel_snapshot:
            # Still need to add hover/anchor overlays on top of cached
            ovls = list(self._ovl_cache)
            if sel.rect_in_progress and sel.anchor:
                ovls.insert(0, self._anchor_overlay(sel.anchor))
            return ovls

        self._ovl_sel_snapshot = current
        ovls: list[Overlay] = []

        # Pending anchor marker
        if sel.rect_in_progress and sel.anchor:
            ovls.append(self._anchor_overlay(sel.anchor))

        # Selected cells overlay
        if sel.has_cells():
            verts: list[tuple[float, float, float]] = []
            for r, c in sel.iter_cells():
                y = 0.06
                if self._zone.floor_heights:
                    y = self._zone.floor_heights[r][c] + 0.06
                verts.extend([
                    (c, y, r), (c + 1, y, r), (c + 1, y, r + 1),
                    (c, y, r), (c + 1, y, r + 1), (c, y, r + 1),
                ])
            ovls.append(Overlay(OverlayMode.TRIS, verts, _SEL_COLOR))

            # Border lines — only edges adjacent to non-selected cells
            border_verts: list[tuple[float, float, float]] = []
            cells_set = sel.cells
            for r, c in sel.iter_cells():
                y = 0.07
                if self._zone.floor_heights:
                    y = self._zone.floor_heights[r][c] + 0.07
                for dr, dc, p0, p1 in [
                    (-1, 0, (c, y, r), (c + 1, y, r)),
                    (1, 0, (c, y, r + 1), (c + 1, y, r + 1)),
                    (0, -1, (c, y, r), (c, y, r + 1)),
                    (0, 1, (c + 1, y, r), (c + 1, y, r + 1)),
                ]:
                    if (r + dr, c + dc) not in cells_set:
                        border_verts.extend([p0, p1])
            if border_verts:
                ovls.append(Overlay(OverlayMode.LINES, border_verts,
                                    _SEL_BORDER, line_width=2.5))

        self._ovl_cache = ovls
        return list(ovls)

    def _anchor_overlay(self, anchor: tuple[int, int]) -> Overlay:
        r, c = anchor
        y = 0.06
        if self._zone.floor_heights:
            y = self._zone.floor_heights[r][c] + 0.06
        v = [
            (c, y, r), (c + 1, y, r), (c + 1, y, r + 1),
            (c, y, r), (c + 1, y, r + 1), (c, y, r + 1),
        ]
        return Overlay(OverlayMode.TRIS, v, _ANCHOR)

        return ovls

    # ── Internal ──────────────────────────────────────────────────

    def _notify(self) -> None:
        self._ovl_cache = None  # invalidate overlay cache
        if self.on_changed:
            self.on_changed()
