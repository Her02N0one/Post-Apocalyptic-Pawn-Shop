"""editor/view_3d/undo.py — Undo/redo mixin for Zone3DEditor."""

from __future__ import annotations

import copy


class UndoMixin:
    """Provides snapshot-based undo/redo over mutable zone state."""

    _UNDO_MAX: int

    def _snapshot(self) -> dict:
        """Capture mutable zone state for undo."""
        z = self.zone
        return {
            "tiles": copy.deepcopy(z.tiles),
            "floor_heights": copy.deepcopy(z.floor_heights),
            "ceil_heights": copy.deepcopy(z.ceil_heights),
            "face_textures": copy.deepcopy(z.face_textures),
            "wall_textures": copy.deepcopy(z.wall_textures) if z.wall_textures else None,
            "floor_textures": copy.deepcopy(z.floor_textures) if z.floor_textures else None,
            "ceil_textures": copy.deepcopy(z.ceil_textures) if z.ceil_textures else None,
            "wall_segments": copy.deepcopy(z.wall_segments),
            "upper_wall_height": copy.deepcopy(z.upper_wall_height),
            "floor_step_textures": copy.deepcopy(z.floor_step_textures),
            "ceil_step_textures": copy.deepcopy(z.ceil_step_textures),
            "floor_step_segments": copy.deepcopy(z.floor_step_segments),
            "ceil_step_segments": copy.deepcopy(z.ceil_step_segments),
            "light_levels": copy.deepcopy(z.light_levels) if z.light_levels else None,
            "rotations": copy.deepcopy(z.rotations) if z.rotations else None,
            "entities": copy.deepcopy(z.entities) if z.entities else [],
            "boxes": copy.deepcopy(z.boxes) if z.boxes else [],
            "quads": copy.deepcopy(z.quads) if z.quads else [],
            "reflect_map": copy.deepcopy(z.reflect_map) if z.reflect_map else [],
            "curves": copy.deepcopy(z.curves) if z.curves else [],
            "floor_slope_dx": copy.deepcopy(z.floor_slope_dx) if z.floor_slope_dx else [],
            "floor_slope_dy": copy.deepcopy(z.floor_slope_dy) if z.floor_slope_dy else [],
            "floor_slope_div": copy.deepcopy(z.floor_slope_div) if z.floor_slope_div else [],
            "floor2_heights": copy.deepcopy(z.floor2_heights) if z.floor2_heights else [],
            "ceil2_heights": copy.deepcopy(z.ceil2_heights) if z.ceil2_heights else [],
            "floor2_textures": copy.deepcopy(z.floor2_textures) if z.floor2_textures else [],
            "ceil2_textures": copy.deepcopy(z.ceil2_textures) if z.ceil2_textures else [],
            "fog_density": copy.deepcopy(z.fog_density) if z.fog_density else [],
            "fog_color": copy.deepcopy(z.fog_color) if z.fog_color else [],
            "render_portals": copy.deepcopy(z.render_portals) if z.render_portals else [],
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
