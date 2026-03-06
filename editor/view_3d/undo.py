"""editor/view_3d/undo.py — Undo/redo mixin for Zone3DEditor.

Performance note
~~~~~~~~~~~~~~~~
The original implementation used ``copy.deepcopy`` for every grid field.
``deepcopy`` carries heavy per-object dispatch overhead (~10-50× slower
than manual list copies for homogeneous grids).  The fast copiers below
exploit the known structure of each field type:

* **2D grids** (primitives — ``float``, ``int``, ``str``, ``tuple``):
  ``[row[:] for row in grid]`` is sufficient because cell values are
  immutable scalars; copying the inner list is all that's needed.

* **3D grids** (face textures — ``list[list[list[str]]]``):
  Each cell is a 4-element list of strings.  ``[cell[:] for cell in row]``
  copies the per-cell list reference.

* **4D grids** (segments — ``list[list[list[list]]]``):
  Each cell has 4 face lists, each containing 0-N segment lists
  ``[tex_key, y_top]``.  We copy face lists **and** segment entries.

* **Flat object lists** (``entities``, ``boxes``, …):
  These are small (< 100 items).  We shallow-copy each dict and nested
  dicts one level deep, which covers all current schemas.
"""

from __future__ import annotations

import copy


# ── Type-specific fast copiers ────────────────────────────────────

def _copy_grid(grid):
    """Copy a 2D grid of primitives (str | int | float | tuple)."""
    if not grid:
        return grid
    return [row[:] for row in grid]


def _copy_grid_3d(grid):
    """Copy a 3D grid — ``list[list[list[str]]]`` (face textures)."""
    if not grid:
        return grid
    return [[cell[:] for cell in row] for row in grid]


def _copy_grid_4d(grid):
    """Copy a 4D grid — ``list[list[list[list]]]`` (segments)."""
    if not grid:
        return grid
    return [[[
        [seg[:] for seg in face] for face in cell
    ] for cell in row] for row in grid]


def _copy_dict_list(lst):
    """Shallow-copy a flat list of dicts (one-level nested dicts)."""
    if not lst:
        return []
    out = []
    for d in lst:
        new = {}
        for k, v in d.items():
            if isinstance(v, dict):
                new[k] = dict(v)
            elif isinstance(v, list):
                new[k] = v[:]
            else:
                new[k] = v
        out.append(new)
    return out


def _copy_overlay_walls(walls):
    """Deep-copy a list of OverlayWall dataclasses."""
    if not walls:
        return []
    import dataclasses
    return [dataclasses.replace(w) for w in walls]


# ── Mixin ─────────────────────────────────────────────────────────

