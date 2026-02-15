"""test_fixes.py — Integration tests for mouse alignment, container promotion,
NPC gateway placement, and the villager schedule brain.

Run: python test_fixes.py
"""
from __future__ import annotations
import sys, traceback, random, math

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
#  TEST 1 — Mouse coordinate mapping (pygame.SCALED)
# ════════════════════════════════════════════════════════════════════════

print("\n=== Test 1: Mouse coordinate mapping (SCALED) ===")

try:
    # With pygame.SCALED the engine no longer does manual letterbox
    # math — SDL handles coordinate remapping internally.  We just
    # verify App.mouse_pos() clamps to the virtual bounds.

    # Simulate the clamping logic from App.mouse_pos()
    def clamp_mouse(mx, my, vw=960, vh=640):
        return max(0, min(mx, vw - 1)), max(0, min(my, vh - 1))

    # Centre of virtual surface
    assert clamp_mouse(480, 320) == (480, 320)
    ok("Centre maps to (480, 320)")

    # Top-left corner
    assert clamp_mouse(0, 0) == (0, 0)
    ok("Top-left maps to (0, 0)")

    # Bottom-right corner
    assert clamp_mouse(960, 640) == (959, 639)
    ok("Beyond bottom-right clamps to (959, 639)")

    # Negative coords (shouldn't happen, but safety)
    assert clamp_mouse(-5, -10) == (0, 0)
    ok("Negative coords clamp to (0, 0)")

    # Verify App class uses SCALED flag
    import core.app as _app_mod
    import inspect
    src = inspect.getsource(_app_mod.App.__init__)
    assert "SCALED" in src, "App.__init__ should use pygame.SCALED flag"
    ok("App.__init__ uses pygame.SCALED")

    # Verify no manual letterbox/remap code remains
    assert not hasattr(_app_mod.App, "_update_letterbox"), \
        "Manual _update_letterbox should be removed"
    assert not hasattr(_app_mod.App, "_remap_mouse_event"), \
        "Manual _remap_mouse_event should be removed"
    ok("No manual letterbox/remap code remains")

except Exception:
    fail("Letterbox math", traceback.format_exc())


# ════════════════════════════════════════════════════════════════════════
#  TEST 2 — Container promotion: containers get Position but NOT
#           Velocity / Collider / Hurtbox / Facing
# ════════════════════════════════════════════════════════════════════════

print("\n=== Test 2: Container promotion ===")

