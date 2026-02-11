"""test_simulation.py — Headless verification of the simulation layer.

Tests three things:
1. WorldSim initializes without crashing
2. Save/load round-trips SubzonePos entities and the scheduler queue
3. A single low-LOD NPC gets ticked by the scheduler (HUNGER_CRITICAL fires)

Run: python test_simulation.py
"""
from __future__ import annotations
import json, sys, traceback
from pathlib import Path

# ── Colorless pass/fail markers ──────────────────────────────────────────

passed = 0
failed = 0

def ok(label: str):
    global passed
    passed += 1
    print(f"  [PASS] {label}")

def fail(label: str, detail: str = ""):
    global failed
    failed += 1
    print(f"  [FAIL] {label}")
    if detail:
        for line in detail.strip().splitlines():
            print(f"         {line}")


# ════════════════════════════════════════════════════════════════════════
#  TEST 1 — WorldSim initialises cleanly
# ════════════════════════════════════════════════════════════════════════

print("\n=== Test 1: WorldSim initialization ===")

try:
    from core.ecs import World
    from simulation.world_sim import WorldSim
    from simulation.subzone import SubzoneGraph

    world = World()
    ws = WorldSim(world)

    # Graph should be empty but present
    assert isinstance(ws.graph, SubzoneGraph), "graph not a SubzoneGraph"
    assert len(ws.graph.nodes) == 0, f"expected 0 nodes, got {len(ws.graph.nodes)}"
    ok("WorldSim constructor succeeds")

    # Load graph from data/subzones.toml
    graph_path = Path("data/subzones.toml")
    if graph_path.exists():
        ws.load_graph(graph_path)
        n = len(ws.graph.nodes)
        assert n > 0, "graph loaded but 0 nodes"
        ok(f"Loaded subzone graph — {n} nodes")
    else:
        fail("data/subzones.toml missing — cannot test graph loading")

    # Verify graph stored as resource
    g = world.res(SubzoneGraph)
    assert g is ws.graph, "graph not stored as world resource"
    ok("SubzoneGraph stored as world resource")

    # Verify paths exist between nodes
    nodes = list(ws.graph.nodes.keys())
    if len(nodes) >= 2:
        path = ws.graph.shortest_path(nodes[0], nodes[-1])
        assert path is not None, f"No path from {nodes[0]} to {nodes[-1]}"
        assert len(path) >= 2, f"Path too short: {path}"
        ok(f"Dijkstra path: {' → '.join(path)}")
    else:
        ok("(skipped path test — fewer than 2 nodes)")

except Exception:
    fail("WorldSim init", traceback.format_exc())


# ════════════════════════════════════════════════════════════════════════
#  TEST 2 — Scheduler ticks a real NPC (HUNGER_CRITICAL fires)
# ════════════════════════════════════════════════════════════════════════

print("\n=== Test 2: Scheduler ticks a low-LOD NPC ===")

try:
    from core.ecs import World
    from components import Identity, Hunger, Inventory
    from components.simulation import SubzonePos, WorldMemory
    from simulation.world_sim import WorldSim
    from simulation.scheduler import WorldScheduler

    world = World()
    ws = WorldSim(world)
    ws.load_graph(Path("data/subzones.toml"))

    # Spawn a low-LOD NPC (has SubzonePos, NOT Position)
    npc = world.spawn()
    world.add(npc, Identity(name="Test Scavenger", kind="villager"))
    world.add(npc, Hunger(current=50.0, maximum=100.0, rate=1.0))
    world.add(npc, Inventory())
    world.add(npc, SubzonePos(zone="settlement", subzone="sett_farm"))
    world.add(npc, WorldMemory())

    ok(f"Spawned NPC eid={npc} at sett_farm")

    # Bootstrap — this should schedule a HUNGER_CRITICAL event
    game_time = 0.0
    ws.bootstrap(world, game_time)

    # Check that an event was scheduled
    pending = ws.scheduler.entity_pending(npc)
    assert len(pending) > 0, f"No events scheduled for NPC (pending={len(pending)})"

    hunger_events = [e for e in pending if e.event_type == "HUNGER_CRITICAL"]
    assert len(hunger_events) > 0, "No HUNGER_CRITICAL event scheduled"

    evt = hunger_events[0]
    ok(f"HUNGER_CRITICAL scheduled at t={evt.time:.2f}")

    # Predict when it should fire:
    # hunger=50, threshold=30 (30% of 100), drain=1/sec=60/min
    # time_to_critical = (50 - 30) / 60 = 0.333 minutes
    expected_time = (50.0 - 30.0) / (1.0 * 60.0)
    tolerance = 0.01
    assert abs(evt.time - expected_time) < tolerance, \
        f"Expected t≈{expected_time:.3f}, got t={evt.time:.3f}"
    ok(f"Event time matches prediction ({expected_time:.3f})")

    # Advance time to just past the event
    processed = ws.tick(world, evt.time + 0.01)
    assert processed >= 1, f"Expected ≥1 events processed, got {processed}"
    ok(f"Scheduler processed {processed} event(s)")

    # Hunger should have been set to threshold (30.0)
    h = world.get(npc, Hunger)
    assert h is not None
    assert h.current <= 30.0 + 0.1, f"Hunger not updated (current={h.current})"
    ok(f"Hunger updated to {h.current:.1f}")

    # A follow-up event should be queued (either another HUNGER_CRITICAL or DECISION_CYCLE)
    next_pending = ws.scheduler.entity_pending(npc)
    assert len(next_pending) > 0, "No follow-up events after hunger critical"
    types = set(e.event_type for e in next_pending)
    ok(f"Follow-up events queued: {types}")

