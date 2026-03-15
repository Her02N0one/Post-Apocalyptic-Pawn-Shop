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
    COL_TOOL_SELECT,
    COL_TOOL_STAMP,
    COL_TOOL_BOX,
    COL_TOOL_LAYER2,
    COL_TOOL_QUAD,
    COL_TOOL_PORTAL,
    COL_TOOL_CURVE,
    COL_TOOL_OVERLAY,
    COL_FACE_HL,
    TOOLS, UTIL_TOOLS, ALL_TOOLS,
    TOOL_LABELS, TOOL_COLORS, UTIL_KEYS,
    HOTBAR_SIZE,
    TOOL_HINTS,
    MODES, MODE_LABELS, MODE_ICONS, MODE_COLORS,
    MODE_DESCRIPTIONS, MODE_TOOLS, MODE_SELECTION_TARGET,
    VIEW_LIT, VIEW_PATHING, VIEW_MODES, VIEW_LABELS,
    PASTE_MASK_ALL,
    MODE_ARCH, MODE_SURF, MODE_PROPS, MODE_LOGIC,
    PASTE_MASK_HEIGHTS, PASTE_MASK_TEXTURES, PASTE_MASK_ENTITIES,
    PASTE_MASK_SEGMENTS, PASTE_MASK_LIGHTING,
    _FACE_DEFS,
    FLY_SPEED, FLY_SPRINT,
    MOUSE_SENS, KB_TURN_SPEED,
    _ensure_palette,
)

# Mixins
from editor.keybinds import create_default_registry, _simplify_mods, MOD_SHIFT, MOD_CTRL, MOD_ALT
from editor.view_3d.selection_store import SelectionStore, uid_of, resolve_index
from editor.view_3d.undo import UndoMixin
from editor.view_3d.geometry import GeometryMixin
from editor.view_3d.tools_sculpt import SculptMixin
from editor.view_3d.tools_paint import PaintMixin
from editor.view_3d.tools_fill import FillMixin
from editor.view_3d.tools_select import SelectMixin
from editor.view_3d.tools_segment import SegmentMixin
from editor.view_3d.tools_stamp import StampMixin
from editor.view_3d.tools_entity import EntityMixin
from editor.view_3d.tools_box import BoxMixin
from editor.view_3d.tools_layer2 import Layer2Mixin
from editor.view_3d.tools_quad import QuadMixin
from editor.view_3d.tools_portal import PortalMixin
from editor.view_3d.tools_curve import CurveMixin
from editor.view_3d.tools_overlay import OverlayWallMixin
from editor.view_3d.objects import ObjectLayer
from editor.view_3d.save import SaveMixin
from editor.view_3d.primitives import DrawPrimitivesMixin
from editor.view_3d.rendering import RenderingMixin

# Phase 0 — Command bus infrastructure
from editor.commands import CommandBus, EventBus, BatchCommand
from editor.commands.sculpt_cmds import (
    SculptFloorRaise, SculptFloorLower,
    SculptCeilRaise, SculptCeilLower,
    SculptToggleCeiling, SculptResetCeiling, SculptResetFloor,
    SculptClearCell, SculptAdjustUpperWall,
    SculptScrollUpperWall, SculptExtendFloor, SculptExtendWallCeiling,
    SculptBatchMakeWall, SculptBatchMakeOpen,
    SculptFlattenFloors, SculptFlattenCeilings,
    SculptBatchRaiseUpperWall, SculptBatchLowerUpperWall,
    SculptBatchResetUpperWall,
    register_sculpt_handlers,
)
from editor.commands.paint_cmds import (
    PaintFace, PaintAllFaces, EraseFace,
    PaintPrismFace, ErasePrismFace, PaintQuad, EraseQuad,
    FloodFill, FloodClear, SelectionFillTexture, SelectionClearTextures,
    ContinuousPaint,
    register_paint_handlers,
)
from editor.commands.erase_cmds import (
    EraseCell, EraseHeight, EraseTexturesOnly,
    register_erase_handlers,
)
from editor.commands.object_cmds import (
    EntityPlace, EntityDelete, EntityMove, EntityRotate,
    BoxPlace, BoxDelete, BoxMove, BoxRotate90, BoxRotateFine,
    BoxAdjustSize, BoxShiftZ,
    QuadPlace, QuadDelete, QuadMove, QuadRotate,
    QuadAdjustSize, QuadToggleTwosided, QuadPaint,
    PortalPlace, PortalDelete,
    CurvePlace, CurveDelete, CurveMove, CurvePaint,
    CurveAdjustRadius, CurveAdjustAngleStart, CurveAdjustAngleEnd,
    OverlayFinishPlace, OverlayDelete, OverlayMove, OverlayPaint,
    OverlayToggleTransparent, OverlayAdjustHeight,
    register_object_handlers,
)
from editor.commands.segment_cmds import (
    SegmentSplit, SegmentMerge, SegmentPaint,
    register_segment_handlers,
)
from editor.commands.stamp_cmds import (
    StampApply,
    register_stamp_handlers,
)
from editor.commands.l2_cmds import (
    L2Raise, L2Lower, L2Paint, L2EraseSingle,
    L2PaintSelection, L2EraseSelection,
    L2Scroll, L2Reset, L2SelScroll,
    L2FlattenFloors, L2FlattenCeilings, L2ToggleCeil,
    L2SelectionReset, L2DeleteAimed,
    register_l2_handlers,
)
from editor.commands.select_cmds import (
    SelScroll, SelDelete, SelResetCells,
    register_select_handlers,
)
from editor.commands.misc_cmds import (
    ClipboardPaste, DuplicateSelection, ObjectDeleteSelected,
    register_misc_handlers,
)


# ===================================================================
#  Zone3DEditor -- direct zone sculpting editor
# ===================================================================

