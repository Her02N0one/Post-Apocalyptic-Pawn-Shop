"""editor/view_3d/rendering.py — All 3D rendering + HUD for Zone3DEditor."""

from __future__ import annotations

import math

import pygame

from core.tiles import TILE_COLORS, tile_def
from core.fonts import get_font as _get_font
from editor.view_3d.math3d import (
    _perspective, _mat4_mul, _build_view_matrix, _project_poly,
    NEAR_CLIP, FAR_CLIP, FOV_DEG,
)
from editor.view_3d.picking import _CellHit
from editor.view_3d.constants import (
    SKY_HEIGHT,
    COL_BG, COL_GRID, COL_GRID_EDGE, COL_CEIL_GRID,
    COL_BLOCK_SEL, COL_CROSSHAIR, COL_EDGE_DIM,
    COL_AXIS_X, COL_AXIS_Y, COL_AXIS_Z,
    COL_HUD_BG, COL_HUD_TEXT, COL_HUD_VAL, COL_HUD_TITLE,
    COL_SEG_LINE,
    COL_WALL_DEF, COL_FLOOR_DEF, COL_CEIL_DEF,
    TOOL_LABELS, TOOL_COLORS, TOOL_HINTS,
    COL_TOOL_SELECT,
    COL_TOOL_CEILING,
    COL_TOOL_LIGHT, COL_TOOL_REFLECT,
    COL_TOOL_LAYER2, COL_TOOL_QUAD, COL_TOOL_PORTAL,
    COL_TOOL_CURVE, COL_TOOL_FOG, COL_TOOL_BOX,
    HOTBAR_SIZE,
    FACE_IDX,
)


def _face_edge_pts(
    c: int, r: int, y: float, face: str,
) -> list[tuple[float, float, float]] | None:
    """Return the two 3D endpoints of a horizontal edge on one face of a cell."""
    if face == "north":
        return [(c, y, r), (c + 1, y, r)]
    if face == "south":
        return [(c + 1, y, r + 1), (c, y, r + 1)]
    if face == "east":
        return [(c + 1, y, r), (c + 1, y, r + 1)]
    if face == "west":
        return [(c, y, r + 1), (c, y, r)]
    return None


# Merge-target boundary colour (red-ish to contrast split preview orange)
COL_SEG_MERGE = (255, 80, 80)


