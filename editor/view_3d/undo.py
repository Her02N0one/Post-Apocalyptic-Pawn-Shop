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
        self.dirty = True

    def _push_undo(self) -> None:
        """Save current state before a mutation."""
        self._undo_stack.append(self._snapshot())
        if len(self._undo_stack) > self._UNDO_MAX:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def _undo(self) -> None:
        if not self._undo_stack:
            return
        self._redo_stack.append(self._snapshot())
        self._restore(self._undo_stack.pop())

    def _redo(self) -> None:
        if not self._redo_stack:
            return
        self._undo_stack.append(self._snapshot())
        self._restore(self._redo_stack.pop())
