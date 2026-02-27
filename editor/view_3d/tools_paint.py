"""editor/view_3d/tools_paint.py — Paint tool methods for Zone3DEditor."""

from __future__ import annotations

from core.tiles import tile_def
from editor.view_3d.constants import _ensure_palette, FACE_IDX


class PaintMixin:
    """Texture painting, erasing, and eyedropper."""

    _FACE_IDX = FACE_IDX

    def _paint(self, push_undo: bool = True) -> None:
        """Paint the aimed face with the current texture.

        When the aimed face has segments, paint only the aimed segment.
        If *push_undo* is False the caller is responsible for having
        pushed an undo snapshot already (used by continuous drag-paint).
        """
        hit = self.aimed
        if not hit or hit.face == "ground":
            return

        # Delegate to segment paint if segments exist
        info = self._seg_face_info()
        if info is not None:
            _r, _c, _fi, segs, *_ = info
            if segs:
                self._seg_paint()
                return

        zone = self.zone
        r, c = hit.row, hit.col
        tex = self.current_texture

        self._ensure_face_textures()

        def _maybe_undo() -> None:
            if push_undo:
                self._push_undo()

        changed = False
        if hit.face in self._FACE_IDX:
            fi = self._FACE_IDX[hit.face]
            td = tile_def(zone.tiles[r][c])
            if td and td.wall:
                old = zone.face_textures[r][c][fi]
                if old != tex:
                    _maybe_undo()
                    zone.face_textures[r][c][fi] = tex
                    zone.wall_textures[r][c] = tex
                    changed = True
            elif hit.part == "floor":
                old = zone.floor_step_textures[r][c][fi]
                if old != tex:
                    _maybe_undo()
                    zone.floor_step_textures[r][c][fi] = tex
                    changed = True
            elif hit.part == "ceiling":
                old = zone.ceil_step_textures[r][c][fi]
                if old != tex:
                    _maybe_undo()
                    zone.ceil_step_textures[r][c][fi] = tex
                    changed = True
            else:
                old = zone.face_textures[r][c][fi]
                if old != tex:
                    _maybe_undo()
                    zone.face_textures[r][c][fi] = tex
                    zone.wall_textures[r][c] = tex
                    changed = True
        elif hit.face == "top":
            if hit.part == "floor" and zone.floor_textures:
                old = zone.floor_textures[r][c]
                if old != tex:
                    _maybe_undo()
                    zone.floor_textures[r][c] = tex
                    changed = True
            elif hit.part in ("wall", "ceiling") and zone.ceil_textures:
                old = zone.ceil_textures[r][c]
                if old != tex:
                    _maybe_undo()
                    zone.ceil_textures[r][c] = tex
                    changed = True
        elif hit.face == "bot":
            if hit.part == "ceiling" and zone.ceil_textures:
                old = zone.ceil_textures[r][c]
                if old != tex:
                    _maybe_undo()
                    zone.ceil_textures[r][c] = tex
                    changed = True
            elif hit.part in ("wall", "floor") and zone.floor_textures:
                old = zone.floor_textures[r][c]
                if old != tex:
                    _maybe_undo()
                    zone.floor_textures[r][c] = tex
                    changed = True

        if changed:
            self.dirty = True

    def _paint_continuous(self) -> None:
        """Continuous drag-paint: apply texture without pushing undo.

        The initial MOUSEBUTTONDOWN already pushed an undo snapshot,
        so the entire drag stroke is a single undo operation.
        """
        self._paint(push_undo=False)

    def _paint_all(self) -> None:
        """Shift+LMB: paint every surface of the aimed cell at once.

        Sets the floor texture, ceiling texture, wall texture, all four
        cardinal face overrides, and all step-wall textures to the current
        brush.  A single undo snapshot covers the whole operation.
        """
        hit = self.aimed
        if not hit:
            return

        zone = self.zone
        r, c = hit.row, hit.col
        tex = self.current_texture

        self._ensure_face_textures()
        self._push_undo()

        # Floor + ceiling surface
        if zone.floor_textures:
            zone.floor_textures[r][c] = tex
        if zone.ceil_textures:
            zone.ceil_textures[r][c] = tex

        # Wall base texture
        zone.wall_textures[r][c] = tex

        # All 4 cardinal face overrides (N/S/E/W)
        zone.face_textures[r][c] = [tex, tex, tex, tex]

        # Floor step textures (4 directions)
        if zone.floor_step_textures and len(zone.floor_step_textures) > r:
            zone.floor_step_textures[r][c] = [tex, tex, tex, tex]

        # Ceiling step textures (4 directions)
        if zone.ceil_step_textures and len(zone.ceil_step_textures) > r:
            zone.ceil_step_textures[r][c] = [tex, tex, tex, tex]

        self.dirty = True

    def _erase_texture(self) -> None:
        """RMB: erase texture override (reset to default)."""
        hit = self.aimed
        if not hit or hit.face == "ground":
            return
        zone = self.zone
        r, c = hit.row, hit.col
        self._ensure_face_textures()

        self._push_undo()
        if hit.face in self._FACE_IDX:
            fi = self._FACE_IDX[hit.face]
            td = tile_def(zone.tiles[r][c])
            if td and td.wall:
                zone.face_textures[r][c][fi] = ""
                if all(f == "" for f in zone.face_textures[r][c]):
                    zone.wall_textures[r][c] = ""
            elif hit.part == "floor":
                zone.floor_step_textures[r][c][fi] = ""
            elif hit.part == "ceiling":
                zone.ceil_step_textures[r][c][fi] = ""
            else:
                zone.face_textures[r][c][fi] = ""
                if all(f == "" for f in zone.face_textures[r][c]):
                    zone.wall_textures[r][c] = ""
        elif hit.face == "top":
            if hit.part == "floor" and zone.floor_textures:
                zone.floor_textures[r][c] = ""
            elif hit.part in ("wall", "ceiling") and zone.ceil_textures:
                zone.ceil_textures[r][c] = ""
        elif hit.face == "bot":
            if hit.part == "ceiling" and zone.ceil_textures:
                zone.ceil_textures[r][c] = ""
            elif hit.part in ("wall", "floor") and zone.floor_textures:
                zone.floor_textures[r][c] = ""
        self.dirty = True

    def _pick_texture(self) -> None:
        """MMB: eyedropper -- pick the texture from the aimed face."""
        hit = self.aimed
        if not hit or hit.face == "ground":
            return
        zone = self.zone
        r, c = hit.row, hit.col
        self._ensure_face_textures()
        picked = ""

        if hit.face in self._FACE_IDX:
            fi = self._FACE_IDX[hit.face]
            td = tile_def(zone.tiles[r][c])
            if td and td.wall:
                picked = zone.face_textures[r][c][fi] or zone.wall_textures[r][c]
            elif hit.part == "floor":
                picked = zone.floor_step_textures[r][c][fi]
            elif hit.part == "ceiling":
                picked = zone.ceil_step_textures[r][c][fi]
            else:
                picked = zone.face_textures[r][c][fi] or zone.wall_textures[r][c]
        elif hit.face == "top":
            if hit.part == "floor" and zone.floor_textures:
                picked = zone.floor_textures[r][c]
            elif hit.part in ("wall", "ceiling") and zone.ceil_textures:
                picked = zone.ceil_textures[r][c]
        elif hit.face == "bot":
            if hit.part == "ceiling" and zone.ceil_textures:
                picked = zone.ceil_textures[r][c]
            elif hit.part in ("wall", "floor") and zone.floor_textures:
                picked = zone.floor_textures[r][c]

        if not picked:
            picked = zone.tiles[r][c]

        palette = _ensure_palette()
        if picked in palette:
            self.tex_idx = palette.index(picked)
            self.current_texture = picked
