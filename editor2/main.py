"""editor2/main.py — Qt + OpenGL zone editor entry point.

Usage:
    python -m editor2.main [zone_name]
    python -m editor2.main test
"""

from __future__ import annotations

import logging
import math
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QFont, QKeySequence, QSurfaceFormat
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QDockWidget,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMenu, QMessageBox, QPlainTextEdit,
    QSpinBox, QStackedWidget, QToolBar, QVBoxLayout, QWidget,
)

log = logging.getLogger(__name__)

# ── Ensure project root is importable ──
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.zones import load_zone, list_zones, Zone, ZONES_DIR
from core.tiles import tile_def
from core.tiles.registry import rebuild_derived
from editor.app.session_cfg import load_session, save_session, push_recent
from editor2.atlas import TileAtlas
from editor2.core import CommandBus
from editor2.panels.inspector import PaintInspector
from editor2.panels.sculpt_inspector import SculptInspector
from editor2.panels.cell_inspector import CellInspector
from editor2.panels.select_inspector import SelectInspector
from editor2.panels.tile_inspector import TileTypeInspector
from editor2.panels.erase_inspector import EraseInspector
from editor2.panels.entity_inspector import EntityInspector
from editor2.panels.light_inspector import LightInspector
from editor2.panels.minimap import MinimapPanel
from editor2.panels.raycaster_mini import RaycasterMiniView
from editor2.raycaster_preview import RaycasterPreview
from editor2.selection import SelectionState
from editor2.tools.erase import EraseTool
from editor2.tools.entity import EntityTool
from editor2.tools.light import LightTool
from editor2.tools.paint import PaintTool
from editor2.tools.sculpt import SculptTool, SNAP_LABELS, SNAP_PRESETS
from editor2.tools.select import SelectTool
from editor2.tools.tile_type import TileTypeTool
from editor2.viewport import ZoneViewport


def _create_empty_zone(w: int = 20, h: int = 20) -> Zone:
    """Create a blank in-memory zone (not saved to disk)."""
    return Zone(
        name="untitled", width=w, height=h,
        anchor=(h / 2.0, w / 2.0),
        first_person=True,
        tiles=[["grass"] * w for _ in range(h)],
        floor_heights=[[0.0] * w for _ in range(h)],
        ceil_heights=[[10.0] * w for _ in range(h)],
        floor_textures=[[""] * w for _ in range(h)],
        ceil_textures=[[""] * w for _ in range(h)],
        wall_textures=[[""] * w for _ in range(h)],
        face_textures=[[[""] * 4 for _ in range(w)] for _ in range(h)],
        light_levels=[[1.0] * w for _ in range(h)],
        rotations=[[0] * w for _ in range(h)],
        wall_segments=[[[[], [], [], []] for _ in range(w)] for _ in range(h)],
        floor_step_textures=[[[""] * 4 for _ in range(w)] for _ in range(h)],
        ceil_step_textures=[[[""] * 4 for _ in range(w)] for _ in range(h)],
        floor_step_segments=[[[[], [], [], []] for _ in range(w)] for _ in range(h)],
        ceil_step_segments=[[[[], [], [], []] for _ in range(w)] for _ in range(h)],
        upper_wall_height=[[0.0] * w for _ in range(h)],
    )


