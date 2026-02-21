"""editor/state.py — Central editor state, zone I/O, undo/redo.

Stores all mutable state for the editor: current zone data, selection
state, view state, tool modes.  Keeps the rest of the code stateless.
"""

from __future__ import annotations

import json
from collections import deque
from copy import deepcopy
from pathlib import Path
from typing import Any

from core.paths import ZONES_DIR, DATA_DIR, TEMPLATES_DIR, ROOMS_DIR
from editor.entity_defs import EntityDef, EDPortal, EDSprite, EDIdentity, EDPosition

import re as _re


def _sanitize_name(name: str) -> str:
    """Strip path traversal and dangerous chars from a user-supplied name.

    Allows only alphanumerics, underscores, hyphens, and spaces.
    Collapses multiple spaces, strips leading/trailing whitespace.
    """
    name = name.replace("..", "").replace("/", "").replace("\\", "")
    name = _re.sub(r"[^\w\s-]", "", name)
    name = _re.sub(r"\s+", " ", name).strip()
    return name or "untitled"


def _safe_zone_path(name: str) -> Path:
    """Return a safe path inside ZONES_DIR for a zone name.

    Raises ValueError if the resolved path escapes ZONES_DIR.
    """
    clean = _sanitize_name(name)
    path = (ZONES_DIR / f"{clean}.json").resolve()
    if not str(path).startswith(str(ZONES_DIR.resolve())):
        raise ValueError(f"Invalid zone name: {name!r}")
    return path


# ── Tools ────────────────────────────────────────────────────────────

class Tool:
    SELECT  = "select"       # click to inspect tile / select entity
    BRUSH   = "brush"
    ERASER  = "eraser"
    FILL    = "fill"
    PICKER  = "picker"       # eyedropper


# ── Undo snapshot ────────────────────────────────────────────────────

class Snapshot:
    """Full state snapshot for undo/redo."""
    __slots__ = ("tiles", "rotations", "entities")

    def __init__(self, tiles, rotations, entities):
        self.tiles = tiles
        self.rotations = rotations
        self.entities = entities


class History:
    """Undo/redo stack."""

    def __init__(self, max_depth: int = 80):
        self._undo: deque[Snapshot] = deque(maxlen=max_depth)
        self._redo: deque[Snapshot] = deque(maxlen=max_depth)

    def push(self, state: "EditorState"):
        snap = Snapshot(
            deepcopy(state.tiles),
            deepcopy(state.rotations),
            deepcopy(state.entities),
        )
        self._undo.append(snap)
        self._redo.clear()

    def undo(self, state: "EditorState") -> bool:
        if len(self._undo) <= 1:
            return False
        current = self._undo.pop()
        self._redo.append(current)
        prev = self._undo[-1]
        state.tiles = deepcopy(prev.tiles)
        state.rotations = deepcopy(prev.rotations)
        state.entities = deepcopy(prev.entities)
        state.map_h = len(state.tiles)
        state.map_w = len(state.tiles[0]) if state.tiles else 0
        return True

    def redo(self, state: "EditorState") -> bool:
        if not self._redo:
            return False
        snap = self._redo.pop()
        self._undo.append(snap)
        state.tiles = deepcopy(snap.tiles)
        state.rotations = deepcopy(snap.rotations)
        state.entities = deepcopy(snap.entities)
        state.map_h = len(state.tiles)
        state.map_w = len(state.tiles[0]) if state.tiles else 0
        return True

    def clear(self):
        self._undo.clear()
        self._redo.clear()

    @property
    def can_undo(self) -> bool:
        return len(self._undo) > 1

    @property
    def can_redo(self) -> bool:
        return len(self._redo) > 0


# ── Editor State ─────────────────────────────────────────────────────