class Zone3DEditor(
    RenderingMixin,
    DrawPrimitivesMixin,
    SculptMixin,
    PaintMixin,
    FillMixin,
    SelectMixin,
    SegmentMixin,
    StampMixin,
    EntityMixin,
    BoxMixin,
    Layer2Mixin,
    QuadMixin,
    PortalMixin,
    CurveMixin,
    OverlayWallMixin,
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

    @property
    def _sculpt_layer2(self) -> bool:
        """Compatibility shim — delegates to active_layer."""
        return self.active_layer == 2

    @_sculpt_layer2.setter
    def _sculpt_layer2(self, value: bool) -> None:
        """Compatibility shim — sets active_layer from bool."""
        self.active_layer = 2 if value else 1

    # ── Dirty flag with zone generation tracking ──────────────────

    @property
    def dirty(self) -> bool:
        return self._dirty

    @dirty.setter
    def dirty(self, value: bool) -> None:
        self._dirty = value
        if value and hasattr(self, 'zone'):
            self.zone.bump_generation()

    # ── Phase 2: bridge properties ────────────────────────────────
    # These translate between the legacy ``_*_selected`` index-based
    # API and the UID-based SelectionStore.  Existing mixin and panel
    # code continues to read/write these fields; the properties route
    # everything through the store so there is only ONE source of truth.

    def _sel_bridge_get(self, type_tag: str) -> int | None:
        """Resolve the store's primary UID to a list index, or None."""
        store = self.selection
        if store.primary_type != type_tag:
            return None
        return store.primary_index(self.zone)

    def _sel_bridge_set(self, type_tag: str, store_attr: str, idx: int | None) -> None:
        """Update the store from a legacy index assignment."""
        sel = self.selection
        if idx is None:
            if sel.primary_type == type_tag:
                uid = sel.primary_uid
                if uid is not None:
                    sel.deselect_object(uid)
        else:
            zone_list = getattr(self.zone, store_attr, None)
            if zone_list and 0 <= idx < len(zone_list):
                uid = uid_of(self.zone, type_tag, idx)
                if uid is not None:
                    sel.select_object(type_tag, uid)

    @property
    def _ent_selected(self) -> int | None:
        return self._sel_bridge_get("entity")

    @_ent_selected.setter
    def _ent_selected(self, idx: int | None) -> None:
        self._sel_bridge_set("entity", "entities", idx)

    @property
    def _box_selected(self) -> int | None:
        return self._sel_bridge_get("prism")

    @_box_selected.setter
    def _box_selected(self, idx: int | None) -> None:
        self._sel_bridge_set("prism", "boxes", idx)

    @property
    def _quad_selected(self) -> int | None:
        return self._sel_bridge_get("quad")

    @_quad_selected.setter
    def _quad_selected(self, idx: int | None) -> None:
        self._sel_bridge_set("quad", "quads", idx)

    @property
    def _portal_selected(self) -> int | None:
        return self._sel_bridge_get("portal")

    @_portal_selected.setter
    def _portal_selected(self, idx: int | None) -> None:
        self._sel_bridge_set("portal", "render_portals", idx)

    @property
    def _curve_selected(self) -> int | None:
        return self._sel_bridge_get("curve")

    @_curve_selected.setter
    def _curve_selected(self, idx: int | None) -> None:
        self._sel_bridge_set("curve", "curves", idx)

    @property
    def _ow_selected(self) -> int | None:
        return self._sel_bridge_get("overlay")

    @_ow_selected.setter
    def _ow_selected(self, idx: int | None) -> None:
        self._sel_bridge_set("overlay", "overlay_walls", idx)

    def __init__(self, zone: Zone) -> None:
        self.zone = zone

        # ── Keybind registry (central source of truth) ────────────
        self.kb = create_default_registry()
        # Load user overrides if config exists
        import os
        _kb_path = os.path.join(os.path.dirname(__file__), '..', '..', 'keybinds.json')
        self.kb.load_overrides(_kb_path)

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

        # Hotbar: 10 quick-access texture slots
        self.hotbar: list[str] = self._init_hotbar(palette)
        self.hotbar_slot: int = 0

        # Tool system (3 core + 2 utility)
        self.tool: str = "sculpt"  # one of ALL_TOOLS
        self._prev_tool: str = "sculpt"  # tool to return to from utility modes

        # ── Unified mode system (state machine) ───────────────────
        # Elevation (Layer) → Mode → Selection → Operation
        self.mode: str = MODE_ARCH   # one of MODES
        self.view_mode_3d: str = VIEW_LIT  # viewport rendering mode

        # Continuous paint state
        self._lmb_held: bool = False

        # ── First-class active layer system ───────────────────────
        # 1 = primary (floor/ceil/walls), 2 = secondary (floor2/ceil2)
        self.active_layer: int = 1
        self.isolate_layer: bool = False  # Alt+I: hide inactive layer

        # ── State clipboard (Ctrl+C / Ctrl+V) ────────────────────
        self._clipboard: dict | None = None  # copied cell state dict
        self._paste_mask: set[str] = set(PASTE_MASK_ALL)  # active mask flags

        # ── Phase 0: Command bus + event bus (before selection so store
        #    can emit SelectionChanged events immediately) ──────────
        self.event_bus = EventBus()
        self.cmd_bus = CommandBus(self, self.event_bus)

        # ── Universal selection layer (Phase 2: UID-based store) ──
        self.selection = SelectionStore(self.event_bus)

        # ── Unified object layer ──────────────────────────────────
        self.objects = ObjectLayer(self)

        # Aimed cell
        self.aimed: _CellHit | None = None

        # Cell box cache (cleared each frame tick in update())
        self._cell_box_cache: dict = {}

        # Reusable scratch surface for alpha-blended polygon faces
        self._alpha_scratch: pygame.Surface | None = None

        # Preview indicators
        # (col, row, y, color) or (col, row, y, color, face_name)
        self.preview_line: tuple | None = None
        self.preview_box:  tuple[int, int, float, float, tuple] | None = None

        # Display toggles
        self.show_axes  = True
        self.show_hud   = True   # pygame HUD overlay (disable when ImGui panels provide the info)

        self._dirty = False

        # Flash callback — set by the owning app for visual feedback
        self.on_flash: callable | None = None

        # Help overlay toggle
        self._show_help: bool = False

        # Undo / redo
        self._undo_stack: list[dict] = []
        self._redo_stack: list[dict] = []
        self._UNDO_MAX = 50

        # Visibility toggles
        self.show_walls = True
        self.show_floors = True
        self.show_ceilings = True
        self.show_entities = True
        self.wireframe = False

        self._resolve_fallback_tiles()
        self._ensure_face_textures()

        # ── Phase 0: register command handlers ─────────────────────
        self._register_all_handlers()

    def set_zone(self, zone: Zone) -> None:
        """Replace the zone being edited and reset camera/undo."""
        self.zone = zone
        self.cam_x = zone.width / 2.0
        self.cam_y = 1.5
        self.cam_z = zone.height / 2.0
        self.dirty = False
        self._undo_stack.clear()
        self._redo_stack.clear()
        self.selection.clear()
        self._ensure_face_textures()
        # Re-register handlers for the new zone
        self._register_all_handlers()

    def _register_all_handlers(self) -> None:
        """Register all Phase 0 command handlers on the bus."""
        register_sculpt_handlers(self.cmd_bus, self)
        register_paint_handlers(self.cmd_bus, self)
        register_erase_handlers(self.cmd_bus, self)
        register_object_handlers(self.cmd_bus, self)
        register_segment_handlers(self.cmd_bus, self)
        register_stamp_handlers(self.cmd_bus, self)
        register_l2_handlers(self.cmd_bus, self)
        register_select_handlers(self.cmd_bus, self)
        register_misc_handlers(self.cmd_bus, self)

    # -- Command dispatch helpers (Phase 0) -------------------------

    def _sculpt_cmd(self, cmd_cls: type) -> None:
        """Dispatch a sculpt command for the current selection or aimed cell.

        If the selection has cells, wraps individual commands in a
        :class:`BatchCommand` for a single undo entry.  Otherwise
        dispatches a single command for the aimed cell.
        """
        if self._has_selection():
            cells = tuple(self.selection.iter_cells())
            if cells:
                self.cmd_bus.execute(BatchCommand(children=tuple(
                    cmd_cls(cell=(r, c)) for r, c in cells
                )))
        elif self.aimed:
            self.cmd_bus.execute(cmd_cls(cell=(self.aimed.row, self.aimed.col)))

    # -- Batch dispatch helper --------------------------------------

    def batch_or_single(self, cell_fn, push_undo: bool = True) -> bool:
        """Apply *cell_fn(r, c)→bool* to the selection or aimed cell.

        If the universal selection has cells, iterate all of them.
        If neither exists, apply to the single aimed cell.
        Returns True if anything changed.
        """
        # 1. Universal selection
        if self.selection.has_cells():
            if push_undo:
                self._push_undo()
                self._ensure_face_textures()
            changed = False
            for r, c in self.selection.iter_cells():
                if cell_fn(r, c):
                    changed = True
            if changed:
                self.dirty = True
            return changed

        # 2. Single aimed cell
        hit = self.aimed
        if not hit:
            return False
        if push_undo:
            self._push_undo()
            self._ensure_face_textures()
        if cell_fn(hit.row, hit.col):
            self.dirty = True
            return True
        return False

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

    @staticmethod
    def _init_hotbar(palette: list[str]) -> list[str]:
        """Fill 10 hotbar slots with useful default textures."""
        # Preferred defaults (first found wins)
        preferred = [
            "brick_wall", "stone_wall", "concrete", "wood_floor",
            "sand", "grass", "dirt", "metal_floor", "carpet", "void",
        ]
        slots: list[str] = []
        for name in preferred:
            if name in palette:
                slots.append(name)
            if len(slots) >= HOTBAR_SIZE:
                break
        # Fill remaining with palette items
        for name in palette:
            if name not in slots:
                slots.append(name)
            if len(slots) >= HOTBAR_SIZE:
                break
        # Pad if palette is tiny
        while len(slots) < HOTBAR_SIZE:
            slots.append(palette[0] if palette else "brick_wall")
        return slots

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

    def _leave_tool(self, old_tool: str) -> None:
        """Clean up state when switching away from *old_tool*."""
        if old_tool == "select":
            self.selection.cancel_rect()  # cancel in-progress rectangle drag
        if old_tool == "stamp":
            self._capture_pending = False
            self._capture_name = ""
        if old_tool == "entity":
            self._ent_deselect()
        if old_tool == "box":
            self._box_deselect()
        if old_tool == "quad":
            self._quad_deselect()
        if old_tool == "portal":
            self._portal_deselect()
        if old_tool == "curve":
            self._curve_deselect()
        if old_tool == "overlay":
            self._ow_deselect()

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

    # ── B-key tri-state helper ────────────────────────────────

    def _handle_b_key(self) -> bool:
        """B key: tri-state select tool toggle.

        * In select tool with active selection → exit select, keep selection
        * In select tool with no selection    → exit select to previous tool
        * Not in select tool                  → enter select tool

        Selection is preserved on exit so you can select, press B, and
        operate on the selection in sculpt/paint.  Press Escape to clear.
        """
        if self.tool == "select":
            # Exit select — keep selection intact so other tools can use it
            self._leave_tool(self.tool)
            self.tool = self._prev_tool
        else:
            self._prev_tool = self.tool  # save ANY tool, not just TOOLS
            self._leave_tool(self.tool)
            self.tool = "select"
        return True

    # ── Keydown dispatch (priority-ordered) ────────────────────

    def _on_keydown(self, event: pygame.event.Event) -> bool:
        key = event.key
        mod = pygame.key.get_mods()
        kb = self.kb   # keybind registry shorthand
        tool = self.tool

        # ── 1. Ctrl / Alt modifier combos (highest priority) ─────
        if kb.check("file.save", key, mod, scope=tool):
            self._save()
            return True
        if kb.check("edit.redo_cz", key, mod, scope=tool):
            self._redo()
            return True
        if kb.check("edit.undo", key, mod, scope=tool):
            self._undo()
            return True
        if kb.check("edit.redo_cy", key, mod, scope=tool):
            self._redo()
            return True
        if kb.check("select.all", key, mod, scope=tool):
            self.selection.select_all_cells(self.zone.width, self.zone.height)
            return True
        if kb.check("select.duplicate", key, mod, scope=tool):
            self.cmd_bus.execute(DuplicateSelection())
            return True
        if kb.check("edit.copy", key, mod, scope=tool):
            self._clipboard_copy()
            return True
        if kb.check("edit.paste", key, mod, scope=tool):
            self.cmd_bus.execute(ClipboardPaste())
            return True
        if kb.check("display.walls_c", key, mod, scope=tool):
            self.show_walls = not self.show_walls
            return True
        if kb.check("display.floors_c", key, mod, scope=tool):
            self.show_floors = not self.show_floors
            return True
        if kb.check("display.ceilings_c", key, mod, scope=tool):
            self.show_ceilings = not self.show_ceilings
            return True
        if kb.check("display.entities_c", key, mod, scope=tool):
            self.show_entities = not self.show_entities
            return True
        if kb.check("display.wireframe_c", key, mod, scope=tool):
            self.wireframe = not self.wireframe
            return True
        if kb.check("display.isolate", key, mod, scope=tool):
            self.isolate_layer = not self.isolate_layer
            return True

        # ── 1b. PageUp/PageDown = switch active layer ─────────────
        if kb.check("layer.up", key, mod, scope=tool):
            self.active_layer = 2
            self._flash("Layer 2", 0.7, (0.7, 0.85, 1.0, 1.0))
            return True
        if kb.check("layer.down", key, mod, scope=tool):
            self.active_layer = 1
            self._flash("Layer 1", 0.7, (0.7, 0.85, 1.0, 1.0))
            return True

        # ── 1d. F1-F4 = switch primary mode ───────────────────────
        _MODE_ACTIONS = [
            ("mode.arch",    MODES[0]),
            ("mode.surface", MODES[1]),
            ("mode.props",   MODES[2]),
            ("mode.logic",   MODES[3]),
        ]
        for _act, _new_mode in _MODE_ACTIONS:
            if kb.check(_act, key, mod, scope=tool):
                self.mode = _new_mode
                mode_tools = MODE_TOOLS[_new_mode]
                if self.tool not in mode_tools:
                    self._leave_tool(self.tool)
                    self.tool = mode_tools[0]
                    self._prev_tool = mode_tools[0]
                self._flash(f"{MODE_LABELS.get(_new_mode, _new_mode)}", 0.8,
                            (0.85, 0.9, 1.0, 1.0))
                return True

        # ── 2. Number keys 1-5 = select tool within current mode ──
        for _i in range(1, 6):
            if kb.check(f"subtool.{_i}", key, mod, scope=tool):
                idx = _i - 1
                mode_tools = MODE_TOOLS[self.mode]
                if idx < len(mode_tools):
                    new_tool = mode_tools[idx]
                    if new_tool != self.tool:
                        self._leave_tool(self.tool)
                        self.tool = new_tool
                        self._prev_tool = new_tool
                _tl = TOOL_LABELS.get(self.tool, self.tool)
                self._flash(f"{_tl}", 0.6, (0.85, 0.9, 1.0, 1.0))
                return True

        # ── 3. B key — select tool toggle ─────────────────────────
        if kb.check("tool.select", key, mod, scope=tool):
            return self._handle_b_key()

        # ── 4. Utility mode toggles (P, I, O, ;) ─────────────────
        _UTIL_ACTIONS = [
            ("tool.stamp",  "stamp"),
            ("tool.quad",   "quad"),
            ("tool.portal", "portal"),
            ("tool.curve",  "curve"),
        ]
        for _act, _target in _UTIL_ACTIONS:
            if kb.check(_act, key, mod, scope=tool):
                if self.tool == _target:
                    self._leave_tool(self.tool)
                    self.tool = self._prev_tool
                else:
                    self._prev_tool = self.tool
                    self._leave_tool(self.tool)
                    self.tool = _target
                return True

        # ── 5. Tab = cycle tools within current mode ──────────────
        if key == pygame.K_TAB:
            mode_tools = MODE_TOOLS[self.mode]
            self._leave_tool(self.tool)
            idx = mode_tools.index(self.tool) if self.tool in mode_tools else 0
            self.tool = mode_tools[(idx + 1) % len(mode_tools)]
            self._prev_tool = self.tool
            return True

        # ── 6. Cross-tool selection keys (when selection active) ──
        #    Scope enforcement limits these to sculpt / select / paint.
        if self._has_selection():
            if self._sculpt_layer2:
                # ── L2 selection operations ────────────────────────
                if kb.check("sel.ceil_mode", key, mod, scope=tool):
                    self._layer2_toggle_target()
                    return True
                if kb.check("sel.flatten_floors", key, mod, scope=tool):
                    return self.cmd_bus.execute(L2FlattenFloors())
                if kb.check("sel.flatten_ceilings", key, mod, scope=tool):
                    return self.cmd_bus.execute(L2FlattenCeilings())
                if kb.check("sel.add_ceilings", key, mod, scope=tool):
                    return self.cmd_bus.execute(L2ToggleCeil())
                if kb.check("sel.remove_ceilings", key, mod, scope=tool):
                    self.cmd_bus.execute(L2SelectionReset())
                    return True
                if kb.check("sel.reset", key, mod, scope=tool):
                    self.cmd_bus.execute(L2SelectionReset())
                    return True
            else:
                # ── L1 selection operations ────────────────────────
                if kb.check("sel.ceil_mode", key, mod, scope=tool):
                    self._sel_toggle_ceiling_mode()
                    return True
                if kb.check("sel.remove_ceilings", key, mod, scope=tool):
                    return self.cmd_bus.execute(SculptToggleCeiling(remove_only=True))
                if kb.check("sel.add_ceilings", key, mod, scope=tool):
                    return self.cmd_bus.execute(SculptToggleCeiling(add_only=True))
                if kb.check("sel.make_open", key, mod, scope=tool):
                    return self.cmd_bus.execute(SculptBatchMakeOpen())
                if kb.check("sel.make_wall", key, mod, scope=tool):
                    return self.cmd_bus.execute(SculptBatchMakeWall())
                if kb.check("sel.flatten_ceilings", key, mod, scope=tool):
                    return self.cmd_bus.execute(SculptFlattenCeilings())
                if kb.check("sel.flatten_floors", key, mod, scope=tool):
                    return self.cmd_bus.execute(SculptFlattenFloors())
                if kb.check("sel.reset_upper_wall", key, mod, scope=tool):
                    return self.cmd_bus.execute(SculptBatchResetUpperWall())
                if kb.check("sel.raise_upper_wall", key, mod, scope=tool):
                    return self.cmd_bus.execute(SculptBatchRaiseUpperWall())
                if kb.check("sel.lower_upper_wall", key, mod, scope=tool):
                    return self.cmd_bus.execute(SculptBatchLowerUpperWall())
                if kb.check("sel.reset", key, mod, scope=tool):
                    return self.cmd_bus.execute(SelDelete())

        # ── 8. Display toggle: axes (F10) ─────────────────────────
        if kb.check("display.axes", key, mod, scope=tool):
            self.show_axes = not self.show_axes
            return True

        # ── 9. Tool-specific keys ────────────────────────────────

        # Upper wall adjust (U key — single cell, no selection)
        # U has no effect on L2 (no upper-wall concept)
        if not self._sculpt_layer2:
            if kb.check("sculpt.reset_upper_wall", key, mod, scope=tool):
                return self.cmd_bus.execute(SculptAdjustUpperWall(modifier=pygame.KMOD_CTRL))
            if kb.check("sculpt.raise_upper_wall", key, mod, scope=tool):
                return self.cmd_bus.execute(SculptAdjustUpperWall(modifier=0))
            if kb.check("sculpt.lower_upper_wall", key, mod, scope=tool):
                return self.cmd_bus.execute(SculptAdjustUpperWall(modifier=pygame.KMOD_SHIFT))

        # Reset (R key) — box tool overrides for 90° rotation
        if kb.check("box.rotate", key, mod, scope=tool):
            self.cmd_bus.execute(BoxRotate90())
            return True
        if kb.check("sculpt.reset_ceiling", key, mod, scope=tool) or kb.check("sculpt.reset_floor", key, mod, scope=tool):
            if self._sculpt_layer2:
                return self.cmd_bus.execute(L2Reset())
            if self.aimed:
                if self.aimed.part in ("ceiling", "ceiling2"):
                    return self.cmd_bus.execute(SculptResetCeiling())
                else:
                    return self.cmd_bus.execute(SculptResetFloor())
            return False

        # Toggle ceiling (T key — single cell when no selection)
        if kb.check("entity.cycle_state", key, mod, scope=tool):
            self._ent_cycle_state()
            return True
        if kb.check("sculpt.toggle_ceiling", key, mod, scope=tool):
            if self._sculpt_layer2:
                return self.cmd_bus.execute(L2ToggleCeil())
            if self.aimed:
                return self.cmd_bus.execute(SculptToggleCeiling())

        # Wall / open conversion (H key — L1 only, no equivalent on L2)
        if not self._sculpt_layer2:
            if kb.check("sculpt.make_open", key, mod, scope=tool):
                return self.cmd_bus.execute(SculptBatchMakeOpen())
            if kb.check("sculpt.make_wall", key, mod, scope=tool):
                return self.cmd_bus.execute(SculptBatchMakeWall())

        # Delete (no selection — unified object layer then cell fallback)
        if kb.check("delete.aimed", key, mod, scope=tool):
            if self.cmd_bus.execute(ObjectDeleteSelected()):
                return True
            if self._sculpt_layer2:
                self.cmd_bus.execute(L2DeleteAimed())
                return True
            return self.cmd_bus.execute(SculptClearCell())

        # Snap grid (G key) / Shift+G = select similar
        if kb.check("select.similar", key, mod, scope=tool):
            self._select_similar()
            return True
        if kb.check("box.toggle_grid", key, mod, scope=tool):
            self._box_toggle_snap()
            return True
        if kb.check("quad.cycle_snap", key, mod, scope=tool):
            _QUAD_SNAPS = [0.25, 0.5, 1.0, 0.0]
            cur = self._quad_snap
            try:
                idx = _QUAD_SNAPS.index(cur)
            except ValueError:
                idx = -1
            self._quad_snap = _QUAD_SNAPS[(idx + 1) % len(_QUAD_SNAPS)]
            return True
        if kb.check("overlay.cycle_snap", key, mod, scope=tool):
            _OW_SNAPS = [0.25, 0.5, 1.0, 0.0]
            cur = self._ow_snap
            try:
                idx = _OW_SNAPS.index(cur)
            except ValueError:
                idx = -1
            self._ow_snap = _OW_SNAPS[(idx + 1) % len(_OW_SNAPS)]
            label = f"{self._ow_snap:.2f}" if self._ow_snap else "off"
            self._flash(f"Snap: {label}", 0.8, (0.7, 0.9, 1.0, 1.0))
            return True
        if kb.check("sculpt.cycle_grid", key, mod, scope=tool):
            self.snap_idx = (self.snap_idx + 1) % len(SNAP_Y_OPTIONS)
            self.snap_y = SNAP_Y_OPTIONS[self.snap_idx]
            return True

        # X key (no selection — tool-specific)
        if kb.check("sculpt.toggle_layer", key, mod, scope=tool):
            self.active_layer = 1 if self.active_layer == 2 else 2
            return True
        if kb.check("select.ceil_mode", key, mod, scope=tool):
            self._sel_toggle_ceiling_mode()
            return True

        # Stamp mode cycle (M key)
        if kb.check("stamp.cycle_mode", key, mod, scope=tool):
            self._stamp_cycle_mode()
            return True

        # ── ? key — toggle keyboard shortcut help overlay ─────────
        if kb.check("help.toggle", key, mod, scope=tool):
            self._show_help = not self._show_help
            return True

        return False

    def _on_click(self, event: pygame.event.Event) -> bool:
        tool = self.tool
        btn = event.button
        shift = bool(pygame.key.get_mods() & pygame.KMOD_SHIFT)
        ctrl = bool(pygame.key.get_mods() & pygame.KMOD_CTRL)
        part = self.aimed.part if self.aimed else None

        # Track LMB held for continuous paint
        if btn == 1:
            self._lmb_held = True

        if tool == "sculpt":
            if btn == 2:
                self._pick_texture()  # universal eyedropper
            elif self._has_selection() and not self._sculpt_layer2:
                # Selection active — Shift XORs with ceiling mode:
                # plain click = floor (or ceiling if X toggled),
                # Shift+click = ceiling (or floor if X toggled).
                ceiling = shift != self.selection.ceiling_mode
                if ceiling:
                    if btn == 1:
                        self._sculpt_cmd(SculptCeilLower)
                    elif btn == 3:
                        self._sculpt_cmd(SculptCeilRaise)
                else:
                    if btn == 1:
                        self._sculpt_cmd(SculptFloorRaise)
                    elif btn == 3:
                        self._sculpt_cmd(SculptFloorLower)
            elif self._sculpt_layer2:
                # Layer 2 sub-mode
                if btn == 1:
                    self.cmd_bus.execute(L2Raise(shift=shift, ctrl=ctrl))
                elif btn == 3:
                    self.cmd_bus.execute(L2Lower(shift=shift))
            else:
                # L1 sculpt — map L2 surface hits to L1 equivalents
                p = {"floor2": "floor", "ceiling2": "ceiling"}.get(part, part)
                if shift and p in ("floor", "wall", "ground"):
                    # Shift on floor/ground = ceiling operation (no need
                    # to aim at ceiling surface specifically)
                    if btn == 1:
                        self._sculpt_cmd(SculptCeilLower)
                    elif btn == 3:
                        self._sculpt_cmd(SculptCeilRaise)
                elif p in ("floor", "wall", "ground"):
                    if btn == 1:
                        self._sculpt_cmd(SculptFloorRaise)
                    elif btn == 3:
                        self._sculpt_cmd(SculptFloorLower)
                elif p == "ceiling":
                    if btn == 1:
                        self._sculpt_cmd(SculptCeilLower)
                    elif btn == 3:
                        self._sculpt_cmd(SculptCeilRaise)
            return True

        if tool == "paint":
            # Layer 2 paint mode
            if self._sculpt_layer2:
                if btn == 2:
                    self._layer2_pick_texture()
                elif self._has_selection():
                    if btn == 1:
                        self.cmd_bus.execute(L2PaintSelection())
                    elif btn == 3:
                        self.cmd_bus.execute(L2EraseSelection())
                else:
                    if btn == 1:
                        self.cmd_bus.execute(L2Paint())
                    elif btn == 3:
                        self.cmd_bus.execute(L2EraseSingle())
                return True
            # Batch paint when selection is active
            if self._has_selection():
                if btn == 1:
                    self.cmd_bus.execute(SelectionFillTexture())
                elif btn == 3:
                    self.cmd_bus.execute(SelectionClearTextures())
                elif btn == 2:
                    self._pick_texture()
                return True
            # Check per-frame aim: prism or quad closer than cell?
            aimed_prism = self._paint_aimed_prism
            aimed_face = self._paint_aimed_prism_face
            aimed_quad = self._paint_aimed_quad

            if aimed_prism is not None:
                if btn == 1 and shift:
                    self.cmd_bus.execute(PaintPrismFace(index=aimed_prism, face=None))
                elif btn == 1:
                    self.cmd_bus.execute(PaintPrismFace(index=aimed_prism, face=aimed_face))
                elif btn == 3 and shift:
                    self.cmd_bus.execute(ErasePrismFace(index=aimed_prism, face=None))
                elif btn == 3:
                    self.cmd_bus.execute(ErasePrismFace(index=aimed_prism, face=aimed_face))
                elif btn == 2:
                    self._pick_prism_texture(aimed_prism, face=aimed_face)
            elif aimed_quad is not None:
                if btn == 1:
                    self.cmd_bus.execute(PaintQuad(index=aimed_quad))
                elif btn == 3:
                    self.cmd_bus.execute(EraseQuad(index=aimed_quad))
                elif btn == 2:
                    self._pick_quad_texture(aimed_quad)
            else:
                # Fall through to cell-based painting
                if btn == 1 and ctrl:
                    self.cmd_bus.execute(FloodFill())
                elif btn == 1 and shift:
                    self.cmd_bus.execute(PaintAllFaces())
                elif btn == 1:
                    self.cmd_bus.execute(PaintFace())
                elif btn == 3 and ctrl:
                    self.cmd_bus.execute(FloodClear())
                elif btn == 3:
                    self.cmd_bus.execute(EraseFace())
                elif btn == 2:
                    self._pick_texture()  # MMB = eyedropper
            return True

        if tool == "select":
            if btn == 1:
                self._sel_click()
            elif btn == 3:
                self._sel_rclick()
            return True

        if tool == "segment":
            if btn == 1:
                self.cmd_bus.execute(SegmentSplit())
            elif btn == 3:
                self.cmd_bus.execute(SegmentMerge())
            elif btn == 2:
                self.cmd_bus.execute(SegmentPaint())
            return True

        if tool == "stamp":
            if btn == 1:
                self.cmd_bus.execute(StampApply())
            elif btn == 3:
                self._stamp_capture_begin()
            return True

        if tool == "entity":
            aimed_ent = self._ent_find_aimed()
            if btn == 1:
                if aimed_ent is not None:
                    # Ctrl+click = toggle in selection set
                    if ctrl:
                        self.objects.toggle_select(("entity", aimed_ent))
                    elif shift:
                        self.objects.select(("entity", aimed_ent), add=True)
                    else:
                        self._ent_select(aimed_ent)
                elif self._ent_selected is not None:
                    # Click on ground with selection → move it there
                    self.cmd_bus.execute(EntityMove())
                else:
                    # Click on ground with nothing selected → place new
                    self.cmd_bus.execute(EntityPlace())
            elif btn == 3:
                if self._ent_selected is not None:
                    # RMB while selected → deselect (no accidental delete)
                    self._ent_deselect()
                elif aimed_ent is not None:
                    # RMB on entity with nothing selected → quick-delete
                    self.cmd_bus.execute(EntityDelete(index=aimed_ent))
            return True

        if tool == "box":
            aimed_box = self._box_find_aimed()
            if btn == 1:
                if aimed_box is not None:
                    if ctrl:
                        self.objects.toggle_select(("prism", aimed_box))
                    elif shift:
                        self.objects.select(("prism", aimed_box), add=True)
                    else:
                        self._box_select(aimed_box)
                elif self._box_selected is not None:
                    self.cmd_bus.execute(BoxMove())
                else:
                    self.cmd_bus.execute(BoxPlace())
            elif btn == 3:
                if self._box_selected is not None:
                    self._box_deselect()
                elif aimed_box is not None:
                    self.cmd_bus.execute(BoxDelete(index=aimed_box))
            return True

        # ── New utility tools ─────────────────────────────────────

        if tool == "quad":
            aimed_quad = self._quad_find_aimed()
            if btn == 1:
                if aimed_quad is not None:
                    if ctrl:
                        self.objects.toggle_select(("quad", aimed_quad))
                    elif shift:
                        self.objects.select(("quad", aimed_quad), add=True)
                    else:
                        self._quad_select(aimed_quad)
                elif self._quad_selected is not None:
                    self.cmd_bus.execute(QuadMove())
                else:
                    self.cmd_bus.execute(QuadPlace())
            elif btn == 2:
                self.cmd_bus.execute(QuadToggleTwosided())
            elif btn == 3:
                if self._quad_selected is not None:
                    self._quad_deselect()
                elif aimed_quad is not None:
                    self.cmd_bus.execute(QuadDelete(index=aimed_quad))
            return True

        if tool == "portal":
            if btn == 1:
                self.cmd_bus.execute(PortalPlace())
            elif btn == 3:
                self.cmd_bus.execute(PortalDelete())
            return True

        if tool == "curve":
            aimed_curve = self._curve_find_aimed()
            if btn == 1:
                if aimed_curve is not None:
                    if ctrl:
                        self.objects.toggle_select(("curve", aimed_curve))
                    elif shift:
                        self.objects.select(("curve", aimed_curve), add=True)
                    else:
                        self._curve_select(aimed_curve)
                elif self._curve_selected is not None:
                    self.cmd_bus.execute(CurveMove())
                else:
                    self.cmd_bus.execute(CurvePlace())
            elif btn == 2:
                self.cmd_bus.execute(CurvePaint())
            elif btn == 3:
                if self._curve_selected is not None:
                    self._curve_deselect()
                elif aimed_curve is not None:
                    self.cmd_bus.execute(CurveDelete(index=aimed_curve))
            return True

        if tool == "overlay":
            aimed_ow = self._ow_find_aimed()
            if btn == 1:
                if self._ow_placing:
                    self.cmd_bus.execute(OverlayFinishPlace())
                elif aimed_ow is not None:
                    self._ow_select(aimed_ow)
                elif self._ow_selected is not None:
                    self.cmd_bus.execute(OverlayMove())
                else:
                    self._ow_begin_place()
            elif btn == 2:
                self.cmd_bus.execute(OverlayToggleTransparent())
            elif btn == 3:
                if self._ow_placing:
                    self._ow_cancel_place()
                elif self._ow_selected is not None:
                    self._ow_deselect()
                elif aimed_ow is not None:
                    self.cmd_bus.execute(OverlayDelete(index=aimed_ow))
            return True

        # ── Universal eyedropper fallback: MMB picks texture in any tool ──
        if btn == 2:
            ap = self._paint_aimed_prism
            af = self._paint_aimed_prism_face
            aq = self._paint_aimed_quad
            if ap is not None:
                self._pick_prism_texture(ap, face=af)
            elif aq is not None:
                self._pick_quad_texture(aq)
            else:
                self._pick_texture()
            return True

        return False

    def _on_mouseup(self, event: pygame.event.Event) -> bool:
        """Track mouse button release for continuous paint."""
        if event.button == 1:
            self._lmb_held = False
        return False

    def _on_scroll(self, event: pygame.event.Event) -> bool:
        tool = self.tool

        if tool in ("paint", "segment"):
            palette = _ensure_palette()
            if not palette:
                return False
            self.tex_idx = (self.tex_idx + event.y) % len(palette)
            self.current_texture = palette[self.tex_idx]
            # Sync hotbar slot
            self.hotbar[self.hotbar_slot] = self.current_texture
            return True

        if tool == "stamp":
            self._stamp_cycle(event.y)
            return True

        if tool == "entity":
            shift = bool(pygame.key.get_mods() & pygame.KMOD_SHIFT)
            if shift and self._ent_selected is not None:
                self.cmd_bus.execute(EntityRotate(direction=event.y))
            elif shift and self._ent_selected is None:
                # Rotate placement yaw for prism entity ghost preview
                from core.entity_defs import snap_angle_8dir
                self._ent_place_yaw = snap_angle_8dir(
                    self._ent_place_yaw + event.y * (math.pi / 4.0))
            else:
                self._ent_cycle_palette(event.y)
            return True

        if tool == "box":
            shift = bool(pygame.key.get_mods() & pygame.KMOD_SHIFT)
            ctrl = bool(pygame.key.get_mods() & pygame.KMOD_CTRL)
            if self._box_selected is not None:
                # Selected: Scroll=Z shift, Shift=fine rotate, Ctrl=height
                if shift:
                    self.cmd_bus.execute(BoxRotateFine(direction=event.y))
                elif ctrl:
                    self.cmd_bus.execute(BoxAdjustSize(direction=event.y, axis="h"))
                else:
                    self.cmd_bus.execute(BoxShiftZ(direction=event.y))
            else:
                # Unselected: Scroll=width, Shift=depth, Ctrl=height
                if shift:
                    self.cmd_bus.execute(BoxAdjustSize(direction=event.y, axis="d"))
                elif ctrl:
                    self.cmd_bus.execute(BoxAdjustSize(direction=event.y, axis="h"))
                else:
                    self.cmd_bus.execute(BoxAdjustSize(direction=event.y, axis="w"))
            return True

        # ── New utility tool scroll handling ──────────────────────

        if tool == "quad":
            shift = bool(pygame.key.get_mods() & pygame.KMOD_SHIFT)
            ctrl = bool(pygame.key.get_mods() & pygame.KMOD_CTRL)
            if shift and self._quad_selected is not None:
                self.cmd_bus.execute(QuadRotate(direction=event.y))
            elif ctrl:
                self.cmd_bus.execute(QuadAdjustSize(direction=event.y))
            else:
                palette = _ensure_palette()
                if palette:
                    self.tex_idx = (self.tex_idx + event.y) % len(palette)
                    self.current_texture = palette[self.tex_idx]
                    self.hotbar[self.hotbar_slot] = self.current_texture
            return True

        if tool == "portal":
            self._portal_cycle(event.y)
            return True

        if tool == "curve":
            shift = bool(pygame.key.get_mods() & pygame.KMOD_SHIFT)
            ctrl = bool(pygame.key.get_mods() & pygame.KMOD_CTRL)
            if shift:
                self.cmd_bus.execute(CurveAdjustAngleStart(direction=event.y))
            elif ctrl:
                self.cmd_bus.execute(CurveAdjustAngleEnd(direction=event.y))
            else:
                self.cmd_bus.execute(CurveAdjustRadius(direction=event.y))
            return True

        if tool == "overlay":
            shift = bool(pygame.key.get_mods() & pygame.KMOD_SHIFT)
            if shift:
                self.cmd_bus.execute(OverlayAdjustHeight(direction=event.y))
            else:
                palette = _ensure_palette()
                if palette:
                    self.tex_idx = (self.tex_idx + event.y) % len(palette)
                    self.current_texture = palette[self.tex_idx]
                    self.hotbar[self.hotbar_slot] = self.current_texture
            return True

        if tool == "select":
            # When selection is active, scroll raises/lowers floors (or ceilings)
            if self._has_selection():
                if self._sculpt_layer2:
                    self.cmd_bus.execute(L2SelScroll(direction=event.y))
                    return True
                shift = bool(pygame.key.get_mods() & pygame.KMOD_SHIFT)
                ceiling = shift != self.selection.ceiling_mode  # Shift XORs mode
                return self.cmd_bus.execute(SelScroll(direction=event.y, ceiling=ceiling))
            # No active selection — cycle texture palette
            palette = _ensure_palette()
            if not palette:
                return False
            self.tex_idx = (self.tex_idx + event.y) % len(palette)
            self.current_texture = palette[self.tex_idx]
            self.hotbar[self.hotbar_slot] = self.current_texture
            return True

        if tool == "sculpt":
            shift = bool(pygame.key.get_mods() & pygame.KMOD_SHIFT)
            # Selection active → batch raise/lower via SelScroll
            if self._has_selection() and not self._sculpt_layer2:
                ceiling = shift != self.selection.ceiling_mode  # Shift XORs mode
                return self.cmd_bus.execute(SelScroll(direction=event.y, ceiling=ceiling))
            # Layer 2 sub-mode: scroll raises/lowers L2 height (Shift = palette)
            if self._sculpt_layer2:
                if self._has_selection():
                    self.cmd_bus.execute(L2SelScroll(direction=event.y))
                else:
                    self.cmd_bus.execute(L2Scroll(direction=event.y))
                return True
            part = self.aimed.part if self.aimed else None
            # Map L2 surface hits to L1 equivalents so L2 geometry
            # doesn't block L1 sculpting.
            part = {"floor2": "floor", "ceiling2": "ceiling"}.get(part, part)
            if shift:
                # Shift+Scroll: fine-adjust snap (half steps)
                self.snap_idx = (self.snap_idx + event.y) % len(SNAP_Y_OPTIONS)
                self.snap_y = SNAP_Y_OPTIONS[self.snap_idx]
            elif part == "ceiling":
                self.cmd_bus.execute(SculptScrollUpperWall(direction=event.y))
            elif part in ("floor", "wall", "ground"):
                hit = self.aimed
                if hit:
                    td_obj = tile_def(self.zone.tiles[hit.row][hit.col])
                    if td_obj and td_obj.wall:
                        self.cmd_bus.execute(SculptExtendWallCeiling(cell=(hit.row, hit.col), direction=event.y))
                    else:
                        self.cmd_bus.execute(SculptExtendFloor(cell=(hit.row, hit.col), direction=event.y))
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
        self._cell_box_cache.clear()
        keys = pygame.key.get_pressed()
        speed = FLY_SPEED
        if keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT]:
            speed *= FLY_SPRINT

        if mouse_captured:
            mx, my = pygame.mouse.get_rel()
            self.yaw += mx * MOUSE_SENS
            self.pitch = clamp_pitch(self.pitch - my * MOUSE_SENS)

        if keys[self.kb.key_for("camera.yaw_left")]:
            self.yaw -= KB_TURN_SPEED * dt
        if keys[self.kb.key_for("camera.yaw_right")]:
            self.yaw += KB_TURN_SPEED * dt

        dx, dy, dz = wasd_3d(
            self.yaw, self.pitch,
            forward=keys[self.kb.key_for("camera.forward")],
            backward=keys[self.kb.key_for("camera.backward")],
            strafe_left=keys[self.kb.key_for("camera.left")],
            strafe_right=keys[self.kb.key_for("camera.right")],
            up=keys[self.kb.key_for("camera.up")],
            down=keys[self.kb.key_for("camera.down")],
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

        # Continuous paint: if LMB held + paint tool, paint every frame.
        # execute_continuation() skips the undo push so the entire drag
        # stroke is captured by the single snapshot taken on MOUSEBUTTONDOWN.
        if self._lmb_held and self.tool == "paint" and self.aimed:
            if self._paint_aimed_prism is None and self._paint_aimed_quad is None:
                self.cmd_bus.execute_continuation(ContinuousPaint())

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
        """Cast a ray from camera forward; find nearest cell box or ground.

        Uses ``_layer_cell_boxes`` so the ray respects the active layer
        and isolation setting.
        """
        fx, fy, fz = self._forward()
        ox, oy, oz = self.cam_x, self.cam_y, self.cam_z
        zone = self.zone
        W, H = zone.width, zone.height

        best: _CellHit | None = None

        # Ground-plane hit (only relevant when L1 is active or not isolated)
        active_l = self.active_layer
        isolating = self.isolate_layer
        show_ground = not (isolating and active_l == 2)

        if show_ground and abs(fy) > 1e-10:
            t = (0.0 - oy) / fy
            if 0.01 < t < FAR_CLIP:
                hx = ox + fx * t
                hz = oz + fz * t
                c = int(math.floor(hx))
                r = int(math.floor(hz))
                if 0 <= c < W and 0 <= r < H:
                    blocked = False
                    for part, yb, yt in self._layer_cell_boxes(r, c):
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
        search = min(int(FAR_CLIP) + 1, 16)
        r_lo = max(0, cam_r - search)
        r_hi = min(H, cam_r + search)
        c_lo = max(0, cam_c - search)
        c_hi = min(W, cam_c + search)
        for r in range(r_lo, r_hi):
            for c in range(c_lo, c_hi):
                for part, yb, yt in self._layer_cell_boxes(r, c):
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
        self._paint_update_aim()

        # Update rectangle preview for select tool live feedback
        if self.tool == "select" and best is not None:
            if self.selection.rect_in_progress:
                self.selection.update_rect(best.row, best.col)

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
                elif hit.part == "floor2":
                    f2 = getattr(zone, 'floor2_heights', None)
                    if f2 and len(f2) > r:
                        f2v = f2[r][c]
                        if f2v > -999:
                            lo = min(fh, f2v)
                            hi = max(fh, f2v)
                            if hi - lo > 0.02:
                                split_y = round(hit.hit_y / snap) * snap
                                split_y = max(lo + 0.01, min(hi - 0.01, split_y))
                                self.preview_line = (c, r, split_y, COL_SEG_LINE, face)
                elif hit.part == "ceiling2":
                    c2 = getattr(zone, 'ceil2_heights', None)
                    if c2 and len(c2) > r:
                        c2v = c2[r][c]
                        if c2v > -999:
                            uwh2_grid = getattr(zone, 'upper_wall_height2', None)
                            uwh2 = uwh2_grid[r][c] if (uwh2_grid and len(uwh2_grid) > r) else 0.0
                            c2_top = uwh2 if uwh2 > c2v else c2v + 0.3
                            if c2_top - c2v > 0.02:
                                split_y = round(hit.hit_y / snap) * snap
                                split_y = max(c2v + 0.01, min(c2_top - 0.01, split_y))
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
            elif part == "floor2":
                LAYER_NONE_VAL = -1000.0
                f2h = getattr(zone, 'floor2_heights', None)
                if f2h and len(f2h) > r:
                    fv2 = f2h[r][c]
                    if fv2 > LAYER_NONE_VAL + 1.0:
                        target_up = min(fv2 + snap, FLOOR_MAX)
                        self.preview_line = (c, r, target_up, (200, 160, 255))
            elif part == "ceiling2":
                LAYER_NONE_VAL = -1000.0
                c2h = getattr(zone, 'ceil2_heights', None)
                if c2h and len(c2h) > r:
                    cv2 = c2h[r][c]
                    if cv2 > LAYER_NONE_VAL + 1.0:
                        target_dn = max(cv2 - snap, CEIL_MIN)
                        self.preview_line = (c, r, target_dn, (160, 120, 230))
            return

    # -- State clipboard (Ctrl+C / Ctrl+V) -------------------------

    def _clipboard_copy(self) -> None:
        """Copy the aimed cell's full state to the clipboard."""
        hit = self.aimed
        if not hit:
            return
        z = self.zone
        r, c = hit.row, hit.col
        from editor.view_3d.tools_layer2 import LAYER_NONE
        state: dict = {
            "floor_height": z.floor_heights[r][c],
            "ceil_height": z.ceil_heights[r][c],
            "tile": z.tiles[r][c],
            "floor_texture": z.floor_textures[r][c] if z.floor_textures else "",
            "ceil_texture": z.ceil_textures[r][c] if z.ceil_textures else "",
            "wall_texture": z.wall_textures[r][c] if z.wall_textures else "",
        }
        if z.face_textures and r < len(z.face_textures) and c < len(z.face_textures[r]):
            state["face_textures"] = list(z.face_textures[r][c])
        if z.light_levels and r < len(z.light_levels):
            state["light_level"] = z.light_levels[r][c]
        if z.reflect_map and r < len(z.reflect_map):
            state["reflect"] = z.reflect_map[r][c]
        if z.upper_wall_height and r < len(z.upper_wall_height):
            state["upper_wall_height"] = z.upper_wall_height[r][c]
        if z.wall_segments and r < len(z.wall_segments):
            state["wall_segments"] = [[s[:] for s in f] for f in z.wall_segments[r][c]]
        if z.floor_step_segments and r < len(z.floor_step_segments):
            state["floor_step_segments"] = [[s[:] for s in f] for f in z.floor_step_segments[r][c]]
        if z.ceil_step_segments and r < len(z.ceil_step_segments):
            state["ceil_step_segments"] = [[s[:] for s in f] for f in z.ceil_step_segments[r][c]]
        # Layer 2
        f2 = getattr(z, 'floor2_heights', None)
        c2 = getattr(z, 'ceil2_heights', None)
        if f2 and r < len(f2):
            state["floor2_height"] = f2[r][c]
        if c2 and r < len(c2):
            state["ceil2_height"] = c2[r][c]
        f2t = getattr(z, 'floor2_textures', None)
        c2t = getattr(z, 'ceil2_textures', None)
        if f2t and r < len(f2t):
            state["floor2_texture"] = f2t[r][c]
        if c2t and r < len(c2t):
            state["ceil2_texture"] = c2t[r][c]
        uwh2 = getattr(z, 'upper_wall_height2', None)
        if uwh2 and r < len(uwh2):
            state["upper_wall_height2"] = uwh2[r][c]
        if hasattr(z, 'fog_density') and z.fog_density and r < len(z.fog_density):
            state["fog_density"] = z.fog_density[r][c]
        # Entities occupying this cell
        cell_ents = []
        if z.entities:
            for ent in z.entities:
                ex, ey = float(ent.get("x", 0)), float(ent.get("y", 0))
                if int(ey) == r and int(ex) == c:
                    cell_ents.append({k: (v.copy() if isinstance(v, (dict, list)) else v)
                                      for k, v in ent.items()})
        if cell_ents:
            state["entities"] = cell_ents
        self._clipboard = state
        self._flash("Copied", 0.8, (0.7, 0.9, 1.0, 1.0))

    def _clipboard_paste(self) -> None:
        """Paste the clipboard state onto the selection or aimed cell,
        respecting the active paste mask."""
        if not self._clipboard:
            self._flash("Nothing to paste", 0.8, (0.6, 0.5, 0.4, 1.0))
            return
        mask = self._paste_mask
        state = self._clipboard
        z = self.zone

        self._push_undo()
        self._ensure_face_textures()

        def _apply(r: int, c: int) -> bool:
            changed = False
            if PASTE_MASK_HEIGHTS in mask:
                if "floor_height" in state:
                    z.floor_heights[r][c] = state["floor_height"]
                    changed = True
                if "ceil_height" in state:
                    z.ceil_heights[r][c] = state["ceil_height"]
                    changed = True
                if "upper_wall_height" in state and z.upper_wall_height:
                    z.upper_wall_height[r][c] = state["upper_wall_height"]
                if "tile" in state:
                    z.tiles[r][c] = state["tile"]
                if "floor2_height" in state:
                    self._layer2_ensure_grids()
                    z.floor2_heights[r][c] = state["floor2_height"]
                if "ceil2_height" in state:
                    self._layer2_ensure_grids()
                    z.ceil2_heights[r][c] = state["ceil2_height"]
                if "upper_wall_height2" in state:
                    self._layer2_ensure_grids()
                    z.upper_wall_height2[r][c] = state["upper_wall_height2"]
            if PASTE_MASK_TEXTURES in mask:
                if "floor_texture" in state and z.floor_textures:
                    z.floor_textures[r][c] = state["floor_texture"]
                    changed = True
                if "ceil_texture" in state and z.ceil_textures:
                    z.ceil_textures[r][c] = state["ceil_texture"]
                    changed = True
                if "wall_texture" in state and z.wall_textures:
                    z.wall_textures[r][c] = state["wall_texture"]
                if "face_textures" in state and z.face_textures:
                    z.face_textures[r][c] = list(state["face_textures"])
                if "floor2_texture" in state and getattr(z, 'floor2_textures', None):
                    z.floor2_textures[r][c] = state["floor2_texture"]
                if "ceil2_texture" in state and getattr(z, 'ceil2_textures', None):
                    z.ceil2_textures[r][c] = state["ceil2_texture"]
            if PASTE_MASK_SEGMENTS in mask:
                if "wall_segments" in state and z.wall_segments:
                    z.wall_segments[r][c] = [[s[:] for s in f] for f in state["wall_segments"]]
                    changed = True
                if "floor_step_segments" in state and z.floor_step_segments:
                    z.floor_step_segments[r][c] = [[s[:] for s in f] for f in state["floor_step_segments"]]
                if "ceil_step_segments" in state and z.ceil_step_segments:
                    z.ceil_step_segments[r][c] = [[s[:] for s in f] for f in state["ceil_step_segments"]]
            if PASTE_MASK_LIGHTING in mask:
                if "light_level" in state and z.light_levels:
                    z.light_levels[r][c] = state["light_level"]
                    changed = True
                if "reflect" in state and z.reflect_map:
                    z.reflect_map[r][c] = state["reflect"]
                if "fog_density" in state and hasattr(z, 'fog_density') and z.fog_density:
                    z.fog_density[r][c] = state["fog_density"]
            if PASTE_MASK_ENTITIES in mask:
                if "entities" in state:
                    # Remove existing entities at target cell
                    if z.entities:
                        z.entities = [
                            e for e in z.entities
                            if not (int(float(e.get("y", 0))) == r and
                                    int(float(e.get("x", 0))) == c)
                        ]
                    else:
                        z.entities = []
                    # Paste cloned entities with updated positions
                    for ent in state["entities"]:
                        clone = {k: (v.copy() if isinstance(v, (dict, list)) else v)
                                 for k, v in ent.items()}
                        # Assign fresh UID to the clone
                        clone["uid"] = z.next_uid()
                        # Remap to target cell centre
                        orig_x = float(ent.get("x", 0))
                        orig_y = float(ent.get("y", 0))
                        frac_x = orig_x - int(orig_x)
                        frac_y = orig_y - int(orig_y)
                        clone["x"] = round(c + frac_x, 3)
                        clone["y"] = round(r + frac_y, 3)
                        z.entities.append(clone)
                    changed = True
            return changed

        if self._has_selection():
            self._apply_to_selection(_apply)
        elif self.aimed:
            _apply(self.aimed.row, self.aimed.col)
        self.dirty = True
        self._flash("Pasted", 0.8, (0.7, 0.9, 1.0, 1.0))

    def _duplicate_selection(self) -> None:
        """Duplicate selected cells, shifting them +1 row / +1 col (Ctrl+D).

        Works like copy-then-paste-at-offset: clones all cell properties
        from each selected cell into the cell one step down-right,
        clamped to zone bounds.  The new positions become the new selection.
        """
        if not self._has_selection():
            self._flash("Nothing selected", 0.8, (0.6, 0.5, 0.4, 1.0))
            return

        z = self.zone
        cells = list(self.selection.iter_cells())

        # Compute bounding-box to choose offset direction
        min_r = min(r for r, _ in cells)
        max_r = max(r for r, _ in cells)
        min_c = min(c for _, c in cells)
        max_c = max(c for _, c in cells)

        # Pick offset: prefer +1,+1 but clamp so everything stays in bounds
        dr = 1 if max_r + 1 < z.height else (-1 if min_r - 1 >= 0 else 0)
        dc = 1 if max_c + 1 < z.width else (-1 if min_c - 1 >= 0 else 0)
        if dr == 0 and dc == 0:
            self._flash("No room to duplicate", 0.8, (0.6, 0.5, 0.4, 1.0))
            return

        self._push_undo()
        self._ensure_face_textures()

        new_cells: set[tuple[int, int]] = set()
        for r, c in cells:
            nr, nc = r + dr, c + dc
            if not (0 <= nr < z.height and 0 <= nc < z.width):
                continue
            # Heights
            z.floor_heights[nr][nc] = z.floor_heights[r][c]
            z.ceil_heights[nr][nc] = z.ceil_heights[r][c]
            z.tiles[nr][nc] = z.tiles[r][c]
            if z.upper_wall_height:
                z.upper_wall_height[nr][nc] = z.upper_wall_height[r][c]
            # Textures
            if z.floor_textures:
                z.floor_textures[nr][nc] = z.floor_textures[r][c]
            if z.ceil_textures:
                z.ceil_textures[nr][nc] = z.ceil_textures[r][c]
            if z.wall_textures:
                z.wall_textures[nr][nc] = z.wall_textures[r][c]
            if z.face_textures:
                z.face_textures[nr][nc] = list(z.face_textures[r][c])
            # Segments
            if z.wall_segments:
                z.wall_segments[nr][nc] = [[s[:] for s in f] for f in z.wall_segments[r][c]]
            if z.floor_step_segments:
                z.floor_step_segments[nr][nc] = [[s[:] for s in f] for f in z.floor_step_segments[r][c]]
            if z.ceil_step_segments:
                z.ceil_step_segments[nr][nc] = [[s[:] for s in f] for f in z.ceil_step_segments[r][c]]
            # Lighting
            if z.light_levels:
                z.light_levels[nr][nc] = z.light_levels[r][c]
            if z.reflect_map:
                z.reflect_map[nr][nc] = z.reflect_map[r][c]
            if hasattr(z, 'fog_density') and z.fog_density:
                z.fog_density[nr][nc] = z.fog_density[r][c]
            # Layer 2
            if getattr(z, 'floor2_heights', None):
                z.floor2_heights[nr][nc] = z.floor2_heights[r][c]
            if getattr(z, 'ceil2_heights', None):
                z.ceil2_heights[nr][nc] = z.ceil2_heights[r][c]
            if getattr(z, 'floor2_textures', None):
                z.floor2_textures[nr][nc] = z.floor2_textures[r][c]
            if getattr(z, 'ceil2_textures', None):
                z.ceil2_textures[nr][nc] = z.ceil2_textures[r][c]
            if getattr(z, 'upper_wall_height2', None):
                z.upper_wall_height2[nr][nc] = z.upper_wall_height2[r][c]
            new_cells.add((nr, nc))

        # Move selection to the duplicated region
        self.selection.cells.clear()
        self.selection.cells.update(new_cells)
        self.dirty = True
        n = len(new_cells)
        self._flash(f"Duplicated {n} cell{'s' if n != 1 else ''}", 0.8, (0.7, 1.0, 0.7, 1.0))

    # -- Smart selection helpers ------------------------------------

    def _select_contiguous(self, r: int, c: int) -> None:
        """Flood-fill select cells sharing the same Z-height as (r, c)."""
        z = self.zone
        fh = z.floor_heights[r][c]
        ch = z.ceil_heights[r][c]
        tile = z.tiles[r][c]
        W, H = z.width, z.height
        # L2 height matching when in L2 mode
        l2 = getattr(self, '_sculpt_layer2', False)
        LAYER_NONE = -1000.0
        f2h_grid = getattr(z, 'floor2_heights', None) if l2 else None
        c2h_grid = getattr(z, 'ceil2_heights', None) if l2 else None
        ref_f2 = f2h_grid[r][c] if f2h_grid and len(f2h_grid) > r else LAYER_NONE
        ref_c2 = c2h_grid[r][c] if c2h_grid and len(c2h_grid) > r else LAYER_NONE
        visited: set[tuple[int, int]] = set()
        stack = [(r, c)]
        while stack:
            cr, cc = stack.pop()
            if (cr, cc) in visited:
                continue
            if not (0 <= cr < H and 0 <= cc < W):
                continue
            if abs(z.floor_heights[cr][cc] - fh) > 0.01:
                continue
            if abs(z.ceil_heights[cr][cc] - ch) > 0.01:
                continue
            if z.tiles[cr][cc] != tile:
                continue
            # L2 height match
            if f2h_grid and len(f2h_grid) > cr:
                nf2 = f2h_grid[cr][cc]
                if abs(nf2 - ref_f2) > 0.01:
                    continue
            if c2h_grid and len(c2h_grid) > cr:
                nc2 = c2h_grid[cr][cc]
                if abs(nc2 - ref_c2) > 0.01:
                    continue
            visited.add((cr, cc))
            stack.extend([(cr-1, cc), (cr+1, cc), (cr, cc-1), (cr, cc+1)])
        self.selection.cells.update(visited)

    def _select_similar(self) -> None:
        """Select all cells on the active layer sharing exact properties
        of the aimed cell (Shift+G)."""
        hit = self.aimed
        if not hit:
            return
        z = self.zone
        r, c = hit.row, hit.col
        fh = z.floor_heights[r][c]
        ch = z.ceil_heights[r][c]
        tile = z.tiles[r][c]
        ft = z.floor_textures[r][c] if z.floor_textures else ""
        wt = z.wall_textures[r][c] if z.wall_textures else ""
        # L2 matching when in L2 mode
        l2 = getattr(self, '_sculpt_layer2', False)
        LAYER_NONE = -1000.0
        f2h_grid = getattr(z, 'floor2_heights', None) if l2 else None
        c2h_grid = getattr(z, 'ceil2_heights', None) if l2 else None
        ref_f2 = f2h_grid[r][c] if f2h_grid and len(f2h_grid) > r else LAYER_NONE
        ref_c2 = c2h_grid[r][c] if c2h_grid and len(c2h_grid) > r else LAYER_NONE
        for rr in range(z.height):
            for cc in range(z.width):
                if abs(z.floor_heights[rr][cc] - fh) > 0.01:
                    continue
                if abs(z.ceil_heights[rr][cc] - ch) > 0.01:
                    continue
                if z.tiles[rr][cc] != tile:
                    continue
                zft = z.floor_textures[rr][cc] if z.floor_textures else ""
                zwt = z.wall_textures[rr][cc] if z.wall_textures else ""
                if zft != ft or zwt != wt:
                    continue
                # L2 height match
                if f2h_grid and len(f2h_grid) > rr:
                    if abs(f2h_grid[rr][cc] - ref_f2) > 0.01:
                        continue
                if c2h_grid and len(c2h_grid) > rr:
                    if abs(c2h_grid[rr][cc] - ref_c2) > 0.01:
                        continue
                self.selection.add_cell(rr, cc)
