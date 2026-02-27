"""editor/view_3d/constants.py — All configuration constants for the 3D editor."""

from __future__ import annotations

import pygame
from core.tiles import TILE_REGISTRY

# ─── Snap-Y presets ───────────────────────────────────────────────
SNAP_Y_OPTIONS = (0.0625, 0.125, 0.25, 0.5, 1.0)
DEFAULT_SNAP_Y = 0.25
CAM_H = 0.5  # eye-level height matching the C renderer constant

# ─── Height limits ────────────────────────────────────────────────
FLOOR_MIN = -5.0   # lowest floor (deep pit)
FLOOR_MAX = 10.0   # highest floor
CEIL_MIN  = -5.0   # lowest ceiling (should be >= floor)
CEIL_MAX  = 10.0   # highest ceiling (non-sky)
SKY_HEIGHT = 10.0  # sentinel: ceiling >= this = open sky
DEFAULT_FLOOR = 0.0
DEFAULT_CEIL  = 1.0

# ─── Colours ──────────────────────────────────────────────────────
COL_BG         = (18, 18, 24)
COL_GRID       = (50, 50, 65)
COL_GRID_EDGE  = (80, 80, 100)
COL_CEIL_GRID  = (35, 35, 55)
COL_BLOCK_SEL  = (255, 230, 60)
COL_GHOST      = (60, 210, 100)
COL_GHOST_BAD  = (230, 50, 50)
COL_CROSSHAIR  = (255, 255, 255)
COL_AXIS_X     = (220, 60, 60)
COL_AXIS_Y     = (60, 220, 60)
COL_AXIS_Z     = (60, 60, 220)
COL_HUD_BG     = (0, 0, 0, 200)
COL_HUD_TEXT   = (220, 220, 200)
COL_HUD_VAL    = (120, 220, 255)
COL_HUD_TITLE  = (255, 200, 80)
COL_HUD_WARN   = (255, 100, 100)
COL_EDGE_DIM   = (60, 60, 70)
COL_SEG_LINE   = (255, 160, 40)   # segment boundary markers on walls
COL_SEG_AIM    = (255, 220, 80)   # aimed segment highlight

# Default box colours when texture has no TILE_COLORS entry
COL_WALL_DEF   = (200, 80, 180)  # distinctive magenta — untextured walls stand out
COL_FLOOR_DEF  = (140, 120, 100)
COL_CEIL_DEF   = (100, 105, 120)

# ─── Tool colours (per-tool crosshair + face highlight) ───────────
COL_TOOL_WALL    = (220, 160, 60)
COL_TOOL_FLOOR   = (100, 200, 120)
COL_TOOL_CEILING = (120, 160, 220)
COL_TOOL_PAINT   = (200, 120, 220)
COL_TOOL_SEGMENT = (255, 180, 60)
COL_TOOL_SELECT  = (255, 220, 100)
COL_FACE_HL      = (255, 255, 255, 90)  # face highlight overlay alpha

# ─── Tool definitions ─────────────────────────────────────────────
# ─── Stamp tool colour ────────────────────────────────────────────
COL_TOOL_STAMP   = (180, 140, 255)

# 3 core tools (F-keys / Tab) + 2 utility modes (letter keys)
TOOLS = ("sculpt", "paint", "segment")
UTIL_TOOLS = ("select", "stamp")
ALL_TOOLS = TOOLS + UTIL_TOOLS

TOOL_LABELS = {
    "sculpt":  "SCULPT",
    "paint":   "PAINT",
    "segment": "DETAIL",
    "select":  "SELECT",
    "stamp":   "MODEL",
}
TOOL_COLORS = {
    "sculpt":  COL_TOOL_WALL,
    "paint":   COL_TOOL_PAINT,
    "segment": COL_TOOL_SEGMENT,
    "select":  COL_TOOL_SELECT,
    "stamp":   COL_TOOL_STAMP,
}
# F-key → core tool
TOOL_KEYS = {
    pygame.K_F5: "sculpt",
    pygame.K_F6: "paint",
    pygame.K_F7: "segment",
}
# Letter key → utility mode (toggles in/out)
UTIL_KEYS = {
    pygame.K_b: "select",
    pygame.K_p: "stamp",
}
# Hotbar: 10 texture quick-access slots (keys 1-0)
HOTBAR_SIZE = 10
HOTBAR_KEYS = {
    pygame.K_1: 0, pygame.K_2: 1, pygame.K_3: 2, pygame.K_4: 3, pygame.K_5: 4,
    pygame.K_6: 5, pygame.K_7: 6, pygame.K_8: 7, pygame.K_9: 8, pygame.K_0: 9,
}