class EditorState:
    """All mutable editor state in one object."""

    def __init__(self):
        # Zone data
        self.zone_name: str = ""
        self.tiles: list[list[str]] = []
        self.rotations: list[list[int]] = []   # parallel grid: 0-3 per cell
        self.map_w: int = 0
        self.map_h: int = 0
        self.entities: list[EntityDef] = []
        self.first_person: bool = False

        # View
        self.cam_x: float = 0.0
        self.cam_y: float = 0.0
        self.zoom: float = 1.0
        self.show_grid: bool = True
        self.show_minimap: bool = True

        # Tool state
        self.tool: str = Tool.BRUSH
        self.selected_tile: str = "grass"
        self.pending_rotation: int = 0   # rotation for next placed tile (0-3)
        self.brush_size: int = 1

        # Entity state
        self.selected_entity: int = -1
        self.entity_dragging: bool = False
        self.pending_prefab: str = ""  # name of prefab/forge ready to place

        # Panning
        self._panning: bool = False
        self._pan_start: tuple[int, int] = (0, 0)
        self._cam_start: tuple[float, float] = (0.0, 0.0)

        # Hover
        self.hover_tile: tuple[int, int] | None = None

        # Toast
        self.toast_msg: str = ""
        self.toast_timer: float = 0.0

        # History
        self.history = History()

        # Dirty flag
        self.dirty: bool = False

        # Zone navigation
        self.zone_history: list[str] = []
        self.zone_history_idx: int = -1

    # ── Zone I/O ────────────────────────────────────────────────

    def load_zone(self, name: str) -> bool:
        """Load zone from JSON. Returns True on success."""
        try:
            path = _safe_zone_path(name)
        except ValueError:
            self.toast(f"Invalid zone name: {name}")
            return False
        if not path.exists():
            self.toast(f"Zone not found: {name}")
            return False
        try:
            with open(path) as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            self.toast(f"Error loading {name}: {e}")
            return False

        self.zone_name = name
        self.tiles = data.get("tiles", [["grass"] * 30 for _ in range(20)])
        self.map_h = len(self.tiles)
        self.map_w = len(self.tiles[0]) if self.tiles else 0

        # Rotation grid (parallel to tiles, default all 0)
        raw_rot = data.get("rotations")
        if raw_rot and len(raw_rot) == self.map_h:
            self.rotations = raw_rot
        else:
            self.rotations = [[0] * self.map_w for _ in range(self.map_h)]

        self.entities = [EntityDef.from_dict(e)
                        for e in data.get("entities", [])]
        self._portals_to_entities(data.get("portals", []))

        self.first_person = bool(data.get("first_person",
                                          data.get("interior", False)))

        # Reset selection
        self.selected_entity = -1
        self.entity_dragging = False

        # Center camera
        self.cam_x = -(self.map_w * 32) / 2
        self.cam_y = -(self.map_h * 32) / 2

        # History
        self.history.clear()
        self.history.push(self)
        self.dirty = False
        self.toast(f"Loaded: {name}")

        # Track navigation history
        if (not self.zone_history
                or self.zone_history[self.zone_history_idx] != name):
            # Trim forward history
            self.zone_history = self.zone_history[:self.zone_history_idx + 1]
            self.zone_history.append(name)
            self.zone_history_idx = len(self.zone_history) - 1

        return True

    def load_zone_data(self, data: dict) -> bool:
        """Load zone from an in-memory dict (e.g. baked template)."""
        self.zone_name = data.get("name", "untitled")
        self.tiles = data.get("tiles", [["grass"] * 30 for _ in range(20)])
        self.map_h = len(self.tiles)
        self.map_w = len(self.tiles[0]) if self.tiles else 0

        raw_rot = data.get("rotations")
        if raw_rot and len(raw_rot) == self.map_h:
            self.rotations = raw_rot
        else:
            self.rotations = [[0] * self.map_w for _ in range(self.map_h)]

        self.entities = [EntityDef.from_dict(e)
                        for e in data.get("entities", [])]
        self._portals_to_entities(data.get("portals", []))

        self.first_person = bool(data.get("first_person", False))

        self.selected_entity = -1
        self.entity_dragging = False
        self.cam_x = -(self.map_w * 32) / 2
        self.cam_y = -(self.map_h * 32) / 2
        self.history.clear()
        self.history.push(self)
        self.dirty = False
        self.toast(f"Loaded: {self.zone_name} (from data)")
        return True

    def save_zone(self) -> bool:
        """Save current zone to JSON. Returns True on success."""
        if not self.zone_name:
            self.toast("No zone name set")
            return False

        data = self.get_zone_data()
        path = _safe_zone_path(self.zone_name)
        try:
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
        except IOError as e:
            self.toast(f"Save error: {e}")
            return False

        self.dirty = False
        self.toast(f"Saved: {path.name}")
        return True

    def get_zone_data(self) -> dict[str, Any]:
        """Return the current zone as a plain dict (for export)."""
        regular, portals = self._split_entities()
        data: dict[str, Any] = {
            "name": self.zone_name,
            "width": self.map_w,
            "height": self.map_h,
            "anchor": [0, 0],
            "tiles": self.tiles,
            "rotations": self.rotations,
            "portals": portals,
            "entities": regular,
        }
        if self.first_person:
            data["first_person"] = True
        return data

    def new_zone(self, name: str, width: int = 30, height: int = 20):
        """Create a blank zone."""
        self.zone_name = _sanitize_name(name)
        self.map_w = width
        self.map_h = height
        self.tiles = [["grass"] * width for _ in range(height)]
        self.rotations = [[0] * width for _ in range(height)]
        self.entities: list[EntityDef] = []
        self.first_person = False
        self.selected_entity = -1
        self.pending_rotation = 0
        self.cam_x = -(width * 32) / 2
        self.cam_y = -(height * 32) / 2
        self.history.clear()
        self.history.push(self)
        self.dirty = False
        self.toast(f"Created: {name} ({width}x{height})")

    def resize_zone(self, new_w: int, new_h: int):
        """Resize zone, preserving existing tiles."""
        new_w = max(5, min(new_w, 200))
        new_h = max(5, min(new_h, 200))
        if new_w == self.map_w and new_h == self.map_h:
            return
        new_tiles = [["grass"] * new_w for _ in range(new_h)]
        new_rots = [[0] * new_w for _ in range(new_h)]
        for r in range(min(new_h, self.map_h)):
            for c in range(min(new_w, self.map_w)):
                new_tiles[r][c] = self.tiles[r][c]
                new_rots[r][c] = self.rotations[r][c] if self.rotations else 0
        self.tiles = new_tiles
        self.rotations = new_rots
        self.map_w = new_w
        self.map_h = new_h
        self.push_undo()
        self.toast(f"Resized to {new_w}x{new_h}")

    def rename_zone(self, new_name: str):
        """Rename the current zone (updates zone_name, saves to new file)."""
        new_name = _sanitize_name(new_name)
        if not new_name or new_name == self.zone_name:
            return
        old_path = _safe_zone_path(self.zone_name) if self.zone_name else None
        self.zone_name = new_name
        self.save_zone()
        # Remove old file if it was different
        if old_path and old_path.exists() and old_path.stem != new_name:
            try:
                old_path.unlink()
                self.toast(f"Renamed → {new_name} (old file removed)")
            except OSError:
                self.toast(f"Renamed → {new_name}")
        else:
            self.toast(f"Renamed → {new_name}")

    # ── Painting ────────────────────────────────────────────────

    def paint(self, row: int, col: int, tile_id: str | None = None,
              rotation: int | None = None):
        tid = tile_id if tile_id is not None else self.selected_tile
        rot = rotation if rotation is not None else self.pending_rotation
        half = self.brush_size // 2
        for rr in range(row - half, row - half + self.brush_size):
            for cc in range(col - half, col - half + self.brush_size):
                if 0 <= rr < self.map_h and 0 <= cc < self.map_w:
                    self.tiles[rr][cc] = tid
                    self.rotations[rr][cc] = rot

    def erase(self, row: int, col: int):
        """Erase to the zone's default floor tile."""
        self.paint(row, col, self.erase_tile, rotation=0)

    @property
    def erase_tile(self) -> str:
        """The tile ID used for erasing — defaults to 'grass'."""
        return getattr(self, '_erase_tile', 'grass')

    @erase_tile.setter
    def erase_tile(self, value: str):
        self._erase_tile = value

    def flood_fill(self, row: int, col: int):
        target = self.tiles[row][col]
        if target == self.selected_tile:
            return
        rot = self.pending_rotation
        stack = [(row, col)]
        visited = set()
        while stack:
            r, c = stack.pop()
            if (r, c) in visited:
                continue
            if not (0 <= r < self.map_h and 0 <= c < self.map_w):
                continue
            if self.tiles[r][c] != target:
                continue
            visited.add((r, c))
            self.tiles[r][c] = self.selected_tile
            self.rotations[r][c] = rot
            stack.extend([(r-1, c), (r+1, c), (r, c-1), (r, c+1)])
        self.toast(f"Filled {len(visited)} tiles")

    # ── Entity helpers ──────────────────────────────────────────

    def _split_entities(self) -> tuple[list[dict], list[dict]]:
        """Split entities into (regular_dicts, portal_dicts) for JSON save.

        Portal entities are serialised into the ``"portals"`` JSON array
        (backward-compatible with the runtime), while non-portal entities
        go into the ``"entities"`` array.
        """
        regular: list[dict] = []
        portals: list[dict] = []
        for ent in self.entities:
            if ent.portal is not None:
                portals.append({
                    "tiles": [list(t) for t in ent.portal.tiles],
                    "target_zone": ent.portal.target_zone,
                    "target_pos": list(ent.portal.target_pos),
                    "exit_direction": ent.portal.exit_direction,
                })
            else:
                regular.append(ent.to_dict())
        return regular, portals

    @property
    def portals(self) -> list[EntityDef]:
        """Return entities that have a portal component."""
        return [e for e in self.entities if e.portal is not None]

    def entity_at(self, row: int, col: int) -> int:
        """Return index of entity near tile, or -1.

        Checks entity position proximity for regular entities, and
        also checks portal tile lists for portal entities.
        """
        for i, ent in enumerate(self.entities):
            # Portal entities: check all portal tiles
            if ent.portal is not None:
                for tile in ent.portal.tiles:
                    if len(tile) >= 2 and tile[0] == row and tile[1] == col:
                        return i
            # Regular proximity check
            ex, ey = ent.position.x, ent.position.y
            if abs(ex - (col + 0.5)) < 0.8 and abs(ey - (row + 0.5)) < 0.8:
                return i
        return -1

    def entity_name(self, idx: int) -> str:
        if 0 <= idx < len(self.entities):
            return self.entities[idx].display_name
        return ""

    def delete_entity(self, idx: int):
        if 0 <= idx < len(self.entities):
            self.entities.pop(idx)
            if self.selected_entity >= len(self.entities):
                self.selected_entity = -1
            self.push_undo()

    # ── Portal helpers ──────────────────────────────────────────

    def _portals_to_entities(self, portals: list[dict]):
        """Convert raw portal JSON dicts into portal entities."""
        for p in portals:
            tiles = [list(t) for t in p.get("tiles", [])]
            target_zone = p.get("target_zone", "")
            target_pos = list(p.get("target_pos", [0, 0]))
            exit_dir = p.get("exit_direction", "up")
            ent = EntityDef()
            ent.id = f"portal_{target_zone}_{len(self.entities)}"
            ent.prefab = "portal"
            if tiles:
                r, c = tiles[0]
                ent.position = EDPosition(x=float(c) + 0.5,
                                          y=float(r) + 0.5)
            ent.portal = EDPortal(tiles=tiles, target_zone=target_zone,
                                  target_pos=target_pos,
                                  exit_direction=exit_dir)
            ent.sprite = EDSprite(char="\u25A3", color=[200, 60, 220],
                                  layer=10)
            ent.identity = EDIdentity(
                name=f"Portal \u2192 {target_zone}", kind="portal")
            self.entities.append(ent)

    # ── History ─────────────────────────────────────────────────

    def push_undo(self):
        self.history.push(self)
        self.dirty = True

    def undo(self) -> bool:
        if self.history.undo(self):
            self.toast("Undo")
            self.dirty = True
            return True
        return False

    def redo(self) -> bool:
        if self.history.redo(self):
            self.toast("Redo")
            self.dirty = True
            return True
        return False

    # ── Toast ───────────────────────────────────────────────────

    def toast(self, msg: str, duration: float = 2.5):
        self.toast_msg = msg
        self.toast_timer = duration

    # ── Zone navigation ─────────────────────────────────────────

    def nav_back(self) -> str | None:
        """Return the previous zone name, or None."""
        if self.zone_history_idx > 0:
            self.zone_history_idx -= 1
            return self.zone_history[self.zone_history_idx]
        return None

    def nav_forward(self) -> str | None:
        """Return the next zone name, or None."""
        if self.zone_history_idx < len(self.zone_history) - 1:
            self.zone_history_idx += 1
            return self.zone_history[self.zone_history_idx]
        return None

    def connected_zones(self) -> list[str]:
        """Return unique portal target zone names."""
        seen: set[str] = set()
        result: list[str] = []
        for ent in self.entities:
            if ent.portal is None:
                continue
            tz = ent.portal.target_zone
            if tz and tz not in seen:
                seen.add(tz)
                result.append(tz)
        return result


