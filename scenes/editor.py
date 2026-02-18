"""scenes/editor.py -- Modern tile-map editor.

A standalone Scene for editing zone JSON files.  Push it from TopDown
with F4 and pop back with F4 or Escape.

Features:
    - Visual tile palette with hover preview
    - Click / drag to paint, right-click to erase (-> grass)
    - Adjustable brush ([ / ])
    - Eyedropper / tile picker (Alt+click)
    - Entity placement, drag-to-move, rename, delete (E mode)
    - Portal wizard (T mode) -- visual step-by-step portal linking
    - Anchor placement (K)
    - Minimap overview panel (M to toggle)
    - Zone metadata editing (name, size, first_person flag)
    - Undo / redo (Ctrl+Z / Ctrl+Y)
    - Save to zones/<name>.json (Ctrl+S)
    - New zone (Ctrl+N)
    - Zone picker (Tab)

Controls are listed in-editor on the top toolbar.
"""

from __future__ import annotations

import json
import math
from collections import deque
from copy import deepcopy
from pathlib import Path
from typing import Any

import pygame

from core.app import App
from core.constants import TILE_SIZE
from core.tiles import TILE_COLORS, TILE_NAMES, TILE_REGISTRY
from core.scene import Scene
from core.zones import ZONES_DIR, load_zone, list_zones, Zone, Portal
from systems.spawner import _PREFAB_DEFAULTS

# ===================================================================
#  Direction helpers
# ===================================================================
DIRECTIONS = ["up", "down", "left", "right"]
DIR_ARROWS = {"up": "\u25B2", "down": "\u25BC", "left": "\u25C0", "right": "\u25B6"}
DIR_DELTA  = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}

# ===================================================================
#  Colours
# ===================================================================
COL_BG         = (30, 30, 34)
COL_PANEL      = (42, 42, 48)
COL_PANEL_LITE = (58, 58, 66)
COL_TEXT       = (220, 220, 220)
COL_TEXT_DIM   = (140, 140, 150)
COL_ACCENT     = (80, 160, 255)
COL_ACCENT2    = (255, 180, 60)
COL_DANGER     = (255, 80, 80)
COL_SUCCESS    = (80, 220, 120)
COL_PORTAL     = (200, 60, 220)
COL_ANCHOR     = (60, 200, 240)
COL_ENTITY     = (100, 220, 160)
COL_GRID       = (60, 60, 66)

# Layout
TOOLBAR_H    = 36
PALETTE_W    = 160
STATUS_H     = 24


# ===================================================================
#  Portal Wizard -- multi-step visual portal creation
# ===================================================================

class PortalWizard:
    """Step-by-step UI for creating / editing a portal link.

    Steps:
        1  Pick entry exit_direction (the direction players walk OUT of
           the portal on the source side).
        2  Pick destination zone (list).
        3  Click on destination zone map to choose target tile +
           pick the exit_direction for that side.
    """

    STEP_ENTRY_DIR  = 1
    STEP_DEST_ZONE  = 2
    STEP_DEST_TILE  = 3

    def __init__(self, source_tile: list[int],
                 editing: dict | None = None) -> None:
        self.source_tile = source_tile  # [row, col] on current zone

        # Result data
        self.entry_dir: str = "up"
        self.dest_zone: str = ""
        self.dest_tile: tuple[int, int] | None = None
        self.exit_dir: str = "up"

        # Pre-fill when editing
        self.editing = editing
        if editing:
            self.entry_dir = editing.get("exit_direction", "up")
            self.dest_zone = editing.get("target_zone", "")
            tp = editing.get("target_pos", [0, 0])
            self.dest_tile = (int(tp[0]), int(tp[1]))
            self.exit_dir = self._read_dest_exit_dir()
            self.step = self.STEP_ENTRY_DIR
        else:
            self.step = self.STEP_ENTRY_DIR

        # Dest zone map preview data
        self.dest_tiles: list[list[int]] | None = None
        self.dest_map_w: int = 0
        self.dest_map_h: int = 0
        self.dest_portals: list[dict] = []
        self.dest_cam_x: float = 0.0
        self.dest_cam_y: float = 0.0
        self.dest_zoom: float = 1.0
        self._dest_panning = False
        self._dest_pan_start: tuple[int, int] = (0, 0)
        self._dest_cam_start: tuple[float, float] = (0.0, 0.0)
        self._dest_hover: tuple[int, int] | None = None

        # Zone list for step 2
        self.zone_list: list[str] = []
        self.zone_scroll: int = 0

    def _read_dest_exit_dir(self) -> str:
        """When editing, try to read the destination zone's matching
        portal to get its exit_direction."""
        if not self.dest_zone or not self.dest_tile:
            return "up"
        try:
            zone = load_zone(self.dest_zone)
            for p in zone.portals:
                for t in p.tiles:
                    if t[0] == self.dest_tile[0] and t[1] == self.dest_tile[1]:
                        return p.exit_direction
        except Exception:
            pass
        return "up"

    def load_dest_zone(self) -> None:
        """Load destination zone tile data for the map preview."""
        try:
            zone = load_zone(self.dest_zone)
            self.dest_tiles = zone.tiles
            self.dest_map_w = zone.width
            self.dest_map_h = zone.height
            self.dest_portals = []
            for p in zone.portals:
                self.dest_portals.append({
                    "tiles": [list(t) for t in p.tiles],
                    "target_zone": p.target_zone,
                })
            self.dest_cam_x = -(self.dest_map_w * TILE_SIZE) / 2
            self.dest_cam_y = -(self.dest_map_h * TILE_SIZE) / 2
        except Exception:
            self.dest_tiles = None

    @property
    def done(self) -> bool:
        return (self.step > self.STEP_DEST_TILE
                and self.dest_tile is not None
                and self.dest_zone != "")

    def advance(self) -> None:
        """Move to next step."""
        self.step += 1
        if self.step == self.STEP_DEST_ZONE:
            self.zone_list = list_zones()
        elif self.step == self.STEP_DEST_TILE:
            if self.dest_zone:
                self.load_dest_zone()

    def build_portal(self) -> dict:
        """Return the portal dict for the source zone."""
        r, c = self.dest_tile or (0, 0)
        return {
            "tiles": [self.source_tile],
            "target_zone": self.dest_zone,
            "target_pos": [float(r), float(c)],
            "exit_direction": self.entry_dir,
        }

    def build_return_portal(self, source_zone: str) -> dict:
        """Return the matching portal dict for the destination zone."""
        sr, sc = self.source_tile
        dr, dc = self.dest_tile or (0, 0)
        return {
            "tiles": [[dr, dc]],
            "target_zone": source_zone,
            "target_pos": [float(sr), float(sc)],
            "exit_direction": self.exit_dir,
        }


# ===================================================================
#  Main Editor Scene
# ===================================================================