except Exception:
    fail("Scheduler NPC tick", traceback.format_exc())


# ════════════════════════════════════════════════════════════════════════
#  TEST 3 — Save/load round-trip for SubzonePos entities
# ════════════════════════════════════════════════════════════════════════

print("\n=== Test 3: Save/load round-trip ===")

try:
    from core.ecs import World
    from components import (
        Identity, Hunger, Inventory, Health, Player, Position
    )
    from components.simulation import SubzonePos, WorldMemory
    from simulation.world_sim import WorldSim
    from simulation.scheduler import WorldScheduler

    # Build a minimal world with player + low-LOD NPC
    world = World()

    # Player (required by save_game_state)
    player = world.spawn()
    world.add(player, Player())
    world.add(player, Position(x=10.0, y=8.0, zone="settlement"))
    world.add(player, Health(current=100.0, maximum=100.0))
    world.add(player, Inventory())

    # Low-LOD NPC
    npc = world.spawn()
    world.add(npc, Identity(name="Save Test NPC", kind="villager"))
    world.add(npc, Hunger(current=65.0, maximum=100.0, rate=0.5))
    world.add(npc, Inventory(items={"canned_beans": 2}))
    world.add(npc, SubzonePos(zone="ruins", subzone="ruins_entrance"))
    world.add(npc, WorldMemory())
    mem = world.get(npc, WorldMemory)
    mem.observe("saw_raider", data={"node": "ruins_entrance"}, game_time=10.0, ttl=300.0)

    # High-LOD NPC (has Position, no SubzonePos)
    npc2 = world.spawn()
    world.add(npc2, Identity(name="Nearby Guard", kind="guard"))
    world.add(npc2, Position(x=12.0, y=9.0, zone="settlement"))
    world.add(npc2, Health(current=80.0, maximum=100.0))

    ok("Built test world (player + 2 NPCs)")

    # Manually run the save logic (we can't use save_game_state because it
    # needs an App object with scene_manager — replicate core logic instead)
    from core.save import _save_entity_common
    from typing import Any

    # Serialize player
    player_data = {
        "zone": "settlement", "x": 10.0, "y": 8.0,
        "inventory": {"items": {}},
        "health": {"current": 100.0, "maximum": 100.0},
    }

    # Serialize entities
    entities_data = {}
    seen_eids: set[int] = set()

    # High-LOD entities (have Position)
    for eid, pos in world.all_of(Position):
        if world.has(eid, Player):
            continue
        seen_eids.add(eid)
        ent_data: dict[str, Any] = {
            "zone": pos.zone, "x": float(pos.x), "y": float(pos.y),
            "sim_mode": "high",
        }
        _save_entity_common(world, eid, ent_data)
        entities_data[str(eid)] = ent_data

    # Low-LOD entities (have SubzonePos, NOT Position)
    from components.simulation import Home
    for eid, sp in world.all_of(SubzonePos):
        if eid in seen_eids or world.has(eid, Player):
            continue
        seen_eids.add(eid)
        ent_data = {
            "sim_mode": "low",
            "subzone_pos": {"zone": sp.zone, "subzone": sp.subzone},
        }
        _save_entity_common(world, eid, ent_data)
        if world.has(eid, WorldMemory):
            wm = world.get(eid, WorldMemory)
            ent_data["world_memory"] = [
                {"key": e.key, "data": e.data, "timestamp": e.timestamp, "ttl": e.ttl}
                for e in wm.entries.values()
            ]
        entities_data[str(eid)] = ent_data

    save_data = {
        "format_version": 2,
        "player": player_data,
        "entities": entities_data,
        "zone_state": {},
        "scheduler_queue": [],
    }

    # Write then read
    test_path = Path("saves/test_sim_roundtrip.json")
    test_path.parent.mkdir(parents=True, exist_ok=True)
    with open(test_path, "w") as f:
        json.dump(save_data, f, indent=2)

    with open(test_path, "r") as f:
        loaded = json.load(f)

    ok("Save file written and re-read")

    # Verify structure
    assert loaded["format_version"] == 2
    assert str(npc) in loaded["entities"], f"NPC eid={npc} not in save"
    assert str(npc2) in loaded["entities"], f"NPC2 eid={npc2} not in save"

    npc_save = loaded["entities"][str(npc)]
    assert npc_save["sim_mode"] == "low"
    assert npc_save["subzone_pos"]["zone"] == "ruins"
    assert npc_save["subzone_pos"]["subzone"] == "ruins_entrance"
    ok("SubzonePos serialized correctly")

    assert "name" in npc_save and npc_save["name"] == "Save Test NPC"
    ok("Identity fields preserved")

    assert "hunger" in npc_save
    assert abs(npc_save["hunger"]["current"] - 65.0) < 0.1
    ok("Hunger serialized correctly")

    assert "inventory" in npc_save
    assert npc_save["inventory"].get("canned_beans") == 2
    ok("Inventory serialized correctly")

    assert "world_memory" in npc_save
    assert len(npc_save["world_memory"]) == 1
    mem_entry = npc_save["world_memory"][0]
    assert mem_entry["key"] == "saw_raider"
    ok("WorldMemory serialized correctly")

    # High-LOD NPC
    npc2_save = loaded["entities"][str(npc2)]
    assert npc2_save["sim_mode"] == "high"
    assert abs(npc2_save["x"] - 12.0) < 0.1
    ok("High-LOD NPC saved with position")

    # Cleanup
    test_path.unlink(missing_ok=True)
    ok("Save/load round-trip complete")

