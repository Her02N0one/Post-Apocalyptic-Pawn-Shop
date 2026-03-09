"""editor/view_3d/objects.py — Unified object layer for the zone editor.

Provides a single entry-point for picking, selecting, deselecting, deleting,
and moving *all* placeable object types (entity, prism, quad, portal, curve,
overlay) without requiring the user to be in the matching tool.

Works with the :class:`SelectionStore` (Phase 2) via UIDs.  The per-type
mixin code handles type-specific operations (resize, rotate, arc adjust).

Usage in editor.py::

    self.objects = ObjectLayer(self)
    hit = self.objects.find_aimed()
    if hit: self.objects.select(hit)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass  # Zone3DEditor is a complex mixin class; avoid import cycles

from editor.view_3d.selection_store import _get_uid


# Object type → zone attribute name
_STORES = {
    "entity":  "entities",
    "prism":   "boxes",
    "quad":    "quads",
    "portal":  "render_portals",
    "curve":   "curves",
}

# Object type → per-type selected field name on editor
_SELECTED_FIELDS = {
    "entity":  "_ent_selected",
    "prism":   "_box_selected",
    "quad":    "_quad_selected",
    "portal":  "_portal_selected",
    "curve":   "_curve_selected",
}

# Object type → editor find_aimed method name
_FIND_METHODS = {
    "entity":  "_ent_find_aimed",
    "prism":   "_box_find_aimed",
    "quad":    "_quad_find_aimed",
    "portal":  None,             # portals use face-based, not ray-pick
    "curve":   "_curve_find_aimed",
}

# Object type → editor select method name
_SELECT_METHODS = {
    "entity":  "_ent_select",
    "prism":   "_box_select",
    "quad":    "_quad_select",
    "portal":  None,
    "curve":   "_curve_select",
}

# Object type → editor deselect method name
_DESELECT_METHODS = {
    "entity":  "_ent_deselect",
    "prism":   "_box_deselect",
    "quad":    "_quad_deselect",
    "portal":  "_portal_deselect",
    "curve":   "_curve_deselect",
}

# Object type → editor delete method name
_DELETE_METHODS = {
    "entity":  "_ent_delete",
    "prism":   "_box_delete",
    "quad":    "_quad_delete",
    "portal":  None,             # portals delete via _portal_delete()
    "curve":   "_curve_delete",
}

# Object type → editor move method name
_MOVE_METHODS = {
    "entity":  "_ent_move_to_aimed",
    "prism":   "_box_move_to_aimed",
    "quad":    "_quad_move_to_aimed",
    "portal":  None,
    "curve":   "_curve_move_to_aimed",
}


class ObjectLayer:
    """Unified object interaction layer.

    Wraps the per-type mixin methods to provide cross-type operations.
    Does NOT replace the mixin code — it delegates to it, so all existing
    type-specific logic (auto-stacking, snap, face painting) is preserved.
    """

    def __init__(self, editor) -> None:
        self.ed = editor

    # ── Query helpers ─────────────────────────────────────────────

    def get_store(self, obj_type: str) -> list:
        """Return the zone list for *obj_type* (e.g. zone.entities)."""
        attr = _STORES.get(obj_type)
        if not attr:
            return []
        zone = self.ed.zone
        if not zone:
            return []
        return getattr(zone, attr, []) or []

    def get_selected(self, obj_type: str) -> int | None:
        """Return the legacy per-type selected index, or None."""
        field = _SELECTED_FIELDS.get(obj_type)
        if not field:
            return None
        return getattr(self.ed, field, None)

    def any_selected(self) -> tuple[str, int] | None:
        """Return (type, idx) of the first legacy-selected object, or None."""
        for otype, field in _SELECTED_FIELDS.items():
            idx = getattr(self.ed, field, None)
            if idx is not None:
                return (otype, idx)
        return None

    # ── Unified find-aimed ────────────────────────────────────────

    def find_aimed(self, types: tuple[str, ...] | None = None,
                   ) -> tuple[str, int] | None:
        """Raycast to find the nearest object of any type under crosshair.

        Returns ``(obj_type, index)`` or ``None`` if nothing hit.
        *types* restricts which types to check (default = all ray-pickable).
        """
        if types is None:
            types = ("entity", "prism", "quad", "curve")  # portal excluded (face-based)

        best: tuple[str, int] | None = None
        best_t = float("inf")

        for otype in types:
            method_name = _FIND_METHODS.get(otype)
            if not method_name:
                continue
            store = self.get_store(otype)
            if not store:
                continue

            # Some find methods return (idx, face, t), some return idx
            method = getattr(self.ed, method_name, None)
            if method is None:
                continue

            idx = method()
            if idx is None:
                continue

            # Estimate distance — use the type-specific t if available
            t = self._estimate_t(otype, idx)
            if t is not None and t < best_t:
                best_t = t
                best = (otype, idx)
            elif t is None and best is None:
                # Fallback: no distance info but something was hit
                best = (otype, idx)

        return best

    def _estimate_t(self, obj_type: str, idx: int) -> float | None:
        """Estimate the ray hit distance for depth-sorting between types."""
        ed = self.ed
        zone = ed.zone
        if not zone:
            return None

        fx, fy, fz = ed._forward()
        ox, oy, oz = ed.cam_x, ed.cam_y, ed.cam_z

        if obj_type == "entity":
            store = zone.entities
            if idx < 0 or idx >= len(store):
                return None
            ent = store[idx]
            ex, ez = ed._ent_world_pos(ent)
            # Simple distance estimate (from camera to entity center)
            dx, dz = ex - ox, ez - oz
            return (dx * fx + dz * fz) if (dx * fx + dz * fz) > 0 else None

        if obj_type == "prism":
            # Use the face-aware finder for accurate t
            result = ed._box_find_aimed_face()
            if result and result[0] == idx:
                return result[2]  # t
            return None

        if obj_type == "quad":
            result = ed._quad_find_aimed_t()
            if result and result[0] == idx:
                return result[1]  # t
            return None

        if obj_type == "curve":
            # Approx: distance to curve center
            store = zone.curves
            if idx < 0 or idx >= len(store):
                return None
            cv = store[idx]
            cx = float(cv.get("cx", 0))
            cy = float(cv.get("cy", 0))
            dx, dz = cx - ox, cy - oz
            return (dx * fx + dz * fz) if (dx * fx + dz * fz) > 0 else None

        return None

    # ── Unified select ────────────────────────────────────────────

    def select(self, hit: tuple[str, int], add: bool = False) -> None:
        """Select an object by (type, idx) tuple.

        If *add* is True, adds to the universal selection set.
        Otherwise replaces the current selection.
        """
        obj_type, idx = hit
        ed = self.ed
        store = self.get_store(obj_type)
        if not store or idx < 0 or idx >= len(store):
            return
        uid = _get_uid(store[idx])
        if not uid:
            return

        if add:
            ed.selection.add_object(obj_type, uid)
            return

        # Single-select: the bridge property setter handles store update
        self.deselect_all()

        method_name = _SELECT_METHODS.get(obj_type)
        if method_name:
            method = getattr(ed, method_name, None)
            if method:
                method(idx)
        else:
            # Portal / other: direct field set (triggers bridge property)
            field = _SELECTED_FIELDS.get(obj_type)
            if field:
                setattr(ed, field, idx)

    def toggle_select(self, hit: tuple[str, int]) -> None:
        """Toggle an object's selection (Ctrl+click)."""
        obj_type, idx = hit
        ed = self.ed
        store = self.get_store(obj_type)
        if not store or idx < 0 or idx >= len(store):
            return
        uid = _get_uid(store[idx])
        if not uid:
            return
        ed.selection.toggle_object(obj_type, uid)
        # Sync legacy singleton from store state
        if ed.selection.is_object_selected(uid):
            field = _SELECTED_FIELDS.get(obj_type)
            if field:
                setattr(ed, field, idx)
        else:
            field = _SELECTED_FIELDS.get(obj_type)
            if field and getattr(ed, field, None) == idx:
                setattr(ed, field, None)

    # ── Unified deselect ──────────────────────────────────────────

    def deselect_all(self) -> None:
        """Deselect all objects across all types."""
        ed = self.ed
        # Clear the store (single source of truth).
        # Bridge property getters will see None automatically.
        ed.selection.clear_objects()

    def deselect_type(self, obj_type: str) -> None:
        """Deselect objects of a specific type."""
        method_name = _DESELECT_METHODS.get(obj_type)
        if method_name:
            method = getattr(self.ed, method_name, None)
            if method:
                method()

    # ── Unified delete ────────────────────────────────────────────

    def delete_selected(self) -> bool:
        """Delete all currently selected objects. Returns True if anything was deleted."""
        ed = self.ed
        deleted = False

        # Check universal selection first (UID-based)
        if ed.selection.has_objects():
            # Group by type, resolve UIDs → indices
            by_type: dict[str, list[tuple[int, int]]] = {}  # type → [(uid, idx), ...]
            zone = ed.zone
            for otype, uid in ed.selection.iter_objects():
                store = self.get_store(otype)
                if not store:
                    continue
                # Find index by scanning for matching UID
                for i, obj in enumerate(store):
                    if _get_uid(obj) == uid:
                        by_type.setdefault(otype, []).append((uid, i))
                        break

            if not by_type:
                return False

            ed._push_undo()
            for otype, uid_idx_pairs in by_type.items():
                store = self.get_store(otype)
                # Sort by descending index so pops don't shift earlier items
                for uid, idx in sorted(uid_idx_pairs, key=lambda p: p[1], reverse=True):
                    if 0 <= idx < len(store):
                        store.pop(idx)
                        deleted = True
                        # Notify store (just discards the UID — no fixup needed)
                        ed.selection.on_object_deleted(uid)

            if deleted:
                ed.dirty = True
            return deleted

        # Fallback: delete whatever is legacy-selected (via bridge properties)
        sel = self.any_selected()
        if sel:
            otype, idx = sel
            method_name = _DELETE_METHODS.get(otype)
            if method_name:
                method = getattr(ed, method_name, None)
                if method:
                    method(idx)
                    deleted = True
            elif otype == "portal":
                zone = ed.zone
                if zone and zone.render_portals and 0 <= idx < len(zone.render_portals):
                    uid = _get_uid(zone.render_portals[idx])
                    ed._push_undo()
                    zone.render_portals.pop(idx)
                    if uid:
                        ed.selection.on_object_deleted(uid)
                    ed._portal_selected = None
                    ed.dirty = True
                    ed._flash("Portal deleted — Ct+Z to undo", 1.5, (1.0, 0.6, 0.5, 1.0))
                    deleted = True

        return deleted

    # ── Unified move ──────────────────────────────────────────────

    def move_selected_to_aimed(self) -> bool:
        """Move the currently selected object(s) to the aimed position.

        For multi-selection, only the primary (legacy) selected object
        is moved (others would need offset calculation — future work).
        Returns True if moved.
        """
        sel = self.any_selected()
        if not sel:
            return False

        otype, idx = sel
        method_name = _MOVE_METHODS.get(otype)
        if not method_name:
            return False

        method = getattr(self.ed, method_name, None)
        if method is None:
            return False

        method()
        return True

    # ── Object count ──────────────────────────────────────────────

    def total_count(self) -> int:
        """Total number of objects across all types."""
        return sum(len(self.get_store(t)) for t in _STORES)

    def selected_count(self) -> int:
        """Number of currently selected objects."""
        ed = self.ed
        count = ed.selection.object_count()
        if count == 0:
            # Bridge property fallback: check if a primary is set
            if ed.selection.primary_uid is not None:
                count = 1
        return count

    # ── Type label ────────────────────────────────────────────────

    @staticmethod
    def type_label(obj_type: str) -> str:
        """Human-readable label for an object type."""
        return {
            "entity": "Entity",
            "prism":  "Prism",
            "quad":   "Quad",
            "portal": "Portal",
            "curve":  "Curve",
        }.get(obj_type, obj_type.title())