class MapEditor(Scene):
    """Full-screen tile-map editor scene."""

    def __init__(self, zone_name: str = "playground") -> None:
        self.zone_name = zone_name
        self._load_zone(zone_name)

        # View state
        self.cam_x: float = 0.0
        self.cam_y: float = 0.0
        self.zoom: float = 1.0
        self._panning = False
        self._pan_start: tuple[int, int] = (0, 0)
        self._cam_start: tuple[float, float] = (0.0, 0.0)

        # Tile painting
        self.selected_tile: int = 1
        self.brush_size: int = 1

        # Mode flags
        self.portal_mode: bool = False
        self.anchor_mode: bool = False

        # Portal wizard (None when inactive)
        self._wizard: PortalWizard | None = None

        # Text input overlay
        self.text_input_active: bool = False
        self.text_input_buffer: str = ""
        self.text_input_label: str = ""
        self._text_callback: Any = None

        # Undo / redo
        self._undo_stack: deque[list[list[int]]] = deque(maxlen=50)
        self._redo_stack: deque[list[list[int]]] = deque(maxlen=50)
        self._push_undo()

        # Status toast
        self._status: str = ""
        self._status_timer: float = 0.0

        # Show grid
        self.show_grid: bool = True

        # Zone picker
        self._zone_list: list[str] = []
        self._zone_picker_open: bool = False
        self._zone_picker_scroll: int = 0

        # Hovered tile
        self._hover: tuple[int, int] | None = None

        # Entity editing
        self.entity_mode: bool = False
        self._entity_selected: int = -1  # index into self.entities
        self._entity_dragging: bool = False
        self._prefab_list: list[str] = sorted(_PREFAB_DEFAULTS.keys())
        self._entity_panel_open: bool = False  # prefab picker
        self._entity_panel_scroll: int = 0

        # Minimap
        self.show_minimap: bool = True

    # -- Zone I/O --------------------------------------------------

    def _load_zone(self, name: str) -> None:
        """Load zone data from JSON into editor state."""
        zone = load_zone(name)
        self.zone_name = name
        self.tiles: list[list[int]] = zone.tiles
        self.map_h: int = zone.height
        self.map_w: int = zone.width
        self.anchor: tuple[float, float] = zone.anchor
        self.portals: list[dict] = []
        for p in zone.portals:
            self.portals.append({
                "tiles": [list(t) for t in p.tiles],
                "target_zone": p.target_zone,
                "target_pos": [p.target_row, p.target_col],
                "exit_direction": p.exit_direction,
            })
        self.entities: list[dict] = zone.entities
        self.first_person: bool = zone.first_person

        # Reset all mode flags so stale state doesn't leak between zones
        self.entity_mode = False
        self._entity_selected = -1
        self._entity_dragging = False
        self._entity_panel_open = False
        self._entity_panel_scroll = 0
        self.portal_mode = False
        self.anchor_mode = False
        self._wizard = None
        self.text_input_active = False
        self.text_input_buffer = ""

        # Centre camera on the map
        self.cam_x = -(self.map_w * TILE_SIZE) / 2
        self.cam_y = -(self.map_h * TILE_SIZE) / 2

    def _save_zone(self) -> None:
        """Write current state to zones/<name>.json."""
        data: dict[str, Any] = {
            "name": self.zone_name,
            "width": self.map_w,
            "height": self.map_h,
            "anchor": list(self.anchor),
            "tiles": self.tiles,
            "portals": self.portals,
            "entities": self.entities,
        }
        if self.first_person:
            data["first_person"] = True
        path = ZONES_DIR / f"{self.zone_name}.json"
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        self._toast(f"Saved {path.name}")

    def _save_dest_zone_portal(self, return_portal: dict,
                               dest_zone_name: str,
                               dest_tile: tuple[int, int]) -> None:
        """Add or update the return portal in the destination zone file."""
        path = ZONES_DIR / f"{dest_zone_name}.json"
        if not path.exists():
            return
        with open(path) as f:
            data = json.load(f)

        portals = data.get("portals", [])

        # Remove any existing portal that has the same dest tile
        dr, dc = dest_tile
        portals = [
            p for p in portals
            if [dr, dc] not in p.get("tiles", [])
        ]

        portals.append(return_portal)
        data["portals"] = portals

        # Also ensure the tile is set to 9 (portal)
        tiles = data.get("tiles", [])
        if 0 <= dr < len(tiles) and 0 <= dc < len(tiles[0]):
            tiles[dr][dc] = 9

        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    # -- Undo / redo -----------------------------------------------

    def _push_undo(self) -> None:
        self._undo_stack.append(deepcopy(self.tiles))
        self._redo_stack.clear()

    def _undo(self) -> None:
        if len(self._undo_stack) > 1:
            self._redo_stack.append(self._undo_stack.pop())
            self.tiles = deepcopy(self._undo_stack[-1])
            self._toast("Undo")

    def _redo(self) -> None:
        if self._redo_stack:
            snap = self._redo_stack.pop()
            self._undo_stack.append(snap)
            self.tiles = deepcopy(snap)
            self._toast("Redo")

    # -- Toast -----------------------------------------------------

    def _toast(self, msg: str, duration: float = 2.0) -> None:
        self._status = msg
        self._status_timer = duration

    # -- Coordinate helpers ----------------------------------------

    def _screen_to_world(self, sx: int, sy: int) -> tuple[float, float]:
        vw, vh = 960, 640
        wx = (sx - vw / 2) / self.zoom - self.cam_x
        wy = (sy - vh / 2 - TOOLBAR_H / 2) / self.zoom - self.cam_y
        return wx, wy

    def _world_to_screen(self, wx: float, wy: float) -> tuple[int, int]:
        vw, vh = 960, 640
        sx = int((wx + self.cam_x) * self.zoom + vw / 2)
        sy = int((wy + self.cam_y) * self.zoom + vh / 2 + TOOLBAR_H / 2)
        return sx, sy

    def _screen_to_tile(self, sx: int, sy: int) -> tuple[int, int] | None:
        wx, wy = self._screen_to_world(sx, sy)
        c = int(wx / TILE_SIZE)
        r = int(wy / TILE_SIZE)
        if 0 <= r < self.map_h and 0 <= c < self.map_w:
            return r, c
        return None

    # -- Paint operations ------------------------------------------

    def _paint(self, row: int, col: int) -> None:
        half = self.brush_size // 2
        for rr in range(row - half, row - half + self.brush_size):
            for cc in range(col - half, col - half + self.brush_size):
                if 0 <= rr < self.map_h and 0 <= cc < self.map_w:
                    self.tiles[rr][cc] = self.selected_tile

    def _erase(self, row: int, col: int) -> None:
        half = self.brush_size // 2
        for rr in range(row - half, row - half + self.brush_size):
            for cc in range(col - half, col - half + self.brush_size):
                if 0 <= rr < self.map_h and 0 <= cc < self.map_w:
                    self.tiles[rr][cc] = 1

    def _flood_fill(self, row: int, col: int) -> None:
        target = self.tiles[row][col]
        if target == self.selected_tile:
            return
        stack = [(row, col)]
        visited = set()
        while stack:
            r, c = stack.pop()
            if (r, c) in visited:
                continue
            if r < 0 or r >= self.map_h or c < 0 or c >= self.map_w:
                continue
            if self.tiles[r][c] != target:
                continue
            visited.add((r, c))
            self.tiles[r][c] = self.selected_tile
            stack.extend([(r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)])
        self._toast(f"Filled {len(visited)} tiles")

    # -- Portal operations -----------------------------------------

    def _start_portal_wizard(self, row: int, col: int) -> None:
        """Start the portal wizard for a tile."""
        # Check if editing existing
        for p in self.portals:
            if [row, col] in p["tiles"]:
                self._wizard = PortalWizard([row, col], editing=p)
                return

        # New portal -- set tile to portal type
        self.tiles[row][col] = 9
        self._wizard = PortalWizard([row, col])

    def _cancel_wizard(self) -> None:
        """Cancel the wizard, reverting tile if it was a new portal."""
        if self._wizard and not self._wizard.editing:
            r, c = self._wizard.source_tile
            self.tiles[r][c] = 1
        self._wizard = None
        self._toast("Portal cancelled")

    def _finish_wizard(self) -> None:
        """Commit the wizard result."""
        wiz = self._wizard
        if not wiz or not wiz.done:
            return

        portal_data = wiz.build_portal()

        if wiz.editing:
            wiz.editing["target_zone"] = portal_data["target_zone"]
            wiz.editing["target_pos"] = portal_data["target_pos"]
            wiz.editing["exit_direction"] = portal_data["exit_direction"]
        else:
            self.portals.append(portal_data)

        # Also update the destination zone file with the return portal
        if wiz.dest_tile:
            return_portal = wiz.build_return_portal(self.zone_name)
            self._save_dest_zone_portal(
                return_portal, wiz.dest_zone, wiz.dest_tile,
            )

        self._wizard = None
        self._push_undo()
        dest = portal_data["target_zone"]
        self._toast(f"Portal linked to {dest}")

    def _delete_portal_at(self, row: int, col: int) -> None:
        for i, p in enumerate(self.portals):
            if [row, col] in p["tiles"]:
                p["tiles"].remove([row, col])
                if not p["tiles"]:
                    self.portals.pop(i)
                self.tiles[row][col] = 1
                self._toast("Portal removed")
                self._push_undo()
                return

    # -- Entity operations -----------------------------------------

    def _entity_at(self, row: int, col: int) -> int:
        """Return index of entity near tile (row,col), or -1."""
        for i, ent in enumerate(self.entities):
            pos = ent.get("position", {})
            ex = pos.get("x", 0.0)
            ey = pos.get("y", 0.0)
            if abs(ex - (col + 0.5)) < 0.8 and abs(ey - (row + 0.5)) < 0.8:
                return i
        return -1

    def _entity_click(self, row: int, col: int, app: App) -> None:
        """Left-click in entity mode: select, start drag, or open picker."""
        idx = self._entity_at(row, col)
        if idx >= 0:
            if idx == self._entity_selected:
                # Double-click on selected entity → open name editor
                ent = self.entities[idx]
                ident = ent.get("identity", {})
                self._open_text_input(
                    "Entity name:", ident.get("name", ""),
                    lambda name, _i=idx: self._rename_entity(_i, name),
                )
            else:
                self._entity_selected = idx
                self._entity_dragging = True
                self._toast(f"Selected: {self._entity_name(idx)}")
        else:
            # Empty tile → open prefab picker to place a new entity
            self._entity_place_at = (row, col)
            self._entity_panel_open = True
            self._entity_panel_scroll = 0

    def _entity_right_click(self, row: int, col: int) -> None:
        """Right-click in entity mode: delete entity at tile."""
        idx = self._entity_at(row, col)
        if idx >= 0:
            name = self._entity_name(idx)
            self.entities.pop(idx)
            if self._entity_selected >= len(self.entities):
                self._entity_selected = -1
            self._toast(f"Deleted: {name}")

    def _entity_name(self, idx: int) -> str:
        """Human-readable name for an entity."""
        ent = self.entities[idx]
        ident = ent.get("identity", {})
        return ident.get("name", ent.get("id", f"entity_{idx}"))

    def _rename_entity(self, idx: int, name: str) -> None:
        if not name or idx >= len(self.entities):
            return
        ent = self.entities[idx]
        ident = ent.setdefault("identity", {})
        ident["name"] = name
        self._toast(f"Renamed → {name}")

    def _place_entity(self, prefab: str) -> None:
        """Place a new entity using the selected prefab."""
        r, c = getattr(self, "_entity_place_at", (0, 0))
        # Generate a unique id
        existing_ids = {e.get("id", "") for e in self.entities}
        base = f"{prefab}_{len(self.entities)}"
        uid = base
        n = 0
        while uid in existing_ids:
            n += 1
            uid = f"{base}_{n}"

        # Get sprite info from prefab defaults
        defaults = _PREFAB_DEFAULTS.get(prefab, {})

        ent: dict[str, Any] = {
            "id": uid,
            "prefab": prefab,
            "position": {"x": float(c) + 0.5, "y": float(r) + 0.5},
        }
        if "identity" in defaults:
            ent["identity"] = dict(defaults["identity"])
            ent["identity"]["name"] = f"{prefab.title()} ({uid})"
        if "sprite" in defaults:
            ent["sprite"] = dict(defaults["sprite"])
        # Tile entity metadata (containers, crops, ground items)
        if "tile_entity" in defaults:
            ent["tile_entity"] = dict(defaults["tile_entity"])
            ent["tile_entity"]["tiles"] = [[r, c]]

        self.entities.append(ent)
        self._entity_selected = len(self.entities) - 1
        self._entity_panel_open = False
        self._toast(f"Placed {prefab}: {uid}")

    # -- Text input ------------------------------------------------

    def _open_text_input(self, label: str, initial: str,
                         callback) -> None:
        self.text_input_active = True
        self.text_input_label = label
        self.text_input_buffer = initial
        self._text_callback = callback

    def _finish_text_input(self, submit: bool) -> None:
        if submit and self._text_callback:
            self._text_callback(self.text_input_buffer.strip())
        self.text_input_active = False
        self.text_input_buffer = ""
        self.text_input_label = ""
        self._text_callback = None

    # -- New zone --------------------------------------------------

    def _new_zone_dialog(self) -> None:
        self._open_text_input("New zone name:", "", self._create_zone)

    def _create_zone(self, name: str) -> None:
        if not name:
            self._toast("Cancelled")
            return
        self.zone_name = name
        self.map_w = 30
        self.map_h = 20
        self.tiles = [[1] * self.map_w for _ in range(self.map_h)]
        self.anchor = (10.0, 15.0)
        self.portals = []
        self.entities = []
        self.first_person = False
        self.cam_x = -(self.map_w * TILE_SIZE) / 2
        self.cam_y = -(self.map_h * TILE_SIZE) / 2
        self._push_undo()
        self._toast(f"Created '{name}' (30x20)")

    def _resize_dialog(self) -> None:
        self._open_text_input(
            "Resize (WxH):", f"{self.map_w}x{self.map_h}",
            self._do_resize,
        )

    def _do_resize(self, val: str) -> None:
        try:
            w_str, h_str = val.lower().split("x")
            nw, nh = int(w_str.strip()), int(h_str.strip())
        except Exception:
            self._toast("Invalid format -- use WxH (e.g. 30x20)")
            return
        nw = max(5, min(nw, 100))
        nh = max(5, min(nh, 100))
        new_tiles = [[1] * nw for _ in range(nh)]
        for r in range(min(nh, self.map_h)):
            for c in range(min(nw, self.map_w)):
                new_tiles[r][c] = self.tiles[r][c]
        self.tiles = new_tiles
        self.map_w = nw
        self.map_h = nh
        self._push_undo()
        self._toast(f"Resized to {nw}x{nh}")

    # -- Scene lifecycle -------------------------------------------

    def on_enter(self, app: App) -> None:
        pass

    def on_exit(self, app: App) -> None:
        pass

    # ==============================================================
    #  EVENT HANDLING
    # ==============================================================

    def handle_event(self, event: pygame.event.Event, app: App) -> None:
        # -- Portal wizard captures all input when active ----------
        if self._wizard is not None:
            self._handle_wizard_event(event, app)
            return

        # -- Zone picker overlay -----------------------------------
        if self._zone_picker_open:
            self._handle_zone_picker_event(event, app)
            return

        # -- Entity prefab picker overlay --------------------------
        if self._entity_panel_open:
            self._handle_entity_panel_event(event, app)
            return

        # -- Text input overlay ------------------------------------
        if self.text_input_active:
            self._handle_text_event(event)
            return

        if event.type == pygame.KEYDOWN:
            self._handle_keydown(event, app)
        elif event.type == pygame.MOUSEBUTTONDOWN:
            self._handle_mouse_down(event, app)
        elif event.type == pygame.MOUSEBUTTONUP:
            self._handle_mouse_up(event)
        elif event.type == pygame.MOUSEMOTION:
            self._handle_mouse_motion(event, app)
        elif event.type == pygame.MOUSEWHEEL:
            if event.y > 0:
                self.zoom = min(4.0, self.zoom * 1.15)
            elif event.y < 0:
                self.zoom = max(0.25, self.zoom / 1.15)

    def _handle_keydown(self, event: pygame.event.Event, app: App) -> None:
        mods = pygame.key.get_mods()
        ctrl = mods & pygame.KMOD_CTRL

        if event.key in (pygame.K_ESCAPE, pygame.K_F4):
            app.pop_scene()
        elif ctrl and event.key == pygame.K_s:
            self._save_zone()
        elif ctrl and event.key == pygame.K_z:
            self._undo()
        elif ctrl and event.key == pygame.K_y:
            self._redo()
        elif ctrl and event.key == pygame.K_n:
            self._new_zone_dialog()
        elif event.key == pygame.K_TAB:
            self._zone_list = list_zones()
            self._zone_picker_open = True
            self._zone_picker_scroll = 0
        elif event.key == pygame.K_m:
            self.show_minimap = not self.show_minimap
        elif event.key == pygame.K_t:
            self.portal_mode = not self.portal_mode
            self.anchor_mode = False
            self.entity_mode = False
            self._toast(f"Portal mode {'ON' if self.portal_mode else 'OFF'}")
        elif event.key == pygame.K_e:
            self.entity_mode = not self.entity_mode
            self.portal_mode = False
            self.anchor_mode = False
            self._entity_selected = -1
            self._toast(f"Entity mode {'ON' if self.entity_mode else 'OFF'}")
        elif event.key == pygame.K_k:
            self.anchor_mode = not self.anchor_mode
            self.portal_mode = False
            self.entity_mode = False
            self._toast(f"Anchor mode {'ON' if self.anchor_mode else 'OFF'}")
        elif event.key == pygame.K_g:
            self.show_grid = not self.show_grid
        elif event.key == pygame.K_f:
            self.first_person = not self.first_person
            self._toast(f"first_person = {self.first_person}")
        elif event.key == pygame.K_r:
            self._resize_dialog()
        elif event.key == pygame.K_LEFTBRACKET:
            self.brush_size = max(1, self.brush_size - 1)
            self._toast(f"Brush {self.brush_size}")
        elif event.key == pygame.K_RIGHTBRACKET:
            self.brush_size = min(8, self.brush_size + 1)
            self._toast(f"Brush {self.brush_size}")
        elif event.key in range(pygame.K_0, pygame.K_9 + 1):
            self.selected_tile = event.key - pygame.K_0
            self.portal_mode = False
            self.anchor_mode = False

    def _handle_mouse_down(self, event: pygame.event.Event,
                           app: App) -> None:
        mx, my = app.mouse_pos()

        # Palette click
        if mx < PALETTE_W and my > TOOLBAR_H:
            self._handle_palette_click(mx, my)
            return

        rc = self._screen_to_tile(mx, my)

        if event.button == 2:
            self._panning = True
            self._pan_start = (mx, my)
            self._cam_start = (self.cam_x, self.cam_y)
            return

        if rc is None:
            return
        r, c = rc

        if event.button == 1:
            mods = pygame.key.get_mods()
            if mods & pygame.KMOD_ALT:
                # Eyedropper — pick tile under cursor
                self.selected_tile = self.tiles[r][c]
                tname = TILE_NAMES.get(self.selected_tile, "?")
                self._toast(f"Picked: {self.selected_tile} ({tname})")
            elif self.entity_mode:
                self._entity_click(r, c, app)
            elif self.anchor_mode:
                self.anchor = (float(c) + 0.5, float(r) + 0.5)
                self._toast(f"Anchor set ({c+0.5:.1f}, {r+0.5:.1f})")
                self._push_undo()
            elif self.portal_mode:
                self._start_portal_wizard(r, c)
            elif mods & pygame.KMOD_SHIFT:
                self._flood_fill(r, c)
                self._push_undo()
            else:
                self._paint(r, c)
        elif event.button == 3:
            if self.entity_mode:
                self._entity_right_click(r, c)
            elif self.portal_mode:
                self._delete_portal_at(r, c)
            else:
                self._erase(r, c)

    def _handle_mouse_up(self, event: pygame.event.Event) -> None:
        if event.button == 2:
            self._panning = False
        elif event.button == 1:
            if self._entity_dragging:
                self._entity_dragging = False
            elif self._undo_stack and self.tiles != self._undo_stack[-1]:
                self._push_undo()
        elif event.button == 3:
            if self._undo_stack and self.tiles != self._undo_stack[-1]:
                self._push_undo()

    def _handle_mouse_motion(self, event: pygame.event.Event,
                             app: App) -> None:
        mx, my = app.mouse_pos()
        self._hover = self._screen_to_tile(mx, my)

        if self._panning:
            dx = mx - self._pan_start[0]
            dy = my - self._pan_start[1]
            self.cam_x = self._cam_start[0] + dx / self.zoom
            self.cam_y = self._cam_start[1] + dy / self.zoom
            return

        btns = pygame.mouse.get_pressed()
        rc = self._screen_to_tile(mx, my)

        # Entity drag
        if self._entity_dragging and self._entity_selected >= 0 and rc:
            r, c = rc
            ent = self.entities[self._entity_selected]
            pos = ent.get("position", {})
            pos["x"] = float(c) + 0.5
            pos["y"] = float(r) + 0.5
            ent["position"] = pos
            return

        if rc and not self.portal_mode and not self.anchor_mode and not self.entity_mode:
            r, c = rc
            if btns[0]:
                self._paint(r, c)
            elif btns[2]:
                self._erase(r, c)

    def _handle_text_event(self, event: pygame.event.Event) -> None:
        if event.type != pygame.KEYDOWN:
            return
        if event.key == pygame.K_RETURN:
            self._finish_text_input(submit=True)
        elif event.key == pygame.K_ESCAPE:
            self._finish_text_input(submit=False)
        elif event.key == pygame.K_BACKSPACE:
            self.text_input_buffer = self.text_input_buffer[:-1]
        else:
            ch = event.unicode
            if ch and ch.isprintable():
                self.text_input_buffer += ch

    def _handle_zone_picker_event(self, event: pygame.event.Event,
                                  app: App) -> None:
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_ESCAPE, pygame.K_TAB):
                self._zone_picker_open = False
                return
        if event.type == pygame.MOUSEWHEEL:
            self._zone_picker_scroll -= event.y * 20
            self._zone_picker_scroll = max(0, self._zone_picker_scroll)
            return
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = app.mouse_pos()
            sw, sh = app.virtual_size
            panel_x, panel_y = 200, 80
            pw, ph = 560, sh - 160
            item_h = 32
            clip = pygame.Rect(panel_x + 8, panel_y + 40,
                               pw - 16, ph - 52)
            for i, z in enumerate(self._zone_list):
                iy = panel_y + 40 + i * item_h - self._zone_picker_scroll
                if (clip.x < mx < clip.x + clip.w
                        and iy < my < iy + item_h
                        and iy + item_h > clip.y
                        and iy < clip.y + clip.h):
                    self._zone_picker_open = False
                    self._load_zone(z)
                    self._undo_stack.clear()
                    self._redo_stack.clear()
                    self._push_undo()
                    self._toast(f"Loaded {z}")
                    return

    def _handle_palette_click(self, mx: int, my: int) -> None:
        idx = (my - TOOLBAR_H - 8) // 36
        if 0 <= idx < len(TILE_NAMES):
            self.selected_tile = idx
            self.portal_mode = False
            self.anchor_mode = False

    def _handle_entity_panel_event(self, event: pygame.event.Event,
                                   app: App) -> None:
        """Handle the prefab picker overlay."""
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self._entity_panel_open = False
                return
        if event.type == pygame.MOUSEWHEEL:
            self._entity_panel_scroll -= event.y * 20
            self._entity_panel_scroll = max(0, self._entity_panel_scroll)
            return
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = app.mouse_pos()
            sw, sh = 960, 640
            panel_w, panel_h = 300, 320
            px = (sw - panel_w) // 2
            py = (sh - panel_h) // 2
            item_h = 40
            list_y = py + 50

            for i, prefab in enumerate(self._prefab_list):
                iy = list_y + i * item_h - self._entity_panel_scroll
                if px + 10 < mx < px + panel_w - 10 and iy < my < iy + item_h:
                    self._place_entity(prefab)
                    return

    # -- Portal wizard event handling ------------------------------

    def _handle_wizard_event(self, event: pygame.event.Event,
                             app: App) -> None:
        wiz = self._wizard
        if not wiz:
            return

        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self._cancel_wizard()
            return

        if wiz.step == PortalWizard.STEP_ENTRY_DIR:
            self._wizard_step_dir_event(event, app, "entry")
        elif wiz.step == PortalWizard.STEP_DEST_ZONE:
            self._wizard_step_zone_event(event, app)
        elif wiz.step == PortalWizard.STEP_DEST_TILE:
            self._wizard_step_tile_event(event, app)

    def _wizard_step_dir_event(self, event: pygame.event.Event,
                               app: App, which: str) -> None:
        """Handle clicks on direction buttons."""
        wiz = self._wizard
        if not wiz:
            return
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return

        mx, my = app.mouse_pos()
        sw, sh = 960, 640
        panel_w, panel_h = 460, 220
        px = (sw - panel_w) // 2
        py = (sh - panel_h) // 2
        btn_w, btn_h = 90, 50
        btn_y = py + 100
        gap = 10
        total_w = 4 * btn_w + 3 * gap
        bx_start = px + (panel_w - total_w) // 2

        for i, d in enumerate(DIRECTIONS):
            bx = bx_start + i * (btn_w + gap)
            if bx <= mx <= bx + btn_w and btn_y <= my <= btn_y + btn_h:
                if which == "entry":
                    wiz.entry_dir = d
                else:
                    wiz.exit_dir = d
                wiz.advance()
                return

    def _wizard_step_zone_event(self, event: pygame.event.Event,
                                app: App) -> None:
        wiz = self._wizard
        if not wiz:
            return
        if event.type == pygame.MOUSEWHEEL:
            wiz.zone_scroll -= event.y * 20
            wiz.zone_scroll = max(0, wiz.zone_scroll)
            return
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return

        mx, my = app.mouse_pos()
        sw, sh = 960, 640
        panel_w, panel_h = 460, 400
        px = (sw - panel_w) // 2
        py = (sh - panel_h) // 2
        item_h = 36
        list_y = py + 60

        for i, z in enumerate(wiz.zone_list):
            iy = list_y + i * item_h - wiz.zone_scroll
            if px + 10 < mx < px + panel_w - 10 and iy < my < iy + item_h:
                wiz.dest_zone = z
                wiz.advance()
                return

    def _wizard_step_tile_event(self, event: pygame.event.Event,
                                app: App) -> None:
        """Step 3: click on dest zone map to pick tile + exit direction."""
        wiz = self._wizard
        if not wiz or not wiz.dest_tiles:
            return

        mx, my = app.mouse_pos()
        sw, sh = 960, 640

        if event.type == pygame.MOUSEWHEEL:
            if event.y > 0:
                wiz.dest_zoom = min(4.0, wiz.dest_zoom * 1.15)
            elif event.y < 0:
                wiz.dest_zoom = max(0.25, wiz.dest_zoom / 1.15)
            return

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 2:
            wiz._dest_panning = True
            wiz._dest_pan_start = (mx, my)
            wiz._dest_cam_start = (wiz.dest_cam_x, wiz.dest_cam_y)
            return

        if event.type == pygame.MOUSEBUTTONUP and event.button == 2:
            wiz._dest_panning = False
            return

        if event.type == pygame.MOUSEMOTION:
            rc = self._dest_screen_to_tile(mx, my, wiz)
            wiz._dest_hover = rc
            if wiz._dest_panning:
                dx = mx - wiz._dest_pan_start[0]
                dy = my - wiz._dest_pan_start[1]
                wiz.dest_cam_x = wiz._dest_cam_start[0] + dx / wiz.dest_zoom
                wiz.dest_cam_y = wiz._dest_cam_start[1] + dy / wiz.dest_zoom
            return

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            # Check direction button clicks (right panel)
            dir_panel_x = sw - 190
            dir_panel_y = 200
            btn_w, btn_h = 80, 40
            gap = 8
            for i, d in enumerate(DIRECTIONS):
                by = dir_panel_y + i * (btn_h + gap)
                if dir_panel_x <= mx <= dir_panel_x + btn_w and by <= my <= by + btn_h:
                    wiz.exit_dir = d
                    return

            # Check "Done" button
            done_y = dir_panel_y + 4 * (btn_h + gap) + 20
            if dir_panel_x <= mx <= dir_panel_x + 120 and done_y <= my <= done_y + 44:
                if wiz.dest_tile:
                    wiz.step = PortalWizard.STEP_DEST_TILE + 1
                    self._finish_wizard()
                    return

            # Click on map to select tile
            rc = self._dest_screen_to_tile(mx, my, wiz)
            if rc:
                wiz.dest_tile = rc
                return

    def _dest_screen_to_tile(self, sx: int, sy: int,
                             wiz: PortalWizard) -> tuple[int, int] | None:
        """Convert screen coords to tile coords on the dest zone preview."""
        if not wiz.dest_tiles:
            return None
        map_cx = 380
        map_cy = (640 + TOOLBAR_H) // 2
        wx = (sx - map_cx) / wiz.dest_zoom - wiz.dest_cam_x
        wy = (sy - map_cy) / wiz.dest_zoom - wiz.dest_cam_y
        c = int(wx / TILE_SIZE)
        r = int(wy / TILE_SIZE)
        if 0 <= r < wiz.dest_map_h and 0 <= c < wiz.dest_map_w:
            return r, c
        return None

    def _dest_world_to_screen(self, wx: float, wy: float,
                              wiz: PortalWizard) -> tuple[int, int]:
        map_cx = 380
        map_cy = (640 + TOOLBAR_H) // 2
        sx = int((wx + wiz.dest_cam_x) * wiz.dest_zoom + map_cx)
        sy = int((wy + wiz.dest_cam_y) * wiz.dest_zoom + map_cy)
        return sx, sy

    # ==============================================================
    #  UPDATE
    # ==============================================================

    def update(self, dt: float, app: App) -> None:
        if self._status_timer > 0:
            self._status_timer -= dt

        if self._wizard is not None:
            return

        keys = pygame.key.get_pressed()
        pan_speed = 400.0 / self.zoom
        if keys[pygame.K_LEFT] or keys[pygame.K_a]:
            self.cam_x += pan_speed * dt
        if keys[pygame.K_RIGHT] or keys[pygame.K_d]:
            self.cam_x -= pan_speed * dt
        if keys[pygame.K_UP] or keys[pygame.K_w]:
            self.cam_y += pan_speed * dt
        if keys[pygame.K_DOWN] or keys[pygame.K_s]:
            if not (pygame.key.get_mods() & pygame.KMOD_CTRL):
                self.cam_y -= pan_speed * dt

    # ==============================================================
    #  DRAWING
    # ==============================================================

    def draw(self, surface: pygame.Surface, app: App) -> None:
        surface.fill(COL_BG)

        self._draw_tiles(surface, app)
        self._draw_entities(surface, app)
        self._draw_portals(surface, app)
        self._draw_anchor(surface, app)
        self._draw_cursor(surface, app)
        self._draw_palette(surface, app)
        self._draw_toolbar(surface, app)
        self._draw_status(surface, app)
        if self.show_minimap:
            self._draw_minimap(surface, app)

        if self.text_input_active:
            self._draw_text_input(surface, app)
        if self._zone_picker_open:
            self._draw_zone_picker(surface, app)
        if self._entity_panel_open:
            self._draw_entity_panel(surface, app)
        if self._wizard is not None:
            self._draw_wizard(surface, app)

    # -- Tile grid -------------------------------------------------

    def _draw_tiles(self, surface: pygame.Surface, app: App) -> None:
        sw, sh = surface.get_size()
        ts = int(TILE_SIZE * self.zoom)
        if ts < 1:
            return
        for r in range(self.map_h):
            for c in range(self.map_w):
                sx, sy = self._world_to_screen(c * TILE_SIZE, r * TILE_SIZE)
                if sx + ts < 0 or sy + ts < 0 or sx > sw or sy > sh:
                    continue
                tile_id = self.tiles[r][c]
                color = TILE_COLORS.get(tile_id, (120, 120, 120))
                rect = pygame.Rect(sx, sy, ts, ts)
                pygame.draw.rect(surface, color, rect)
                if self.show_grid and ts >= 8:
                    pygame.draw.rect(surface, COL_GRID, rect, 1)

    # -- Portal markers --------------------------------------------

    def _draw_portals(self, surface: pygame.Surface, app: App) -> None:
        ts = int(TILE_SIZE * self.zoom)
        for p in self.portals:
            for tile in p["tiles"]:
                r, c = tile
                sx, sy = self._world_to_screen(c * TILE_SIZE, r * TILE_SIZE)
                center = (sx + ts // 2, sy + ts // 2)
                radius = max(4, ts // 3)
                pygame.draw.circle(surface, COL_PORTAL, center, radius)
                pygame.draw.circle(surface, (255, 255, 255), center, radius, 1)

                if ts >= 16:
                    label = p["target_zone"][:8]
                    app.draw_text(surface, label,
                                  sx + 2, sy + ts + 1,
                                  COL_TEXT_DIM, app.font_sm)
                    d = p.get("exit_direction", "up")
                    arrow = DIR_ARROWS.get(d, "?")
                    app.draw_text(surface, arrow,
                                  center[0] - 4, center[1] - 6,
                                  (255, 255, 255), app.font_sm)

    # -- Anchor ----------------------------------------------------

    def _draw_anchor(self, surface: pygame.Surface, app: App) -> None:
        ax, ay = self.anchor
        sx, sy = self._world_to_screen(ax * TILE_SIZE, ay * TILE_SIZE)
        pygame.draw.circle(surface, COL_ANCHOR, (sx, sy), 8, 2)
        pygame.draw.line(surface, COL_ANCHOR, (sx - 10, sy), (sx + 10, sy), 1)
        pygame.draw.line(surface, COL_ANCHOR, (sx, sy - 10), (sx, sy + 10), 1)

    # -- Cursor preview --------------------------------------------

    def _draw_cursor(self, surface: pygame.Surface, app: App) -> None:
        if self._hover is None or self._wizard:
            return
        r, c = self._hover
        ts = int(TILE_SIZE * self.zoom)
        half = self.brush_size // 2
        for rr in range(r - half, r - half + self.brush_size):
            for cc in range(c - half, c - half + self.brush_size):
                if 0 <= rr < self.map_h and 0 <= cc < self.map_w:
                    sx, sy = self._world_to_screen(cc * TILE_SIZE,
                                                   rr * TILE_SIZE)
                    rect = pygame.Rect(sx, sy, ts, ts)
                    cursor_surf = pygame.Surface((ts, ts), pygame.SRCALPHA)
                    color = TILE_COLORS.get(self.selected_tile, (200, 200, 200))
                    cursor_surf.fill((*color, 80))
                    surface.blit(cursor_surf, (sx, sy))
                    pygame.draw.rect(surface, (255, 255, 255), rect, 1)

    # -- Entities --------------------------------------------------

    def _draw_entities(self, surface: pygame.Surface, app: App) -> None:
        """Draw entity markers on the tile grid."""
        ts = int(TILE_SIZE * self.zoom)
        for i, ent in enumerate(self.entities):
            pos = ent.get("position", {})
            ex = pos.get("x", 0.0)
            ey = pos.get("y", 0.0)
            sx, sy = self._world_to_screen(ex * TILE_SIZE, ey * TILE_SIZE)

            # Sprite glyph + colour from entity or prefab defaults
            sprite = ent.get("sprite", {})
            if not sprite:
                defaults = _PREFAB_DEFAULTS.get(ent.get("prefab", ""), {})
                sprite = defaults.get("sprite", {})
            char = sprite.get("char", "?")
            color = tuple(sprite.get("color", [200, 200, 200]))
            ident = ent.get("identity", {})
            name = ident.get("name", ent.get("id", ""))

            # Draw marker circle — tile entities get a square instead
            radius = max(6, ts // 3)
            is_sel = (i == self._entity_selected)
            ring_col = COL_ACCENT if is_sel else COL_ENTITY
            te = ent.get("tile_entity", {})
            if te:
                # Square marker for tile entities
                half = radius
                te_col = COL_ACCENT2 if is_sel else (180, 140, 80)
                pygame.draw.rect(surface, te_col,
                                 (sx - half, sy - half, half * 2, half * 2), 2)
            else:
                pygame.draw.circle(surface, ring_col, (sx, sy), radius, 2)

            # Draw glyph
            if ts >= 12:
                glyph = app.font.render(char, True, color)
                surface.blit(glyph, (sx - glyph.get_width() // 2,
                                     sy - glyph.get_height() // 2))
            # Name label
            if ts >= 16 and name:
                label = name[:12]
                app.draw_text(surface, label,
                              sx - len(label) * 3, sy + radius + 2,
                              COL_TEXT_DIM, app.font_sm)

    # -- Minimap ---------------------------------------------------

    _MINIMAP_W = 160
    _MINIMAP_H = 120

    def _draw_minimap(self, surface: pygame.Surface, app: App) -> None:
        """Draw a small overview of the entire zone in the bottom-right."""
        sw, sh = surface.get_size()
        mm_w = self._MINIMAP_W
        mm_h = self._MINIMAP_H
        mm_x = sw - mm_w - 8
        mm_y = sh - mm_h - STATUS_H - 8

        # Background
        bg = pygame.Surface((mm_w, mm_h), pygame.SRCALPHA)
        bg.fill((20, 20, 24, 200))
        surface.blit(bg, (mm_x, mm_y))
        pygame.draw.rect(surface, COL_PANEL_LITE,
                         (mm_x, mm_y, mm_w, mm_h), 1)

        if self.map_w == 0 or self.map_h == 0:
            return

        # Scale to fit
        scale_x = (mm_w - 4) / self.map_w
        scale_y = (mm_h - 4) / self.map_h
        scale = min(scale_x, scale_y)
        ox = mm_x + 2 + int((mm_w - 4 - self.map_w * scale) / 2)
        oy = mm_y + 2 + int((mm_h - 4 - self.map_h * scale) / 2)

        # Draw tiles as pixels
        px_w = max(1, int(scale))
        for r in range(self.map_h):
            for c in range(self.map_w):
                tid = self.tiles[r][c]
                color = TILE_COLORS.get(tid, (80, 80, 80))
                tx = ox + int(c * scale)
                ty = oy + int(r * scale)
                if px_w <= 1:
                    surface.set_at((tx, ty), color)
                else:
                    pygame.draw.rect(surface, color,
                                     (tx, ty, px_w, px_w))

        # Draw portal dots
        for p in self.portals:
            for tile in p["tiles"]:
                pr, pc = tile
                tx = ox + int(pc * scale) + px_w // 2
                ty = oy + int(pr * scale) + px_w // 2
                pygame.draw.circle(surface, COL_PORTAL, (tx, ty),
                                   max(2, px_w))

        # Draw entity dots
        for ent in self.entities:
            pos = ent.get("position", {})
            ex = pos.get("x", 0.0)
            ey = pos.get("y", 0.0)
            tx = ox + int(ex * scale)
            ty = oy + int(ey * scale)
            pygame.draw.circle(surface, COL_ENTITY, (tx, ty),
                               max(1, px_w))

        # Draw viewport rectangle
        vw, vh = 960, 640
        # Viewport corners in tile coords
        tlx, tly = self._screen_to_world(PALETTE_W, TOOLBAR_H)
        brx, bry = self._screen_to_world(vw, vh - STATUS_H)
        vr_x = ox + int(tlx / TILE_SIZE * scale)
        vr_y = oy + int(tly / TILE_SIZE * scale)
        vr_w = int((brx - tlx) / TILE_SIZE * scale)
        vr_h = int((bry - tly) / TILE_SIZE * scale)
        pygame.draw.rect(surface, COL_ACCENT,
                         (vr_x, vr_y, vr_w, vr_h), 1)

    # -- Entity panel (prefab picker) ------------------------------

    def _draw_entity_panel(self, surface: pygame.Surface,
                           app: App) -> None:
        """Draw the prefab picker overlay for placing entities."""
        sw, sh = 960, 640
        overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        surface.blit(overlay, (0, 0))

        panel_w, panel_h = 300, 320
        px = (sw - panel_w) // 2
        py = (sh - panel_h) // 2

        pygame.draw.rect(surface, COL_PANEL,
                         (px, py, panel_w, panel_h), border_radius=10)
        pygame.draw.rect(surface, COL_ENTITY,
                         (px, py, panel_w, panel_h), 2, border_radius=10)

        app.draw_text(surface, "Place Entity  (Esc to cancel)",
                      px + 16, py + 12, COL_ENTITY, app.font)
        app.draw_text(surface, "Select a prefab:",
                      px + 16, py + 32, COL_TEXT_DIM, app.font_sm)

        item_h = 40
        list_y = py + 50
        mx, my = app.mouse_pos()
        clip_bottom = py + panel_h - 20

        for i, prefab in enumerate(self._prefab_list):
            iy = list_y + i * item_h - self._entity_panel_scroll
            if iy + item_h < list_y or iy > clip_bottom:
                continue

            is_hover = (px + 10 < mx < px + panel_w - 10
                        and iy < my < iy + item_h)
            bg = COL_PANEL_LITE if is_hover else COL_PANEL
            item_rect = pygame.Rect(px + 10, iy, panel_w - 20, item_h - 3)
            pygame.draw.rect(surface, bg, item_rect, border_radius=4)

            # Prefab info
            defaults = _PREFAB_DEFAULTS.get(prefab, {})
            sprite_data = defaults.get("sprite", {})
            char = sprite_data.get("char", "?")
            color = tuple(sprite_data.get("color", [200, 200, 200]))

            # Glyph
            glyph = app.font.render(char, True, color)
            surface.blit(glyph, (px + 18, iy + 10))

            # Name
            app.draw_text(surface, prefab.title(),
                          px + 38, iy + 6, COL_TEXT, app.font)
            ident = defaults.get("identity", {})
            kind = ident.get("kind", "")
            app.draw_text(surface, f"Kind: {kind}",
                          px + 38, iy + 22, COL_TEXT_DIM, app.font_sm)

    # -- Palette ---------------------------------------------------

    def _draw_palette(self, surface: pygame.Surface, app: App) -> None:
        panel = pygame.Surface((PALETTE_W, surface.get_height() - TOOLBAR_H),
                               pygame.SRCALPHA)
        panel.fill((*COL_PANEL, 230))
        surface.blit(panel, (0, TOOLBAR_H))

        y = TOOLBAR_H + 8
        for tid in sorted(TILE_NAMES.keys()):
            color = TILE_COLORS.get(tid, (120, 120, 120))
            swatch = pygame.Rect(8, y, 28, 28)
            if tid == self.selected_tile:
                sel_rect = pygame.Rect(4, y - 2, PALETTE_W - 8, 32)
                pygame.draw.rect(surface, COL_ACCENT, sel_rect, 2,
                                 border_radius=4)
            pygame.draw.rect(surface, color, swatch, border_radius=3)
            pygame.draw.rect(surface, (80, 80, 80), swatch, 1, border_radius=3)
            app.draw_text(surface, f"{tid}: {TILE_NAMES[tid]}",
                          42, y + 6, COL_TEXT, app.font_sm)
            y += 36

        y += 16
        if self.portal_mode:
            app.draw_text(surface, "[T] Portal Mode",
                          8, y, COL_PORTAL, app.font_sm)
            y += 18
        if self.anchor_mode:
            app.draw_text(surface, "[K] Anchor Mode",
                          8, y, COL_ANCHOR, app.font_sm)
            y += 18
        if self.entity_mode:
            app.draw_text(surface, "[E] Entity Mode",
                          8, y, COL_ENTITY, app.font_sm)
            y += 18
            app.draw_text(surface, "  Click: select/place",
                          8, y, COL_TEXT_DIM, app.font_sm)
            y += 14
            app.draw_text(surface, "  Drag: move entity",
                          8, y, COL_TEXT_DIM, app.font_sm)
            y += 14
            app.draw_text(surface, "  RClick: delete",
                          8, y, COL_TEXT_DIM, app.font_sm)
            y += 14
            app.draw_text(surface, "  2xClick: rename",
                          8, y, COL_TEXT_DIM, app.font_sm)
            y += 18
        app.draw_text(surface, f"Brush: {self.brush_size}  [ / ]",
                      8, y, COL_TEXT_DIM, app.font_sm)

    # -- Toolbar ---------------------------------------------------

    def _draw_toolbar(self, surface: pygame.Surface, app: App) -> None:
        sw = surface.get_width()
        pygame.draw.rect(surface, COL_PANEL, (0, 0, sw, TOOLBAR_H))
        pygame.draw.line(surface, COL_PANEL_LITE, (0, TOOLBAR_H - 1),
                         (sw, TOOLBAR_H - 1))
        app.draw_text(surface, f"Zone: {self.zone_name}", 8, 10,
                      COL_ACCENT, app.font)
        hints = "F4:Exit  ^S:Save  Tab:Zones  T:Portal  E:Entity  K:Anchor  M:Map  G:Grid  R:Resize  Alt+Click:Pick"
        app.draw_text(surface, hints, 220, 12, COL_TEXT_DIM, app.font_sm)
        if self.first_person:
            app.draw_text(surface, "FP", sw - 30, 10, COL_SUCCESS, app.font)

    # -- Status bar ------------------------------------------------

    def _draw_status(self, surface: pygame.Surface, app: App) -> None:
        sw, sh = surface.get_size()
        pygame.draw.rect(surface, COL_PANEL, (0, sh - STATUS_H, sw, STATUS_H))
        if self._hover:
            r, c = self._hover
            tid = self.tiles[r][c]
            tname = TILE_NAMES.get(tid, "?")
            extra = ""
            if self.entity_mode:
                eidx = self._entity_at(r, c)
                if eidx >= 0:
                    extra = f"  entity={self._entity_name(eidx)}"
            app.draw_text(surface,
                          f"({c}, {r})  tile={tid} ({tname})  "
                          f"size={self.map_w}x{self.map_h}  "
                          f"zoom={self.zoom:.1f}x{extra}",
                          8, sh - STATUS_H + 5, COL_TEXT_DIM, app.font_sm)
        if self._status_timer > 0:
            alpha = min(1.0, self._status_timer * 2) * 255
            toast_surf = app.font.render(self._status, True, COL_ACCENT2)
            toast_surf.set_alpha(int(alpha))
            surface.blit(toast_surf, (sw // 2 - toast_surf.get_width() // 2,
                                      sh - STATUS_H - 30))

    # -- Text input overlay ----------------------------------------

    def _draw_text_input(self, surface: pygame.Surface, app: App) -> None:
        sw, sh = surface.get_size()
        overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 160))
        surface.blit(overlay, (0, 0))

        bw, bh = 420, 80
        bx = (sw - bw) // 2
        by = (sh - bh) // 2
        pygame.draw.rect(surface, COL_PANEL, (bx, by, bw, bh),
                         border_radius=8)
        pygame.draw.rect(surface, COL_ACCENT, (bx, by, bw, bh), 2,
                         border_radius=8)
        app.draw_text(surface, self.text_input_label,
                      bx + 12, by + 10, COL_TEXT_DIM, app.font_sm)
        field_rect = pygame.Rect(bx + 12, by + 32, bw - 24, 28)
        pygame.draw.rect(surface, (20, 20, 24), field_rect, border_radius=4)
        pygame.draw.rect(surface, COL_ACCENT, field_rect, 1, border_radius=4)
        app.draw_text(surface, self.text_input_buffer + "|",
                      field_rect.x + 6, field_rect.y + 6, COL_TEXT, app.font)
        app.draw_text(surface, "Enter to confirm  |  Esc to cancel",
                      bx + 12, by + bh - 18, COL_TEXT_DIM, app.font_sm)

    # -- Zone picker overlay ---------------------------------------

    def _draw_zone_picker(self, surface: pygame.Surface, app: App) -> None:
        sw, sh = surface.get_size()
        overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        surface.blit(overlay, (0, 0))

        px, py = 200, 80
        pw, ph = 560, sh - 160
        pygame.draw.rect(surface, COL_PANEL, (px, py, pw, ph),
                         border_radius=10)
        pygame.draw.rect(surface, COL_ACCENT, (px, py, pw, ph), 2,
                         border_radius=10)
        app.draw_text(surface, "Select Zone  (Esc/Tab to close)",
                      px + 16, py + 12, COL_ACCENT, app.font)

        item_h = 32
        clip = pygame.Rect(px + 8, py + 40, pw - 16, ph - 52)
        for i, z in enumerate(self._zone_list):
            iy = py + 40 + i * item_h - self._zone_picker_scroll
            if iy + item_h < clip.y or iy > clip.y + clip.h:
                continue
            hover_color = COL_PANEL_LITE if z == self.zone_name else COL_PANEL
            mx, my = app.mouse_pos()
            if clip.x < mx < clip.x + clip.w and iy < my < iy + item_h:
                hover_color = COL_PANEL_LITE
            item_rect = pygame.Rect(px + 8, iy, pw - 16, item_h - 2)
            pygame.draw.rect(surface, hover_color, item_rect, border_radius=4)
            text_color = COL_ACCENT if z == self.zone_name else COL_TEXT
            app.draw_text(surface, z, px + 20, iy + 8, text_color, app.font)

    # ==============================================================
    #  PORTAL WIZARD DRAWING
    # ==============================================================

    def _draw_wizard(self, surface: pygame.Surface, app: App) -> None:
        wiz = self._wizard
        if not wiz:
            return

        sw, sh = surface.get_size()
        overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        surface.blit(overlay, (0, 0))

        if wiz.step == PortalWizard.STEP_ENTRY_DIR:
            self._draw_wizard_dir_step(surface, app, wiz, "entry")
        elif wiz.step == PortalWizard.STEP_DEST_ZONE:
            self._draw_wizard_zone_step(surface, app, wiz)
        elif wiz.step == PortalWizard.STEP_DEST_TILE:
            self._draw_wizard_tile_step(surface, app, wiz)

    def _draw_wizard_dir_step(self, surface: pygame.Surface, app: App,
                              wiz: PortalWizard, which: str) -> None:
        """Draw direction picker (step 1)."""
        sw, sh = surface.get_size()
        panel_w, panel_h = 460, 220
        px = (sw - panel_w) // 2
        py = (sh - panel_h) // 2

        pygame.draw.rect(surface, COL_PANEL, (px, py, panel_w, panel_h),
                         border_radius=10)
        pygame.draw.rect(surface, COL_PORTAL, (px, py, panel_w, panel_h), 2,
                         border_radius=10)

        app.draw_text(surface, "Portal Wizard  --  Step 1 of 3",
                      px + 16, py + 12, COL_PORTAL, app.font)

        sr, sc = wiz.source_tile
        app.draw_text(surface,
                      f"Which direction should the player walk OUT",
                      px + 16, py + 38, COL_TEXT, app.font_sm)
        app.draw_text(surface,
                      f"of the portal at ({sc}, {sr})?",
                      px + 16, py + 54, COL_TEXT, app.font_sm)
        app.draw_text(surface,
                      "This is the walk-out direction on THIS side.",
                      px + 16, py + 74, COL_TEXT_DIM, app.font_sm)

        btn_w, btn_h = 90, 50
        btn_y = py + 100
        gap = 10
        total_w = 4 * btn_w + 3 * gap
        bx_start = px + (panel_w - total_w) // 2
        mx, my = app.mouse_pos()

        current = wiz.entry_dir if which == "entry" else wiz.exit_dir

        for i, d in enumerate(DIRECTIONS):
            bx = bx_start + i * (btn_w + gap)
            is_hover = bx <= mx <= bx + btn_w and btn_y <= my <= btn_y + btn_h
            is_selected = (d == current)

            bg = COL_PANEL_LITE if is_hover else COL_PANEL
            if is_selected:
                bg = (70, 50, 90)
            pygame.draw.rect(surface, bg, (bx, btn_y, btn_w, btn_h),
                             border_radius=6)
            border_col = COL_PORTAL if is_selected else COL_PANEL_LITE
            pygame.draw.rect(surface, border_col,
                             (bx, btn_y, btn_w, btn_h), 2, border_radius=6)

            arrow = DIR_ARROWS[d]
            app.draw_text(surface, f"{arrow} {d.title()}",
                          bx + 8, btn_y + 16, COL_TEXT, app.font)

        app.draw_text(surface, "Esc to cancel",
                      px + 16, py + panel_h - 26, COL_TEXT_DIM, app.font_sm)

    def _draw_wizard_zone_step(self, surface: pygame.Surface, app: App,
                               wiz: PortalWizard) -> None:
        """Draw destination zone picker (step 2)."""
        sw, sh = surface.get_size()
        panel_w, panel_h = 460, 420
        px = (sw - panel_w) // 2
        py = (sh - panel_h) // 2

        pygame.draw.rect(surface, COL_PANEL, (px, py, panel_w, panel_h),
                         border_radius=10)
        pygame.draw.rect(surface, COL_PORTAL, (px, py, panel_w, panel_h), 2,
                         border_radius=10)

        app.draw_text(surface, "Portal Wizard  --  Step 2 of 3",
                      px + 16, py + 12, COL_PORTAL, app.font)
        app.draw_text(surface, "Select destination zone:",
                      px + 16, py + 36, COL_TEXT, app.font_sm)

        item_h = 36
        list_y = py + 60
        mx, my = app.mouse_pos()
        clip_bottom = py + panel_h - 40

        for i, z in enumerate(wiz.zone_list):
            iy = list_y + i * item_h - wiz.zone_scroll
            if iy + item_h < list_y or iy > clip_bottom:
                continue

            is_hover = (px + 10 < mx < px + panel_w - 10
                        and iy < my < iy + item_h)
            bg = COL_PANEL_LITE if is_hover else COL_PANEL
            if z == wiz.dest_zone:
                bg = (60, 40, 80)

            item_rect = pygame.Rect(px + 10, iy, panel_w - 20, item_h - 3)
            pygame.draw.rect(surface, bg, item_rect, border_radius=4)

            text_col = COL_PORTAL if z == wiz.dest_zone else COL_TEXT
            app.draw_text(surface, z, px + 22, iy + 10, text_col, app.font)

        app.draw_text(surface, "Esc to cancel  |  Scroll to browse",
                      px + 16, py + panel_h - 26, COL_TEXT_DIM, app.font_sm)

    def _draw_wizard_tile_step(self, surface: pygame.Surface, app: App,
                               wiz: PortalWizard) -> None:
        """Draw dest zone map + click-to-place + exit direction picker."""
        if not wiz.dest_tiles:
            sw, sh = surface.get_size()
            app.draw_text(surface, f"Could not load '{wiz.dest_zone}'",
                          sw // 2 - 80, sh // 2, COL_DANGER, app.font)
            return

        sw, sh = surface.get_size()

        # -- Left side: destination zone tile map ------------------
        self._draw_dest_map(surface, app, wiz)

        # -- Right panel: direction picker + done button -----------
        panel_x = sw - 200
        pygame.draw.rect(surface, COL_PANEL,
                         (panel_x, 0, 200, sh))
        pygame.draw.line(surface, COL_PANEL_LITE,
                         (panel_x, 0), (panel_x, sh))

        app.draw_text(surface, "Step 3 of 3",
                      panel_x + 12, 10, COL_PORTAL, app.font)
        app.draw_text(surface, f"Zone: {wiz.dest_zone}",
                      panel_x + 12, 30, COL_ACCENT, app.font_sm)
        app.draw_text(surface, "Click map to pick",
                      panel_x + 12, 50, COL_TEXT_DIM, app.font_sm)
        app.draw_text(surface, "target tile.",
                      panel_x + 12, 66, COL_TEXT_DIM, app.font_sm)

        if wiz.dest_tile:
            dr, dc = wiz.dest_tile
            app.draw_text(surface, f"Target: ({dc}, {dr})",
                          panel_x + 12, 100, COL_SUCCESS, app.font)
        else:
            app.draw_text(surface, "Target: (none)",
                          panel_x + 12, 100, COL_TEXT_DIM, app.font)

        app.draw_text(surface, "Exit direction",
                      panel_x + 12, 140, COL_TEXT, app.font_sm)
        app.draw_text(surface, "(walk-out on dest):",
                      panel_x + 12, 156, COL_TEXT_DIM, app.font_sm)

        dir_panel_x = panel_x + 10
        dir_panel_y = 200
        btn_w, btn_h = 80, 40
        gap = 8
        mx, my = app.mouse_pos()

        for i, d in enumerate(DIRECTIONS):
            by = dir_panel_y + i * (btn_h + gap)
            is_hover = (dir_panel_x <= mx <= dir_panel_x + btn_w
                        and by <= my <= by + btn_h)
            is_selected = (d == wiz.exit_dir)

            bg = COL_PANEL_LITE if is_hover else COL_PANEL
            if is_selected:
                bg = (60, 40, 80)
            pygame.draw.rect(surface, bg, (dir_panel_x, by, btn_w, btn_h),
                             border_radius=6)
            border_col = COL_PORTAL if is_selected else COL_PANEL_LITE
            pygame.draw.rect(surface, border_col,
                             (dir_panel_x, by, btn_w, btn_h), 2,
                             border_radius=6)
            arrow = DIR_ARROWS[d]
            app.draw_text(surface, f"{arrow} {d.title()}",
                          dir_panel_x + 6, by + 12, COL_TEXT, app.font_sm)

        # Done button
        done_y = dir_panel_y + 4 * (btn_h + gap) + 20
        done_w = 120
        done_enabled = wiz.dest_tile is not None
        done_bg = (40, 120, 60) if done_enabled else (50, 50, 55)
        is_done_hover = (dir_panel_x <= mx <= dir_panel_x + done_w
                         and done_y <= my <= done_y + 44)
        if is_done_hover and done_enabled:
            done_bg = (50, 160, 80)

        pygame.draw.rect(surface, done_bg,
                         (dir_panel_x, done_y, done_w, 44),
                         border_radius=8)
        pygame.draw.rect(surface, COL_SUCCESS if done_enabled else COL_PANEL_LITE,
                         (dir_panel_x, done_y, done_w, 44), 2,
                         border_radius=8)
        label = "Create Portal" if not wiz.editing else "Update Portal"
        app.draw_text(surface, label,
                      dir_panel_x + 8, done_y + 14,
                      COL_TEXT if done_enabled else COL_TEXT_DIM, app.font_sm)

        app.draw_text(surface, "Mid-click: pan",
                      panel_x + 12, sh - 50, COL_TEXT_DIM, app.font_sm)
        app.draw_text(surface, "Scroll: zoom  Esc: cancel",
                      panel_x + 12, sh - 34, COL_TEXT_DIM, app.font_sm)

    def _draw_dest_map(self, surface: pygame.Surface, app: App,
                       wiz: PortalWizard) -> None:
        """Draw the destination zone's tile map for picking."""
        if not wiz.dest_tiles:
            return

        sw, sh = surface.get_size()
        map_area_w = sw - 200

        ts = int(TILE_SIZE * wiz.dest_zoom)
        if ts < 1:
            return

        for r in range(wiz.dest_map_h):
            for c in range(wiz.dest_map_w):
                sx, sy = self._dest_world_to_screen(
                    c * TILE_SIZE, r * TILE_SIZE, wiz)
                if sx + ts < 0 or sy + ts < 0 or sx > map_area_w or sy > sh:
                    continue
                tile_id = wiz.dest_tiles[r][c]
                color = TILE_COLORS.get(tile_id, (120, 120, 120))
                rect = pygame.Rect(sx, sy, ts, ts)
                pygame.draw.rect(surface, color, rect)
                if ts >= 8:
                    pygame.draw.rect(surface, COL_GRID, rect, 1)

        # Draw existing portals on this zone
        for p in wiz.dest_portals:
            for tile in p["tiles"]:
                r, c = tile
                sx, sy = self._dest_world_to_screen(
                    c * TILE_SIZE, r * TILE_SIZE, wiz)
                center = (sx + ts // 2, sy + ts // 2)
                radius = max(3, ts // 4)
                pygame.draw.circle(surface, (160, 60, 180), center, radius)
                if ts >= 12:
                    lbl = p["target_zone"][:5]
                    app.draw_text(surface, lbl,
                                  sx + 2, sy + ts + 1,
                                  COL_TEXT_DIM, app.font_sm)

        # Highlight selected tile
        if wiz.dest_tile:
            dr, dc = wiz.dest_tile
            sx, sy = self._dest_world_to_screen(
                dc * TILE_SIZE, dr * TILE_SIZE, wiz)
            sel_rect = pygame.Rect(sx, sy, ts, ts)
            pygame.draw.rect(surface, COL_SUCCESS, sel_rect, 3)
            arrow = DIR_ARROWS.get(wiz.exit_dir, "?")
            app.draw_text(surface, arrow,
                          sx + ts // 2 - 4, sy + ts // 2 - 6,
                          COL_SUCCESS, app.font)

        # Hover highlight
        if wiz._dest_hover and wiz._dest_hover != wiz.dest_tile:
            hr, hc = wiz._dest_hover
            sx, sy = self._dest_world_to_screen(
                hc * TILE_SIZE, hr * TILE_SIZE, wiz)
            hover_rect = pygame.Rect(sx, sy, ts, ts)
            hover_surf = pygame.Surface((ts, ts), pygame.SRCALPHA)
            hover_surf.fill((255, 255, 255, 50))
            surface.blit(hover_surf, (sx, sy))
            pygame.draw.rect(surface, (255, 255, 255), hover_rect, 1)

        # Zone title bar at top of map area
        title_bg = pygame.Surface((map_area_w, 28), pygame.SRCALPHA)
        title_bg.fill((30, 30, 34, 200))
        surface.blit(title_bg, (0, 0))
        app.draw_text(surface,
                      f"Destination: {wiz.dest_zone}  "
                      f"({wiz.dest_map_w}x{wiz.dest_map_h})",
                      8, 6, COL_ACCENT, app.font_sm)
