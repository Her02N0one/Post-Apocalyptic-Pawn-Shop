"""core.tiles — TOML-backed tile registry package.

    from core.tiles import tile_def, TF, TileDef, TILE_REGISTRY
"""

# Types & enums
from core.tiles.types import (                                # noqa: F401
    TileType, TF, TileDef,
    _TYPE_FLAGS, _TYPE_DEFAULT_HEIGHT,
    _FLAG_MAP, _PROP_FLAG_MAP,
    _flags_from_names, _flags_to_names, _type_from_flags,
    FACE_WALL_SLOTS, FACE_TOP_SLOT, FACE_ALL_SLOTS, TILE_FACE_SLOTS,
    _ROT_FRONT, _ROT_BACK,
)

# Registry & LUTs
from core.tiles.registry import (                             # noqa: F401
    TILE_TEX_DIR, TILES_TOML_DIR,
    TC_TERRAIN, TC_FLOORS, TC_WALLS, TC_OPENINGS,
    TC_BARRIERS, TC_PLATFORMS, TC_CUSTOM,
    TILE_CATEGORIES,
    TILE_REGISTRY, tile_def,
    SOLID_IDS, WALL_IDS, HALF_WALL_IDS, PLATFORM_IDS, DOOR_IDS,
    TILE_COLORS, TILE_NAMES,
    rebuild_derived,
    tiles_by_category, tiles_by_type,
    tile_str_to_int, tile_int_to_str, grid_to_ints,
    color_lut, solid_int_set,
    wall_lut, half_wall_lut, platform_lut, hs_lut,
    transparent_lut, thin_wall_lut, tall_wall_lut, alt_tex_lut,
)

# TOML I/O
from core.tiles.io import (                                   # noqa: F401
    _tile_toml_path, _parse_tile_toml, _load_tiles_toml,
    _save_tile_toml, save_tiles, save_tile,
)

# CRUD operations
from core.tiles.crud import (                                 # noqa: F401
    register_tile, update_tile, delete_tile,
    add_category, remove_category,
    _next_tile_key,
)


# ═══════════════════════════════════════════════════════════════════
#  Bootstrap — runs once at import time
# ═══════════════════════════════════════════════════════════════════

def _bootstrap() -> None:
    """Load tiles from TOML (assets/models/tiles/)."""
    if _load_tiles_toml():
        return
    # Minimal fallback
    TILE_REGISTRY["void"] = TileDef(
        "void", "Void", (40, 40, 40),
        type=TileType.WALL,
        flags=TF.SOLID | TF.WALL,
    )
    rebuild_derived()


_bootstrap()

# Re-bind derived frozensets that were empty before _bootstrap ran.
# The ``from … import`` above captured the initial empty values;
# ``rebuild_derived()`` reassigned them in registry.py's namespace.
from core.tiles.registry import (                             # noqa: F811,E402
    SOLID_IDS, WALL_IDS, HALF_WALL_IDS, PLATFORM_IDS, DOOR_IDS,
    TILE_COLORS, TILE_NAMES,
)
