"""editor/view_3d/tools_fill.py — Flood-fill tool for Zone3DEditor.

Fills connected surfaces with the current texture, stopping at:
  - Height changes (floor or ceiling discontinuity)
  - Wall cells (tile type boundary)
  - Segment boundaries on shared faces
  - Grid edges

LMB  = flood-fill with current texture
RMB  = flood-clear (reset all filled cells to default texture)
"""

from __future__ import annotations

from collections import deque

from core.tiles import tile_def
from editor.view_3d.constants import FACE_IDX


class FillMixin:
    """Flood-fill tool — paint connected same-height surfaces."""

    _FACE_IDX_FILL = FACE_IDX

    def _fill(self) -> bool:
        """LMB: flood-fill current texture across connected faces."""
        hit = self.aimed
        if not hit or hit.face == "ground":
            return False
        return self._flood_fill(hit, self.current_texture)

    def _fill_clear(self) -> bool:
        """RMB: flood-clear (reset to default texture)."""
        hit = self.aimed
        if not hit or hit.face == "ground":
            return False
        return self._flood_fill(hit, "")

    def _flood_fill(self, hit, tex: str) -> bool:
        """BFS flood fill starting from the aimed cell.

        Fills the same surface type (floor-top, ceil-top, wall-face, etc.)
        across 4-connected neighbours, stopping at height discontinuities,
        wall boundaries, and segment boundaries.
        """
        zone = self.zone
        r0, c0 = hit.row, hit.col
        part = hit.part
        face = hit.face
        W, H = zone.width, zone.height

        self._ensure_face_textures()

        # Determine what we're filling and how to read/write textures
        fill_mode = self._classify_fill_target(r0, c0, part, face)
        if fill_mode is None:
            return False

        mode, ref_height = fill_mode

        # Get the current texture at origin to know what we're replacing
        origin_tex = self._read_fill_tex(r0, c0, mode, face)

        # Don't fill if it's already the target texture
        if origin_tex == tex:
            return False

        self._push_undo()

        # BFS flood fill
        visited: set[tuple[int, int]] = set()
        queue: deque[tuple[int, int]] = deque()
        queue.append((r0, c0))
        visited.add((r0, c0))
        filled = 0

        while queue:
            r, c = queue.popleft()

            # Write texture
            self._write_fill_tex(r, c, mode, face, tex)
            filled += 1

            # Spread to 4 neighbors
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nr, nc = r + dr, c + dc
                if (nr, nc) in visited:
                    continue
                if nr < 0 or nr >= H or nc < 0 or nc >= W:
                    continue

                # Check if neighbor qualifies
                if not self._fill_can_spread(r, c, nr, nc, mode, ref_height, face, origin_tex):
                    continue

                visited.add((nr, nc))
                queue.append((nr, nc))

        if filled > 0:
            self.dirty = True
        return filled > 0

    def _classify_fill_target(self, r: int, c: int, part: str, face: str
                              ) -> tuple[str, float] | None:
        """Determine fill mode and reference height.

        Returns (mode, ref_height) or None if not fillable.
        mode is one of: "floor_top", "ceil_top", "wall_face", "floor_step", "ceil_step",
                        "floor2_top", "ceil2_top", "floor2_step", "ceil2_step"
        """
        zone = self.zone
        td = tile_def(zone.tiles[r][c])
        is_wall = td and td.wall

        if face == "top":
            if part == "floor":
                return ("floor_top", zone.floor_heights[r][c])
            elif part == "floor2":
                f2h = getattr(zone, 'floor2_heights', None)
                if f2h:
                    return ("floor2_top", f2h[r][c])
            elif part in ("wall", "ceiling"):
                return ("ceil_top", zone.ceil_heights[r][c])
            elif part == "ceiling2":
                c2h = getattr(zone, 'ceil2_heights', None)
                if c2h:
                    return ("ceil2_top", c2h[r][c])

        if face in self._FACE_IDX_FILL:
            if is_wall:
                return ("wall_face", zone.floor_heights[r][c])
            elif part == "floor":
                return ("floor_step", zone.floor_heights[r][c])
            elif part == "ceiling":
                return ("ceil_step", zone.ceil_heights[r][c])
            elif part == "floor2":
                f2h = getattr(zone, 'floor2_heights', None)
                if f2h:
                    return ("floor2_step", f2h[r][c])
            elif part == "ceiling2":
                c2h = getattr(zone, 'ceil2_heights', None)
                if c2h:
                    return ("ceil2_step", c2h[r][c])

        if face == "bot":
            if part == "floor":
                return ("floor_top", zone.floor_heights[r][c])
            elif part == "ceiling":
                return ("ceil_top", zone.ceil_heights[r][c])
            elif part == "floor2":
                f2h = getattr(zone, 'floor2_heights', None)
                if f2h:
                    return ("floor2_top", f2h[r][c])
            elif part == "ceiling2":
                c2h = getattr(zone, 'ceil2_heights', None)
                if c2h:
                    return ("ceil2_top", c2h[r][c])

        return None

    def _read_fill_tex(self, r: int, c: int, mode: str, face: str) -> str:
        """Read the current texture for a cell in the given fill mode."""
        zone = self.zone
        if mode == "floor_top":
            return zone.floor_textures[r][c] if zone.floor_textures else ""
        if mode == "ceil_top":
            return zone.ceil_textures[r][c] if zone.ceil_textures else ""
        if mode == "floor2_top":
            ft2 = getattr(zone, 'floor2_textures', None)
            return ft2[r][c] if ft2 else ""
        if mode == "ceil2_top":
            ct2 = getattr(zone, 'ceil2_textures', None)
            return ct2[r][c] if ct2 else ""
        if mode in ("wall_face", "floor_step", "ceil_step", "floor2_step", "ceil2_step"):
            fi = self._FACE_IDX_FILL.get(face, 0)
            if mode == "wall_face":
                return zone.face_textures[r][c][fi] if zone.face_textures else ""
            elif mode in ("floor_step", "floor2_step"):
                return zone.floor_step_textures[r][c][fi] if zone.floor_step_textures else ""
            elif mode in ("ceil_step", "ceil2_step"):
                return zone.ceil_step_textures[r][c][fi] if zone.ceil_step_textures else ""
        return ""

    def _write_fill_tex(self, r: int, c: int, mode: str, face: str, tex: str) -> None:
        """Write a texture for a cell in the given fill mode."""
        zone = self.zone
        if mode == "floor_top":
            if zone.floor_textures:
                zone.floor_textures[r][c] = tex
        elif mode == "ceil_top":
            if zone.ceil_textures:
                zone.ceil_textures[r][c] = tex
        elif mode == "floor2_top":
            ft2 = getattr(zone, 'floor2_textures', None)
            if ft2:
                ft2[r][c] = tex
        elif mode == "ceil2_top":
            ct2 = getattr(zone, 'ceil2_textures', None)
            if ct2:
                ct2[r][c] = tex
        elif mode == "wall_face":
            fi = self._FACE_IDX_FILL.get(face, 0)
            if zone.face_textures:
                zone.face_textures[r][c][fi] = tex
                zone.wall_textures[r][c] = tex
        elif mode in ("floor_step", "floor2_step"):
            fi = self._FACE_IDX_FILL.get(face, 0)
            if zone.floor_step_textures:
                zone.floor_step_textures[r][c][fi] = tex
        elif mode in ("ceil_step", "ceil2_step"):
            fi = self._FACE_IDX_FILL.get(face, 0)
            if zone.ceil_step_textures:
                zone.ceil_step_textures[r][c][fi] = tex

    def _fill_can_spread(self, r: int, c: int, nr: int, nc: int,
                         mode: str, ref_height: float, face: str,
                         origin_tex: str) -> bool:
        """Check whether fill can spread from (r,c) to (nr,nc)."""
        zone = self.zone

        # Height match check (within tolerance)
        tol = 0.01
        td_n = tile_def(zone.tiles[nr][nc])
        is_wall_n = td_n and td_n.wall
        td_c = tile_def(zone.tiles[r][c])
        is_wall_c = td_c and td_c.wall

        if mode == "floor_top":
            # Don't spread into walls
            if is_wall_n:
                return False
            # Check height match
            if abs(zone.floor_heights[nr][nc] - ref_height) > tol:
                return False
            # Check texture matches origin
            cur = zone.floor_textures[nr][nc] if zone.floor_textures else ""
            if cur != origin_tex:
                return False
            return True

        if mode == "ceil_top":
            if is_wall_n:
                return False
            if abs(zone.ceil_heights[nr][nc] - ref_height) > tol:
                return False
            cur = zone.ceil_textures[nr][nc] if zone.ceil_textures else ""
            if cur != origin_tex:
                return False
            return True

        if mode == "wall_face":
            # Only fill same-face walls at same height
            if not is_wall_n:
                return False
            if abs(zone.floor_heights[nr][nc] - ref_height) > tol:
                return False
            fi = self._FACE_IDX_FILL.get(face, 0)
            cur = zone.face_textures[nr][nc][fi] if zone.face_textures else ""
            if cur != origin_tex:
                return False
            # Check segment boundary: if either cell has segments on the
            # shared face, don't spread
            if self._fill_has_segments(r, c, nr, nc, "wall"):
                return False
            return True

        if mode == "floor_step":
            if is_wall_n:
                return False
            if abs(zone.floor_heights[nr][nc] - ref_height) > tol:
                return False
            fi = self._FACE_IDX_FILL.get(face, 0)
            cur = zone.floor_step_textures[nr][nc][fi] if zone.floor_step_textures else ""
            if cur != origin_tex:
                return False
            if self._fill_has_segments(r, c, nr, nc, "floor_step"):
                return False
            return True

        if mode == "ceil_step":
            if is_wall_n:
                return False
            if abs(zone.ceil_heights[nr][nc] - ref_height) > tol:
                return False
            fi = self._FACE_IDX_FILL.get(face, 0)
            cur = zone.ceil_step_textures[nr][nc][fi] if zone.ceil_step_textures else ""
            if cur != origin_tex:
                return False
            if self._fill_has_segments(r, c, nr, nc, "ceil_step"):
                return False
            return True

        LAYER_NONE = -1000.0

        if mode == "floor2_top":
            if is_wall_n:
                return False
            f2h = getattr(zone, 'floor2_heights', None)
            if not f2h or f2h[nr][nc] <= LAYER_NONE + 1.0:
                return False
            if abs(f2h[nr][nc] - ref_height) > tol:
                return False
            ft2 = getattr(zone, 'floor2_textures', None)
            cur = ft2[nr][nc] if ft2 else ""
            if cur != origin_tex:
                return False
            return True

        if mode == "ceil2_top":
            if is_wall_n:
                return False
            c2h = getattr(zone, 'ceil2_heights', None)
            if not c2h or c2h[nr][nc] <= LAYER_NONE + 1.0:
                return False
            if abs(c2h[nr][nc] - ref_height) > tol:
                return False
            ct2 = getattr(zone, 'ceil2_textures', None)
            cur = ct2[nr][nc] if ct2 else ""
            if cur != origin_tex:
                return False
            return True

        if mode == "floor2_step":
            if is_wall_n:
                return False
            f2h = getattr(zone, 'floor2_heights', None)
            if not f2h or f2h[nr][nc] <= LAYER_NONE + 1.0:
                return False
            if abs(f2h[nr][nc] - ref_height) > tol:
                return False
            fi = self._FACE_IDX_FILL.get(face, 0)
            cur = zone.floor_step_textures[nr][nc][fi] if zone.floor_step_textures else ""
            if cur != origin_tex:
                return False
            if self._fill_has_segments(r, c, nr, nc, "floor_step"):
                return False
            return True

        if mode == "ceil2_step":
            if is_wall_n:
                return False
            c2h = getattr(zone, 'ceil2_heights', None)
            if not c2h or c2h[nr][nc] <= LAYER_NONE + 1.0:
                return False
            if abs(c2h[nr][nc] - ref_height) > tol:
                return False
            fi = self._FACE_IDX_FILL.get(face, 0)
            cur = zone.ceil_step_textures[nr][nc][fi] if zone.ceil_step_textures else ""
            if cur != origin_tex:
                return False
            if self._fill_has_segments(r, c, nr, nc, "ceil_step"):
                return False
            return True

        return False

    def _fill_has_segments(self, r: int, c: int, nr: int, nc: int,
                           seg_type: str) -> bool:
        """Check if there are segment boundaries between two adjacent cells."""
        zone = self.zone

        if seg_type == "wall":
            grid = zone.wall_segments
        elif seg_type == "floor_step":
            grid = zone.floor_step_segments
        else:
            grid = zone.ceil_step_segments

        if not grid:
            return False

        # Determine the shared face direction
        dr, dc = nr - r, nc - c
        # From (r,c) looking toward (nr,nc):
        if dr == -1:
            fi_from = 0  # north
        elif dr == 1:
            fi_from = 1  # south
        elif dc == 1:
            fi_from = 2  # east
        elif dc == -1:
            fi_from = 3  # west
        else:
            return False

        # If either cell has segments on the shared face, stop
        if len(grid) > r and len(grid[r]) > c:
            if grid[r][c][fi_from]:
                return True

        # Opposite face on neighbor
        fi_opp = {0: 1, 1: 0, 2: 3, 3: 2}[fi_from]
        if len(grid) > nr and len(grid[nr]) > nc:
            if grid[nr][nc][fi_opp]:
                return True

        return False