try:
    from core.ecs import World
    from components import (
        Identity, Position, Velocity, Collider, Hurtbox, Facing,
        Health, Brain, Lod, Inventory, HomeRange,
    )
    from components.simulation import SubzonePos
    from simulation.subzone import SubzoneGraph
    from simulation.lod_transition import promote_entity
    from simulation.scheduler import WorldScheduler

    world = World()
    graph = SubzoneGraph.from_toml("data/subzones.toml")
    world.set_res(graph)
    scheduler = WorldScheduler()
    game_time = 0.0

    # Spawn a container entity
    container_eid = world.spawn()
    world.add(container_eid, Identity(name="Supply Crate", kind="container"))
    world.add(container_eid, SubzonePos(zone="settlement", subzone="sett_market"))
    world.add(container_eid, Inventory(items={"scrap_metal": 3}))
    world.add(container_eid, Lod(level="low"))

    result = promote_entity(world, container_eid, graph, scheduler, game_time)
    assert result is True, "promote_entity returned False for container"
    ok("Container promoted successfully")

    # Container should have Position
    pos = world.get(container_eid, Position)
    assert pos is not None, "Container missing Position after promotion"
    ok("Container has Position after promotion")

    # Container should NOT have movement/combat components
    assert not world.has(container_eid, Velocity), "Container should NOT have Velocity"
    assert not world.has(container_eid, Collider), "Container should NOT have Collider"
    assert not world.has(container_eid, Hurtbox), "Container should NOT have Hurtbox"
    assert not world.has(container_eid, Facing), "Container should NOT have Facing"
    ok("Container has no Velocity/Collider/Hurtbox/Facing")

    # Container Lod should be "high"
    lod = world.get(container_eid, Lod)
    assert lod and lod.level == "high", f"Container Lod should be 'high', got {lod}"
    ok("Container Lod set to 'high'")

    # Now spawn an NPC and promote — should get the full set
    npc_eid = world.spawn()
    world.add(npc_eid, Identity(name="Maria", kind="npc"))
    world.add(npc_eid, SubzonePos(zone="settlement", subzone="sett_market"))
    world.add(npc_eid, Health(current=100.0, maximum=100.0))
    world.add(npc_eid, Brain(kind="villager", active=False, state={}))
    world.add(npc_eid, HomeRange(origin_x=20, origin_y=22, radius=5, speed=2.0))
    world.add(npc_eid, Lod(level="low"))

    result = promote_entity(world, npc_eid, graph, scheduler, game_time)
    assert result is True, "promote_entity returned False for NPC"
    ok("NPC promoted successfully")

    assert world.has(npc_eid, Position), "NPC missing Position"
    assert world.has(npc_eid, Velocity), "NPC missing Velocity"
    assert world.has(npc_eid, Collider), "NPC missing Collider"
    assert world.has(npc_eid, Hurtbox), "NPC missing Hurtbox"
    assert world.has(npc_eid, Facing), "NPC missing Facing"
    ok("NPC has full component set after promotion")

except Exception:
    fail("Container promotion", traceback.format_exc())


# ════════════════════════════════════════════════════════════════════════
#  TEST 3 — NPC gateway placement: entities at portal subzones should
#           appear near the portal spawn point, not random anchor
# ════════════════════════════════════════════════════════════════════════

print("\n=== Test 3: NPC gateway placement ===")

try:
    from core.ecs import World
    from components import (
        Identity, Position, Health, Brain, Lod, HomeRange,
    )
    from components.simulation import SubzonePos, TravelPlan
    from simulation.subzone import SubzoneGraph
    from simulation.lod_transition import promote_entity
    from simulation.scheduler import WorldScheduler
    from core.zone import load_portals, ZONE_PORTALS

    # Ensure portals are loaded
    load_portals()
    assert len(ZONE_PORTALS) > 0, "No portals loaded"
    ok(f"Loaded {len(ZONE_PORTALS)} portals")

    world = World()
    graph = SubzoneGraph.from_toml("data/subzones.toml")
    world.set_res(graph)
    scheduler = WorldScheduler()
    game_time = 0.0

    # Spawn NPC at sett_gate (portal subzone) with a travel plan
    npc_eid = world.spawn()
    world.add(npc_eid, Identity(name="Traveler", kind="npc"))
    world.add(npc_eid, SubzonePos(zone="settlement", subzone="sett_gate"))
    world.add(npc_eid, Health(current=100.0, maximum=100.0))
    world.add(npc_eid, Brain(kind="villager", active=False, state={}))
    world.add(npc_eid, HomeRange(origin_x=20, origin_y=2, radius=8, speed=2.0))
    world.add(npc_eid, Lod(level="low"))
    world.add(npc_eid, TravelPlan(
        destination="road_sett_end",
        path=["sett_gate", "road_sett_end"],
        current_index=0,
    ))

    # Find the settlement portal spawn point
    portal_spawn = None
    for p in ZONE_PORTALS:
        if p.side_a.subzone == "sett_gate":
            portal_spawn = p.side_a.spawn
            break
        if p.side_b.subzone == "sett_gate":
            portal_spawn = p.side_b.spawn
            break

    assert portal_spawn is not None, "Could not find portal for sett_gate"
    ok(f"Portal spawn for sett_gate: {portal_spawn}")

    # Promote the NPC multiple times and check placement
    TRIALS = 20
    near_portal = 0
    near_anchor = 0
    anchor = graph.get_node("sett_gate").anchor

    for i in range(TRIALS):
        random.seed(i * 37)

        # Reset entity for re-promotion
        world.remove(npc_eid, Position)
        world.add(npc_eid, SubzonePos(zone="settlement", subzone="sett_gate"))
        world.add(npc_eid, TravelPlan(
            destination="road_sett_end",
            path=["sett_gate", "road_sett_end"],
            current_index=0,
        ))
        brain = world.get(npc_eid, Brain)
        brain.active = False
        brain.state = {}
        lod = world.get(npc_eid, Lod)
        lod.level = "low"

        promote_entity(world, npc_eid, graph, scheduler, game_time)
        pos = world.get(npc_eid, Position)
        assert pos is not None, f"Trial {i}: no Position after promotion"

        dist_portal = math.hypot(pos.x - portal_spawn[0],
                                 pos.y - portal_spawn[1])
        dist_anchor = math.hypot(pos.x - anchor[0],
                                 pos.y - anchor[1])

        if dist_portal < 3.0:
            near_portal += 1
        if dist_anchor < 3.0:
            near_anchor += 1

    # With travel plan, NPC should always be near portal, not random anchor
    assert near_portal == TRIALS, \
        f"Expected all {TRIALS} placements near portal, got {near_portal}"
    ok(f"All {TRIALS} trials placed NPC near portal ({portal_spawn})")

