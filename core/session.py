"""core/session.py — Game session lifecycle.

Manages the data pipeline so the scene never touches it:

  - **Zone files** provide the static world layout (tiles, spawn points).
  - **Save files** provide the dynamic entity state (positions, health, inventory).
  - **Prefab data** provides transient component values (sprites, colliders, identity)
    which are rebuilt from templates on every load.

Usage::

    session = Session(app.world)
    session.new_game("playground")       # loads zone, spawns player + NPCs
    app.push_scene(WorldScene(session))  # scene only reads session data

    session.save()                       # persist dynamic state
    session.load()                       # restore from disk
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, TYPE_CHECKING

from core.zones import load_zone
from components import Camera, GameClock
from systems.spawner import (
    spawn_from_descriptor,
    spawn_zone_entities,
    rebuild_transients,
)
from core.save import save_game, load_game, restore_entity

if TYPE_CHECKING:
    from core.ecs import World


class Session:
    """Owns the data pipeline — loads zones, spawns entities, saves/loads.

    The scene reads ``session.tiles``, ``session.zone_name``, etc.
    but never calls ``load_zone`` or ``spawn_*`` itself.
    """

    def __init__(self, world: "World") -> None:
        self.world = world
        self.zone_name: str = ""
        self.tiles: list[list[int]] = []
        self.map_w: int = 0
        self.map_h: int = 0
        self.visited_zones: set[str] = set()

        # uid → zone descriptor dict (for rebuilding transient components)
        self._descriptor_index: dict[str, dict[str, Any]] = {}

        # Status message — the scene can read & display this
        self.status: str = ""
        self.status_timer: float = 0.0

    # ── New game ──────────────────────────────────────────────────

    def new_game(self, start_zone: str = "playground") -> None:
        """Start a fresh game: load zone, spawn player + zone entities."""
        self._load_zone_template(start_zone)
        self.visited_zones = {start_zone}

        # Spawn player at zone anchor
        zd = load_zone(start_zone)
        ax, ay = zd.anchor
        player_desc: dict[str, Any] = {
            "id": "player",
            "prefab": "player",
            "position": {"x": ax, "y": ay},
        }
        spawn_from_descriptor(self.world, player_desc, start_zone)

        # Spawn zone entities (NPCs, objects, etc.)
        spawned = spawn_zone_entities(self.world, zd.entities, start_zone)
        print(f"[SESSION] New game in '{start_zone}' — "
              f"spawned player + {len(spawned)} entities")

        # World resources
        self.world.resources.set(Camera(x=ax, y=ay))
        self.world.resources.set(GameClock())

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

        # 1) Kill every existing entity
        self._clear_entities()

        # 2) Load zone template (tiles only + cache descriptors)
        saved_zone = data.get("zone", self.zone_name)
        self._load_zone_template(saved_zone)
        self.visited_zones = set(data.get("visited_zones", [saved_zone]))

        # Cache descriptors for all visited zones (needed for rebuild)
        for z in self.visited_zones:
            if z != saved_zone:
                self._cache_zone_descriptors(z)

        # 3) Restore entities from save (persistent components only)
        for entry in data.get("entities", []):
            restore_entity(self.world, entry)

        # 4) Rebuild transient components from prefab defaults + descriptors
        rebuild_transients(self.world, self._descriptor_index)

        # 5) Restore clock
        clock = self.world.resources.try_get(GameClock)
        if clock:
            clock.time = data.get("clock", 0.0)
        else:
            self.world.resources.set(GameClock(time=data.get("clock", 0.0)))

        self.status = "Game loaded"
        self.status_timer = 2.0
        return True

    # ── Internal ──────────────────────────────────────────────────

    def _load_zone_template(self, name: str) -> None:
        """Load tiles from a zone file and cache its entity descriptors."""
        zd = load_zone(name)
        self.zone_name = name
        self.tiles = zd.tiles
        self.map_h = len(zd.tiles)
        self.map_w = len(zd.tiles[0]) if zd.tiles else 0
        self._cache_descriptors_from_list(zd.entities)

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
