"""editor2/tools/light.py — Light level painting tool."""

from __future__ import annotations

from typing import Callable

from core.zones import Zone
from editor2.camera import Camera
from editor2.core import CommandBus, SetCellFieldCmd
from editor2.picking import pick_cell
from editor2.tools import Overlay, OverlayMode


class LightTool:
    """Paint light levels onto zone cells.

    - LMB: increase light level by step
    - Shift+LMB: decrease light level by step
    - Scroll: adjust step size
    - Middle-click: eyedropper (sample light level)
    """

    name = "light"
    wants_middle_click = True

    STEPS = [0.05, 0.1, 0.25, 0.5, 1.0]

    def __init__(self, zone: Zone, bus: CommandBus, cam: Camera) -> None:
        self._zone = zone
        self._bus = bus
        self._cam = cam
        self.on_changed: Callable[[], None] | None = None

        self.step_idx: int = 2  # default 0.25
        self.hover_hit = None
        self._dragging = False
        self.sampled_value: float | None = None

    @property
    def step(self) -> float:
        return self.STEPS[self.step_idx]

    def on_mouse_move(self, sx: float, sy: float,
                      vp_w: int, vp_h: int) -> None:
        hit = pick_cell(sx, sy, vp_w, vp_h, self._cam, self._zone)
        self.hover_hit = hit
        if self._dragging and hit:
            self._apply(hit.row, hit.col)
        if self.on_changed:
            self.on_changed()

    def on_mouse_press(self, sx: float, sy: float,
                       vp_w: int, vp_h: int, button: int) -> None:
        hit = pick_cell(sx, sy, vp_w, vp_h, self._cam, self._zone)
        if hit is None:
            return

        if button == 1:
            self._dragging = True
            self._apply(hit.row, hit.col)
        elif button == 3:
            # Middle-click eyedropper
            self._sample(hit.row, hit.col)

        if self.on_changed:
            self.on_changed()

    def on_mouse_release(self, sx: float, sy: float,
                         vp_w: int, vp_h: int, button: int) -> None:
        if button == 1:
            self._dragging = False

    def _apply(self, row: int, col: int) -> None:
        zone = self._zone
        old = zone.light_levels[row][col] if zone.light_levels else 1.0
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import Qt
        mods = QApplication.keyboardModifiers()
        if mods & Qt.KeyboardModifier.ShiftModifier:
            new = max(0.0, old - self.step)
        else:
            new = min(1.0, old + self.step)
        if new != old:
            self._bus.execute(SetCellFieldCmd(row, col, "light_levels", new))

    def _sample(self, row: int, col: int) -> None:
        """Eyedropper: store sampled light level for status display."""
        zone = self._zone
        ll = zone.light_levels[row][col] if zone.light_levels else 1.0
        self.sampled_value = ll
        if self.on_changed:
            self.on_changed()

    def cycle_step(self, direction: int = 1) -> None:
        self.step_idx = (self.step_idx + direction) % len(self.STEPS)
        if self.on_changed:
            self.on_changed()

    def overlays(self) -> list[Overlay]:
        ovls: list[Overlay] = []
        zone = self._zone

        # Zone-wide light level overlay — show all non-default cells
        if zone.light_levels:
            for r in range(zone.height):
                for c in range(zone.width):
                    ll = zone.light_levels[r][c]
                    if abs(ll - 1.0) < 0.01:
                        continue  # skip default (fully lit) cells
                    fh = zone.floor_heights[r][c] if zone.floor_heights else 0.0
                    y = fh + 0.015
                    # Dark cells → blue tint, bright cells → yellow tint
                    if ll < 1.0:
                        # Darkness overlay: darker blue the lower the light
                        darkness = 1.0 - ll
                        ovls.append(Overlay(
                            mode=OverlayMode.TRIS,
                            verts=[
                                (c, y, r), (c + 1, y, r), (c + 1, y, r + 1),
                                (c, y, r), (c + 1, y, r + 1), (c, y, r + 1),
                            ],
                            color=(0.0, 0.0, 0.3, darkness * 0.5),
                        ))

        # Hover cell highlight
        hit = self.hover_hit
        if hit is None:
            return ovls

        r, c = hit.row, hit.col
        fh = zone.floor_heights[r][c] if zone.floor_heights else 0.0
        y = fh + 0.01
        ovls.append(Overlay(
            mode=OverlayMode.LINES,
            verts=[
                (c, y, r), (c + 1, y, r),
                (c + 1, y, r), (c + 1, y, r + 1),
                (c + 1, y, r + 1), (c, y, r + 1),
                (c, y, r + 1), (c, y, r),
            ],
            color=(1.0, 0.9, 0.3, 0.6),
        ))

        # Show light level as a semi-transparent floor overlay
        ll = zone.light_levels[r][c] if zone.light_levels else 1.0
        brightness = ll * 0.8
        ovls.append(Overlay(
            mode=OverlayMode.TRIS,
            verts=[
                (c, y, r), (c + 1, y, r), (c + 1, y, r + 1),
                (c, y, r), (c + 1, y, r + 1), (c, y, r + 1),
            ],
            color=(brightness, brightness, brightness * 0.8, 0.3),
        ))

        return ovls
