"""editor/view_3d/tools_layer2.py — Secondary floor/ceiling layer editing for Zone3DEditor.

Edit the second layer of floor/ceiling surfaces (catwalks, bridges, pits).

Actions (when tool == "layer2"):
  LMB          Raise secondary floor at aimed cell (creates it if absent)
  RMB          Lower secondary floor at aimed cell
  Shift+LMB    Raise secondary ceiling
  Shift+RMB    Lower secondary ceiling
  Ctrl+LMB     Remove secondary layer entirely (reset to sentinel)
  X            Toggle floor2 ↔ ceil2 target
  Scroll       Cycle texture palette (paints on secondary layer)
"""

from __future__ import annotations

from editor.view_3d.constants import (
    FLOOR_MIN, FLOOR_MAX, CEIL_MIN, CEIL_MAX, SKY_HEIGHT,
)

LAYER_NONE = -1000.0


class Layer2Mixin:
    """Secondary (layer 2) floor/ceiling surface editing."""

    _layer2_target: str = "floor2"   # "floor2" or "ceil2"

    def _layer2_ensure_grids(self) -> None:
        """Ensure floor2/ceil2 height and texture grids are correctly sized."""
        z = self.zone
        H, W = z.height, z.width
        for attr, default in [
            ("floor2_heights", LAYER_NONE),
            ("ceil2_heights", LAYER_NONE),
        ]:
            g = getattr(z, attr)
            if not g or len(g) != H:
                g = [[default] * W for _ in range(H)]
                setattr(z, attr, g)
            for r in range(H):
                if len(g[r]) != W:
                    g[r] = [default] * W
        for attr in ("floor2_textures", "ceil2_textures"):
            g = getattr(z, attr)
            if not g or len(g) != H:
                g = [[""] * W for _ in range(H)]
                setattr(z, attr, g)
            for r in range(H):
                if len(g[r]) != W:
                    g[r] = [""] * W

    def _layer2_raise(self, shift: bool = False, ctrl: bool = False) -> None:
        """LMB: raise secondary floor (or ceiling if shift).  Ctrl = remove."""
        hit = self.aimed
        if not hit:
            return
        self._layer2_ensure_grids()
        zone = self.zone
        r, c = hit.row, hit.col

        if ctrl:
            # Remove secondary layer
            self._push_undo()
            zone.floor2_heights[r][c] = LAYER_NONE
            zone.ceil2_heights[r][c] = LAYER_NONE
            zone.floor2_textures[r][c] = ""
            zone.ceil2_textures[r][c] = ""
            self.dirty = True
            return

        if shift or self._layer2_target == "ceil2":
            # Raise secondary ceiling
            old = zone.ceil2_heights[r][c]
            if old <= LAYER_NONE + 1.0:
                # Create at primary ceiling height
                old = zone.ceil_heights[r][c] if zone.ceil_heights else 1.0
            new = min(CEIL_MAX, old + self.snap_y)
            if abs(new - old) < 0.001:
                return
            self._push_undo()
            zone.ceil2_heights[r][c] = round(new, 3)
            # Auto-set texture if empty
            if not zone.ceil2_textures[r][c]:
                zone.ceil2_textures[r][c] = self.current_texture
            self.dirty = True
        else:
            # Raise secondary floor
            old = zone.floor2_heights[r][c]
            if old <= LAYER_NONE + 1.0:
                # Create at primary floor height + offset
                base = zone.floor_heights[r][c] if zone.floor_heights else 0.0
                old = base + 0.5
            new = min(FLOOR_MAX, old + self.snap_y)
            if abs(new - old) < 0.001:
                return
            self._push_undo()
            zone.floor2_heights[r][c] = round(new, 3)
            if not zone.floor2_textures[r][c]:
                zone.floor2_textures[r][c] = self.current_texture
            self.dirty = True

    def _layer2_lower(self, shift: bool = False) -> None:
        """RMB: lower secondary floor (or ceiling if shift)."""
        hit = self.aimed
        if not hit:
            return
        self._layer2_ensure_grids()
        zone = self.zone
        r, c = hit.row, hit.col

        if shift or self._layer2_target == "ceil2":
            old = zone.ceil2_heights[r][c]
            if old <= LAYER_NONE + 1.0:
                return  # no secondary ceiling to lower
            new = max(CEIL_MIN, old - self.snap_y)
            self._push_undo()
            zone.ceil2_heights[r][c] = round(new, 3)
            self.dirty = True
        else:
            old = zone.floor2_heights[r][c]
            if old <= LAYER_NONE + 1.0:
                return
            new = max(FLOOR_MIN, old - self.snap_y)
            self._push_undo()
            zone.floor2_heights[r][c] = round(new, 3)
            self.dirty = True

    def _layer2_paint(self) -> None:
        """Apply current_texture to the aimed cell's secondary layer."""
        hit = self.aimed
        if not hit:
            return
        self._layer2_ensure_grids()
        zone = self.zone
        r, c = hit.row, hit.col
        if self._layer2_target == "ceil2":
            if zone.ceil2_heights[r][c] <= LAYER_NONE + 1.0:
                return
            old = zone.ceil2_textures[r][c]
            if old == self.current_texture:
                return
            self._push_undo()
            zone.ceil2_textures[r][c] = self.current_texture
        else:
            if zone.floor2_heights[r][c] <= LAYER_NONE + 1.0:
                return
            old = zone.floor2_textures[r][c]
            if old == self.current_texture:
                return
            self._push_undo()
            zone.floor2_textures[r][c] = self.current_texture
        self.dirty = True

    def _layer2_toggle_target(self) -> None:
        """X key: toggle floor2 ↔ ceil2."""
        self._layer2_target = "ceil2" if self._layer2_target == "floor2" else "floor2"
