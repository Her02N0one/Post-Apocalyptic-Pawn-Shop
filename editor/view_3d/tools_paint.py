"""editor/view_3d/tools_paint.py — Paint tool methods for Zone3DEditor."""

from __future__ import annotations

from core.tiles import tile_def
from editor.view_3d.constants import _ensure_palette, FACE_IDX


class PaintMixin:
    """Texture painting, erasing, and eyedropper."""

    _FACE_IDX = FACE_IDX

    # ── Per-frame aim tracking for prisms / quads ─────────────────
    # These are updated every frame by _paint_update_aim() so that
    # the renderer can show a face highlight in real time.

    _paint_aimed_prism: int | None = None
    _paint_aimed_prism_face: str = ""        # 'north','south','east','west','top','bot'
    _paint_aimed_quad: int | None = None

    # Face-name mapping: ray-picker names → box texture-dict keys
    _PRISM_FACE_KEY = {
        "north": "N", "south": "S", "east": "E", "west": "W",
        "top": "top", "bot": "bot",
    }

    def _paint_update_aim(self) -> None:
        """Recompute which prism/quad (and face) the crosshair hits.

        Called every frame from ``_update_aim()`` so highlights stay
        current as the camera moves.  Picks whichever object face
        (prism, quad, or cell) is closest to the camera.
        """
        pf = self._box_find_aimed_face()   # (idx, face, t) | None
        qf = self._quad_find_aimed_t()     # (idx, t)        | None

        prism_t = pf[2] if pf is not None else float("inf")
        quad_t  = qf[1] if qf is not None else float("inf")

        if pf is not None and prism_t <= quad_t:
            self._paint_aimed_prism = pf[0]
            self._paint_aimed_prism_face = pf[1]
            self._paint_aimed_quad = None
        elif qf is not None:
            self._paint_aimed_prism = None
            self._paint_aimed_prism_face = ""
            self._paint_aimed_quad = qf[0]
        else:
            self._paint_aimed_prism = None
            self._paint_aimed_prism_face = ""
            self._paint_aimed_quad = None

    # ── Paint prisms and quads ────────────────────────────────────

    def _paint_prism(self, idx: int, face: str | None = None) -> None:
        """Paint one face (or all faces if *face* is None) of a prism."""
        zone = self.zone
        if not zone or not zone.boxes:
            return
        if idx < 0 or idx >= len(zone.boxes):
            return
        self._push_undo()
        tex = zone.boxes[idx].setdefault("textures", {})
        if face and face in self._PRISM_FACE_KEY:
            tex[self._PRISM_FACE_KEY[face]] = self.current_texture
        else:
            for f in ("N", "S", "E", "W", "top", "bot"):
                tex[f] = self.current_texture
        self.dirty = True

    def _erase_prism(self, idx: int, face: str | None = None) -> None:
        """Erase one face (or all faces) of a prism."""
        zone = self.zone
        if not zone or not zone.boxes:
            return
        if idx < 0 or idx >= len(zone.boxes):
            return
        self._push_undo()
        tex = zone.boxes[idx].setdefault("textures", {})
        if face and face in self._PRISM_FACE_KEY:
            tex[self._PRISM_FACE_KEY[face]] = ""
        else:
            for f in ("N", "S", "E", "W", "top", "bot"):
                tex[f] = ""
        self.dirty = True

    def _pick_prism_texture(self, idx: int, face: str | None = None) -> None:
        """Eyedropper: pick the texture from the aimed prism face."""
        zone = self.zone
        if not zone or not zone.boxes:
            return
        if idx < 0 or idx >= len(zone.boxes):
            return
        tex = zone.boxes[idx].get("textures", {})
        picked = ""
        if face and face in self._PRISM_FACE_KEY:
            picked = tex.get(self._PRISM_FACE_KEY[face], "")
        if not picked:
            for f in ("N", "S", "E", "W", "top", "bot"):
                t = tex.get(f, "")
                if t:
                    picked = t
                    break
        if picked:
            palette = _ensure_palette()
            if picked in palette:
                self.tex_idx = palette.index(picked)
                self.current_texture = picked

    def _paint_quad(self, idx: int) -> None:
        """Paint the aimed quad with the current texture."""
        zone = self.zone
        if not zone or not zone.quads:
            return
        if idx < 0 or idx >= len(zone.quads):
            return
        self._push_undo()
        zone.quads[idx]["texture"] = self.current_texture
        self.dirty = True

    def _erase_quad(self, idx: int) -> None:
        """Erase (clear) the texture on the aimed quad."""
        zone = self.zone
        if not zone or not zone.quads:
            return
        if idx < 0 or idx >= len(zone.quads):
            return
        self._push_undo()
        zone.quads[idx]["texture"] = ""
        self.dirty = True

    def _pick_quad_texture(self, idx: int) -> None:
        """Eyedropper: pick the texture from the aimed quad."""
        zone = self.zone
        if not zone or not zone.quads:
            return
        if idx < 0 or idx >= len(zone.quads):
            return
        picked = zone.quads[idx].get("texture", "")
        if picked:
            palette = _ensure_palette()
            if picked in palette:
                self.tex_idx = palette.index(picked)
                self.current_texture = picked

    # ── Cell painting ─────────────────────────────────────────────

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
                    # Also paint the neighbor's face_textures so the
                    # 2.5D renderer (which may draw a wall tile's face
                    # or use resolve_face_tex fallback) stays in sync.
                    dr, dc = [(- 1, 0), (1, 0), (0, 1), (0, -1)][fi]
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < zone.height and 0 <= nc < zone.width:
                        ntd = tile_def(zone.tiles[nr][nc])
                        opp = fi ^ 1
                        if ntd and ntd.wall:
                            zone.face_textures[nr][nc][opp] = tex
                        else:
                            zone.ceil_step_textures[nr][nc][opp] = tex
                    changed = True
            elif hit.part == "ceiling2":
                old = zone.ceil_step_textures[r][c][fi]
                if old != tex:
                    _maybe_undo()
                    zone.ceil_step_textures[r][c][fi] = tex
                    dr, dc = [(-1, 0), (1, 0), (0, 1), (0, -1)][fi]
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < zone.height and 0 <= nc < zone.width:
                        ntd = tile_def(zone.tiles[nr][nc])
                        opp = fi ^ 1
                        if ntd and ntd.wall:
                            zone.face_textures[nr][nc][opp] = tex
                        else:
                            zone.ceil_step_textures[nr][nc][opp] = tex
                    changed = True
            elif hit.part == "floor2":
                old = zone.floor_step_textures[r][c][fi]
                if old != tex:
                    _maybe_undo()
                    zone.floor_step_textures[r][c][fi] = tex
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
            elif hit.part == "floor2":
                ft2 = getattr(zone, 'floor2_textures', None)
                if ft2 and len(ft2) > r and len(ft2[r]) > c:
                    old = ft2[r][c]
                    if old != tex:
                        _maybe_undo()
                        ft2[r][c] = tex
                        changed = True
            elif hit.part == "ceiling2":
                ct2 = getattr(zone, 'ceil2_textures', None)
                if ct2 and len(ct2) > r and len(ct2[r]) > c:
                    old = ct2[r][c]
                    if old != tex:
                        _maybe_undo()
                        ct2[r][c] = tex
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
            elif hit.part == "ceiling2":
                ct2 = getattr(zone, 'ceil2_textures', None)
                if ct2 and len(ct2) > r and len(ct2[r]) > c:
                    old = ct2[r][c]
                    if old != tex:
                        _maybe_undo()
                        ct2[r][c] = tex
                        changed = True
            elif hit.part == "floor2":
                ft2 = getattr(zone, 'floor2_textures', None)
                if ft2 and len(ft2) > r and len(ft2[r]) > c:
                    old = ft2[r][c]
                    if old != tex:
                        _maybe_undo()
                        ft2[r][c] = tex
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

        # Layer 2 flat textures
        f2t = getattr(zone, 'floor2_textures', None)
        if f2t and len(f2t) > r and len(f2t[r]) > c:
            f2t[r][c] = tex
        c2t = getattr(zone, 'ceil2_textures', None)
        if c2t and len(c2t) > r and len(c2t[r]) > c:
            c2t[r][c] = tex

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
            elif hit.part == "ceiling2":
                zone.ceil_step_textures[r][c][fi] = ""
            elif hit.part == "floor2":
                zone.floor_step_textures[r][c][fi] = ""
            else:
                zone.face_textures[r][c][fi] = ""
                if all(f == "" for f in zone.face_textures[r][c]):
                    zone.wall_textures[r][c] = ""
        elif hit.face == "top":
            if hit.part == "floor" and zone.floor_textures:
                zone.floor_textures[r][c] = ""
            elif hit.part == "floor2":
                ft2 = getattr(zone, 'floor2_textures', None)
                if ft2 and len(ft2) > r and len(ft2[r]) > c:
                    ft2[r][c] = ""
            elif hit.part == "ceiling2":
                ct2 = getattr(zone, 'ceil2_textures', None)
                if ct2 and len(ct2) > r and len(ct2[r]) > c:
                    ct2[r][c] = ""
            elif hit.part in ("wall", "ceiling") and zone.ceil_textures:
                zone.ceil_textures[r][c] = ""
        elif hit.face == "bot":
            if hit.part == "ceiling" and zone.ceil_textures:
                zone.ceil_textures[r][c] = ""
            elif hit.part == "ceiling2":
                ct2 = getattr(zone, 'ceil2_textures', None)
                if ct2 and len(ct2) > r and len(ct2[r]) > c:
                    ct2[r][c] = ""
            elif hit.part == "floor2":
                ft2 = getattr(zone, 'floor2_textures', None)
                if ft2 and len(ft2) > r and len(ft2[r]) > c:
                    ft2[r][c] = ""
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
            elif hit.part == "ceiling2":
                picked = zone.ceil_step_textures[r][c][fi]
            elif hit.part == "floor2":
                picked = zone.floor_step_textures[r][c][fi]
            else:
                picked = zone.face_textures[r][c][fi] or zone.wall_textures[r][c]
        elif hit.face == "top":
            if hit.part == "floor" and zone.floor_textures:
                picked = zone.floor_textures[r][c]
            elif hit.part == "floor2":
                ft2 = getattr(zone, 'floor2_textures', None)
                if ft2 and len(ft2) > r and len(ft2[r]) > c:
                    picked = ft2[r][c]
            elif hit.part == "ceiling2":
                ct2 = getattr(zone, 'ceil2_textures', None)
                if ct2 and len(ct2) > r and len(ct2[r]) > c:
                    picked = ct2[r][c]
            elif hit.part in ("wall", "ceiling") and zone.ceil_textures:
                picked = zone.ceil_textures[r][c]
        elif hit.face == "bot":
            if hit.part == "ceiling" and zone.ceil_textures:
                picked = zone.ceil_textures[r][c]
            elif hit.part == "ceiling2":
                ct2 = getattr(zone, 'ceil2_textures', None)
                if ct2 and len(ct2) > r and len(ct2[r]) > c:
                    picked = ct2[r][c]
            elif hit.part == "floor2":
                ft2 = getattr(zone, 'floor2_textures', None)
                if ft2 and len(ft2) > r and len(ft2[r]) > c:
                    picked = ft2[r][c]
            elif hit.part in ("wall", "floor") and zone.floor_textures:
                picked = zone.floor_textures[r][c]

        if not picked:
            picked = zone.tiles[r][c]

        palette = _ensure_palette()
        if picked in palette:
            self.tex_idx = palette.index(picked)
            self.current_texture = picked
