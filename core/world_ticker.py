"""core.world_ticker — Background world simulation helpers.

Extracted from ``core.session`` to keep the Session class focused on
data-pipeline lifecycle (zone loading, save/load).

Classes
-------
WorldTickerMixin
    Mixed into Session.  Provides ``tick_world()``,
    ``_init_background_sim()``, and ``_tick_restocking()``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.constants import DAY_LENGTH
from components import (
    GameClock, WorldClock, WorldEventLog,
    Position, Identity, TileEntity,
)
from systems.lod import sync_zone_lod, tick_timers

if TYPE_CHECKING:
    from core.ecs import World


class WorldTickerMixin:
    """Background simulation: world clock, zone sim, beast spawner, restocking.

    Expects the host class to provide:
    - ``world: World``
    - ``zone_name: str``
    - ``zone_sim: ZoneSim``
    - ``beast_spawner: BeastSpawner``
    - ``_restock_timer: float``
    """

    # All known zone files — used to preload neighbor zones for background sim
    ALL_ZONES = [
        "playground", "pawn_shop", "house_interior",
        "outskirts", "crossroads", "campsite",
    ]

    # Restocking interval: 120 real seconds ≈ ~0.4 game-days
    RESTOCK_INTERVAL: float = 120.0

    def _init_background_sim(self, active_zone: str) -> None:
        """Load all zones into ZoneSim and run initial LOD sync."""
        for z in self.ALL_ZONES:
            if not self.zone_sim.has_zone(z):
                try:
                    self.zone_sim.load_zone(z)
                except FileNotFoundError:
                    pass
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

    def _tick_restocking(self, dt: float) -> None:
        """Periodically restock looted containers."""
        self._restock_timer -= dt
        if self._restock_timer > 0:
            return
        self._restock_timer = self.RESTOCK_INTERVAL

        for eid, te in self.world.all_of(TileEntity):
            if te.tile_type == "container" and te.looted:
                te.looted = False
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
