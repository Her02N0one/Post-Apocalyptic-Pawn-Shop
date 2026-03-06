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
COL_TOOL_ENTITY  = (60, 200, 255)
COL_TOOL_BOX     = (255, 180, 60)
COL_TOOL_LAYER2  = (200, 160, 255)
COL_TOOL_QUAD    = (255, 140, 180)
COL_TOOL_PORTAL  = (80, 255, 220)
COL_TOOL_CURVE   = (255, 200, 100)
COL_TOOL_OVERLAY = (160, 220, 180)
COL_FACE_HL      = (255, 255, 255, 90)  # face highlight overlay alpha

# ─── Tool definitions ─────────────────────────────────────────────
# ─── Stamp tool colour ────────────────────────────────────────────
COL_TOOL_STAMP   = (180, 140, 255)

# ─── Primary Modes (state machine) ────────────────────────────────
# The editor is a strict state machine:
#   Elevation (Layer) → Mode → Selection → Operation
#
# Four foundational modes based on user intent:
MODE_ARCH   = "arch"     # Architecture: grid BSP, walkable space
MODE_SURF   = "surface"  # Surface: texturing faces / materials
MODE_PROPS  = "props"    # Props & Geometry: freeform set dressing
MODE_LOGIC  = "logic"    # Logic: entities, portals, gameplay

MODES = (MODE_ARCH, MODE_SURF, MODE_PROPS, MODE_LOGIC)

MODE_LABELS = {
    MODE_ARCH:  "ARCH",
    MODE_SURF:  "SURFACE",
    MODE_PROPS: "PROPS",
    MODE_LOGIC: "LOGIC",
}

MODE_ICONS = {
    MODE_ARCH:  "\u25a4",   # ▤
    MODE_SURF:  "\u25a9",   # ▩
    MODE_PROPS: "\u25a7",   # ▧
    MODE_LOGIC: "\u235f",   # ⍟
}

MODE_COLORS = {
    MODE_ARCH:  (220, 160, 60),   # amber
    MODE_SURF:  (200, 120, 220),  # purple
    MODE_PROPS: (255, 180, 60),   # orange
    MODE_LOGIC: (60, 200, 255),   # cyan
}

MODE_DESCRIPTIONS = {
    MODE_ARCH:  "Define walkable BSP: Z-heights, walls, segments",
    MODE_SURF:  "Paint faces: textures, materials, lighting",
    MODE_PROPS: "Place geometry: prisms, quads, curves",
    MODE_LOGIC: "Place logic: entities, portals, spawners",
}

# Mode → available sub-tools mapping
MODE_TOOLS = {
    MODE_ARCH:  ("sculpt", "segment"),
    MODE_SURF:  ("paint",),
    MODE_PROPS: ("box", "quad", "curve", "overlay"),
    MODE_LOGIC: ("entity", "portal"),
}

# Mode → selection target description
MODE_SELECTION_TARGET = {
    MODE_ARCH:  "2D Grid Cells",
    MODE_SURF:  "Individual Faces (N/S/E/W/Floor/Ceil)",
    MODE_PROPS: "Prop Objects",
    MODE_LOGIC: "Logic Nodes",
}

# ─── View modes (viewport rendering) ──────────────────────────────
VIEW_LIT      = "lit"       # Normal textured/coloured view
VIEW_PATHING  = "pathing"   # Pathable surface heatmap
VIEW_MODES    = (VIEW_LIT, VIEW_PATHING)

VIEW_LABELS = {
    VIEW_LIT:     "Lit",
    VIEW_PATHING: "Pathing",
}

# ─── Paste masking flags ──────────────────────────────────────────
PASTE_MASK_HEIGHTS   = "heights"
PASTE_MASK_TEXTURES  = "textures"
PASTE_MASK_ENTITIES  = "entities"
PASTE_MASK_SEGMENTS  = "segments"
PASTE_MASK_LIGHTING  = "lighting"
PASTE_MASK_ALL = (
    PASTE_MASK_HEIGHTS, PASTE_MASK_TEXTURES,
    PASTE_MASK_ENTITIES, PASTE_MASK_SEGMENTS,
    PASTE_MASK_LIGHTING,
)

