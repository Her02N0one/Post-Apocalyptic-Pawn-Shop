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
    ``radius`` — patrol leash distance (m).
    ``speed``  — patrol movement speed (m/s).
    """
    origin_x: float = 0.0      # m
    origin_y: float = 0.0      # m
    radius: float = 6.0        # m  (default patrol leash)
    speed: float = 2.0         # m/s  (~brisk walk)


@dataclass
class Threat:
    """Perception and engagement parameters.

    Attached to entities that detect and react to hostiles.
    ``aggro_radius``    — detection range (m).
    ``leash_radius``    — max chase distance from spawn (m).
    ``flee_threshold``  — HP fraction below which entity flees (0 = never).
    ``sensor_interval`` — seconds between sensor sweeps (s).
    ``last_sensor_time`` — absolute GameClock.time of last sensor run (s).
    """
    aggro_radius: float = 5000.0   # m   (human eyesight, ~3 miles)
    leash_radius: float = 200.0    # m   (max chase distance)
    flee_threshold: float = 0.2    # HP fraction (0–1)
    sensor_interval: float = 0.1   # s
    last_sensor_time: float = 0.0  # s


@dataclass
class AttackConfig:
    """How an entity fights.

    ``attack_type`` — "melee" or "ranged".
    ``range``       — melee reach or ranged standoff distance (m).
    ``cooldown``    — time between attacks (s).
    ``last_attack_time`` — absolute GameClock.time of last attack (s).
    ``accuracy``    — 0.0–1.0 projectile accuracy (unitless).
    ``proj_speed``  — projectile speed (m/s) when no weapon item.
    """
    attack_type: str = "melee"
    range: float = 1.2           # m
    cooldown: float = 0.5        # s
    last_attack_time: float = 0.0  # s
    accuracy: float = 0.85       # 0–1
    proj_speed: float = 14.0     # m/s


@dataclass
class VisionCone:
    """Directional perception for high-LOD AI entities.

    ``fov_degrees``      — total field-of-view angle (°, e.g. 120 = ±60°).
    ``view_distance``    — forward detection range (m).
    ``peripheral_range`` — omnidirectional close-range awareness (m).
                           Enemies inside this radius are always detected
                           regardless of facing direction.

    When present alongside ``Threat``, combat_engagement uses the cone
    for idle→chase transitions instead of the simple radius check.
    ``Threat.aggro_radius`` still serves as the absolute max range cap.
    """
    fov_degrees: float = 120.0       # °
    view_distance: float = 5000.0    # m  (forward sight range, ~3 miles)
    peripheral_range: float = 10.0   # m  (omnidirectional reflex zone)


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
