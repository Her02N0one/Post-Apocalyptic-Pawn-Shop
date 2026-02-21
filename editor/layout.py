"""editor/layout.py — Responsive layout for the editor UI.

Uses a classic **menu bar + zone nav** layout across the top, a tile
palette on the left, and an inspector on the right.  The menu bar
houses standard dropdown menus (File, Edit, View, Tools, Editors).

Provides a singleton ``Layout`` class whose class attributes are
recalculated each frame via ``Layout.update(sw, sh)``.  Every panel
references these instead of hard-coded pixel constants, so the editor
adapts to window resizes gracefully.

Panel widths can be overridden by the user by dragging the splitter
handles between panels.  Call ``set_palette_w`` / ``set_inspector_w``
to apply a user override that persists across window resizes.

A global **scale** factor (``Layout.scale``) is computed from the
window height relative to a 640px reference.  Panels and widgets that
need to scale pixel constants should call ``Layout.s(px)`` which
returns ``round(px * scale)``.
"""

from __future__ import annotations


# Reference height that the original 960×640 layout was designed for
_REF_H = 640


class Layout:
    """Mutable layout singleton — call ``update(sw, sh)`` once per frame."""

    # ── Scale factor ─────────────────────────────────────────────
    scale: float = 1.0         # sh / _REF_H  (≥1.0 on most monitors)
    _fonts_dirty: bool = True  # True when scale changed and fonts need rebuild

    # ── Panel sizes (recalculated by update) ─────────────────────
    menu_h: int = 28
    nav_h: int = 32
    palette_w: int = 200
    inspector_w: int = 300
    status_h: int = 26

    # Backward-compat aliases
    toolbar_h: int = 28
    sidebar_w: int = 0
    panel_w: int = 200

    # ── Derived canvas area ──────────────────────────────────────
    canvas_x: int = 200
    canvas_y: int = 60
    canvas_w: int = 780
    canvas_h: int = 700

    # ── Screen size cache ────────────────────────────────────────
    sw: int = 1280
    sh: int = 800

    # ── User overrides (None = auto-scale) ───────────────────────
    _user_palette_frac: float | None = None
    _user_inspector_frac: float | None = None

    # Absolute min/max for dragging (scaled each update)
    PALETTE_MIN: int = 100
    PALETTE_MAX: int = 500
    INSPECTOR_MIN: int = 200
    INSPECTOR_MAX: int = 560
    CANVAS_MIN: int = 260

    # ── Common scaled metric helpers ─────────────────────────────
    # Frequently-used item sizes that panels can reference instead
    # of hardcoding raw pixels.  Updated every ``update()`` call.
    row_h: int = 26         # standard list-row height
    item_h: int = 30        # slightly taller list item
    header_h: int = 26      # section header height
    field_h: int = 26       # text-field / input height
    swatch: int = 40        # tile swatch size (tile palette)
    thumb: int = 40         # texture thumbnail size
    pad_sm: int = 4         # small padding
    pad_md: int = 8         # medium padding
    pad_lg: int = 12        # large padding
    scroll_step: int = 34   # mouse-wheel scroll amount
    label_col: int = 90     # label column width (inspector)
    btn_h: int = 28         # standard button height
    border_r: int = 4       # standard border-radius
    panel_tab_h: int = 60   # height reserved for panel mode tabs strip (2 rows)

    # ── Horizontal top bars (computed by update) ───────────────
    # Each bar spans full screen width.  y = top pixel, h = height.
    menu_y: int = 0          # always 0
    nav_y: int = 0           # menu_h
    toolbar_y: int = 0       # menu_h + nav_h

    # ── Left-panel vertical slots (computed by update) ───────────
    # These define the non-overlapping regions of the left panel.
    # Every panel MUST use these instead of computing its own offsets.
    lp_tabs_y: int = 0       # top of the tab-button strip
    lp_tabs_h: int = 0       # height of the tab-button strip
    lp_content_y: int = 0    # first pixel of scrollable content area
    lp_content_h: int = 0    # height of scrollable content area
    lp_bottom_y: int = 0     # bottom edge (status bar top)

    # ── Right-panel (inspector) vertical slots ───────────────────
    rp_x: int = 0            # left pixel of the inspector
    rp_tabs_y: int = 0       # top of the inspector tab strip
    rp_tabs_h: int = 0       # height of the inspector tab strip
    rp_content_y: int = 0    # first pixel of scrollable inspector content
    rp_content_h: int = 0    # height of scrollable inspector content
    rp_bottom_y: int = 0     # bottom edge (status bar top)

    # ── Status bar ───────────────────────────────────────────────
    status_y: int = 0        # sh - status_h

    @classmethod
    def s(cls, px: int) -> int:
        """Scale a reference-resolution pixel value to current scale."""
        return round(px * cls.scale)

    @classmethod
    def set_palette_w(cls, w: int):
        """Set a user-chosen left-panel width (stored as fraction of sw)."""
        clamped = max(cls.PALETTE_MIN, min(cls.PALETTE_MAX, w))
        cls._user_palette_frac = clamped / max(1, cls.sw)
        # Force recompute on next frame
        cls.sw = -1

    @classmethod
    def set_inspector_w(cls, w: int):
        """Set a user-chosen right-panel width (stored as fraction of sw)."""
        clamped = max(cls.INSPECTOR_MIN, min(cls.INSPECTOR_MAX, w))
        cls._user_inspector_frac = clamped / max(1, cls.sw)
        cls.sw = -1

    @classmethod
    def update(cls, sw: int, sh: int):
        """Recompute all sizes for the current window dimensions."""
        if sw == cls.sw and sh == cls.sh:
            return
        cls.sw = sw
        cls.sh = sh

        # ── Scale factor ────────────────────────────────────────
        prev_scale = cls.scale
        cls.scale = max(0.75, sh / _REF_H)
        cls._fonts_dirty = abs(cls.scale - prev_scale) > 0.01

        _s = cls.s  # local alias for readability

        # Fixed chrome sizes (scaled)
        cls.menu_h = _s(22)
        cls.nav_h = _s(26)
        cls.status_h = _s(22)
        cls.toolbar_h = _s(24)
        cls.sidebar_w = 0

        # ── Scaled min/max clamps ───────────────────────────────
        cls.PALETTE_MIN = _s(80)
        cls.PALETTE_MAX = _s(360)
        cls.INSPECTOR_MIN = _s(160)
        cls.INSPECTOR_MAX = _s(440)
        cls.CANVAS_MIN = _s(200)

        # ── Left panel ──────────────────────────────────────────
        if cls._user_palette_frac is not None:
            computed = int(cls._user_palette_frac * sw)
            cls.palette_w = max(cls.PALETTE_MIN,
                                min(cls.PALETTE_MAX, computed))
        else:
            cls.palette_w = max(_s(130), min(_s(200), int(sw * 0.16)))
        cls.panel_w = cls.palette_w

        # ── Right panel ─────────────────────────────────────────
        if cls._user_inspector_frac is not None:
            computed = int(cls._user_inspector_frac * sw)
            cls.inspector_w = max(cls.INSPECTOR_MIN,
                                  min(cls.INSPECTOR_MAX, computed))
        else:
            cls.inspector_w = max(_s(210), min(_s(320), int(sw * 0.24)))

        # Ensure minimum canvas width — shrink panels if needed
        available = sw - cls.palette_w - cls.inspector_w
        if available < cls.CANVAS_MIN:
            excess = cls.CANVAS_MIN - available
            # Shrink inspector first, then palette
            shrink_insp = min(excess,
                              cls.inspector_w - cls.INSPECTOR_MIN)
            cls.inspector_w -= shrink_insp
            excess -= shrink_insp
            if excess > 0:
                cls.palette_w = max(cls.PALETTE_MIN,
                                    cls.palette_w - excess)

        # Canvas fills the remainder
        cls.canvas_x = cls.palette_w
        cls.canvas_y = cls.menu_h + cls.nav_h + cls.toolbar_h
        cls.canvas_w = max(cls.CANVAS_MIN,
                           sw - cls.palette_w - cls.inspector_w)
        cls.canvas_h = max(100, sh - cls.canvas_y - cls.status_h)

        # ── Common metrics ──────────────────────────────────────
        cls.row_h = _s(22)
        cls.item_h = _s(28)
        cls.header_h = _s(22)
        cls.field_h = _s(22)
        cls.swatch = _s(32)
        cls.thumb = _s(32)
        cls.pad_sm = max(2, _s(3))
        cls.pad_md = max(4, _s(6))
        cls.pad_lg = max(6, _s(10))
        cls.scroll_step = _s(28)
        cls.label_col = _s(70)
        cls.btn_h = _s(24)
        cls.border_r = max(2, _s(3))

        # ── Left-panel vertical regions (non-overlapping) ───────
        tab_btn_h = _s(26)                       # actual button height
        cls.panel_tab_h = tab_btn_h * 2 + cls.pad_sm + cls.pad_sm * 2
        cls.lp_tabs_y = cls.canvas_y + cls.pad_sm
        cls.lp_tabs_h = cls.panel_tab_h - cls.pad_sm
        cls.lp_content_y = cls.canvas_y + cls.panel_tab_h
        cls.lp_bottom_y = sh - cls.status_h
        cls.lp_content_h = cls.lp_bottom_y - cls.lp_content_y

        # ── Horizontal top bars ─────────────────────────────────
        cls.menu_y = 0
        cls.nav_y = cls.menu_h
        cls.toolbar_y = cls.menu_h + cls.nav_h

        # ── Right-panel (inspector) vertical regions ────────────
        cls.rp_x = sw - cls.inspector_w
        rp_tab_h = tab_btn_h                     # inspector has 1 row of tabs
        cls.rp_tabs_y = cls.canvas_y
        cls.rp_tabs_h = rp_tab_h
        cls.rp_content_y = cls.canvas_y + rp_tab_h
        cls.rp_bottom_y = sh - cls.status_h
        cls.rp_content_h = cls.rp_bottom_y - cls.rp_content_y

        # ── Status bar ──────────────────────────────────────────
        cls.status_y = sh - cls.status_h
