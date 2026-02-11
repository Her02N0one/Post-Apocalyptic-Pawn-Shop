"""core/constants.py — Shared constants used across the codebase.

Centralises magic numbers so there's exactly one place to change them.
"""

# Tile IDs  (must match TILE_COLORS and data in *.nbt files)
TILE_VOID       = 0
TILE_GRASS      = 1
TILE_DIRT       = 2
TILE_STONE      = 3
TILE_WATER      = 4
TILE_WOOD_FLOOR = 5
TILE_WALL       = 6
TILE_TELEPORTER = 9

# Render
TILE_SIZE = 32

# Simple tile palette — index → color
TILE_COLORS = {
    0: (40, 40, 40),       # void
    1: (50, 80, 40),       # grass
    2: (80, 70, 50),       # dirt
    3: (60, 60, 70),       # stone
    4: (30, 60, 90),       # water
    5: (70, 50, 35),       # wood floor
    6: (90, 90, 90),       # wall
    9: (180, 20, 180),     # teleporter
}
