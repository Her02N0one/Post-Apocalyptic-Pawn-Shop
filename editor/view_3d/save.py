"""editor/view_3d/save.py — Zone JSON serialization for Zone3DEditor."""

from __future__ import annotations

import json
from typing import Any

import core.paths as _core_paths


class SaveMixin:
    """Save zone data to JSON."""

    def _save(self) -> None:
        self._save_zone_json()
        self.dirty = False

    def _save_zone_json(self) -> None:
        zone = self.zone
        path = _core_paths.ZONES_DIR / f"{zone.name}.json"
        data: dict[str, Any] = {}
        data["anchor"] = list(zone.anchor)
        data["first_person"] = zone.first_person
        data["tiles"] = zone.tiles
        data["rotations"] = zone.rotations
        data["floor_heights"] = zone.floor_heights
        data["ceil_heights"] = zone.ceil_heights
        data["floor_textures"] = zone.floor_textures
        data["ceil_textures"] = zone.ceil_textures
        data["wall_textures"] = zone.wall_textures
        data["face_textures"] = zone.face_textures
        data["light_levels"] = zone.light_levels

        # Only persist wall_segments if any cell has non-empty segments
        if hasattr(zone, "wall_segments") and zone.wall_segments:
            has_any = any(
                any(any(face for face in cell) for cell in row)
                for row in zone.wall_segments
            )
            if has_any:
                data["wall_segments"] = zone.wall_segments

        # Step-wall textures (only if any non-empty)
        def _has_step_tex(grid: list) -> bool:
            return any(any(any(f for f in cell) for cell in row) for row in grid)

        def _has_step_seg(grid: list) -> bool:
            return any(any(any(face for face in cell) for cell in row) for row in grid)

        if hasattr(zone, "floor_step_textures") and zone.floor_step_textures:
            if _has_step_tex(zone.floor_step_textures):
                data["floor_step_textures"] = zone.floor_step_textures
        if hasattr(zone, "ceil_step_textures") and zone.ceil_step_textures:
            if _has_step_tex(zone.ceil_step_textures):
                data["ceil_step_textures"] = zone.ceil_step_textures
        if hasattr(zone, "floor_step_segments") and zone.floor_step_segments:
            if _has_step_seg(zone.floor_step_segments):
                data["floor_step_segments"] = zone.floor_step_segments
        if hasattr(zone, "ceil_step_segments") and zone.ceil_step_segments:
            if _has_step_seg(zone.ceil_step_segments):
                data["ceil_step_segments"] = zone.ceil_step_segments
        if hasattr(zone, "upper_wall_height") and zone.upper_wall_height:
            if any(any(v > 0 for v in row) for row in zone.upper_wall_height):
                data["upper_wall_height"] = zone.upper_wall_height

        data["entities"] = zone.entities
        portals_out = []
        for p in zone.portals:
            portals_out.append({
                "tiles": [list(t) for t in p.tiles],
                "target_zone": p.target_zone,
                "target_pos": [p.target_row, p.target_col],
                "exit_direction": p.exit_direction,
            })
        data["portals"] = portals_out
        if zone.overlay_walls:
            ov_out = []
            for ow in zone.overlay_walls:
                ov_out.append({
                    "x1": ow.x1, "y1": ow.y1,
                    "x2": ow.x2, "y2": ow.y2,
                    "texture": ow.texture,
                    "height_scale": ow.height_scale,
                    "transparent": ow.transparent,
                    "blocks": ow.blocks,
                })
            data["overlay_walls"] = ov_out
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
