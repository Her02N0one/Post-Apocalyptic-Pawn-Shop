"""components.ai — Brain, patrol, threat, attack config, memory, goals, tasks."""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Brain:
    """Entity AI controller — minimal.

    ``kind`` selects non-combat default behaviour ("wander", "villager", …).
    ``state`` is an opaque dict brain functions use across ticks.
    ``active`` must be True for the brain runner to execute.

    Combat behaviour is driven entirely by Threat + AttackConfig presence,
    NOT by the kind string.
    """
    kind: str = "wander"
    state: dict = field(default_factory=dict)
    active: bool = False          # off by default — opt-in


@dataclass
class HomeRange:
    """Wander / patrol envelope.

    Attached to any entity that moves on its own.
    ``origin_x/y`` are set to spawn position on first tick if zero.
    ``radius`` is the leash around origin.
    ``speed`` is tiles/sec while patrolling.
    """
    origin_x: float = 0.0
    origin_y: float = 0.0
    radius: float = 5.0
    speed: float = 2.0


@dataclass
class Threat:
    """Perception and engagement parameters.

    Attached to entities that detect and react to hostiles.
    ``aggro_radius`` — detection range (tiles).
    ``leash_radius`` — max chase distance from spawn.
    ``flee_threshold`` — HP ratio below which entity flees (0 = never flee).
    ``sensor_interval`` — seconds between expensive sensor sweeps.
    ``last_sensor_time`` — absolute GameClock.time of last sensor run.
    """
    aggro_radius: float = 8.0
    leash_radius: float = 15.0
    flee_threshold: float = 0.2
    sensor_interval: float = 0.1
    last_sensor_time: float = 0.0


@dataclass
class AttackConfig:
    """How an entity fights.

    ``attack_type`` — "melee" or "ranged".
    ``range`` — melee reach or ranged standoff distance (tiles).
    ``cooldown`` — seconds between attacks.
    ``last_attack_time`` — absolute GameClock.time of last attack.
    ``accuracy`` — 0.0–1.0 projectile accuracy (1 = perfect).  Used by
                   ``npc_ranged_attack`` when no Equipment/ItemRegistry.
    ``proj_speed`` — projectile speed (tiles/sec) when no weapon item.
    """
    attack_type: str = "melee"
    range: float = 1.2
    cooldown: float = 0.5
    last_attack_time: float = 0.0
    accuracy: float = 0.85
    proj_speed: float = 14.0


@dataclass
class VisionCone:
    """Directional perception for high-LOD AI entities.

    ``fov_degrees``      — total field-of-view angle (e.g. 120 = ±60° from facing).
    ``view_distance``    — forward detection range (tiles).
    ``peripheral_range`` — omnidirectional close-range awareness (tiles).
                           Enemies inside this radius are always detected
                           regardless of facing direction.

    When present alongside ``Threat``, combat_engagement uses the cone
    for idle→chase transitions instead of the simple radius check.
    ``Threat.aggro_radius`` still serves as the absolute max range cap.
    """
    fov_degrees: float = 120.0
    view_distance: float = 12.0
    peripheral_range: float = 4.0


@dataclass
class Task:
    """Simple task assigned to an entity.

    type: e.g. 'farm'
    tx, ty: target tile coords
    duration: seconds required to complete
    progress: seconds already worked
    """
    type: str = ""
    tx: int = 0
    ty: int = 0
    duration: float = 1.0
    progress: float = 0.0
    # If >0 this task is sleeping until the given absolute time (time.time()).
    # While sleeping the entity need not be ticked; the task is considered
    # to be progressing off-line and will be completed when wake time arrives.
    sleep_until: float = 0.0


# ── Minecraft-style AI components ────────────────────────────────────

@dataclass
class Memory:
    """Typed key-value store for AI entities.

    Sensors write observations here; goals read them.
    Supports TTL-based auto-expiry keyed to ``GameClock.time``.
    """
    data: dict[str, Any] = field(default_factory=dict)
    expiry: dict[str, float] = field(default_factory=dict)

    def set(self, key: str, value: Any, *,
            ttl: float | None = None, game_time: float = 0.0) -> None:
        self.data[key] = value
        if ttl is not None:
            self.expiry[key] = game_time + ttl
        elif key in self.expiry:
            del self.expiry[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def has(self, key: str) -> bool:
        return key in self.data

    def forget(self, key: str) -> None:
        self.data.pop(key, None)
        self.expiry.pop(key, None)

    def tick_expiry(self, game_time: float) -> None:
        expired = [k for k, t in self.expiry.items() if game_time >= t]
        for k in expired:
            self.data.pop(k, None)
            del self.expiry[k]


@dataclass
class GoalSet:
    """Priority-ordered goal list for an entity.

    ``goals`` is a list of ``(priority, Goal)`` tuples.  Lower priority
    numbers are more important and preempt higher numbers.

    ``active`` is the currently running Goal instance (or ``None``).
    ``active_priority`` tracks the priority of the running goal so the
    evaluator can decide whether a new goal should preempt it.
    """
    goals: list = field(default_factory=list)
    active: Any = None
    active_priority: int = 999
