"""core.session — Game session lifecycle.

Manages the data pipeline so the scene never touches it:

  - **Zone files** provide the static world layout (tiles, spawn points).
  - **Save files** provide the dynamic entity state (positions, health, inventory).
  - **Prefab data** provides transient component values (sprites, colliders, identity)
    which are rebuilt from templates on every load.

Portal transitions are handled by :class:`core.transition.TransitionMixin`.
Background world simulation by :class:`core.world_ticker.WorldTickerMixin`.

Usage::

    session = Session(app.world)
    session.new_game("playground")       # loads zone, spawns player + NPCs
    app.push_scene(TopDown(session))  # view only reads session data

    session.save()                       # persist dynamic state
    session.load()                       # restore from disk
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, TYPE_CHECKING

from core.zones import load_zone, Zone
from core.types import Direction
from core.constants import DAY_LENGTH
from components import (
    Camera, GameClock, WorldClock, WorldEventLog,
    Position, Player, Velocity, Facing, CoarsePos, Identity,
)
from systems.spawner import (
    spawn_from_descriptor,
    spawn_zone_entities,
    rebuild_transients,
)
from systems.lod import sync_zone_lod, tick_timers
from systems.zone_sim import ZoneSim
from systems.beast_spawner import BeastSpawner
from core.save import save_game, load_game, restore_entity

from core.transition import TransitionMixin
from core.world_ticker import WorldTickerMixin

if TYPE_CHECKING:
    from core.ecs import World


class Session(TransitionMixin, WorldTickerMixin):
    """Owns the data pipeline — loads zones, spawns entities, saves/loads.

    The scene reads ``session.tiles``, ``session.zone_name``, etc.
    but never calls ``load_zone`` or ``spawn_*`` itself.
    """

    def __init__(self, world: "World") -> None:
        self.world = world
        self.zone_name: str = ""
        self.tiles: list[list[str]] = []
        self.rotations: list[list[int]] = []
        self.map_w: int = 0
        self.map_h: int = 0
        self.visited_zones: set[str] = set()

        self.first_person: bool = False

        # Per-cell floor/ceiling heights
        self.floor_heights: list[list[float]] = []
        self.ceil_heights: list[list[float]] = []
        self.floor_textures: list[list[str]] = []
        self.ceil_textures: list[list[str]] = []

        # Layer-2 (secondary) floor/ceiling heights
        self.floor2_heights: list[list[float]] = []
        self.ceil2_heights: list[list[float]] = []

        # uid → zone descriptor dict (for rebuilding transient components)
        self._descriptor_index: dict[str, dict[str, Any]] = {}

        # Status message — the scene can read & display this
        self.status: str = ""
        self.status_timer: float = 0.0

        # Portal lookup built when a zone is loaded
        self._portal_map: dict[tuple[int,int], tuple[str, float, float, str]] = {}
        self._portal_arrival: tuple[int, int] | None = None

        # ── Auto-walk state ──────────────────────────────────────
        self.auto_walk_active: bool = False
        self.auto_walk_timer: float = 0.0
        self.auto_walk_duration: float = 0.0
        self.auto_walk_dx: float = 0.0
        self.auto_walk_dy: float = 0.0

        # ── Screen fade transition ───────────────────────────────
        self.fade_alpha: float = 0.0
        self._fade_direction: int = 0
        self._fade_speed: float = 4.0
        self._pending_teleport: tuple[str, float, float, str] | None = None

        # ── Background simulation ────────────────────────────────
        self.zone_sim = ZoneSim(world, tick_interval=1.0)
        self.beast_spawner = BeastSpawner(world)
        self._restock_timer: float = 60.0

    @property
    def portal_positions(self) -> set[tuple[int, int]]:
        """Set of (row, col) coordinates that host a portal."""
        return set(self._portal_map.keys())

    # ── New game ──────────────────────────────────────────────────

    def new_game(self, start_zone: str = "playground") -> None:
        """Start a fresh game: load zone, spawn player + zone entities."""
        zd = self._load_zone_template(start_zone)
        self.visited_zones = {start_zone}

        ax, ay = zd.anchor
        player_desc: dict[str, Any] = {
            "id": "player",
            "prefab": "player",
            "position": {"x": ax, "y": ay},
        }
        spawn_from_descriptor(self.world, player_desc, start_zone)

        spawned = spawn_zone_entities(self.world, zd.entities, start_zone)
        print(f"[SESSION] New game in '{start_zone}' — "
              f"spawned player + {len(spawned)} entities")

        self.world.resources.set(Camera(x=ax, y=ay))
        self.world.resources.set(GameClock())
        self.world.resources.set(WorldClock())
        self.world.resources.set(WorldEventLog())

        self._init_background_sim(start_zone)

    # ── Save ──────────────────────────────────────────────────────

    def save(self, slot: int = 0) -> Path:
        """Persist dynamic entity state to disk."""
        path = save_game(
            self.world, self.zone_name,
            slot=slot, visited_zones=self.visited_zones,
        )
        self.status = f"Saved to {path.name}"
        self.status_timer = 2.0
        return path

    # ── Load ──────────────────────────────────────────────────────

    def load(self, slot: int = 0) -> bool:
        """Restore game from a save file.  Returns True on success."""
        data = load_game(slot)
        if data is None:
            self.status = "No save found"
            self.status_timer = 1.5
            return False

        self._clear_entities()

        saved_zone = data.get("zone", self.zone_name)
        self._load_zone_template(saved_zone)
        self.visited_zones = set(data.get("visited_zones", [saved_zone]))

        for z in self.visited_zones:
            if z != saved_zone:
                self._cache_zone_descriptors(z)

        for entry in data.get("entities", []):
            if not isinstance(entry, dict):
                continue
            restore_entity(self.world, entry)

        rebuild_transients(self.world, self._descriptor_index)

        clock = self.world.resources.try_get(GameClock)
        if clock:
            clock.time = data.get("clock", 0.0)
        else:
            self.world.resources.set(GameClock(time=data.get("clock", 0.0)))

        wc_data = data.get("world_clock")
        if wc_data and isinstance(wc_data, dict):
            self.world.resources.set(WorldClock(
                real_time=wc_data.get("real_time", 0.0),
                world_time=wc_data.get("world_time", 0.0),
                day=wc_data.get("day", 0),
                day_phase=wc_data.get("day_phase", 0.25),
            ))
        else:
            self.world.resources.set(WorldClock())

        self.world.resources.set(WorldEventLog())

        self._init_background_sim(saved_zone)

        self.status = "Game loaded"
        self.status_timer = 2.0
        return True

    # ── Internal ──────────────────────────────────────────────────

    def _load_zone_template(self, name: str) -> Zone:
        """Load tiles from a zone file and cache its entity descriptors."""
        zd = load_zone(name)
        self.zone_name = name
        self.tiles = zd.tiles
        self.rotations = zd.rotations if zd.rotations else [
            [0] * (len(zd.tiles[0]) if zd.tiles else 0)
            for _ in range(len(zd.tiles))
        ]
        self.map_h = len(zd.tiles)
        self.map_w = len(zd.tiles[0]) if zd.tiles else 0
        self.first_person = zd.first_person
        self.floor_heights = zd.floor_heights
        self.ceil_heights = zd.ceil_heights
        self.floor_textures = zd.floor_textures
        self.ceil_textures = zd.ceil_textures
        self.floor2_heights = getattr(zd, 'floor2_heights', [])
        self.ceil2_heights = getattr(zd, 'ceil2_heights', [])
        self._cache_descriptors_from_list(zd.entities)
        self._build_portal_map(zd)
        return zd

    def _cache_zone_descriptors(self, name: str) -> None:
        """Cache entity descriptors from a zone without loading tiles."""
        try:
            zd = load_zone(name)
            self._cache_descriptors_from_list(zd.entities)
        except FileNotFoundError:
            pass

    def _cache_descriptors_from_list(
        self, descriptors: list[dict[str, Any]]
    ) -> None:
        """Index descriptors by uid for transient rebuild lookups."""
        for desc in descriptors:
            uid = desc.get("id", "")
            if uid:
                self._descriptor_index[uid] = desc

    def _clear_entities(self) -> None:
        """Kill and purge every entity in the world."""
        all_eids: set[int] = set()
        for store in self.world._stores.values():
            all_eids.update(store.keys())
        all_eids -= self.world._dead
        for eid in all_eids:
            self.world.kill(eid)
        self.world.purge()

    def _build_portal_map(self, zd: "Zone") -> None:
        """Build tile→(target_zone, row, col, exit_dir) lookup."""
        self._portal_map.clear()
        for portal in zd.portals:
            for tile in portal.tiles:
                self._portal_map[tile] = (
                    portal.target_zone,
                    portal.target_row,
                    portal.target_col,
                    portal.exit_direction,
                )