# Core tools (F-keys / Tab) + utility modes (letter keys)
TOOLS = ("sculpt", "paint", "segment", "entity", "box")
UTIL_TOOLS = ("select", "stamp",
              "quad", "portal", "curve", "overlay")
ALL_TOOLS = TOOLS + UTIL_TOOLS

TOOL_LABELS = {
    "sculpt":  "SCULPT",
    "paint":   "PAINT",
    "segment": "DETAIL",
    "entity":  "ENTITY",
    "box":     "PRISM",
    "select":  "SELECT",
    "stamp":   "PRESET",
    "quad":    "QUAD",
    "portal":  "PORTAL",
    "curve":   "CURVE",
    "overlay": "OVRWALL",
}
TOOL_COLORS = {
    "sculpt":  COL_TOOL_WALL,
    "paint":   COL_TOOL_PAINT,
    "segment": COL_TOOL_SEGMENT,
    "entity":  COL_TOOL_ENTITY,
    "box":     COL_TOOL_BOX,
    "select":  COL_TOOL_SELECT,
    "stamp":   COL_TOOL_STAMP,
    "quad":    COL_TOOL_QUAD,
    "portal":  COL_TOOL_PORTAL,
    "curve":   COL_TOOL_CURVE,
    "overlay": COL_TOOL_OVERLAY,
}
# Number-key → select tool within current mode (handled in _on_keydown)
# 1..N = tools in MODE_TOOLS[mode], Tab = cycle

# Letter key → utility mode (toggles in/out)
# NOTE: these must NOT collide with tool-specific keys (H=wall, etc.)
# or with Ctrl combos (Ctrl+Y = redo).
UTIL_KEYS = {
    pygame.K_b: "select",
    pygame.K_p: "stamp",
    pygame.K_i: "quad",        # was H — freed H for wall conversion
    pygame.K_o: "portal",      # was Y — freed Ctrl+Y for redo
    pygame.K_SEMICOLON: "curve",
    pygame.K_l: "overlay",
}
# Hotbar: 10 texture quick-access slots
# With new layout: bare 6-0 works directly, Alt+1-0 works for all 10,
# bare 1-5 are now tool selection.
HOTBAR_SIZE = 10