except Exception:
    fail("NPC gateway placement", traceback.format_exc())


# ════════════════════════════════════════════════════════════════════════
#  TEST 4 — Villager brain: schedule-driven behaviour
# ════════════════════════════════════════════════════════════════════════

print("\n=== Test 4: Villager brain schedule ===")

try:
    from core import tuning as tuning_mod
    tuning_mod.load()
    from logic.ai.villager import (
        _time_of_day, _day_length, _villager_brain,
        _walk_toward,
    )
    from core.ecs import World
    from components import (
        Brain, HomeRange, Position, Velocity, Identity, Lod,
        GameClock,
    )
    from simulation.subzone import SubzoneGraph

    DAY_LENGTH = _day_length()

    # Test _time_of_day function
    assert _time_of_day(0.0) == "morning"
    assert _time_of_day(DAY_LENGTH * 0.15) == "morning"
    assert _time_of_day(DAY_LENGTH * 0.35) == "midday"
    assert _time_of_day(DAY_LENGTH * 0.55) == "afternoon"
    assert _time_of_day(DAY_LENGTH * 0.85) == "evening"
    # Day should cycle
    assert _time_of_day(DAY_LENGTH * 1.15) == "morning"
    assert _time_of_day(DAY_LENGTH * 2.35) == "midday"
    ok("_time_of_day returns correct periods and cycles")

    # Test the brain FSM with a real world
    world = World()
    graph = SubzoneGraph.from_toml("data/subzones.toml")
    world.set_res(graph)
    clock = GameClock(time=0.0)
    world.set_res(clock)

    npc = world.spawn()
    world.add(npc, Identity(name="TestNPC", kind="npc"))
    world.add(npc, Position(x=20.0, y=22.0, zone="settlement"))
    world.add(npc, Velocity(x=0.0, y=0.0))
    world.add(npc, Brain(kind="villager", active=True, state={}))
    world.add(npc, HomeRange(origin_x=20, origin_y=22, radius=8, speed=2.0))
    world.add(npc, Lod(level="high"))

    brain = world.get(npc, Brain)
    dt = 0.016  # ~60fps

    # Tick during morning — should set period and start schedule_walk
    clock.time = DAY_LENGTH * 0.1
    _villager_brain(world, npc, brain, dt, clock.time)
    v = brain.state.get("villager", {})
    assert v.get("period") == "morning", f"Period should be 'morning', got {v.get('period')}"
    ok("Morning period triggers schedule behavior")

    # Tick during afternoon — should change period
    clock.time = DAY_LENGTH * 0.55
    _villager_brain(world, npc, brain, dt, clock.time)
    v = brain.state.get("villager", {})
    assert v.get("period") == "afternoon", f"Period should be 'afternoon', got {v.get('period')}"
    ok("Afternoon period detected correctly")

    # Test destination walk from LOD promotion
    brain2 = Brain(kind="villager", active=True, state={
        "_sim_was_traveling": True,
        "_sim_destination": "road_sett_end",
    })
    world2 = World()
    graph2 = SubzoneGraph.from_toml("data/subzones.toml")
    world2.set_res(graph2)
    clock2 = GameClock(time=0.0)
    world2.set_res(clock2)

    npc2 = world2.spawn()
    world2.add(npc2, Identity(name="Traveler", kind="npc"))
    world2.add(npc2, Position(x=20.0, y=2.0, zone="settlement"))
    world2.add(npc2, Velocity(x=0.0, y=0.0))
    world2.add(npc2, brain2)
    world2.add(npc2, HomeRange(origin_x=20, origin_y=2, radius=8, speed=2.0))
    world2.add(npc2, Lod(level="high"))

    _villager_brain(world2, npc2, brain2, dt, 0.0)
    v2 = brain2.state.get("villager", {})
    assert v2.get("mode") == "travel", f"Should be 'travel' mode, got {v2.get('mode')}"
    assert v2.get("travel_target") is not None, "travel_target should be set"
    ok("LOD promotion with destination triggers travel mode")

    # Verify _sim_was_traveling flag is consumed (not re-triggered)
    assert "_sim_was_traveling" not in brain2.state, "Flag should be consumed"
    ok("_sim_was_traveling flag consumed after activation")

