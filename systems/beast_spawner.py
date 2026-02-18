"""systems/beast_spawner.py — Periodic beast spawn in outdoor zones.

Every ``spawn_interval`` game-seconds a random outdoor zone gets a
beast entity added (up to a per-zone cap).  Beasts wander via
``ZoneSim`` and fight NPCs through ``combat_sim``.

Usage::

    from systems.beast_spawner import BeastSpawner
    spawner = BeastSpawner(world)
    spawner.tick(dt, zone_sim)           # call every frame
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from components import (
    CoarsePos, Health, Identity, CombatStats, Timers,
    WorldEventLog, GameClock,
)
from core.types import EntityKind

if TYPE_CHECKING:
    from core.ecs import World
    from systems.zone_sim import ZoneSim

# Outdoor zones where beasts can spawn
OUTDOOR_ZONES = {"outskirts", "crossroads", "campsite", "playground"}

# Beast templates
BEAST_TEMPLATES = [
    {
        "name": "Feral Dog",
        "char": "d",
        "color": (180, 120, 80),
        "hp": 30.0,
        "damage": 8.0,
        "speed": 3.0,
    },
    {
        "name": "Rad-Rat",
        "char": "r",
        "color": (160, 200, 80),
        "hp": 15.0,
        "damage": 4.0,
        "speed": 4.0,
    },
    {
        "name": "Wasteland Crawler",
        "char": "C",
        "color": (100, 60, 40),
        "hp": 60.0,
        "damage": 15.0,
        "speed": 1.5,
    },
]


class BeastSpawner:
    """Periodically spawns beasts in outdoor zones."""

    MAX_BEASTS_PER_ZONE = 3
    SPAWN_INTERVAL = 45.0  # real seconds between spawn attempts

    def __init__(self, world: "World") -> None:
        self.world = world
        self._timer: float = 20.0  # first spawn after 20s

    def tick(self, dt: float, zone_sim: "ZoneSim", active_zone: str) -> None:
        """Accumulate time and try to spawn beasts."""
        self._timer -= dt
        if self._timer > 0:
            return
        self._timer = self.SPAWN_INTERVAL

        # Pick a random outdoor zone that the zone_sim knows about
        candidates = [
            z for z in zone_sim.zone_names
            if z in OUTDOOR_ZONES and z != active_zone
        ]
        if not candidates:
            return

        zone_name = random.choice(candidates)
        zc = zone_sim.get_zone(zone_name)
        if zc is None:
            return

        # Count existing beasts in this zone
        beast_count = 0
        for eid, cp in self.world.all_of(CoarsePos):
            if cp.zone != zone_name:
                continue
            ident = self.world.get(eid, Identity)
            if ident and ident.kind == EntityKind.BEAST:
                beast_count += 1

        if beast_count >= self.MAX_BEASTS_PER_ZONE:
            return

        # Find a walkable tile to spawn on
        from systems.pathfinding import random_walkable
        spawn = random_walkable(zc.tiles, zc.height // 2, zc.width // 2,
                                min_dist=2, max_dist=max(zc.height, zc.width) // 2)
        if spawn is None:
            return

        template = random.choice(BEAST_TEMPLATES)
        eid = self.world.spawn()
        self.world.add(eid, CoarsePos(
            row=spawn[0], col=spawn[1], zone=zone_name,
            speed=template["speed"],
        ))
        self.world.add(eid, Identity(
            name=template["name"], kind=EntityKind.BEAST,
        ))
        self.world.add(eid, Health(
            current=template["hp"], maximum=template["hp"],
        ))
        self.world.add(eid, CombatStats(
            damage=template["damage"], hostile=True,
            attack_range=1, attack_cooldown=2.0,
        ))
        self.world.add(eid, Timers(active={}))

        # Log the spawn
        event_log = self.world.resources.try_get(WorldEventLog)
        if event_log:
            gc = self.world.resources.try_get(GameClock)
            t = gc.time if gc else 0.0
            event_log.add(
                f"A {template['name']} appeared in {zone_name}",
                zone=zone_name, category="combat", time=t,
            )
