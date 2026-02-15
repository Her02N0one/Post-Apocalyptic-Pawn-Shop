"""systems.movement — Spatial movement, physics, and navigation.

Modules
-------
physics      — per-frame movement, tile collision, entity separation
pathfinding  — A* navigation with tile penalties and clearance
"""

from .physics import movement_system                            # noqa: F401
from .pathfinding import find_path, path_next_waypoint          # noqa: F401
