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
    HOTBAR_SIZE,
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
        self._draw_entities(surface, vp, hw, hh, zone)
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

    # Default colour for entity markers (warm amber)
    _COL_ENT_DEFAULT = (255, 180, 60)
    # Selection highlight colour (bright cyan)
    _COL_ENT_SELECTED = (60, 255, 255)
    # Marker half-width (world units)
    _ENT_MARKER_R = 0.15
    # Marker vertical bar half-height
    _ENT_MARKER_H = 0.30

    def _draw_entities(self, surface, vp, hw, hh, zone):
        """Draw diamond-shaped markers at each entity's position."""
        if not getattr(self, 'show_entities', True):
            return
        entities = getattr(zone, 'entities', None)
        if not entities:
            return

        from core.entity_defs import get_entity_def

        r = self._ENT_MARKER_R
        L = self._line3d
        selected_idx = getattr(self, '_ent_selected', None)

        for i, ent in enumerate(entities):
            # Resolve position — new format (x/y) or legacy (position dict)
            if "x" in ent:
                ex = float(ent["x"])
                ez = float(ent["y"])
            else:
                pos = ent.get("position")
                if not pos:
                    continue
                ex = float(pos.get("x", 0))
                ez = float(pos.get("y", 0))

            # Resolve floor height at entity cell
            ci = max(0, min(zone.width - 1, int(ex)))
            ri = max(0, min(zone.height - 1, int(ez)))
            fh = zone.floor_heights[ri][ci] if zone.floor_heights else 0.0

            # Resolve colour from entity_defs, sprite data, or default
            edef = get_entity_def(ent.get("type", ""))
            if edef:
                col = edef.color
                scale = edef.scale
            else:
                spr = ent.get("sprite", {})
                color = spr.get("color")
                if color and len(color) >= 3:
                    col = (int(color[0]), int(color[1]), int(color[2]))
                else:
                    col = self._COL_ENT_DEFAULT
                scale = 0.5

            # Override colour + width for selected entity
            is_sel = (selected_idx is not None and i == selected_idx)
            draw_col = self._COL_ENT_SELECTED if is_sel else col
            lw = 3 if is_sel else 2
            mh = scale * 0.5

            ey = fh  # base Y = floor height

            # Horizontal diamond (X-Z plane) at floor level
            L(surface, vp, hw, hh, ex - r, ey, ez, ex, ey, ez - r, draw_col, lw)
            L(surface, vp, hw, hh, ex, ey, ez - r, ex + r, ey, ez, draw_col, lw)
            L(surface, vp, hw, hh, ex + r, ey, ez, ex, ey, ez + r, draw_col, lw)
            L(surface, vp, hw, hh, ex, ey, ez + r, ex - r, ey, ez, draw_col, lw)

            # Vertical bar from floor to marker height
            top = ey + mh * 2
            L(surface, vp, hw, hh, ex, ey, ez, ex, top, ez, draw_col, lw)

            # Top diamond
            L(surface, vp, hw, hh, ex - r, top, ez, ex, top, ez - r, draw_col, lw)
            L(surface, vp, hw, hh, ex, top, ez - r, ex + r, top, ez, draw_col, lw)
            L(surface, vp, hw, hh, ex + r, top, ez, ex, top, ez + r, draw_col, lw)
            L(surface, vp, hw, hh, ex, top, ez + r, ex - r, top, ez, draw_col, lw)

            # Vertical edges connecting top and bottom diamonds
            L(surface, vp, hw, hh, ex - r, ey, ez, ex - r, top, ez, draw_col, 1)
            L(surface, vp, hw, hh, ex + r, ey, ez, ex + r, top, ez, draw_col, 1)
            L(surface, vp, hw, hh, ex, ey, ez - r, ex, top, ez - r, draw_col, 1)
            L(surface, vp, hw, hh, ex, ey, ez + r, ex, top, ez + r, draw_col, 1)

            # Facing direction line for directional entities
            if edef and edef.directional:
                angle = float(ent.get("angle", 0.0))
                dx = math.cos(angle) * r * 2.5
                dz = -math.sin(angle) * r * 2.5  # -sin: Z is flipped in 3D
                mid_y = ey + mh
                L(surface, vp, hw, hh,
                  ex, mid_y, ez, ex + dx, mid_y, ez + dz, draw_col, 2)

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
        tool_col = TOOL_COLORS.get(self.tool, COL_CROSSHAIR)
        cx, cy = sw // 2, sh // 2
        pygame.draw.line(surface, tool_col, (cx - 14, cy), (cx - 4, cy), 2)
        pygame.draw.line(surface, tool_col, (cx + 4, cy), (cx + 14, cy), 2)
        pygame.draw.line(surface, tool_col, (cx, cy - 14), (cx, cy - 4), 2)
        pygame.draw.line(surface, tool_col, (cx, cy + 4), (cx, cy + 14), 2)
        pygame.draw.circle(surface, tool_col, (cx, cy), 2)

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
            if part == "ceiling":
                ctx_key = "ceiling"
            elif part in ("floor", "wall", "ground"):
                ctx_key = "floor"
            else:
                ctx_key = "none"
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

        bg = pygame.Surface((bg_w, bg_h), pygame.SRCALPHA)
        bg.fill((0, 0, 0, 120))
        surface.blit(bg, (bg_x, bg_y))

        for i, (text, col) in enumerate(lines):
            img = font.render(text, True, col)
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
                    return self._tile_color(tex)
            if zone.wall_textures and zone.wall_textures[r][c]:
                return self._tile_color(zone.wall_textures[r][c])
            return self._tile_color(zone.tiles[r][c])
        elif part == "floor":
            return self._tile_color(self._resolve_floor_tex(r, c))
        elif part == "ceiling":
            return self._tile_color(self._resolve_ceil_tex(r, c))
        return COL_WALL_DEF

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