except Exception:
    fail("Villager brain schedule", traceback.format_exc())


# ════════════════════════════════════════════════════════════════════════
#  TEST 5 — Container demotion: containers should demote cleanly
# ════════════════════════════════════════════════════════════════════════

print("\n=== Test 5: Container round-trip (promote + demote) ===")

try:
    from core.ecs import World
    from components import (
        Identity, Position, Velocity, Collider, Hurtbox, Facing,
        Lod, Inventory,
    )
    from components.simulation import SubzonePos
    from simulation.subzone import SubzoneGraph
    from simulation.lod_transition import promote_entity, demote_entity
    from simulation.scheduler import WorldScheduler

    world = World()
    graph = SubzoneGraph.from_toml("data/subzones.toml")
    world.set_res(graph)
    scheduler = WorldScheduler()

    crate = world.spawn()
    world.add(crate, Identity(name="Rubble Pile", kind="container"))
    world.add(crate, SubzonePos(zone="settlement", subzone="sett_storehouse"))
    world.add(crate, Inventory(items={"old_electronics": 2}))
    world.add(crate, Lod(level="low"))

    # Promote
    promote_entity(world, crate, graph, scheduler, 0.0)
    assert world.has(crate, Position), "Container should have Position"
    assert not world.has(crate, Velocity), "Container should NOT have Velocity"
    ok("Container promoted cleanly (no combat/movement components)")

    # Demote
    result = demote_entity(world, crate, graph, scheduler, 0.0)
    assert result is True, "demote_entity returned False"
    assert world.has(crate, SubzonePos), "Container should have SubzonePos after demotion"
    assert not world.has(crate, Position), "Container should NOT have Position after demotion"
    ok("Container demoted cleanly")

    # Check inventory preserved
    inv = world.get(crate, Inventory)
    assert inv is not None, "Inventory lost after round-trip"
    assert "old_electronics" in inv.items, "Inventory items lost"
    ok("Container inventory preserved through round-trip")

except Exception:
    fail("Container round-trip", traceback.format_exc())


