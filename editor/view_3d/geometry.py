"""editor/view_3d/geometry.py — Cell box computation for picking + rendering."""

from __future__ import annotations

from core.tiles import tile_def
from editor.view_3d.constants import SKY_HEIGHT


class GeometryMixin:
    """Shared geometry helpers used by both picking and rendering."""

    _SLAB = 0.04

    def _cell_boxes(self, r: int, c: int
                    ) -> list[tuple[str, float, float]]:
        """Visual boxes for a cell: list of (part, y_bot, y_top).

        For open cells the editor shows two solid masses:
          - **floor mass** -- ground (0) up to the floor surface.
          - **ceiling mass** -- ceiling surface up to the highest
            neighbouring ceiling (or upper-wall override).
        """
        zone = self.zone
        td = tile_def(zone.tiles[r][c])
        fh = zone.floor_heights[r][c] if zone.floor_heights else 0.0
        ch = zone.ceil_heights[r][c] if zone.ceil_heights else 1.0
        S = self._SLAB

        if td and td.wall:
            return [("wall", fh, max(ch, fh + 0.05))]

        # Geometry-solid: floor meets or exceeds ceiling
        if fh >= ch - 0.01:
            return [("wall", min(0.0, fh), max(fh + S, ch + S, 1.0))]

        result: list[tuple[str, float, float]] = []

        # ── Floor mass ────────────────────────────────────────────
        W2, H2 = zone.width, zone.height
        min_adj_fh = 0.0
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nr, nc = r + dr, c + dc
            if 0 <= nr < H2 and 0 <= nc < W2:
                nfh = zone.floor_heights[nr][nc] if zone.floor_heights else 0.0
                if nfh < min_adj_fh:
                    min_adj_fh = nfh
        floor_bot = min(0.0, fh - S, min_adj_fh - S)
        result.append(("floor", floor_bot, fh + S))

        # ── Ceiling mass ──────────────────────────────────────────
        if ch < SKY_HEIGHT:
            uwh = zone.upper_wall_height[r][c] if zone.upper_wall_height else 0.0
            if uwh > ch:
                ceil_top = min(uwh + S, 10.0)
            else:
                ceil_top = ch + S
            result.append(("ceiling", ch - S, ceil_top))

        return result

    def _ceil_mass_top(self, r: int, c: int) -> float:
        """Compute the top of the ceiling mass (auto or overridden)."""
        zone = self.zone
        ch = zone.ceil_heights[r][c]
        uwh = zone.upper_wall_height[r][c] if zone.upper_wall_height else 0.0
        S = self._SLAB
        if uwh > ch:
            return min(uwh + S, 10.0)
        return ch + S
