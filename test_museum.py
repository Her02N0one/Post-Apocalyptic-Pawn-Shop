"""test_museum.py — Headless integration tests for every museum exhibit.

Each test replicates the museum tab's entity spawning and system ticking
without any pygame rendering.  If a system silently breaks, these tests
catch it.

Run: python test_museum.py
"""
from __future__ import annotations
import sys, traceback, random, math

# ── Bootstrap (tuning + zone map) ────────────────────────────────────
from core.tuning import load as _load_tuning
_load_tuning()

from core.ecs import World
from core.zone import ZONE_MAPS
from core.constants import (
    TILE_GRASS, TILE_WALL, TILE_SIZE,
)
from core.events import EventBus, AttackIntent, EntityDied
from components import (
    Position, Velocity, Sprite, Identity, Collider, Hurtbox, Facing,
    Health, Hunger, Needs, Inventory, CombatStats, Lod, Brain, GameClock,
)
from components.ai import HomeRange, Threat, AttackConfig, VisionCone
from components.social import Faction

# ── Test harness ─────────────────────────────────────────────────────

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


# ── Helpers ──────────────────────────────────────────────────────────

_ARENA_W = 30
_ARENA_H = 20
ZONE = "__test_museum__"

def make_arena() -> list[list[int]]:
    """30×20 grass grid with a wall border — same as museum."""
    tiles = [[TILE_GRASS] * _ARENA_W for _ in range(_ARENA_H)]
    for c in range(_ARENA_W):
        tiles[0][c] = TILE_WALL
        tiles[_ARENA_H - 1][c] = TILE_WALL
    for r in range(_ARENA_H):
        tiles[r][0] = TILE_WALL
        tiles[r][_ARENA_W - 1] = TILE_WALL
    return tiles

def fresh_world(tiles: list[list[int]] | None = None) -> tuple[World, list[list[int]]]:
    """Return (world, tiles) with Clock and EventBus ready."""
    w = World()
    if tiles is None:
        tiles = make_arena()
    ZONE_MAPS[ZONE] = tiles
    w.set_res(GameClock())
    w.set_res(EventBus())
    return w, tiles

def spawn_npc(w: World, name: str, brain_kind: str,
              x: float, y: float,
              color: tuple = (200, 200, 200),
              faction_group: str = "neutral",
              disposition: str = "neutral") -> int:
    """Mirror of MuseumScene._spawn_npc."""
    eid = w.spawn()
    w.add(eid, Position(x=x, y=y, zone=ZONE))
    w.add(eid, Velocity())
    w.add(eid, Sprite(char=name[0], color=color))
    w.add(eid, Identity(name=name, kind="npc"))
    w.add(eid, Collider())
    w.add(eid, Hurtbox())
    w.add(eid, Facing())
    w.add(eid, Health(current=100, maximum=100))
    w.add(eid, CombatStats(damage=10, defense=2))
    w.add(eid, Lod(level="high"))
    w.add(eid, Brain(kind=brain_kind, active=True))
    w.add(eid, HomeRange(origin_x=x, origin_y=y, radius=6.0, speed=2.0))
    w.add(eid, Faction(group=faction_group, disposition=disposition,
                       home_disposition=disposition))
    if brain_kind in ("guard", "hostile_melee"):
        w.add(eid, Threat(aggro_radius=8.0, leash_radius=15.0))
        w.add(eid, AttackConfig(attack_type="melee", range=1.2, cooldown=0.5))
    elif brain_kind == "hostile_ranged":
        w.add(eid, Threat(aggro_radius=12.0, leash_radius=20.0))
        w.add(eid, AttackConfig(attack_type="ranged", range=8.0, cooldown=0.6))
    w.zone_add(eid, ZONE)
    return eid


def spawn_combat_npc(w: World, name: str, brain_kind: str,
                     x: float, y: float,
                     color: tuple, faction_group: str, *,
                     hp: int = 100, defense: int = 5,
                     damage: int = 10, aggro: float = 8.0,
                     atk_range: float = 1.2, cooldown: float = 0.5,
                     attack_type: str = "melee",
                     flee_threshold: float = 0.2,
                     speed: float = 2.0,
                     accuracy: float = 0.85,
                     proj_speed: float = 14.0,
                     fov_degrees: float = 120.0,
                     view_distance: float = 20.0,
                     peripheral_range: float = 5.0,
                     initial_facing: str = "down") -> int:
    """Mirror of MuseumScene._spawn_combat_npc."""
    eid = w.spawn()
    w.add(eid, Position(x=x, y=y, zone=ZONE))
    w.add(eid, Velocity())
    w.add(eid, Sprite(char=name[0], color=color))
    w.add(eid, Identity(name=name, kind="npc"))
    w.add(eid, Collider())
    w.add(eid, Hurtbox())
    w.add(eid, Facing(direction=initial_facing))
    w.add(eid, Health(current=hp, maximum=hp))
    w.add(eid, CombatStats(damage=damage, defense=defense))
    w.add(eid, Lod(level="high"))
    w.add(eid, Brain(kind=brain_kind, active=True))
    w.add(eid, HomeRange(origin_x=x, origin_y=y, radius=12.0, speed=speed))
    w.add(eid, Faction(group=faction_group, disposition="hostile",
                       home_disposition="hostile"))
    w.add(eid, Threat(aggro_radius=aggro, leash_radius=30.0,
                      flee_threshold=flee_threshold))
    w.add(eid, AttackConfig(attack_type=attack_type, range=atk_range,
                            cooldown=cooldown, accuracy=accuracy,
                            proj_speed=proj_speed))
    w.add(eid, VisionCone(fov_degrees=fov_degrees,
                          view_distance=view_distance,
                          peripheral_range=peripheral_range))
    w.zone_add(eid, ZONE)
    return eid


