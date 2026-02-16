"""scenes/lab — Developer lab scenes and exhibit plugins.

Submodules
----------
base        Shared TestScene base class
debug       Developer overlay (AI observer, ECS browser, event log)
gym         Movement & pathfinding test arena
zoo         Entity bestiary / inspector
museum      Interactive exhibit museum
picker      Scene-selection menu (F3)

exhibits/   Auto-discovered museum exhibit modules
"""

__all__ = [
    "base", "debug", "gym", "zoo", "museum", "picker",
    "exhibits",
]
