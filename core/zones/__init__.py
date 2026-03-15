"""core.zones — Zone data model, binary I/O, and compilation.

Submodules
----------
zone            Zone/Portal/OverlayWall data classes, load_zone(), list_zones()
objects         Typed dataclasses for zone placeables (Quad, Box, Curve, etc.)
cell_layer      CellLayer — per-cell surface layer abstraction
tex_priority    Canonical texture resolution priority chain
migration       Zone schema versioning and migration pipeline
validation      Structured zone validation pass (validate_zone)
compiler        compile_zone_to_arrays() — Zone → flat numpy arrays
io              save_binary_zone() / load_binary_zone() — chunked binary format
format          Binary zone format constants (magic number, chunk IDs, NAV bits)
game_registry   GameRegistry — str↔uint16 persistent asset ID mappings

Re-exports
----------
All public names from ``zone`` are re-exported here for convenience::

    from core.zones import Zone, load_zone, list_zones
"""

from core.zones.zone import (          # noqa: F401 — re-export
    Zone,
    Portal,
    OverlayWall,
    load_zone,
    list_zones,
    find_spawn,
)
from core.zones.objects import (       # noqa: F401 — re-export
    Quad,
    Box,
    Curve,
    CF_TRANSPARENT,
    RenderPortal,
    EntityDescriptor,
    serialize_objects,
)
from core.zones.cell_layer import CellLayer  # noqa: F401
from core.zones.tex_priority import (  # noqa: F401
    resolve_wall_texture,
    resolve_floor_ceil_texture,
    FACE_NAMES,
    FLOOR_STEP_DEFAULT,
    CEIL_STEP_DEFAULT,
)
from core.zones.migration import ZONE_SCHEMA_VERSION  # noqa: F401
from core.zones.game_registry import GameRegistry  # noqa: F401
from core.zones.validation import (     # noqa: F401
    validate_zone,
    ZoneIssue,
)
from core.paths import ZONES_DIR  # noqa: F401 — re-export for tests
