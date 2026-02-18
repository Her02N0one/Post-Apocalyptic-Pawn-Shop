"""components — Typed ECS component dataclasses.

Every game component subclasses ``core.ecs.Component``.
Resources (Camera, GameClock) are plain dataclasses — NOT Components —
so they can only live in ``world.resources``, never on an entity.

Set ``_persist = True`` on components that should survive save/load.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from core.ecs import Component
from core.types import Direction, EntityKind


# ── Spatial ──────────────────────────────────────────────────────────

@dataclass
class Position(Component):
    """Entity location in the world (tiles)."""
    _persist = True
    x: float = 0.0
    y: float = 0.0
    zone: str = "playground"


@dataclass
class Velocity(Component):
    """Movement vector (tiles/second)."""
    x: float = 0.0
    y: float = 0.0


@dataclass
class Facing(Component):
    """Which direction the entity faces."""
    direction: Direction = Direction.DOWN


@dataclass
class Collider(Component):
    """Axis-aligned collision box (tile units, relative to Position)."""
    w: float = 0.6
    h: float = 0.6
    ox: float = 0.0
    oy: float = 0.0
    solid: bool = True


# ── Rendering ────────────────────────────────────────────────────────

@dataclass
class Sprite(Component):
    """Visual representation — a colored character."""
    char: str = "?"
    color: tuple[int, int, int] = (255, 255, 255)
    layer: int = 0


@dataclass
class Identity(Component):
    """Name and role tag."""
    name: str = ""
    kind: EntityKind = EntityKind.NPC


# ── RPG ──────────────────────────────────────────────────────────────

@dataclass
class Health(Component):
    """Hit points."""
    _persist = True
    current: float = 100.0
    maximum: float = 100.0


@dataclass
class Inventory(Component):
    """Item bag — maps item name → count."""
    _persist = True
    items: dict[str, int] = field(default_factory=dict)


# ── Template ─────────────────────────────────────────────────────────

@dataclass
class TileEntity(Component):
    """Marks an entity as grid-snapped (occupies one or more tiles).

    Tile entities are placed on the grid and associated with tiles,
    but live in the ECS — NOT in the tilemap / binary flag system.
    Examples: containers, crops, dropped ground items.
    """
    _persist = True
    tile_type: str = ""           # "container", "crop", "ground_item"
    item_id: str = ""             # for ground_items: which item this represents
    item_qty: int = 1             # stack size for ground items
    tiles: list = field(default_factory=list)  # [(row, col), ...] occupied
    loot_table: str = ""          # for containers: loot table ID
    looted: bool = False          # for containers: already opened?


@dataclass
class PrefabRef(Component):
    """Links entity to its prefab template for rebuilding transient components.

    uid:    unique identifier matching ``"id"`` in zone descriptor files.
    prefab: prefab name used to look up default component values.
    """
    _persist = True
    uid: str = ""
    prefab: str = ""


# ── Player ───────────────────────────────────────────────────────────

@dataclass
class Player(Component):
    """Marks this entity as the player-controlled character."""
    speed: float = 6.0

# ── Dual-resolution spatial ──────────────────────────────────────

@dataclass
class CoarsePos(Component):
    """Integer-tile position for off-screen (low-LOD) simulation.

    When an NPC is in a zone the player isn't viewing, all movement
    and perception uses integer tile coordinates.  ``CoarsePos`` is
    the authoritative position in that mode.

    On promotion (entity enters player zone) the values seed a
    fine-grained ``Position``.  On demotion they're written back.
    """
    _persist = True
    row: int = 0
    col: int = 0
    zone: str = "playground"
    # Movement speed in tiles/second — used by coarse sim
    speed: float = 2.0


# ── Timing ───────────────────────────────────────────────────────

@dataclass
class Timers(Component):
    """Generic named cooldowns / timers.

    Stores ``{name: remaining_seconds}``.  When a timer hits ≤ 0 it
    is removed on the next tick.  Systems add timers and check them:

        timers.active["attack_cd"] = 0.5   # set a 0.5 s cooldown
        if "attack_cd" not in timers.active:
            ...  # cooldown has expired, can attack again
    """
    _persist = True
    active: dict[str, float] = field(default_factory=dict)


@dataclass
class CombatStats(Component):
    """Combat capability for NPCs and beasts."""
    _persist = True
    damage: float = 5.0
    attack_range: int = 1       # tiles
    attack_cooldown: float = 2.0  # seconds between attacks
    hostile: bool = False       # True for beasts/hostiles

# ═════════════════════════════════════════════════════════════════════
#  Resources (plain dataclasses — NOT Components)
# ═════════════════════════════════════════════════════════════════════

@dataclass
class Camera:
    """Viewport position.  World resource, never attached to an entity."""
    x: float = 0.0
    y: float = 0.0


@dataclass
class GameClock:
    """Canonical game timer (real seconds)."""
    time: float = 0.0


@dataclass
class WorldClock:
    """World simulation clock — tracks real time and game-world time.

    ``real_time``:  wall-clock seconds since game start (same as old GameClock).
    ``world_time``: scaled game-time seconds (advances faster than real time).
    ``day``:        current in-game day number.
    ``day_phase``:  fraction of current day elapsed (0.0 = midnight, 0.5 = noon).
    ``paused``:     when True, world_time doesn't advance (menus, etc.).
    """
    real_time: float = 0.0
    world_time: float = 0.0
    day: int = 0
    day_phase: float = 0.25  # start at 06:00 (quarter through the day)
    paused: bool = False
    time_scale: float = 1.0   # 1× = normal, 2×/4×/8×/16× = fast-forward

    TIME_SCALES: ClassVar[tuple[float, ...]] = (1.0, 2.0, 4.0, 8.0, 16.0)


@dataclass
class WorldEventEntry:
    """A single log entry about something that happened in the world."""
    message: str = ""
    zone: str = ""
    time: float = 0.0         # game real_time when it happened
    category: str = "info"    # info, combat, travel, loot


@dataclass
class WorldEventLog:
    """Ring-buffer of recent world events (resource, not component).

    Toast notifications display recent unread entries in the HUD.
    """
    entries: list[WorldEventEntry] = field(default_factory=list)
    max_entries: int = 50
    unread: int = 0  # count of entries the player hasn't seen yet

    def add(self, message: str, zone: str = "", time: float = 0.0,
            category: str = "info") -> None:
        entry = WorldEventEntry(message=message, zone=zone,
                                time=time, category=category)
        self.entries.append(entry)
        if len(self.entries) > self.max_entries:
            self.entries.pop(0)
        else:
            self.unread += 1
        # Cap unread
        self.unread = min(self.unread, len(self.entries))

    def add_stamped(self, message: str, clock_time: float,
                    zone: str = "", category: str = "info") -> None:
        """Convenience: add with explicit timestamp."""
        self.add(message, zone=zone, time=clock_time, category=category)


__all__ = [
    # Components
    "Position", "Velocity", "Facing", "Collider",
    "Sprite", "Identity",
    "Health", "Inventory", "TileEntity",
    "PrefabRef", "Player",
    "CoarsePos", "Timers", "CombatStats",
    # Resources
    "Camera", "GameClock", "WorldClock",
    "WorldEventEntry", "WorldEventLog",
]