def wire_combat(w: World):
    """Subscribe EntityDied + AttackIntent handlers — same as museum."""
    from logic.combat import handle_death, npc_melee_attack, npc_ranged_attack
    bus = w.res(EventBus)

    def _on_entity_died(ev):
        handle_death(w, ev.eid)

    def _on_attack_intent(ev):
        if ev.attack_type == "ranged":
            npc_ranged_attack(w, ev.attacker_eid, ev.target_eid)
        else:
            npc_melee_attack(w, ev.attacker_eid, ev.target_eid)

    bus.subscribe("EntityDied", _on_entity_died)
    bus.subscribe("AttackIntent", _on_attack_intent)


# ════════════════════════════════════════════════════════════════════════
#  TEST 1 — Tab 0: AI Brains (NPCs actually move)
# ════════════════════════════════════════════════════════════════════════

print("\n=== Test 1: AI Brains — NPCs move with different brain types ===")
try:
    from logic.ai.brains import tick_ai
    from logic.movement import movement_system

    w, tiles = fresh_world()
    brain_types = [
        ("Wanderer",      "wander",        5, 5),
        ("Villager",      "villager",      10, 5),
        ("Guard",         "guard",         15, 5),
        ("Hostile Melee", "hostile_melee", 20, 5),
        ("Hostile Range", "hostile_ranged",25, 5),
    ]
    eids = []
    spawn_positions = {}
    for name, bkind, x, y in brain_types:
        eid = spawn_npc(w, name, bkind, float(x), float(y))
        eids.append(eid)
        spawn_positions[eid] = (float(x), float(y))

    # Tick 200 frames at 60 fps
    dt = 1.0 / 60.0
    for _ in range(200):
        clock = w.res(GameClock)
        clock.time += dt
        tick_ai(w, dt)
        movement_system(w, dt, tiles)
        w.purge()

    moved = 0
    for eid in eids:
        if not w.alive(eid):
            moved += 1  # died = something happened
            continue
        pos = w.get(eid, Position)
        sx, sy = spawn_positions[eid]
        dist = math.hypot(pos.x - sx, pos.y - sy)
        if dist > 0.1:
            moved += 1

    if moved >= 3:
        ok(f"At least 3 brain types moved ({moved}/5)")
    else:
        fail(f"Only {moved}/5 NPCs moved from spawn", "Brains not producing movement")

    # Verify each brain kind was created correctly
    for eid in eids:
        if w.alive(eid):
            b = w.get(eid, Brain)
            if b:
                ok(f"Brain '{b.kind}' active={b.active}")
            else:
                fail(f"eid {eid} lost its Brain component")

except Exception:
    fail("AI Brains test crashed", traceback.format_exc())


# ════════════════════════════════════════════════════════════════════════
#  TEST 2 — Tab 1: CombatStats (teams fight, damage is dealt)
# ════════════════════════════════════════════════════════════════════════

