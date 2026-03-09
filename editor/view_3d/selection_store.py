"""editor/view_3d/selection_store.py — Single source of truth for selection.

Phase 2 replacement for the dual-state system (``SelectionState.objects``
+ per-tool ``_*_selected`` singletons).

Design
~~~~~~
* **Cells** are identified by stable ``(row, col)`` tuples — same as before.
* **Objects** are identified by persistent **UIDs** (integers assigned by
  ``Zone.next_uid()``).  UIDs survive deletions of unrelated objects, so
  the store never needs index-fixup callbacks.
* A single **primary** UID represents the inspector / scroll-adjust target
  (replaces the six ``_*_selected`` singletons).
* The store emits :class:`SelectionChanged` events on every mutation.

Migration note
~~~~~~~~~~~~~~
Legacy code that reads / writes ``self._ent_selected`` etc. goes through
bridge properties on ``Zone3DEditor`` that translate between list indices
and UIDs via :meth:`resolve_index` / :meth:`uid_of`.
"""

from __future__ import annotations

from typing import Any, Iterator, TYPE_CHECKING

if TYPE_CHECKING:
    from core.zones.zone import Zone

# ── Zone-list attribute mapping ───────────────────────────────────

_STORES: dict[str, str] = {
    "entity":  "entities",
    "prism":   "boxes",
    "quad":    "quads",
    "portal":  "render_portals",
    "curve":   "curves",
    "overlay": "overlay_walls",
}


# ── Helpers ───────────────────────────────────────────────────────

def _get_uid(obj: Any) -> int:
    """Extract the UID from a zone object (dict or dataclass)."""
    if isinstance(obj, dict):
        return obj.get("uid", 0)
    return getattr(obj, "uid", 0)


def uid_of(zone: "Zone", type_tag: str, index: int) -> int | None:
    """Return the UID of the object at *index* in the zone list, or None."""
    store_attr = _STORES.get(type_tag)
    if store_attr is None:
        return None
    store = getattr(zone, store_attr, None)
    if not store or index < 0 or index >= len(store):
        return None
    return _get_uid(store[index]) or None


def resolve_index(zone: "Zone", type_tag: str, uid: int) -> int | None:
    """Return the list index for *uid* in the zone list, or None.

    Linear scan — O(n) where n is small (typically <100 objects).
    """
    store_attr = _STORES.get(type_tag)
    if store_attr is None:
        return None
    store = getattr(zone, store_attr, None)
    if not store:
        return None
    for i, obj in enumerate(store):
        if _get_uid(obj) == uid:
            return i
    return None


# ── SelectionStore ────────────────────────────────────────────────

