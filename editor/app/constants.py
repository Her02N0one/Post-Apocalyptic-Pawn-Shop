"""editor/app/constants.py — Application-level configuration.

Window dimensions, panel widths, raycaster preview settings.
These are *not* 3D-editor tool constants (those live in editor.view_3d.constants).
"""

from __future__ import annotations

import math

# ── Window ────────────────────────────────────────────────────────
WINDOW_W      = 1600
WINDOW_H      = 900
WINDOW_TITLE  = "Zone Editor"

# ── Panel widths ──────────────────────────────────────────────────
LEFT_PANEL_W  = 280
RIGHT_PANEL_W = 250
MENU_BAR_H    = 22
STATE_BAR_H   = 32   # global state bar (single row: layer + view + actions)
STATUS_BAR_H  = 28

# ── Raycaster preview ────────────────────────────────────────────
RAY_RES_W     = 640
RAY_RES_H     = 360
RAY_FOV       = math.pi / 3

# ── Player movement (raycaster preview) ──────────────────────────
MOVE_SPEED     = 3.0
SPRINT_MULT    = 2.0
SLOW_MULT      = 0.3
EYE_HEIGHT     = 0.5
MAX_STEP_UP    = 0.5
HEAD_CLEARANCE = 0.4
CAM_LERP       = 8.0