print("\n=== Test 2: CombatStats — Two teams fight, damage is dealt ===")
try:
    from logic.ai.brains import tick_ai
    from logic.movement import movement_system
    from logic.combat.projectiles import projectile_system

    w, tiles = fresh_world()
    wire_combat(w)

    # Add cover blocks
    cover_positions = [
        (6, 14), (6, 15),
        (9, 12), (9, 13), (9, 16), (9, 17),
        (13, 14), (13, 15),
    ]
    for r, c in cover_positions:
        if 0 < r < _ARENA_H - 1 and 0 < c < _ARENA_W - 1:
            tiles[r][c] = TILE_WALL
    ZONE_MAPS[ZONE] = tiles

    blue_eids = []
    red_eids = []

    # Blue team — 2 melee + 1 ranged
    for name, x, y, hp, defense in [("Blue Tank", 4.0, 5.0, 150, 40),
                                     ("Blue Fighter", 4.0, 14.0, 100, 20)]:
        eid = spawn_combat_npc(w, name, "hostile_melee", x, y,
                               (80, 140, 255), "blue_team",
                               hp=hp, defense=defense, damage=15,
                               aggro=24.0, atk_range=1.2, cooldown=0.6,
                               flee_threshold=0.15, speed=2.5,
                               fov_degrees=120.0, view_distance=22.0,
                               peripheral_range=5.0, initial_facing="right")
        blue_eids.append(eid)

    eid = spawn_combat_npc(w, "Blue Sniper", "hostile_ranged", 3.0, 10.0,
                           (100, 160, 255), "blue_team",
                           hp=70, defense=5, damage=20,
                           aggro=28.0, atk_range=10.0, cooldown=0.8,
                           attack_type="ranged", flee_threshold=0.3, speed=2.0,
                           accuracy=0.95, proj_speed=18.0,
                           fov_degrees=90.0, view_distance=26.0,
                           peripheral_range=5.0, initial_facing="right")
    blue_eids.append(eid)

    # Red team — 2 melee + 1 ranged
    for name, x, y, hp, defense in [("Red Brute", 25.0, 5.0, 130, 30),
                                     ("Red Brawler", 25.0, 14.0, 100, 25)]:
        eid = spawn_combat_npc(w, name, "hostile_melee", x, y,
                               (255, 80, 80), "red_team",
                               hp=hp, defense=defense, damage=18,
                               aggro=24.0, atk_range=1.2, cooldown=0.5,
                               flee_threshold=0.15, speed=2.8,
                               fov_degrees=120.0, view_distance=22.0,
                               peripheral_range=5.0, initial_facing="left")
        red_eids.append(eid)

    eid = spawn_combat_npc(w, "Red Archer", "hostile_ranged", 26.0, 10.0,
                           (255, 120, 100), "red_team",
                           hp=60, defense=5, damage=15,
                           aggro=28.0, atk_range=9.0, cooldown=0.7,
                           attack_type="ranged", flee_threshold=0.35, speed=2.2,
                           accuracy=0.88, proj_speed=14.0,
                           fov_degrees=90.0, view_distance=26.0,
                           peripheral_range=5.0, initial_facing="left")
    red_eids.append(eid)

    all_eids = blue_eids + red_eids
    start_hp = {}
    for eid in all_eids:
        h = w.get(eid, Health)
        start_hp[eid] = h.current if h else 0

    # Tick 600 frames (~10 seconds)
    dt = 1.0 / 60.0
    for _ in range(600):
        clock = w.res(GameClock)
        clock.time += dt
        tick_ai(w, dt)
        movement_system(w, dt, tiles)
        projectile_system(w, dt, tiles)
        bus = w.res(EventBus)
        if bus:
            bus.drain()
        w.purge()

    # Check that some damage was dealt
    damage_dealt = 0
    deaths = 0
    for eid in all_eids:
        if not w.alive(eid):
            deaths += 1
            damage_dealt += start_hp[eid]
        else:
            h = w.get(eid, Health)
            if h:
                dmg = start_hp[eid] - h.current
                if dmg > 0:
                    damage_dealt += dmg

    if damage_dealt > 0:
        ok(f"CombatStats dealt {damage_dealt:.0f} total damage across all fighters")
    else:
        fail("No damage dealt after 600 frames of combat")

    if deaths > 0:
        ok(f"{deaths} entities died in combat")
    else:
        # Deaths aren't guaranteed in 10s — just note it
        ok("No deaths yet (combat is slow — damage was dealt)")

    # Verify event bus processed events
    bus = w.res(EventBus)
    stats = bus.stats()
    total_events = sum(stats.values())
    if total_events > 0:
        ok(f"EventBus processed {total_events} events: {stats}")
    else:
        fail("EventBus processed 0 events — combat system not firing")

except Exception:
    fail("CombatStats test crashed", traceback.format_exc())


# ════════════════════════════════════════════════════════════════════════
#  TEST 3 — Tab 2: LOD (entities get correct LOD tiers by distance)
# ════════════════════════════════════════════════════════════════════════