class SelectionStore:
    """Single source of truth for cell and object selection.

    Parameters
    ----------
    event_bus : EventBus | None
        If provided, :class:`SelectionChanged` events are emitted on
        every selection mutation.
    """

    __slots__ = (
        "_event_bus",
        # Cell selection
        "cells", "_rect_origin", "_rect_end", "ceiling_mode", "anchor",
        # Object selection (keyed by UID)
        "_selected", "_uid_types", "_primary",
    )

    def __init__(self, event_bus: Any = None) -> None:
        self._event_bus = event_bus

        # ── Cell selection ────────────────────────────────────────
        self.cells: set[tuple[int, int]] = set()
        self._rect_origin: tuple[int, int] | None = None
        self._rect_end: tuple[int, int] | None = None
        self.ceiling_mode: bool = False
        self.anchor: tuple[int, int] | None = None

        # ── Object selection ──────────────────────────────────────
        self._selected: set[int] = set()             # UIDs
        self._uid_types: dict[int, str] = {}          # uid → type_tag
        self._primary: int | None = None              # inspector target

    # ══════════════════════════════════════════════════════════════
    #  Cell selection  (API-compatible with SelectionState)
    # ══════════════════════════════════════════════════════════════

    def select_cell(self, r: int, c: int) -> None:
        self.cells.clear()
        self.cells.add((r, c))

    def add_cell(self, r: int, c: int) -> None:
        self.cells.add((r, c))

    def toggle_cell(self, r: int, c: int) -> None:
        key = (r, c)
        if key in self.cells:
            self.cells.discard(key)
        else:
            self.cells.add(key)

    def select_rect(self, r1: int, c1: int, r2: int, c2: int) -> None:
        self.cells.clear()
        self.add_rect(r1, c1, r2, c2)

    def add_rect(self, r1: int, c1: int, r2: int, c2: int) -> None:
        rmin, rmax = min(r1, r2), max(r1, r2)
        cmin, cmax = min(c1, c2), max(c1, c2)
        for r in range(rmin, rmax + 1):
            for c in range(cmin, cmax + 1):
                self.cells.add((r, c))

    def select_line(self, r1: int, c1: int, r2: int, c2: int) -> None:
        self.cells.clear()
        self.add_line(r1, c1, r2, c2)

    def add_line(self, r1: int, c1: int, r2: int, c2: int) -> None:
        dr = abs(r2 - r1)
        dc = abs(c2 - c1)
        sr = 1 if r1 < r2 else -1
        sc = 1 if c1 < c2 else -1
        err = dr - dc
        r, c = r1, c1
        while True:
            self.cells.add((r, c))
            if r == r2 and c == c2:
                break
            e2 = 2 * err
            if e2 > -dc:
                err -= dc
                r += sr
            if e2 < dr:
                err += dr
                c += sc

    def select_all_cells(self, width: int, height: int) -> None:
        self.cells = {(r, c) for r in range(height) for c in range(width)}
        self.anchor = (0, 0)

    # ── Rectangle drag ────────────────────────────────────────────

    def begin_rect(self, r: int, c: int) -> None:
        self._rect_origin = (r, c)
        self._rect_end = None
        self.anchor = (r, c)

    def update_rect(self, r: int, c: int) -> None:
        self._rect_end = (r, c)

    def finish_rect(self, r: int, c: int, *, extend: bool = False) -> None:
        if self._rect_origin is None:
            return
        r1, c1 = self._rect_origin
        if extend:
            self.add_rect(r1, c1, r, c)
        else:
            self.select_rect(r1, c1, r, c)
        self._rect_origin = None
        self._rect_end = None

    def cancel_rect(self) -> None:
        self._rect_origin = None
        self._rect_end = None

    @property
    def rect_in_progress(self) -> bool:
        return self._rect_origin is not None

    @property
    def rect_preview(self) -> tuple[int, int, int, int] | None:
        if self._rect_origin is None or self._rect_end is None:
            return None
        r1, c1 = self._rect_origin
        r2, c2 = self._rect_end
        return (min(r1, r2), min(c1, c2), max(r1, r2), max(c1, c2))

    # ══════════════════════════════════════════════════════════════
    #  Object selection  (UID-based — the core Phase 2 change)
    # ══════════════════════════════════════════════════════════════

    def select_object(self, type_tag: str, uid: int) -> None:
        """Single-select an object (clears prior object selection)."""
        self._selected.clear()
        self._uid_types.clear()
        self._selected.add(uid)
        self._uid_types[uid] = type_tag
        self._primary = uid
        self._emit_changed()

    def add_object(self, type_tag: str, uid: int) -> None:
        """Add an object to multi-selection."""
        self._selected.add(uid)
        self._uid_types[uid] = type_tag
        if self._primary is None:
            self._primary = uid
        self._emit_changed()

    def toggle_object(self, type_tag: str, uid: int) -> None:
        """Toggle an object in/out of the selection (Ctrl+click)."""
        if uid in self._selected:
            self._selected.discard(uid)
            self._uid_types.pop(uid, None)
            if self._primary == uid:
                self._primary = next(iter(self._selected), None)
        else:
            self._selected.add(uid)
            self._uid_types[uid] = type_tag
            if self._primary is None:
                self._primary = uid
        self._emit_changed()

    def deselect_object(self, uid: int) -> None:
        """Remove a single object from the selection."""
        if uid not in self._selected:
            return
        self._selected.discard(uid)
        self._uid_types.pop(uid, None)
        if self._primary == uid:
            self._primary = next(iter(self._selected), None)
        self._emit_changed()

    def select_objects_in_rect(
        self, rmin: int, cmin: int, rmax: int, cmax: int, zone: "Zone",
    ) -> None:
        """Select all objects whose position falls inside the cell bounds."""
        self._selected.clear()
        self._uid_types.clear()
        self._primary = None

        def _check(store, x_key, y_key, tag):
            for obj in (store or []):
                ox = float(obj.get(x_key, 0) if isinstance(obj, dict)
                           else getattr(obj, x_key, 0))
                oy = float(obj.get(y_key, 0) if isinstance(obj, dict)
                           else getattr(obj, y_key, 0))
                ec, er = int(ox), int(oy)
                if rmin <= er <= rmax and cmin <= ec <= cmax:
                    uid = _get_uid(obj)
                    if uid:
                        self._selected.add(uid)
                        self._uid_types[uid] = tag

        _check(zone.entities,       "x", "y",  "entity")
        _check(zone.boxes,          "x", "y",  "prism")
        _check(zone.quads,          "x", "z",  "quad")
        _check(zone.curves,         "cx", "cy", "curve")
        # Overlays use (x1,y1)→(x2,y2) midpoint
        for ow in (zone.overlay_walls or []):
            mx = (ow.x1 + ow.x2) / 2.0
            my = (ow.y1 + ow.y2) / 2.0
            ec, er = int(mx), int(my)
            if rmin <= er <= rmax and cmin <= ec <= cmax:
                if ow.uid:
                    self._selected.add(ow.uid)
                    self._uid_types[ow.uid] = "overlay"

        if self._selected:
            self._primary = next(iter(self._selected))
        self._emit_changed()

    # ── Primary (inspector / scroll target) ───────────────────────

    @property
    def primary_uid(self) -> int | None:
        """UID of the focused object, or None."""
        return self._primary

    @property
    def primary_type(self) -> str | None:
        """Type tag of the focused object, or None."""
        if self._primary is None:
            return None
        return self._uid_types.get(self._primary)

    def primary_index(self, zone: "Zone") -> int | None:
        """Resolve primary UID to its current list index."""
        if self._primary is None:
            return None
        tag = self._uid_types.get(self._primary)
        if tag is None:
            return None
        return resolve_index(zone, tag, self._primary)

    # ── Queries ───────────────────────────────────────────────────

    def is_object_selected(self, uid: int) -> bool:
        return uid in self._selected

    def has_cells(self) -> bool:
        return len(self.cells) > 0

    def has_objects(self) -> bool:
        return bool(self._selected)

    def has_anything(self) -> bool:
        return self.has_cells() or self.has_objects()

    def cell_count(self) -> int:
        return len(self.cells)

    def object_count(self) -> int:
        return len(self._selected)

    def iter_cells(self) -> Iterator[tuple[int, int]]:
        return iter(self.cells)

    def iter_objects(self) -> Iterator[tuple[str, int]]:
        """Yield ``(type_tag, uid)`` for every selected object."""
        for uid in self._selected:
            yield (self._uid_types.get(uid, ""), uid)

    def selected_uids_by_type(self, type_tag: str) -> list[int]:
        """Return UIDs of all selected objects with the given type tag."""
        return [u for u in self._selected if self._uid_types.get(u) == type_tag]

    def bounds(self) -> tuple[int, int, int, int] | None:
        """Return (rmin, cmin, rmax, cmax) of all selected cells."""
        if not self.cells:
            return None
        rmin = min(r for r, _ in self.cells)
        cmin = min(c for _, c in self.cells)
        rmax = max(r for r, _ in self.cells)
        cmax = max(c for _, c in self.cells)
        return (rmin, cmin, rmax, cmax)

    def contains_cell(self, r: int, c: int) -> bool:
        return (r, c) in self.cells

    def contains_object(self, type_tag: str, uid: int) -> bool:
        return uid in self._selected and self._uid_types.get(uid) == type_tag

    # ── Object lifecycle ──────────────────────────────────────────

    def on_object_deleted(self, uid: int) -> None:
        """Remove a deleted object from the selection.

        No index fixup needed — UIDs are stable.
        """
        if uid not in self._selected:
            return
        was_primary = self._primary == uid
        self._selected.discard(uid)
        self._uid_types.pop(uid, None)
        if was_primary:
            self._primary = next(iter(self._selected), None)
        self._emit_changed()

    def on_object_inserted(self, type_tag: str, uid: int) -> None:
        """No-op — provided for API compatibility.

        With UID-based selection, insertion of new objects cannot
        invalidate existing selection entries.
        """
        pass

    # ── Clear ─────────────────────────────────────────────────────

    def clear_cells(self) -> None:
        self.cells.clear()
        self._rect_origin = None
        self._rect_end = None
        self.anchor = None

    def clear_objects(self) -> None:
        if not self._selected:
            return
        self._selected.clear()
        self._uid_types.clear()
        self._primary = None
        self._emit_changed()

    def clear(self) -> None:
        self.clear_cells()
        self.clear_objects()

    # ── Toggle mode ───────────────────────────────────────────────

    def toggle_ceiling_mode(self) -> None:
        self.ceiling_mode = not self.ceiling_mode

    # ── Backward-compat shims ─────────────────────────────────────
    # Some old code accesses ``selection.objects`` as a set directly.
    # Provide a read-only property that returns the current contents
    # as a set of ``(type_tag, uid)`` pairs.

    @property
    def objects(self) -> set[tuple[str, int]]:
        """Read-only view of selected objects as ``{(type_tag, uid), ...}``."""
        return {(self._uid_types.get(u, ""), u) for u in self._selected}

    # ── Event emission ────────────────────────────────────────────

    def _emit_changed(self) -> None:
        if self._event_bus is None:
            return
        from editor.commands.events import SelectionChanged
        self._event_bus.emit(SelectionChanged(
            cells=frozenset(self.cells),
            objects=frozenset(self.iter_objects()),
        ))
