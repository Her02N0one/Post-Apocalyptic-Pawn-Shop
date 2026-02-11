"""simulation/world_sim.py — Top-level simulation manager.

Provides the ``WorldSim`` class that initialises all simulation
subsystems and exposes a single ``tick()`` method for the game loop.

Usage in world_scene.py::

    # In on_enter():
    self.world_sim = WorldSim(app.world)
    self.world_sim.load_graph("data/subzones.toml")
    self.world_sim.bootstrap(game_time)

    # In update():
    self.world_sim.tick(app.world, game_time)
"""

from __future__ import annotations
from pathlib import Path
from typing import Any

from simulation.subzone import SubzoneGraph
from simulation.scheduler import WorldScheduler
from simulation.events import register_all_handlers, schedule_hunger_events
from simulation.lod_transition import is_high_lod


class WorldSim:
    """Orchestrates the off-screen persistent world simulation.

    Stored as a world resource or held by the scene.
    """

    def __init__(self, world: Any) -> None:
        self.graph = SubzoneGraph()
        self.scheduler = WorldScheduler()
        self._bootstrapped = False

        # Store as world resources so subsystems can look them up
        world.set_res(self.graph)
        world.set_res(self.scheduler)

    # ── Setup ────────────────────────────────────────────────────────

    def load_graph(self, filepath: str | Path) -> None:
        """Load the subzone graph from a TOML file."""
        loaded = SubzoneGraph.from_toml(filepath)
        self.graph.nodes.update(loaded.nodes)

    def register_handlers(self) -> None:
        """Register all event handlers on the scheduler."""
        register_all_handlers(self.scheduler, self.graph)

    def bootstrap(self, world: Any, game_time: float) -> None:
        """Bootstrap the simulation: register handlers and schedule
        initial events for all low-LOD entities.

        Call once after all entities are spawned and the graph is loaded.
        """
        self.register_handlers()

        # Schedule hunger events for all entities with SubzonePos
        count = schedule_hunger_events(world, self.scheduler, game_time)

        # Schedule communal mealtime events for settlers
        from simulation.events import schedule_meal_events
        meal_count = schedule_meal_events(world, self.scheduler, game_time)

        print(f"[SIM] Bootstrapped: {count} hunger events scheduled, "
              f"{meal_count} meal events, "
              f"{len(self.graph.nodes)} subzone nodes loaded")

        self._bootstrapped = True

    # ── Per-frame tick ───────────────────────────────────────────────

    def tick(self, world: Any, game_time: float) -> int:
        """Process simulation events up to ``game_time``.

        ``game_time`` is in game-minutes (typically GameClock.time
        converted to minutes).

        Returns the number of events processed.
        """
        if not self._bootstrapped:
            return 0

        return self.scheduler.tick(
            world,
            game_time,
            is_high_lod=is_high_lod,
        )

    # ── LOD transitions ──────────────────────────────────────────────

    def on_zone_change(self, world: Any, new_zone: str,
                       game_time: float) -> tuple[int, int]:
        """Handle player changing zones.

        Promotes entities in the new zone, demotes entities elsewhere.
        Returns (promoted, demoted).
        """
        from simulation.lod_transition import on_player_enter_zone
        return on_player_enter_zone(world, new_zone, self.graph,
                                    self.scheduler, game_time)

    # ── Queries ──────────────────────────────────────────────────────

    @property
    def active(self) -> bool:
        return self._bootstrapped and len(self.graph.nodes) > 0

    def debug_info(self) -> dict:
        """Return debug information about the simulation state."""
        return {
            "nodes": len(self.graph.nodes),
            "pending_events": self.scheduler.pending_count(),
            "events_processed": self.scheduler.events_processed,
            "next_event_time": self.scheduler.peek_time(),
            "upcoming": self.scheduler.debug_dump(10),
        }