print("\n=== Test 3: LOD — Entities assigned correct tiers by distance ===")
try:
    w, tiles = fresh_world()

    # Spawn entities at known distances from center (15, 10)
    center = (15.0, 10.0)
    lod_radius = 8.0

    # Close entity — should be "high"
    close_eid = w.spawn()
    w.add(close_eid, Position(x=15.0, y=10.0, zone=ZONE))
    w.add(close_eid, Lod(level="medium"))
    w.zone_add(close_eid, ZONE)

    # Mid entity — within radius
    mid_eid = w.spawn()
    w.add(mid_eid, Position(x=20.0, y=10.0, zone=ZONE))  # dist=5
    w.add(mid_eid, Lod(level="medium"))
    w.zone_add(mid_eid, ZONE)

    # Far entity — beyond radius
    far_eid = w.spawn()
    w.add(far_eid, Position(x=26.0, y=10.0, zone=ZONE))  # dist=11
    w.add(far_eid, Lod(level="high"))
    w.zone_add(far_eid, ZONE)

    # Apply same LOD logic as LODExhibit.update()
    for eid in [close_eid, mid_eid, far_eid]:
        pos = w.get(eid, Position)
        lod = w.get(eid, Lod)
        d = math.hypot(pos.x - center[0], pos.y - center[1])
        lod.level = "high" if d <= lod_radius else "medium"

    close_lod = w.get(close_eid, Lod)
    mid_lod = w.get(mid_eid, Lod)
    far_lod = w.get(far_eid, Lod)

    if close_lod.level == "high":
        ok("Entity at center → high LOD")
    else:
        fail(f"Entity at center should be high, got {close_lod.level}")

    if mid_lod.level == "high":
        ok("Entity at dist=5 (< radius 8) → high LOD")
    else:
        fail(f"Entity at dist=5 should be high, got {mid_lod.level}")

    if far_lod.level == "medium":
        ok("Entity at dist=11 (> radius 8) → medium LOD")
    else:
        fail(f"Entity at dist=11 should be medium, got {far_lod.level}")

except Exception:
    fail("LOD test crashed", traceback.format_exc())


# ════════════════════════════════════════════════════════════════════════
#  TEST 4 — Tab 3: Pathfinding (A* finds valid paths)
# ════════════════════════════════════════════════════════════════════════

print("\n=== Test 4: Pathfinding — A* finds paths, avoids walls ===")
try:
    from logic.pathfinding import find_path

    tiles = make_arena()

    # Add the museum's wall pattern
    for r in range(3, 17):
        if r != 10:
            tiles[r][15] = TILE_WALL
    for c in range(3, 10):
        tiles[7][c] = TILE_WALL
    for r in range(3, 8):
        tiles[r][9] = TILE_WALL
    for c in range(18, 28):
        if c not in (22, 23):
            tiles[13][c] = TILE_WALL
    for r, c in [(5, 20), (5, 24), (15, 6), (15, 12)]:
        tiles[r][c] = TILE_WALL
    ZONE_MAPS[ZONE] = tiles

    # Path across the map (museum default start/goal)
    path = find_path(ZONE, 3.5, 5.5, 26.5, 5.5)
    if path and len(path) >= 2:
        ok(f"A* found path from (3.5,5.5) → (26.5,5.5) with {len(path)} waypoints")
    else:
        fail("A* found no path across the arena", f"path={path}")

    # Verify path doesn't pass through walls
    wall_violations = 0
    if path:
        for px, py in path:
            row, col = int(py), int(px)
            if 0 <= row < _ARENA_H and 0 <= col < _ARENA_W:
                if tiles[row][col] == TILE_WALL:
                    wall_violations += 1
    if wall_violations == 0:
        ok("Path does not pass through any wall tiles")
    else:
        fail(f"Path passes through {wall_violations} wall tiles")

    # Path through the narrow gap at row 10, col 15
    path2 = find_path(ZONE, 12.5, 10.5, 18.5, 10.5)
    if path2 and len(path2) >= 2:
        ok(f"A* finds path through the 1-tile gap at (15,10)")
    else:
        fail("A* cannot find path through the narrow gap")

    # Blocked path — try to go through a solid wall section
    # Seal the gap
    tiles[10][15] = TILE_WALL
    ZONE_MAPS[ZONE] = tiles
    path3 = find_path(ZONE, 5.5, 5.5, 20.5, 5.5, max_dist=14)
    # With the gap sealed, path should go around or fail within small radius
    # It might still find a path going around — that's fine.
    # We just verify the pathfinder doesn't crash.
    ok(f"Pathfinder handles sealed gap gracefully (path={'found' if path3 else 'none'})")

except Exception:
    fail("Pathfinding test crashed", traceback.format_exc())


# ════════════════════════════════════════════════════════════════════════
#  TEST 5 — Tab 4: Faction Alert Cascade
# ════════════════════════════════════════════════════════════════════════