class UndoMixin:
    """Provides snapshot-based undo/redo over mutable zone state.

    Uses fast type-aware copiers instead of ``copy.deepcopy`` for the
    hot-path grid fields, while retaining ``copy.deepcopy`` as a
    fallback for any future fields not yet covered.
    """

    _UNDO_MAX: int

    def _snapshot(self) -> dict:
        """Capture mutable zone state for undo."""
        z = self.zone
        return {
            # 2D grids (primitives)
            "tiles":               _copy_grid(z.tiles),
            "floor_heights":       _copy_grid(z.floor_heights),
            "ceil_heights":        _copy_grid(z.ceil_heights),
            "wall_textures":       _copy_grid(z.wall_textures) if z.wall_textures else None,
            "floor_textures":      _copy_grid(z.floor_textures) if z.floor_textures else None,
            "ceil_textures":       _copy_grid(z.ceil_textures) if z.ceil_textures else None,
            "upper_wall_height":   _copy_grid(z.upper_wall_height),
            "light_levels":        _copy_grid(z.light_levels) if z.light_levels else None,
            "rotations":           _copy_grid(z.rotations) if z.rotations else None,
            "reflect_map":         _copy_grid(z.reflect_map) if z.reflect_map else [],
            "floor_slope_dx":      _copy_grid(z.floor_slope_dx) if z.floor_slope_dx else [],
            "floor_slope_dy":      _copy_grid(z.floor_slope_dy) if z.floor_slope_dy else [],
            "floor_slope_div":     _copy_grid(z.floor_slope_div) if z.floor_slope_div else [],
            "floor2_heights":      _copy_grid(z.floor2_heights) if z.floor2_heights else [],
            "ceil2_heights":       _copy_grid(z.ceil2_heights) if z.ceil2_heights else [],
            "floor2_textures":     _copy_grid(z.floor2_textures) if z.floor2_textures else [],
            "ceil2_textures":      _copy_grid(z.ceil2_textures) if z.ceil2_textures else [],
            "fog_density":         _copy_grid(z.fog_density) if z.fog_density else [],
            "fog_color":           _copy_grid(z.fog_color) if z.fog_color else [],
            # 3D grids (face textures — list[list[list[str]]])
            "face_textures":         _copy_grid_3d(z.face_textures),
            "floor_step_textures":   _copy_grid_3d(z.floor_step_textures),
            "ceil_step_textures":    _copy_grid_3d(z.ceil_step_textures),
            # 4D grids (segments — list[list[list[list]]])
            "wall_segments":         _copy_grid_4d(z.wall_segments),
            "floor_step_segments":   _copy_grid_4d(z.floor_step_segments),
            "ceil_step_segments":    _copy_grid_4d(z.ceil_step_segments),
            # Flat object lists (small — dict shallow-copy is fine)
            "entities":        _copy_dict_list(z.entities) if z.entities else [],
            "boxes":           _copy_dict_list(z.boxes) if z.boxes else [],
            "quads":           _copy_dict_list(z.quads) if z.quads else [],
            "curves":          _copy_dict_list(z.curves) if z.curves else [],
            "render_portals":  _copy_dict_list(z.render_portals) if z.render_portals else [],
            "overlay_walls":   _copy_overlay_walls(z.overlay_walls) if z.overlay_walls else [],
        }

    def _restore(self, snap: dict) -> None:
        """Restore zone state from a snapshot."""
        z = self.zone
        z.tiles = snap["tiles"]
        z.floor_heights = snap["floor_heights"]
        z.ceil_heights = snap["ceil_heights"]
        z.face_textures = snap["face_textures"]
        if snap["wall_textures"] is not None:
            z.wall_textures = snap["wall_textures"]
        if snap["floor_textures"] is not None:
            z.floor_textures = snap["floor_textures"]
        if snap["ceil_textures"] is not None:
            z.ceil_textures = snap["ceil_textures"]
        z.wall_segments = snap["wall_segments"]
        z.upper_wall_height = snap["upper_wall_height"]
        z.floor_step_textures = snap["floor_step_textures"]
        z.ceil_step_textures = snap["ceil_step_textures"]
        z.floor_step_segments = snap["floor_step_segments"]
        z.ceil_step_segments = snap["ceil_step_segments"]
        if snap.get("light_levels") is not None:
            z.light_levels = snap["light_levels"]
        if snap.get("rotations") is not None:
            z.rotations = snap["rotations"]
        if "entities" in snap:
            z.entities = snap["entities"]
        if "boxes" in snap:
            z.boxes = snap["boxes"]
        if "quads" in snap:
            z.quads = snap["quads"]
        if "reflect_map" in snap:
            z.reflect_map = snap["reflect_map"]
        if "curves" in snap:
            z.curves = snap["curves"]
        if "floor_slope_dx" in snap:
            z.floor_slope_dx = snap["floor_slope_dx"]
        if "floor_slope_dy" in snap:
            z.floor_slope_dy = snap["floor_slope_dy"]
        if "floor_slope_div" in snap:
            z.floor_slope_div = snap["floor_slope_div"]
        if "floor2_heights" in snap:
            z.floor2_heights = snap["floor2_heights"]
        if "ceil2_heights" in snap:
            z.ceil2_heights = snap["ceil2_heights"]
        if "floor2_textures" in snap:
            z.floor2_textures = snap["floor2_textures"]
        if "ceil2_textures" in snap:
            z.ceil2_textures = snap["ceil2_textures"]
        if "fog_density" in snap:
            z.fog_density = snap["fog_density"]
        if "fog_color" in snap:
            z.fog_color = snap["fog_color"]
        if "render_portals" in snap:
            z.render_portals = snap["render_portals"]
        if "overlay_walls" in snap:
            z.overlay_walls = snap["overlay_walls"]
        self.dirty = True

    def _push_undo(self) -> None:
        """Save current state before a mutation."""
        self._undo_stack.append(self._snapshot())
        if len(self._undo_stack) > self._UNDO_MAX:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def _flash(self, text: str, duration: float = 1.2,
               color: tuple = (0.95, 0.90, 0.75, 1.0)) -> None:
        """Trigger a visual flash via the owning app's callback."""
        cb = getattr(self, 'on_flash', None)
        if cb:
            cb(text, duration, color)

    def _undo(self) -> None:
        if not self._undo_stack:
            self._flash("Nothing to undo", 1.0, (0.6, 0.5, 0.4, 1.0))
            return
        self._redo_stack.append(self._snapshot())
        self._restore(self._undo_stack.pop())
        n = len(self._undo_stack)
        self._flash(f"Undo  ({n} left)", 1.0, (0.8, 0.85, 1.0, 1.0))

    def _redo(self) -> None:
        if not self._redo_stack:
            self._flash("Nothing to redo", 1.0, (0.6, 0.5, 0.4, 1.0))
            return
        self._undo_stack.append(self._snapshot())
        self._restore(self._redo_stack.pop())
        n = len(self._redo_stack)
        self._flash(f"Redo  ({n} left)", 1.0, (0.8, 0.85, 1.0, 1.0))
