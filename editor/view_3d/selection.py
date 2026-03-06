"""editor/view_3d/selection.py — Universal selection layer.

The selection is a persistent, cross-cutting layer that every tool
respects.  It holds two independent sets:

* **cells**   — grid cells identified by ``(row, col)`` tuples
* **objects** — placeable objects identified by ``(type_tag, index)``
                where *type_tag* is one of ``"entity"``, ``"prism"``,
                ``"quad"``, ``"portal"``, ``"curve"``.

Selection survives tool switches.  Tools that operate on cells check
``sel.has_cells()`` and iterate ``sel.iter_cells()`` to apply their
action in batch.  Tools that operate on objects check
``sel.has_objects()`` similarly.

Rectangle selection is built-in: call ``begin_rect(r, c)`` on the
first click and ``finish_rect(r, c)`` on the second to fill *cells*
with every cell inside the rectangle.  Shift-click *adds* to the
existing selection; Ctrl-click *toggles* individual items.
"""

from __future__ import annotations

from typing import Iterator


class SelectionState:
    """Persistent selection state shared by all tools."""

    __slots__ = (
        "cells", "objects",
        "_rect_origin", "_rect_end",
        "ceiling_mode",
        "anchor",
    )

    def __init__(self) -> None:
        self.cells: set[tuple[int, int]] = set()
        self.objects: set[tuple[str, int]] = set()

        # Rectangle-drag state
        self._rect_origin: tuple[int, int] | None = None
        self._rect_end: tuple[int, int] | None = None

        # Floor / ceiling targeting for batch height ops
        self.ceiling_mode: bool = False

        # Remembered first-corner for shift+click operations.
        # Set automatically by begin_rect / select_all_cells.
        self.anchor: tuple[int, int] | None = None

    # ── Cell selection ────────────────────────────────────────────

    def select_cell(self, r: int, c: int) -> None:
        """Set selection to exactly this one cell (clears prior)."""
        self.cells.clear()
        self.cells.add((r, c))

    def add_cell(self, r: int, c: int) -> None:
        """Add (r, c) to the selection (Shift+click)."""
        self.cells.add((r, c))

    def toggle_cell(self, r: int, c: int) -> None:
        """Toggle (r, c) in the selection (Ctrl+click)."""
        key = (r, c)
        if key in self.cells:
            self.cells.discard(key)
        else:
            self.cells.add(key)

    def select_rect(self, r1: int, c1: int, r2: int, c2: int) -> None:
        """Replace cell selection with every cell in a rectangle."""
        self.cells.clear()
        self.add_rect(r1, c1, r2, c2)

    def add_rect(self, r1: int, c1: int, r2: int, c2: int) -> None:
        """Add all cells in a rectangle to the selection."""
        rmin, rmax = min(r1, r2), max(r1, r2)
        cmin, cmax = min(c1, c2), max(c1, c2)
        for r in range(rmin, rmax + 1):
            for c in range(cmin, cmax + 1):
                self.cells.add((r, c))

    def select_line(self, r1: int, c1: int, r2: int, c2: int) -> None:
        """Select cells along a Bresenham line between two endpoints."""
        self.cells.clear()
        self.add_line(r1, c1, r2, c2)

    def add_line(self, r1: int, c1: int, r2: int, c2: int) -> None:
        """Add cells along a Bresenham line to the selection."""
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
        """Select every cell in the zone."""
        self.cells = {(r, c) for r in range(height) for c in range(width)}
        self.anchor = (0, 0)

    # ── Rectangle drag helpers ────────────────────────────────────

    def begin_rect(self, r: int, c: int) -> None:
        """Start a rectangle drag from cell (r, c)."""
        self._rect_origin = (r, c)
        self._rect_end = None
        self.anchor = (r, c)

    def update_rect(self, r: int, c: int) -> None:
        """Update the second corner of the rectangle (for preview)."""
        self._rect_end = (r, c)

    def finish_rect(self, r: int, c: int, *, extend: bool = False) -> None:
        """Complete the rectangle and add/replace cell selection."""
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
        """Cancel an in-progress rectangle drag."""
        self._rect_origin = None
        self._rect_end = None

    @property
    def rect_in_progress(self) -> bool:
        return self._rect_origin is not None

    @property
    def rect_preview(self) -> tuple[int, int, int, int] | None:
        """Return (rmin, cmin, rmax, cmax) of the in-progress rect, or None."""
        if self._rect_origin is None or self._rect_end is None:
            return None
        r1, c1 = self._rect_origin
        r2, c2 = self._rect_end
        return (min(r1, r2), min(c1, c2), max(r1, r2), max(c1, c2))

    # ── Object selection ──────────────────────────────────────────

    def select_object(self, type_tag: str, idx: int) -> None:
        """Set selection to exactly one object (clears prior objects)."""
        self.objects.clear()
        self.objects.add((type_tag, idx))

    def add_object(self, type_tag: str, idx: int) -> None:
        """Add an object to the selection (Shift+click)."""
        self.objects.add((type_tag, idx))

    def toggle_object(self, type_tag: str, idx: int) -> None:
        """Toggle an object in the selection (Ctrl+click)."""
        key = (type_tag, idx)
        if key in self.objects:
            self.objects.discard(key)
        else:
            self.objects.add(key)

    def select_objects_in_rect(
        self, rmin: int, cmin: int, rmax: int, cmax: int,
        zone,
    ) -> None:
        """Select all objects whose position falls inside the cell bounds."""
        self.objects.clear()
        # Entities
        for i, ent in enumerate(zone.entities or []):
            ex = float(ent.get("x", 0))
            ey = float(ent.get("y", 0))
            ec, er = int(ex), int(ey)
            if rmin <= er <= rmax and cmin <= ec <= cmax:
                self.objects.add(("entity", i))
        # Prisms (boxes)
        for i, b in enumerate(zone.boxes or []):
            bx = float(b.get("x", 0))
            bz = float(b.get("y", 0))
            bc, br = int(bx), int(bz)
            if rmin <= br <= rmax and cmin <= bc <= cmax:
                self.objects.add(("prism", i))
        # Quads
        for i, q in enumerate(zone.quads or []):
            qx = float(q.get("x", 0))
            qz = float(q.get("z", 0))
            qc, qr = int(qx), int(qz)
            if rmin <= qr <= rmax and cmin <= qc <= cmax:
                self.objects.add(("quad", i))
        # Curves
        for i, cv in enumerate(zone.curves or []):
            cx = float(cv.get("cx", 0))
            cy = float(cv.get("cy", 0))
            cc_i, cr = int(cx), int(cy)
            if rmin <= cr <= rmax and cmin <= cc_i <= cmax:
                self.objects.add(("curve", i))

    # ── Queries ───────────────────────────────────────────────────

    def has_cells(self) -> bool:
        return len(self.cells) > 0

    def has_objects(self) -> bool:
        return len(self.objects) > 0

    def has_anything(self) -> bool:
        return self.has_cells() or self.has_objects()

    def cell_count(self) -> int:
        return len(self.cells)

    def object_count(self) -> int:
        return len(self.objects)

    def iter_cells(self) -> Iterator[tuple[int, int]]:
        return iter(self.cells)

    def iter_objects(self) -> Iterator[tuple[str, int]]:
        return iter(self.objects)

    def bounds(self) -> tuple[int, int, int, int] | None:
        """Return (rmin, cmin, rmax, cmax) of all selected cells, or None."""
        if not self.cells:
            return None
        rmin = min(r for r, _ in self.cells)
        cmin = min(c for _, c in self.cells)
        rmax = max(r for r, _ in self.cells)
        cmax = max(c for _, c in self.cells)
        return (rmin, cmin, rmax, cmax)

    def contains_cell(self, r: int, c: int) -> bool:
        return (r, c) in self.cells

    def contains_object(self, type_tag: str, idx: int) -> bool:
        return (type_tag, idx) in self.objects

    # ── Clear ─────────────────────────────────────────────────────

    def clear_cells(self) -> None:
        self.cells.clear()
        self._rect_origin = None
        self._rect_end = None
        self.anchor = None

    def clear_objects(self) -> None:
        self.objects.clear()

    def clear(self) -> None:
        self.clear_cells()
        self.clear_objects()

    # ── Toggle mode ───────────────────────────────────────────────

    def toggle_ceiling_mode(self) -> None:
        self.ceiling_mode = not self.ceiling_mode

    # ── Adjustment to object indices after deletions ──────────────

    def on_object_deleted(self, type_tag: str, idx: int) -> None:
        """Call after deleting an object to fix selection indices."""
        self.objects.discard((type_tag, idx))
        fixed: set[tuple[str, int]] = set()
        for tag, i in self.objects:
            if tag == type_tag and i > idx:
                fixed.add((tag, i - 1))
            else:
                fixed.add((tag, i))
        self.objects = fixed

    def on_object_inserted(self, type_tag: str, idx: int) -> None:
        """Call after inserting an object to fix selection indices."""
        fixed: set[tuple[str, int]] = set()
        for tag, i in self.objects:
            if tag == type_tag and i >= idx:
                fixed.add((tag, i + 1))
            else:
                fixed.add((tag, i))
        self.objects = fixed