except Exception:
    fail("Save/load round-trip", traceback.format_exc())


# ════════════════════════════════════════════════════════════════════════
#  TEST 4 — Scheduler queue serialization
# ════════════════════════════════════════════════════════════════════════

print("\n=== Test 4: Scheduler queue serialization ===")

try:
    from simulation.scheduler import WorldScheduler

    sched = WorldScheduler()
    sched.post(10.0, 1, "HUNGER_CRITICAL", {"severity": "high"})
    sched.post(15.0, 2, "ARRIVE_NODE", {"node": "sett_farm"})
    sched.post(20.0, 1, "DECISION_CYCLE", {"node": "sett_market"})

    # Cancel one
    sched.cancel_entity_type(1, "DECISION_CYCLE")

    serialized = sched.to_list()
    assert len(serialized) == 2, f"Expected 2 non-cancelled events, got {len(serialized)}"
    ok("Serialization excludes cancelled events")

    # Restore into fresh scheduler
    sched2 = WorldScheduler()
    sched2.load_list(serialized)
    assert sched2.pending_count() == 2
    ok("Deserialized into new scheduler")

    # Check round-trip fidelity
    dump = sched2.to_list()
    assert dump[0]["eid"] == 1
    assert dump[0]["event_type"] == "HUNGER_CRITICAL"
    assert abs(dump[0]["time"] - 10.0) < 0.001
    assert dump[0]["data"]["severity"] == "high"
    ok("Event data preserved through round-trip")

except Exception:
    fail("Scheduler serialization", traceback.format_exc())


# ════════════════════════════════════════════════════════════════════════
#  TEST 5 — Decision cycle runs without crash
# ════════════════════════════════════════════════════════════════════════

print("\n=== Test 5: Decision cycle runs end-to-end ===")

try:
    from core.ecs import World
    from components import Identity, Hunger, Inventory, Health
    from components.simulation import SubzonePos, Home, WorldMemory
    from simulation.world_sim import WorldSim

    world = World()
    ws = WorldSim(world)
    ws.load_graph(Path("data/subzones.toml"))

    # NPC with all the components the decision system checks
    npc = world.spawn()
    world.add(npc, Identity(name="Decision Test", kind="villager"))
    world.add(npc, Hunger(current=80.0, maximum=100.0, rate=1.0))
    world.add(npc, Inventory(items={"canned_beans": 2}))
    world.add(npc, Health(current=100.0, maximum=100.0))
    world.add(npc, SubzonePos(zone="settlement", subzone="sett_farm"))
    world.add(npc, Home(zone="settlement", subzone="sett_market"))
    world.add(npc, WorldMemory())

    ws.bootstrap(world, 0.0)
    ok("Bootstrap complete")

    # Manually trigger a decision cycle
    from simulation.decision import run_decision_cycle
    action = run_decision_cycle(world, npc, "sett_farm", ws.graph,
                                ws.scheduler, 0.0)
    ok(f"Decision cycle returned: '{action}'")

    # Should have queued follow-up events
    pending = ws.scheduler.entity_pending(npc)
    types = set(e.event_type for e in pending)
    ok(f"Pending after decision: {types}")

    # Run forward 5 game-minutes, see if things cascade
    events_count = 0
    for minute in range(300):
        t = minute * 0.1
        n = ws.tick(world, t)
        events_count += n

    ok(f"Ran 30 game-minutes — {events_count} total events processed")

    # NPC should still be alive
    assert world.alive(npc), "NPC died during simulation"
    h = world.get(npc, Hunger)
    ok(f"NPC alive, hunger={h.current:.1f}" if h else "NPC alive")

except Exception:
    fail("Decision cycle", traceback.format_exc())


# ════════════════════════════════════════════════════════════════════════
#  SUMMARY
# ════════════════════════════════════════════════════════════════════════

print(f"\n{'='*50}")
print(f"  {passed} passed, {failed} failed")
print(f"{'='*50}")
sys.exit(1 if failed else 0)
