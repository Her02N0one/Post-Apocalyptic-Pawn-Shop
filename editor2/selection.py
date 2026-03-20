"""editor2/selection.py — Persistent cell selection state."""

from __future__ import annotations

from typing import Iterator


class SelectionState:
    """Grid cell selection that survives tool switches.

    Supports rectangle, line (Bresenham), and individual cell
    toggle operations.
    """

    __slots__ = ("cells", "anchor", "_rect_origin", "ceiling_mode")

    def __init__(self) -> None:
        self.cells: set[tuple[int, int]] = set()
        self.anchor: tuple[int, int] | None = None
        self._rect_origin: tuple[int, int] | None = None
        self.ceiling_mode: bool = False

    # ── Queries ───────────────────────────────────────────────────

    def has_cells(self) -> bool:
        return bool(self.cells)

    def iter_cells(self) -> Iterator[tuple[int, int]]:
        return iter(self.cells)

    def bounds(self) -> tuple[int, int, int, int] | None:
        """Return (rmin, cmin, rmax, cmax) or None."""
        if not self.cells:
            return None
        rows = [r for r, _ in self.cells]
        cols = [c for _, c in self.cells]
        return min(rows), min(cols), max(rows), max(cols)

    # ── Cell operations ───────────────────────────────────────────

    def toggle_cell(self, r: int, c: int) -> None:
        key = (r, c)
        if key in self.cells:
            self.cells.discard(key)
        else:
            self.cells.add(key)

    def select_all(self, width: int, height: int) -> None:
        self.cells = {(r, c) for r in range(height) for c in range(width)}
        self.anchor = (0, 0)

    def clear(self) -> None:
        self.cells.clear()
        self._rect_origin = None
        self.anchor = None

    # ── Rectangle ─────────────────────────────────────────────────

    def begin_rect(self, r: int, c: int) -> None:
        self._rect_origin = (r, c)
        self.anchor = (r, c)
        # Immediately preview the single origin cell
        self.cells.clear()
        self.cells.add((r, c))

    def preview_rect(self, r: int, c: int) -> None:
        """Update cells to preview rectangle from origin to (r, c)."""
        if self._rect_origin is None:
            return
        r1, c1 = self._rect_origin
        rmin, rmax = min(r1, r), max(r1, r)
        cmin, cmax = min(c1, c), max(c1, c)
        self.cells.clear()
        for rr in range(rmin, rmax + 1):
            for cc in range(cmin, cmax + 1):
                self.cells.add((rr, cc))

    def finish_rect(self, r: int, c: int) -> None:
        if self._rect_origin is None:
            return
        r1, c1 = self._rect_origin
        rmin, rmax = min(r1, r), max(r1, r)
        cmin, cmax = min(c1, c), max(c1, c)
        self.cells.clear()
        for rr in range(rmin, rmax + 1):
            for cc in range(cmin, cmax + 1):
                self.cells.add((rr, cc))
        self._rect_origin = None

    def cancel_rect(self) -> None:
        self._rect_origin = None

    @property
    def rect_in_progress(self) -> bool:
        return self._rect_origin is not None

    # ── Line (Bresenham) ──────────────────────────────────────────

    def select_line(self, r1: int, c1: int, r2: int, c2: int) -> None:
        self.cells.clear()
        self._bresenham(r1, c1, r2, c2)

    def _bresenham(self, r1: int, c1: int, r2: int, c2: int) -> None:
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

    def toggle_ceiling_mode(self) -> None:
        self.ceiling_mode = not self.ceiling_mode