# ── Helpers ──────────────────────────────────────────────────────────

from core.zones import list_zones   # re-export for backward compat  # noqa: F401


def list_loot_tables() -> list[str]:
    """Return list of loot table IDs from data/loot_tables.toml."""
    path = DATA_DIR / "loot_tables.toml"
    if not path.exists():
        return []
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore
        except ImportError:
            return []
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
        return sorted(data.get("tables", {}).keys())
    except (OSError, ValueError, KeyError):
        return []


def load_loot_tables() -> dict[str, Any]:
    """Load all loot table data."""
    path = DATA_DIR / "loot_tables.toml"
    if not path.exists():
        return {}
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore
        except ImportError:
            return {}
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
        return data.get("tables", {})
    except (OSError, ValueError, KeyError):
        return {}


def save_loot_tables(tables: dict[str, Any]) -> bool:
    """Save loot tables back to TOML."""
    def _q(s: str) -> str:
        """Escape a string for TOML double-quoted value."""
        return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")

    path = DATA_DIR / "loot_tables.toml"
    lines = ["# Loot tables — visual editor output",
             "# Each table has pools. Each pool rolls entries by weight.\n"]
    for table_id, table in sorted(tables.items()):
        desc = table.get("description", "")
        lines.append(f'[tables.{table_id}]')
        if desc:
            lines.append(f'description = "{_q(desc)}"')
        lines.append("")
        for pool in table.get("pools", []):
            lines.append(f'[[tables.{table_id}.pools]]')
            pname = pool.get("name", "loot")
            lines.append(f'name = "{_q(pname)}"')
            lines.append(f'rolls = {pool.get("rolls", 1)}')
            bonus = pool.get("bonus_rolls", 0)
            lines.append(f'bonus_rolls = {bonus}')
            lines.append("")
            for entry in pool.get("entries", []):
                lines.append(f'[[tables.{table_id}.pools.entries]]')
                lines.append(f'item = "{_q(entry.get("item", ""))}"')
                lines.append(f'weight = {entry.get("weight", 1)}')
                lines.append(f'min_count = {entry.get("min_count", 1)}')
                lines.append(f'max_count = {entry.get("max_count", 1)}')
                lines.append("")
        lines.append("")

    try:
        with open(path, "w") as f:
            f.write("\n".join(lines))
        return True
    except IOError:
        return False


def load_item_ids() -> list[str]:
    """Load all item IDs from data/items.toml."""
    path = DATA_DIR / "items.toml"
    if not path.exists():
        return []
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore
        except ImportError:
            return []
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
        return sorted(k for k in data.keys()
                      if isinstance(data[k], dict))
    except (OSError, ValueError, KeyError):
        return []