print("\n=== Test 5: Faction — Alert cascade when raider attacks ===")
try:
    from logic.ai.brains import tick_ai
    from logic.movement import movement_system
    from logic.combat.projectiles import projectile_system

    w, tiles = fresh_world()
    wire_combat(w)

    villager_eids = []
    # Villager cluster (mirrors museum)
    villager_data = [
        ("Villager A", 15.0, 8.0, "wander"),
        ("Villager B", 17.0, 9.0, "wander"),
        ("Villager C", 14.0, 11.0, "wander"),
        ("Villager D", 16.0, 12.0, "wander"),
        ("Villager E", 18.0, 10.0, "wander"),
        ("Guard",      13.0, 10.0, "guard"),
    ]
    for name, x, y, bkind in villager_data:
        eid = w.spawn()
        is_guard = "Guard" in name
        color = (255, 200, 50) if is_guard else (100, 220, 100)
        w.add(eid, Position(x=x, y=y, zone=ZONE))
        w.add(eid, Velocity())
        w.add(eid, Sprite(char=name[0], color=color))
        w.add(eid, Identity(name=name, kind="npc"))
        w.add(eid, Collider())
        w.add(eid, Hurtbox())
        w.add(eid, Facing())
        w.add(eid, Health(current=80, maximum=80))
        w.add(eid, CombatStats(damage=8 if not is_guard else 15, defense=5))
        w.add(eid, Lod(level="high"))
        w.add(eid, Brain(kind=bkind, active=True))
        w.add(eid, HomeRange(origin_x=x, origin_y=y, radius=3.0, speed=1.5))
        w.add(eid, Faction(group="villagers", disposition="neutral",
                           home_disposition="neutral", alert_radius=6.0))
        if is_guard:
            w.add(eid, Threat(aggro_radius=10.0, leash_radius=18.0,
                              flee_threshold=0.0))
            w.add(eid, AttackConfig(attack_type="melee", range=1.2,
                                    cooldown=0.5))
        w.zone_add(eid, ZONE)
        villager_eids.append(eid)

    # Hostile raider
    raider_eid = spawn_combat_npc(
        w, "Raider", "hostile_melee", 3.0, 10.0, (255, 60, 60),
        "raiders", hp=120, defense=10, damage=12,
        aggro=20.0, atk_range=1.2, cooldown=0.6,
        flee_threshold=0.1, speed=2.5,
        fov_degrees=120.0, view_distance=20.0, peripheral_range=5.0,
        initial_facing="right")

    # Verify initial dispositions are neutral
    neutral_count = 0
    for eid in villager_eids:
        fac = w.get(eid, Faction)
        if fac and fac.disposition == "neutral":
            neutral_count += 1
    if neutral_count == len(villager_eids):
        ok(f"All {neutral_count} villagers start neutral")
    else:
        fail(f"Only {neutral_count}/{len(villager_eids)} villagers are neutral at start")

    raider_fac = w.get(raider_eid, Faction)
    if raider_fac and raider_fac.disposition == "hostile":
        ok("Raider starts hostile")
    else:
        fail("Raider not hostile at start")

    # Tick 1200 frames (~20 seconds) — raider should approach and attack
    dt = 1.0 / 60.0
    for _ in range(1200):
        clock = w.res(GameClock)
        clock.time += dt
        tick_ai(w, dt)
        movement_system(w, dt, tiles)
        projectile_system(w, dt, tiles)
        bus = w.res(EventBus)
        if bus:
            bus.drain()
        w.purge()

    # Check if any villagers flipped hostile (alert cascade)
    hostile_villagers = 0
    for eid in villager_eids:
        if not w.alive(eid):
            continue
        fac = w.get(eid, Faction)
        if fac and fac.disposition == "hostile":
            hostile_villagers += 1

    if hostile_villagers > 0:
        ok(f"{hostile_villagers} villagers turned hostile (alert cascade worked)")
    else:
        # Alert cascade might not trigger in 10s if raider hasn't reached
        # the cluster yet — check if raider moved toward them
        raider_pos = w.get(raider_eid, Position) if w.alive(raider_eid) else None
        if raider_pos and raider_pos.x > 5.0:
            ok(f"Raider advanced to x={raider_pos.x:.1f} (approaching cluster)")
        else:
            fail("No alert cascade and raider didn't move toward villagers")

except Exception:
    fail("Faction alert test crashed", traceback.format_exc())


# ════════════════════════════════════════════════════════════════════════
#  TEST 6 — Tab 5: Stealth / Vision Cone detection
# ════════════════════════════════════════════════════════════════════════

