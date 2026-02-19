"""scenes/world/fp_perflog.py — Frame-by-frame render performance logger.

Writes a CSV file into ``logs/`` with one row per frame, capturing
per-stage timings, cache statistics, entity counts, and player state.

**How to use:**

1.  Press **F6** in first-person view to toggle logging on/off.
2.  Play/stress-test normally — walk around, spin the camera fast, etc.
3.  Press **F6** again (or leave the zone) to stop logging.
4.  The log CSV is saved in ``logs/perf_<timestamp>.csv``.

The logger is designed to be zero-overhead when inactive (just one
``if`` check per frame).
"""

from __future__ import annotations

import csv
import os
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

# ── CSV columns ──────────────────────────────────────────────────
_COLUMNS = [
    # Frame identity
    "frame",
    "timestamp",
    "wall_clock_ms",       # real time since logging started
    # Player state
    "zone",
    "px", "py", "angle",
    "fov",
    # Resolution
    "render_w", "render_h",
    # Per-stage durations (milliseconds)
    "dt_floor_ceil",
    "dt_walls",
    "dt_cast",
    "dt_blit_walls",
    "dt_visplane",
    "dt_entities",
    "dt_tint",
    "dt_upscale",
    "dt_hud",
    "dt_sim",
    "dt_physics",
    "dt_frame_total",
    # FPS
    "fps",
    # Cache statistics
    "strip_cache_size",
    "strip_cache_prev_size",
    "col_cache_size",
    "ent_pool_size",
    "bb_base_cache_size",
    "glyph_cache_size",
    # Entity info
    "n_entities_visible",
    "n_entity_billboards",
    "n_deferred_halves",
    # Raycaster
    "n_slices",
    "c_extension_active",
]


class PerfLogger:
    """Lightweight per-frame CSV logger for render performance."""

    def __init__(self) -> None:
        self._active = False
        self._writer: csv.writer | None = None
        self._file = None
        self._filepath: str = ""
        self._frame: int = 0
        self._t_start: float = 0.0
        # Per-frame accumulator — stages write here then flush at end
        self._row: dict[str, object] = {}

    # ── Public API ───────────────────────────────────────────────

    @property
    def active(self) -> bool:
        return self._active

    def toggle(self) -> str:
        """Toggle logging on/off.  Returns a status message."""
        if self._active:
            return self.stop()
        else:
            return self.start()

    def start(self) -> str:
        """Start a new logging session and return the file path."""
        if self._active:
            return f"Already logging → {self._filepath}"

        logs_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__)))),
            "logs",
        )
        os.makedirs(logs_dir, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        self._filepath = os.path.join(logs_dir, f"perf_{ts}.csv")
        self._file = open(self._filepath, "w", newline="", buffering=1)
        self._writer = csv.writer(self._file)
        self._writer.writerow(_COLUMNS)
        self._frame = 0
        self._t_start = time.perf_counter()
        self._active = True
        self._row = {}
        return f"Perf logging → {self._filepath}"

    def stop(self) -> str:
        """Flush and close the current log file."""
        if not self._active:
            return "Not logging"
        self._active = False
        path = self._filepath
        if self._file:
            self._file.close()
            self._file = None
        self._writer = None
        return f"Perf log saved ({self._frame} frames) → {path}"

    # ── Per-frame recording ──────────────────────────────────────

    def begin_frame(self) -> None:
        """Call at the very start of each frame."""
        if not self._active:
            return
        self._row = {
            "frame": self._frame,
            "timestamp": time.time(),
            "wall_clock_ms": (time.perf_counter() - self._t_start) * 1000.0,
        }
        self._frame_t0 = time.perf_counter()

    def record(self, key: str, value: object) -> None:
        """Set a column value for the current frame."""
        if not self._active:
            return
        self._row[key] = value

    def record_ms(self, key: str, seconds: float) -> None:
        """Record a timing in milliseconds (input is seconds)."""
        if not self._active:
            return
        self._row[key] = round(seconds * 1000.0, 3)

    def end_frame(self, fps: float = 0.0) -> None:
        """Flush the accumulated row to CSV."""
        if not self._active or self._writer is None:
            return
        self._row["dt_frame_total"] = round(
            (time.perf_counter() - self._frame_t0) * 1000.0, 3
        )
        self._row.setdefault("fps", round(fps, 1))
        row_data = [self._row.get(col, "") for col in _COLUMNS]
        self._writer.writerow(row_data)
        self._frame += 1

    # ── Cleanup ──────────────────────────────────────────────────

    def __del__(self) -> None:
        if self._file:
            try:
                self._file.close()
            except Exception:
                pass
