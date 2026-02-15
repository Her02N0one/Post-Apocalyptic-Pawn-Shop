"""systems.engine — Frame pipeline, input, entity spawning, and VFX.

Modules
-------
tick             — per-frame system orchestrator
input_manager    — raw input → intent mapping
entity_factory   — table-driven entity creation from TOML descriptors
particles        — lightweight particle VFX system
"""

from .tick import tick_systems, input_system, item_pickup_system  # noqa: F401
from .input_manager import InputManager, InputContext             # noqa: F401
from .entity_factory import (                                    # noqa: F401
    spawn_from_descriptor,
    spawn_zone_entities,
    ensure_combat_components,
)
from .particles import ParticleManager                           # noqa: F401