# ════════════════════════════════════════════════════════════════════════
#  TEST 6 — on_player_enter_zone: containers and NPCs both get promoted
#           correctly in a bulk zone transition
# ════════════════════════════════════════════════════════════════════════

print("\n=== Test 6: Bulk zone transition ===")

try:
    from core.ecs import World
    from components import (
        Identity, Position, Velocity, Collider, Hurtbox, Facing,
        Health, Brain, Lod, Inventory, HomeRange, Player,
    )
    from components.simulation import SubzonePos
    from simulation.subzone import SubzoneGraph
    from simulation.lod_transition import on_player_enter_zone
    from simulation.scheduler import WorldScheduler

    world = World()
    graph = SubzoneGraph.from_toml("data/subzones.toml")
    world.set_res(graph)
    scheduler = WorldScheduler()

    # Spawn some settlement entities
    npc1 = world.spawn()
    world.add(npc1, Identity(name="Pete", kind="npc"))
    world.add(npc1, SubzonePos(zone="settlement", subzone="sett_market"))
    world.add(npc1, Health(current=80, maximum=80))
    world.add(npc1, Brain(kind="villager", active=False, state={}))
    world.add(npc1, HomeRange(origin_x=20, origin_y=22, radius=5, speed=2.0))
    world.add(npc1, Lod(level="low"))

    crate1 = world.spawn()
    world.add(crate1, Identity(name="Supply Crate", kind="container"))
    world.add(crate1, SubzonePos(zone="settlement", subzone="sett_storehouse"))
    world.add(crate1, Inventory(items={"scrap": 5}))
    world.add(crate1, Lod(level="low"))

    crate2 = world.spawn()
    world.add(crate2, Identity(name="Farm Shed", kind="container"))
    world.add(crate2, SubzonePos(zone="settlement", subzone="sett_farm"))
    world.add(crate2, Inventory(items={"wheat": 10}))
    world.add(crate2, Lod(level="low"))

    promoted, demoted = on_player_enter_zone(
        world, "settlement", graph, scheduler, 0.0)
    assert promoted == 3, f"Expected 3 promotions, got {promoted}"
    ok(f"Zone transition promoted {promoted} entities")

    # NPC should have full components
    assert world.has(npc1, Position), "NPC missing Position"
    assert world.has(npc1, Velocity), "NPC missing Velocity"
    assert world.has(npc1, Collider), "NPC missing Collider"
    ok("NPC has full components after zone transition")

    # Containers should have Position but NOT combat/movement
    for ceid in (crate1, crate2):
        assert world.has(ceid, Position), f"Container {ceid} missing Position"
        assert not world.has(ceid, Velocity), f"Container {ceid} has Velocity"
        assert not world.has(ceid, Collider), f"Container {ceid} has Collider"
        assert not world.has(ceid, Hurtbox), f"Container {ceid} has Hurtbox"
    ok("Containers promoted with Position only (no combat/movement)")

except Exception:
    fail("Bulk zone transition", traceback.format_exc())


# ════════════════════════════════════════════════════════════════════════
#  TEST 7 — Wall avoidance: _walk_toward tries alternate angles
# ════════════════════════════════════════════════════════════════════════

print("\n=== Test 7: Wall avoidance in _walk_toward ===")

