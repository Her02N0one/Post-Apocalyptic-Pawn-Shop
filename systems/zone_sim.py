"""systems/zone_sim.py — Off-screen zone simulation.

Ticks all non-player zones at a configurable rate (default 1 Hz).
Each tick:
    1. Move NPC entities by one tile step toward their waypoint.
    2. Run simplified sight checks between entities.
    3. Handle NPC portal traversal (cross-zone travel).

The sim reads zone tile data for wall checks and portal positions.
It only touches entities that have ``CoarsePos`` and no ``Position``
(i.e. they're in the off-screen / low-LOD pool).

Usage in the game loop::

    zone_sim = ZoneSim(world)
    zone_sim.load_zone("playground")   # cache tile + portal data
    zone_sim.tick(dt, active_zone="playground")
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from components import CoarsePos, Position, Identity, Health, Timers
from core.tiles import SOLID_IDS
from systems.pathfinding import (
    astar, random_walkable, visible_tiles as pf_visible_tiles,
)

if TYPE_CHECKING:
    from core.ecs import World
    from core.zones import Zone


# ── Zone cache ────────────────────────────────────────────────────────

@dataclass
class ZoneCache:
    """Pre-loaded zone data needed by the coarse sim."""
    name: str
    tiles: list[list[str]]
    height: int
    width: int
    # portal tile → (target_zone, target_row, target_col)
    portals: dict[tuple[int, int], tuple[str, int, int]] = field(default_factory=dict)


# ── Sight check ───────────────────────────────────────────────────────

def _tile_los(tiles: list[list[str]], r0: int, c0: int,
              r1: int, c1: int, max_range: int = 18) -> bool:
    """Bresenham line-of-sight on the tile grid.

    Returns True if there's a clear path (no solid tiles) between
    (r0, c0) and (r1, c1).  Stops at *max_range* tiles.
    """
    dr = abs(r1 - r0)
    dc = abs(c1 - c0)
    if dr + dc > max_range:
        return False

    sr = 1 if r1 > r0 else -1
    sc = 1 if c1 > c0 else -1
    err = dc - dr
    r, c = r0, c0
    h = len(tiles)
    w = len(tiles[0]) if h else 0

    steps = 0
    while steps < max_range * 2:
        if r == r1 and c == c1:
            return True
        if r < 0 or r >= h or c < 0 or c >= w:
            return False
        if tiles[r][c] in SOLID_IDS and (r, c) != (r0, c0):
            return False
        e2 = 2 * err
        if e2 > -dr:
            err -= dr
            c += sc
        if e2 < dc:
            err += dc
            r += sr
        steps += 1
    return False


def _manhattan(r0: int, c0: int, r1: int, c1: int) -> int:
    return abs(r1 - r0) + abs(c1 - c0)


# ── Coarse movement ──────────────────────────────────────────────────

def _step_toward(r: int, c: int, tr: int, tc: int) -> tuple[int, int]:
    """Return the next (row, col) one tile closer to target.

    Simple greedy step — no pathfinding yet.  Prefers the axis with
    the larger delta.
    """
    dr = tr - r
    dc = tc - c
    if abs(dr) >= abs(dc):
        return (r + (1 if dr > 0 else -1), c) if dr != 0 else (r, c)
    return (r, c + (1 if dc > 0 else -1)) if dc != 0 else (r, c)


def _tile_walkable(tiles: list[list[str]], r: int, c: int) -> bool:
    """Check if a tile is walkable (in bounds and not solid)."""
    h = len(tiles)
    w = len(tiles[0]) if h else 0
    if r < 0 or r >= h or c < 0 or c >= w:
        return False
    return tiles[r][c] not in SOLID_IDS


# ══════════════════════════════════════════════════════════════════════
#  ZoneSim
# ══════════════════════════════════════════════════════════════════════

class ZoneSim:
    """Off-screen zone simulator.

    Maintains cached tile/portal data for all loaded zones and ticks
    entities that live in those zones at a reduced rate.

    The sim accumulates real-time ``dt`` and fires a coarse tick
    every ``tick_interval`` seconds (default 1.0).
    """

    # Maximum coarse ticks per real frame to prevent frame drops at
    # high time scales.  Excess accumulator time is discarded.
    MAX_TICKS_PER_FRAME: int = 10

    def __init__(self, world: "World", tick_interval: float = 1.0) -> None:
        self.world = world
        self.tick_interval = tick_interval
        self._accumulator: float = 0.0
        self._zones: dict[str, ZoneCache] = {}

        # Per-entity cached A* path (eid → list of (r,c))
        self._paths: dict[int, list[tuple[int, int]]] = {}

        # Portal-arrival tracking: eid → (row, col) of the portal tile
        # the entity just arrived at.  Prevents immediate bounce-back
        # without needing a timer — cleared when the entity moves off
        # the arrival tile (mirrors the player's _portal_arrival approach).
        self._portal_arrivals: dict[int, tuple[int, int]] = {}

        # Sight check parameters (tiles)
        self.sight_range: int = 18
        self.alert_range: int = 10

    # ── Zone caching ──────────────────────────────────────────────

    def load_zone(self, name: str, zone: "Zone | None" = None) -> None:
        """Cache tile + portal data for a zone.

        If *zone* is None, loads it from disk.
        """
        if zone is None:
            from core.zones import load_zone
            zone = load_zone(name)

        portals: dict[tuple[int, int], tuple[str, int, int]] = {}
        for p in zone.portals:
            for tile in p.tiles:
                portals[tile] = (p.target_zone, int(p.target_row), int(p.target_col))

        self._zones[name] = ZoneCache(
            name=name,
            tiles=zone.tiles,
            height=zone.height,
            width=zone.width,
            portals=portals,
        )

    def has_zone(self, name: str) -> bool:
        return name in self._zones

    def get_zone(self, name: str) -> ZoneCache | None:
        return self._zones.get(name)

    @property
    def zone_names(self) -> list[str]:
        return list(self._zones.keys())

    # ── Path management ───────────────────────────────────────────

    def clear_path(self, eid: int) -> None:
        """Remove cached path for an entity."""
        self._paths.pop(eid, None)

    # ── Main tick ─────────────────────────────────────────────────

    def tick(self, dt: float, active_zone: str) -> int:
        """Accumulate time and run coarse ticks if due.

        Skips *active_zone* (the player's zone — handled at full res).
        Returns the number of coarse ticks that fired.

        At high time scales, many ticks may be due per real frame.
        The tick count is capped at ``MAX_TICKS_PER_FRAME`` to prevent
        frame drops; excess accumulator time is discarded (the sim is
        approximate anyway).
        """
        self._accumulator += dt
        ticks_fired = 0

        while self._accumulator >= self.tick_interval and ticks_fired < self.MAX_TICKS_PER_FRAME:
            self._accumulator -= self.tick_interval
            ticks_fired += 1
            for zone_name, zc in self._zones.items():
                if zone_name == active_zone:
                    continue
                self._tick_zone(zc)

        # Discard excess accumulator time that exceeds the per-frame cap
        # to prevent spiral-of-death lag buildup.
        if self._accumulator > self.tick_interval * 2:
            self._accumulator = 0.0

        return ticks_fired

    # ── Per-zone tick logic ───────────────────────────────────────

    def _tick_zone(self, zc: ZoneCache) -> None:
        """One coarse-resolution tick for a single off-screen zone."""
        zone_name = zc.name

        # Gather all coarse entities in this zone
        entities: list[tuple[int, CoarsePos]] = []
        for eid, cp in self.world.all_of(CoarsePos):
            # Skip entities that also have fine Position (they're in active zone)
            if self.world.has(eid, Position):
                continue
            if cp.zone == zone_name:
                entities.append((eid, cp))

        if not entities:
            return

        # 0) Clean up dead entities (HP <= 0)
        alive: list[tuple[int, CoarsePos]] = []
        for eid, cp in entities:
            hp = self.world.get(eid, Health)
            if hp and hp.current <= 0:
                self.world.kill(eid)
            else:
                alive.append((eid, cp))
        entities = alive

        if not entities:
            return

        # 1) Portal checks first — teleport before wandering
        for eid, cp in entities:
            self._check_portal(eid, cp, zc)

        # Rebuild list: some entities may have left this zone
        entities = [(eid, cp) for eid, cp in entities if cp.zone == zone_name]

        # 2) Move each remaining entity one step
        for eid, cp in entities:
            self._move_entity(eid, cp, zc)

        # 3) Sight checks between entity pairs
        self._sight_checks(entities, zc)

    def _move_entity(self, eid: int, cp: CoarsePos, zc: ZoneCache) -> None:
        """Move one entity along its A*-pathed waypoint route.

        If the entity has no path, pick a random walkable target and
        compute a path to it.  Each tick moves one step along the path.
        """
        # Check movement cooldown
        timers = self.world.get(eid, Timers)
        if timers and "move_cd" in timers.active:
            return

        # Get or compute a path
        path = self._paths.get(eid)
        if not path or len(path) <= 1:
            # Pick a new random target and pathfind to it
            target = random_walkable(zc.tiles, cp.row, cp.col,
                                     min_dist=3, max_dist=10)
            if target:
                path = astar(zc.tiles, cp.row, cp.col, target[0], target[1])
            if path and len(path) > 1:
                self._paths[eid] = path[1:]  # skip current position
            else:
                # Fallback: random step like before
                self._paths.pop(eid, None)
                self._random_step(eid, cp, zc)
                return
            path = self._paths.get(eid)

        if not path:
            return

        # Follow next step in the path
        nr, nc = path[0]
        if _tile_walkable(zc.tiles, nr, nc):
            cp.row = nr
            cp.col = nc
            path.pop(0)
            if not path:
                self._paths.pop(eid, None)
        else:
            # Path blocked — clear it and re-plan next tick
            self._paths.pop(eid, None)

        # Set movement cooldown
        cd = 1.0 / max(0.1, cp.speed)
        if timers is None:
            timers = Timers(active={})
            self.world.add(eid, timers)
        timers.active["move_cd"] = cd

    def _random_step(self, eid: int, cp: CoarsePos, zc: ZoneCache) -> None:
        """Single random-direction step (fallback when A* can't find a target)."""
        directions = [(-1, 0), (1, 0), (0, -1), (0, 1)]
        random.shuffle(directions)
        for dr, dc in directions:
            nr, nc = cp.row + dr, cp.col + dc
            if _tile_walkable(zc.tiles, nr, nc):
                cp.row = nr
                cp.col = nc
                cd = 1.0 / max(0.1, cp.speed)
                timers = self.world.get(eid, Timers)
                if timers is None:
                    timers = Timers(active={})
                    self.world.add(eid, timers)
                timers.active["move_cd"] = cd
                return

    def _sight_checks(self, entities: list[tuple[int, CoarsePos]],
                      zc: ZoneCache) -> None:
        """Run pairwise sight checks and trigger combat for hostile pairs.

        When two entities can see each other and at least one has
        hostile ``CombatStats``, combat is resolved automatically.
        """
        from systems.combat_sim import resolve_coarse_combat

        n = len(entities)
        for i in range(n):
            eid_a, cp_a = entities[i]
            for j in range(i + 1, n):
                eid_b, cp_b = entities[j]
                dist = _manhattan(cp_a.row, cp_a.col, cp_b.row, cp_b.col)
                if dist > self.sight_range:
                    continue
                if _tile_los(zc.tiles, cp_a.row, cp_a.col,
                             cp_b.row, cp_b.col, self.sight_range):
                    # Combat resolution for hostile pairs
                    resolve_coarse_combat(
                        self.world,
                        eid_a, cp_a, eid_b, cp_b,
                        zc.tiles,
                    )

    def _check_portal(self, eid: int, cp: CoarsePos, zc: ZoneCache) -> None:
        """If entity is standing on a portal tile, teleport to target zone.

        Bounce prevention uses positional tracking rather than a timer:
        after teleporting, the arrival tile is recorded.  The portal
        won't fire again until the entity moves off that tile (analogous
        to the player's ``_portal_arrival`` mechanism).
        """
        key = (cp.row, cp.col)

        # Clear arrival tracking once the entity leaves the arrival tile
        arrival = self._portal_arrivals.get(eid)
        if arrival is not None:
            if key == arrival:
                return  # still on arrival tile — skip portal
            del self._portal_arrivals[eid]

        if key not in zc.portals:
            return

        target_zone, target_row, target_col = zc.portals[key]

        # Only traverse if we have the target zone cached
        if target_zone not in self._zones:
            return

        # Check walkable at destination
        dest_zc = self._zones[target_zone]
        if not _tile_walkable(dest_zc.tiles, target_row, target_col):
            return

        # Teleport
        cp.zone = target_zone
        cp.row = target_row
        cp.col = target_col

        # Record arrival tile for bounce prevention
        self._portal_arrivals[eid] = (target_row, target_col)

        # Clear stale path from old zone
        self._paths.pop(eid, None)

        # Set movement cooldown (no more timer-based portal_cd)
        timers = self.world.get(eid, Timers)
        if timers is None:
            timers = Timers(active={})
            self.world.add(eid, timers)
        timers.active["move_cd"] = 1.0 / max(0.1, cp.speed)

        # Log the travel event
        from components import WorldEventLog, GameClock
        event_log = self.world.resources.try_get(WorldEventLog)
        if event_log:
            ident = self.world.get(eid, Identity)
            name = ident.name if ident else f"Entity#{eid}"
            gc = self.world.resources.try_get(GameClock)
            t = gc.time if gc else 0.0
            event_log.add(
                f"{name} traveled to {target_zone}",
                zone=target_zone, category="travel", time=t,
            )

    # ── Queries (for debug exhibit) ───────────────────────────────

    def zone_entity_positions(self, zone_name: str) -> list[tuple[int, int, int, str]]:
        """Return [(eid, row, col, name), ...] for entities in a zone.

        Reads CoarsePos for off-screen entities.
        """
        result: list[tuple[int, int, int, str]] = []
        for eid, cp in self.world.all_of(CoarsePos):
            if cp.zone != zone_name:
                continue
            ident = self.world.get(eid, Identity)
            name = ident.name if ident else f"E{eid}"
            result.append((eid, cp.row, cp.col, name))
        return result

    def entity_path(self, eid: int) -> list[tuple[int, int]]:
        """Return the current cached path for an entity (for debug display)."""
        return list(self._paths.get(eid, []))

    def entity_vision(self, eid: int) -> set[tuple[int, int]]:
        """Return all tiles visible to an entity via LOS (for debug display).

        Only works for coarse entities (not in active zone).
        """
        cp = self.world.get(eid, CoarsePos)
        if cp is None:
            return set()
        zc = self._zones.get(cp.zone)
        if zc is None:
            return set()
        return pf_visible_tiles(zc.tiles, cp.row, cp.col,
                                max_range=self.sight_range)
