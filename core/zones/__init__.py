"""core.zones — Zone data model, binary I/O, and compilation.

Submodules
----------
zone            Zone/Portal/OverlayWall data classes, load_zone(), list_zones()
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
from core.zones.game_registry import GameRegistry  # noqa: F401
from core.paths import ZONES_DIR  # noqa: F401 — re-export for tests