class EditorWindow(QMainWindow):
    def __init__(self, zone: Zone, zone_name: str = "") -> None:
        super().__init__()
        self._zone_name = zone_name or zone.name
        self._session = load_session()
        self._dirty = False

        self.resize(1400, 900)

        # ── Shared resources ──
        self._atlas = TileAtlas()
        self._bus = CommandBus(zone, self)

        # ── Viewport + Raycaster (stacked central widget) ──
        self.viewport = ZoneViewport(zone, self._atlas, self)
        self._raycaster = RaycasterPreview(zone, self)

        self._central_stack = QStackedWidget(self)
        self._central_stack.addWidget(self.viewport)    # index 0 = 3D
        self._central_stack.addWidget(self._raycaster)   # index 1 = 2.5D
        self._central_stack.setCurrentIndex(0)
        self.setCentralWidget(self._central_stack)

        self._view_mode = "3d"  # "3d" | "2d"
        self._show_entities = True

        self.viewport.on_hover = self._update_status_bar
        self.viewport._on_scroll = self._on_viewport_scroll
        self.viewport.extra_overlays = self._get_selection_overlays
        self.viewport.on_eyedrop = self._on_eyedrop

        # ── Default camera: elevated isometric-ish view ──
        cam = self.viewport.camera
        cam.x = zone.width * 0.5
        cam.z = zone.height * 0.5
        cam.y = max(zone.width, zone.height) * 0.6
        cam.pitch = -0.75   # ~43° downward
        cam.yaw = 0.78      # ~45° rotated

        # ── Selection (shared across tools) ──
        self._selection = SelectionState()

        # ── Tools ──
        self._paint_tool = PaintTool(zone, self._bus, cam)
        self._sculpt_tool = SculptTool(zone, self._bus, cam)
        self._select_tool = SelectTool(zone, self._bus, cam, self._selection)
        self._erase_tool = EraseTool(zone, self._bus, cam)
        self._tile_type_tool = TileTypeTool(zone, self._bus, cam)
        self._entity_tool = EntityTool(zone, self._bus, cam)
        self._light_tool = LightTool(zone, self._bus, cam)
        self._active_tool_name = "paint"

        self.viewport.tool = self._paint_tool

        # ── Clipboard ──
        self._clipboard: list[dict] | None = None
        self._clipboard_origin: tuple[int, int] = (0, 0)

        # ── Camera bookmarks (Shift+1..9 save, 1..9 recall in select) ──
        self._cam_bookmarks: dict[int, tuple[float, ...]] = {}

        # ── Inspector dock ──
        self._paint_inspector = PaintInspector(self._paint_tool, self._atlas)
        self._sculpt_inspector = SculptInspector(self._sculpt_tool)
        self._select_inspector = SelectInspector()
        self._erase_inspector = EraseInspector()
        self._tile_type_inspector = TileTypeInspector(self._tile_type_tool)
        self._entity_inspector = EntityInspector(self._entity_tool)
        self._light_inspector = LightInspector(self._light_tool)

        self._inspector_dock = QDockWidget("Paint", self)
        self._inspector_dock.setObjectName("InspectorDock")
        self._inspector_dock.setWidget(self._paint_inspector)
        self._inspector_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea,
                           self._inspector_dock)

        # ── Cell inspector dock (left side) ──
        self._cell_inspector = CellInspector(zone)
        self._cell_dock = QDockWidget("Cell Info", self)
        self._cell_dock.setObjectName("CellInfoDock")
        self._cell_dock.setWidget(self._cell_inspector)
        self._cell_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea,
                           self._cell_dock)

        # ── Minimap / Preview dock ──
        self._minimap = MinimapPanel(zone)
        self._mini_preview = RaycasterMiniView(zone)

        self._minimap_stack = QStackedWidget(self)
        self._minimap_stack.addWidget(self._mini_preview)  # index 0 = 2.5D preview
        self._minimap_stack.addWidget(self._minimap)        # index 1 = minimap
        self._minimap_stack.setCurrentIndex(0)  # start with preview (3D editing mode)

        self._minimap_dock = QDockWidget("Preview", self)
        self._minimap_dock.setObjectName("MinimapDock")
        self._minimap_dock.setWidget(self._minimap_stack)
        self._minimap_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea,
                           self._minimap_dock)

        # Timer drives both minimap + mini-preview camera sync (~8 Hz)
        self._minimap_timer = QTimer(self)
        self._minimap_timer.timeout.connect(self._update_minimap)
        self._minimap_timer.start(120)

        # ── Signals ──
        self._bus.zone_changed.connect(self._on_zone_changed)
        self._paint_tool.on_changed = self._on_tool_changed
        self._sculpt_tool.on_changed = self._on_tool_changed
        self._select_tool.on_changed = self._on_tool_changed
        self._erase_tool.on_changed = self._on_tool_changed
        self._tile_type_tool.on_changed = self._on_tool_changed
        self._entity_tool.on_changed = self._on_tool_changed
        self._light_tool.on_changed = self._on_tool_changed

        # Select inspector button wiring
        self._select_inspector.set_texture_list(self._atlas.keys)
        self._select_inspector.btn_fill.clicked.connect(self._sel_fill)
        self._select_inspector.btn_clear_tex.clicked.connect(self._sel_clear_tex)
        self._select_inspector.btn_reset.clicked.connect(self._sel_reset)
        self._select_inspector.btn_flatten.clicked.connect(self._sel_flatten)
        self._select_inspector.btn_wall.clicked.connect(
            lambda: self._select_tool.make_wall())
        self._select_inspector.btn_open.clicked.connect(
            lambda: self._select_tool.make_open())
        self._select_inspector.btn_toggle_ceil.clicked.connect(
            self._sel_toggle_ceiling)

        # ── Menu bar ──
        self._build_menus()

        # ── Toolbar ──
        self._build_toolbar()

        # ── Shortcuts ──
        # (Tool shortcuts handled by toolbar actions)

        # ── Status bar ──
        self._cell_label = QLabel("Cell: —")
        self._height_label = QLabel("Heights: —")
        self._snap_label = QLabel("Snap: —")
        self._tex_label = QLabel("Tex: —")
        self._perf_label = QLabel()
        self._perf_label.hide()
        sb = self.statusBar()
        sb.addWidget(self._cell_label, 1)
        sb.addWidget(self._height_label, 1)
        sb.addPermanentWidget(self._snap_label)
        sb.addPermanentWidget(self._tex_label)
        sb.addPermanentWidget(self._perf_label)

        self._perf_timer = QTimer(self)
        self._perf_timer.timeout.connect(self._update_perf)

        self._update_title()
        self._restore_geometry()

    # ── Menu construction ─────────────────────────────────────────

    def _build_menus(self) -> None:
        mb = self.menuBar()

        file_menu = mb.addMenu("&File")

        new_act = file_menu.addAction("&New Zone...")
        new_act.setShortcut(QKeySequence.StandardKey.New)
        new_act.triggered.connect(self._on_new_zone)

        open_act = file_menu.addAction("&Open Zone...")
        open_act.setShortcut(QKeySequence.StandardKey.Open)
        open_act.triggered.connect(self._on_open_zone)

        # ── Recent zones submenu ──
        self._recent_menu = QMenu("Recent Zones", self)
        file_menu.addMenu(self._recent_menu)
        self._rebuild_recent_menu()

        file_menu.addSeparator()

        save_act = file_menu.addAction("&Save")
        save_act.setShortcut(QKeySequence.StandardKey.Save)
        save_act.triggered.connect(self._on_save)

        save_as_act = file_menu.addAction("Save &As...")
        save_as_act.setShortcut(QKeySequence("Ctrl+Shift+S"))
        save_as_act.triggered.connect(self._on_save_as)

        file_menu.addSeparator()

        quit_act = file_menu.addAction("&Quit")
        quit_act.setShortcut(QKeySequence.StandardKey.Quit)
        quit_act.triggered.connect(self.close)

        # ── Edit menu ──
        edit_menu = mb.addMenu("&Edit")

        undo_menu_act = edit_menu.addAction("&Undo")
        undo_menu_act.setShortcut(QKeySequence.StandardKey.Undo)
        undo_menu_act.triggered.connect(self._bus.undo)

        redo_menu_act = edit_menu.addAction("&Redo")
        redo_menu_act.setShortcut(QKeySequence.StandardKey.Redo)
        redo_menu_act.triggered.connect(self._bus.redo)

        edit_menu.addSeparator()

        find_replace_act = edit_menu.addAction("Find / &Replace Texture...")
        find_replace_act.setShortcut(QKeySequence("Ctrl+F"))
        find_replace_act.triggered.connect(self._on_find_replace)

        edit_menu.addSeparator()

        copy_act = edit_menu.addAction("&Copy Selection")
        copy_act.setShortcut(QKeySequence("Ctrl+C"))
        copy_act.triggered.connect(self._copy_selection)

        paste_act = edit_menu.addAction("&Paste")
        paste_act.setShortcut(QKeySequence("Ctrl+V"))
        paste_act.triggered.connect(self._paste_clipboard)

        # ── Tools menu ──
        tools_menu = mb.addMenu("&Tools")

        paint_act = tools_menu.addAction("&Paint")
        paint_act.triggered.connect(lambda: self._switch_tool("paint"))

        sculpt_act = tools_menu.addAction("&Sculpt")
        sculpt_act.triggered.connect(lambda: self._switch_tool("sculpt"))

        select_act = tools_menu.addAction("Se&lect")
        select_act.triggered.connect(lambda: self._switch_tool("select"))

        erase_act = tools_menu.addAction("&Erase")
        erase_act.triggered.connect(lambda: self._switch_tool("erase"))

        tile_type_act = tools_menu.addAction("&Tile Type")
        tile_type_act.triggered.connect(lambda: self._switch_tool("tile_type"))

        tools_menu.addSeparator()

        entity_act = tools_menu.addAction("E&ntity")
        entity_act.triggered.connect(lambda: self._switch_tool("entity"))

        light_act = tools_menu.addAction("&Light")
        light_act.triggered.connect(lambda: self._switch_tool("light"))

        # ── View menu ──
        view_menu = mb.addMenu("&View")

        self._grid_act = view_menu.addAction("Show &Grid")
        self._grid_act.setCheckable(True)
        self._grid_act.setChecked(True)
        self._grid_act.toggled.connect(self._toggle_grid)

        self._wire_act = view_menu.addAction("&Wireframe")
        self._wire_act.setCheckable(True)
        self._wire_act.setChecked(False)
        self._wire_act.setShortcut(QKeySequence("Ctrl+5"))
        self._wire_act.toggled.connect(self._toggle_wireframe)

        view_menu.addSeparator()

        self._show_walls_act = view_menu.addAction("Show &Walls")
        self._show_walls_act.setCheckable(True)
        self._show_walls_act.setChecked(True)
        self._show_walls_act.setShortcut(QKeySequence("Ctrl+1"))
        self._show_walls_act.toggled.connect(
            lambda on: self._toggle_layer_vis("walls", on))

        self._show_floors_act = view_menu.addAction("Show &Floors")
        self._show_floors_act.setCheckable(True)
        self._show_floors_act.setChecked(True)
        self._show_floors_act.setShortcut(QKeySequence("Ctrl+2"))
        self._show_floors_act.toggled.connect(
            lambda on: self._toggle_layer_vis("floors", on))

        self._show_ceilings_act = view_menu.addAction("Show &Ceilings")
        self._show_ceilings_act.setCheckable(True)
        self._show_ceilings_act.setChecked(True)
        self._show_ceilings_act.setShortcut(QKeySequence("Ctrl+3"))
        self._show_ceilings_act.toggled.connect(
            lambda on: self._toggle_layer_vis("ceilings", on))

        self._show_entities_act = view_menu.addAction("Show &Entities")
        self._show_entities_act.setCheckable(True)
        self._show_entities_act.setChecked(True)
        self._show_entities_act.setShortcut(QKeySequence("Ctrl+4"))
        self._show_entities_act.toggled.connect(self._toggle_entity_vis)

        view_menu.addSeparator()

        reset_cam_act = view_menu.addAction("&Reset Camera")
        reset_cam_act.setShortcut(QKeySequence("Home"))
        reset_cam_act.triggered.connect(self._reset_camera)

        view_menu.addSeparator()

        self._preview_act = view_menu.addAction("Toggle 2.5D &Preview")
        self._preview_act.setShortcut(QKeySequence("Tab"))
        self._preview_act.triggered.connect(self._toggle_view_mode)

        # ── Zone menu ──
        zone_menu = mb.addMenu("&Zone")

        resize_act = zone_menu.addAction("&Resize Zone...")
        resize_act.triggered.connect(self._on_resize_zone)

        zone_menu.addSeparator()

        zone_info_act = zone_menu.addAction("Zone &Info")
        zone_info_act.triggered.connect(self._on_zone_info)

        zone_menu.addSeparator()

        dup_act = zone_menu.addAction("&Duplicate Zone...")
        dup_act.triggered.connect(self._on_duplicate_zone)

        validate_act = zone_menu.addAction("&Validate Zone")
        validate_act.triggered.connect(self._on_validate_zone)

        export_act = zone_menu.addAction("&Export Top-Down Image...")
        export_act.triggered.connect(self._on_export_topdown)

        zone_menu.addSeparator()

        zone_settings_act = zone_menu.addAction("Zone &Settings...")
        zone_settings_act.triggered.connect(self._on_zone_settings)

        # ── Window menu ──
        window_menu = mb.addMenu("&Window")

        help_act = window_menu.addAction("&Keyboard Shortcuts")
        help_act.setShortcut(QKeySequence("?"))
        help_act.triggered.connect(self._show_help)

        # ── Debug menu ──
        debug_menu = mb.addMenu("&Debug")

        self._perf_act = debug_menu.addAction("Show &Performance")
        self._perf_act.setCheckable(True)
        self._perf_act.setShortcut(QKeySequence("F3"))
        self._perf_act.toggled.connect(self._toggle_perf)

        log_menu = debug_menu.addMenu("Log Level")
        for level_name in ("DEBUG", "INFO", "WARNING"):
            act = log_menu.addAction(level_name)
            act.triggered.connect(
                lambda checked=False, lv=level_name: self._set_log_level(lv))

        debug_menu.addSeparator()
        dump_act = debug_menu.addAction("Dump &Stats")
        dump_act.setShortcut(QKeySequence("F4"))
        dump_act.triggered.connect(self._dump_stats)

    def _rebuild_recent_menu(self) -> None:
        self._recent_menu.clear()
        recent = self._session.get("recent_zones", [])
        if not recent:
            act = self._recent_menu.addAction("(no recent zones)")
            act.setEnabled(False)
            return
        for name in recent:
            act = self._recent_menu.addAction(name)
            act.triggered.connect(lambda checked=False, n=name: self._switch_zone(n))

    # ── Toolbar ───────────────────────────────────────────────────

    def _build_toolbar(self) -> None:
        tb = QToolBar("Tools", self)
        tb.setObjectName("ToolsToolBar")
        tb.setMovable(False)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, tb)

        # Tool actions (exclusive toggle group)
        self._tool_group = QActionGroup(self)
        self._tool_group.setExclusive(True)

        self._paint_act = QAction("Paint", self)
        self._paint_act.setCheckable(True)
        self._paint_act.setChecked(True)
        self._paint_act.setShortcut(QKeySequence("1"))
        self._paint_act.setToolTip("Paint textures (1)")
        self._tool_group.addAction(self._paint_act)
        tb.addAction(self._paint_act)

        self._sculpt_act = QAction("Sculpt", self)
        self._sculpt_act.setCheckable(True)
        self._sculpt_act.setShortcut(QKeySequence("2"))
        self._sculpt_act.setToolTip("Sculpt heights (2)")
        self._tool_group.addAction(self._sculpt_act)
        tb.addAction(self._sculpt_act)

        self._select_act = QAction("Select", self)
        self._select_act.setCheckable(True)
        self._select_act.setShortcut(QKeySequence("3"))
        self._select_act.setToolTip("Select cells (3)")
        self._tool_group.addAction(self._select_act)
        tb.addAction(self._select_act)

        self._erase_act = QAction("Erase", self)
        self._erase_act.setCheckable(True)
        self._erase_act.setShortcut(QKeySequence("4"))
        self._erase_act.setToolTip("Erase cells (4)")
        self._tool_group.addAction(self._erase_act)
        tb.addAction(self._erase_act)

        self._tile_type_act = QAction("Tile Type", self)
        self._tile_type_act.setCheckable(True)
        self._tile_type_act.setShortcut(QKeySequence("5"))
        self._tile_type_act.setToolTip("Set tile type (5)")
        self._tool_group.addAction(self._tile_type_act)
        tb.addAction(self._tile_type_act)

        self._entity_act_tb = QAction("Entity", self)
        self._entity_act_tb.setCheckable(True)
        self._entity_act_tb.setShortcut(QKeySequence("6"))
        self._entity_act_tb.setToolTip("Place / edit entities (6)")
        self._tool_group.addAction(self._entity_act_tb)
        tb.addAction(self._entity_act_tb)

        self._light_act_tb = QAction("Light", self)
        self._light_act_tb.setCheckable(True)
        self._light_act_tb.setShortcut(QKeySequence("7"))
        self._light_act_tb.setToolTip("Paint light levels (7)")
        self._tool_group.addAction(self._light_act_tb)
        tb.addAction(self._light_act_tb)

        self._tool_group.triggered.connect(self._on_toolbar_tool)

        tb.addSeparator()

        # Undo / Redo
        undo_act = QAction("Undo", self)
        undo_act.setToolTip("Undo (Ctrl+Z)")
        undo_act.triggered.connect(self._bus.undo)
        tb.addAction(undo_act)

        redo_act = QAction("Redo", self)
        redo_act.setToolTip("Redo (Ctrl+Y)")
        redo_act.triggered.connect(self._bus.redo)
        tb.addAction(redo_act)

        tb.addSeparator()

        # Grid toggle
        grid_act = QAction("Grid", self)
        grid_act.setCheckable(True)
        grid_act.setChecked(True)
        grid_act.setToolTip("Toggle grid")
        grid_act.toggled.connect(self._toggle_grid)
        tb.addAction(grid_act)
        # Sync with View menu item
        self._toolbar_grid_act = grid_act

        wire_act = QAction("Wire", self)
        wire_act.setCheckable(True)
        wire_act.setChecked(False)
        wire_act.setToolTip("Toggle wireframe (Ctrl+5)")
        wire_act.toggled.connect(self._toggle_wireframe)
        tb.addAction(wire_act)
        self._toolbar_wire_act = wire_act

    def _on_toolbar_tool(self, action: QAction) -> None:
        if action == self._paint_act:
            self._switch_tool("paint")
        elif action == self._sculpt_act:
            self._switch_tool("sculpt")
        elif action == self._select_act:
            self._switch_tool("select")
        elif action == self._erase_act:
            self._switch_tool("erase")
        elif action == self._tile_type_act:
            self._switch_tool("tile_type")
        elif action == self._entity_act_tb:
            self._switch_tool("entity")
        elif action == self._light_act_tb:
            self._switch_tool("light")

    # ── Title bar ─────────────────────────────────────────────────

    def _update_title(self) -> None:
        dirty = " *" if self._dirty else ""
        self.setWindowTitle(f"Zone Editor — {self._zone_name}{dirty}")

    # ── Zone switching ────────────────────────────────────────────

    def _attach_zone(self, zone: Zone, name: str) -> None:
        """Wire a new zone into the editor, replacing the current one."""
        self._zone_name = name
        self._dirty = False

        # Update command bus
        self._bus = CommandBus(zone, self)
        self._bus.zone_changed.connect(self._on_zone_changed)

        # Update viewport
        self.viewport.zone = zone
        cam = self.viewport.camera
        cam.x = zone.width * 0.5
        cam.z = zone.height * 0.5
        cam.y = max(zone.width, zone.height) * 0.6
        cam.pitch = -0.75
        cam.yaw = 0.78
        self.viewport.rebuild_mesh()

        # Update tools
        cam = self.viewport.camera
        self._paint_tool = PaintTool(zone, self._bus, cam)
        self._sculpt_tool = SculptTool(zone, self._bus, cam)
        self._selection.clear()
        self._select_tool = SelectTool(zone, self._bus, cam, self._selection)
        self._erase_tool = EraseTool(zone, self._bus, cam)
        self._tile_type_tool = TileTypeTool(zone, self._bus, cam)
        self._entity_tool = EntityTool(zone, self._bus, cam)
        self._light_tool = LightTool(zone, self._bus, cam)
        self._paint_tool.on_changed = self._on_tool_changed
        self._sculpt_tool.on_changed = self._on_tool_changed
        self._select_tool.on_changed = self._on_tool_changed
        self._erase_tool.on_changed = self._on_tool_changed
        self._tile_type_tool.on_changed = self._on_tool_changed
        self._entity_tool.on_changed = self._on_tool_changed
        self._light_tool.on_changed = self._on_tool_changed

        # Update inspector panels with new tool refs
        self._paint_inspector.set_tool(self._paint_tool)
        self._sculpt_inspector._tool = self._sculpt_tool
        self._tile_type_inspector.set_tool(self._tile_type_tool)
        self._entity_inspector.set_tool(self._entity_tool)
        self._light_inspector.set_tool(self._light_tool)
        self._cell_inspector.set_zone(zone)
        self._minimap.set_zone(zone)

        # Update raycasters
        self._raycaster.update_zone(zone)
        self._mini_preview.update_zone(zone)

        # Re-activate current tool
        self._switch_tool(self._active_tool_name)

        self._update_title()

    def _switch_zone(self, name: str) -> None:
        """Load a zone by name and attach it."""
        if not self._guard_unsaved():
            return
        try:
            zone = load_zone(name)
        except Exception as exc:
            QMessageBox.warning(self, "Load Error", f"Failed to load '{name}':\n{exc}")
            return
        self._attach_zone(zone, name)
        push_recent(self._session, name)
        self._session["last_zone"] = name
        save_session(self._session)
        self._rebuild_recent_menu()

    # ── File menu actions ─────────────────────────────────────────

    def _on_new_zone(self) -> None:
        if not self._guard_unsaved():
            return
        dlg = NewZoneDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            w, h = dlg.zone_size()
            zone = _create_empty_zone(w, h)
            self._attach_zone(zone, "untitled")

    def _on_open_zone(self) -> None:
        if not self._guard_unsaved():
            return
        zones = list_zones()
        if not zones:
            QMessageBox.information(self, "Open Zone", "No .zone files found.")
            return
        dlg = OpenZoneDialog(zones, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            name = dlg.selected_zone()
            if name:
                self._switch_zone(name)

    def _on_save(self) -> None:
        if self._zone_name == "untitled" or not self._zone_name:
            self._on_save_as()
            return
        self._do_save(self._zone_name)

    def _on_save_as(self) -> None:
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "Save As", "Zone name:",
                                        text=self._zone_name)
        if not ok or not name.strip():
            return
        name = name.strip()
        self._do_save(name)

    def _do_save(self, name: str) -> None:
        zone = self._bus.zone
        zone.name = name
        self._zone_name = name

        from core.zones import GameRegistry
        registry = GameRegistry()
        path = ZONES_DIR / f"{name}.zone"
        try:
            zone.save_to_file(path, registry)
        except Exception as exc:
            QMessageBox.warning(self, "Save Error", f"Save failed:\n{exc}")
            return

        self._dirty = False
        push_recent(self._session, name)
        self._session["last_zone"] = name
        save_session(self._session)
        self._rebuild_recent_menu()
        self._update_title()
        self.statusBar().showMessage(f"Saved {name} ✓", 3000)

    # ── Unsaved changes guard ─────────────────────────────────────

    def _guard_unsaved(self) -> bool:
        """If there are unsaved changes, ask the user. Returns True to proceed."""
        if not self._dirty:
            return True
        result = QMessageBox.question(
            self, "Unsaved Changes",
            f"'{self._zone_name}' has unsaved changes.\n\nDo you want to save?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
        )
        if result == QMessageBox.StandardButton.Save:
            self._on_save()
            return True
        return result == QMessageBox.StandardButton.Discard

    def closeEvent(self, ev) -> None:
        if self._guard_unsaved():
            self._save_geometry()
            save_session(self._session)
            ev.accept()
        else:
            ev.ignore()

    def _save_geometry(self) -> None:
        """Persist window geometry to session."""
        import base64
        self._session["editor2_geometry"] = base64.b64encode(
            bytes(self.saveGeometry())).decode("ascii")
        self._session["editor2_state"] = base64.b64encode(
            bytes(self.saveState())).decode("ascii")

    def _restore_geometry(self) -> None:
        """Restore window geometry from session."""
        import base64
        from PySide6.QtCore import QByteArray
        geo = self._session.get("editor2_geometry")
        if geo:
            self.restoreGeometry(QByteArray(base64.b64decode(geo)))
        state = self._session.get("editor2_state")
        if state:
            self.restoreState(QByteArray(base64.b64decode(state)))

    # ── Signals ───────────────────────────────────────────────────

    def _on_zone_changed(self) -> None:
        self._dirty = True
        self._update_title()
        self.viewport.mark_mesh_dirty()
        self._refresh_inspector()
        # Push changes to raycaster(s)
        if self._view_mode == "2d":
            self._raycaster.update_zone(self._bus.zone)
        self._mini_preview.update_zone(self._bus.zone)

    def _on_tool_changed(self) -> None:
        self._refresh_inspector()
        self._update_status_bar()

    def _refresh_inspector(self) -> None:
        w = self._inspector_dock.widget()
        if hasattr(w, 'refresh'):
            w.refresh()

    def _update_status_bar(self) -> None:
        """Update status bar, cell inspector, and viewport HUD."""
        tool = self.viewport.tool
        hit = getattr(tool, 'hover_hit', None) if tool else None

        # Persistent status indicators
        snap_label = SNAP_LABELS[self._sculpt_tool.snap_idx]
        self._snap_label.setText(f"Snap: {snap_label}")
        tex = self._paint_tool.current_texture or '—'
        self._tex_label.setText(f"Tex: {tex}")

        if hit is None:
            self._cell_label.setText("Cell: —")
            self._height_label.setText("Heights: —")
            self._cell_inspector.update_cell(None, None)
            self._build_hud(None)
            return

        zone = self._bus.zone
        r, c = hit.row, hit.col
        fh = zone.floor_heights[r][c] if zone.floor_heights else 0.0
        ch = zone.ceil_heights[r][c] if zone.ceil_heights else 10.0
        self._cell_label.setText(
            f"Cell: ({c}, {r})  |  {hit.part}.{hit.face.name}")
        self._height_label.setText(
            f"Floor: {fh:.2f}  Ceil: {ch:.2f}")
        self._cell_inspector.update_cell(r, c)
        self._build_hud(hit)

    # ── Viewport HUD ──────────────────────────────────────────────

    _HUD_TITLE = (255, 200, 80)
    _HUD_VALUE = (120, 220, 255)
    _HUD_TEXT  = (220, 220, 200)

    def _build_hud(self, hit) -> None:
        """Build HUD overlay lines for the viewport."""
        lines: list[tuple[str, tuple[int, int, int]]] = []

        # Tool line
        tool_name = self._active_tool_name.replace("_", " ").title()
        lines.append((f"Tool: {tool_name}", self._HUD_TITLE))

        # Snap (sculpt only)
        if self._active_tool_name == "sculpt":
            snap_label = SNAP_LABELS[self._sculpt_tool.snap_idx]
            lines.append((f"Snap: {snap_label}", self._HUD_VALUE))

        # Current texture (paint only)
        if self._active_tool_name == "paint":
            tex = self._paint_tool.current_texture or '—'
            lines.append((f"Texture: {tex}", self._HUD_VALUE))

        # Entity type (entity tool only)
        if self._active_tool_name == "entity":
            etype = self._entity_tool.current_type or '—'
            lines.append((f"Entity: {etype}", self._HUD_VALUE))
            if self._entity_tool.selected_uid is not None:
                lines.append((f"Selected UID: {self._entity_tool.selected_uid}",
                              self._HUD_VALUE))

        # Light step (light tool only)
        if self._active_tool_name == "light":
            lines.append((f"Light step: {self._light_tool.step}",
                          self._HUD_VALUE))

        # Selection count
        if self._selection.has_cells():
            n = len(self._selection.cells)
            mode = "Ceil" if self._selection.ceiling_mode else "Floor"
            lines.append((f"Selection: {n} cells ({mode})", self._HUD_VALUE))

        # Cell info
        if hit is not None:
            zone = self._bus.zone
            r, c = hit.row, hit.col
            fh = zone.floor_heights[r][c] if zone.floor_heights else 0.0
            ch = zone.ceil_heights[r][c] if zone.ceil_heights else 10.0
            ll = zone.light_levels[r][c] if zone.light_levels else 1.0
            tile = zone.tiles[r][c]
            lines.append(("", (0, 0, 0)))  # blank separator
            lines.append((f"Cell: ({c}, {r})  {tile}", self._HUD_TEXT))
            lines.append((f"Floor: {fh:.2f}  Ceil: {ch:.2f}  Light: {ll:.2f}",
                          self._HUD_TEXT))
            lines.append((f"Face: {hit.part}.{hit.face.name}", self._HUD_TEXT))

        self.viewport.hud_lines = lines

    # ── Tool switching ────────────────────────────────────────────

    def _switch_tool(self, name: str) -> None:
        self._active_tool_name = name
        tool_map = {
            "paint":     (self._paint_tool, self._paint_inspector, self._paint_act),
            "sculpt":    (self._sculpt_tool, self._sculpt_inspector, self._sculpt_act),
            "select":    (self._select_tool, self._select_inspector, self._select_act),
            "erase":     (self._erase_tool, self._erase_inspector, self._erase_act),
            "tile_type": (self._tile_type_tool, self._tile_type_inspector, self._tile_type_act),
            "entity":    (self._entity_tool, self._entity_inspector, self._entity_act_tb),
            "light":     (self._light_tool, self._light_inspector, self._light_act_tb),
        }
        tool, panel, act = tool_map.get(name, tool_map["paint"])
        self.viewport.tool = tool
        if panel is not None:
            self._inspector_dock.setWidget(panel)
        self._inspector_dock.setWindowTitle(name.replace("_", " ").title())
        act.setChecked(True)
        self.statusBar().showMessage(f"Tool: {name.replace('_', ' ').title()}", 2000)
        self.viewport.update()

    # ── View actions ──────────────────────────────────────────────

    def _toggle_grid(self, on: bool) -> None:
        self.viewport.show_grid = on
        # Keep menu and toolbar in sync
        self._grid_act.blockSignals(True)
        self._grid_act.setChecked(on)
        self._grid_act.blockSignals(False)
        self._toolbar_grid_act.blockSignals(True)
        self._toolbar_grid_act.setChecked(on)
        self._toolbar_grid_act.blockSignals(False)
        self.viewport.update()

    def _toggle_wireframe(self, on: bool) -> None:
        self.viewport.wireframe = on
        self._wire_act.blockSignals(True)
        self._wire_act.setChecked(on)
        self._wire_act.blockSignals(False)
        self._toolbar_wire_act.blockSignals(True)
        self._toolbar_wire_act.setChecked(on)
        self._toolbar_wire_act.blockSignals(False)
        self.viewport.update()

    def _reset_camera(self) -> None:
        zone = self._bus.zone
        cam = self.viewport.camera
        cam.x = zone.width * 0.5
        cam.z = zone.height * 0.5
        cam.y = max(zone.width, zone.height) * 0.6
        cam.pitch = -0.75
        cam.yaw = 0.78
        self.viewport.update()

    def _toggle_layer_vis(self, layer: str, on: bool) -> None:
        """Toggle visibility of walls/floors/ceilings."""
        self.viewport.set_layer_vis(layer, on)

    def _toggle_entity_vis(self, on: bool) -> None:
        """Toggle entity marker visibility."""
        self._show_entities = on
        self.viewport.update()

    def _toggle_view_mode(self) -> None:
        """Toggle between 3D editor and 2.5D raycaster (fullscreen swap)."""
        if self._view_mode == "3d":
            # Switch to 2.5D raycaster
            self._raycaster.set_enabled(True)      # creates renderer if needed
            self._raycaster.update_zone(self._bus.zone)  # push latest zone
            self._raycaster.sync_from_editor_camera(self.viewport.camera)
            self._central_stack.setCurrentIndex(1)
            self._raycaster.setFocus()
            self._view_mode = "2d"
            # Dock: show minimap while in fullscreen 2.5D
            self._minimap_stack.setCurrentIndex(1)
            self._minimap_dock.setWindowTitle("Minimap")
            self.statusBar().showMessage("2.5D Preview — Tab to return", 2000)
        else:
            # Switch back to 3D editor
            self._raycaster.sync_to_editor_camera(self.viewport.camera)
            self._raycaster.set_enabled(False)
            self._central_stack.setCurrentIndex(0)
            self.viewport.setFocus()
            self._view_mode = "3d"
            # Dock: show live 2.5D preview while in 3D editor
            self._minimap_stack.setCurrentIndex(0)
            self._minimap_dock.setWindowTitle("Preview")
            self.statusBar().showMessage("3D Editor", 1500)

    def _update_minimap(self) -> None:
        """Periodic refresh — minimap camera + live 2.5D mini-preview."""
        if self._view_mode == "2d":
            # In fullscreen 2.5D mode: track raycaster position on minimap
            rc = self._raycaster
            self._minimap.set_camera(rc.px, rc.py, rc.angle - math.pi * 0.5)
        else:
            cam = self.viewport.camera
            self._minimap.set_camera(cam.x, cam.z, cam.yaw)
            # Sync mini-preview if visible
            if self._minimap_stack.currentIndex() == 0:
                self._mini_preview.ensure_ready()
                self._mini_preview.sync_camera(cam)
        self._minimap.set_selection(self._selection.cells)

    # ── Zone menu actions ─────────────────────────────────────────

    def _on_resize_zone(self) -> None:
        zone = self._bus.zone
        dlg = ResizeZoneDialog(zone.width, zone.height, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            nw, nh = dlg.zone_size()
            if nw == zone.width and nh == zone.height:
                return
            self._resize_zone(nw, nh)

    def _resize_zone(self, nw: int, nh: int) -> None:
        """Resize the current zone, preserving existing cell data."""
        zone = self._bus.zone
        ow, oh = zone.width, zone.height

        def _resize_grid(grid, default):
            """Resize a 2D grid, keeping existing data where it overlaps."""
            new = [[default] * nw for _ in range(nh)]
            for r in range(min(oh, nh)):
                for c in range(min(ow, nw)):
                    new[r][c] = grid[r][c]
            return new

        def _resize_4face(grid, default=""):
            new = [[[default] * 4 for _ in range(nw)] for _ in range(nh)]
            for r in range(min(oh, nh)):
                for c in range(min(ow, nw)):
                    new[r][c] = list(grid[r][c])
            return new

        def _resize_4seg(grid):
            new = [[[[], [], [], []] for _ in range(nw)] for _ in range(nh)]
            for r in range(min(oh, nh)):
                for c in range(min(ow, nw)):
                    new[r][c] = [list(s) for s in grid[r][c]]
            return new

        zone.width = nw
        zone.height = nh
        zone.tiles = _resize_grid(zone.tiles, "grass")
        zone.floor_heights = _resize_grid(zone.floor_heights, 0.0)
        zone.ceil_heights = _resize_grid(zone.ceil_heights, 10.0)
        zone.floor_textures = _resize_grid(zone.floor_textures, "")
        zone.ceil_textures = _resize_grid(zone.ceil_textures, "")
        zone.wall_textures = _resize_grid(zone.wall_textures, "")
        zone.light_levels = _resize_grid(zone.light_levels, 1.0)
        zone.rotations = _resize_grid(zone.rotations, 0)
        zone.face_textures = _resize_4face(zone.face_textures)
        zone.wall_segments = _resize_4seg(zone.wall_segments)
        zone.floor_step_textures = _resize_4face(zone.floor_step_textures)
        zone.ceil_step_textures = _resize_4face(zone.ceil_step_textures)
        zone.floor_step_segments = _resize_4seg(zone.floor_step_segments)
        zone.ceil_step_segments = _resize_4seg(zone.ceil_step_segments)
        zone.upper_wall_height = _resize_grid(
            zone.upper_wall_height if zone.upper_wall_height else
            [[0.0] * ow for _ in range(oh)], 0.0)

        self._dirty = True
        self._update_title()
        self.viewport.rebuild_mesh()
        self.statusBar().showMessage(
            f"Resized {ow}×{oh} → {nw}×{nh}", 3000)

    def _on_zone_info(self) -> None:
        zone = self._bus.zone
        wall_count = sum(
            1 for r in range(zone.height) for c in range(zone.width)
            if tile_def(zone.tiles[r][c]) and tile_def(zone.tiles[r][c]).wall
        )
        info = (
            f"Name: {self._zone_name}\n"
            f"Size: {zone.width} × {zone.height}\n"
            f"Cells: {zone.width * zone.height}\n"
            f"Walls: {wall_count}\n"
            f"Entities: {len(zone.entities)}"
        )
        QMessageBox.information(self, "Zone Info", info)

    def _on_zone_settings(self) -> None:
        zone = self._bus.zone
        dlg = ZoneSettingsDialog(zone, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            vals = dlg.values()
            zone.first_person = vals["first_person"]
            zone.skybox = vals["skybox"]
            zone.sky_color = vals["sky_color"]
            zone.anchor = vals["anchor"]
            self._dirty = True
            self._update_title()
            self.statusBar().showMessage("Zone settings updated", 2000)

    def _on_duplicate_zone(self) -> None:
        """Deep-copy the current zone, prompt for a name, and save it."""
        import copy
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(
            self, "Duplicate Zone", "New zone name:",
            text=f"{self._zone_name}_copy")
        if not ok or not name.strip():
            return
        name = name.strip()
        zone = self._bus.zone
        dup = copy.deepcopy(zone)
        dup.name = name

        from core.zones import GameRegistry
        registry = GameRegistry()
        path = ZONES_DIR / f"{name}.zone"
        try:
            dup.save_to_file(path, registry)
        except Exception as exc:
            QMessageBox.warning(self, "Duplicate Error",
                                f"Failed to save duplicate:\n{exc}")
            return
        self.statusBar().showMessage(f"Duplicated → {name} ✓", 3000)

    def _on_validate_zone(self) -> None:
        """Run zone validation and show results in a dialog."""
        from core.zones.validation import validate_zone
        from core.entity_defs import entity_registry
        zone = self._bus.zone
        issues = validate_zone(zone, entity_registry=entity_registry())
        if not issues:
            QMessageBox.information(self, "Validate Zone",
                                    "No issues found ✓")
            return
        errors = [i for i in issues if i.severity == "error"]
        warnings = [i for i in issues if i.severity == "warning"]
        lines = []
        if errors:
            lines.append(f"=== {len(errors)} Error(s) ===")
            for i in errors:
                loc = f" [{i.location}]" if i.location else ""
                lines.append(f"  ✗ {i.message}{loc}")
        if warnings:
            lines.append(f"\n=== {len(warnings)} Warning(s) ===")
            for i in warnings:
                loc = f" [{i.location}]" if i.location else ""
                lines.append(f"  ⚠ {i.message}{loc}")
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Validate Zone — {len(issues)} issue(s)")
        dlg.resize(520, 400)
        layout = QVBoxLayout(dlg)
        text = QPlainTextEdit()
        text.setPlainText("\n".join(lines))
        text.setReadOnly(True)
        text.setFont(QFont("Consolas", 10))
        layout.addWidget(text)
        from PySide6.QtWidgets import QDialogButtonBox
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)
        dlg.exec()

    def _on_export_topdown(self) -> None:
        """Export a top-down tile-colour image of the zone."""
        from PIL import Image
        zone = self._bus.zone
        w, h = zone.width, zone.height
        scale = 8  # pixels per cell
        img = Image.new("RGB", (w * scale, h * scale), (30, 30, 30))

        for r in range(h):
            for c in range(w):
                td = tile_def(zone.tiles[r][c])
                if td:
                    color = td.color if hasattr(td, 'color') and td.color else (80, 80, 80)
                else:
                    color = (80, 80, 80)
                ll = zone.light_levels[r][c] if zone.light_levels else 1.0
                rc = tuple(max(0, min(255, int(ch * ll))) for ch in color)
                for py in range(scale):
                    for px in range(scale):
                        img.putpixel((c * scale + px, r * scale + py), rc)

        # Mark entities with red crosses
        for ent in zone.entities:
            ex, ey = int(ent.x * scale), int(ent.y * scale)
            for d in range(-2, 3):
                for xy in [(ex + d, ey), (ex, ey + d)]:
                    if 0 <= xy[0] < w * scale and 0 <= xy[1] < h * scale:
                        img.putpixel(xy, (255, 50, 50))

        # Mark anchor with green circle
        if zone.anchor:
            ar, ac = zone.anchor
            ax, ay = int(ac * scale), int(ar * scale)
            for d in range(-3, 4):
                for xy in [(ax + d, ay), (ax, ay + d)]:
                    if 0 <= xy[0] < w * scale and 0 <= xy[1] < h * scale:
                        img.putpixel(xy, (50, 255, 50))

        out_dir = Path("debug_renders")
        out_dir.mkdir(exist_ok=True)
        out_path = out_dir / f"{self._zone_name}_topdown.png"
        img.save(str(out_path))
        self.statusBar().showMessage(f"Exported → {out_path}", 4000)

    # ── Find / Replace Texture ────────────────────────────────────

    def _on_find_replace(self) -> None:
        dlg = FindReplaceDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        find_tex, replace_tex = dlg.values()
        if not find_tex or not replace_tex:
            return
        count = self._do_find_replace(find_tex, replace_tex)
        self.statusBar().showMessage(
            f"Replaced {count} occurrence(s) of '{find_tex}' → '{replace_tex}'",
            4000)

    def _do_find_replace(self, find: str, replace: str) -> int:
        """Replace all occurrences of a texture name across all zone grids."""
        zone = self._bus.zone
        from editor2.core import BatchCmd, SetCellFieldCmd, SetFaceFieldCmd
        cmds: list = []
        for r in range(zone.height):
            for c in range(zone.width):
                if zone.tiles[r][c] == find:
                    cmds.append(SetCellFieldCmd(r, c, "tiles", replace))
                if zone.floor_textures and zone.floor_textures[r][c] == find:
                    cmds.append(SetCellFieldCmd(r, c, "floor_textures", replace))
                if zone.ceil_textures and zone.ceil_textures[r][c] == find:
                    cmds.append(SetCellFieldCmd(r, c, "ceil_textures", replace))
                if zone.wall_textures and zone.wall_textures[r][c] == find:
                    cmds.append(SetCellFieldCmd(r, c, "wall_textures", replace))
                if zone.face_textures and zone.face_textures[r][c]:
                    for i in range(4):
                        if zone.face_textures[r][c][i] == find:
                            cmds.append(SetFaceFieldCmd(r, c, i, "face_textures", replace))
        if cmds:
            self._bus.execute(BatchCmd(cmds, f"Replace '{find}' → '{replace}'"))
        return len(cmds)

    # ── Help window ───────────────────────────────────────────────

    def _show_help(self) -> None:
        dlg = HelpDialog(self)
        dlg.exec()

    # ── Debug / Profiling ─────────────────────────────────────────

    def _toggle_perf(self, on: bool) -> None:
        self.viewport.show_perf = on
        if on:
            self._perf_timer.start(500)  # update twice per second
            self._perf_label.show()
        else:
            self._perf_timer.stop()
            self._perf_label.hide()

    def _update_perf(self) -> None:
        vp = self.viewport
        fps = vp.fps
        frame = vp.avg_frame_ms
        rebuild = vp.last_rebuild_ms
        self._perf_label.setText(
            f"FPS: {fps:.0f}  |  frame: {frame:.1f} ms  |  "
            f"rebuild: {rebuild:.1f} ms  |  "
            f"tris: {vp._vertex_count // 3:,}")

    @staticmethod
    def _set_log_level(level_name: str) -> None:
        level = getattr(logging, level_name)
        logging.getLogger("editor2").setLevel(level)
        log.info("Log level set to %s", level_name)

    def _dump_stats(self) -> None:
        vp = self.viewport
        zone = self._bus.zone
        lines = [
            f"Zone: {self._zone_name} ({zone.width}×{zone.height})",
            f"Vertices: {vp._vertex_count:,}  Triangles: {vp._vertex_count // 3:,}",
            f"Avg frame: {vp.avg_frame_ms:.2f} ms  ({vp.fps:.0f} FPS)",
            f"Last rebuild: {vp.last_rebuild_ms:.2f} ms",
            f"Undo stack: {len(self._bus._undo_stack)}",
            f"Redo stack: {len(self._bus._redo_stack)}",
            f"Camera: ({vp.camera.x:.1f}, {vp.camera.y:.1f}, {vp.camera.z:.1f})",
            f"  yaw={vp.camera.yaw:.1f}°  pitch={vp.camera.pitch:.1f}°",
        ]
        text = "\n".join(lines)
        log.info("Stats dump:\n%s", text)
        QMessageBox.information(self, "Editor Stats", text)

    def keyPressEvent(self, ev) -> None:
        key = ev.key()
        mods = ev.modifiers()
        is_sculpt = self._active_tool_name == "sculpt"
        is_select = self._active_tool_name == "select"
        is_entity = self._active_tool_name == "entity"
        is_light = self._active_tool_name == "light"

        # ── Global shortcuts ──
        if key == Qt.Key.Key_Escape:
            if self._selection.has_cells():
                self._selection.clear()
                self._update_select_inspector()
                self.viewport.update()
                self.statusBar().showMessage("Selection cleared", 1500)
                return
            if self._selection.rect_in_progress:
                self._selection.cancel_rect()
                self.viewport.update()
                return

        if key == Qt.Key.Key_A and mods & Qt.KeyboardModifier.ControlModifier:
            zone = self._bus.zone
            self._selection.select_all(zone.width, zone.height)
            self._update_select_inspector()
            self.viewport.update()
            self.statusBar().showMessage("Selected all cells", 1500)
            return

        # Copy / Paste
        if key == Qt.Key.Key_C and mods & Qt.KeyboardModifier.ControlModifier:
            self._copy_selection()
            return
        if key == Qt.Key.Key_V and mods & Qt.KeyboardModifier.ControlModifier:
            self._paste_clipboard()
            return

        # Camera bookmarks: Shift+1..9 save, Alt+1..9 recall
        if (mods & Qt.KeyboardModifier.ShiftModifier
                and Qt.Key.Key_1 <= key <= Qt.Key.Key_9
                and not (mods & Qt.KeyboardModifier.ControlModifier)):
            idx = key - Qt.Key.Key_1
            cam = self.viewport.camera
            self._cam_bookmarks[idx] = (cam.x, cam.y, cam.z,
                                        cam.yaw, cam.pitch)
            self.statusBar().showMessage(f"Bookmark {idx + 1} saved", 1500)
            return

        if (mods & Qt.KeyboardModifier.AltModifier
                and Qt.Key.Key_1 <= key <= Qt.Key.Key_9
                and not (mods & Qt.KeyboardModifier.ControlModifier)):
            self._recall_bookmark(key - Qt.Key.Key_1)
            return

        # ── G key: always cycle snap grid ──
        if key == Qt.Key.Key_G:
            if mods & Qt.KeyboardModifier.ShiftModifier:
                # Shift+G toggles visual grid
                self._toggle_grid(not self.viewport.show_grid)
            else:
                self._sculpt_tool.cycle_snap()
                snap_label = SNAP_LABELS[self._sculpt_tool.snap_idx]
                self.statusBar().showMessage(f"Snap: {snap_label}", 1500)
            return

        # ── Select tool shortcuts ──
        if is_select:
            if key == Qt.Key.Key_X:
                self._selection.toggle_ceiling_mode()
                self._update_select_inspector()
                mode = "Ceiling" if self._selection.ceiling_mode else "Floor"
                self.statusBar().showMessage(f"Selection mode: {mode}", 1500)
                return
            if key == Qt.Key.Key_Delete:
                n = self._select_tool.reset_cells()
                self.statusBar().showMessage(
                    f"Reset {len(self._selection.cells)} cell(s)", 1500)
                return
            if key == Qt.Key.Key_H:
                if mods & Qt.KeyboardModifier.ShiftModifier:
                    self._select_tool.make_open()
                else:
                    self._select_tool.make_wall()
                return

        # ── Sculpt cell shortcuts ──
        if is_sculpt:
            if key == Qt.Key.Key_H:
                if mods & Qt.KeyboardModifier.ShiftModifier:
                    self._sculpt_tool.make_open()
                    self.statusBar().showMessage("Cell → Open", 1500)
                else:
                    self._sculpt_tool.make_wall()
                    self.statusBar().showMessage("Cell → Wall", 1500)
                return
            if key == Qt.Key.Key_T:
                self._sculpt_tool.toggle_ceiling()
                self.statusBar().showMessage("Ceiling toggled", 1500)
                return
            if key == Qt.Key.Key_R:
                self._sculpt_tool.reset_height()
                self.statusBar().showMessage("Height reset", 1500)
                return
            if key == Qt.Key.Key_U:
                if mods & Qt.KeyboardModifier.ControlModifier:
                    self._sculpt_tool.adjust_upper_wall_height("reset")
                    self.statusBar().showMessage("Upper wall reset", 1500)
                elif mods & Qt.KeyboardModifier.ShiftModifier:
                    self._sculpt_tool.adjust_upper_wall_height("lower")
                    self.statusBar().showMessage("Upper wall lowered", 1500)
                else:
                    self._sculpt_tool.adjust_upper_wall_height("raise")
                    self.statusBar().showMessage("Upper wall raised", 1500)
                return
            if key == Qt.Key.Key_Delete:
                self._sculpt_tool.clear_cell()
                self.statusBar().showMessage("Cell cleared", 1500)
                return

        # ── Entity tool shortcuts ──
        if is_entity:
            if key == Qt.Key.Key_R:
                self._entity_tool.rotate_selected()
                self.statusBar().showMessage("Entity rotated 90°", 1500)
                return
            if key == Qt.Key.Key_M:
                self._entity_tool.move_selected_to_hover()
                self.statusBar().showMessage("Entity moved", 1500)
                return
            if key == Qt.Key.Key_Delete:
                self._entity_tool.delete_selected()
                self.statusBar().showMessage("Entity deleted", 1500)
                return

        # ── Light tool shortcuts ──
        if is_light:
            if key == Qt.Key.Key_BracketLeft:
                self._light_tool.cycle_step(-1)
                self.statusBar().showMessage(
                    f"Light step: {self._light_tool.step}", 1500)
                return
            if key == Qt.Key.Key_BracketRight:
                self._light_tool.cycle_step(1)
                self.statusBar().showMessage(
                    f"Light step: {self._light_tool.step}", 1500)
                return

        self.viewport.keyPressEvent(ev)

    # ── Selection batch helpers (button wiring) ───────────────────

    def _sel_fill(self) -> None:
        tex = self._select_inspector.selected_texture
        if not tex:
            tex = self._paint_tool.current_texture
        n = self._select_tool.fill_texture(tex)
        self.statusBar().showMessage(
            f"Filled {len(self._selection.cells)} cell(s) with '{tex}'", 2000)

    def _sel_clear_tex(self) -> None:
        self._select_tool.clear_textures()
        self.statusBar().showMessage("Textures cleared", 1500)

    def _sel_reset(self) -> None:
        self._select_tool.reset_cells()
        self.statusBar().showMessage("Cells reset", 1500)

    def _sel_flatten(self) -> None:
        self._select_tool.flatten()
        mode = "ceiling" if self._selection.ceiling_mode else "floor"
        self.statusBar().showMessage(f"Flattened {mode} heights", 1500)

    def _sel_toggle_ceiling(self) -> None:
        """Toggle ceiling on/off for all selected cells."""
        sel = self._selection
        if not sel.has_cells():
            return
        zone = self._bus.zone
        from editor2.core import BatchCmd, SetCellFieldCmd
        cmds: list = []
        for r, c in sel.iter_cells():
            ch = zone.ceil_heights[r][c] if zone.ceil_heights else 10.0
            fh = zone.floor_heights[r][c] if zone.floor_heights else 0.0
            if ch >= 10.0:
                # Sky → close at fh + 1.0
                cmds.append(SetCellFieldCmd(r, c, "ceil_heights", fh + 1.0))
            else:
                # Closed → sky
                cmds.append(SetCellFieldCmd(r, c, "ceil_heights", 10.0))
        if cmds:
            self._bus.execute(BatchCmd(cmds, "Toggle ceiling"))
        self.statusBar().showMessage(
            f"Toggled ceiling on {len(cmds)} cell(s)", 1500)

    def _update_select_inspector(self) -> None:
        self._select_inspector.update_info(
            len(self._selection.cells), self._selection.ceiling_mode)

    def _get_selection_overlays(self) -> list:
        """Return selection + entity overlays when not drawn by the active tool."""
        ovls: list = []
        # Selection overlays (select tool draws its own)
        if self._active_tool_name != "select" and self._selection.has_cells():
            ovls.extend(self._select_tool.overlays())
        # Entity overlays (entity tool draws its own)
        if self._show_entities and self._active_tool_name != "entity":
            ovls.extend(self._build_entity_overlays())
        return ovls

    def _build_entity_overlays(self) -> list:
        """Build diamond-marker overlays for all entities (passive view)."""
        from editor2.tools import Overlay, OverlayMode
        from core.entity_defs import get_entity_def
        zone = self._bus.zone
        ovls: list = []
        for ent in zone.entities:
            edef = get_entity_def(ent.type)
            if edef:
                r, g, b = edef.color
                cr, cg, cb = r / 255, g / 255, b / 255
            else:
                cr, cg, cb = 0.8, 0.8, 0.8
            ex, ey = ent.x, ent.y
            row, col = int(ey), int(ex)
            fh = 0.0
            if 0 <= row < zone.height and 0 <= col < zone.width:
                fh = zone.floor_heights[row][col] if zone.floor_heights else 0.0
            y = fh + 0.02
            s = 0.3
            verts = [
                (ex, y, ey - s), (ex + s, y, ey),
                (ex, y, ey + s), (ex - s, y, ey),
            ]
            ovls.append(Overlay(
                mode=OverlayMode.TRIS,
                verts=[verts[0], verts[1], verts[2],
                       verts[0], verts[2], verts[3]],
                color=(cr, cg, cb, 0.35),
            ))
            # Direction line
            dx = math.cos(ent.angle) * 0.5
            dy = math.sin(ent.angle) * 0.5
            ovls.append(Overlay(
                mode=OverlayMode.LINES,
                verts=[(ex, y + 0.01, ey), (ex + dx, y + 0.01, ey + dy)],
                color=(1.0, 1.0, 0.0, 0.4),
            ))
        return ovls

    # ── Clipboard (copy / paste) ──────────────────────────────────

    def _copy_selection(self) -> None:
        if not self._selection.has_cells():
            self.statusBar().showMessage("Nothing to copy", 1500)
            return
        zone = self._bus.zone
        bounds = self._selection.bounds()
        if not bounds:
            return
        rmin, cmin, _, _ = bounds
        self._clipboard_origin = (rmin, cmin)
        self._clipboard = []
        for r, c in self._selection.iter_cells():
            cell = {
                "dr": r - rmin, "dc": c - cmin,
                "tile": zone.tiles[r][c],
                "fh": zone.floor_heights[r][c] if zone.floor_heights else 0.0,
                "ch": zone.ceil_heights[r][c] if zone.ceil_heights else 10.0,
                "ft": zone.floor_textures[r][c] if zone.floor_textures else "",
                "ct": zone.ceil_textures[r][c] if zone.ceil_textures else "",
                "wt": zone.wall_textures[r][c] if zone.wall_textures else "",
                "face_tex": list(zone.face_textures[r][c]) if zone.face_textures else [""] * 4,
            }
            self._clipboard.append(cell)
        self.statusBar().showMessage(
            f"Copied {len(self._clipboard)} cell(s)", 1500)

    def _paste_clipboard(self) -> None:
        if not self._clipboard:
            self.statusBar().showMessage("Clipboard empty", 1500)
            return
        # Paste at the hovered cell, or at the original position
        tool = self.viewport.tool
        hit = getattr(tool, 'hover_hit', None) if tool else None
        if hit is not None:
            base_r, base_c = hit.row, hit.col
        else:
            base_r, base_c = self._clipboard_origin

        zone = self._bus.zone
        from editor2.core import BatchCmd, SetCellFieldCmd, SetFaceFieldCmd
        cmds: list = []
        count = 0
        for cell in self._clipboard:
            r = base_r + cell["dr"]
            c = base_c + cell["dc"]
            if not (0 <= r < zone.height and 0 <= c < zone.width):
                continue
            count += 1
            cmds.append(SetCellFieldCmd(r, c, "tiles", cell["tile"]))
            cmds.append(SetCellFieldCmd(r, c, "floor_heights", cell["fh"]))
            cmds.append(SetCellFieldCmd(r, c, "ceil_heights", cell["ch"]))
            if zone.floor_textures:
                cmds.append(SetCellFieldCmd(r, c, "floor_textures", cell["ft"]))
            if zone.ceil_textures:
                cmds.append(SetCellFieldCmd(r, c, "ceil_textures", cell["ct"]))
            if zone.wall_textures:
                cmds.append(SetCellFieldCmd(r, c, "wall_textures", cell["wt"]))
            if zone.face_textures:
                for fi in range(4):
                    cmds.append(SetFaceFieldCmd(r, c, fi, "face_textures",
                                                cell["face_tex"][fi]))
        if cmds:
            self._bus.execute(BatchCmd(cmds, f"Paste {count} cells"))
        self.statusBar().showMessage(f"Pasted {count} cell(s)", 1500)

    # ── Camera bookmarks ──────────────────────────────────────────

    def _recall_bookmark(self, idx: int) -> None:
        bm = self._cam_bookmarks.get(idx)
        if bm is None:
            self.statusBar().showMessage(f"No bookmark {idx + 1}", 1500)
            return
        cam = self.viewport.camera
        cam.x, cam.y, cam.z, cam.yaw, cam.pitch = bm
        self.viewport.update()
        self.statusBar().showMessage(f"Bookmark {idx + 1} recalled", 1500)

    # ── Viewport scroll callback ──────────────────────────────────

    def _on_viewport_scroll(self, direction: int) -> bool:
        """Called by viewport wheelEvent. Return True to consume scroll."""
        if self._selection.has_cells():
            snap = SNAP_PRESETS[self._sculpt_tool.snap_idx]
            self._select_tool.raise_lower(direction, snap)
            return True
        return False

    def _on_eyedrop(self, sx: float, sy: float,
                    vp_w: int, vp_h: int) -> None:
        """Global middle-click eyedropper — pick texture from any face."""
        from editor2.picking import pick_cell, Face
        hit = pick_cell(sx, sy, vp_w, vp_h,
                        self.viewport.camera, self._bus.zone)
        if hit is None:
            return
        zone = self._bus.zone
        r, c = hit.row, hit.col
        tex = ""
        if hit.face == Face.TOP:
            tex = (zone.floor_textures[r][c] if zone.floor_textures else "")
        elif hit.face == Face.BOTTOM:
            tex = (zone.ceil_textures[r][c] if zone.ceil_textures else "")
        elif hit.face in (Face.NORTH, Face.SOUTH, Face.EAST, Face.WEST):
            fi = {Face.NORTH: 0, Face.SOUTH: 1, Face.WEST: 2, Face.EAST: 3}[hit.face]
            if zone.face_textures and zone.face_textures[r][c][fi]:
                tex = zone.face_textures[r][c][fi]
            elif zone.wall_textures:
                tex = zone.wall_textures[r][c]
        if tex:
            self._paint_tool.current_texture = tex
            self.statusBar().showMessage(f"Picked: {tex}", 1500)


# ── Dialogs ──────────────────────────────────────────────────────


class NewZoneDialog(QDialog):
    """Simple dialog to pick width × height for a new zone."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New Zone")
        layout = QFormLayout(self)

        self._w_spin = QSpinBox()
        self._w_spin.setRange(4, 128)
        self._w_spin.setValue(20)
        layout.addRow("Width:", self._w_spin)

        self._h_spin = QSpinBox()
        self._h_spin.setRange(4, 128)
        self._h_spin.setValue(20)
        layout.addRow("Height:", self._h_spin)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def zone_size(self) -> tuple[int, int]:
        return self._w_spin.value(), self._h_spin.value()


class OpenZoneDialog(QDialog):
    """Dialog listing all available .zone files to pick from."""

    def __init__(self, zones: list[str], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Open Zone")
        self.resize(300, 400)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Select a zone to open:"))

        from PySide6.QtWidgets import QListWidget, QListWidgetItem
        self._list = QListWidget()
        for name in zones:
            self._list.addItem(QListWidgetItem(name))
        self._list.itemDoubleClicked.connect(self.accept)
        layout.addWidget(self._list)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Open
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_zone(self) -> str | None:
        item = self._list.currentItem()
        return item.text() if item else None


class ResizeZoneDialog(QDialog):
    """Dialog to resize the current zone."""

    def __init__(self, cur_w: int, cur_h: int, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Resize Zone")
        layout = QFormLayout(self)

        layout.addRow(QLabel(f"Current size: {cur_w} × {cur_h}"))

        self._w_spin = QSpinBox()
        self._w_spin.setRange(4, 128)
        self._w_spin.setValue(cur_w)
        layout.addRow("New Width:", self._w_spin)

        self._h_spin = QSpinBox()
        self._h_spin.setRange(4, 128)
        self._h_spin.setValue(cur_h)
        layout.addRow("New Height:", self._h_spin)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def zone_size(self) -> tuple[int, int]:
        return self._w_spin.value(), self._h_spin.value()


class FindReplaceDialog(QDialog):
    """Dialog with two text inputs to find and replace texture names."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Find / Replace Texture")
        layout = QFormLayout(self)

        self._find_edit = QLineEdit()
        self._find_edit.setPlaceholderText("e.g. grass")
        layout.addRow("Find:", self._find_edit)

        self._replace_edit = QLineEdit()
        self._replace_edit.setPlaceholderText("e.g. dirt")
        layout.addRow("Replace:", self._replace_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def values(self) -> tuple[str, str]:
        return self._find_edit.text().strip(), self._replace_edit.text().strip()


class ZoneSettingsDialog(QDialog):
    """Edit zone-level settings: first_person, skybox, sky_color, anchor."""

    def __init__(self, zone: Zone, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Zone Settings")
        layout = QFormLayout(self)

        from PySide6.QtWidgets import QCheckBox, QDoubleSpinBox

        self._fp_check = QCheckBox()
        self._fp_check.setChecked(zone.first_person)
        layout.addRow("First Person:", self._fp_check)

        self._skybox_edit = QLineEdit()
        self._skybox_edit.setText(zone.skybox if zone.skybox else "")
        self._skybox_edit.setPlaceholderText("(empty = procedural gradient)")
        layout.addRow("Skybox:", self._skybox_edit)

        sky = zone.sky_color if zone.sky_color else (0, 0, 0)
        self._sky_r = QSpinBox()
        self._sky_r.setRange(0, 255)
        self._sky_r.setValue(sky[0] if len(sky) >= 1 else 0)
        self._sky_g = QSpinBox()
        self._sky_g.setRange(0, 255)
        self._sky_g.setValue(sky[1] if len(sky) >= 2 else 0)
        self._sky_b = QSpinBox()
        self._sky_b.setRange(0, 255)
        self._sky_b.setValue(sky[2] if len(sky) >= 3 else 0)
        from PySide6.QtWidgets import QHBoxLayout, QWidget
        sky_row = QWidget()
        sky_layout = QHBoxLayout(sky_row)
        sky_layout.setContentsMargins(0, 0, 0, 0)
        sky_layout.addWidget(QLabel("R"))
        sky_layout.addWidget(self._sky_r)
        sky_layout.addWidget(QLabel("G"))
        sky_layout.addWidget(self._sky_g)
        sky_layout.addWidget(QLabel("B"))
        sky_layout.addWidget(self._sky_b)
        layout.addRow("Sky Color:", sky_row)

        anchor = zone.anchor if zone.anchor else (0.0, 0.0)
        self._anchor_r = QDoubleSpinBox()
        self._anchor_r.setRange(0.0, zone.height - 1)
        self._anchor_r.setDecimals(2)
        self._anchor_r.setValue(anchor[0] if len(anchor) >= 1 else 0.0)
        self._anchor_c = QDoubleSpinBox()
        self._anchor_c.setRange(0.0, zone.width - 1)
        self._anchor_c.setDecimals(2)
        self._anchor_c.setValue(anchor[1] if len(anchor) >= 2 else 0.0)
        anchor_row = QWidget()
        anchor_layout = QHBoxLayout(anchor_row)
        anchor_layout.setContentsMargins(0, 0, 0, 0)
        anchor_layout.addWidget(QLabel("Row"))
        anchor_layout.addWidget(self._anchor_r)
        anchor_layout.addWidget(QLabel("Col"))
        anchor_layout.addWidget(self._anchor_c)
        layout.addRow("Spawn Anchor:", anchor_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def values(self) -> dict:
        sky = (self._sky_r.value(), self._sky_g.value(), self._sky_b.value())
        if sky == (0, 0, 0):
            sky = ()
        return {
            "first_person": self._fp_check.isChecked(),
            "skybox": self._skybox_edit.text().strip(),
            "sky_color": sky,
            "anchor": (self._anchor_r.value(), self._anchor_c.value()),
        }


class HelpDialog(QDialog):
    """Dialog showing all keyboard shortcuts."""

    _SHORTCUTS = """\
─── General ───────────────────────────
1              Paint tool
2              Sculpt tool
3              Select tool
4              Erase tool
5              Tile Type tool
6              Entity tool
7              Light tool
Ctrl+Z         Undo
Ctrl+Y / Ctrl+Shift+Z   Redo
Ctrl+S         Save
Ctrl+Shift+S   Save As
Ctrl+N         New Zone
Ctrl+O         Open Zone
Ctrl+F         Find / Replace Texture
Ctrl+A         Select all cells
Ctrl+C         Copy selection
Ctrl+V         Paste at hovered cell
Escape         Clear selection
Home           Reset Camera
Tab            Toggle 2.5D raycaster preview

─── Camera ────────────────────────────
Right-click + drag   Orbit / Look
W / A / S / D  Move (while right-click)
Shift          Sprint
Scroll wheel   Zoom in / out
Shift+1..9     Save camera bookmark
Alt+1..9       Recall camera bookmark

─── Paint Tool ────────────────────────
Click          Paint face
Shift+Click    Paint all faces of cell
Ctrl+Click     Flood fill
Middle-click   Eyedropper (pick texture)

─── Sculpt Tool ───────────────────────
Click + drag   Raise (floor) / Lower (ceiling)
Shift+Click    Lower (floor) / Raise (ceiling)
G              Cycle snap grid
H              Make cell a wall
Shift+H        Make cell open (grass)
T              Toggle ceiling (sky / closed)
R              Reset floor or ceiling height
U              Raise upper wall height
Shift+U        Lower upper wall height
Ctrl+U         Reset upper wall height
Delete         Clear cell (all defaults)

─── Select Tool ───────────────────────
Click          Set rectangle corners (2-click)
Ctrl+Click     Toggle individual cell
Shift+Click    Select line (Bresenham)
Scroll wheel   Raise / lower selected heights
X              Toggle floor / ceiling mode
Delete         Reset selected cells
H              Make selected cells walls
Shift+H        Make selected cells open

─── Entity Tool ───────────────────────
Click          Place / select entity
Shift+Click    Always place (ignore existing)
Right-click    Delete entity under cursor
R              Rotate selected 90°
M              Move selected to hovered cell
Delete         Delete selected entity

─── Light Tool ─────────────────────────
Click + drag   Increase light level
Shift+Click    Decrease light level
[ / ]          Decrease / increase step size
Middle-click   Sample light level

─── Erase Tool ────────────────────────
Click          Full cell reset
Shift+Click    Clear textures only
Right-click    Reset height only

─── View ──────────────────────────────
Ctrl+1         Toggle walls visibility
Ctrl+2         Toggle floors visibility
Ctrl+3         Toggle ceilings visibility
Ctrl+4         Toggle entities visibility
Ctrl+5         Toggle wireframe
G              Toggle grid (non-sculpt)
F3             Toggle performance overlay
F4             Dump stats

─── Raycaster Preview ─────────────────
Tab            Return to 3D editor
Click          Enter FPS mode
W / A / S / D  Move
Shift          Sprint
Escape         Release mouse
"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Keyboard Shortcuts")
        self.resize(480, 520)
        layout = QVBoxLayout(self)

        text = QPlainTextEdit()
        text.setPlainText(self._SHORTCUTS)
        text.setReadOnly(True)
        text.setFont(QFont("Consolas", 10))
        layout.addWidget(text)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # Import QFont locally if needed
    pass


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    rebuild_derived()

    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    fmt.setDepthBufferSize(24)
    fmt.setSamples(4)
    QSurfaceFormat.setDefaultFormat(fmt)

    app = QApplication(sys.argv)

    # Determine which zone to load
    session = load_session()
    zone_name = ""
    zone: Zone | None = None

    if len(sys.argv) > 1:
        zone_name = sys.argv[1]
    else:
        zone_name = session.get("last_zone", "")

    if zone_name:
        try:
            zone = load_zone(zone_name)
            print(f"Loaded zone: {zone_name} "
                  f"({zone.width}×{zone.height}, {len(zone.entities)} entities)")
        except Exception:
            print(f"Could not load '{zone_name}', starting with empty zone")
            zone = None
            zone_name = ""

    if zone is None:
        zone = _create_empty_zone()
        zone_name = "untitled"
        print("Starting with empty 20×20 zone")

    win = EditorWindow(zone, zone_name)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
