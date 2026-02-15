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

from systems.offscreen.manager import WorldSim
from systems.offscreen.scheduler import WorldScheduler
from systems.offscreen.lod import lod_system

__all__ = ["WorldSim", "WorldScheduler", "lod_system"]