class RenderingMixin:
    """draw(), HUD, face highlight, segment overdraw, colour helpers."""

    # Face-index mapping:  _FACE_DEFS order -> zone face-texture index
    #   _FACE_DEFS: 0=top 1=bot 2=north 3=south 4=west 5=east
    #   zone data:  face_textures[r][c][fi]  fi: 0=N 1=S 2=E 3=W
    _FDEF_TO_ZONE = {2: 0, 3: 1, 5: 2, 4: 3}  # N S E W

    # Per-zone-face-index rendering info: (brightness, normal)
    _SEG_QUAD_INFO: dict[int, tuple[float, tuple[int, int, int]]] = {
        0: (0.65, ( 0,  0, -1)),  # North
        1: (0.80, ( 0,  0,  1)),  # South
        2: (0.70, ( 1,  0,  0)),  # East
        3: (0.50, (-1,  0,  0)),  # West
    }

    _FACE_HL_MAP = {
        "top":   ((4, 5, 6, 7), ( 0,  1,  0)),
        "bot":   ((0, 3, 2, 1), ( 0, -1,  0)),
        "north": ((0, 1, 5, 4), ( 0,  0, -1)),
        "south": ((2, 3, 7, 6), ( 0,  0,  1)),
        "west":  ((0, 4, 7, 3), (-1,  0,  0)),
        "east":  ((1, 2, 6, 5), ( 1,  0,  0)),
    }

    # ── Main draw entry point ─────────────────────────────────────

    def draw(self, surface: pygame.Surface) -> None:
        surface.fill(COL_BG)
        sw, sh = surface.get_size()
        hw, hh = sw * 0.5, sh * 0.5

        aspect = sw / sh if sh > 0 else 1.0
        proj = _perspective(math.radians(FOV_DEG), aspect, NEAR_CLIP, FAR_CLIP)
        view = _build_view_matrix(
            (self.cam_x, self.cam_y, self.cam_z), self.yaw, self.pitch)
        vp = _mat4_mul(proj, view)

        zone = self.zone
        W, H = zone.width, zone.height

        self._draw_grids(surface, vp, hw, hh, W, H)
        self._draw_axes(surface, vp, hw, hh)
        self._draw_cell_boxes(surface, vp, hw, hh, zone, W, H)
        self._draw_surface_markers(surface, vp, hw, hh, zone, W, H)
        self._draw_seg_boundary_rings(surface, vp, hw, hh, zone, W, H)
        # ── Per-cell tool overlays ──
        self._draw_light_overlay(surface, vp, hw, hh, zone, W, H)
        self._draw_reflect_overlay(surface, vp, hw, hh, zone, W, H)
        self._draw_layer2_slabs(surface, vp, hw, hh, zone, W, H)
        self._draw_fog_overlay(surface, vp, hw, hh, zone, W, H)
        self._draw_entities(surface, vp, hw, hh, zone)
        self._draw_boxes(surface, vp, hw, hh, zone)
        # ── Discrete object overlays ──
        self._draw_quads(surface, vp, hw, hh, zone)
        self._draw_portals(surface, vp, hw, hh, zone)
        self._draw_curves(surface, vp, hw, hh, zone)
        self._draw_selection_highlight(surface, vp, hw, hh, zone)
        self._draw_face_hl_and_preview(surface, vp, hw, hh, sw, sh)
        self._draw_crosshair(surface, sw, sh)
        self._draw_action_context(surface, sw, sh)
        self._draw_hotbar(surface, sw, sh)
        self._draw_hud(surface, sw, sh)

    # ── Sub-methods ───────────────────────────────────────────────

    def _draw_grids(self, surface, vp, hw, hh, W, H):
        pass  # static grids removed; cell edges on walls provide structure

    def _draw_axes(self, surface, vp, hw, hh):
        if not self.show_axes:
            return
        self._line3d(surface, vp, hw, hh, 0, 0, 0, 2, 0, 0, COL_AXIS_X, 2)
        self._line3d(surface, vp, hw, hh, 0, 0, 0, 0, 2, 0, COL_AXIS_Y, 2)
        self._line3d(surface, vp, hw, hh, 0, 0, 0, 0, 0, 2, COL_AXIS_Z, 2)

    # ── Entity markers ────────────────────────────────────────────

    # Selection highlight colour (bright cyan)
    _COL_ENT_SELECTED = (60, 255, 255)
    # Ghost preview colour (translucent white)
    _COL_ENT_GHOST = (200, 200, 255)

    def _draw_entities(self, surface, vp, hw, hh, zone):
        """Draw solid shaded boxes at each entity's position + ghost preview."""
        if not getattr(self, 'show_entities', True):
            return
        entities = getattr(zone, 'entities', None)

        selected_idx = getattr(self, '_ent_selected', None)

        # ── Draw placed entities ──
        if entities:
            for i, ent in enumerate(entities):
                self._draw_one_entity(
                    surface, vp, hw, hh, zone, ent, i,
                    is_selected=(selected_idx is not None and i == selected_idx),
                    ghost=False,
                )

        # ── Ghost preview (entity tool, nothing selected) ──
        if (getattr(self, 'tool', '') == 'entity'
                and selected_idx is None
                and getattr(self, 'aimed', None) is not None):
            self._draw_entity_ghost(surface, vp, hw, hh, zone)

    def _draw_entity_ghost(self, surface, vp, hw, hh, zone):
        """Draw a translucent preview of the entity about to be placed."""
        from core.entity_defs import get_entity_def

        hit = self.aimed
        if hit is None:
            return
        etype = self._ent_current_type()
        edef = get_entity_def(etype)
        if not edef:
            return

        fx, _fy, fz = self._forward()
        ox, _, oz = self.cam_x, self.cam_y, self.cam_z
        wx = ox + fx * hit.t
        wz = oz + fz * hit.t
        wx = max(0.1, min(zone.width - 0.1, wx))
        wz = max(0.1, min(zone.height - 0.1, wz))

        # Build a temporary entity dict for the ghost
        ghost_ent = {
            "type": etype,
            "x": wx,
            "y": wz,
            "angle": 0.0,
            "state": "default",
        }
        self._draw_one_entity(
            surface, vp, hw, hh, zone, ghost_ent, -1,
            is_selected=False, ghost=True,
        )

    def _draw_one_entity(self, surface, vp, hw, hh, zone, ent, idx,
                         is_selected=False, ghost=False):
        """Draw a single entity as a solid shaded box with direction indicator."""
        from core.entity_defs import get_entity_def

        # Resolve position
        if "x" in ent:
            ex = float(ent["x"])
            ez = float(ent["y"])
        else:
            pos = ent.get("position")
            if not pos:
                return
            ex = float(pos.get("x", 0))
            ez = float(pos.get("y", 0))

        # Floor height at entity cell
        ci = max(0, min(zone.width - 1, int(ex)))
        ri = max(0, min(zone.height - 1, int(ez)))
        fh = zone.floor_heights[ri][ci] if zone.floor_heights else 0.0

        # Resolve entity def + scale
        edef = get_entity_def(ent.get("type", ""))
        if edef:
            col = edef.color
            def_scale = edef.scale
        else:
            spr = ent.get("sprite", {})
            color = spr.get("color")
            if color and len(color) >= 3:
                col = (int(color[0]), int(color[1]), int(color[2]))
            else:
                col = (255, 180, 60)
            def_scale = 0.5

        # Per-entity scale override (from properties)
        scale = float(ent.get("properties", {}).get("scale", def_scale))
        half_w = max(scale * 0.22, 0.08)
        height = scale

        # Override visuals for selection / ghost
        if ghost:
            col = self._COL_ENT_GHOST
            alpha = 100
        elif is_selected:
            alpha = 255
        else:
            alpha = 200

        edge_col = self._COL_ENT_SELECTED if is_selected else None

        # Draw the filled box body
        self._filled_box(
            surface, vp, hw, hh,
            ex - half_w, fh, ez - half_w,
            ex + half_w, fh + height, ez + half_w,
            base_color=col,
            edge_color=edge_col if is_selected else (
                min(255, col[0] + 40),
                min(255, col[1] + 40),
                min(255, col[2] + 40),
            ),
            edge_width=3 if is_selected else 1,
            alpha=alpha,
        )

        # Direction indicator line for directional entities
        if edef and edef.directional:
            angle = float(ent.get("angle", 0.0))
            dx = math.cos(angle) * half_w * 3.0
            dz = -math.sin(angle) * half_w * 3.0
            mid_y = fh + height * 0.5
            dir_col = self._COL_ENT_SELECTED if is_selected else (
                min(255, col[0] + 80),
                min(255, col[1] + 80),
                min(255, col[2] + 80),
            )
            self._line3d(surface, vp, hw, hh,
                         ex, mid_y, ez,
                         ex + dx, mid_y, ez + dz,
                         dir_col, 3 if is_selected else 2)
            # Arrow head
            perp_x = -dz * 0.3
            perp_z = dx * 0.3
            tip_x = ex + dx
            tip_z = ez + dz
            self._line3d(surface, vp, hw, hh,
                         tip_x, mid_y, tip_z,
                         tip_x - dx * 0.3 + perp_x, mid_y,
                         tip_z - dz * 0.3 + perp_z,
                         dir_col, 2)
            self._line3d(surface, vp, hw, hh,
                         tip_x, mid_y, tip_z,
                         tip_x - dx * 0.3 - perp_x, mid_y,
                         tip_z - dz * 0.3 - perp_z,
                         dir_col, 2)

        # Label — entity type name rendered at screen position above the box
        if not ghost:
            from editor.view_3d.math3d import _project
            sp = _project(vp, ex, fh + height + 0.12, ez, hw, hh)
            if sp is not None:
                sx, sy = int(sp[0]), int(sp[1])
                sw2, sh2 = int(hw * 2), int(hh * 2)
                if 0 <= sx < sw2 and 0 <= sy < sh2:
                    label = ent.get("type", "?")
                    font = _get_font(11)
                    txt = font.render(label, True,
                                      self._COL_ENT_SELECTED if is_selected
                                      else (220, 220, 220))
                    surface.blit(txt, (sx - txt.get_width() // 2, sy - 14))

    # ── Freeform box markers ──────────────────────────────────────

    _COL_BOX_SELECTED = (255, 200, 60)
    _COL_BOX_GHOST = (255, 210, 140)

    def _draw_boxes(self, surface, vp, hw, hh, zone):
        """Draw freeform boxes as rotated shaded boxes + ghost preview."""
        boxes = getattr(zone, 'boxes', None)
        selected_idx = getattr(self, '_box_selected', None)

        if boxes:
            for i, b in enumerate(boxes):
                bx = float(b.get("x", 0))
                bz = float(b.get("y", 0))
                base_y = float(b.get("z", 0))
                w_ = float(b.get("w", 1))
                h_ = float(b.get("h", 1))
                d_ = float(b.get("d", 1))
                yaw = float(b.get("yaw", 0))

                is_sel = (selected_idx is not None and i == selected_idx)
                col = self._COL_BOX_SELECTED if is_sel else (200, 160, 80)
                edge = self._COL_BOX_SELECTED if is_sel else (160, 130, 60)

                self._filled_rotated_box(
                    surface, vp, hw, hh,
                    bx, bz, w_, h_, d_, base_y, yaw,
                    base_color=col,
                    edge_color=edge,
                    edge_width=3 if is_sel else 1,
                    alpha=255 if is_sel else 180,
                )

        # Ghost preview (box tool, nothing selected)
        if (getattr(self, 'tool', '') == 'box'
                and selected_idx is None
                and getattr(self, 'aimed', None) is not None):
            self._draw_box_ghost(surface, vp, hw, hh, zone)

    def _draw_box_ghost(self, surface, vp, hw, hh, zone):
        """Draw a translucent preview of the prism about to be placed.

        Respects grid-snap and auto-stacking so the ghost shows the
        actual placement position.
        """
        hit = self.aimed
        if hit is None:
            return
        fx, _, fz = self._forward()
        ox, _, oz = self.cam_x, self.cam_y, self.cam_z
        wx = ox + fx * hit.t
        wz = oz + fz * hit.t
        wx = max(0.1, min(zone.width - 0.1, wx))
        wz = max(0.1, min(zone.height - 0.1, wz))

        w, d, h = self._box_w, self._box_d, self._box_h
        wx, wz = self._box_snap_pos(wx, wz)
        fh = self._box_stack_height(wx, wz, w, d)

        self._filled_rotated_box(
            surface, vp, hw, hh,
            wx, wz,
            w, h, d,
            fh, self._box_yaw,
            base_color=self._COL_BOX_GHOST,
            edge_color=(255, 240, 180),
            edge_width=1,
            alpha=80,
        )

    def _draw_cell_boxes(self, surface, vp, hw, hh, zone, W, H):
        aimed = self.aimed
        cam = (self.cam_x, self.cam_y, self.cam_z)
        box_list: list[tuple[float, int, int, str, float, float]] = []

        for r in range(H):
            for c in range(W):
                for part, yb, yt in self._cell_boxes(r, c):
                    mx = c + 0.5
                    my = (yb + yt) * 0.5
                    mz = r + 0.5
                    d = ((cam[0]-mx)**2 + (cam[1]-my)**2 + (cam[2]-mz)**2)
                    box_list.append((d, r, c, part, yb, yt))

        box_list.sort(reverse=True)

        for _, r, c, part, yb, yt in box_list:
            is_aimed = (aimed is not None
                        and aimed.col == c and aimed.row == r
                        and aimed.part == part)

            # Visibility: skip hidden layers entirely
            if part == "wall" and not self.show_walls:
                continue
            if part == "floor" and not self.show_floors:
                continue
            if part == "ceiling" and not self.show_ceilings:
                continue
            alpha = 255

            fcols = self._get_face_colors(r, c, part)
            bcol = self._get_box_color(r, c, part)
            # Only draw edge wireframe on the aimed cell or on walls;
            # floor/ceiling slabs look cleaner without per-cell outlines.
            if is_aimed:
                edge = COL_BLOCK_SEL
                ew = 2
            elif part == "wall":
                edge = COL_EDGE_DIM
                ew = 1
            else:
                edge = None
                ew = 1
            self._filled_box(surface, vp, hw, hh,
                             float(c), yb, float(r),
                             c + 1.0, yt, r + 1.0,
                             bcol, edge, ew, alpha=alpha,
                             face_colors=fcols,
                             wireframe=self.wireframe)
            self._draw_cell_segments(
                surface, vp, hw, hh, r, c, part, alpha)

    def _draw_surface_markers(self, surface, vp, hw, hh, zone, W, H):
        COL_FLOOR_SURF = (180, 230, 140)
        COL_CEIL_SURF  = (140, 170, 230)
        for r in range(H):
            for c in range(W):
                td = tile_def(zone.tiles[r][c])
                if td and td.wall:
                    continue
                fh = zone.floor_heights[r][c] if zone.floor_heights else 0.0
                ch = zone.ceil_heights[r][c] if zone.ceil_heights else 1.0
                if self.show_floors and abs(fh) > 0.01:
                    self._line3d(surface, vp, hw, hh, c, fh, r, c+1, fh, r, COL_FLOOR_SURF, 2)
                    self._line3d(surface, vp, hw, hh, c+1, fh, r, c+1, fh, r+1, COL_FLOOR_SURF, 2)
                    self._line3d(surface, vp, hw, hh, c+1, fh, r+1, c, fh, r+1, COL_FLOOR_SURF, 2)
                    self._line3d(surface, vp, hw, hh, c, fh, r+1, c, fh, r, COL_FLOOR_SURF, 2)
                if self.show_ceilings and ch < SKY_HEIGHT - 0.01:
                    self._line3d(surface, vp, hw, hh, c, ch, r, c+1, ch, r, COL_CEIL_SURF, 2)
                    self._line3d(surface, vp, hw, hh, c+1, ch, r, c+1, ch, r+1, COL_CEIL_SURF, 2)
                    self._line3d(surface, vp, hw, hh, c+1, ch, r+1, c, ch, r+1, COL_CEIL_SURF, 2)
                    self._line3d(surface, vp, hw, hh, c, ch, r+1, c, ch, r, COL_CEIL_SURF, 2)

    _ZONE_FI_FACE = {0: "north", 1: "south", 2: "east", 3: "west"}

    def _draw_seg_boundary_rings(self, surface, vp, hw, hh, zone, W, H):
        """Draw segment boundaries as per-face edges (not full-cell rings)."""
        if not self.show_walls:
            return
        def _draw_seg_edges(seg_grid: list) -> None:
            if not seg_grid:
                return
            for r2 in range(H):
                for c2 in range(W):
                    if r2 >= len(seg_grid) or c2 >= len(seg_grid[r2]):
                        continue
                    for fi2, segs2 in enumerate(seg_grid[r2][c2]):
                        if len(segs2) < 2:
                            continue
                        face = self._ZONE_FI_FACE.get(fi2)
                        if face is None:
                            continue
                        for si2 in range(len(segs2) - 1):
                            y2 = segs2[si2][1]
                            pts = _face_edge_pts(c2, r2, y2, face)
                            if pts:
                                self._line3d(surface, vp, hw, hh,
                                             *pts[0], *pts[1], COL_SEG_LINE, 2)

        _draw_seg_edges(zone.wall_segments)
        _draw_seg_edges(zone.floor_step_segments)
        _draw_seg_edges(zone.ceil_step_segments)

    # ── Per-cell tool overlays ────────────────────────────────────

    def _draw_light_overlay(self, surface, vp, hw, hh, zone, W, H):
        """Draw tinted floor quads showing light levels (active in light tool or when data exists)."""
        if self.tool != "light":
            return
        ll = zone.light_levels
        if not ll:
            return
        from core.tiles import tile_def as _td
        aimed = self.aimed
        for r in range(H):
            for c in range(W):
                v = ll[r][c]
                if abs(v - 1.0) < 0.01:
                    continue  # fully lit, skip
                td = _td(zone.tiles[r][c])
                if td and td.wall:
                    continue
                fh = zone.floor_heights[r][c] if zone.floor_heights else 0.0
                # Darkness overlay: stronger alpha for darker cells
                darkness = 1.0 - v
                alpha = int(darkness * 180) + 20
                if alpha < 10:
                    continue
                is_aim = (aimed and aimed.row == r and aimed.col == c)
                col = COL_TOOL_LIGHT if is_aim else (40, 30, 10)
                a = min(220, alpha + 50) if is_aim else alpha
                self._filled_box(surface, vp, hw, hh,
                                 float(c), fh, float(r),
                                 c + 1.0, fh + 0.02, r + 1.0,
                                 col, COL_TOOL_LIGHT if is_aim else None,
                                 2 if is_aim else 1, alpha=a)

    def _draw_reflect_overlay(self, surface, vp, hw, hh, zone, W, H):
        """Draw blue-tinted floor quads showing reflectivity."""
        if self.tool != "reflect":
            return
        rm = zone.reflect_map
        if not rm:
            return
        from core.tiles import tile_def as _td
        aimed = self.aimed
        for r in range(H):
            for c in range(W):
                v = rm[r][c]
                if v < 1:
                    continue
                td = _td(zone.tiles[r][c])
                if td and td.wall:
                    continue
                fh = zone.floor_heights[r][c] if zone.floor_heights else 0.0
                alpha = int(v / 255.0 * 160) + 40
                is_aim = (aimed and aimed.row == r and aimed.col == c)
                col = COL_TOOL_REFLECT
                a = min(220, alpha + 50) if is_aim else alpha
                self._filled_box(surface, vp, hw, hh,
                                 float(c), fh, float(r),
                                 c + 1.0, fh + 0.02, r + 1.0,
                                 col, col if is_aim else None,
                                 2 if is_aim else 1, alpha=a)

    def _draw_layer2_slabs(self, surface, vp, hw, hh, zone, W, H):
        """Draw secondary floor/ceiling surfaces as wireframe rectangles."""
        f2 = getattr(zone, 'floor2_heights', None)
        c2 = getattr(zone, 'ceil2_heights', None)
        if not f2 and not c2:
            return
        from editor.view_3d.tools_layer2 import LAYER_NONE
        aimed = self.aimed
        is_layer2_mode = getattr(self, '_sculpt_layer2', False)
        target = getattr(self, '_layer2_target', 'floor2')
        for r in range(H):
            for c in range(W):
                is_aim = (aimed and aimed.row == r and aimed.col == c) and is_layer2_mode
                # Floor2
                if f2:
                    fv = f2[r][c]
                    if fv > LAYER_NONE + 1.0:
                        col = COL_TOOL_LAYER2 if (is_aim and target == "floor2") else (160, 120, 200)
                        w = 3 if is_aim else 2
                        self._filled_box(surface, vp, hw, hh,
                                         float(c), fv, float(r),
                                         c + 1.0, fv + 0.04, r + 1.0,
                                         col, col, w, alpha=80 if is_aim else 50)
                # Ceil2
                if c2:
                    cv = c2[r][c]
                    if cv > LAYER_NONE + 1.0:
                        col = (180, 140, 240) if (is_aim and target == "ceil2") else (130, 100, 180)
                        w = 3 if is_aim else 2
                        self._filled_box(surface, vp, hw, hh,
                                         float(c), cv - 0.04, float(r),
                                         c + 1.0, cv, r + 1.0,
                                         col, col, w, alpha=80 if is_aim else 50)

    def _draw_fog_overlay(self, surface, vp, hw, hh, zone, W, H):
        """Draw semi-transparent volumes showing fog density."""
        if self.tool != "fog":
            return
        fd = zone.fog_density
        if not fd:
            return
        from core.tiles import tile_def as _td
        aimed = self.aimed
        for r in range(H):
            for c in range(W):
                v = fd[r][c]
                if v < 0.01:
                    continue
                td = _td(zone.tiles[r][c])
                if td and td.wall:
                    continue
                fh = zone.floor_heights[r][c] if zone.floor_heights else 0.0
                ch = zone.ceil_heights[r][c] if zone.ceil_heights else 1.0
                alpha = int(v * 140) + 30
                is_aim = (aimed and aimed.row == r and aimed.col == c)
                col = COL_TOOL_FOG
                a = min(200, alpha + 50) if is_aim else alpha
                self._filled_box(surface, vp, hw, hh,
                                 float(c) + 0.05, fh + 0.01, float(r) + 0.05,
                                 c + 0.95, ch - 0.01, r + 0.95,
                                 col, col if is_aim else None,
                                 2 if is_aim else 1, alpha=a)

    # ── Discrete object overlays ──────────────────────────────────

    def _draw_quads(self, surface, vp, hw, hh, zone):
        """Draw all quads as vertical rectangles + ghost preview."""
        quads = getattr(zone, 'quads', None)
        selected = getattr(self, '_quad_selected', None)
        if quads:
            for i, q in enumerate(quads):
                qx = float(q.get("x", 0.0))
                qz = float(q.get("z", 0.0))
                by = float(q.get("base_y", 0.0))
                w = float(q.get("width", 1.0))
                h = float(q.get("height", 1.0))
                angle = float(q.get("angle", 0.0))
                is_sel = (selected is not None and i == selected)

                # Compute two endpoints of the quad plane
                cos_a = math.cos(angle)
                sin_a = math.sin(angle)
                hw2 = w * 0.5
                x0 = qx - cos_a * hw2
                z0 = qz + sin_a * hw2
                x1 = qx + cos_a * hw2
                z1 = qz - sin_a * hw2

                col = COL_TOOL_QUAD if is_sel else (200, 110, 140)
                ew = 3 if is_sel else 2
                # Bottom edge
                self._line3d(surface, vp, hw, hh, x0, by, z0, x1, by, z1, col, ew)
                # Top edge
                self._line3d(surface, vp, hw, hh, x0, by + h, z0, x1, by + h, z1, col, ew)
                # Left edge
                self._line3d(surface, vp, hw, hh, x0, by, z0, x0, by + h, z0, col, ew)
                # Right edge
                self._line3d(surface, vp, hw, hh, x1, by, z1, x1, by + h, z1, col, ew)
                # Diagonal cross for visibility (always, not just selected)
                self._line3d(surface, vp, hw, hh, x0, by, z0, x1, by + h, z1, col, 1)
                self._line3d(surface, vp, hw, hh, x1, by, z1, x0, by + h, z0, col, 1)

        # Ghost preview
        if (getattr(self, 'tool', '') == 'quad'
                and selected is None
                and getattr(self, 'aimed', None) is not None):
            self._draw_quad_ghost(surface, vp, hw, hh, zone)

    def _draw_quad_ghost(self, surface, vp, hw, hh, zone):
        """Draw translucent preview of quad about to be placed."""
        hit = self.aimed
        if hit is None:
            return
        fx, _, fz = self._forward()
        ox, _, oz = self.cam_x, self.cam_y, self.cam_z
        wx = ox + fx * hit.t
        wz = oz + fz * hit.t
        wx = max(0.1, min(zone.width - 0.1, wx))
        wz = max(0.1, min(zone.height - 0.1, wz))

        # Apply snap if enabled
        snap = getattr(self, '_quad_snap', 0.25)
        if snap > 0:
            wx = round(wx / snap) * snap
            wz = round(wz / snap) * snap
            wx = max(0.1, min(zone.width - 0.1, wx))
            wz = max(0.1, min(zone.height - 0.1, wz))

        ci = max(0, min(zone.width - 1, int(wx)))
        ri = max(0, min(zone.height - 1, int(wz)))
        fh = zone.floor_heights[ri][ci] if zone.floor_heights else 0.0

        w = getattr(self, '_quad_width', 1.0)
        h = getattr(self, '_quad_height', 1.0)
        yaw = getattr(self, '_quad_yaw', 0.0)
        cos_a = math.cos(yaw)
        sin_a = math.sin(yaw)
        hw2 = w * 0.5
        x0 = wx - cos_a * hw2
        z0 = wz + sin_a * hw2
        x1 = wx + cos_a * hw2
        z1 = wz - sin_a * hw2

        ghost_col = (255, 180, 210)
        self._line3d(surface, vp, hw, hh, x0, fh, z0, x1, fh, z1, ghost_col, 2)
        self._line3d(surface, vp, hw, hh, x0, fh + h, z0, x1, fh + h, z1, ghost_col, 2)
        self._line3d(surface, vp, hw, hh, x0, fh, z0, x0, fh + h, z0, ghost_col, 2)
        self._line3d(surface, vp, hw, hh, x1, fh, z1, x1, fh + h, z1, ghost_col, 2)
        # Diagonal cross
        self._line3d(surface, vp, hw, hh, x0, fh, z0, x1, fh + h, z1, ghost_col, 1)
        self._line3d(surface, vp, hw, hh, x1, fh, z1, x0, fh + h, z0, ghost_col, 1)

    def _draw_portals(self, surface, vp, hw, hh, zone):
        """Draw portal face markers and destination lines."""
        portals = getattr(zone, 'render_portals', None)
        if not portals:
            return
        selected = getattr(self, '_portal_selected', None)
        _face_offsets = {
            0: (0.0, 0.5, "north"),   # N face: z=r, x spans c..c+1
            1: (0.0, 0.5, "south"),   # S face: z=r+1
            2: (0.5, 0.0, "east"),    # E face: x=c+1
            3: (0.5, 0.0, "west"),    # W face: x=c
        }
        _face_corners = {
            0: lambda c, r, fh, ch: [(c, fh, r), (c+1, fh, r), (c+1, ch, r), (c, ch, r)],
            1: lambda c, r, fh, ch: [(c+1, fh, r+1), (c, fh, r+1), (c, ch, r+1), (c+1, ch, r+1)],
            2: lambda c, r, fh, ch: [(c+1, fh, r), (c+1, fh, r+1), (c+1, ch, r+1), (c+1, ch, r)],
            3: lambda c, r, fh, ch: [(c, fh, r+1), (c, fh, r), (c, ch, r), (c, ch, r+1)],
        }

        for i, p in enumerate(portals):
            cell = p.get("cell", [0, 0])
            face = int(p.get("face", 0))
            r, c = int(cell[0]), int(cell[1])
            if r < 0 or r >= zone.height or c < 0 or c >= zone.width:
                continue
            fh = zone.floor_heights[r][c] if zone.floor_heights else 0.0
            ch = zone.ceil_heights[r][c] if zone.ceil_heights else 1.0

            is_sel = (selected is not None and i == selected)
            col = COL_TOOL_PORTAL if is_sel else (60, 200, 180)
            ew = 3 if is_sel else 2

            # Draw portal face outline
            corners_fn = _face_corners.get(face)
            if corners_fn:
                corners = corners_fn(c, r, fh, ch)
                for ci2 in range(4):
                    cj = (ci2 + 1) % 4
                    self._line3d(surface, vp, hw, hh,
                                 *corners[ci2], *corners[cj], col, ew)
                # Fill with translucent colour
                poly = _project_poly(vp, corners, hw, hh)
                if poly is not None:
                    xs = [pt[0] for pt in poly]
                    ys = [pt[1] for pt in poly]
                    sw2, sh2 = int(hw * 2), int(hh * 2)
                    if not (max(xs) < -50 or min(xs) > sw2 + 50
                            or max(ys) < -50 or min(ys) > sh2 + 50):
                        try:
                            min_x = max(0, min(xs))
                            min_y = max(0, min(ys))
                            max_x = min(sw2, max(xs))
                            max_y = min(sh2, max(ys))
                            tw = max_x - min_x + 1
                            th = max_y - min_y + 1
                            if tw > 0 and th > 0:
                                tmp = pygame.Surface((tw, th), pygame.SRCALPHA)
                                off = [(px - min_x, py - min_y) for px, py in poly]
                                fill_a = 80 if is_sel else 40
                                pygame.draw.polygon(tmp, (*col, fill_a), off)
                                surface.blit(tmp, (min_x, min_y))
                        except (ValueError, OverflowError):
                            pass

            # Destination line for selected portal
            if is_sel:
                dx = float(p.get("dest_x", c + 0.5))
                dy = float(p.get("dest_y", r + 0.5))
                mid_y = (fh + ch) * 0.5
                face_cx = c + 0.5
                face_cz = r + 0.5
                if face == 0:
                    face_cz = float(r)
                elif face == 1:
                    face_cz = float(r + 1)
                elif face == 2:
                    face_cx = float(c + 1)
                elif face == 3:
                    face_cx = float(c)
                self._line3d(surface, vp, hw, hh,
                             face_cx, mid_y, face_cz,
                             dx, mid_y, dy,
                             (255, 255, 100), 2)
                # Destination marker
                self._line3d(surface, vp, hw, hh,
                             dx - 0.1, mid_y - 0.1, dy,
                             dx + 0.1, mid_y + 0.1, dy,
                             (255, 255, 100), 2)
                self._line3d(surface, vp, hw, hh,
                             dx, mid_y - 0.1, dy - 0.1,
                             dx, mid_y + 0.1, dy + 0.1,
                             (255, 255, 100), 2)

    def _draw_curves(self, surface, vp, hw, hh, zone):
        """Draw all curves as arc wireframes + ghost preview."""
        curves = getattr(zone, 'curves', None)
        selected = getattr(self, '_curve_selected', None)
        N_SAMPLES = 16  # arc sample count

        if curves:
            for i, cv in enumerate(curves):
                cx = float(cv.get("cx", 0.0))
                cy = float(cv.get("cy", 0.0))
                rad = float(cv.get("radius", 1.0))
                a0 = float(cv.get("angle_start", 0.0))
                a1 = float(cv.get("angle_end", math.pi))
                hs = float(cv.get("height_scale", 1.0))
                by = float(cv.get("base_y", 0.0))

                is_sel = (selected is not None and i == selected)
                col = COL_TOOL_CURVE if is_sel else (200, 160, 80)
                ew = 3 if is_sel else 1

                # Sample arc points
                pts = []
                for s in range(N_SAMPLES + 1):
                    t = s / N_SAMPLES
                    a = a0 + (a1 - a0) * t
                    px = cx + rad * math.cos(a)
                    pz = cy + rad * math.sin(a)
                    pts.append((px, pz))

                # Bottom arc
                for j in range(len(pts) - 1):
                    self._line3d(surface, vp, hw, hh,
                                 pts[j][0], by, pts[j][1],
                                 pts[j+1][0], by, pts[j+1][1],
                                 col, ew)
                # Top arc
                top_y = by + hs
                for j in range(len(pts) - 1):
                    self._line3d(surface, vp, hw, hh,
                                 pts[j][0], top_y, pts[j][1],
                                 pts[j+1][0], top_y, pts[j+1][1],
                                 col, ew)
                # Vertical edges (at endpoints and a few samples)
                for j in (0, N_SAMPLES // 4, N_SAMPLES // 2,
                          3 * N_SAMPLES // 4, N_SAMPLES):
                    if j < len(pts):
                        self._line3d(surface, vp, hw, hh,
                                     pts[j][0], by, pts[j][1],
                                     pts[j][0], top_y, pts[j][1],
                                     col, ew)

                # Centre marker for selected
                if is_sel:
                    mid_y = by + hs * 0.5
                    self._line3d(surface, vp, hw, hh,
                                 cx - 0.1, mid_y, cy,
                                 cx + 0.1, mid_y, cy,
                                 (255, 255, 200), 2)
                    self._line3d(surface, vp, hw, hh,
                                 cx, mid_y, cy - 0.1,
                                 cx, mid_y, cy + 0.1,
                                 (255, 255, 200), 2)

        # Ghost preview
        if (getattr(self, 'tool', '') == 'curve'
                and selected is None
                and getattr(self, 'aimed', None) is not None):
            self._draw_curve_ghost(surface, vp, hw, hh, zone, N_SAMPLES)

    def _draw_curve_ghost(self, surface, vp, hw, hh, zone, n_samples):
        """Draw translucent preview of curve about to be placed."""
        hit = self.aimed
        if hit is None:
            return
        fx, _, fz = self._forward()
        ox, _, oz = self.cam_x, self.cam_y, self.cam_z
        wx = ox + fx * hit.t
        wz = oz + fz * hit.t
        wx = max(0.1, min(zone.width - 0.1, wx))
        wz = max(0.1, min(zone.height - 0.1, wz))
        ci = max(0, min(zone.width - 1, int(wx)))
        ri = max(0, min(zone.height - 1, int(wz)))
        fh = zone.floor_heights[ri][ci] if zone.floor_heights else 0.0

        rad = getattr(self, '_curve_radius', 1.0)
        ghost_col = (220, 190, 130)
        a0 = 0.0
        a1 = math.pi
        pts = []
        for s in range(n_samples + 1):
            t = s / n_samples
            a = a0 + (a1 - a0) * t
            px = wx + rad * math.cos(a)
            pz = wz + rad * math.sin(a)
            pts.append((px, pz))
        for j in range(len(pts) - 1):
            self._line3d(surface, vp, hw, hh,
                         pts[j][0], fh, pts[j][1],
                         pts[j+1][0], fh, pts[j+1][1],
                         ghost_col, 1)
            self._line3d(surface, vp, hw, hh,
                         pts[j][0], fh + 1.0, pts[j][1],
                         pts[j+1][0], fh + 1.0, pts[j+1][1],
                         ghost_col, 1)
        for j in (0, n_samples):
            if j < len(pts):
                self._line3d(surface, vp, hw, hh,
                             pts[j][0], fh, pts[j][1],
                             pts[j][0], fh + 1.0, pts[j][1],
                             ghost_col, 1)

    def _draw_face_hl_and_preview(self, surface, vp, hw, hh, sw, sh):
        aimed = self.aimed
        if aimed is not None and aimed.face != "ground":
            self._draw_face_highlight(surface, vp, hw, hh, aimed)

        # Segment merge-target: highlight the boundary nearest to crosshair
        if self.tool == "segment" and aimed is not None:
            self._draw_merge_target(surface, vp, hw, hh)

        if self.preview_box is not None:
            gc, gr, gy0, gy1, gcol = self.preview_box
            self._filled_box(surface, vp, hw, hh,
                             float(gc), gy0, float(gr),
                             gc + 1.0, gy1, gr + 1.0,
                             gcol, gcol, 2, alpha=100)

        if self.preview_line is not None:
            lc, lr, ly, lcol = self.preview_line[:4]
            face = self.preview_line[4] if len(self.preview_line) > 4 else None
            if face is None:
                # Full perimeter ring (sculpt preview)
                self._line3d(surface, vp, hw, hh, lc, ly, lr, lc + 1, ly, lr, lcol, 2)
                self._line3d(surface, vp, hw, hh, lc + 1, ly, lr, lc + 1, ly, lr + 1, lcol, 2)
                self._line3d(surface, vp, hw, hh, lc + 1, ly, lr + 1, lc, ly, lr + 1, lcol, 2)
                self._line3d(surface, vp, hw, hh, lc, ly, lr + 1, lc, ly, lr, lcol, 2)
            else:
                # Single-face edge (segment split preview)
                pts = _face_edge_pts(lc, lr, ly, face)
                if pts:
                    self._line3d(surface, vp, hw, hh, *pts[0], *pts[1], lcol, 3)

    def _draw_crosshair(self, surface, sw, sh):
        is_layer2 = (self.tool == "sculpt"
                     and getattr(self, '_sculpt_layer2', False))
        tool_col = COL_TOOL_LAYER2 if is_layer2 else TOOL_COLORS.get(self.tool, COL_CROSSHAIR)
        cx, cy = sw // 2, sh // 2

        # Inner crosshair lines + dot
        pygame.draw.line(surface, tool_col, (cx - 14, cy), (cx - 4, cy), 2)
        pygame.draw.line(surface, tool_col, (cx + 4, cy), (cx + 14, cy), 2)
        pygame.draw.line(surface, tool_col, (cx, cy - 14), (cx, cy - 4), 2)
        pygame.draw.line(surface, tool_col, (cx, cy + 4), (cx, cy + 14), 2)
        pygame.draw.circle(surface, tool_col, (cx, cy), 2)

        # Layer 2 mode: outer diamond + "L2" badge
        if is_layer2:
            d = 20
            pts = [(cx, cy - d), (cx + d, cy), (cx, cy + d), (cx - d, cy)]
            pygame.draw.polygon(surface, tool_col, pts, 2)

            font = _get_font(12)
            tgt = getattr(self, '_layer2_target', 'floor2')
            badge = "L2:FLOOR" if tgt == "floor2" else "L2:CEIL"
            badge_img = font.render(badge, True, tool_col)
            bw, bh = badge_img.get_size()
            badge_x = cx - bw // 2
            badge_y = cy - d - bh - 4
            bg = pygame.Surface((bw + 8, bh + 4), pygame.SRCALPHA)
            bg.fill((0, 0, 0, 160))
            surface.blit(bg, (badge_x - 4, badge_y - 2))
            surface.blit(badge_img, (badge_x, badge_y))

        if self.aimed:
            zone_a = self.zone
            fh_a = zone_a.floor_heights[self.aimed.row][self.aimed.col]
            ch_a = zone_a.ceil_heights[self.aimed.row][self.aimed.col]
            is_sky = ch_a >= SKY_HEIGHT - 0.01
            if abs(fh_a) > 0.01:
                tick_len = min(int(abs(fh_a) * 8), 20)
                pygame.draw.line(surface, (180, 230, 140),
                                 (cx - 18, cy + 2), (cx - 18, cy + 2 + tick_len), 3)
            if not is_sky:
                tick_len = min(int(ch_a * 8), 20)
                pygame.draw.line(surface, (140, 170, 230),
                                 (cx - 18, cy - 2), (cx - 18, cy - 2 - tick_len), 3)

    # ── Action context overlay ────────────────────────────────────

    def _draw_action_context(self, surface: pygame.Surface, sw: int, sh: int) -> None:
        """Show LMB/RMB/Scroll actions near the crosshair based on tool + aimed part."""
        if not self.show_hud:
            return
        hint = TOOL_HINTS.get(self.tool)
        if hint is None:
            return
        actions_dict = hint.get("actions", {})

        # Pick the best matching action set for current context
        part = self.aimed.part if self.aimed else None
        tool = self.tool

        if tool == "select":
            if self._sel_start is not None and self._sel_end is not None:
                ctx_key = "active"
            elif self._sel_start is not None:
                ctx_key = "started"
            else:
                ctx_key = "none"
        elif tool == "sculpt":
            if getattr(self, '_sculpt_layer2', False):
                ctx_key = "layer2"
            elif part == "ceiling":
                ctx_key = "ceiling"
            elif part in ("floor", "wall", "ground"):
                ctx_key = "floor"
            else:
                ctx_key = "none"
        elif tool == "box":
            ctx_key = "selected" if getattr(self, '_box_selected', None) is not None else "unselected"
        else:
            ctx_key = "any"

        actions = actions_dict.get(ctx_key, actions_dict.get("any", {}))
        if not actions:
            return

        font = _get_font(12)
        lh = font.get_linesize()
        cx, cy = sw // 2, sh // 2
        start_y = cy + 26

        tool_col = TOOL_COLORS.get(self.tool, COL_HUD_TEXT)
        dim_col = (180, 180, 180)

        lines: list[tuple[str, tuple[int, int, int]]] = []
        for key, desc in actions.items():
            lines.append((f"{key}: {desc}", dim_col))

        if not lines:
            return

        # Compute background width
        max_w = max(font.size(t)[0] for t, _ in lines)
        bg_w = max_w + 12
        bg_h = len(lines) * lh + 8
        bg_x = cx - bg_w // 2
        bg_y = start_y

        is_layer2 = (self.tool == "sculpt"
                     and getattr(self, '_sculpt_layer2', False))
        bg = pygame.Surface((bg_w, bg_h), pygame.SRCALPHA)
        if is_layer2:
            bg.fill((60, 30, 80, 150))
        else:
            bg.fill((0, 0, 0, 120))
        surface.blit(bg, (bg_x, bg_y))

        for i, (text, col) in enumerate(lines):
            # Use layer2 colour for action text when in layer2 sub-mode
            text_col = COL_TOOL_LAYER2 if is_layer2 else col
            img = font.render(text, True, text_col)
            surface.blit(img, (bg_x + 6, bg_y + 4 + i * lh))

    # ── Selection highlight ───────────────────────────────────────

    def _draw_selection_highlight(self, surface: pygame.Surface, vp, hw, hh, zone) -> None:
        """Draw highlighted cells for the rectangular selection tool."""
        bounds = getattr(self, '_sel_bounds', None)
        if bounds is None:
            return
        ceiling_mode = getattr(self, '_sel_ceiling_mode', False)
        col = COL_TOOL_CEILING if ceiling_mode else COL_TOOL_SELECT

        result = bounds()
        if result is None:
            # Partial selection: just highlight start corner
            start = getattr(self, '_sel_start', None)
            if start is None:
                return
            r, c = start
            if ceiling_mode:
                ch = zone.ceil_heights[r][c]
                h = ch - 0.05
            else:
                h = zone.floor_heights[r][c]
            self._filled_box(surface, vp, hw, hh,
                             float(c), h, float(r),
                             c + 1.0, h + 0.05, r + 1.0,
                             col, col, 2, alpha=100)
            return

        r_min, c_min, r_max, c_max = result
        for r in range(r_min, r_max + 1):
            for c in range(c_min, c_max + 1):
                if ceiling_mode:
                    ch = zone.ceil_heights[r][c]
                    h = ch - 0.05
                else:
                    h = zone.floor_heights[r][c]
                self._filled_box(surface, vp, hw, hh,
                                 float(c), h, float(r),
                                 c + 1.0, h + 0.05, r + 1.0,
                                 col, col, 1, alpha=60)

    # ── Hotbar ─────────────────────────────────────────────────────

    def _draw_hotbar(self, surface: pygame.Surface, sw: int, sh: int) -> None:
        """Draw 10 texture-colour slots centred at the bottom of the viewport."""
        if not self.show_hud:
            return

        slot_size = 32
        gap = 4
        total_w = HOTBAR_SIZE * slot_size + (HOTBAR_SIZE - 1) * gap
        x0 = (sw - total_w) // 2
        y0 = sh - slot_size - 12  # 12px margin from bottom

        font = _get_font(11)
        active = getattr(self, 'hotbar_slot', 0)
        hotbar = getattr(self, 'hotbar', [''] * HOTBAR_SIZE)

        # Background bar
        bg = pygame.Surface((total_w + 8, slot_size + 8), pygame.SRCALPHA)
        bg.fill((0, 0, 0, 140))
        surface.blit(bg, (x0 - 4, y0 - 4))

        for i in range(HOTBAR_SIZE):
            x = x0 + i * (slot_size + gap)
            tex = hotbar[i] if i < len(hotbar) else ''

            # Slot colour from TILE_COLORS
            c = TILE_COLORS.get(tex) if tex else None
            if c:
                fill = (min(255, c[0] + 40), min(255, c[1] + 40), min(255, c[2] + 40))
            else:
                fill = (50, 50, 50)

            rect = pygame.Rect(x, y0, slot_size, slot_size)
            pygame.draw.rect(surface, fill, rect)

            # Active-slot highlight
            if i == active:
                pygame.draw.rect(surface, (255, 255, 255), rect, 2)
            else:
                pygame.draw.rect(surface, (100, 100, 100), rect, 1)

            # Slot number label (1-9, 0)
            label = str((i + 1) % 10)
            lbl_img = font.render(label, True, (200, 200, 200))
            surface.blit(lbl_img, (x + 2, y0 + 1))

    # ── HUD ───────────────────────────────────────────────────────

    def _draw_hud(self, surface: pygame.Surface, sw: int, sh: int) -> None:
        if not self.show_hud:
            return
        font = _get_font(14)
        lh = font.get_linesize()
        pad = 6
        x0, y0 = pad, pad

        lines: list[tuple[str, tuple[int, int, int]]] = []

        tool_label = TOOL_LABELS.get(self.tool, self.tool.upper())
        tool_col = TOOL_COLORS.get(self.tool, COL_HUD_TEXT)
        lines.append((f"Tool: {tool_label}", tool_col))
        if self.tool == "select":
            mode = "Ceiling" if getattr(self, '_sel_ceiling_mode', False) else "Floor"
            lines.append((f"Mode: {mode}  (X to toggle)", COL_HUD_VAL))
        lines.append((f"Snap: {self.snap_y}", COL_HUD_VAL))
        lines.append((f"Tex: {self.current_texture}", COL_HUD_VAL))
        if self.tool == "stamp":
            preset = self._stamp_current()
            pname = preset.name if preset else "(none)"
            lines.append((f"Preset: {pname}", (180, 140, 255)))
            mode_str = getattr(self, '_stamp_current_mode', lambda: "replace")()
            lines.append((f"Mode: {mode_str}  (M)", (160, 200, 255)))
            if getattr(self, '_capture_pending', False):
                cap_name = getattr(self, '_capture_name', '')
                lines.append(("", COL_HUD_TEXT))
                lines.append(("CAPTURE NAME:", (255, 220, 80)))
                lines.append((f"> {cap_name}_", (255, 255, 200)))

        # ── New tool HUD info ─────────────────────────────────────
        if self.tool == "sculpt" and getattr(self, '_sculpt_layer2', False):
            tgt = getattr(self, '_layer2_target', 'floor2')
            lines.append((f"[Layer 2]  Target: {tgt}", COL_TOOL_LAYER2))
        elif self.tool == "light":
            step = getattr(self, '_light_step', 0.1)
            lines.append((f"Step: {step:.2f}", COL_TOOL_LIGHT))
        elif self.tool == "reflect":
            step = getattr(self, '_reflect_step', 32)
            lines.append((f"Step: {step}", COL_TOOL_REFLECT))
        elif self.tool == "quad":
            sel = getattr(self, '_quad_selected', None)
            snap = getattr(self, '_quad_snap', 0.25)
            snap_str = f"{snap:.2f}" if snap > 0 else "OFF"
            lines.append((f"Snap: {snap_str}  (G)", COL_TOOL_QUAD))
            if sel is not None:
                lines.append((f"Quad #{sel} selected", COL_TOOL_QUAD))
            else:
                w = getattr(self, '_quad_width', 1.0)
                h = getattr(self, '_quad_height', 1.0)
                lines.append((f"Size: {w:.1f}x{h:.1f}", COL_TOOL_QUAD))
        elif self.tool == "portal":
            sel = getattr(self, '_portal_selected', None)
            if sel is not None:
                lines.append((f"Portal #{sel} selected", COL_TOOL_PORTAL))
        elif self.tool == "curve":
            sel = getattr(self, '_curve_selected', None)
            if sel is not None:
                lines.append((f"Curve #{sel} selected", COL_TOOL_CURVE))
            else:
                rad = getattr(self, '_curve_radius', 1.0)
                lines.append((f"Radius: {rad:.2f}", COL_TOOL_CURVE))
        elif self.tool == "fog":
            step = getattr(self, '_fog_step', 0.1)
            lines.append((f"Step: {step:.2f}", COL_TOOL_FOG))
        elif self.tool == "box":
            sel = getattr(self, '_box_selected', None)
            snap = getattr(self, '_box_snap', True)
            snap_str = "ON" if snap else "OFF"
            lines.append((f"Snap: {snap_str}  (G)", COL_TOOL_BOX))
            if sel is not None:
                lines.append((f"Prism #{sel} selected", COL_TOOL_BOX))
            else:
                w = getattr(self, '_box_w', 1.0)
                h = getattr(self, '_box_h', 1.0)
                d = getattr(self, '_box_d', 1.0)
                lines.append((f"Size: {w:.2f}w × {d:.2f}d × {h:.2f}h", COL_TOOL_BOX))

        hit = self.aimed
        if hit:
            zone = self.zone
            r, c = hit.row, hit.col
            fh = zone.floor_heights[r][c]
            ch = zone.ceil_heights[r][c]
            is_sky = ch >= SKY_HEIGHT - 0.01
            uwh = 0.0
            if zone.upper_wall_height and len(zone.upper_wall_height) > r:
                uwh = zone.upper_wall_height[r][c]

            lines.append(("", COL_HUD_TEXT))
            lines.append((f"Cell: ({c}, {r})  {hit.part}", COL_HUD_TITLE))
            lines.append((f"Floor: {fh:.2f}", (180, 230, 140)))
            ceil_str = "SKY" if is_sky else f"{ch:.2f}"
            lines.append((f"Ceil:  {ceil_str}", (140, 170, 230)))
            if uwh > ch + 0.01 and not is_sky:
                lines.append((f"UWH:   {uwh:.2f}", (200, 180, 120)))
            if hit.face and hit.face != "ground":
                lines.append((f"Face: {hit.face}", COL_HUD_TEXT))

            fi = self._FACE_IDX_MAP.get(hit.face, -1)
            if fi >= 0:
                self._ensure_face_textures()
                td = tile_def(zone.tiles[r][c])
                if td and td.wall:
                    n_seg = len(zone.wall_segments[r][c][fi])
                elif hit.part == "floor":
                    n_seg = len(zone.floor_step_segments[r][c][fi])
                elif hit.part == "ceiling":
                    n_seg = len(zone.ceil_step_segments[r][c][fi])
                else:
                    n_seg = 0
                if n_seg > 0:
                    lines.append((f"Segs: {n_seg}", (200, 160, 220)))
                    info = self._seg_face_info()
                    if info is not None:
                        _r, _c, _fi2, segs, band_bot, band_top, hy, _stype = info
                        if segs:
                            idx = self._aimed_segment_idx()
                            if 0 <= idx < len(segs):
                                seg_tex = segs[idx][0] or "(none)"
                                seg_bot = band_bot
                                for si in range(idx):
                                    seg_bot = segs[si][1]
                                seg_top_val = segs[idx][1]
                                lines.append(
                                    (f" #{idx}: {seg_tex}", (220, 200, 140)))
                                lines.append(
                                    (f" Y: {seg_bot:.2f}..{seg_top_val:.2f}",
                                     (180, 180, 180)))

            # Tool-specific cell data
            if self.tool == "light":
                ll = zone.light_levels
                lv = ll[r][c] if ll and r < len(ll) and c < len(ll[r]) else 1.0
                lines.append((f"Light: {lv:.2f}", COL_TOOL_LIGHT))
            elif self.tool == "reflect":
                rm = zone.reflect_map
                rv = rm[r][c] if rm and r < len(rm) and c < len(rm[r]) else 0
                lines.append((f"Reflect: {rv}", COL_TOOL_REFLECT))
            elif getattr(self, '_sculpt_layer2', False):
                from editor.view_3d.tools_layer2 import LAYER_NONE as _LN
                f2 = getattr(zone, 'floor2_heights', None)
                c2h = getattr(zone, 'ceil2_heights', None)
                fv = f2[r][c] if f2 and r < len(f2) and c < len(f2[r]) else _LN
                cv = c2h[r][c] if c2h and r < len(c2h) and c < len(c2h[r]) else _LN
                f_str = f"{fv:.2f}" if fv > _LN + 1 else "\u2014"
                c_str = f"{cv:.2f}" if cv > _LN + 1 else "\u2014"
                lines.append((f"Floor2: {f_str}  Ceil2: {c_str}", COL_TOOL_LAYER2))
            elif self.tool == "fog":
                fd = zone.fog_density
                fv = fd[r][c] if fd and r < len(fd) and c < len(fd[r]) else 0.0
                lines.append((f"Fog: {fv:.2f}", COL_TOOL_FOG))

        max_w = max((font.size(t)[0] for t, _ in lines if t), default=80)
        bg_h = len(lines) * lh + pad * 2
        bg_w = max_w + pad * 2
        bg = pygame.Surface((bg_w, bg_h), pygame.SRCALPHA)
        bg.fill(COL_HUD_BG)
        surface.blit(bg, (x0, y0))

        for i, (text, col) in enumerate(lines):
            if not text:
                continue
            img = font.render(text, True, col)
            surface.blit(img, (x0 + pad, y0 + pad + i * lh))

    # ── Face highlight ────────────────────────────────────────────

    def _draw_face_highlight(
        self, surface: pygame.Surface, vp: list[float],
        hw: float, hh: float, hit: _CellHit,
    ) -> None:
        """Draw a translucent highlight on the aimed face / segment band."""
        face_info = self._FACE_HL_MAP.get(hit.face)
        if face_info is None:
            return
        indices, normal = face_info

        c, r = hit.col, hit.row
        y0, y1 = None, None
        for part, yb, yt in self._cell_boxes(r, c):
            if part == hit.part:
                y0, y1 = yb, yt
                break
        if y0 is None:
            return

        seg_y0, seg_y1 = y0, y1
        if hit.face in ("north", "south", "east", "west"):
            info = self._seg_face_info()
            if info is not None:
                _r, _c, _fi, segs, band_bot, band_top, hy, _stype = info
                if segs:
                    idx = self._aimed_segment_idx()
                    if 0 <= idx < len(segs):
                        bot = band_bot
                        for si in range(idx):
                            bot = segs[si][1]
                        seg_y0 = bot
                        seg_y1 = segs[idx][1]

        x0, z0 = float(c), float(r)
        x1, z1 = c + 1.0, r + 1.0
        corners = [
            (x0, seg_y0, z0), (x1, seg_y0, z0),
            (x1, seg_y0, z1), (x0, seg_y0, z1),
            (x0, seg_y1, z0), (x1, seg_y1, z0),
            (x1, seg_y1, z1), (x0, seg_y1, z1),
        ]
        face_corners = [corners[i] for i in indices]
        poly = _project_poly(vp, face_corners, hw, hh)
        if poly is None:
            return
        xs = [p[0] for p in poly]
        ys = [p[1] for p in poly]
        sw2, sh2 = int(hw * 2), int(hh * 2)
        if max(xs) < -50 or min(xs) > sw2 + 50:
            return
        if max(ys) < -50 or min(ys) > sh2 + 50:
            return

        tool_col = TOOL_COLORS.get(self.tool, COL_CROSSHAIR)
        try:
            min_x = max(0, min(xs))
            min_y = max(0, min(ys))
            max_x = min(sw2, max(xs))
            max_y = min(sh2, max(ys))
            tw = max_x - min_x + 1
            th = max_y - min_y + 1
            if tw > 0 and th > 0:
                is_seg = self.tool == "segment"
                fill_a = 90 if self.tool == "paint" else (100 if is_seg else 60)
                edge_a = 150 if self.tool == "paint" else (180 if is_seg else 100)
                edge_w = 3 if self.tool in ("paint", "segment") else 2
                tmp = pygame.Surface((tw, th), pygame.SRCALPHA)
                off = [(px - min_x, py - min_y) for px, py in poly]
                pygame.draw.polygon(tmp, (*tool_col[:3], fill_a), off)
                surface.blit(tmp, (min_x, min_y))
                pygame.draw.polygon(tmp, (*tool_col[:3], edge_a), off, edge_w)
                surface.blit(tmp, (min_x, min_y))
        except (ValueError, OverflowError):
            pass

    def _draw_merge_target(
        self, surface: pygame.Surface, vp: list[float],
        hw: float, hh: float,
    ) -> None:
        """Highlight the segment boundary nearest to crosshair (merge target) in red."""
        info = self._seg_face_info()
        if info is None:
            return
        r, c, fi, segs, y_bot, y_top, hy, seg_type = info
        if len(segs) < 2:
            return
        face = self._ZONE_FI_FACE.get(fi)
        if face is None:
            return
        # Find nearest internal boundary (same logic as _seg_merge)
        best_dist = float("inf")
        best_y = None
        bot = y_bot
        for i, (stex, ytop) in enumerate(segs):
            if i > 0:
                d = abs(hy - bot)
                if d < best_dist:
                    best_dist = d
                    best_y = bot
            bot = ytop
        if best_y is not None:
            pts = _face_edge_pts(c, r, best_y, face)
            if pts:
                self._line3d(surface, vp, hw, hh,
                             *pts[0], *pts[1], COL_SEG_MERGE, 3)

    # ── Segment overdraw ──────────────────────────────────────────

    @staticmethod
    def _seg_quad_pts(
        zone_fi: int, c: int, r: int, sb: float, st: float,
    ) -> list[tuple[float, float, float]]:
        """Return 4 corners for a segment band quad."""
        x0, x1 = float(c), float(c + 1)
        z0, z1 = float(r), float(r + 1)
        if zone_fi == 0:  # North
            return [(x0, sb, z0), (x1, sb, z0), (x1, st, z0), (x0, st, z0)]
        if zone_fi == 1:  # South
            return [(x1, sb, z1), (x0, sb, z1), (x0, st, z1), (x1, st, z1)]
        if zone_fi == 2:  # East
            return [(x1, sb, z0), (x1, sb, z1), (x1, st, z1), (x1, st, z0)]
        # West
        return [(x0, sb, z1), (x0, sb, z0), (x0, st, z0), (x0, st, z1)]

    def _draw_cell_segments(
        self, surface: pygame.Surface, vp: list[float],
        hw: float, hh: float,
        r: int, c: int, part: str, alpha: int = 255,
    ) -> None:
        """Overdraw per-segment colour bands on faces with >= 2 segments."""
        zone = self.zone
        td = tile_def(zone.tiles[r][c])
        is_wall = td is not None and td.wall
        self._ensure_face_textures()

        cam = (self.cam_x, self.cam_y, self.cam_z)
        use_alpha = alpha < 255
        sw2, sh2 = int(hw * 2), int(hh * 2)

        for zone_fi in range(4):
            if is_wall:
                segs = zone.wall_segments[r][c][zone_fi]
                fh = zone.floor_heights[r][c]
                y_bot = fh
            elif part == "floor":
                segs = zone.floor_step_segments[r][c][zone_fi]
                fh = zone.floor_heights[r][c]
                y_bot = min(0.0, fh)
            elif part == "ceiling":
                segs = zone.ceil_step_segments[r][c][zone_fi]
                ch = zone.ceil_heights[r][c]
                y_bot = ch
            else:
                continue

            if len(segs) < 2:
                continue

            brightness, normal = self._SEG_QUAD_INFO[zone_fi]
            nx, ny, nz = normal

            fcx = c + 0.5 + nx * 0.5
            fcz = r + 0.5 + nz * 0.5
            dx = cam[0] - fcx
            dz = cam[2] - fcz
            if dx * nx + dz * nz <= 0:
                continue

            bot = y_bot
            for stex, ytop in segs:
                color = self._tile_color(stex) if stex else COL_WALL_DEF
                corners = self._seg_quad_pts(zone_fi, c, r, bot, ytop)
                poly = _project_poly(vp, corners, hw, hh)
                if poly is None:
                    bot = ytop
                    continue
                xs = [p[0] for p in poly]
                ys = [p[1] for p in poly]
                if max(xs) < -50 or min(xs) > sw2 + 50:
                    bot = ytop
                    continue
                if max(ys) < -50 or min(ys) > sh2 + 50:
                    bot = ytop
                    continue
                ri = min(255, int(color[0] * brightness))
                gi = min(255, int(color[1] * brightness))
                bi = min(255, int(color[2] * brightness))
                try:
                    if use_alpha:
                        min_x = max(0, min(xs))
                        min_y = max(0, min(ys))
                        max_x = min(sw2, max(xs))
                        max_y = min(sh2, max(ys))
                        tw = max_x - min_x + 1
                        th = max_y - min_y + 1
                        if tw > 0 and th > 0:
                            tmp = pygame.Surface((tw, th), pygame.SRCALPHA)
                            off = [(px - min_x, py - min_y)
                                   for px, py in poly]
                            pygame.draw.polygon(
                                tmp, (ri, gi, bi, alpha), off)
                            surface.blit(tmp, (min_x, min_y))
                    else:
                        pygame.draw.polygon(surface, (ri, gi, bi), poly)
                except (ValueError, OverflowError):
                    pass
                bot = ytop

    # ── Colour helpers ────────────────────────────────────────────

    def _resolve_floor_tex(self, r: int, c: int) -> str:
        """Return the effective floor texture key for a cell.

        Priority: floor_textures override -> base tile from tiles[].
        This matches the raycaster's fallback logic.
        """
        zone = self.zone
        if zone.floor_textures:
            tex = zone.floor_textures[r][c]
            if tex:
                return tex
        return zone.tiles[r][c]

    def _resolve_ceil_tex(self, r: int, c: int) -> str:
        """Return the effective ceiling texture key for a cell.

        Priority: ceil_textures override -> 'concrete' default
        (matching the raycaster).
        """
        zone = self.zone
        if zone.ceil_textures:
            tex = zone.ceil_textures[r][c]
            if tex:
                return tex
        return "concrete"

    def _get_box_color(self, r: int, c: int, part: str
                       ) -> tuple[int, int, int]:
        zone = self.zone
        if part == "wall":
            if zone.face_textures and zone.face_textures[r][c]:
                ft = zone.face_textures[r][c]
                tex = ft[0] or ft[1] or ft[2] or ft[3]
                if tex:
                    col = self._tile_color(tex)
                else:
                    col = self._tile_color(zone.tiles[r][c])
            elif zone.wall_textures and zone.wall_textures[r][c]:
                col = self._tile_color(zone.wall_textures[r][c])
            else:
                col = self._tile_color(zone.tiles[r][c])
        elif part == "floor":
            col = self._tile_color(self._resolve_floor_tex(r, c))
        elif part == "ceiling":
            col = self._tile_color(self._resolve_ceil_tex(r, c))
        else:
            col = COL_WALL_DEF
        return self._apply_cell_effects(col, r, c, part)

    def _get_face_colors(self, r: int, c: int, part: str
                         ) -> list[tuple[int, int, int]]:
        """Return 6 per-face colours in ``_FACE_DEFS`` order."""
        zone = self.zone
        tc = self._tile_color
        base = self._get_box_color(r, c, part)
        cols: list[tuple[int, int, int]] = [base] * 6

        self._ensure_face_textures()

        td = tile_def(zone.tiles[r][c])
        is_wall = td is not None and td.wall

        if part == "floor":
            ftex = self._resolve_floor_tex(r, c)
            cols[0] = tc(ftex)
            # Bottom face of a floor mass: slightly darker base
            cols[1] = self._darken(tc(ftex), 0.65)
        elif part == "ceiling":
            ctex = self._resolve_ceil_tex(r, c)
            # Top face of ceiling mass: slightly darker
            cols[0] = self._darken(tc(ctex), 0.65)
            cols[1] = tc(ctex)

        for fdef_idx, zone_fi in self._FDEF_TO_ZONE.items():
            tex = ""
            if is_wall:
                ft = zone.face_textures[r][c]
                tex = ft[zone_fi] if ft else ""
                if not tex:
                    tex = zone.wall_textures[r][c] if zone.wall_textures else ""
                if not tex:
                    tex = zone.tiles[r][c]
                segs = zone.wall_segments[r][c][zone_fi]
                if segs:
                    tex = self._largest_seg_tex(segs, tex)
            elif part == "floor":
                tex = zone.floor_step_textures[r][c][zone_fi]
                segs = zone.floor_step_segments[r][c][zone_fi]
                if segs:
                    tex = self._largest_seg_tex(segs, tex)
            elif part == "ceiling":
                tex = zone.ceil_step_textures[r][c][zone_fi]
                segs = zone.ceil_step_segments[r][c][zone_fi]
                if segs:
                    tex = self._largest_seg_tex(segs, tex)

            if tex:
                cols[fdef_idx] = tc(tex)
            else:
                cols[fdef_idx] = base

        # Apply light, fog, and reflect effects to every face colour
        ae = self._apply_cell_effects
        cols = [ae(fc, r, c, part) for fc in cols]

        return cols

    @staticmethod
    def _largest_seg_tex(segs: list, fallback: str) -> str:
        """Return the texture of the tallest segment, or *fallback*."""
        if not segs:
            return fallback
        best_tex = fallback
        best_h = -1.0
        prev_top = 0.0
        for stex, ytop in segs:
            h = ytop - prev_top
            if h > best_h and stex:
                best_h = h
                best_tex = stex
            prev_top = ytop
        return best_tex

    def _apply_cell_effects(
        self, col: tuple[int, int, int], r: int, c: int, part: str,
    ) -> tuple[int, int, int]:
        """Tint a cell colour by light level, fog density, and reflectivity."""
        zone = self.zone
        cr, cg, cb = col

        # ── Light level (darken when < 1.0) ──
        ll = zone.light_levels
        if ll and r < len(ll) and c < len(ll[r]):
            lv = ll[r][c]
            if lv < 0.99:
                cr = int(cr * lv)
                cg = int(cg * lv)
                cb = int(cb * lv)

        # ── Fog density (blend toward grey fog colour) ──
        fd = getattr(zone, 'fog_density', None)
        if fd and r < len(fd) and c < len(fd[r]):
            fv = fd[r][c]
            if fv > 0.01:
                fc = (128, 128, 128)  # default fog colour
                fco = getattr(zone, 'fog_color', None)
                if fco and r < len(fco) and c < len(fco[r]):
                    fc = fco[r][c]
                t = min(fv, 1.0) * 0.6  # blend strength
                cr = int(cr * (1.0 - t) + fc[0] * t)
                cg = int(cg * (1.0 - t) + fc[1] * t)
                cb = int(cb * (1.0 - t) + fc[2] * t)

        # ── Reflectivity (blue-ish tint on floor faces) ──
        if part == "floor":
            rm = getattr(zone, 'reflect_map', None)
            if rm and r < len(rm) and c < len(rm[r]):
                rv = rm[r][c]
                if rv > 0:
                    t = (rv / 255.0) * 0.35
                    cr = int(cr * (1.0 - t))
                    cg = int(cg * (1.0 - t) + 60 * t)
                    cb = int(cb * (1.0 - t) + 200 * t)

        return (max(0, min(255, cr)), max(0, min(255, cg)), max(0, min(255, cb)))

    @staticmethod
    def _tile_color(texture: str) -> tuple[int, int, int]:
        c = TILE_COLORS.get(texture)
        if c:
            return (min(255, c[0] + 60),
                    min(255, c[1] + 60),
                    min(255, c[2] + 60))
        return COL_WALL_DEF

    @staticmethod
    def _darken(color: tuple[int, int, int], factor: float
                ) -> tuple[int, int, int]:
        return (int(color[0] * factor),
                int(color[1] * factor),
                int(color[2] * factor))
