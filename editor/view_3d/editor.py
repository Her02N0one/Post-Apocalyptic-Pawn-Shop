"""editor/view_3d/editor.py -- Zone3DEditor class (3D zone sculpting).

This is the main assembler class that composes all mixins.  Each concern
lives in its own module:

  constants.py     -- colours, tool defs, height limits
  undo.py          -- snapshot-based undo/redo
  geometry.py      -- cell box computation
  picking.py       -- ray-AABB intersection (unchanged)
  tools_sculpt.py  -- floor/ceiling sculpt, cell conversion
  tools_paint.py   -- texture painting, erase, eyedropper
  tools_fill.py    -- flood-fill (stops at height/segment boundaries)
  tools_erase.py   -- full-cell / height / texture reset
  tools_select.py  -- rectangular area selection + batch ops
  tools_segment.py -- segment split/merge/paint, auto-segment
  save.py          -- zone JSON serialization
  primitives.py    -- _line3d, _box, _filled_box
  rendering.py     -- draw(), HUD, face highlight, colour helpers
"""

from __future__ import annotations

import math

import pygame

from core.tiles import TILE_REGISTRY, tile_def
from core.zones import Zone
from core.fonts import get_font as _get_font

from editor.view_3d.math3d import (
    _perspective, _mat4_mul, _build_view_matrix, _project, _project_line,
    NEAR_CLIP, FAR_CLIP, FOV_DEG,
)
from editor.view_3d.picking import _ray_vs_aabb, _CellHit
from editor.fly_camera import (
    MOUSE_SENS as _MOUSE_SENS,
    KB_TURN_SPEED as _KB_TURN_SPEED,
    forward_3d, right_3d, wasd_3d, clamp_pitch,
)

# Constants -- re-exported so ``from editor.view_3d.editor import X`` still works
from editor.view_3d.constants import (  # noqa: F401
    SNAP_Y_OPTIONS, DEFAULT_SNAP_Y, CAM_H,
    FLOOR_MIN, FLOOR_MAX, CEIL_MIN, CEIL_MAX,
    SKY_HEIGHT, DEFAULT_FLOOR, DEFAULT_CEIL,
    COL_BG, COL_GRID, COL_GRID_EDGE, COL_CEIL_GRID,
    COL_BLOCK_SEL, COL_GHOST, COL_GHOST_BAD,
    COL_CROSSHAIR,
    COL_AXIS_X, COL_AXIS_Y, COL_AXIS_Z,
    COL_HUD_BG, COL_HUD_TEXT, COL_HUD_VAL,
    COL_HUD_TITLE, COL_HUD_WARN, COL_EDGE_DIM,
    COL_SEG_LINE, COL_SEG_AIM,
    COL_WALL_DEF, COL_FLOOR_DEF, COL_CEIL_DEF,
    COL_TOOL_WALL, COL_TOOL_FLOOR, COL_TOOL_CEILING,
    COL_TOOL_PAINT, COL_TOOL_SEGMENT,
    COL_TOOL_FILL, COL_TOOL_ERASE, COL_TOOL_SELECT,
    COL_TOOL_STAMP,
    COL_FACE_HL,
    TOOLS, TOOL_LABELS, TOOL_COLORS, TOOL_KEYS, TOOL_HINTS,
    _FACE_DEFS,
    FLY_SPEED, FLY_SPRINT,
    MOUSE_SENS, KB_TURN_SPEED,
    _ensure_palette,
)

# Mixins
from editor.view_3d.undo import UndoMixin
from editor.view_3d.geometry import GeometryMixin
from editor.view_3d.tools_sculpt import SculptMixin
from editor.view_3d.tools_paint import PaintMixin
from editor.view_3d.tools_fill import FillMixin
from editor.view_3d.tools_erase import EraseMixin
from editor.view_3d.tools_select import SelectMixin
from editor.view_3d.tools_segment import SegmentMixin
from editor.view_3d.tools_stamp import StampMixin
from editor.view_3d.save import SaveMixin
from editor.view_3d.primitives import DrawPrimitivesMixin
from editor.view_3d.rendering import RenderingMixin


# ===================================================================
#  Zone3DEditor -- direct zone sculpting editor
# ===================================================================

