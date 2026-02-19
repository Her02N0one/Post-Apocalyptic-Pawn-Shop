"""editor/layout.py — Responsive layout for the editor UI.

Uses a classic **menu bar + zone nav** layout across the top, a tile
palette on the left, and an inspector on the right.  The menu bar
houses standard dropdown menus (File, Edit, View, Tools, Editors).

Provides a singleton ``Layout`` class whose class attributes are
recalculated each frame via ``Layout.update(sw, sh)``.  Every panel
references these instead of hard-coded pixel constants, so the editor
adapts to window resizes gracefully.
"""

from __future__ import annotations


class Layout:
    """Mutable layout singleton — call ``update(sw, sh)`` once per frame."""

    # ── Panel sizes (recalculated by update) ─────────────────────
    menu_h: int = 22          # top menu bar
    nav_h: int = 26           # zone nav bar below menu
    palette_w: int = 150      # tile palette on the left
    inspector_w: int = 240    # right-side property panel
    status_h: int = 22        # bottom status bar

    # Backward-compat aliases
    toolbar_h: int = 0
    sidebar_w: int = 0
    panel_w: int = 150

    # ── Derived canvas area ──────────────────────────────────────
    canvas_x: int = 150
    canvas_y: int = 48        # menu_h + nav_h
    canvas_w: int = 570
    canvas_h: int = 570

    # ── Screen size cache ────────────────────────────────────────
    sw: int = 960
    sh: int = 640

    @classmethod
    def update(cls, sw: int, sh: int):
        """Recompute all sizes for the current window dimensions."""
        if sw == cls.sw and sh == cls.sh:
            return
        cls.sw = sw
        cls.sh = sh

        # Fixed sizes
        cls.menu_h = 22
        cls.nav_h = 26
        cls.status_h = 22
        cls.toolbar_h = 0
        cls.sidebar_w = 0

        # Scale side panels proportionally (min / max clamped)
        cls.palette_w = max(130, min(180, int(sw * 0.16)))
        cls.panel_w = cls.palette_w
        cls.inspector_w = max(210, min(280, int(sw * 0.24)))

        # Canvas fills the remainder
        cls.canvas_x = cls.palette_w
        cls.canvas_y = cls.menu_h + cls.nav_h
        cls.canvas_w = max(200, sw - cls.palette_w - cls.inspector_w)
        cls.canvas_h = max(100, sh - cls.canvas_y - cls.status_h)
