"""editor/view_3d — 3D zone sculpting editor package.

Re-exports every public name so existing ``from editor.view_3d import …``
statements continue to work unchanged.
"""

# Selection layer (new — universal selection system)
from editor.view_3d.selection import SelectionState  # noqa: F401

# Unified object layer
from editor.view_3d.objects import ObjectLayer  # noqa: F401

# Math helpers
from editor.view_3d.math3d import (          # noqa: F401
    _perspective, _mat4_mul, _build_view_matrix, _project, _project_line,
    NEAR_CLIP, FAR_CLIP, FOV_DEG,
)

# Picking / hit result
from editor.view_3d.picking import (         # noqa: F401
    _ray_vs_aabb, _CellHit,
    _FACE_NAMES_X, _FACE_NAMES_Y, _FACE_NAMES_Z,
)

# Editor class + config constants
from editor.view_3d.editor import (          # noqa: F401
    Zone3DEditor,
    SNAP_Y_OPTIONS, DEFAULT_SNAP_Y, CAM_H,
    COL_BG, COL_GRID, COL_GRID_EDGE, COL_CEIL_GRID,
    COL_BLOCK_SEL, COL_GHOST, COL_GHOST_BAD,
    COL_CROSSHAIR,
    COL_AXIS_X, COL_AXIS_Y, COL_AXIS_Z,
    COL_HUD_BG, COL_HUD_TEXT, COL_HUD_VAL,
    COL_HUD_TITLE, COL_HUD_WARN, COL_EDGE_DIM,
    COL_SEG_LINE, COL_SEG_AIM,
    COL_WALL_DEF, COL_FLOOR_DEF, COL_CEIL_DEF,
    COL_TOOL_WALL, COL_TOOL_FLOOR, COL_TOOL_CEILING,
    COL_TOOL_PAINT, COL_TOOL_SEGMENT, COL_FACE_HL,
    TOOLS, UTIL_TOOLS, ALL_TOOLS,
    TOOL_LABELS, TOOL_COLORS, UTIL_KEYS,
    HOTBAR_SIZE,
    TOOL_HINTS,
    MODES, MODE_LABELS, MODE_ICONS, MODE_COLORS,
    MODE_DESCRIPTIONS, MODE_TOOLS, MODE_SELECTION_TARGET,
    VIEW_LIT, VIEW_PATHING, VIEW_MODES, VIEW_LABELS,
    PASTE_MASK_ALL,
    FLY_SPEED, FLY_SPRINT,
    MOUSE_SENS, KB_TURN_SPEED,
    _ensure_palette,
)
