"""core/constants.py — Shared constants used across the codebase.

Centralises magic numbers so there's exactly one place to change them.

Unit System
-----------
All gameplay distances are measured in **tiles**, where:

    1 tile = 1 metre   (the canonical spatial unit)

Standard units used throughout the codebase:

    Distance / position     m       (metres)
    Speed                   m/s     (metres per second)
    Time (real)             s       (seconds)
    Time (game)             min     (game-minutes, see below)
    Health                  HP      (hit points)
    Damage (instant)        HP      (per hit or per second)
    Angles                  °       (degrees)
    Mass / weight           kg      (future — currently item counts)
    Counts                  —       (unitless)

Rendering converts to pixels via ``TILE_SIZE`` (px per tile).
No gameplay code should reference pixels — only the renderer.

Game Time Scale
~~~~~~~~~~~~~~~
``GameClock.time`` is in **real seconds** (incremented by ``dt``
each frame).  This is the single canonical time base for ALL systems:
per-frame brains, the off-screen scheduler, scheduled activities,
and hunger prediction.

``DAY_LENGTH`` real seconds = 1 in-game day.
``SECONDS_PER_GAME_MINUTE`` converts for display only (HUD clock).

Reference speeds (real-world → game):
    Walk        1.2–1.5 m/s (patrol_speed = 2.0 m/s — brisk walk)
    Jog         2.5–3.0 m/s (chase mult ×1.4 brings patrol up here)
    Run         5.0 m/s     (Player.speed — fast run)
    Sprint      7.5 m/s     (×1.5 mult on run — fit human sprint)
    Arrow/Bolt  50+ m/s     (game uses 12–18 m/s for dodge-able feel)

Note: perception ranges are compressed ~10× from real-world values
so they fit the 30×20 m museum arenas.  The *ratios* between tiers
are realistic — a gunshot IS ~4× louder than a shout in practice.

Detection Range Hierarchy (small → large):
     3 m   Peripheral vision (reflex zone)
     6 m   Melee hearing (swords clashing)
    10 m   Aggro radius / crime witness range
    15 m   Faction alert cascade / shout hearing
    18 m   Forward vision (clear line of sight)
    25 m   Gunshot hearing / leash radius
    30 m   LOD high-detail simulation zone
"""

# ── Unit scale ──────────────────────────────────────────────────────
TILE_METRES = 1.0  # 1 tile = 1 metre (canonical scale)

# ── Game-time conversion ────────────────────────────────────────────
DAY_LENGTH: float = 300.0              # real seconds per in-game day
SECONDS_PER_GAME_MINUTE: float = DAY_LENGTH / (24.0 * 60.0)  # ~0.2083 s

# Render
TILE_SIZE = 32

# ── Tile definitions ────────────────────────────────────────────────
# The canonical source for tile IDs, names, colours, and flags is
# ``core.tiles``.  We re-export the most commonly-used symbols here
# for backward compatibility.
from core.tiles import (                          # noqa: E402
    TF,
    TILE_COLORS,
    TILE_REGISTRY,
    SOLID_IDS,
    WALL_IDS,
    HALF_WALL_IDS,
    tile_def,
)

# Legacy scalar aliases (prefer ``tile_def(id)`` for new code)
TILE_VOID       = 0
TILE_GRASS      = 1
TILE_DIRT       = 2
TILE_STONE      = 3
TILE_WATER      = 4
TILE_WOOD_FLOOR = 5
TILE_WALL       = 6
TILE_SAND       = 7
TILE_RUBBLE     = 8
TILE_DOOR       = 9   # was TILE_TELEPORTER
TILE_WINDOW     = 10
TILE_FARMLAND   = 11
TILE_GATEWAY    = 12
TILE_CONCRETE   = 13
TILE_TILE_FLOOR = 14
TILE_METAL_WALL = 15
TILE_HALF_WALL  = 16
TILE_LOW_WALL   = 17
TILE_PILLAR     = 18
TILE_COUNTER_TOP = 19
TILE_RAILING    = 20

# Backward-compat alias
TILE_TELEPORTER = TILE_DOOR