class Zone3DEditor(
    RenderingMixin,
    DrawPrimitivesMixin,
    SculptMixin,
    PaintMixin,
    FillMixin,
    EraseMixin,
    SelectMixin,
    SegmentMixin,
    StampMixin,
    GeometryMixin,
    UndoMixin,
    SaveMixin,
):
    """3D sculpting editor for first-person zone geometry.

    Works directly on zone properties (floor_heights, ceil_heights,
    tiles, face_textures) rather than an intermediate block model.
    """

    # --- Fallback tile IDs (resolved once) -------------------------
    _wall_tile: str = ""
    _open_tile: str = ""

    def __init__(self, zone: Zone) -> None:
        self.zone = zone

        # Camera
        self.cam_x = zone.width / 2.0
        self.cam_y = 1.5
        self.cam_z = zone.height / 2.0
        self.yaw   = 0.0
        self.pitch = -0.3

        # Editor state
        self.snap_y = DEFAULT_SNAP_Y
        self.snap_idx = SNAP_Y_OPTIONS.index(DEFAULT_SNAP_Y)
        palette = _ensure_palette()
        self.tex_idx = (palette.index("brick_wall")
                        if "brick_wall" in palette else 0)
        self.current_texture: str = palette[self.tex_idx]

        # Tool system
        self.tool: str = "sculpt"  # one of TOOLS

        # Continuous paint state
        self._lmb_held: bool = False

        # Selection state (for select tool)
        self._sel_start: tuple[int, int] | None = None
        self._sel_end: tuple[int, int] | None = None
        self._sel_ceiling_mode: bool = False

        # Aimed cell
        self.aimed: _CellHit | None = None

        # Preview indicators
        # (col, row, y, color) or (col, row, y, color, face_name)
        self.preview_line: tuple | None = None
        self.preview_box:  tuple[int, int, float, float, tuple] | None = None

        # Display toggles
        self.show_grid  = True
        self.show_ceiling_grid = True
        self.show_axes  = True
        self.show_hud   = True   # pygame HUD overlay (disable when ImGui panels provide the info)

        self.dirty = False

        # Undo / redo
        self._undo_stack: list[dict] = []
        self._redo_stack: list[dict] = []
        self._UNDO_MAX = 50

        # Wall visibility toggle
        self.show_walls = True

        self._resolve_fallback_tiles()
        self._ensure_face_textures()

    def set_zone(self, zone: Zone) -> None:
        """Replace the zone being edited and reset camera/undo."""
        self.zone = zone
        self.cam_x = zone.width / 2.0
        self.cam_y = 1.5
        self.cam_z = zone.height / 2.0
        self.dirty = False
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._ensure_face_textures()

    # -- Helpers ----------------------------------------------------

    def _resolve_fallback_tiles(self) -> None:
        """Find default wall/open tile IDs from the tile registry."""
        if not Zone3DEditor._wall_tile:
            for name, td in TILE_REGISTRY.items():
                if td.wall:
                    Zone3DEditor._wall_tile = name
                    break
            else:
                Zone3DEditor._wall_tile = "brick_wall"
        if not Zone3DEditor._open_tile:
            for name, td in TILE_REGISTRY.items():
                if not td.wall and not td.liquid:
                    Zone3DEditor._open_tile = name
                    break
            else:
                Zone3DEditor._open_tile = "concrete"

    def _ensure_face_textures(self) -> None:
        """Ensure all face-texture / segment grids exist and are correctly sized."""
        z = self.zone
        H, W = z.height, z.width

        def _ensure_tex4(grid, attr):
            g = getattr(z, attr)
            if not g or len(g) != H:
                g = [[["", "", "", ""] for _ in range(W)] for _ in range(H)]
                setattr(z, attr, g)
            for r in range(H):
                if len(g[r]) != W:
                    g[r] = [["", "", "", ""] for _ in range(W)]

        def _ensure_seg4(grid, attr):
            g = getattr(z, attr)
            if not g or len(g) != H:
                g = [[[[], [], [], []] for _ in range(W)] for _ in range(H)]
                setattr(z, attr, g)
            for r in range(H):
                if len(g[r]) != W:
                    g[r] = [[[], [], [], []] for _ in range(W)]

        _ensure_tex4(z.face_textures, "face_textures")
        _ensure_seg4(z.wall_segments, "wall_segments")
        _ensure_tex4(z.floor_step_textures, "floor_step_textures")
        _ensure_tex4(z.ceil_step_textures, "ceil_step_textures")
        _ensure_seg4(z.floor_step_segments, "floor_step_segments")
        _ensure_seg4(z.ceil_step_segments, "ceil_step_segments")

        if not z.upper_wall_height or len(z.upper_wall_height) != H:
            z.upper_wall_height = [[0.0] * W for _ in range(H)]
        for r in range(H):
            if len(z.upper_wall_height[r]) != W:
                z.upper_wall_height[r] = [0.0] * W

    # -- Camera helpers ---------------------------------------------

    def _forward(self) -> tuple[float, float, float]:
        """Camera forward vector."""
        return forward_3d(self.yaw, self.pitch)

    def _right(self) -> tuple[float, float, float]:
        """Camera right vector (horizontal only)."""
        return right_3d(self.yaw)

    # -- Adjacent cell helper ---------------------------------------

    @staticmethod
    def _adjacent(r: int, c: int, face: str) -> tuple[int, int]:
        """Return the (row, col) of the neighbour across *face*."""
        if face == "north": return (r - 1, c)
        if face == "south": return (r + 1, c)
        if face == "east":  return (r, c + 1)
        if face == "west":  return (r, c - 1)
        return (r, c)

    # -- Input handling ---------------------------------------------

    def handle_event(self, event: pygame.event.Event) -> bool:
        """Route a pygame event to the appropriate handler.  Returns True if consumed."""
        if event.type == pygame.KEYDOWN:
            return self._on_keydown(event)
        if event.type == pygame.MOUSEBUTTONDOWN:
            return self._on_click(event)
        if event.type == pygame.MOUSEBUTTONUP:
            return self._on_mouseup(event)
        if event.type == pygame.MOUSEWHEEL:
            return self._on_scroll(event)
        return False

    def _on_keydown(self, event: pygame.event.Event) -> bool:
        key = event.key
        mod = pygame.key.get_mods()

        # Stamp capture naming mode intercepts all keys
        if self.tool == "stamp" and getattr(self, '_capture_pending', False):
            return self._stamp_capture_key(key, event.unicode)

        # Tool selection
        if key in TOOL_KEYS:
            new_tool = TOOL_KEYS[key]
            if new_tool != "select" and self.tool == "select":
                self._sel_cancel()  # clear selection when leaving select tool
            self.tool = new_tool
            return True

        # Display toggles
        if key == pygame.K_F2:
            self.show_grid = not self.show_grid; return True
        if key == pygame.K_F3:
            self.show_ceiling_grid = not self.show_ceiling_grid; return True
        if key == pygame.K_F4:
            self.show_axes = not self.show_axes; return True

        # Upper wall adjust
        if key == pygame.K_u:
            return self._adjust_upper_wall_height(mod)

        # Reset
        if key == pygame.K_r:
            if self.tool == "sculpt" and self.aimed:
                if self.aimed.part == "ceiling":
                    return self._reset_ceiling()
                else:
                    return self._reset_floor()
            return False

        # Toggle ceiling
        if key == pygame.K_t:
            if self.tool == "sculpt" and self.aimed:
                return self._toggle_ceiling()
            return False

        # Delete / Backspace — select-tool batch delete takes priority
        if key in (pygame.K_DELETE, pygame.K_BACKSPACE):
            if self.tool == "select" and self._sel_start is not None and self._sel_end is not None:
                return self._sel_delete()
            return self._clear_cell()

        # Cycle snap grid
        if key == pygame.K_g:
            self.snap_idx = (self.snap_idx + 1) % len(SNAP_Y_OPTIONS)
            self.snap_y = SNAP_Y_OPTIONS[self.snap_idx]
            return True

        # Save
        if key == pygame.K_s and (mod & pygame.KMOD_CTRL):
            self._save()
            return True

        # Cancel aim / selection
        if key == pygame.K_ESCAPE:
            if self.tool == "select" and (self._sel_start is not None or self._sel_end is not None):
                self._sel_cancel()
                return True
            self.aimed = None
            return True

        # Toggle ceiling mode in select tool
        if key == pygame.K_x and self.tool == "select":
            self._sel_toggle_ceiling_mode()
            return True

        # Undo / redo
        if key == pygame.K_z and (mod & pygame.KMOD_CTRL):
            if mod & pygame.KMOD_SHIFT:
                self._redo()
            else:
                self._undo()
            return True
        if key == pygame.K_y and (mod & pygame.KMOD_CTRL):
            self._redo()
            return True

        # Toggle wall drawing
        if key == pygame.K_v:
            self.show_walls = not self.show_walls
            return True

        # Cycle stamp apply mode
        if key == pygame.K_m and self.tool == "stamp":
            self._stamp_cycle_mode()
            return True

        return False

    def _on_click(self, event: pygame.event.Event) -> bool:
        tool = self.tool
        btn = event.button
        shift = bool(pygame.key.get_mods() & pygame.KMOD_SHIFT)
        part = self.aimed.part if self.aimed else None

        # Track LMB held for continuous paint
        if btn == 1:
            self._lmb_held = True

        if tool == "sculpt":
            if btn == 2:
                self._paint()
            elif part in ("floor", "wall", "ground"):
                if btn == 1:
                    self._tool_floor_raise()
                elif btn == 3:
                    self._tool_floor_lower()
            elif part == "ceiling":
                if btn == 1:
                    self._tool_ceiling_lower()
                elif btn == 3:
                    self._tool_ceiling_raise()
            return True

        if tool == "paint":
            if btn == 1 and shift:
                self._paint_all()
            elif btn == 1:
                self._paint()
            elif btn == 3:
                self._erase_texture()
            elif btn == 2:
                self._pick_texture()
            return True

        if tool == "fill":
            if btn == 1:
                self._fill()
            elif btn == 3:
                self._fill_clear()
            return True

        if tool == "erase":
            if btn == 1 and shift:
                self._erase_textures_only()
            elif btn == 1:
                self._erase_cell()
            elif btn == 3:
                self._erase_height()
            return True

        if tool == "select":
            if btn == 1:
                self._sel_click()
            elif btn == 3:
                self._sel_rclick()
            return True

        if tool == "segment":
            if btn == 1:
                self._seg_split()
            elif btn == 3:
                self._seg_merge()
            elif btn == 2:
                self._seg_paint()
            return True

        if tool == "stamp":
            if btn == 1:
                self._stamp_apply()
            elif btn == 3:
                self._stamp_capture_begin()
            return True

        return False

    def _on_mouseup(self, event: pygame.event.Event) -> bool:
        """Track mouse button release for continuous paint."""
        if event.button == 1:
            self._lmb_held = False
        return False

    def _on_scroll(self, event: pygame.event.Event) -> bool:
        tool = self.tool

        if tool in ("paint", "segment", "fill"):
            palette = _ensure_palette()
            if not palette:
                return False
            self.tex_idx = (self.tex_idx + event.y) % len(palette)
            self.current_texture = palette[self.tex_idx]
            return True

        if tool == "stamp":
            self._stamp_cycle(event.y)
            return True

        if tool == "select":
            # When selection is active, scroll raises/lowers floors (or ceilings)
            if self._sel_start is not None and self._sel_end is not None:
                return self._sel_scroll(event.y)
            # No active selection — cycle texture palette
            palette = _ensure_palette()
            if not palette:
                return False
            self.tex_idx = (self.tex_idx + event.y) % len(palette)
            self.current_texture = palette[self.tex_idx]
            return True

        if tool == "sculpt":
            shift = bool(pygame.key.get_mods() & pygame.KMOD_SHIFT)
            part = self.aimed.part if self.aimed else None
            if shift:
                # Shift+Scroll: fine-adjust snap (half steps)
                self.snap_idx = (self.snap_idx + event.y) % len(SNAP_Y_OPTIONS)
                self.snap_y = SNAP_Y_OPTIONS[self.snap_idx]
            elif part == "ceiling":
                self._scroll_upper_wall(event.y)
            elif part in ("floor", "wall", "ground"):
                hit = self.aimed
                if hit:
                    self._extend_floor(hit.row, hit.col, event.y)
            else:
                self.snap_idx = (self.snap_idx + event.y) % len(SNAP_Y_OPTIONS)
                self.snap_y = SNAP_Y_OPTIONS[self.snap_idx]
            return True

        return False

    # -- Update (per frame) -----------------------------------------

    # Camera collision radius (XZ plane)
    _CAM_RADIUS = 0.18

    def update(self, dt: float, mouse_captured: bool) -> None:
        """Tick camera movement, mouse-look, and re-aim."""
        keys = pygame.key.get_pressed()
        speed = FLY_SPEED
        if keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT]:
            speed *= FLY_SPRINT

        if mouse_captured:
            mx, my = pygame.mouse.get_rel()
            self.yaw += mx * MOUSE_SENS
            self.pitch = clamp_pitch(self.pitch - my * MOUSE_SENS)

        if keys[pygame.K_q]:
            self.yaw -= KB_TURN_SPEED * dt
        if keys[pygame.K_e]:
            self.yaw += KB_TURN_SPEED * dt

        ctrl_held = bool(pygame.key.get_mods() & pygame.KMOD_CTRL)

        dx, dy, dz = wasd_3d(
            self.yaw, self.pitch,
            forward=keys[pygame.K_w],
            backward=keys[pygame.K_s] and not ctrl_held,
            strafe_left=keys[pygame.K_a],
            strafe_right=keys[pygame.K_d],
            up=keys[pygame.K_SPACE],
            down=ctrl_held,
            speed=speed,
            dt=dt,
        )

        # --- Wall collision (slide along walls) ---
        R = self._CAM_RADIUS

        # Try X independently
        new_x = self.cam_x + dx
        if not self._collides_xz(new_x, self.cam_z, self.cam_y, R):
            self.cam_x = new_x

        # Try Z independently
        new_z = self.cam_z + dz
        if not self._collides_xz(self.cam_x, new_z, self.cam_y, R):
            self.cam_z = new_z

        # Y is free (fly camera) but clamp to current cell floor/ceiling
        new_y = self.cam_y + dy
        cr = int(math.floor(self.cam_z))
        cc = int(math.floor(self.cam_x))
        zone = self.zone
        if 0 <= cr < zone.height and 0 <= cc < zone.width:
            td = tile_def(zone.tiles[cr][cc])
            if not (td and td.wall):
                fh = zone.floor_heights[cr][cc] if zone.floor_heights else 0.0
                ch = zone.ceil_heights[cr][cc] if zone.ceil_heights else 1.0
                margin = 0.1
                new_y = max(fh + margin, new_y)
                if ch < SKY_HEIGHT:
                    new_y = min(ch - margin, new_y)
        self.cam_y = new_y

        self._update_aim()

        # Continuous paint: if LMB held + paint tool, paint every frame
        # Skip undo push — a single undo entry was pushed on the initial
        # MOUSEBUTTONDOWN so the entire stroke is one undo operation.
        if self._lmb_held and self.tool == "paint" and self.aimed:
            self._paint_continuous()

    def _collides_xz(self, x: float, z: float, y: float, radius: float) -> bool:
        """True if a camera circle at *(x, z)* overlaps any solid cell at height *y*.

        Checks wall tiles and open cells whose floor is above or ceiling
        is below the camera.  Uses circle-vs-AABB overlap.
        """
        zone = self.zone
        c_min = int(math.floor(x - radius))
        c_max = int(math.floor(x + radius))
        r_min = int(math.floor(z - radius))
        r_max = int(math.floor(z + radius))
        rsq = radius * radius

        for r in range(r_min, r_max + 1):
            for c in range(c_min, c_max + 1):
                if r < 0 or r >= zone.height or c < 0 or c >= zone.width:
                    continue  # editor allows flying outside bounds

                # Nearest point on cell AABB to the camera
                closest_x = max(float(c), min(float(c + 1), x))
                closest_z = max(float(r), min(float(r + 1), z))
                dist_sq = (x - closest_x) ** 2 + (z - closest_z) ** 2
                if dist_sq >= rsq:
                    continue  # circle doesn't touch this cell

                td = tile_def(zone.tiles[r][c])
                if td and td.wall:
                    return True

                # Open cell — block if camera is below floor or above ceiling
                fh = zone.floor_heights[r][c] if zone.floor_heights else 0.0
                ch = zone.ceil_heights[r][c] if zone.ceil_heights else 1.0
                margin = 0.1
                if y < fh + margin:
                    return True
                if ch < SKY_HEIGHT and y > ch - margin:
                    return True

        return False

    # -- Raycasting / picking ---------------------------------------

    def _update_aim(self) -> None:
        """Cast a ray from camera forward; find nearest cell box or ground."""
        fx, fy, fz = self._forward()
        ox, oy, oz = self.cam_x, self.cam_y, self.cam_z
        zone = self.zone
        W, H = zone.width, zone.height

        best: _CellHit | None = None

        # Ground-plane hit
        if abs(fy) > 1e-10:
            t = (0.0 - oy) / fy
            if 0.01 < t < FAR_CLIP:
                hx = ox + fx * t
                hz = oz + fz * t
                c = int(math.floor(hx))
                r = int(math.floor(hz))
                if 0 <= c < W and 0 <= r < H:
                    blocked = False
                    for part, yb, yt in self._cell_boxes(r, c):
                        tb = _ray_vs_aabb(ox, oy, oz, fx, fy, fz,
                                          float(c), yb, float(r),
                                          c + 1.0, yt, r + 1.0)
                        if tb and tb[0] < t:
                            blocked = True
                            if best is None or tb[0] < best.t:
                                best = _CellHit(tb[0], c, r, part, tb[1],
                                                oy + tb[0] * fy)
                    if not blocked and (best is None or t < best.t):
                        best = _CellHit(t, c, r, "floor", "ground", 0.0)

        # Search cells near camera
        cam_c = int(math.floor(ox))
        cam_r = int(math.floor(oz))
        search = min(int(FAR_CLIP) + 1, 24)
        r_lo = max(0, cam_r - search)
        r_hi = min(H, cam_r + search)
        c_lo = max(0, cam_c - search)
        c_hi = min(W, cam_c + search)
        for r in range(r_lo, r_hi):
            for c in range(c_lo, c_hi):
                for part, yb, yt in self._cell_boxes(r, c):
                    result = _ray_vs_aabb(
                        ox, oy, oz, fx, fy, fz,
                        float(c), yb, float(r),
                        c + 1.0, yt, r + 1.0,
                    )
                    if result is None:
                        continue
                    t_hit, face = result
                    if best is None or t_hit < best.t:
                        best = _CellHit(t_hit, c, r, part, face,
                                        oy + t_hit * fy)

        self.aimed = best
        self._compute_preview()

    def _compute_preview(self) -> None:
        """Compute preview indicators showing what the next click will do."""
        hit = self.aimed
        if hit is None:
            self.preview_line = None
            self.preview_box = None
            return

        zone = self.zone
        r, c = hit.row, hit.col
        snap = self.snap_y
        fh = zone.floor_heights[r][c]
        ch = zone.ceil_heights[r][c]
        td = tile_def(zone.tiles[r][c])
        is_wall = td and td.wall
        tool = self.tool

        self.preview_line = None
        self.preview_box = None

        if tool == "paint":
            return

        if tool == "segment":
            if hit.face in ("north", "south", "east", "west"):
                face = hit.face
                if hit.part == "wall" and is_wall:
                    split_y = round(hit.hit_y / snap) * snap
                    split_y = max(fh + 0.01, min(ch - 0.01, split_y))
                    self.preview_line = (c, r, split_y, COL_SEG_LINE, face)
                elif hit.part == "floor" and abs(fh) > 0.02:
                    lo = min(0.0, fh)
                    hi = max(0.0, fh)
                    split_y = round(hit.hit_y / snap) * snap
                    split_y = max(lo + 0.01, min(hi - 0.01, split_y))
                    self.preview_line = (c, r, split_y, COL_SEG_LINE, face)
                elif hit.part == "ceiling":
                    ct = self._ceil_mass_top(r, c)
                    if ct - ch > 0.02:
                        split_y = round(hit.hit_y / snap) * snap
                        split_y = max(ch + 0.01, min(ct - 0.01, split_y))
                        self.preview_line = (c, r, split_y, COL_SEG_LINE, face)
            return

        if tool == "sculpt":
            part = hit.part
            if part in ("floor", "wall", "ground"):
                target_up = min(fh + snap, FLOOR_MAX)
                self.preview_line = (c, r, target_up, COL_TOOL_FLOOR)
                if ch >= SKY_HEIGHT:
                    S = self._SLAB
                    ghost_ch = fh + DEFAULT_CEIL
                    self.preview_box = (c, r, ghost_ch - S, ghost_ch + S,
                                        COL_TOOL_CEILING)
            elif part == "ceiling":
                min_ch = max(CEIL_MIN, fh + 0.05)
                target_dn = max(ch - snap, min_ch)
                self.preview_line = (c, r, target_dn, COL_TOOL_CEILING)
            return