TOOL_HINTS = {
    "sculpt": {
        "title": "Sculpt",
        "actions": {
            "floor": {
                "LMB": "Raise floor",
                "RMB": "Lower floor",
                "Scroll": "Extend",
                "Sh+Scrl": "Snap grid",
            },
            "ceiling": {
                "LMB": "Lower ceiling",
                "RMB": "Raise ceiling",
                "Scroll": "Upper wall",
                "Sh+Scrl": "Snap grid",
            },
            "none": {
                "LMB": "Aim at surface",
            },
        },
        "keys": "C=ceil  R=reset  Del=clear  G=snap  V=walls",
    },
    "paint": {
        "title": "Paint",
        "actions": {
            "any": {
                "LMB": "Paint face (hold=drag)",
                "Sh+LMB": "Paint whole cell",
                "Ct+LMB": "Flood fill",
                "RMB": "Erase texture",
                "Ct+RMB": "Flood clear",
                "MMB": "Eyedropper",
                "Scroll": "Cycle palette",
            },
        },
        "keys": "T=tile picker  1-0=hotbar",
    },
    "segment": {
        "title": "Detail",
        "actions": {
            "any": {
                "LMB": "Split face at line",
                "RMB": "Merge (red line)",
                "MMB": "Paint segment",
                "Scroll": "Cycle palette",
            },
        },
        "keys": "Aim at wall/step face",
    },
    "select": {
        "title": "Select  (B=exit)",
        "actions": {
            "none": {
                "LMB": "First corner",
                "Scroll": "Cycle palette",
            },
            "started": {
                "LMB": "Second corner",
                "Scroll": "Cycle palette",
                "Esc": "Cancel",
            },
            "active": {
                "LMB": "Fill texture",
                "RMB": "Clear textures",
                "Scroll": "Adjust height",
                "Del": "Reset cells",
                "Esc": "Deselect",
            },
        },
        "keys": "X=floor/ceil  B=exit select",
    },
    "stamp": {
        "title": "Model  (P=exit)",
        "actions": {
            "any": {
                "LMB": "Apply preset",
                "RMB": "Capture cell → name",
                "Scroll": "Cycle presets",
            },
        },
        "keys": "M=cycle mode  P=exit model",
    },
}

# ─── Face index mapping (N/S/E/W → 0/1/2/3) ─────────────────────
FACE_IDX = {"north": 0, "south": 1, "east": 2, "west": 3}

# ─── Face definitions for filled-box rendering ────────────────────
# (corner_indices, outward_normal, brightness_multiplier)
_FACE_DEFS: list[tuple[tuple[int, ...], tuple[int, int, int], float]] = [
    ((4, 5, 6, 7), ( 0,  1,  0), 1.00),  # top    +Y
    ((0, 3, 2, 1), ( 0, -1,  0), 0.55),  # bottom -Y
    ((0, 1, 5, 4), ( 0,  0, -1), 0.65),  # north  -Z
    ((2, 3, 7, 6), ( 0,  0,  1), 0.80),  # south  +Z
    ((0, 4, 7, 3), (-1,  0,  0), 0.50),  # west   -X
    ((1, 2, 6, 5), ( 1,  0,  0), 0.70),  # east   +X
]

# ─── Camera config ────────────────────────────────────────────────
from editor.fly_camera import (
    MOUSE_SENS as _MOUSE_SENS,
    KB_TURN_SPEED as _KB_TURN_SPEED,
)

FLY_SPEED      = 6.0
FLY_SPRINT     = 2.5
MOUSE_SENS     = _MOUSE_SENS    # from fly_camera (canonical)
KB_TURN_SPEED  = _KB_TURN_SPEED  # from fly_camera (canonical)

# ── Texture palette (populated from registry on first use) ────────
_TEX_PALETTE: list[str] = []


def _ensure_palette() -> list[str]:
    global _TEX_PALETTE
    if not _TEX_PALETTE:
        walls = sorted(k for k, td in TILE_REGISTRY.items() if td.wall)
        floors = sorted(k for k, td in TILE_REGISTRY.items()
                        if not td.wall and not td.liquid)
        rest = sorted(k for k in TILE_REGISTRY
                      if k not in walls and k not in floors)
        _TEX_PALETTE = walls + floors + rest
        if not _TEX_PALETTE:
            _TEX_PALETTE = ["brick_wall"]
    return _TEX_PALETTE
