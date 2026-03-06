"""editor/app/panels_pkg/inspectors.py — Cell and object inspectors."""

from __future__ import annotations

import math

import imgui

from core.tiles import tile_def, TILE_COLORS
from core.entity_defs import get_entity_def, angle_to_label
from editor.view_3d import _ensure_palette
from editor.view_3d.constants import (
    PASTE_MASK_HEIGHTS, PASTE_MASK_TEXTURES, PASTE_MASK_ENTITIES,
    PASTE_MASK_SEGMENTS, PASTE_MASK_LIGHTING,
)


# ── Free helpers ──────────────────────────────────────────────────

def _paint_target_label(part: str, face: str, is_wall_tile: bool = False) -> str:
    """Return a human-readable label describing the paint target face."""
    if face == "ground":
        return ""
    _DIR = {"north": "N", "south": "S", "east": "E", "west": "W"}
    if face in _DIR:
        d = _DIR[face]
        if part == "floor":
            return f"Floor {d} Step"
        elif part == "ceiling":
            return f"Ceil {d} Step"
        else:
            return f"{d} Wall Face"
    elif face == "top":
        if part == "floor":
            return "Floor Surface"
        elif part in ("wall", "ceiling"):
            return "Ceiling Top"
    elif face == "bot":
        if part == "ceiling":
            return "Ceiling Underside"
        elif part in ("wall", "floor"):
            return "Floor Bottom"
    return f"{part} ({face})"


def _parse_relative_value(text: str, current_values: list[float]) -> list[float]:
    """Parse a relative math expression and apply it to a list of values.

    Supported prefixes:
        ``=N``  → set all to N (absolute)
        ``+N``  → add N to each
        ``-N``  → subtract N from each
        ``*N``  → multiply each by N

    A bare number (no prefix) is treated as ``=N`` (absolute set).
    Returns a new list of computed values (same length as *current_values*).
    """
    s = text.strip()
    if not s:
        return list(current_values)
    try:
        if s.startswith("="):
            n = float(s[1:])
            return [n] * len(current_values)
        elif s.startswith("+"):
            n = float(s[1:])
            return [v + n for v in current_values]
        elif s.startswith("-"):
            n = float(s[1:])
            return [v - n for v in current_values]
        elif s.startswith("*"):
            n = float(s[1:])
            return [v * n for v in current_values]
        else:
            n = float(s)
            return [n] * len(current_values)
    except (ValueError, IndexError):
        return list(current_values)


def _collect_cell_values(zone, cells, getter) -> list:
    """Collect a property value from each cell using *getter(zone, r, c)*."""
    out = []
    for r, c in cells:
        try:
            out.append(getter(zone, r, c))
        except (IndexError, AttributeError):
            out.append(None)
    return out


def _summarise_values(values: list) -> tuple:
    """Return (display_str, is_mixed, common_value)."""
    unique = set()
    for v in values:
        if isinstance(v, float):
            unique.add(round(v, 4))
        else:
            unique.add(v)
    if len(unique) == 1:
        val = values[0]
        if isinstance(val, float):
            return f"{val:.3f}", False, val
        return str(val) if val else "\u2014", False, val
    return "<Mixed>", True, None


# ── Mixin ─────────────────────────────────────────────────────────

