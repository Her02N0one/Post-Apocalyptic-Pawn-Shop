"""core/constants.py — Shared constants used across the codebase.

Centralises magic numbers so there's exactly one place to change them.

Unit System
-----------
All gameplay distances are measured in **tiles**, where:

    1 tile = 1 metre

This applies to positions, speeds (m/s), ranges, radii, etc.
Rendering converts to pixels via ``TILE_SIZE`` (px per tile).

Reference speeds (real-world):
    Walk        ~1.4 m/s    (patrol speed 2.0 is a brisk walk)
    Jog         ~2.5 m/s    (chase multiplier brings this up)
    Sprint      ~4–5 m/s    (lunge / flee bursts)
    Arrow       ~50 m/s     (we use 12-18 for gameplay feel)

Reference distances:
    Melee reach      1.0–1.5 m     (sword/spear)
    Short range      8–12 m        (pistol / bow effective)
    Medium range     15–25 m       (rifle / longbow)
    Hearing          10–15 m       (alert radius)
    Vision (open)    20–30 m       (clear line of sight)
"""

# ── Unit scale ──────────────────────────────────────────────────────
TILE_METRES = 1.0  # 1 tile = 1 metre (canonical scale)

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
