"""core/session.py — Game session lifecycle.

Manages the data pipeline so the scene never touches it:

  - **Zone files** provide the static world layout (tiles, spawn points).
  - **Save files** provide the dynamic entity state (positions, health, inventory).
  - **Prefab data** provides transient component values (sprites, colliders, identity)
    which are rebuilt from templates on every load.

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
        self.tiles: list[list[str]] = []
        self.map_w: int = 0
        self.map_h: int = 0
        self.visited_zones: set[str] = set()

        self.first_person: bool = False   # current zone supports first-person view

        # uid → zone descriptor dict (for rebuilding transient components)
        self._descriptor_index: dict[str, dict[str, Any]] = {}

        # Status message — the scene can read & display this
        self.status: str = ""
        self.status_timer: float = 0.0

        # Portal lookup built when a zone is loaded
        # tile → (target_zone, target_row, target_col, exit_direction)
        self._portal_map: dict[tuple[int,int], tuple[str, float, float, str]] = {}

        # Suppress portal re-trigger: tile the player just arrived at
        self._portal_arrival: tuple[int, int] | None = None

        # ── Auto-walk state ──────────────────────────────────────
        # While active, the player moves on rails and input is locked.
        self.auto_walk_active: bool = False
        self.auto_walk_timer: float = 0.0
        self.auto_walk_duration: float = 0.0
        self.auto_walk_dx: float = 0.0
        self.auto_walk_dy: float = 0.0

        # ── Screen fade transition ───────────────────────────────
        # 0.0 = fully visible, 1.0 = fully black.
        self.fade_alpha: float = 0.0
        self._fade_direction: int = 0   # +1 fading out, -1 fading in, 0 idle
        self._fade_speed: float = 4.0   # alpha units / second
        self._pending_teleport: tuple[str, float, float, str] | None = None

        # ── Background simulation ────────────────────────────────
        self.zone_sim = ZoneSim(world, tick_interval=1.0)
        self.beast_spawner = BeastSpawner(world)
        self._restock_timer: float = 60.0  # first restock check after 60s

    @property
    def portal_positions(self) -> set[tuple[int, int]]:
        """Set of (row, col) coordinates that host a portal.

        Used by the physics system for doorway magnetism nudging.
        """
        return set(self._portal_map.keys())

    # ── Direction helpers ────────────────────────────────────────────

    _DIR_DELTA: dict[str, tuple[float, float]] = {
        "up":    ( 0.0, -1.0),
        "down":  ( 0.0,  1.0),
        "left":  (-1.0,  0.0),
        "right": ( 1.0,  0.0),
    }

    _DIR_ENUM: dict[str, Direction] = {
        "up":    Direction.UP,
        "down":  Direction.DOWN,
        "left":  Direction.LEFT,
        "right": Direction.RIGHT,
    }

    _OPPOSITE_DIR: dict[str, str] = {
        "up":    "down",
        "down":  "up",
        "left":  "right",
        "right": "left",
    }

    # ── Portal checking ───────────────────────────────────────────

    def check_portals(self, dt: float = 0.0) -> bool:
        """If the player is standing on a portal tile, begin transition.

        Returns True if a zone-change sequence was *started* (fade-out).
        The actual teleport happens when the fade completes.
        """
        # Don't trigger portals while auto-walking or during a fade
        if self.auto_walk_active or self._fade_direction != 0:
            return False

        result = self.world.query_one(Player, Position)
        if not result:
            return False
        eid, _, pos = result
        r = int(pos.y)
        c = int(pos.x)
        key = (r, c)

        # Clear arrival suppression once the player steps off the tile
        if self._portal_arrival is not None and key != self._portal_arrival:
            self._portal_arrival = None

        # Still standing on the tile we just arrived at — skip
        if key == self._portal_arrival:
            return False

        if key not in self._portal_map:
            return False

        target_zone, target_r, target_c, exit_dir = self._portal_map[key]

        # Start fade-out; the actual teleport fires when fade reaches 1.0
        self._pending_teleport = (target_zone, target_r, target_c, exit_dir)
        self._fade_direction = 1  # fade out
        return True

    def update_transition(self, dt: float) -> None:
        """Tick the fade and auto-walk state.  Call from scene.update().

        This should be called every frame.  It:
        1. Advances the screen fade (out then in).
        2. When fade-out completes, performs the actual teleport and starts fade-in.
        3. Advances auto-walk timer and applies rail movement.
        """
        # ── Screen fade ──────────────────────────────────────────
        if self._fade_direction != 0:
            self.fade_alpha += self._fade_direction * self._fade_speed * dt
            if self._fade_direction == 1 and self.fade_alpha >= 1.0:
                # Fade-out complete → do teleport → start fade-in
                self.fade_alpha = 1.0
                if self._pending_teleport:
                    self._execute_teleport(*self._pending_teleport)
                    self._pending_teleport = None
                self._fade_direction = -1  # now fade in
            elif self._fade_direction == -1 and self.fade_alpha <= 0.0:
                self.fade_alpha = 0.0
                self._fade_direction = 0  # done

        # ── Auto-walk ────────────────────────────────────────────
        if self.auto_walk_active:
            self.auto_walk_timer -= dt
            if self.auto_walk_timer <= 0:
                self.auto_walk_active = False
                self.auto_walk_timer = 0.0
                # Zero velocity when rails end
                for _, _, vel in self.world.query(Player, Velocity):
                    vel.x = 0.0
                    vel.y = 0.0
            else:
                # Apply constant velocity in the exit direction
                result = self.world.query_one(Player, Velocity)
                if result:
                    _, _, vel = result
                    speed = 4.0  # auto-walk speed (tiles/s)
                    vel.x = self.auto_walk_dx * speed
                    vel.y = self.auto_walk_dy * speed

    def _execute_teleport(self, target_zone: str, target_r: float,
                          target_c: float, exit_dir: str) -> None:
        """Actually move the player to the destination zone + start auto-walk.

        ``exit_dir`` is the source portal's exit_direction.  The *arrival*
        direction is read directly from the destination portal's
        ``exit_direction`` — it describes the direction the player should
        walk/face when arriving at that portal from another zone.
        """
        # Load destination zone (also rebuilds _portal_map for the new zone)
        try:
            zd = self._load_zone_template(target_zone)
        except (FileNotFoundError, ValueError) as exc:
            print(f"[SESSION] Teleport failed — cannot load '{target_zone}': {exc}")
            self._fade_direction = -1  # fade back in
            return

        # Spawn entities on first visit to this zone
        if target_zone not in self.visited_zones:
            spawned = spawn_zone_entities(self.world, zd.entities, target_zone)
            print(f"[SESSION] First visit to '{target_zone}' — "
                  f"spawned {len(spawned)} entities")
        self.visited_zones.add(target_zone)

        # Sync LOD: promote entities in the new zone, demote old-zone entities
        sync_zone_lod(self.world, target_zone)

        # Move player to the center of the portal tile in the destination
        result = self.world.query_one(Player, Position)
        if not result:
            return
        _, _, pos = result
        pos.x = target_c + 0.5
        pos.y = target_r + 0.5
        pos.zone = target_zone

        # Suppress re-trigger at the destination tile
        dest_r = int(pos.y)
        dest_c = int(pos.x)
        self._portal_arrival = (dest_r, dest_c)

        # Read the arrival direction from the DESTINATION portal.
        # Each portal's exit_direction describes the direction the
        # player walks/faces when arriving at that portal.  No flip
        # needed — the value is used directly.
        dest_key = (dest_r, dest_c)
        if dest_key in self._portal_map:
            arrival_dir = self._portal_map[dest_key][3]
        else:
            # Fallback: no matching return-portal — use source direction
            arrival_dir = exit_dir

        # Set player facing to the arrival direction
        direction = self._DIR_ENUM.get(arrival_dir, Direction.UP)
        for _, _, facing in self.world.query(Player, Facing):
            facing.direction = direction

        # Start auto-walk: move ~1.5 tiles in the arrival direction
        dx, dy = self._DIR_DELTA.get(arrival_dir, (0.0, -1.0))
        self.auto_walk_active = True
        self.auto_walk_duration = 0.6
        self.auto_walk_timer = self.auto_walk_duration
        self.auto_walk_dx = dx
        self.auto_walk_dy = dy

        self.status = f"Entered {target_zone}"
        self.status_timer = 1.5

    # ── New game ──────────────────────────────────────────────────

    def new_game(self, start_zone: str = "playground") -> None:
        """Start a fresh game: load zone, spawn player + zone entities."""
        zd = self._load_zone_template(start_zone)
        self.visited_zones = {start_zone}

        # Spawn player at zone anchor
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
        self.world.resources.set(WorldClock())
        self.world.resources.set(WorldEventLog())

        # Background sim: cache start zone + load neighbor zones
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
            if not isinstance(entry, dict):
                continue
            restore_entity(self.world, entry)

        # 4) Rebuild transient components from prefab defaults + descriptors
        rebuild_transients(self.world, self._descriptor_index)

        # 5) Restore clock
        clock = self.world.resources.try_get(GameClock)
        if clock:
            clock.time = data.get("clock", 0.0)
        else:
            self.world.resources.set(GameClock(time=data.get("clock", 0.0)))

        # 6) Restore world clock
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

        # 7) Fresh event log
        self.world.resources.set(WorldEventLog())

        # 8) Init background sim for all visited zones
        self._init_background_sim(saved_zone)

        self.status = "Game loaded"
        self.status_timer = 2.0
        return True

    # ── Internal ──────────────────────────────────────────────────

    # All known zone files — used to preload neighbor zones for background sim
    ALL_ZONES = [
        "playground", "pawn_shop", "house_interior",
        "outskirts", "crossroads", "campsite",
    ]

    def _init_background_sim(self, active_zone: str) -> None:
        """Load all zones into ZoneSim and run initial LOD sync."""
        for z in self.ALL_ZONES:
            if not self.zone_sim.has_zone(z):
                try:
                    self.zone_sim.load_zone(z)
                except FileNotFoundError:
                    pass
        # Sync LOD: promote entities in active zone, demote the rest
        sync_zone_lod(self.world, active_zone)

    def tick_world(self, dt: float) -> None:
        """Advance all background systems — call from scene.update().

        Ticks: WorldClock, Timers, ZoneSim (off-screen NPCs), BeastSpawner,
        container restocking.
        """
        # ── World clock ──────────────────────────────────────────
        wc = self.world.resources.try_get(WorldClock)
        if wc and not wc.paused:
            wc.real_time += dt
            scaled_dt = dt * wc.time_scale
            wc.world_time += scaled_dt
            # Update day / day_phase
            wc.day_phase = (wc.world_time % DAY_LENGTH) / DAY_LENGTH
            wc.day = int(wc.world_time / DAY_LENGTH)
        else:
            scaled_dt = dt

        # ── Timers ───────────────────────────────────────────────
        tick_timers(self.world, scaled_dt)

        # ── Zone sim (off-screen NPC movement + combat) ──────────
        self.zone_sim.tick(scaled_dt, active_zone=self.zone_name)

        # ── Beast spawner ────────────────────────────────────────
        self.beast_spawner.tick(scaled_dt, self.zone_sim, self.zone_name)

        # ── Container restocking ─────────────────────────────────
        self._tick_restocking(scaled_dt)

        # ── Purge dead entities ──────────────────────────────────
        self.world.purge()

    # Restocking interval: 120 real seconds ≈ ~0.4 game-days
    RESTOCK_INTERVAL: float = 120.0

    def _tick_restocking(self, dt: float) -> None:
        """Periodically restock looted containers."""
        self._restock_timer -= dt
        if self._restock_timer > 0:
            return
        self._restock_timer = self.RESTOCK_INTERVAL

        from components import TileEntity
        for eid, te in self.world.all_of(TileEntity):
            if te.tile_type == "container" and te.looted:
                te.looted = False
                # Log restocking
                event_log = self.world.resources.try_get(WorldEventLog)
                if event_log:
                    ident = self.world.get(eid, Identity)
                    name = ident.name if ident else "A container"
                    pos = self.world.get(eid, Position)
                    zone = pos.zone if pos else "?"
                    gc = self.world.resources.try_get(GameClock)
                    t = gc.time if gc else 0.0
                    event_log.add(
                        f"{name} has been restocked",
                        zone=zone, category="loot", time=t,
                    )

    def _load_zone_template(self, name: str) -> Zone:
        """Load tiles from a zone file and cache its entity descriptors.

        Returns the loaded Zone so callers can read anchor/entities
        without re-loading from disk.
        """
        zd = load_zone(name)
        self.zone_name = name
        self.tiles = zd.tiles
        self.map_h = len(zd.tiles)
        self.map_w = len(zd.tiles[0]) if zd.tiles else 0
        self.first_person = zd.first_person
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
        """Build tile→(target_zone, row, col, exit_dir) lookup from zone portals."""
        self._portal_map.clear()
        for portal in zd.portals:
            for tile in portal.tiles:
                self._portal_map[tile] = (
                    portal.target_zone,
                    portal.target_row,
                    portal.target_col,
                    portal.exit_direction,
                )