try:
    from logic.ai.villager import _walk_toward
    from components import Position, Velocity
    from core import zone as _zone_mod

    # Create a simple 10x10 map: all floor except a wall barrier
    # from (5,0) to (5,8) — NPC at (3,5) needs to reach (7,5)
    TILE_FLOOR = 0
    TILE_WALL = 6
    test_map = []
    for r in range(10):
        row = []
        for c in range(10):
            if r == 5 and c < 8:
                row.append(TILE_WALL)
            else:
                row.append(TILE_FLOOR)
        test_map.append(row)

    # Temporarily inject our test map
    _zone_mod.ZONE_MAPS["test_walk"] = test_map

    pos = Position(x=5.0, y=3.0, zone="test_walk")
    vel = Velocity(x=0.0, y=0.0)
    target_x, target_y = 5.0, 7.0
    dt = 0.016

    # With old code, direct path is blocked (wall at row 5).
    # Axis-slides also blocked. NPC would stop dead.
    # New code should try alternate angles and find a way around.
    dist = _walk_toward(pos, vel, target_x, target_y, 2.0, dt)

    has_velocity = abs(vel.x) > 0.01 or abs(vel.y) > 0.01
    assert has_velocity, \
        f"NPC should steer around wall, but vel=({vel.x:.2f}, {vel.y:.2f})"
    ok("NPC steers around wall barrier (non-zero velocity)")

    # The velocity should have a positive x component (going right to
    # get around the wall that ends at c=8)
    # Actually it uses angular offsets, so it could go either way — just
    # verify it's not trying to go straight into the wall
    ok(f"Avoidance velocity: ({vel.x:.2f}, {vel.y:.2f})")

    # Test open path — should go direct
    pos2 = Position(x=5.0, y=1.0, zone="test_walk")
    vel2 = Velocity(x=0.0, y=0.0)
    _walk_toward(pos2, vel2, 5.0, 3.0, 2.0, dt)
    # Should have mostly +y velocity (heading down)
    assert vel2.y > 0, f"Open path should head toward target, vel.y={vel2.y:.2f}"
    ok("Open path: NPC walks directly toward target")

    # Clean up
    del _zone_mod.ZONE_MAPS["test_walk"]

except Exception:
    fail("Wall avoidance", traceback.format_exc())


# ════════════════════════════════════════════════════════════════════════
#  TEST 8 — Stuck detection: NPC gives up after not making progress
# ════════════════════════════════════════════════════════════════════════

print("\n=== Test 8: Stuck detection ===")

try:
    from logic.ai.villager import _check_stuck
    from core.tuning import get as _tun
    _STUCK_CHECK_INTERVAL = _tun("ai.villager", "stuck_check_interval", 1.0)

    # Simulate stuck NPC — position doesn't change over multiple checks
    v = {}
    from components import Position
    pos = Position(x=5.0, y=5.0, zone="test")

    # First check — initialises
    assert _check_stuck(v, pos, 0.0) is False
    ok("First stuck check initialises (not stuck)")

    # Second check after interval — same position → strike 1
    assert _check_stuck(v, pos, _STUCK_CHECK_INTERVAL + 0.1) is False
    assert v.get("stuck_strikes") == 1
    ok("Same position → strike 1")

    # Third check — strike 2
    assert _check_stuck(v, pos, _STUCK_CHECK_INTERVAL * 2 + 0.2) is False
    assert v.get("stuck_strikes") == 2
    ok("Same position → strike 2")

    # Fourth check — strike 3 → STUCK
    assert _check_stuck(v, pos, _STUCK_CHECK_INTERVAL * 3 + 0.3) is True
    ok("3 consecutive stuck samples → gives up")

    # After reset, moving NPC should not get stuck
    v2 = {}
    pos_moving = Position(x=5.0, y=5.0, zone="test")
    _check_stuck(v2, pos_moving, 0.0)  # init
    pos_moving.x = 6.0  # moved!
    assert _check_stuck(v2, pos_moving, _STUCK_CHECK_INTERVAL + 0.1) is False
    assert v2.get("stuck_strikes", 0) == 0
    ok("Moving NPC resets stuck counter")

except Exception:
    fail("Stuck detection", traceback.format_exc())


# ════════════════════════════════════════════════════════════════════════
#  Summary
# ════════════════════════════════════════════════════════════════════════

print(f"\n{'═' * 50}")
print(f"  Results: {passed} passed, {failed} failed")
print(f"{'═' * 50}")
if __name__ == "__main__":
    sys.exit(1 if failed else 0)