TOOL_HINTS = {
    "sculpt": {
        "title": "Sculpt",
        "actions": {
            "selection": {
                "LMB": "Raise floor / Sh=lower ceil",
                "RMB": "Lower floor / Sh=raise ceil",
                "Scroll": "Adjust floor / Sh=ceil",
                "T": "Add ceilings  Sh+T=remove",
                "H": "Make wall  Sh+H=open",
                "L": "Flatten  Sh+L=ceilings",
            },
            "floor": {
                "LMB": "Raise floor  Sh=lower ceil",
                "RMB": "Lower floor  Sh=raise ceil",
                "Scroll": "Extend",
                "Sh+Scrl": "Snap grid",
            },
            "ceiling": {
                "LMB": "Lower ceiling (room shorter)",
                "RMB": "Raise ceiling (room taller)",
                "Scroll": "Raise/lower ceiling",
                "Ct+Scrl": "Extend/retract wall above",
                "Sh+Scrl": "Snap grid",
            },
            "layer2": {
                "LMB": "Raise floor2",
                "Sh+LMB": "Raise ceil2",
                "Ct+LMB": "Remove layer 2",
                "RMB": "Lower floor2",
                "Sh+RMB": "Lower ceil2",
                "Scroll": "Cycle texture",
            },
            "none": {
                "LMB": "Aim at surface",
            },
        },
        "keys": "Sh=ceiling  T=add ceil  R=reset  Del=clear  G=snap  X=layer2  H=wall  L=flatten",
    },
    "paint": {
        "title": "Paint",
        "actions": {
            "any": {
                "LMB": "Paint face / prism face / quad",
                "Sh+LMB": "Paint whole cell / all prism faces",
                "Ct+LMB": "Flood fill",
                "RMB": "Erase texture",
                "Sh+RMB": "Erase all prism faces",
                "Ct+RMB": "Flood clear",
                "MMB": "Eyedropper",
                "Scroll": "Cycle palette",
            },
        },
        "keys": "T=tile picker  Scroll=cycle palette",
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
        "title": "Select  (B=exit/clear)",
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
                "Scroll": "Adjust floor / Sh=ceil",
                "T": "Add ceilings  Sh+T=remove",
                "H": "Make wall  Sh+H=open",
                "L": "Flatten  Sh+L=ceilings",
                "Del": "Reset cells",
            },
        },
        "keys": "X=floor/ceil  T=ceil  H=wall  L=flatten  Ct+A=all  B=exit/clear",
    },
    "stamp": {
        "title": "Preset  (P=exit)",
        "actions": {
            "any": {
                "LMB": "Apply preset",
                "RMB": "Capture cell → name",
                "Scroll": "Cycle presets",
            },
        },
        "keys": "M=cycle mode  P=exit preset",
    },
    "entity": {
        "title": "Entity",
        "actions": {
            "any": {
                "LMB": "Place / select entity",
                "LMB(sel)": "Move selected",
                "RMB": "Deselect / delete aimed",
                "Scroll": "Cycle entity type",
                "Sh+Scrl": "Rotate selected",
            },
        },
        "keys": "Del=delete  T=cycle state  Esc=deselect",
    },
    "box": {
        "title": "Prism",
        "actions": {
            "unselected": {
                "LMB": "Place / select prism",
                "RMB": "Delete aimed prism",
                "Scroll": "Width",
                "Sh+Scrl": "Depth",
                "Ct+Scrl": "Height",
            },
            "selected": {
                "LMB": "Move selected (stacks)",
                "RMB": "Deselect",
                "Scroll": "Shift Z up/down",
                "Sh+Scrl": "Fine rotate (15°)",
                "Ct+Scrl": "Adjust height",
            },
        },
        "keys": "R=rotate 90°  G=snap  Del=delete  Esc=deselect",
    },

    "quad": {
        "title": "Quad  (I=exit)",
        "actions": {
            "any": {
                "LMB": "Place / select quad",
                "LMB(sel)": "Move selected",
                "RMB": "Deselect / delete",
                "Scroll": "Cycle texture",
                "Sh+Scrl": "Rotate (15\u00b0)",
                "Ct+Scrl": "Adjust width",
            },
        },
        "keys": "Del=delete  Esc=deselect  MMB=toggle 2-sided",
    },
    "portal": {
        "title": "Portal  (O=exit)",
        "actions": {
            "any": {
                "LMB": "Place portal on face",
                "RMB": "Delete portal",
                "Scroll": "Cycle portals",
            },
        },
        "keys": "Edit dest in inspector  O=exit portal",
    },
    "curve": {
        "title": "Curve  (;=exit)",
        "actions": {
            "any": {
                "LMB": "Place / select curve",
                "LMB(sel)": "Move selected",
                "RMB": "Deselect / delete",
                "Scroll": "Adjust radius",
                "Sh+Scrl": "Arc start angle",
                "Ct+Scrl": "Arc end angle",
            },
        },
        "keys": "Del=delete  Esc=deselect  MMB=paint texture",
    },
    "overlay": {
        "title": "Overlay Wall  (L=exit)",
        "actions": {
            "any": {
                "LMB": "Place start / end / select",
                "LMB(sel)": "Move selected wall",
                "RMB": "Cancel / deselect / delete",
                "Scroll": "Cycle texture",
                "Sh+Scrl": "Adjust height",
            },
        },
        "keys": "Del=delete  Esc=deselect  MMB=toggle transparent  G=snap grid",
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
