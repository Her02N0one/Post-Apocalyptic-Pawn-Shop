"""editor/view_3d/tools_segment.py — Segment editing + auto-segment helpers."""

from __future__ import annotations

from core.tiles import tile_def
from editor.view_3d.constants import FACE_IDX


class SegmentMixin:
    """Segment splitting, merging, painting, and auto-segmentation."""

    _FACE_IDX_MAP = FACE_IDX

    # ── Segment query helpers ─────────────────────────────────────

    def _seg_face_info(self) -> tuple | None:
        """Return (r, c, fi, segs, y_bot, y_top, hit_y, seg_type) or None.

        seg_type: "wall" | "floor_step" | "ceil_step"
        """
        hit = self.aimed
        if not hit or hit.face not in self._FACE_IDX_MAP:
            return None
        zone = self.zone
        r, c = hit.row, hit.col
        fi = self._FACE_IDX_MAP[hit.face]
        self._ensure_face_textures()

        td = tile_def(zone.tiles[r][c])
        if td and td.wall:
            segs = zone.wall_segments[r][c][fi]
            fh = zone.floor_heights[r][c]
            ch = zone.ceil_heights[r][c]
            return (r, c, fi, segs, fh, ch, hit.hit_y, "wall")

        if hit.part == "floor":
            fh = zone.floor_heights[r][c]
            if abs(fh) < 0.02:
                return None
            lo = min(0.0, fh)
            hi = max(0.0, fh)
            segs = zone.floor_step_segments[r][c][fi]
            return (r, c, fi, segs, lo, hi, hit.hit_y, "floor_step")

        if hit.part == "ceiling":
            ch = zone.ceil_heights[r][c]
            ct = self._ceil_mass_top(r, c)
            if ct - ch < 0.02:
                return None
            segs = zone.ceil_step_segments[r][c][fi]
            return (r, c, fi, segs, ch, ct, hit.hit_y, "ceil_step")

        if hit.part == "floor2":
            fh = zone.floor_heights[r][c]
            f2 = getattr(zone, 'floor2_heights', None)
            if not f2 or len(f2) <= r:
                return None
            f2v = f2[r][c]
            if f2v <= -999:
                return None
            lo = min(fh, f2v)
            hi = max(fh, f2v)
            if hi - lo < 0.02:
                return None
            segs = zone.floor_step_segments[r][c][fi]
            return (r, c, fi, segs, lo, hi, hit.hit_y, "floor_step")

        if hit.part == "ceiling2":
            c2 = getattr(zone, 'ceil2_heights', None)
            if not c2 or len(c2) <= r:
                return None
            c2v = c2[r][c]
            if c2v <= -999:
                return None
            uwh2_grid = getattr(zone, 'upper_wall_height2', None)
            uwh2 = uwh2_grid[r][c] if (uwh2_grid and len(uwh2_grid) > r) else 0.0
            c2_top = uwh2 if uwh2 > c2v else c2v + 0.3
            if c2_top - c2v < 0.02:
                return None
            segs = zone.ceil_step_segments[r][c][fi]
            return (r, c, fi, segs, c2v, c2_top, hit.hit_y, "ceil_step")

        return None

    def _seg_arrays(self, r: int, c: int, fi: int, seg_type: str
                    ) -> tuple:
        """Return (seg_list_ref, face_tex_ref) for the given seg_type."""
        z = self.zone
        if seg_type == "wall":
            return z.wall_segments[r][c], z.face_textures[r][c]
        if seg_type == "floor_step":
            return z.floor_step_segments[r][c], z.floor_step_textures[r][c]
        return z.ceil_step_segments[r][c], z.ceil_step_textures[r][c]

    def _aimed_segment_idx(self) -> int:
        """Return index of the segment containing hit_y, or -1."""
        info = self._seg_face_info()
        if info is None:
            return -1
        r, c, fi, segs, y_bot, y_top, hy, seg_type = info
        if not segs:
            return -1
        bot = y_bot
        for i, (tex, ytop) in enumerate(segs):
            if bot <= hy <= ytop:
                return i
            bot = ytop
        return len(segs) - 1

    # ── Interactive segment editing ───────────────────────────────

    def _seg_split(self) -> None:
        """Split the aimed face at the crosshair Y."""
        info = self._seg_face_info()
        if info is None:
            return
        r, c, fi, segs, y_bot, y_top, hy, seg_type = info
        zone = self.zone
        tex = self.current_texture

        self._push_undo()
        split_y = round(hy / self.snap_y) * self.snap_y
        split_y = max(y_bot + 0.01, min(y_top - 0.01, split_y))

        seg_arr, face_tex_arr = self._seg_arrays(r, c, fi, seg_type)

        if not segs:
            base_tex = face_tex_arr[fi] or tex
            seg_arr[fi] = [
                [base_tex, split_y],
                [tex, y_top],
            ]
        else:
            bot = y_bot
            for i, (stex, ytop) in enumerate(segs):
                if bot < split_y < ytop - 0.01:
                    new_segs = segs[:i] + [[stex, split_y], [tex, ytop]] + segs[i+1:]
                    seg_arr[fi] = new_segs
                    break
                bot = ytop
        self.dirty = True

    def _seg_merge(self) -> None:
        """Remove the nearest segment boundary to the crosshair Y."""
        info = self._seg_face_info()
        if info is None:
            return
        r, c, fi, segs, y_bot, y_top, hy, seg_type = info
        seg_arr, face_tex_arr = self._seg_arrays(r, c, fi, seg_type)

        self._push_undo()
        if len(segs) < 2:
            seg_arr[fi] = []
            self.dirty = True
            return
        best_dist = float("inf")
        best_idx = -1
        bot = y_bot
        for i, (stex, ytop) in enumerate(segs):
            if i > 0:
                boundary = bot
                d = abs(hy - boundary)
                if d < best_dist:
                    best_dist = d
                    best_idx = i
            bot = ytop
        if best_idx < 1:
            seg_arr[fi] = []
        else:
            merged_ytop = segs[best_idx][1]
            merged_tex = segs[best_idx - 1][0]
            new_segs = segs[:best_idx - 1] + [[merged_tex, merged_ytop]] + segs[best_idx + 1:]
            if len(new_segs) <= 1:
                if new_segs:
                    face_tex_arr[fi] = new_segs[0][0]
                seg_arr[fi] = []
            else:
                seg_arr[fi] = new_segs
        self.dirty = True

    def _seg_paint(self) -> None:
        """Paint the aimed segment with the current texture."""
        info = self._seg_face_info()
        if info is None:
            self._paint()
            return
        r, c, fi, segs, y_bot, y_top, hy, seg_type = info
        if not segs:
            self._paint()
            return
        idx = self._aimed_segment_idx()
        if 0 <= idx < len(segs):
            self._push_undo()
            segs[idx][0] = self.current_texture
            self.dirty = True

    # ── Auto-segment helpers (click = new layer, scroll = extend) ─

    def _auto_segment_floor(self, r: int, c: int, old_fh: float,
                            new_fh: float) -> None:
        """After raising floor, add a segment boundary at old_fh."""
        if abs(old_fh) < 0.02:
            return
        zone = self.zone
        tex = self.current_texture
        for fi in range(4):
            segs = zone.floor_step_segments[r][c][fi]
            if not segs:
                base = zone.floor_step_textures[r][c][fi] or tex
                zone.floor_step_segments[r][c][fi] = [
                    [base, old_fh],
                    [tex,  new_fh],
                ]
            else:
                last_ytop = segs[-1][1]
                if abs(last_ytop - old_fh) < 0.02:
                    segs.append([tex, new_fh])
                else:
                    segs[-1][1] = old_fh
                    segs.append([tex, new_fh])

    def _auto_trim_floor(self, r: int, c: int,
                         new_fh: float) -> None:
        """After lowering floor, trim segments above new_fh."""
        zone = self.zone
        hi = max(0.0, new_fh)
        if hi < 0.02:
            for fi in range(4):
                zone.floor_step_segments[r][c][fi] = []
            return
        for fi in range(4):
            segs = zone.floor_step_segments[r][c][fi]
            if not segs:
                continue
            while len(segs) > 1 and segs[-1][1] > hi + 0.02:
                segs.pop()
            if segs:
                segs[-1][1] = hi
            if len(segs) <= 1:
                if segs:
                    zone.floor_step_textures[r][c][fi] = segs[0][0]
                zone.floor_step_segments[r][c][fi] = []

    def _auto_segment_ceil(self, r: int, c: int, old_ch: float,
                           new_ch: float) -> None:
        """After lowering ceiling, add a segment boundary at old_ch."""
        zone = self.zone
        tex = self.current_texture
        ct = self._ceil_mass_top(r, c)
        for fi in range(4):
            segs = zone.ceil_step_segments[r][c][fi]
            if not segs:
                base = zone.ceil_step_textures[r][c][fi] or tex
                zone.ceil_step_segments[r][c][fi] = [
                    [tex,  old_ch],
                    [base, ct],
                ]
            else:
                zone.ceil_step_segments[r][c][fi] = [
                    [tex, old_ch],
                ] + segs

    def _auto_segment_uwh(self, r: int, c: int, old_uwh: float,
                          new_uwh: float) -> None:
        """After raising upper wall, add a segment boundary at old_uwh."""
        zone = self.zone
        tex = self.current_texture
        for fi in range(4):
            segs = zone.ceil_step_segments[r][c][fi]
            if not segs:
                base = zone.ceil_step_textures[r][c][fi] or tex
                zone.ceil_step_segments[r][c][fi] = [
                    [base, old_uwh],
                    [tex,  new_uwh],
                ]
            else:
                last_ytop = segs[-1][1]
                if abs(last_ytop - old_uwh) < 0.02:
                    segs.append([tex, new_uwh])
                else:
                    segs[-1][1] = old_uwh
                    segs.append([tex, new_uwh])