class InspectorMixin:
    """Cell, bulk, and object inspector panels."""

    def _draw_display_section(self, ed) -> None:
        self._section_header("\u2581 DISPLAY", 0.50, 0.60, 0.65)
        half_w = imgui.get_content_region_available()[0] * 0.5
        _w = self._kb_label("display.walls_c")
        _f = self._kb_label("display.floors_c")
        _c = self._kb_label("display.ceilings_c")
        _e = self._kb_label("display.entities_c")
        _wf = self._kb_label("display.wireframe_c")
        _, ed.show_walls = imgui.checkbox(f"Walls ({_w})", ed.show_walls)
        imgui.same_line(half_w)
        _, ed.show_floors = imgui.checkbox(f"Floors ({_f})", ed.show_floors)
        _, ed.show_ceilings = imgui.checkbox(f"Ceilings ({_c})", ed.show_ceilings)
        imgui.same_line(half_w)
        _, ed.show_axes = imgui.checkbox("Axes", ed.show_axes)
        _, ed.show_entities = imgui.checkbox(f"Entities ({_e})", ed.show_entities)
        imgui.same_line(half_w)
        _, ed.wireframe = imgui.checkbox(f"Wire ({_wf})", ed.wireframe)

        if self.view_mode == "2d" and self.renderer:
            imgui.spacing()
            fov_deg = math.degrees(self.renderer.fov)
            changed, fov_deg = imgui.slider_float(
                "FOV", fov_deg, 45.0, 120.0, "%.0f\u00b0")
            if changed:
                self.renderer.fov = math.radians(fov_deg)

    def _draw_view_mode_button(self) -> None:
        imgui.spacing()
        full_w = imgui.get_content_region_available()[0]
        mode_label = "Preview" if self.view_mode == "3d" else "Editor"
        mode_icon = "\u25b6" if self.view_mode == "3d" else "\u270e"
        _tab = self._kb_label("view.toggle")
        if imgui.button(f"{mode_icon} Switch to {mode_label} ({_tab})", full_w, 26):
            self._toggle_view_mode()

    def _draw_zone_list(self) -> None:
        self._section_header("\u2581 ZONES", 0.85, 0.75, 0.45)
        if imgui.button("+ New Zone", imgui.get_content_region_available()[0], 24):
            if self._request_guarded("new"):
                self.show_new_zone = True

        # Recent zones (MRU) — show if we have session data
        recent = getattr(self, '_session', {}).get('recent_zones', [])
        if recent:
            imgui.spacing()
            imgui.text_disabled("Recent:")
            for rname in recent[:5]:
                if rname not in self.all_zones:
                    continue
                is_loaded = (rname == self.zone_name)
                if is_loaded:
                    continue  # already visible in the main list below
                if imgui.small_button(f"  {rname}##recent"):
                    if self._request_guarded("switch", rname):
                        self._load_zone(rname)
            imgui.spacing()

        for name in self.all_zones:
            is_loaded = (name == self.zone_name)
            if is_loaded:
                imgui.push_style_color(imgui.COLOR_TEXT, 1.0, 0.82, 0.25, 1.0)
            prefix = "\u25b8 " if is_loaded else "  "
            dirty_mark = " *" if is_loaded and self.dirty else ""
            clicked, _ = imgui.selectable(
                f"{prefix}{name}{dirty_mark}", is_loaded)
            if clicked and name != self.zone_name:
                if self._request_guarded("switch", name):
                    self._load_zone(name)

            # Right-click context menu
            if imgui.begin_popup_context_item(f"##ctx_{name}"):
                if imgui.menu_item("Load")[0] and name != self.zone_name:
                    if self._request_guarded("switch", name):
                        self._load_zone(name)
                if imgui.menu_item("Duplicate...")[0]:
                    self._dup_name = f"{name}_copy"
                    # Load it first if not current, so duplicate works
                    if name != self.zone_name:
                        if self._request_guarded("switch", name):
                            self._load_zone(name)
                    self.show_duplicate_zone = True
                imgui.separator()
                if imgui.menu_item("Delete")[0]:
                    if name != self.zone_name:
                        self._delete_zone_file(name)
                    else:
                        self._flash_transient(
                            "Cannot delete the loaded zone",
                            1.5, (0.9, 0.5, 0.3, 1.0))
                imgui.end_popup()

            if is_loaded:
                imgui.pop_style_color()

    def _draw_cell_inspector(self, zone) -> None:
        """Draw the cell inspector for the currently aimed cell."""
        ed = self.editor_3d
        hit = ed.aimed
        r, c = hit.row, hit.col
        active_layer = getattr(ed, 'active_layer', 1)
        pw = self.right_panel_w
        has_sel = ed._has_selection()
        sel_count = ed.selection.cell_count() if hasattr(ed, 'selection') and ed.selection.has_cells() else 0

        if has_sel and sel_count > 0:
            hdr = f"{sel_count} Cells Selected  (aimed {r},{c})"
        else:
            hdr = f"Cell ({r}, {c})"
        if not imgui.collapsing_header(f"{hdr}##cell",
                                       imgui.TREE_NODE_DEFAULT_OPEN)[0]:
            return

        if active_layer == 2:
            imgui.text_colored("[LAYER 2]", 0.78, 0.63, 1.0, 1.0)
        else:
            imgui.text_colored("[LAYER 1]", 0.55, 0.80, 0.55, 1.0)
        imgui.same_line()
        imgui.text_disabled("PgUp/PgDn")

        if has_sel:
            imgui.push_style_color(imgui.COLOR_BUTTON, 0.25, 0.55, 0.35, 1.0)
            imgui.push_style_color(imgui.COLOR_BUTTON_HOVERED, 0.30, 0.65, 0.40, 1.0)
            imgui.push_style_color(imgui.COLOR_BUTTON_ACTIVE, 0.20, 0.45, 0.30, 1.0)
            if imgui.button("Clone Aimed \u2192 Selection", pw - 30, 22):
                ed._apply_cell_to_selection()
                self.dirty = True
            imgui.pop_style_color(3)
            imgui.spacing()

        td_obj = tile_def(zone.tiles[r][c])
        tile_name = zone.tiles[r][c]
        is_wall = td_obj and td_obj.wall

        if active_layer == 1:
            if is_wall:
                imgui.text_colored("WALL", 0.9, 0.4, 0.3, 1.0)
            else:
                imgui.text_colored("OPEN", 0.4, 0.8, 0.4, 1.0)
            imgui.same_line(65)
            if imgui.small_button("Toggle##wall_toggle"):
                ed._push_undo()
                ed._ensure_face_textures()
                if is_wall:
                    self._batch_set_cell_prop(
                        lambda _r, _c: ed._make_open_at(_r, _c), has_sel)
                else:
                    self._batch_set_cell_prop(
                        lambda _r, _c: ed._make_wall_at(_r, _c), has_sel)
                self.dirty = True

            imgui.spacing()
            self._section_header("\u2581 GEOMETRY", 0.65, 0.80, 0.55, pad_top=False)
            imgui.push_item_width(pw - 90)

            fh = zone.floor_heights[r][c]
            ch = zone.ceil_heights[r][c]
            is_sky = ch >= 10.0 - 0.01

            changed_fh, new_fh = imgui.input_float(
                "Floor##insp_fh", fh, 0.25, 0.5, "%.3f")
            if changed_fh:
                new_fh = round(max(-5.0, min(10.0, new_fh)), 3)
                ed._push_undo()
                ed._ensure_face_textures()
                def _set_fh(rr, cc):
                    zone.floor_heights[rr][cc] = new_fh
                    ed._sync_tile_type(rr, cc)
                    return True
                self._batch_set_cell_prop(_set_fh, has_sel)
                self.dirty = True

            ceil_display = 10.0 if is_sky else ch
            changed_ch, new_ch = imgui.input_float(
                "Ceil##insp_ch", ceil_display, 0.25, 0.5, "%.3f")
            if changed_ch:
                new_ch = round(max(-5.0, min(10.0, new_ch)), 3)
                ed._push_undo()
                ed._ensure_face_textures()
                def _set_ch(rr, cc):
                    zone.ceil_heights[rr][cc] = new_ch
                    ed._sync_tile_type(rr, cc)
                    return True
                self._batch_set_cell_prop(_set_ch, has_sel)
                self.dirty = True

            imgui.same_line()
            sky_label = "\u2600" if is_sky else "\u25a3"
            if imgui.small_button(f"{sky_label}##sky_toggle"):
                ed._push_undo()
                if is_sky:
                    def _add_ceil(rr, cc):
                        return ed._add_ceiling_at(rr, cc)
                    self._batch_set_cell_prop(_add_ceil, has_sel)
                else:
                    def _rem_ceil(rr, cc):
                        return ed._remove_ceiling_at(rr, cc)
                    self._batch_set_cell_prop(_rem_ceil, has_sel)
                self.dirty = True

            gap = ch - fh
            gap_col = (0.9, 0.3, 0.3, 1.0) if gap < 0.5 else (0.6, 0.6, 0.6, 1.0)
            imgui.text_disabled("Gap")
            imgui.same_line(55)
            imgui.text_colored(f"{gap:.2f}", *gap_col)

            uwh = 0.0
            if zone.upper_wall_height and len(zone.upper_wall_height) > r:
                uwh = zone.upper_wall_height[r][c]
            changed_uwh, new_uwh = imgui.input_float(
                "Upper Wall##insp_uwh", uwh, 0.25, 0.5, "%.3f")
            if changed_uwh:
                new_uwh = round(max(0.0, min(10.0, new_uwh)), 3)
                ed._push_undo()
                ed._ensure_face_textures()
                def _set_uwh(rr, cc):
                    if zone.upper_wall_height and len(zone.upper_wall_height) > rr:
                        zone.upper_wall_height[rr][cc] = new_uwh
                    return True
                self._batch_set_cell_prop(_set_uwh, has_sel)
                self.dirty = True

            imgui.pop_item_width()

            imgui.spacing()
            self._section_header("\u2581 TEXTURES", 0.75, 0.55, 0.85, pad_top=False)

            wt = zone.wall_textures[r][c] if zone.wall_textures else ""
            ft = zone.floor_textures[r][c] if zone.floor_textures else ""
            ct = zone.ceil_textures[r][c] if zone.ceil_textures else ""

            # Editable texture inputs with autocomplete popup
            palette = _ensure_palette()
            _tex_input_w = pw - 60
            imgui.push_item_width(_tex_input_w)
            for lbl, tex, setter_key in (
                ("Wall", wt, "wall"),
                ("Floor", ft, "floor"),
                ("Ceil", ct, "ceil"),
            ):
                imgui.text_disabled(lbl)
                imgui.same_line(55)
                _id = f"##{setter_key}_tex_input"
                changed, new_val = imgui.input_text(
                    _id, tex or "", 64,
                    imgui.INPUT_TEXT_ENTER_RETURNS_TRUE)
                if changed and new_val != tex:
                    if new_val in palette or new_val == "":
                        ed._push_undo()
                        ed._ensure_face_textures()
                        _nv = new_val
                        _sk = setter_key
                        def _set_tex(rr, cc, _nv=_nv, _sk=_sk):
                            if _sk == "wall":
                                if zone.wall_textures and len(zone.wall_textures) > rr:
                                    zone.wall_textures[rr][cc] = _nv
                                for fi in range(4):
                                    if zone.face_textures and len(zone.face_textures) > rr:
                                        zone.face_textures[rr][cc][fi] = _nv
                            elif _sk == "floor":
                                if zone.floor_textures:
                                    zone.floor_textures[rr][cc] = _nv
                            elif _sk == "ceil":
                                if zone.ceil_textures:
                                    zone.ceil_textures[rr][cc] = _nv
                            return True
                        self._batch_set_cell_prop(_set_tex, has_sel)
                        self.dirty = True
                # Show autocomplete tooltip if partially typed
                if imgui.is_item_active() and tex:
                    _partial = tex.lower()
                    _matches = [p for p in palette if _partial in p.lower()][:8]
                    if _matches and len(_matches) < len(palette):
                        imgui.set_tooltip("\n".join(_matches))
            imgui.pop_item_width()

            brush = ed.current_texture
            if brush:
                imgui.spacing()
                btn_w = (pw - 40) / 3.0
                if imgui.button(f"Set Floor##{brush}_sf", btn_w, 20):
                    ed._push_undo()
                    ed._ensure_face_textures()
                    def _set_ft(rr, cc):
                        if zone.floor_textures:
                            zone.floor_textures[rr][cc] = brush
                        return True
                    self._batch_set_cell_prop(_set_ft, has_sel)
                    self.dirty = True
                imgui.same_line()
                if imgui.button(f"Set Ceil##{brush}_sc", btn_w, 20):
                    ed._push_undo()
                    ed._ensure_face_textures()
                    def _set_ct(rr, cc):
                        if zone.ceil_textures:
                            zone.ceil_textures[rr][cc] = brush
                        return True
                    self._batch_set_cell_prop(_set_ct, has_sel)
                    self.dirty = True
                imgui.same_line()
                if imgui.button(f"Set Wall##{brush}_sw", btn_w, 20):
                    ed._push_undo()
                    ed._ensure_face_textures()
                    def _set_wt(rr, cc):
                        if zone.wall_textures and len(zone.wall_textures) > rr:
                            zone.wall_textures[rr][cc] = brush
                        for fi in range(4):
                            if zone.face_textures and len(zone.face_textures) > rr:
                                zone.face_textures[rr][cc][fi] = brush
                        return True
                    self._batch_set_cell_prop(_set_wt, has_sel)
                    self.dirty = True
                imgui.text_disabled(f"Brush: {brush}")

            if zone.face_textures:
                faces = zone.face_textures[r][c]
                imgui.push_item_width(_tex_input_w)
                for i, d in enumerate("NSEW"):
                    imgui.text_disabled(f"  {d}")
                    imgui.same_line(55)
                    ftex = faces[i] if faces[i] else ""
                    _fid = f"##face_{d}_tex"
                    f_changed, f_new = imgui.input_text(
                        _fid, ftex, 64,
                        imgui.INPUT_TEXT_ENTER_RETURNS_TRUE)
                    if f_changed and f_new != ftex:
                        if f_new in palette or f_new == "":
                            ed._push_undo()
                            _fi = i
                            _fnv = f_new
                            def _set_face(rr, cc, _fi=_fi, _fnv=_fnv):
                                if zone.face_textures and len(zone.face_textures) > rr:
                                    zone.face_textures[rr][cc][_fi] = _fnv
                                return True
                            self._batch_set_cell_prop(_set_face, has_sel)
                            self.dirty = True
                imgui.pop_item_width()

            if zone.wall_segments:
                segs = zone.wall_segments[r][c]
                has_segs = any(face_segs for face_segs in segs)
                if has_segs and imgui.tree_node("Segments"):
                    for fi, face_segs in enumerate(segs):
                        if face_segs:
                            fn = "NSEW"[fi]
                            for seg in face_segs:
                                imgui.text_disabled(f"  {fn}")
                                imgui.same_line(40)
                                imgui.text(f"{seg[0]} @ {seg[1]:.2f}")
                    imgui.tree_pop()

        else:
            imgui.spacing()
            self._section_header("\u2581 LAYER 2 GEOMETRY", 0.78, 0.63, 1.0, pad_top=False)
            imgui.push_item_width(pw - 90)

            LAYER_NONE = -1000.0
            f2 = getattr(zone, 'floor2_heights', None)
            c2 = getattr(zone, 'ceil2_heights', None)
            f2v = f2[r][c] if f2 and r < len(f2) and c < len(f2[r]) else LAYER_NONE
            c2v = c2[r][c] if c2 and r < len(c2) and c < len(c2[r]) else LAYER_NONE
            has_f2 = f2v > LAYER_NONE + 1.0
            has_c2 = c2v > LAYER_NONE + 1.0

            f2_display = f2v if has_f2 else 0.0
            changed_f2, new_f2 = imgui.input_float(
                "Floor2##insp_f2", f2_display, 0.25, 0.5, "%.3f")
            if changed_f2:
                new_f2 = round(max(-5.0, min(10.0, new_f2)), 3)
                ed._push_undo()
                ed._layer2_ensure_grids()
                def _set_f2(rr, cc):
                    zone.floor2_heights[rr][cc] = new_f2
                    return True
                self._batch_set_cell_prop(_set_f2, has_sel)
                self.dirty = True
            imgui.same_line()
            if has_f2:
                if imgui.small_button("\u2716##del_f2"):
                    ed._push_undo()
                    ed._layer2_ensure_grids()
                    zone.floor2_heights[r][c] = LAYER_NONE
                    zone.floor2_textures[r][c] = ""
                    self.dirty = True
            else:
                if imgui.small_button("+##add_f2"):
                    ed._push_undo()
                    ed._layer2_ensure_grids()
                    base = zone.floor_heights[r][c] if zone.floor_heights else 0.0
                    zone.floor2_heights[r][c] = round(base + 0.5, 3)
                    self.dirty = True

            c2_display = c2v if has_c2 else 0.0
            changed_c2, new_c2 = imgui.input_float(
                "Ceil2##insp_c2", c2_display, 0.25, 0.5, "%.3f")
            if changed_c2:
                new_c2 = round(max(-5.0, min(10.0, new_c2)), 3)
                ed._push_undo()
                ed._layer2_ensure_grids()
                def _set_c2(rr, cc):
                    zone.ceil2_heights[rr][cc] = new_c2
                    return True
                self._batch_set_cell_prop(_set_c2, has_sel)
                self.dirty = True
            imgui.same_line()
            if has_c2:
                if imgui.small_button("\u2716##del_c2"):
                    ed._push_undo()
                    ed._layer2_ensure_grids()
                    zone.ceil2_heights[r][c] = LAYER_NONE
                    zone.ceil2_textures[r][c] = ""
                    self.dirty = True
            else:
                if imgui.small_button("+##add_c2"):
                    ed._push_undo()
                    ed._layer2_ensure_grids()
                    ch_val = zone.ceil_heights[r][c] if zone.ceil_heights else 1.0
                    zone.ceil2_heights[r][c] = round(ch_val - 0.25, 3)
                    self.dirty = True

            if has_f2 and has_c2:
                gap2 = c2v - f2v
                gap_col = (0.9, 0.3, 0.3, 1.0) if gap2 < 0.5 else (0.6, 0.6, 0.6, 1.0)
                imgui.text_disabled("Gap")
                imgui.same_line(55)
                imgui.text_colored(f"{gap2:.2f}", *gap_col)

            imgui.pop_item_width()

            imgui.spacing()
            self._section_header("\u2581 TEXTURES", 0.75, 0.55, 0.85, pad_top=False)
            f2t = zone.floor2_textures[r][c] if getattr(zone, 'floor2_textures', None) else ""
            c2t = zone.ceil2_textures[r][c] if getattr(zone, 'ceil2_textures', None) else ""
            palette = _ensure_palette()
            _l2_tex_w = pw - 60
            imgui.push_item_width(_l2_tex_w)
            for lbl, tex, l2key in (("Floor2", f2t, "f2"), ("Ceil2", c2t, "c2")):
                imgui.text_disabled(lbl)
                imgui.same_line(55)
                _l2id = f"##{l2key}_tex_input"
                l2_changed, l2_new = imgui.input_text(
                    _l2id, tex or "", 64,
                    imgui.INPUT_TEXT_ENTER_RETURNS_TRUE)
                if l2_changed and l2_new != tex:
                    if l2_new in palette or l2_new == "":
                        ed._push_undo()
                        ed._layer2_ensure_grids()
                        _l2k = l2key
                        _l2v = l2_new
                        def _set_l2(rr, cc, _l2k=_l2k, _l2v=_l2v):
                            if _l2k == "f2":
                                zone.floor2_textures[rr][cc] = _l2v
                            else:
                                zone.ceil2_textures[rr][cc] = _l2v
                            return True
                        self._batch_set_cell_prop(_set_l2, has_sel)
                        self.dirty = True
            imgui.pop_item_width()
            brush = ed.current_texture
            if brush:
                imgui.spacing()
                btn_w = (pw - 40) / 2.0
                if imgui.button(f"Set F2##{brush}_sf2", btn_w, 20):
                    ed._push_undo()
                    ed._layer2_ensure_grids()
                    def _set_f2t(rr, cc):
                        zone.floor2_textures[rr][cc] = brush
                        return True
                    self._batch_set_cell_prop(_set_f2t, has_sel)
                    self.dirty = True
                imgui.same_line()
                if imgui.button(f"Set C2##{brush}_sc2", btn_w, 20):
                    ed._push_undo()
                    ed._layer2_ensure_grids()
                    def _set_c2t(rr, cc):
                        zone.ceil2_textures[rr][cc] = brush
                        return True
                    self._batch_set_cell_prop(_set_c2t, has_sel)
                    self.dirty = True
                imgui.text_disabled(f"Brush: {brush}")

        if hit.part:
            imgui.spacing()
            is_wall_a = td_obj and td_obj.wall
            face_label = _paint_target_label(hit.part, hit.face, is_wall_a)
            if hit.part == "floor":
                pc = (0.7, 0.9, 0.55, 1.0)
            elif hit.part == "ceiling":
                pc = (0.55, 0.7, 0.9, 1.0)
            else:
                pc = (0.95, 0.75, 0.35, 1.0)
            imgui.text_colored(f"> {face_label}", *pc)

            if ed.tool == "paint":
                tex = ed.current_texture or zone.tiles[r][c]
                cur = self._get_face_texture(zone, r, c, hit.part, hit.face)
                imgui.text_disabled("Brush")
                imgui.same_line(55)
                imgui.text(tex)
                imgui.text_disabled("Current")
                imgui.same_line(55)
                imgui.text(cur if cur else "\u2014")

        self._draw_cell_properties(zone, r, c)

    def _draw_bulk_inspector(self, zone, sel_count: int) -> None:
        """Inspector for multi-cell selections."""
        ed = self.editor_3d
        pw = self.right_panel_w
        active_layer = getattr(ed, 'active_layer', 1)
        cells = list(ed.selection.cells)

        hdr = f"{sel_count} Cells Selected"
        if not imgui.collapsing_header(f"{hdr}##bulk",
                                       imgui.TREE_NODE_DEFAULT_OPEN)[0]:
            return

        if active_layer == 2:
            imgui.text_colored("[LAYER 2]", 0.78, 0.63, 1.0, 1.0)
        else:
            imgui.text_colored("[LAYER 1]", 0.55, 0.80, 0.55, 1.0)
        imgui.same_line()
        imgui.text_disabled("PgUp/PgDn")

        full_w = imgui.get_content_region_available()[0]
        btn_w3 = (full_w - imgui.get_style().item_spacing.x * 2) / 3
        if imgui.button("Clear##bulk_clr", btn_w3, 22):
            ed.selection.clear()
        imgui.same_line()
        if imgui.button("Ct+C##bulk_copy", btn_w3, 22):
            ed._clipboard_copy()
        imgui.same_line()
        if imgui.button("Ct+V##bulk_paste", btn_w3, 22):
            ed._clipboard_paste()

        imgui.spacing()

        if active_layer == 1:
            self._draw_bulk_layer1(zone, ed, cells, pw)
        else:
            self._draw_bulk_layer2(zone, ed, cells, pw)

        imgui.spacing()
        self._section_header("\u2581 PASTE MASK", 0.55, 0.55, 0.65, pad_top=True)
        imgui.text_disabled("Controls which data Ctrl+V pastes:")
        mask = ed._paste_mask
        for flag, label in [
            (PASTE_MASK_HEIGHTS, "Heights"),
            (PASTE_MASK_TEXTURES, "Textures"),
            (PASTE_MASK_ENTITIES, "Entities"),
            (PASTE_MASK_SEGMENTS, "Segments"),
            (PASTE_MASK_LIGHTING, "Lighting"),
        ]:
            is_on = flag in mask
            changed, new_val = imgui.checkbox(f"{label}##pm_{flag}", is_on)
            if changed:
                if new_val:
                    mask.add(flag)
                else:
                    mask.discard(flag)

    def _draw_bulk_layer1(self, zone, ed, cells, pw) -> None:
        """Bulk inspector fields for Layer 1."""
        self._section_header("\u2581 GEOMETRY", 0.65, 0.80, 0.55, pad_top=False)
        imgui.push_item_width(pw - 90)

        floor_vals = _collect_cell_values(
            zone, cells, lambda z, r, c: z.floor_heights[r][c])
        fh_str, fh_mixed, fh_common = _summarise_values(floor_vals)
        if fh_mixed:
            imgui.text_disabled("Floor")
            imgui.same_line(55)
            imgui.text_colored("<Mixed>", 0.9, 0.7, 0.3, 1.0)
        else:
            imgui.text_disabled("Floor")
            imgui.same_line(55)
            imgui.text(fh_str)

        fh_input = getattr(self, '_bulk_fh_input', "")
        changed, fh_input = imgui.input_text("##bulk_fh", fh_input, 32)
        if changed:
            self._bulk_fh_input = fh_input
        imgui.same_line()
        if imgui.small_button("Apply##bulk_fh_go"):
            vals = _parse_relative_value(
                getattr(self, '_bulk_fh_input', ''),
                [v for v in floor_vals if v is not None])
            if vals:
                ed._push_undo()
                ed._ensure_face_textures()
                idx = 0
                for r, c in cells:
                    if idx < len(vals):
                        zone.floor_heights[r][c] = round(
                            max(-5.0, min(10.0, vals[idx])), 3)
                        ed._sync_tile_type(r, c)
                    idx += 1
                self.dirty = True
                self._bulk_fh_input = ""

        ceil_vals = _collect_cell_values(
            zone, cells, lambda z, r, c: z.ceil_heights[r][c])
        ch_str, ch_mixed, ch_common = _summarise_values(ceil_vals)
        if ch_mixed:
            imgui.text_disabled("Ceil")
            imgui.same_line(55)
            imgui.text_colored("<Mixed>", 0.9, 0.7, 0.3, 1.0)
        else:
            imgui.text_disabled("Ceil")
            imgui.same_line(55)
            imgui.text(ch_str)

        ch_input = getattr(self, '_bulk_ch_input', "")
        changed, ch_input = imgui.input_text("##bulk_ch", ch_input, 32)
        if changed:
            self._bulk_ch_input = ch_input
        imgui.same_line()
        if imgui.small_button("Apply##bulk_ch_go"):
            vals = _parse_relative_value(
                getattr(self, '_bulk_ch_input', ''),
                [v for v in ceil_vals if v is not None])
            if vals:
                ed._push_undo()
                ed._ensure_face_textures()
                idx = 0
                for r, c in cells:
                    if idx < len(vals):
                        zone.ceil_heights[r][c] = round(
                            max(-5.0, min(10.0, vals[idx])), 3)
                        ed._sync_tile_type(r, c)
                    idx += 1
                self.dirty = True
                self._bulk_ch_input = ""

        imgui.pop_item_width()
        imgui.text_disabled("Syntax: +N  -N  *N  =N  or bare N")

        imgui.spacing()
        self._section_header("\u2581 TEXTURES", 0.75, 0.55, 0.85, pad_top=False)

        wall_vals = _collect_cell_values(
            zone, cells, lambda z, r, c: z.wall_textures[r][c] if z.wall_textures else "")
        floor_tex = _collect_cell_values(
            zone, cells, lambda z, r, c: z.floor_textures[r][c] if z.floor_textures else "")
        ceil_tex = _collect_cell_values(
            zone, cells, lambda z, r, c: z.ceil_textures[r][c] if z.ceil_textures else "")

        for lbl, vals in [("Wall", wall_vals), ("Floor", floor_tex), ("Ceil", ceil_tex)]:
            disp, mixed, _ = _summarise_values(vals)
            imgui.text_disabled(lbl)
            imgui.same_line(55)
            if mixed:
                imgui.text_colored("<Mixed>", 0.9, 0.7, 0.3, 1.0)
            else:
                imgui.text(disp)

        brush = ed.current_texture
        if brush:
            imgui.spacing()
            btn_w = (pw - 40) / 3.0
            if imgui.button(f"Set Floor##{brush}_bf", btn_w, 20):
                ed._push_undo()
                ed._ensure_face_textures()
                for r, c in cells:
                    if zone.floor_textures:
                        zone.floor_textures[r][c] = brush
                self.dirty = True
            imgui.same_line()
            if imgui.button(f"Set Ceil##{brush}_bc", btn_w, 20):
                ed._push_undo()
                ed._ensure_face_textures()
                for r, c in cells:
                    if zone.ceil_textures:
                        zone.ceil_textures[r][c] = brush
                self.dirty = True
            imgui.same_line()
            if imgui.button(f"Set Wall##{brush}_bw", btn_w, 20):
                ed._push_undo()
                ed._ensure_face_textures()
                for r, c in cells:
                    if zone.wall_textures:
                        zone.wall_textures[r][c] = brush
                    if zone.face_textures:
                        for fi in range(4):
                            zone.face_textures[r][c][fi] = brush
                self.dirty = True
            imgui.text_disabled(f"Brush: {brush}")

        imgui.spacing()
        self._section_header("\u2581 LIGHTING", 0.60, 0.60, 0.50, pad_top=False)
        light_vals = _collect_cell_values(
            zone, cells,
            lambda z, r, c: z.light_levels[r][c]
            if z.light_levels and len(z.light_levels) > r and len(z.light_levels[r]) > c
            else 1.0)
        ll_str, ll_mixed, ll_common = _summarise_values(light_vals)
        imgui.text_disabled("Light")
        imgui.same_line(55)
        if ll_mixed:
            imgui.text_colored("<Mixed>", 0.9, 0.7, 0.3, 1.0)
        else:
            imgui.text(ll_str)

        imgui.push_item_width(pw - 90)
        ll_input = getattr(self, '_bulk_ll_input', "")
        changed, ll_input = imgui.input_text("##bulk_ll", ll_input, 32)
        if changed:
            self._bulk_ll_input = ll_input
        imgui.same_line()
        if imgui.small_button("Apply##bulk_ll_go"):
            vals = _parse_relative_value(
                getattr(self, '_bulk_ll_input', ''),
                [v for v in light_vals if v is not None])
            if vals:
                ed._push_undo()
                idx = 0
                for r, c in cells:
                    if (idx < len(vals) and zone.light_levels
                            and len(zone.light_levels) > r):
                        zone.light_levels[r][c] = round(
                            max(0.0, min(1.0, vals[idx])), 3)
                    idx += 1
                self.dirty = True
                self._bulk_ll_input = ""
        imgui.pop_item_width()

    def _draw_bulk_layer2(self, zone, ed, cells, pw) -> None:
        """Bulk inspector fields for Layer 2."""
        LAYER_NONE = -1000.0
        self._section_header("\u2581 LAYER 2 GEOMETRY", 0.78, 0.63, 1.0, pad_top=False)
        imgui.push_item_width(pw - 90)

        f2_vals = _collect_cell_values(
            zone, cells,
            lambda z, r, c: z.floor2_heights[r][c]
            if getattr(z, 'floor2_heights', None) and len(z.floor2_heights) > r
            else LAYER_NONE)
        c2_vals = _collect_cell_values(
            zone, cells,
            lambda z, r, c: z.ceil2_heights[r][c]
            if getattr(z, 'ceil2_heights', None) and len(z.ceil2_heights) > r
            else LAYER_NONE)

        for lbl, vals, attr in [("Floor2", f2_vals, "floor2_heights"),
                                ("Ceil2", c2_vals, "ceil2_heights")]:
            disp, mixed, common = _summarise_values(vals)
            imgui.text_disabled(lbl)
            imgui.same_line(55)
            if mixed:
                imgui.text_colored("<Mixed>", 0.9, 0.7, 0.3, 1.0)
            else:
                v = common if common is not None else LAYER_NONE
                if v <= LAYER_NONE + 1.0:
                    imgui.text_colored("(none)", 0.4, 0.4, 0.45, 1.0)
                else:
                    imgui.text(f"{v:.3f}")

            inp_key = f'_bulk_{attr}_input'
            inp_val = getattr(self, inp_key, "")
            changed, inp_val = imgui.input_text(f"##{attr}_bi", inp_val, 32)
            if changed:
                setattr(self, inp_key, inp_val)
            imgui.same_line()
            if imgui.small_button(f"Apply##{attr}_go"):
                raw = getattr(self, inp_key, '')
                numeric_vals = [v for v in vals if v is not None and v > LAYER_NONE + 1.0]
                if not numeric_vals:
                    numeric_vals = [0.0] * len(cells)
                new_vals = _parse_relative_value(raw, numeric_vals)
                if new_vals:
                    ed._push_undo()
                    ed._layer2_ensure_grids()
                    idx = 0
                    for r, c in cells:
                        if idx < len(new_vals):
                            getattr(zone, attr)[r][c] = round(
                                max(-5.0, min(10.0, new_vals[idx])), 3)
                        idx += 1
                    self.dirty = True
                    setattr(self, inp_key, "")

        imgui.pop_item_width()
        imgui.text_disabled("Syntax: +N  -N  *N  =N  or bare N")

    def _batch_set_cell_prop(self, fn, has_sel: bool) -> None:
        """Apply *fn(r, c)* to selection cells or aimed cell only."""
        ed = self.editor_3d
        if has_sel:
            ed._apply_to_selection(fn)
        else:
            hit = ed.aimed
            if hit:
                fn(hit.row, hit.col)

    def _draw_cell_properties(self, zone, r: int, c: int) -> None:
        """Draw per-cell property sections (light, reflect, layer2, fog)."""
        pw = self.right_panel_w

        if zone.light_levels and len(zone.light_levels) > r and len(zone.light_levels[r]) > c:
            ll = zone.light_levels[r][c]
            imgui.spacing()
            imgui.text_disabled("Light")
            imgui.same_line(55)
            bright = min(1.0, ll)
            imgui.text_colored(f"{ll:.2f}", bright, bright, 0.4 + 0.6 * bright, 1.0)
            imgui.push_item_width(pw - 80)
            changed, new_ll = imgui.slider_float(
                "##light_slider", ll, 0.0, 1.0, "%.2f")
            imgui.pop_item_width()
            if changed:
                self.editor_3d._push_undo()
                zone.light_levels[r][c] = round(new_ll, 3)
                self.dirty = True

        if zone.reflect_map and len(zone.reflect_map) > r and len(zone.reflect_map[r]) > c:
            rv = zone.reflect_map[r][c]
            imgui.spacing()
            imgui.text_disabled("Reflect")
            imgui.same_line(55)
            pct = rv / 255.0
            imgui.text_colored(f"{rv}", 0.4 + 0.6 * pct, 0.7 + 0.3 * pct, 1.0, 1.0)
            imgui.push_item_width(pw - 80)
            changed, new_rv = imgui.slider_int(
                "##reflect_slider", rv, 0, 255)
            imgui.pop_item_width()
            if changed:
                self.editor_3d._push_undo()
                zone.reflect_map[r][c] = new_rv
                self.dirty = True

        LAYER_NONE = -1000.0
        has_f2 = (zone.floor2_heights and len(zone.floor2_heights) > r
                  and zone.floor2_heights[r][c] > LAYER_NONE + 1.0)
        has_c2 = (zone.ceil2_heights and len(zone.ceil2_heights) > r
                  and zone.ceil2_heights[r][c] > LAYER_NONE + 1.0)
        show_l2 = has_f2 or has_c2 or (self.editor_3d and getattr(self.editor_3d, '_sculpt_layer2', False))
        if show_l2:
            imgui.spacing()
            imgui.text_disabled("Layer 2")
            if has_f2:
                f2h = zone.floor2_heights[r][c]
                f2t = zone.floor2_textures[r][c] if zone.floor2_textures else ""
                imgui.text_disabled("  F2")
                imgui.same_line(40)
                imgui.text(f"{f2h:.2f}")
                if f2t:
                    imgui.same_line()
                    imgui.text_disabled(f"({f2t})")
            if has_c2:
                c2h = zone.ceil2_heights[r][c]
                c2t = zone.ceil2_textures[r][c] if zone.ceil2_textures else ""
                imgui.text_disabled("  C2")
                imgui.same_line(40)
                imgui.text(f"{c2h:.2f}")
                if c2t:
                    imgui.same_line()
                    imgui.text_disabled(f"({c2t})")
            if self.editor_3d and getattr(self.editor_3d, '_sculpt_layer2', False):
                tgt = self.editor_3d._layer2_target
                imgui.text_disabled("  Target")
                imgui.same_line(60)
                imgui.text_colored(tgt, 0.8, 0.6, 1.0, 1.0)

        if hasattr(zone, "fog_density") and zone.fog_density and len(zone.fog_density) > r:
            fd = zone.fog_density[r][c]
            imgui.spacing()
            imgui.text_disabled("Fog")
            imgui.same_line(55)
            imgui.text(f"{fd:.2f}")
            imgui.push_item_width(pw - 80)
            changed, new_fd = imgui.slider_float(
                "##fog_slider", fd, 0.0, 1.0, "%.2f")
            imgui.pop_item_width()
            if changed:
                self.editor_3d._push_undo()
                zone.fog_density[r][c] = round(new_fd, 3)
                self.dirty = True

    def _draw_entity_inspector(self, zone) -> None:
        """Draw editable inspector for the currently selected entity."""
        ed = self.editor_3d
        idx = ed._ent_selected
        if idx is None or idx < 0 or idx >= len(zone.entities):
            return
        ent = zone.entities[idx]
        etype = ent.get("type", "unknown")
        edef = get_entity_def(etype)

        opened, _ = imgui.collapsing_header(
            f"Entity: {etype}##entinsp", imgui.TREE_NODE_DEFAULT_OPEN)
        if not opened:
            return

        if edef:
            r0, g0, b0 = edef.color[0] / 255.0, edef.color[1] / 255.0, edef.color[2] / 255.0
            imgui.color_button("##einsp_col", r0, g0, b0, 1.0, 0, 14, 14)
            imgui.same_line()
            imgui.text_colored(edef.display_name, 0.95, 0.90, 0.75, 1.0)
        else:
            imgui.text(etype)

        imgui.text_disabled("ID")
        imgui.same_line(55)
        imgui.text(ent.get("id", "?"))

        imgui.push_item_width(self.right_panel_w - 80)

        ex = float(ent.get("x", 0.0))
        changed_x, new_x = imgui.input_float("X##einsp_x", ex, 0.1, 0.5, "%.3f")
        if changed_x:
            ed._push_undo()
            ent["x"] = round(max(0.1, min(zone.width - 0.1, new_x)), 3)
            self.dirty = True

        ey = float(ent.get("y", 0.0))
        changed_y, new_y = imgui.input_float("Z##einsp_y", ey, 0.1, 0.5, "%.3f")
        if changed_y:
            ed._push_undo()
            ent["y"] = round(max(0.1, min(zone.height - 0.1, new_y)), 3)
            self.dirty = True

        angle = float(ent.get("angle", 0.0))
        deg = math.degrees(angle)
        label = angle_to_label(angle)
        changed_a, new_deg = imgui.slider_float(
            f"Angle ({label})##einsp_angle", deg, 0.0, 360.0, "%.0f\u00b0")
        if changed_a:
            ed._push_undo()
            from core.entity_defs import snap_angle_8dir
            ent["angle"] = snap_angle_8dir(math.radians(new_deg))
            self.dirty = True
        if edef and edef.directional:
            imgui.same_line()
            imgui.text_colored("\u27a4", 0.6, 0.8, 1.0, 1.0)

        state = ent.get("state", "default")
        if edef and len(edef.states) > 1:
            states_list = list(edef.states)
            try:
                cur_idx = states_list.index(state)
            except ValueError:
                cur_idx = 0
            changed_s, new_idx = imgui.combo(
                "State##einsp_state", cur_idx, states_list)
            if changed_s:
                ed._push_undo()
                ent["state"] = states_list[new_idx]
                self.dirty = True
        else:
            imgui.text_disabled("State")
            imgui.same_line(55)
            imgui.text(state)

        def_scale = edef.scale if edef else 0.5
        props = ent.setdefault("properties", {})
        cur_scale = float(props.get("scale", def_scale))
        changed_sc, new_scale = imgui.slider_float(
            "Scale##einsp_scale", cur_scale, 0.1, 3.0, "%.2f")
        if changed_sc:
            ed._push_undo()
            props["scale"] = round(new_scale, 2)
            self.dirty = True
        imgui.same_line()
        if imgui.small_button("Reset##einsp_scale_reset"):
            props.pop("scale", None)
            self.dirty = True

        imgui.pop_item_width()

        imgui.spacing()
        if imgui.button("Deselect##einsp_desel"):
            ed._ent_deselect()
        imgui.same_line()
        imgui.push_style_color(imgui.COLOR_BUTTON, 0.6, 0.15, 0.15, 1.0)
        if imgui.button("Delete##einsp_del"):
            ed._ent_delete(idx)
        imgui.pop_style_color()

        imgui.separator()

    def _draw_prism_inspector(self, zone) -> None:
        """Draw editable inspector for the currently selected prism."""
        ed = self.editor_3d
        idx = ed._box_selected
        if idx is None or idx < 0 or idx >= len(zone.boxes):
            return
        b = zone.boxes[idx]

        opened, _ = imgui.collapsing_header(
            f"Prism #{idx}##boxinsp", imgui.TREE_NODE_DEFAULT_OPEN)
        if not opened:
            return

        imgui.push_item_width(self.right_panel_w - 80)

        bx = float(b.get("x", 0.0))
        changed, new_x = imgui.input_float("X##binsp_x", bx, 0.1, 0.5, "%.3f")
        if changed:
            ed._push_undo()
            b["x"] = round(max(0.1, min(zone.width - 0.1, new_x)), 3)
            self.dirty = True

        bz = float(b.get("y", 0.0))
        changed, new_z = imgui.input_float("Z##binsp_z", bz, 0.1, 0.5, "%.3f")
        if changed:
            ed._push_undo()
            b["y"] = round(max(0.1, min(zone.height - 0.1, new_z)), 3)
            self.dirty = True

        by = float(b.get("z", 0.0))
        changed, new_y = imgui.input_float("Base Y##binsp_by", by, 0.1, 0.5, "%.3f")
        if changed:
            ed._push_undo()
            b["z"] = round(new_y, 3)
            self.dirty = True

        bw = float(b.get("w", 1.0))
        changed, new_w = imgui.slider_float("Width##binsp_w", bw, 0.25, 8.0, "%.2f")
        if changed:
            ed._push_undo()
            b["w"] = round(new_w, 3)
            self.dirty = True

        bh = float(b.get("h", 1.0))
        changed, new_h = imgui.slider_float("Height##binsp_h", bh, 0.25, 8.0, "%.2f")
        if changed:
            ed._push_undo()
            b["h"] = round(new_h, 3)
            self.dirty = True

        bd = float(b.get("d", 1.0))
        changed, new_d = imgui.slider_float("Depth##binsp_d", bd, 0.25, 8.0, "%.2f")
        if changed:
            ed._push_undo()
            b["d"] = round(new_d, 3)
            self.dirty = True

        yaw = float(b.get("yaw", 0.0))
        deg = math.degrees(yaw)
        changed, new_deg = imgui.slider_float("Yaw##binsp_yaw", deg, 0.0, 360.0, "%.0f\u00b0")
        if changed:
            ed._push_undo()
            b["yaw"] = round(math.radians(new_deg), 4)
            self.dirty = True

        col = bool(b.get("collision", True))
        changed, new_col = imgui.checkbox("Collision##binsp_col", col)
        if changed:
            ed._push_undo()
            b["collision"] = new_col
            self.dirty = True

        textures = b.get("textures", {})
        if textures:
            imgui.spacing()
            imgui.text_disabled("Textures:")
            for face_key in ("N", "S", "E", "W", "top", "bot"):
                tex = textures.get(face_key, "")
                changed, new_tex = imgui.input_text(
                    f"{face_key}##binsp_tex_{face_key}", tex, 128)
                if changed:
                    ed._push_undo()
                    textures[face_key] = new_tex.strip()
                    self.dirty = True

        imgui.pop_item_width()

        imgui.spacing()
        if imgui.button("Deselect##binsp_desel"):
            ed._box_deselect()
        imgui.same_line()
        imgui.push_style_color(imgui.COLOR_BUTTON, 0.6, 0.15, 0.15, 1.0)
        if imgui.button("Delete##binsp_del"):
            ed._box_delete(idx)
        imgui.pop_style_color()

        imgui.separator()

    def _draw_quad_inspector(self, zone) -> None:
        """Draw editable inspector for the currently selected quad."""
        ed = self.editor_3d
        idx = ed._quad_selected
        if idx is None or idx < 0 or idx >= len(zone.quads):
            return
        q = zone.quads[idx]

        opened, _ = imgui.collapsing_header(
            f"Quad #{idx}##quadinsp", imgui.TREE_NODE_DEFAULT_OPEN)
        if not opened:
            return

        imgui.push_item_width(self.right_panel_w - 80)

        qx = float(q.get("x", 0.0))
        changed, new_x = imgui.input_float("X##qinsp_x", qx, 0.1, 0.5, "%.3f")
        if changed:
            ed._push_undo()
            q["x"] = round(max(0.1, min(zone.width - 0.1, new_x)), 3)
            self.dirty = True

        qz = float(q.get("z", 0.0))
        changed, new_z = imgui.input_float("Z##qinsp_z", qz, 0.1, 0.5, "%.3f")
        if changed:
            ed._push_undo()
            q["z"] = round(max(0.1, min(zone.height - 0.1, new_z)), 3)
            self.dirty = True

        by = float(q.get("base_y", 0.0))
        changed, new_by = imgui.input_float("Base Y##qinsp_by", by, 0.1, 0.5, "%.3f")
        if changed:
            ed._push_undo()
            q["base_y"] = round(new_by, 3)
            self.dirty = True

        w = float(q.get("width", 1.0))
        changed, new_w = imgui.slider_float("Width##qinsp_w", w, 0.25, 5.0, "%.2f")
        if changed:
            ed._push_undo()
            q["width"] = round(new_w, 3)
            self.dirty = True

        h = float(q.get("height", 1.0))
        changed, new_h = imgui.slider_float("Height##qinsp_h", h, 0.25, 5.0, "%.2f")
        if changed:
            ed._push_undo()
            q["height"] = round(new_h, 3)
            self.dirty = True

        angle = float(q.get("angle", 0.0))
        deg = math.degrees(angle)
        changed, new_deg = imgui.slider_float("Angle##qinsp_a", deg, 0.0, 360.0, "%.0f\u00b0")
        if changed:
            ed._push_undo()
            q["angle"] = round(math.radians(new_deg), 4)
            self.dirty = True

        tex = q.get("texture", "")
        changed, new_tex = imgui.input_text("Tex##qinsp_tex", tex, 128)
        if changed:
            ed._push_undo()
            q["texture"] = new_tex.strip()
            self.dirty = True

        ts = bool(q.get("two_sided", True))
        changed, new_ts = imgui.checkbox("Two-sided##qinsp_ts", ts)
        if changed:
            ed._push_undo()
            q["two_sided"] = new_ts
            self.dirty = True

        col = bool(q.get("collision", False))
        changed, new_col = imgui.checkbox("Collision##qinsp_col", col)
        if changed:
            ed._push_undo()
            q["collision"] = new_col
            self.dirty = True

        imgui.pop_item_width()

        imgui.spacing()
        if imgui.button("Deselect##qinsp_desel"):
            ed._quad_deselect()
        imgui.same_line()
        imgui.push_style_color(imgui.COLOR_BUTTON, 0.6, 0.15, 0.15, 1.0)
        if imgui.button("Delete##qinsp_del"):
            ed._quad_delete(idx)
        imgui.pop_style_color()
        imgui.separator()

    def _draw_portal_inspector(self, zone) -> None:
        """Draw editable inspector for the currently selected render portal."""
        ed = self.editor_3d
        idx = ed._portal_selected
        if idx is None or idx < 0 or idx >= len(zone.render_portals):
            return
        p = zone.render_portals[idx]

        opened, _ = imgui.collapsing_header(
            f"Portal #{idx}##pinsp", imgui.TREE_NODE_DEFAULT_OPEN)
        if not opened:
            return

        cell = p.get("cell", [0, 0])
        face = int(p.get("face", 0))
        face_names = ["N", "S", "E", "W"]
        fn = face_names[face] if 0 <= face < 4 else "?"
        imgui.text_disabled("Source")
        imgui.same_line(55)
        imgui.text(f"({cell[0]},{cell[1]}) {fn}")

        imgui.push_item_width(self.right_panel_w - 80)

        dx = float(p.get("dest_x", 0.0))
        changed, new_dx = imgui.input_float("Dest X##pinsp_dx", dx, 0.5, 1.0, "%.2f")
        if changed:
            ed._push_undo()
            p["dest_x"] = round(new_dx, 2)
            self.dirty = True

        dy = float(p.get("dest_y", 0.0))
        changed, new_dy = imgui.input_float("Dest Y##pinsp_dy", dy, 0.5, 1.0, "%.2f")
        if changed:
            ed._push_undo()
            p["dest_y"] = round(new_dy, 2)
            self.dirty = True

        ao = float(p.get("angle_offset", 0.0))
        deg = math.degrees(ao)
        changed, new_deg = imgui.slider_float(
            "Angle Off##pinsp_ao", deg, -180.0, 180.0, "%.0f\u00b0")
        if changed:
            ed._push_undo()
            p["angle_offset"] = round(math.radians(new_deg), 4)
            self.dirty = True

        imgui.pop_item_width()

        imgui.spacing()
        if imgui.button("Deselect##pinsp_desel"):
            ed._portal_deselect()
        imgui.same_line()
        imgui.push_style_color(imgui.COLOR_BUTTON, 0.6, 0.15, 0.15, 1.0)
        if imgui.button("Delete##pinsp_del"):
            ed._push_undo()
            zone.render_portals.pop(idx)
            ed._portal_selected = None
            self.dirty = True
        imgui.pop_style_color()
        imgui.separator()

    def _draw_curve_inspector(self, zone) -> None:
        """Draw editable inspector for the currently selected curve."""
        ed = self.editor_3d
        idx = ed._curve_selected
        if idx is None or idx < 0 or idx >= len(zone.curves):
            return
        cv = zone.curves[idx]

        opened, _ = imgui.collapsing_header(
            f"Curve #{idx}##cinsp", imgui.TREE_NODE_DEFAULT_OPEN)
        if not opened:
            return

        imgui.push_item_width(self.right_panel_w - 80)

        cx = float(cv.get("cx", 0.0))
        changed, new_cx = imgui.input_float("CX##cinsp_cx", cx, 0.1, 0.5, "%.3f")
        if changed:
            ed._push_undo()
            cv["cx"] = round(new_cx, 3)
            self.dirty = True

        cy = float(cv.get("cy", 0.0))
        changed, new_cy = imgui.input_float("CY##cinsp_cy", cy, 0.1, 0.5, "%.3f")
        if changed:
            ed._push_undo()
            cv["cy"] = round(new_cy, 3)
            self.dirty = True

        rad = float(cv.get("radius", 1.0))
        changed, new_rad = imgui.slider_float("Radius##cinsp_r", rad, 0.25, 10.0, "%.2f")
        if changed:
            ed._push_undo()
            cv["radius"] = round(new_rad, 3)
            self.dirty = True

        a_s = math.degrees(float(cv.get("angle_start", 0.0)))
        changed, new_as = imgui.slider_float("Arc Start##cinsp_as", a_s, 0.0, 360.0, "%.0f\u00b0")
        if changed:
            ed._push_undo()
            cv["angle_start"] = round(math.radians(new_as), 4)
            self.dirty = True

        a_e = math.degrees(float(cv.get("angle_end", 180.0)))
        changed, new_ae = imgui.slider_float("Arc End##cinsp_ae", a_e, 0.0, 360.0, "%.0f\u00b0")
        if changed:
            ed._push_undo()
            cv["angle_end"] = round(math.radians(new_ae), 4)
            self.dirty = True

        hs = float(cv.get("height_scale", 1.0))
        changed, new_hs = imgui.slider_float("Height##cinsp_h", hs, 0.25, 5.0, "%.2f")
        if changed:
            ed._push_undo()
            cv["height_scale"] = round(new_hs, 3)
            self.dirty = True

        by = float(cv.get("base_y", 0.0))
        changed, new_by = imgui.input_float("Base Y##cinsp_by", by, 0.1, 0.5, "%.3f")
        if changed:
            ed._push_undo()
            cv["base_y"] = round(new_by, 3)
            self.dirty = True

        tex = cv.get("texture", "")
        changed, new_tex = imgui.input_text("Tex##cinsp_tex", tex, 128)
        if changed:
            ed._push_undo()
            cv["texture"] = new_tex.strip()
            self.dirty = True

        imgui.pop_item_width()

        imgui.spacing()
        if imgui.button("Deselect##cinsp_desel"):
            ed._curve_deselect()
        imgui.same_line()
        imgui.push_style_color(imgui.COLOR_BUTTON, 0.6, 0.15, 0.15, 1.0)
        if imgui.button("Delete##cinsp_del"):
            ed._curve_delete(idx)
        imgui.pop_style_color()
        imgui.separator()

    def _draw_overlay_wall_inspector(self, zone) -> None:
        """Draw editable inspector for the currently selected overlay wall."""
        ed = self.editor_3d
        idx = getattr(ed, '_ow_selected', None)
        if idx is None or idx < 0 or idx >= len(zone.overlay_walls):
            return
        ow = zone.overlay_walls[idx]

        opened, _ = imgui.collapsing_header(
            f"Overlay Wall #{idx}##owinsp", imgui.TREE_NODE_DEFAULT_OPEN)
        if not opened:
            return

        imgui.push_item_width(self.right_panel_w - 80)

        changed, new_x1 = imgui.input_float("X1##owinsp_x1", ow.x1, 0.1, 0.5, "%.3f")
        if changed:
            ed._push_undo()
            ow.x1 = round(max(0.0, min(float(zone.width), new_x1)), 3)
            self.dirty = True

        changed, new_z1 = imgui.input_float("Z1##owinsp_z1", ow.y1, 0.1, 0.5, "%.3f")
        if changed:
            ed._push_undo()
            ow.y1 = round(max(0.0, min(float(zone.height), new_z1)), 3)
            self.dirty = True

        changed, new_x2 = imgui.input_float("X2##owinsp_x2", ow.x2, 0.1, 0.5, "%.3f")
        if changed:
            ed._push_undo()
            ow.x2 = round(max(0.0, min(float(zone.width), new_x2)), 3)
            self.dirty = True

        changed, new_z2 = imgui.input_float("Z2##owinsp_z2", ow.y2, 0.1, 0.5, "%.3f")
        if changed:
            ed._push_undo()
            ow.y2 = round(max(0.0, min(float(zone.height), new_z2)), 3)
            self.dirty = True

        changed, new_hs = imgui.slider_float(
            "Height##owinsp_hs", ow.height_scale, 0.125, 5.0, "%.3f")
        if changed:
            ed._push_undo()
            ow.height_scale = round(new_hs, 3)
            self.dirty = True

        tex = ow.texture if ow.texture else ""
        changed, new_tex = imgui.input_text("Tex##owinsp_tex", tex, 128)
        if changed:
            ed._push_undo()
            ow.texture = new_tex.strip()
            self.dirty = True

        changed, new_tr = imgui.checkbox("Transparent##owinsp_tr", ow.transparent)
        if changed:
            ed._push_undo()
            ow.transparent = new_tr
            self.dirty = True

        changed, new_bl = imgui.checkbox("Blocks##owinsp_bl", ow.blocks)
        if changed:
            ed._push_undo()
            ow.blocks = new_bl
            self.dirty = True

        imgui.pop_item_width()

        imgui.spacing()
        pw = self.right_panel_w - 20
        btn_w = (pw - 10) / 3.0
        if imgui.button("Paint Tex##owinsp_paint", btn_w, 20):
            ed._ow_paint()
        imgui.same_line()
        if imgui.button("Deselect##owinsp_desel", btn_w, 20):
            ed._ow_deselect()
        imgui.same_line()
        imgui.push_style_color(imgui.COLOR_BUTTON, 0.6, 0.15, 0.15, 1.0)
        if imgui.button("Delete##owinsp_del", btn_w, 20):
            ed._ow_delete(idx)
        imgui.pop_style_color()
        imgui.separator()

    def _draw_zone_settings(self, zone) -> None:
        if not imgui.collapsing_header("Zone Settings", imgui.TREE_NODE_DEFAULT_OPEN)[0]:
            return

        imgui.text_disabled("Size")
        imgui.same_line(55)
        imgui.text(f"{zone.width} x {zone.height}")
        imgui.spacing()

        ar, ac = zone.anchor if zone.anchor else (0.0, 0.0)
        imgui.text_disabled("Anchor")
        imgui.push_item_width(self.right_panel_w - 80)
        changed_r, new_ar = imgui.input_float("Row##anchor_r", ar, 0.5, 1.0)
        changed_c, new_ac = imgui.input_float("Col##anchor_c", ac, 0.5, 1.0)
        imgui.pop_item_width()
        if changed_r or changed_c:
            zone.anchor = (new_ar, new_ac)
            self.dirty = True
        if self.editor_3d and imgui.button("Set to Camera##anchor_cam"):
            zone.anchor = (self.editor_3d.cam_z, self.editor_3d.cam_x)
            self.dirty = True

        imgui.spacing()
        changed_fp, new_fp = imgui.checkbox("First Person", zone.first_person)
        if changed_fp:
            zone.first_person = new_fp
            self.dirty = True

        imgui.spacing()
        imgui.text_disabled("Skybox")
        from core.paths import SKYBOXES_DIR
        _sky_exts = {".png", ".jpg", ".jpeg", ".bmp"}
        sky_files = ["(none)"]
        if SKYBOXES_DIR.exists():
            sky_files += sorted(
                f.name for f in SKYBOXES_DIR.iterdir()
                if f.suffix.lower() in _sky_exts
            )
        cur_sky = zone.skybox if zone.skybox else "(none)"
        try:
            cur_idx = sky_files.index(cur_sky)
        except ValueError:
            sky_files.append(cur_sky)
            cur_idx = len(sky_files) - 1
        imgui.push_item_width(self.right_panel_w - 80)
        changed_sky, new_idx = imgui.combo("##skybox_combo", cur_idx, sky_files)
        imgui.pop_item_width()
        if changed_sky:
            chosen = sky_files[new_idx]
            zone.skybox = "" if chosen == "(none)" else chosen
            self.dirty = True

        if not zone.skybox:
            sc = zone.sky_color if zone.sky_color else (50, 70, 160)
            r_f, g_f, b_f = sc[0] / 255.0, sc[1] / 255.0, sc[2] / 255.0
            changed_sc, (nr, ng, nb) = imgui.color_edit3(
                "Sky Tint##sky_col", r_f, g_f, b_f)
            if changed_sc:
                zone.sky_color = (int(nr * 255), int(ng * 255), int(nb * 255))
                self.dirty = True

    def _draw_camera_info(self) -> None:
        if not imgui.collapsing_header("Camera", imgui.TREE_NODE_DEFAULT_OPEN)[0]:
            return

        ed = self.editor_3d
        imgui.columns(2, "##cam_cols", False)
        imgui.set_column_width(0, 45)
        for lbl, val in (("X", ed.cam_x), ("Y", ed.cam_y), ("Z", ed.cam_z)):
            imgui.text_disabled(lbl)
            imgui.next_column()
            imgui.text(f"{val:.2f}")
            imgui.next_column()
        imgui.text_disabled("Yaw")
        imgui.next_column()
        imgui.text(f"{math.degrees(ed.yaw):.0f}\u00b0")
        imgui.next_column()
        imgui.text_disabled("Pitch")
        imgui.next_column()
        imgui.text(f"{math.degrees(ed.pitch):.0f}\u00b0")
        imgui.columns(1)

    def _get_face_texture(self, zone, r: int, c: int, part: str, face: str) -> str:
        """Return the currently applied texture string for a given face."""
        from editor.view_3d.constants import FACE_IDX
        if face in FACE_IDX:
            fi = FACE_IDX[face]
            td_obj = tile_def(zone.tiles[r][c])
            if td_obj and td_obj.wall:
                if zone.face_textures:
                    return zone.face_textures[r][c][fi]
            elif part == "floor" and hasattr(zone, "floor_step_textures") and zone.floor_step_textures:
                return zone.floor_step_textures[r][c][fi]
            elif part == "ceiling" and hasattr(zone, "ceil_step_textures") and zone.ceil_step_textures:
                return zone.ceil_step_textures[r][c][fi]
            elif zone.face_textures:
                return zone.face_textures[r][c][fi]
        elif face == "top":
            if part == "floor" and zone.floor_textures:
                return zone.floor_textures[r][c]
            elif part in ("wall", "ceiling") and zone.ceil_textures:
                return zone.ceil_textures[r][c]
        elif face == "bot":
            if part == "ceiling" and zone.ceil_textures:
                return zone.ceil_textures[r][c]
            elif part in ("wall", "floor") and zone.floor_textures:
                return zone.floor_textures[r][c]
        return ""