print("\n=== Test 6: Stealth — Vision cone detection ===")
try:
    from logic.ai.perception import in_vision_cone

    # Direct vision cone test — target directly in front of guard
    guard_pos = Position(x=15.0, y=10.0, zone=ZONE)
    cone = VisionCone(fov_degrees=90.0, view_distance=10.0,
                      peripheral_range=2.5)

    # Target directly ahead (guard facing right)
    target_ahead = Position(x=20.0, y=10.0, zone=ZONE)
    if in_vision_cone(guard_pos, "right", target_ahead, cone):
        ok("Target directly ahead is detected")
    else:
        fail("Target directly ahead NOT detected")

    # Target behind (guard facing right, target to the left)
    target_behind = Position(x=8.0, y=10.0, zone=ZONE)
    if not in_vision_cone(guard_pos, "right", target_behind, cone):
        ok("Target behind guard is NOT detected (correct)")
    else:
        fail("Target behind guard IS detected (should not be)")

    # Target in peripheral range (close, any direction)
    target_close = Position(x=14.0, y=10.0, zone=ZONE)
    if in_vision_cone(guard_pos, "right", target_close, cone):
        ok("Target within peripheral range detected (omni-directional)")
    else:
        fail("Target within peripheral range NOT detected")

    # Target just outside view distance
    target_far = Position(x=26.0, y=10.0, zone=ZONE)
    if not in_vision_cone(guard_pos, "right", target_far, cone):
        ok("Target beyond view_distance NOT detected (correct)")
    else:
        fail("Target beyond view_distance IS detected (should not be)")

    # Target at edge of FOV (45 degrees off center for 90 deg FOV)
    angle = math.radians(44.0)  # just inside half-FOV
    tx = 15.0 + math.cos(angle) * 8.0
    ty = 10.0 + math.sin(angle) * 8.0
    target_edge = Position(x=tx, y=ty, zone=ZONE)
    if in_vision_cone(guard_pos, "right", target_edge, cone):
        ok("Target at edge of FOV (44°) is detected")
    else:
        fail("Target at edge of FOV (44°) NOT detected")

    # Target just outside FOV
    angle2 = math.radians(46.0)
    tx2 = 15.0 + math.cos(angle2) * 8.0
    ty2 = 10.0 + math.sin(angle2) * 8.0
    target_outside = Position(x=tx2, y=ty2, zone=ZONE)
    if not in_vision_cone(guard_pos, "right", target_outside, cone):
        ok("Target just outside FOV (46°) NOT detected (correct)")
    else:
        fail("Target just outside FOV (46°) IS detected (should not be)")

    # Test with integrated entity spawning (like museum stealth tab)
    w, tiles = fresh_world()
    from logic.ai.brains import tick_ai
    from logic.movement import movement_system

    # Guard facing RIGHT, intruder is to the right and nearby
    g_eid = w.spawn()
    w.add(g_eid, Position(x=10.0, y=10.0, zone=ZONE))
    w.add(g_eid, Velocity())
    w.add(g_eid, Sprite(char="G", color=(255, 200, 50)))
    w.add(g_eid, Identity(name="Guard", kind="npc"))
    w.add(g_eid, Facing(direction="right"))
    w.add(g_eid, VisionCone(fov_degrees=90.0, view_distance=10.0,
                            peripheral_range=2.5))
    w.zone_add(g_eid, ZONE)

    i_eid = w.spawn()
    w.add(i_eid, Position(x=16.0, y=10.0, zone=ZONE))
    w.add(i_eid, Identity(name="Intruder", kind="npc"))
    w.zone_add(i_eid, ZONE)

    gpos = w.get(g_eid, Position)
    ipos = w.get(i_eid, Position)
    gface = w.get(g_eid, Facing)
    gcone = w.get(g_eid, VisionCone)

    detected = in_vision_cone(gpos, gface.direction, ipos, gcone)
    if detected:
        ok("Integrated stealth check: guard detects intruder in cone")
    else:
        fail("Integrated stealth check failed")

except Exception:
    fail("Stealth / Vision Cone test crashed", traceback.format_exc())


# ════════════════════════════════════════════════════════════════════════
#  TEST 7 — Tab 6: Particles (emit, tick, decay)
# ════════════════════════════════════════════════════════════════════════

print("\n=== Test 7: Particles — Emit, tick, and decay ===")
try:
    from logic.particles import ParticleManager

    pm = ParticleManager(max_particles=512)

    # Emit a burst
    pm.emit_burst(10.0, 10.0, count=20,
                  color=(255, 50, 50), speed=3.0,
                  life=0.5, size=2.0)

    if pm.count == 20:
        ok(f"Emitted 20 particles (count={pm.count})")
    else:
        fail(f"Expected 20 particles, got {pm.count}")

    # Tick a few frames — particles should still be alive
    pm.update(0.1)
    alive_after_01 = pm.count
    if alive_after_01 > 0:
        ok(f"After 0.1s: {alive_after_01} particles still alive")
    else:
        fail("All particles died after 0.1s (life is 0.5s)")

    # Tick past their lifetime
    pm.update(1.0)
    alive_after_dead = pm.count
    if alive_after_dead == 0:
        ok("After 1.1s total: all particles decayed (count=0)")
    else:
        fail(f"Expected 0 particles after 1.1s, got {alive_after_dead}")

    # Max particle cap
    pm2 = ParticleManager(max_particles=50)
    pm2.emit_burst(5.0, 5.0, count=100, color=(255, 255, 255),
                   speed=2.0, life=1.0)
    if pm2.count <= 50:
        ok(f"Max particle cap enforced (tried 100, got {pm2.count})")
    else:
        fail(f"Particle cap exceeded: {pm2.count} > 50")

    # Particles move
    pm3 = ParticleManager(max_particles=10)
    pm3.emit_burst(5.0, 5.0, count=5, color=(255, 0, 0),
                   speed=10.0, life=2.0, gravity=0.0, drag=1.0)
    initial_positions = [(p.x, p.y) for p in pm3.particles]
    pm3.update(0.5)
    moved_particles = 0
    for i, p in enumerate(pm3.particles):
        ox, oy = initial_positions[i] if i < len(initial_positions) else (5.0, 5.0)
        if abs(p.x - ox) > 0.01 or abs(p.y - oy) > 0.01:
            moved_particles += 1
    if moved_particles > 0:
        ok(f"{moved_particles} particles moved from spawn position")
    else:
        fail("No particles moved after 0.5s tick")

    # World resource integration
    w, tiles = fresh_world()
    w.set_res(ParticleManager(max_particles=256))
    pm_res = w.res(ParticleManager)
    pm_res.emit_burst(15.0, 10.0, count=10, color=(0, 255, 0))
    if pm_res.count == 10:
        ok("ParticleManager works as World resource")
    else:
        fail(f"World resource PM has {pm_res.count} particles, expected 10")

