"""systems.offscreen — Off-screen event-driven scheduling infrastructure.

Provides the event queue, handlers, LOD bridge, and travel system that
keep entities alive when the player isn't looking.

Submodules
----------
scheduler    WorldScheduler — event priority queue
handlers     Event resolution functions for the scheduler
manager      WorldSim — top-level simulation orchestrator
lod          LOD promotion / demotion + per-frame sweep
travel       Route planning through the subzone graph
checkpoint   Subzone arrival evaluation
"""

# Lazy re-exports to avoid circular imports with systems.engine.
# The cycle: engine/__init__ → tick → offscreen.lod →
#   (triggers this __init__) → manager → lod → engine.entity_factory
#   → (triggers partially-loaded engine/__init__).
# By deferring imports to attribute access, the cycle never fires
# during module loading.

__all__ = ["WorldSim", "WorldScheduler", "lod_system"]

def __getattr__(name: str):
    if name == "WorldSim":
        from systems.offscreen.manager import WorldSim
        return WorldSim
    if name == "WorldScheduler":
        from systems.offscreen.scheduler import WorldScheduler
        return WorldScheduler
    if name == "lod_system":
        from systems.offscreen.lod import lod_system
        return lod_system
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
