"""editor/view_3d/cell_ops.py — Backwards-compatible re-exports.

The actual implementations now live in :mod:`editor.zone_ops` which has
no ``editor.view_3d`` package dependency.   Existing imports like
``from editor.view_3d.cell_ops import reset_cell`` continue to work.
"""

from __future__ import annotations

from editor.zone_ops import (          # noqa: F401 — re-export
    reset_cell,
    clear_cell_textures,
    DEFAULT_FLOOR,
    SKY_HEIGHT,
    LAYER_NONE,
)