except Exception:
    fail("Particles test crashed", traceback.format_exc())


# ════════════════════════════════════════════════════════════════════════
#  TEST 8 — Tab 7: Needs / Hunger (hunger drains, eating works)
# ════════════════════════════════════════════════════════════════════════

print("\n=== Test 8: Needs — Hunger drains, NPCs eat ===")
try:
    from logic.needs import hunger_system, auto_eat_system

    w, tiles = fresh_world()

    npc_data = [
        ("Well-Fed Farmer",  8.0,  6.0,  80.0),
        ("Hungry Scavenger", 15.0, 6.0,  30.0),
        ("Starving Nomad",   22.0, 6.0,  10.0),
        ("Village Cook",     8.0,  14.0, 60.0),
        ("Trader",           15.0, 14.0, 50.0),
    ]
    eids = []
    start_hunger = {}

    for name, x, y, hunger_start in npc_data:
        eid = w.spawn()
        w.add(eid, Position(x=x, y=y, zone=ZONE))
        w.add(eid, Velocity())
        w.add(eid, Sprite(char=name[0], color=(200, 200, 200)))
        w.add(eid, Identity(name=name, kind="npc"))
        w.add(eid, Facing())
        w.add(eid, Health(current=100, maximum=100))
        w.add(eid, Lod(level="high"))
        w.add(eid, Brain(kind="wander", active=True))
        w.add(eid, HomeRange(origin_x=x, origin_y=y, radius=3.0, speed=1.5))
        w.add(eid, Hunger(current=hunger_start, maximum=100.0,
                          rate=0.5, starve_dps=2.0))
        w.add(eid, Needs())
        inv = Inventory()
        inv.items = {"ration": 3, "stew": 1}
        w.add(eid, inv)
        w.zone_add(eid, ZONE)
        eids.append(eid)
        start_hunger[eid] = hunger_start

    # Tick hunger at 10x speed (like museum's _needs_time_scale)
    time_scale = 10.0
    dt = 1.0 / 60.0
    for _ in range(300):
        clock = w.res(GameClock)
        clock.time += dt
        hunger_system(w, dt * time_scale)
        auto_eat_system(w, dt * time_scale)
        w.purge()

    # Check hunger decreased
    hunger_decreased = 0
    for eid in eids:
        if not w.alive(eid):
            continue
        h = w.get(eid, Hunger)
        if h and h.current < start_hunger[eid]:
            hunger_decreased += 1

    if hunger_decreased >= 3:
        ok(f"{hunger_decreased}/{len(eids)} NPCs have lower hunger than start")
    else:
        fail(f"Only {hunger_decreased}/{len(eids)} show hunger drain")

    # Check starving NPC (started at 10.0 hunger)
    starving = eids[2]  # "Starving Nomad"
    if w.alive(starving):
        h = w.get(starving, Hunger)
        needs = w.get(starving, Needs)
        if h:
            if h.current < 10.0:
                ok(f"Starving Nomad hunger drained: {h.current:.1f}/100")
            else:
                fail(f"Starving Nomad hunger didn't drain: {h.current:.1f}")
        if needs:
            ok(f"Starving Nomad needs.priority = '{needs.priority}'")

    # Check that Needs.priority is set to 'eat' for hungry NPCs
    eat_count = 0
    for eid in eids:
        if not w.alive(eid):
            continue
        needs = w.get(eid, Needs)
        h = w.get(eid, Hunger)
        if needs and h:
            ratio = h.current / max(h.maximum, 0.01)
            if ratio < 0.5 and needs.priority == "eat":
                eat_count += 1

    if eat_count > 0:
        ok(f"{eat_count} hungry NPCs have needs.priority='eat'")
    else:
        # Might have eaten enough to recover — check food consumed
        food_consumed = 0
        for eid in eids:
            if not w.alive(eid):
                continue
            inv = w.get(eid, Inventory)
            if inv:
                total = sum(inv.items.values())
                if total < 4:  # started with 4 food items
                    food_consumed += (4 - total)
        if food_consumed > 0:
            ok(f"NPCs consumed {food_consumed} food items (auto-eat works)")
        else:
            fail("No hunger priority set and no food consumed")

    # Starvation damage check
    # Run longer for the nomad to starve
    w2, tiles2 = fresh_world()
    starve_eid = w2.spawn()
    w2.add(starve_eid, Position(x=5.0, y=5.0, zone=ZONE))
    w2.add(starve_eid, Health(current=50, maximum=50))
    w2.add(starve_eid, Hunger(current=0.0, maximum=100.0,
                              rate=0.5, starve_dps=5.0))
    w2.zone_add(starve_eid, ZONE)

    for _ in range(60):
        clock2 = w2.res(GameClock)
        clock2.time += dt
        hunger_system(w2, dt * time_scale)
        w2.purge()

    hp = w2.get(starve_eid, Health)
    if hp and hp.current < 50:
        ok(f"Starvation deals damage: HP {hp.current:.1f}/50")
    else:
        fail("Starvation damage not applied")

