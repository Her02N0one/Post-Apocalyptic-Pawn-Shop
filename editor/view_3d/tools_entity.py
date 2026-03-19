"""editor/view_3d/tools_entity.py — Entity tool for Zone3DEditor.

Place, select, move, delete, and rotate entities in the 3D editor.

Actions:
  LMB on ground       Place entity of current palette type
  LMB on entity       Select it
  LMB (w/ selected)   Move selected entity to aimed position
  RMB on entity       Delete it
  RMB on ground       Deselect current entity
  Scroll              Cycle entity type palette
  Shift+Scroll        Rotate selected entity (8-dir snap)
  Delete / Backspace  Delete selected entity
  Escape              Deselect
"""

from __future__ import annotations

import math
import uuid

import pygame

from core.tiles import tile_def as _tile_def
from core.entity_defs import (
    entity_palette,
    get_entity_def,
    snap_angle_8dir,
)
from editor.view_3d.picking import _ray_vs_aabb, _ray_vs_obb


class EntityMixin:
    """Entity placement, selection, and manipulation."""

    # Current palette index
    _ent_type_idx: int = 0
    # Placement yaw for prism entities (radians)
    _ent_place_yaw: float = 0.0
    # Selected entity: managed by Zone3DEditor bridge property

    # ── Palette helpers ───────────────────────────────────────────

    def _ent_current_type(self) -> str:
        """Return the entity type ID currently selected in the palette."""
        pal = entity_palette()
        if not pal:
            return ""
        return pal[self._ent_type_idx % len(pal)]

    def _ent_current_def(self):
        """Return the :class:`EntityDef` for the current palette type."""
        return get_entity_def(self._ent_current_type())

    def _ent_cycle_palette(self, direction: int) -> None:
        pal = entity_palette()
        if not pal:
            return
        self._ent_type_idx = (self._ent_type_idx + direction) % len(pal)

    # ── Entity aiming / picking ───────────────────────────────────

    def _ent_find_aimed(self) -> int | None:
        """Return index of entity under crosshair, or None.

        Uses ray-AABB intersection against each entity's bounding box.
        Only returns the entity if it is closer than the aimed cell.
        """
        zone = self.zone
        if not zone or not zone.entities:
            return None

        fx, fy, fz = self._forward()
        ox, oy, oz = self.cam_x, self.cam_y, self.cam_z

        best_t = float("inf")
        best_idx: int | None = None

        for i, ent in enumerate(zone.entities):
            ex, ez = self._ent_world_pos(ent)
            edef = get_entity_def(ent.get("type", ""))
            def_s = edef.scale if edef else 0.5
            # Use per-entity scale override if present
            s = float(ent.get("overrides", {}).get("scale", def_s))

            # Floor height at entity cell
            ci = max(0, min(zone.width - 1, int(ex)))
            ri = max(0, min(zone.height - 1, int(ez)))
            fh = zone.floor_heights[ri][ci] if zone.floor_heights else 0.0

            # Base Y: wall-mounted entities use wall_height, others use floor
            base_y = self._ent_base_y(ent, zone, fh, edef)

            if edef and edef.render_type == "prism":
                # Prism entities: oriented bounding box with real dims
                angle = float(ent.get("angle", 0.0))
                result = _ray_vs_obb(
                    ox, oy, oz, fx, fy, fz,
                    ex, ez, base_y,
                    edef.width, edef.height, edef.depth,
                    angle,
                )
            else:
                # Billboard / 8-way: small axis-aligned bbox
                half = max(s * 0.25, 0.15)
                result = _ray_vs_aabb(
                    ox, oy, oz, fx, fy, fz,
                    ex - half, base_y, ez - half,
                    ex + half, base_y + s, ez + half,
                )
            if result is not None and result[0] < best_t:
                best_t = result[0]
                best_idx = i

        # Only pick entity if it's nearer than the aimed cell
        if best_idx is not None:
            aimed = self.aimed
            if aimed is None or best_t < aimed.t:
                return best_idx

        return None

    @staticmethod
    def _ent_world_pos(ent: dict) -> tuple[float, float]:
        """Return (world_x, world_z) from an entity dict.

        Handles both new format (``x``/``y`` keys) and legacy
        format (``position.x``/``position.y``).
        """
        if "x" in ent:
            return float(ent["x"]), float(ent["y"])
        pos = ent.get("position", {})
        return float(pos.get("x", 0)), float(pos.get("y", 0))

    # ── Wall placement helpers ────────────────────────────────────

    # Faces that count as wall surfaces for entity snapping.
    _WALL_FACES = {"north", "south", "east", "west"}

    # Small inset from the wall surface so the entity doesn't z-fight.
    _WALL_INSET = 0.01

    # Maximum ray distance for wall-snap detection.
    _WALL_SNAP_RANGE = 16.0

    @staticmethod
    def _infer_wall_face(fx: float, fz: float) -> str:
        """Pick the cardinal face most aligned with the camera forward.

        Used when the ray enters a wall cell through the top or bottom
        face instead of a cardinal side.
        """
        if abs(fz) >= abs(fx):
            return "north" if fz < 0 else "south"
        return "west" if fx < 0 else "east"

    def _project_ray_onto_face(
        self,
        r: int, c: int,
        face: str,
        ox: float, oy: float, oz: float,
        fx: float, fy: float, fz: float,
    ) -> tuple[float, float, float]:
        """Intersect the ray with the plane of *face* on cell (r, c).

        Returns ``(hit_y, hit_x, hit_z)`` — the world-space coordinates
        where the ray crosses the face plane.  If the ray is nearly
        parallel to the plane, returns a fallback (cell centre, camera Y).
        """
        if face in ("north", "south"):
            # face plane is Z = r (north) or Z = r + 1 (south)
            zp = float(r) if face == "north" else float(r + 1)
            if abs(fz) > 1e-10:
                t = (zp - oz) / fz
                return oy + t * fy, ox + t * fx, zp
            return oy, float(c) + 0.5, zp
        else:
            # face plane is X = c (west) or X = c + 1 (east)
            xp = float(c) if face == "west" else float(c + 1)
            if abs(fx) > 1e-10:
                t = (xp - ox) / fx
                return oy + t * fy, xp, oz + t * fz
            return oy, xp, float(r) + 0.5

    def _ent_compute_wall_snap(self, hit, entity_height: float = 0.0) -> dict | None:
        """If the crosshair points at a wall face, return wall-mount fields.

        Returns ``{"x", "y", "wall_face", "wall_height"}`` or ``None``
        when no wall face is found.

        Because the aimed cell is often a thin floor slab that sits
        closer than the wall behind it, we cast our own ray that only
        considers wall-tile AABBs.  We snap to the wall only when it
        is closer than (or barely behind) the aimed floor hit — a
        tight margin of 0.3 prevents false positives in dense zones
        where nearly every cell is near a wall.

        When the camera is above (or below) wall height the ray enters
        via the top/bot face of the AABB.  We still accept the hit and
        infer the cardinal wall face from the camera's horizontal
        forward direction so the entity can be placed anywhere on the
        wall.
        """
        zone = self.zone
        if zone is None:
            return None

        fx, fy, fz = self._forward()
        ox, oy, oz = self.cam_x, self.cam_y, self.cam_z

        # If the aimed hit is already on a wall cell, use it directly.
        if hit is not None and hit.part == "wall":
            face = hit.face
            if face in self._WALL_FACES:
                # Direct cardinal-face hit — use the ray intersection
                hx = ox + fx * hit.t
                hz = oz + fz * hit.t
                h_y = hit.hit_y
            else:
                # Top/bot hit — infer face and project ray onto it
                face = self._infer_wall_face(fx, fz)
                h_y, hx, hz = self._project_ray_onto_face(
                    hit.row, hit.col, face, ox, oy, oz, fx, fy, fz,
                )
            return self._wall_snap_from_hit(
                hit.row, hit.col, face, h_y, hx, hz, zone,
                entity_height=entity_height,
            )

        W, H = zone.width, zone.height

        # Find the nearest wall-cell hit along the ray with NO
        # tolerance based on the aimed floor t.  We decide whether
        # to use it afterwards via an adjacency / distance check.
        #
        # The wall AABB is used as-is (no vertical extension).
        # Top/bot face hits are handled by inferring the cardinal
        # face from the camera direction, so no extension is needed.

        best_t = self._WALL_SNAP_RANGE
        best_face: str | None = None
        best_r = 0
        best_c = 0
        best_was_topbot = False

        cam_c = int(math.floor(ox))
        cam_r = int(math.floor(oz))
        search = min(int(self._WALL_SNAP_RANGE) + 1, 16)

        for r in range(max(0, cam_r - search), min(H, cam_r + search)):
            for c in range(max(0, cam_c - search), min(W, cam_c + search)):
                for part, yb, yt in self._layer_cell_boxes(r, c):
                    if part != "wall":
                        continue  # skip floor / ceiling slabs
                    result = _ray_vs_aabb(
                        ox, oy, oz, fx, fy, fz,
                        float(c), yb, float(r),
                        c + 1.0, yt, r + 1.0,
                    )
                    if result is None:
                        continue
                    t_hit, face = result
                    was_topbot = False
                    # Accept cardinal faces directly; for top/bot we
                    # infer the cardinal face later from camera direction.
                    if face in self._WALL_FACES:
                        pass  # good
                    elif face in ("top", "bot"):
                        face = self._infer_wall_face(fx, fz)
                        was_topbot = True
                    else:
                        continue
                    if t_hit < best_t:
                        best_t = t_hit
                        best_face = face
                        best_r = r
                        best_c = c
                        best_was_topbot = was_topbot

        # ── Decide ──────────────────────────────────────────────
        #
        # Accept the wall hit only when it is at most slightly farther
        # than the aimed floor/slab hit.  The 0.3 margin catches the
        # common case where a floor slab sits just in front of the
        # wall face.  Larger distances mean the user is aiming at the
        # floor / ground — not at a wall.
        prefer_wall = False
        if best_face is not None:
            if hit is None:
                prefer_wall = True
            elif best_t <= hit.t + 0.3:
                prefer_wall = True
            elif hit.part == "ceiling":
                # The camera is above wall height and looking down;
                # the ceiling slab of an open cell sits very close
                # (small t) while the wall is further behind.  Use a
                # generous margin — entities can never be placed on
                # ceilings, so preferring the wall is always correct.
                prefer_wall = best_t <= hit.t + 2.0

        if prefer_wall:
            if best_was_topbot:
                # Project onto the inferred face plane for correct Y
                hit_y, hit_x, hit_z = self._project_ray_onto_face(
                    best_r, best_c, best_face,
                    ox, oy, oz, fx, fy, fz,
                )
            else:
                hit_y = oy + best_t * fy
                hit_x = ox + fx * best_t
                hit_z = oz + fz * best_t
            return self._wall_snap_from_hit(
                best_r, best_c, best_face, hit_y, hit_x, hit_z, zone,
                entity_height=entity_height,
            )

        # Step-wall fallback: accept a floor/ceiling face only when
        # there is an actual height difference creating a visible
        # step wall on that face.
        if (hit is not None
                and hit.face in self._WALL_FACES
                and hit.part not in ("wall",)):
            _ADJ_OFF = {
                "north": (-1, 0), "south": (1, 0),
                "west": (0, -1), "east": (0, 1),
            }
            dr, dc = _ADJ_OFF[hit.face]
            adj_r, adj_c = hit.row + dr, hit.col + dc
            if 0 <= adj_r < H and 0 <= adj_c < W:
                hit_fh = zone.floor_heights[hit.row][hit.col] if zone.floor_heights else 0.0
                adj_fh = zone.floor_heights[adj_r][adj_c] if zone.floor_heights else 0.0
                if hit_fh > adj_fh + 0.02:
                    sw_x = ox + fx * hit.t
                    sw_z = oz + fz * hit.t
                    return self._wall_snap_from_hit(
                        hit.row, hit.col, hit.face, hit.hit_y,
                        sw_x, sw_z, zone,
                        entity_height=entity_height,
                    )

        return None

    def _wall_snap_from_hit(
        self,
        r: int, c: int,
        face: str,
        hit_y: float,
        hit_x: float,
        hit_z: float,
        zone,
        entity_height: float = 0.0,
    ) -> dict | None:
        """Build wall-snap placement dict for a confirmed wall-face hit."""
        inset = self._WALL_INSET

        td = _tile_def(zone.tiles[r][c])
        is_solid_wall = td and td.wall

        wall_fh = zone.floor_heights[r][c] if zone.floor_heights else 0.0
        wall_ch = zone.ceil_heights[r][c] if zone.ceil_heights else 2.0

        # The 3D viewport renders the wall box from rendered_bot to
        # rendered_top (same formula as _compute_cell_boxes).  Use
        # pitch-angle proportional mapping across this visual box so
        # the entity tracks the user's vertical aim naturally — even
        # when the camera is far above/below the wall.
        rendered_bot = min(0.0, wall_fh)
        rendered_top = max(wall_ch, wall_fh + 0.05)

        _MARGIN = 0.1

        if is_solid_wall:
            _ADJ = {
                "north": (r - 1, c),
                "south": (r + 1, c),
                "west":  (r, c - 1),
                "east":  (r, c + 1),
            }
            adj_r, adj_c = _ADJ[face]
            if not (0 <= adj_r < zone.height and 0 <= adj_c < zone.width):
                return None

            if face in ("north", "south"):
                wx = max(c + _MARGIN, min(c + 1 - _MARGIN, hit_x))
                wz = (float(r) - inset) if face == "north" else (float(r + 1) + inset)
            else:
                wx = (float(c) - inset) if face == "west" else (float(c + 1) + inset)
                wz = max(r + _MARGIN, min(r + 1 - _MARGIN, hit_z))
        else:
            if face in ("north", "south"):
                wx = max(c + _MARGIN, min(c + 1 - _MARGIN, hit_x))
                wz = (float(r) - inset) if face == "north" else (float(r + 1) + inset)
            else:
                wx = (float(c) - inset) if face == "west" else (float(c + 1) + inset)
                wz = max(r + _MARGIN, min(r + 1 - _MARGIN, hit_z))

        wx = max(0.1, min(zone.width - 0.1, wx))
        wz = max(0.1, min(zone.height - 0.1, wz))

        # Pitch-angle mapping: compute the angle from the camera to
        # the top and bottom of the rendered wall box, then map the
        # camera's current pitch proportionally between them.
        dx = wx - self.cam_x
        dz = wz - self.cam_z
        d_horiz = math.sqrt(dx * dx + dz * dz)

        if d_horiz < 0.01 or rendered_top - rendered_bot < 0.001:
            wall_h = (rendered_bot + rendered_top) * 0.5
        else:
            angle_top = math.atan2(rendered_top - self.cam_y, d_horiz)
            angle_bot = math.atan2(rendered_bot - self.cam_y, d_horiz)
            fx, fy, fz = self._forward()
            pitch = math.atan2(fy, math.sqrt(fx * fx + fz * fz))
            span = angle_top - angle_bot
            if abs(span) < 1e-6:
                frac = 0.5
            else:
                frac = (pitch - angle_bot) / span
            frac = max(0.0, min(1.0, frac))
            wall_h = rendered_bot + frac * (rendered_top - rendered_bot)

        # Offset so the entity is centered on the crosshair, not
        # sitting with its base there.  Clamp to stay within the wall.
        wall_h -= entity_height * 0.5
        wall_h = max(rendered_bot, min(wall_h, rendered_top - entity_height))

        return {
            "x": round(wx, 3),
            "y": round(wz, 3),
            "wall_face": face,
            "wall_height": round(wall_h, 3),
        }

    @staticmethod
    def _ent_base_y(ent: dict, zone, fh: float, edef) -> float:
        """Return the rendering base-Y for an entity.

        Wall-mounted entities use their stored ``wall_height``;
        floor entities use floor height + definition elevation.
        Layer-2 entities use ``floor2_heights`` when available.
        """
        wh = ent.get("wall_height")
        if wh is not None:
            return float(wh)
        layer = ent.get("layer", 1)
        if layer == 2:
            if "x" in ent:
                ex, ez = float(ent["x"]), float(ent["y"])
            else:
                pos = ent.get("position", {})
                ex, ez = float(pos.get("x", 0)), float(pos.get("y", 0))
            ci = max(0, min(zone.width - 1, int(ex)))
            ri = max(0, min(zone.height - 1, int(ez)))
            f2 = getattr(zone, "floor2_heights", None)
            if f2 and len(f2) > ri and len(f2[ri]) > ci:
                fh = f2[ri][ci]
        elev = edef.elevation if edef else 0.0
        return fh + elev

    # ── Placement ─────────────────────────────────────────────────

    def _ent_place(self) -> None:
        """Place a new entity at the aimed position (floor or wall)."""
        hit = self.aimed
        if hit is None:
            return
        zone = self.zone
        if not zone:
            return
        etype = self._ent_current_type()
        if not etype:
            return

        # Check for wall-face snap first
        edef = get_entity_def(etype)
        # Use actual rendered height: prism uses def height,
        # billboard uses scale * 0.6 (matching C renderer h_scale).
        ent_h = edef.height if (edef and edef.render_type == "prism") else (edef.scale * 0.6 if edef else 0.3)
        wall = self._ent_compute_wall_snap(hit, entity_height=ent_h)

        if wall:
            wx, wz = wall["x"], wall["y"]
        else:
            # World position from camera + ray distance (floor placement)
            fx, fy, fz = self._forward()
            ox, oy, oz = self.cam_x, self.cam_y, self.cam_z
            wx = ox + fx * hit.t
            wz = oz + fz * hit.t
            wx = max(0.1, min(zone.width - 0.1, wx))
            wz = max(0.1, min(zone.height - 0.1, wz))

        self._push_undo()
        # Use placement yaw for directional entities (prism + billboard)
        edef = get_entity_def(etype)
        place_angle = self._ent_place_yaw if (edef and edef.directional) else 0.0
        ent: dict = {
            "id": f"{etype}_{uuid.uuid4().hex[:6]}",
            "uid": zone.next_uid(),
            "type": etype,
            "x": round(wx, 3),
            "y": round(wz, 3),
            "angle": round(place_angle, 4),
            "state": "default",
            "overrides": {},
        }
        # Attach wall-mount metadata when placed on a wall face
        if wall:
            ent["wall_face"] = wall["wall_face"]
            ent["wall_height"] = wall["wall_height"]
        # Tag with layer 2 when placed on a floor2/ceiling2 surface
        if hit is not None and hit.part in ("floor2", "ceiling2"):
            ent["layer"] = 2
        zone.entities.append(ent)
        # Don't auto-select after placing — keeps us in placement mode
        # so the user can rapidly place multiple entities.
        self._ent_selected = None
        self.dirty = True

    # ── Selection ─────────────────────────────────────────────────

    def _ent_select(self, idx: int) -> None:
        self._ent_selected = idx

    def _ent_deselect(self) -> None:
        self._ent_selected = None

    # ── Deletion ──────────────────────────────────────────────────

    def _ent_delete(self, idx: int | None = None) -> None:
        """Delete entity at *idx* (or the selected entity)."""
        zone = self.zone
        if not zone or not zone.entities:
            return
        if idx is None:
            idx = self._ent_selected
        if idx is None or idx < 0 or idx >= len(zone.entities):
            return

        self._push_undo()
        uid = zone.entities[idx].get("uid", 0)
        zone.entities.pop(idx)
        self._flash("Entity deleted — Ct+Z to undo", 1.5, (1.0, 0.6, 0.5, 1.0))

        # Notify selection store (no index fixup needed — UIDs are stable)
        if uid:
            self.selection.on_object_deleted(uid)
        self.dirty = True

    # ── Move ──────────────────────────────────────────────────────

    def _ent_move_to_aimed(self) -> None:
        """Move the selected entity to where the crosshair hits (floor or wall)."""
        hit = self.aimed
        if hit is None or self._ent_selected is None:
            return
        zone = self.zone
        if not zone or not zone.entities:
            return
        idx = self._ent_selected
        if idx < 0 or idx >= len(zone.entities):
            return

        # Check for wall-face snap
        ent = zone.entities[idx]
        edef = get_entity_def(ent.get("type", ""))
        ent_h = edef.height if (edef and edef.render_type == "prism") else (edef.scale if edef else 0.5)
        wall = self._ent_compute_wall_snap(hit, entity_height=ent_h)

        if wall:
            wx, wz = wall["x"], wall["y"]
        else:
            fx, fy, fz = self._forward()
            ox, oy, oz = self.cam_x, self.cam_y, self.cam_z
            wx = ox + fx * hit.t
            wz = oz + fz * hit.t
            wx = max(0.1, min(zone.width - 0.1, wx))
            wz = max(0.1, min(zone.height - 0.1, wz))

        self._push_undo()
        ent = zone.entities[idx]
        ent["x"] = round(wx, 3)
        ent["y"] = round(wz, 3)
        if wall:
            ent["wall_face"] = wall["wall_face"]
            ent["wall_height"] = wall["wall_height"]
        else:
            # Moving to floor — clear wall-mount metadata
            ent.pop("wall_face", None)
            ent.pop("wall_height", None)
        # Update layer tag based on target surface
        if hit is not None and hit.part in ("floor2", "ceiling2"):
            ent["layer"] = 2
        else:
            ent.pop("layer", None)
        self.dirty = True

    # ── Rotation ──────────────────────────────────────────────────

    def _ent_rotate(self, direction: int) -> None:
        """Rotate the selected entity by 45° increments."""
        if self._ent_selected is None:
            return
        zone = self.zone
        if not zone or not zone.entities:
            return
        idx = self._ent_selected
        if idx < 0 or idx >= len(zone.entities):
            return

        ent = zone.entities[idx]
        angle = float(ent.get("angle", 0.0))
        angle += direction * (math.pi / 4.0)
        ent["angle"] = snap_angle_8dir(angle)
        self.dirty = True

    # ── State cycling ─────────────────────────────────────────────

    def _ent_cycle_state(self, direction: int = 1) -> None:
        """Cycle the visual state of the selected entity."""
        if self._ent_selected is None:
            return
        zone = self.zone
        if not zone or not zone.entities:
            return
        idx = self._ent_selected
        if idx < 0 or idx >= len(zone.entities):
            return
        ent = zone.entities[idx]
        edef = get_entity_def(ent.get("type", ""))
        if not edef or len(edef.states) < 2:
            return
        cur = ent.get("state", "default")
        try:
            si = list(edef.states).index(cur)
        except ValueError:
            si = 0
        si = (si + direction) % len(edef.states)
        ent["state"] = edef.states[si]
        self.dirty = True
