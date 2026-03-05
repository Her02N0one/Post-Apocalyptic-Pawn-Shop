"""editor/view_3d/geometry.py — Cell box computation for picking + rendering."""

from __future__ import annotations

from core.tiles import tile_def
from editor.view_3d.constants import SKY_HEIGHT


class GeometryMixin:
    """Shared geometry helpers used by both picking and rendering."""

    _SLAB = 0.04

    def _cell_boxes(self, r: int, c: int
                    ) -> list[tuple[str, float, float]]:
        """Visual boxes for a cell (cached per frame)."""
        cache = self._cell_box_cache
        key = (r, c)
        hit = cache.get(key)
        if hit is not None:
            return hit
        result = self._compute_cell_boxes(r, c)
        cache[key] = result
        return result

    def _compute_cell_boxes(self, r: int, c: int
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
            # Render a solid column from ground up to the max height.
            # When fh == ch (e.g. both 10.0) the (fh \u2192 ch) range is a
            # paper-thin invisible sliver; anchoring at 0 keeps it visible.
            return [("wall", min(0.0, fh), max(ch, fh + 0.05, 1.0))]

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
        # Extend upward to include visible step walls (mirrors how
        # the floor mass extends downward for floor steps).  The FP
        # renderer draws ceiling step walls between adjacent cells
        # with different ceiling heights; without this extension the
        # 3D editor shows only a paper-thin slab that cannot be
        # targeted for painting.
        if ch < SKY_HEIGHT:
            uwh = zone.upper_wall_height[r][c] if zone.upper_wall_height else 0.0
            if uwh > ch:
                ceil_top = min(uwh + S, 10.0)
            else:
                ceil_top = ch + S

            # Check adjacent ceilings — extend to show step walls
            max_adj_ch = ch
            sky_adjacent = False
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nr, nc = r + dr, c + dc
                if 0 <= nr < H2 and 0 <= nc < W2:
                    ntd = tile_def(zone.tiles[nr][nc])
                    if ntd and ntd.wall:
                        continue  # wall tiles have their own column
                    nch = zone.ceil_heights[nr][nc] if zone.ceil_heights else 1.0
                    if nch >= SKY_HEIGHT:
                        sky_adjacent = True
                    elif nch > max_adj_ch:
                        max_adj_ch = nch
                else:
                    # Zone boundary — treat as sky exposure
                    sky_adjacent = True

            if max_adj_ch > ch:
                ceil_top = max(ceil_top, max_adj_ch + S)
            if sky_adjacent:
                # Small extension so the face is targetable for painting
                # without creating a visually misleading tall wall.
                ceil_top = max(ceil_top, ch + 0.2)

            ceil_top = min(ceil_top, SKY_HEIGHT)
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

    def _layer_cell_boxes(self, r: int, c: int
                          ) -> list[tuple[str, float, float]]:
        """Return cell boxes filtered by active layer + isolate state.

        When ``active_layer == 2``, prefers Layer 2 floor/ceil slabs.
        When ``isolate_layer`` is True, only returns boxes for the active layer.
        """
        active = getattr(self, 'active_layer', 1)
        isolate = getattr(self, 'isolate_layer', False)

        # Always include L1 unless isolating to L2
        l1_boxes: list[tuple[str, float, float]] = []
        if not (isolate and active == 2):
            l1_boxes = self._cell_boxes(r, c)

        # Add L2 boxes if the layer data exists
        l2_boxes: list[tuple[str, float, float]] = []
        LAYER_NONE = -1000.0
        zone = self.zone
        f2 = getattr(zone, 'floor2_heights', None)
        c2 = getattr(zone, 'ceil2_heights', None)
        if f2 and c2 and len(f2) > r and len(c2) > r:
            f2v = f2[r][c]
            c2v = c2[r][c]
            S = self._SLAB
            has_f2 = f2v > LAYER_NONE + 1.0
            has_c2 = c2v > LAYER_NONE + 1.0
            if has_f2:
                l2_boxes.append(("floor2", f2v - S, f2v + S))
            if has_c2:
                l2_boxes.append(("ceiling2", c2v - S, c2v + S))
            if has_f2 and has_c2 and c2v > f2v:
                pass  # The gap between is open space, no box

        if isolate:
            return l2_boxes if active == 2 else l1_boxes

        # When editing L2, put L2 boxes first (higher hit priority)
        if active == 2:
            return l2_boxes + l1_boxes
        return l1_boxes + l2_boxes
