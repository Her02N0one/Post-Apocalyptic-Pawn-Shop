"""components.resources — World-level singletons (not per-entity)."""

from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class GameClock:
    """Monotonic game time — accumulated ``dt`` since session start.

    Used as a single source of truth for timestamp-based expiry,
    brain throttling, and any system that needs absolute game time.
    Updated once per frame in the scene's ``update()``.
    """
    time: float = 0.0


@dataclass
class Camera:
    x: float = 0.0
    y: float = 0.0
    zoom: float = 1.0


@dataclass
class SpawnInfo:
    """Lightweight metadata used for abstract NPCs and spawning.

    - `zone`: logical zone name the NPC belongs to
    - `abstract`: whether the NPC is stored in an abstract (low-LOD) form
    - `spawn_radius`: rough radius used when recrystallizing a precise position
    """
    zone: str = "overworld"
    abstract: bool = True
    spawn_radius: float = 12.0


@dataclass
class Lod:
    """Level of detail state for an entity.

    Values: 'low', 'medium', 'high'
    ``transition_until`` is the absolute GameClock time at which an
    entity that just transitioned to high LOD finishes its "orienting"
    grace period and starts normal brain execution.
    """
    level: str = "low"
    # chunk coordinate the entity currently belongs to (for medium/high LOD calc)
    chunk: tuple[int, int] = (0, 0)
    # Grace period: entity is "orienting" until this game-time
    transition_until: float = 0.0


@dataclass
class ZoneMetadata:
    """Zone metadata resource for systems to read map/chunk sizes."""
    name: str = "overworld"
    width: int = 0
    height: int = 0
    chunk_size: int = 16


@dataclass
class Player:
    """Marks the player entity."""
    speed: float = 80.0        # pixels per second


# ── System-tick timers (previously module-level mutable state) ───────

@dataclass
class LodTimer:
    """Tracks the last time the LOD system ran its sweep."""
    last_time: float = 0.0


@dataclass
class RefillTimers:
    """Per-container refill timestamps for the storehouse system."""
    timers: dict[int, float] = field(default_factory=dict)

