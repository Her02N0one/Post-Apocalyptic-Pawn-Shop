"""data/dummy_spawner.py — Dummy entity spawning utilities.

Reads from ``data/dummy_entities.py`` tables and creates test dummies,
NPCs, and containers via ``spawn_from_descriptor``.
"""

from __future__ import annotations
from core.ecs import World
from components import Lod


def spawn_test_entities(world: World, zone: str) -> list[int]:
    """Spawn test dummies, NPCs, and containers.

    All categories flow through ``spawn_from_descriptor`` — no
    imperative entity assembly.
    """
    from data.dummy_entities import TEST_DUMMIES, TEST_CONTAINERS, TEST_NPCS
    from systems.engine.entity_factory import spawn_from_descriptor

    eids: list[int] = []

    for _key, data in TEST_DUMMIES.items():
        desc = dict(data)
        eid = spawn_from_descriptor(world, desc, zone)
        # Force Lod to high so brains run in test mode
        if world.has(eid, Lod):
            world.get(eid, Lod).level = "high"
        pos = data.get("position", {})
        name = data.get("identity", {}).get("name", "?")
        print(f"[SPAWN] Spawned {name} at ({pos.get('x', 0)}, {pos.get('y', 0)})")
        eids.append(eid)

    for _key, data in TEST_NPCS.items():
        desc = dict(data)
        eid = spawn_from_descriptor(world, desc, zone)
        # Force Lod to high so brains run in test mode
        if world.has(eid, Lod):
            world.get(eid, Lod).level = "high"
        pos = data.get("position", {})
        name = data.get("identity", {}).get("name", "?")
        print(f"[SPAWN] Spawned {name} at ({pos.get('x', 0)}, {pos.get('y', 0)})")
        eids.append(eid)

    for _key, data in TEST_CONTAINERS.items():
        desc = dict(data)
        eid = spawn_from_descriptor(world, desc, zone)
        pos = data.get("position", {})
        name = data.get("identity", {}).get("name", "?")
        print(f"[SPAWN] Spawned {name} at ({pos.get('x', 25.0)}, {pos.get('y', 25.0)})")
        eids.append(eid)

    return eids