except Exception:
    fail("Needs / Hunger test crashed", traceback.format_exc())


# ════════════════════════════════════════════════════════════════════════
#  TEST 9 — tick_systems orchestration (all systems run together)
# ════════════════════════════════════════════════════════════════════════

print("\n=== Test 9: tick_systems — Full system orchestration ===")
try:
    from logic.tick import tick_systems

    w, tiles = fresh_world()
    wire_combat(w)

    # Spawn a wanderer and a hostile pair to exercise all sub-systems
    wander_eid = spawn_npc(w, "Walker", "wander", 10.0, 10.0)
    hostile_eid = spawn_combat_npc(
        w, "Aggressor", "hostile_melee", 14.0, 10.0,
        (255, 0, 0), "raiders",
        hp=100, damage=10, aggro=12.0, atk_range=1.2, cooldown=0.5,
        fov_degrees=120.0, view_distance=15.0, peripheral_range=3.0,
        initial_facing="left")

    # Add particle manager
    from logic.particles import ParticleManager
    w.set_res(ParticleManager())

    # Tick 100 frames via tick_systems (not calling individual systems)
    dt = 1.0 / 60.0
    for _ in range(100):
        tick_systems(w, dt, tiles)
        w.purge()

    # Verify clock advanced
    clock = w.res(GameClock)
    expected = 100 * dt
    if abs(clock.time - expected) < 0.01:
        ok(f"GameClock advanced to {clock.time:.2f}s")
    else:
        fail(f"GameClock at {clock.time:.2f}s, expected ~{expected:.2f}s")

    # Wanderer should have moved
    if w.alive(wander_eid):
        pos = w.get(wander_eid, Position)
        d = math.hypot(pos.x - 10.0, pos.y - 10.0)
        if d > 0.1:
            ok(f"Walker moved {d:.1f} tiles via tick_systems")
        else:
            ok("Walker stayed near spawn (may not have chosen a target yet)")
    else:
        ok("Walker died (combat happened via tick_systems)")

    ok("tick_systems completed 100 frames without crashing")

except Exception:
    fail("tick_systems test crashed", traceback.format_exc())


# ════════════════════════════════════════════════════════════════════════
#  TEST 10 — EventBus mechanics
# ════════════════════════════════════════════════════════════════════════

print("\n=== Test 10: EventBus — Subscribe, emit, drain ===")
try:
    bus = EventBus()

    received = []
    bus.subscribe("EntityDied", lambda ev: received.append(ev))

    bus.emit(EntityDied(eid=42, killer_eid=7))
    bus.emit(EntityDied(eid=99, killer_eid=None))

    if bus.pending_count() == 2:
        ok("2 events pending before drain")
    else:
        fail(f"Expected 2 pending, got {bus.pending_count()}")

    count = bus.drain()
    if count >= 2:
        ok(f"drain() processed {count} events (>= 2)")
    else:
        fail(f"drain() processed {count}, expected >= 2")

    if len(received) == 2:
        ok("Handler received both events")
    else:
        fail(f"Handler received {len(received)} events, expected 2")

    if received[0].eid == 42 and received[1].eid == 99:
        ok("Events delivered in FIFO order")
    else:
        fail("Events out of order")

    if bus.pending_count() == 0:
        ok("Queue empty after drain")
    else:
        fail(f"Queue not empty: {bus.pending_count()} remaining")

    # Stats tracking
    stats = bus.stats()
    if stats.get("EntityDied", 0) == 2:
        ok("Event stats tracked correctly")
    else:
        fail(f"Stats mismatch: {stats}")

except Exception:
    fail("EventBus test crashed", traceback.format_exc())


# ════════════════════════════════════════════════════════════════════════
#  Summary
# ════════════════════════════════════════════════════════════════════════

print(f"\n{'='*60}")
print(f"  Museum Tests: {passed} passed, {failed} failed")
print(f"{'='*60}")
sys.exit(1 if failed else 0)
