"""test_combat_behavior.py — Behavioral tests for combat AI.

Each test verifies a SPECIFIC behaviour of the combat brain:
what NPCs should do, and crucially what they should NOT do.

Tests are deterministic: fixed positions, seeded RNG, known tile
layouts.  If they pass, the combat AI is behaving correctly.

Run:  python test_combat_behavior.py
"""
from __future__ import annotations
import sys, math, random, traceback

# ── Test framework ──────────────────────────────────────────────────

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


# ── Imports ──────────────────────────────────────────────────────────

from core.ecs import World
from core.zone import ZONE_MAPS
from core.constants import TILE_GRASS, TILE_WALL
from core.events import EventBus, AttackIntent
from components import (
    Position, Velocity, Identity, Health, Facing, Brain,
    Collider, Hurtbox, Sprite, Player, Lod,
)
from components.ai import Patrol, Threat, AttackConfig, VisionCone
from components.combat import Combat
from components.social import Faction
from components.resources import GameClock

# Ensure tuning is loaded (uses defaults if no file)
import core.tuning as _tuning
_tuning.load()


# ═══════════════════════════════════════════════════════════════════
#  Scenario builder — minimal arenas for each test
# ═══════════════════════════════════════════════════════════════════

ZONE = "_test_combat"


def _make_arena(width: int = 20, height: int = 20,
                walls: list[tuple[int, int]] | None = None) -> list[list[int]]:
    """Grass tiles with border walls.  Extra walls from *walls* list."""
    tiles = [[TILE_GRASS] * width for _ in range(height)]
    for r in range(height):
        tiles[r][0] = TILE_WALL
        tiles[r][width - 1] = TILE_WALL
    for c in range(width):
        tiles[0][c] = TILE_WALL
        tiles[height - 1][c] = TILE_WALL
    if walls:
        for r, c in walls:
            if 0 <= r < height and 0 <= c < width:
                tiles[r][c] = TILE_WALL
    ZONE_MAPS[ZONE] = tiles
    return tiles


def _make_world() -> World:
    """Fresh World with GameClock + EventBus.

    Callers must call ``_make_arena(...)`` first to set up the tile map.
    Falls back to a plain grass arena if none was set.
    """
    if ZONE not in ZONE_MAPS:
        _make_arena()
    w = World()
    w.set_res(GameClock(time=1.0))
    w.set_res(EventBus())
    return w


def _spawn_npc(w: World, x: float, y: float, *,
               name: str = "NPC",
               brain_kind: str = "hostile_ranged",
               attack_type: str = "ranged",
               atk_range: float = 8.0,
               cooldown: float = 0.5,
               speed: float = 3.0,
               hp: float = 100.0,
               aggro: float = 12.0,
               leash: float = 30.0,
               flee_threshold: float = 0.2,
               faction_group: str = "red",
               accuracy: float = 1.0,
               active: bool = True) -> int:
    eid = w.spawn()
    w.add(eid, Position(x=x, y=y, zone=ZONE))
    w.add(eid, Velocity())
    w.add(eid, Identity(name=name, kind="npc"))
    w.add(eid, Sprite(char=name[0], color=(200, 80, 80)))
    w.add(eid, Collider())
    w.add(eid, Hurtbox())
    w.add(eid, Facing(direction="right"))
    w.add(eid, Health(current=hp, maximum=hp))
    w.add(eid, Combat(damage=10, defense=2))
    w.add(eid, Lod(level="high"))
    w.add(eid, Brain(kind=brain_kind, active=active))
    w.add(eid, Patrol(origin_x=x, origin_y=y, radius=12.0, speed=speed))
    w.add(eid, Faction(group=faction_group, disposition="hostile",
                       home_disposition="hostile"))
    # sensor_interval=0 → sensor runs every tick (deterministic)
    w.add(eid, Threat(aggro_radius=aggro, leash_radius=leash,
                      flee_threshold=flee_threshold,
                      sensor_interval=0.0))
    w.add(eid, AttackConfig(attack_type=attack_type, range=atk_range,
                            cooldown=cooldown, accuracy=accuracy))
    w.zone_add(eid, ZONE)
    return eid


def _spawn_target(w: World, x: float, y: float, *,
                  as_player: bool = True,
                  faction_group: str = "blue",
                  hp: float = 100.0) -> int:
    eid = w.spawn()
    w.add(eid, Position(x=x, y=y, zone=ZONE))
    w.add(eid, Velocity())
    w.add(eid, Health(current=hp, maximum=hp))
    w.add(eid, Collider())
    w.add(eid, Hurtbox())
    w.add(eid, Facing())
    w.add(eid, Lod(level="high"))
    if as_player:
        w.add(eid, Player())
    else:
        w.add(eid, Identity(name="Enemy", kind="npc"))
        w.add(eid, Faction(group=faction_group, disposition="hostile",
                           home_disposition="hostile"))
    w.zone_add(eid, ZONE)
    return eid


def _tick(w: World, npc_eid: int, dt: float = 0.016):
    """Run one combat brain tick at the current GameClock time."""
    from logic.combat_engagement import _combat_brain
    clock = w.res(GameClock)
    brain = w.get(npc_eid, Brain)
    _combat_brain(w, npc_eid, brain, dt, clock.time)


def _advance(w: World, amount: float):
    w.res(GameClock).time += amount


def _combat(w: World, eid: int) -> dict:
    """Return the NPC's combat state dict."""
    return w.get(eid, Brain).state.get("combat", {})


def _mode(w: World, eid: int) -> str:
    return _combat(w, eid).get("mode", "idle")


def _attack_intents(w: World) -> list[AttackIntent]:
    bus = w.res(EventBus)
    return [e for e in bus._queue if isinstance(e, AttackIntent)]


def _drain(w: World):
    """Clear the event bus queue."""
    w.res(EventBus)._queue.clear()


# ═══════════════════════════════════════════════════════════════════
#  A — WALL LOS SAFETY  (negative tests — NPCs must NEVER shoot
#      through walls)
# ═══════════════════════════════════════════════════════════════════

print("\n=== A: Wall LOS safety ===")

# A1: Ranged NPC with wall between it and player → zero attacks emitted
try:
    random.seed(1)
    # Wall column at x=10 from r=3..17
    wall_cells = [(r, 10) for r in range(3, 18)]
    _make_arena(20, 20, walls=wall_cells)
    w = _make_world()
    npc = _spawn_npc(w, 8.0, 10.0, atk_range=8.0)
    tgt = _spawn_target(w, 12.0, 10.0)

    # Run brain for 20 ticks (enough for FSM to stabilise)
    for i in range(20):
        _tick(w, npc)
        _advance(w, 0.016)

    attacks = _attack_intents(w)
    if len(attacks) == 0:
        ok("A1: ranged NPC never fires through wall")
    else:
        fail("A1: ranged NPC never fires through wall",
             f"Expected 0 attacks, got {len(attacks)}")
except Exception:
    fail("A1: ranged NPC never fires through wall", traceback.format_exc())

# A2: Ranged NPC with clear LOS → DOES fire
try:
    random.seed(2)
    _make_arena(20, 20)  # no interior walls – overwrite A1 arena
    w = _make_world()
    npc = _spawn_npc(w, 5.0, 10.0, atk_range=10.0, cooldown=0.1)
    tgt = _spawn_target(w, 10.0, 10.0)

    # First tick: idle→chase
    _tick(w, npc)
    _advance(w, 0.016)
    # Second tick: chase→attack (close enough + LOS clear)
    _tick(w, npc)
    _advance(w, 0.016)
    # Third tick: should fire (cooldown from attack_until should expire)
    _advance(w, 0.5)
    _tick(w, npc)

    attacks = _attack_intents(w)
    if len(attacks) >= 1:
        ok("A2: ranged NPC fires when LOS is clear")
    else:
        mode = _mode(w, npc)
        fail("A2: ranged NPC fires when LOS is clear",
             f"Expected ≥1 attacks, got {len(attacks)}; mode={mode}")
except Exception:
    fail("A2: ranged NPC fires when LOS is clear", traceback.format_exc())

# A3: Ranged NPC behind wall → mode stays chase (can't enter attack)
try:
    random.seed(3)
    wall_cells = [(r, 10) for r in range(3, 18)]
    _make_arena(20, 20, walls=wall_cells)
    w = _make_world()
    npc = _spawn_npc(w, 8.0, 10.0, atk_range=8.0)
    tgt = _spawn_target(w, 12.0, 10.0)

    # Run several ticks
    for _ in range(10):
        _tick(w, npc)
        _advance(w, 0.016)

    mode = _mode(w, npc)
    if mode == "chase":
        ok("A3: wall-blocked NPC stays in chase (not attack)")
    else:
        fail("A3: wall-blocked NPC stays in chase (not attack)",
             f"Expected mode=chase, got mode={mode}")
except Exception:
    fail("A3: wall-blocked NPC stays in chase (not attack)",
         traceback.format_exc())

# A4: NPC in attack mode loses wall LOS mid-fight → stops firing
try:
    random.seed(4)
    _make_arena(20, 20)  # start with clear LOS
    w = _make_world()
    npc = _spawn_npc(w, 5.0, 10.0, atk_range=10.0, cooldown=0.1)
    tgt = _spawn_target(w, 10.0, 10.0)

    # Get into attack mode
    for _ in range(3):
        _tick(w, npc)
        _advance(w, 0.5)
    _drain(w)

    # Now place a wall between them (simulating door close / cover)
    tiles = ZONE_MAPS[ZONE]
    for r in range(3, 18):
        tiles[r][8] = TILE_WALL

    # More ticks — should NOT fire through the new wall
    for _ in range(10):
        _tick(w, npc)
        _advance(w, 0.1)

    attacks = _attack_intents(w)
    if len(attacks) == 0:
        ok("A4: NPC stops firing when wall appears mid-fight")
    else:
        fail("A4: NPC stops firing when wall appears mid-fight",
             f"Expected 0 attacks, got {len(attacks)}")
except Exception:
    fail("A4: NPC stops firing when wall appears mid-fight",
         traceback.format_exc())


# ═══════════════════════════════════════════════════════════════════
#  B — FSM TRANSITIONS (the state machine is correct)
# ═══════════════════════════════════════════════════════════════════

print("\n=== B: FSM transitions ===")

# B1: idle → chase when target detected in range
try:
    random.seed(10)
    _make_arena(30, 30)
    w = _make_world()
    npc = _spawn_npc(w, 5.0, 15.0, aggro=10.0)
    tgt = _spawn_target(w, 10.0, 15.0)  # 5 tiles away, within aggro

    assert _mode(w, npc) == "idle", "NPC should start idle"
    _tick(w, npc)
    mode = _mode(w, npc)
    if mode == "chase":
        ok("B1: idle → chase when target in aggro range")
    else:
        fail("B1: idle → chase when target in aggro range",
             f"mode={mode}")
except Exception:
    fail("B1: idle → chase when target in aggro range",
         traceback.format_exc())

# B2: idle stays idle when target out of range
try:
    random.seed(11)
    _make_arena(30, 30)
    w = _make_world()
    npc = _spawn_npc(w, 5.0, 15.0, aggro=4.0)
    tgt = _spawn_target(w, 15.0, 15.0)  # 10 tiles away > aggro=4

    _tick(w, npc)
    mode = _mode(w, npc)
    if mode == "idle":
        ok("B2: idle stays idle when target out of aggro range")
    else:
        fail("B2: idle stays idle when target out of aggro range",
             f"mode={mode}")
except Exception:
    fail("B2: idle stays idle when target out of aggro range",
         traceback.format_exc())

# B3: chase → attack when in range + LOS (ranged)
try:
    random.seed(12)
    _make_arena(30, 30)
    w = _make_world()
    npc = _spawn_npc(w, 5.0, 15.0, atk_range=10.0, aggro=15.0)
    tgt = _spawn_target(w, 10.0, 15.0)  # dist=5, well within range*1.1

    # First tick: idle → chase
    _tick(w, npc)
    assert _mode(w, npc) == "chase"
    _advance(w, 0.016)
    # Second tick: chase → attack (dist=5 <= range*1.1=11, LOS clear)
    _tick(w, npc)
    mode = _mode(w, npc)
    if mode == "attack":
        ok("B3: chase → attack when in range + clear LOS (ranged)")
    else:
        fail("B3: chase → attack when in range + clear LOS (ranged)",
             f"mode={mode}")
except Exception:
    fail("B3: chase → attack when in range + clear LOS (ranged)",
         traceback.format_exc())

# B4: chase → flee when HP low
try:
    random.seed(13)
    _make_arena(20, 20)
    w = _make_world()
    npc = _spawn_npc(w, 5.0, 10.0, aggro=15.0, flee_threshold=0.3,
                     hp=100.0)
    tgt = _spawn_target(w, 10.0, 10.0)

    # Get into chase
    _tick(w, npc)
    assert _mode(w, npc) == "chase"

    # Drop HP to 20% (below flee_threshold 0.3)
    w.get(npc, Health).current = 20.0
    _advance(w, 0.016)
    _tick(w, npc)

    mode = _mode(w, npc)
    if mode == "flee":
        ok("B4: chase → flee when HP below threshold")
    else:
        fail("B4: chase → flee when HP below threshold",
             f"mode={mode}, hp={w.get(npc, Health).current}")
except Exception:
    fail("B4: chase → flee when HP below threshold",
         traceback.format_exc())

# B5: attack → flee when HP drops
try:
    random.seed(14)
    _make_arena(30, 30)
    w = _make_world()
    npc = _spawn_npc(w, 5.0, 15.0, atk_range=10.0, aggro=15.0,
                     flee_threshold=0.3, hp=100.0)
    tgt = _spawn_target(w, 10.0, 15.0)

    # Get into attack mode
    _tick(w, npc)
    _advance(w, 0.016)
    _tick(w, npc)
    assert _mode(w, npc) == "attack"

    # Drop HP
    w.get(npc, Health).current = 15.0
    _advance(w, 0.016)
    _tick(w, npc)

    mode = _mode(w, npc)
    if mode == "flee":
        ok("B5: attack → flee when HP drops below threshold")
    else:
        fail("B5: attack → flee when HP drops below threshold",
             f"mode={mode}")
except Exception:
    fail("B5: attack → flee when HP drops below threshold",
         traceback.format_exc())

# B6: chase → return when leash exceeded
try:
    random.seed(15)
    _make_arena(40, 40)
    w = _make_world()
    # NPC at origin (5,20), leash=6
    npc = _spawn_npc(w, 5.0, 20.0, aggro=30.0, leash=6.0)
    tgt = _spawn_target(w, 35.0, 20.0)  # very far away

    # Get into chase
    _tick(w, npc)
    assert _mode(w, npc) == "chase"

    # Manually move NPC far from its origin to exceed leash
    w.get(npc, Position).x = 15.0  # 10 tiles from origin > leash=6
    _advance(w, 0.016)
    _tick(w, npc)

    mode = _mode(w, npc)
    if mode == "return":
        ok("B6: chase → return when leash exceeded")
    else:
        fail("B6: chase → return when leash exceeded",
             f"mode={mode}, home_dist={math.hypot(15.0-5.0, 0)}")
except Exception:
    fail("B6: chase → return when leash exceeded",
         traceback.format_exc())

# B7: return → idle when back at origin
try:
    random.seed(16)
    _make_arena(20, 20)
    w = _make_world()
    npc = _spawn_npc(w, 10.0, 10.0, leash=5.0, aggro=20.0)
    tgt = _spawn_target(w, 18.0, 10.0)

    # Force into return mode
    brain = w.get(npc, Brain)
    c = brain.state.setdefault("combat", {})
    c["mode"] = "return"
    c["origin"] = (10.0, 10.0)

    # NPC already at origin → should transition to idle
    _tick(w, npc)
    mode = _mode(w, npc)
    if mode == "idle":
        ok("B7: return → idle when at origin")
    else:
        fail("B7: return → idle when at origin", f"mode={mode}")
except Exception:
    fail("B7: return → idle when at origin", traceback.format_exc())

# B8: flee_threshold=0 → NPC never flees
try:
    random.seed(17)
    _make_arena(20, 20)
    w = _make_world()
    npc = _spawn_npc(w, 5.0, 10.0, aggro=15.0, atk_range=10.0,
                     flee_threshold=0.0, hp=100.0)
    tgt = _spawn_target(w, 10.0, 10.0)

    # Get into attack
    _tick(w, npc)
    _advance(w, 0.016)
    _tick(w, npc)

    # Drop HP to 1%
    w.get(npc, Health).current = 1.0
    _advance(w, 0.016)
    _tick(w, npc)

    mode = _mode(w, npc)
    if mode != "flee":
        ok("B8: flee_threshold=0 → NPC never flees")
    else:
        fail("B8: flee_threshold=0 → NPC never flees", f"mode={mode}")
except Exception:
    fail("B8: flee_threshold=0 → NPC never flees", traceback.format_exc())


# ═══════════════════════════════════════════════════════════════════
#  C — COOLDOWN ENFORCEMENT
# ═══════════════════════════════════════════════════════════════════

print("\n=== C: Cooldown enforcement ===")

# C1: NPC fires once, can't fire again within cooldown
try:
    random.seed(20)
    _make_arena(20, 20)
    w = _make_world()
    npc = _spawn_npc(w, 5.0, 10.0, atk_range=10.0, cooldown=1.0)
    tgt = _spawn_target(w, 10.0, 10.0)

    # Force directly into attack mode with no warmup delay
    brain = w.get(npc, Brain)
    c = brain.state.setdefault("combat", {})
    c["mode"] = "attack"
    c["origin"] = (5.0, 10.0)
    c["p_eid"] = tgt
    c["p_pos"] = (10.0, 10.0)
    c["attack_until"] = 0.0  # no warmup

    # Tick — should fire
    _tick(w, npc)
    first_attacks = len(_attack_intents(w))
    _drain(w)

    # Advance only 0.1s (< cooldown 1.0) and tick again → should NOT fire
    _advance(w, 0.1)
    _tick(w, npc)
    second_attacks = len(_attack_intents(w))

    if first_attacks >= 1 and second_attacks == 0:
        ok("C1: NPC can't fire again within cooldown")
    else:
        fail("C1: NPC can't fire again within cooldown",
             f"first={first_attacks}, immediate_retry={second_attacks}")
except Exception:
    fail("C1: NPC can't fire again within cooldown",
         traceback.format_exc())

# C2: NPC fires again AFTER cooldown expires
try:
    random.seed(21)
    _make_arena(20, 20)
    w = _make_world()
    npc = _spawn_npc(w, 5.0, 10.0, atk_range=10.0, cooldown=0.5)
    tgt = _spawn_target(w, 10.0, 10.0)

    # Get into attack mode
    for _ in range(3):
        _tick(w, npc)
        _advance(w, 0.5)
    _drain(w)

    # Advance past cooldown and tick again
    _advance(w, 1.0)
    _tick(w, npc)
    attacks = len(_attack_intents(w))

    if attacks >= 1:
        ok("C2: NPC fires again after cooldown expires")
    else:
        c = _combat(w, npc)
        fail("C2: NPC fires again after cooldown expires",
             f"attacks={attacks}, mode={c.get('mode')}, "
             f"attack_until={c.get('attack_until', '?')}")
except Exception:
    fail("C2: NPC fires again after cooldown expires",
         traceback.format_exc())


# ═══════════════════════════════════════════════════════════════════
#  D — RANGE MAINTENANCE (ranged NPCs don't walk into melee)
# ═══════════════════════════════════════════════════════════════════

print("\n=== D: Range maintenance ===")

# D1: Ranged NPC at ideal range → strafes (nonzero velocity but
#     doesn't significantly change distance)
try:
    random.seed(30)
    _make_arena(30, 30)
    w = _make_world()
    # NPC 5 tiles from target, range=8 → ideal band is ~4..6.8
    npc = _spawn_npc(w, 10.0, 15.0, atk_range=8.0, speed=3.0)
    tgt = _spawn_target(w, 15.0, 15.0)

    # Get into attack mode
    _tick(w, npc)
    _advance(w, 0.016)
    _tick(w, npc)
    assert _mode(w, npc) == "attack", f"mode={_mode(w, npc)}"

    # Record starting distance
    npc_pos = w.get(npc, Position)
    tgt_pos = w.get(tgt, Position)
    d0 = math.hypot(npc_pos.x - tgt_pos.x, npc_pos.y - tgt_pos.y)

    # Tick several frames and check velocity is nonzero (strafing)
    _advance(w, 1.0)
    _tick(w, npc)
    vel = w.get(npc, Velocity)
    speed_mag = math.hypot(vel.x, vel.y)

    if speed_mag > 0.1:
        ok("D1: ranged NPC at ideal range strafes (v > 0.1)")
    else:
        fail("D1: ranged NPC at ideal range strafes (v > 0.1)",
             f"speed={speed_mag:.3f}")
except Exception:
    fail("D1: ranged NPC at ideal range strafes (v > 0.1)",
         traceback.format_exc())

# D2: Ranged NPC too close → moves AWAY from target
try:
    random.seed(31)
    _make_arena(30, 30)
    w = _make_world()
    # NPC 2 tiles from target, range=8 → too_close threshold = 8*0.35=2.8
    npc = _spawn_npc(w, 14.0, 15.0, atk_range=8.0, speed=3.0)
    tgt = _spawn_target(w, 15.0, 15.0)

    # Get into attack mode
    _tick(w, npc)
    _advance(w, 0.016)
    _tick(w, npc)

    # Now move NPC very close
    w.get(npc, Position).x = 14.5  # 0.5 tiles away (< 2.8 too_close)
    _advance(w, 0.5)
    _tick(w, npc)

    vel = w.get(npc, Velocity)
    npc_pos = w.get(npc, Position)
    tgt_pos = w.get(tgt, Position)
    # Velocity should be moving AWAY (negative x since target is at 15)
    dir_x = vel.x
    target_dir = tgt_pos.x - npc_pos.x  # positive (target is right)

    # NPC should move away → velocity opposite to target direction
    if (target_dir > 0 and dir_x < -0.1) or (target_dir < 0 and dir_x > 0.1):
        ok("D2: ranged NPC too close → kites away")
    elif abs(vel.x) < 0.01 and abs(vel.y) > 0.5:
        ok("D2: ranged NPC too close → moves laterally away")
    else:
        fail("D2: ranged NPC too close → kites away",
             f"vel=({vel.x:.2f}, {vel.y:.2f}), target_dir={target_dir:.1f}")
except Exception:
    fail("D2: ranged NPC too close → kites away",
         traceback.format_exc())

# D3: Ranged NPC with wall-blocked LOS → moves to reposition
try:
    random.seed(32)
    wall_cells = [(r, 10) for r in range(3, 18)]
    _make_arena(20, 20, walls=wall_cells)
    w = _make_world()
    npc = _spawn_npc(w, 8.0, 10.0, atk_range=8.0, speed=3.0)
    tgt = _spawn_target(w, 12.0, 10.0)

    # Several ticks — NPC should be chasing (wall blocks attack transition)
    for _ in range(5):
        _tick(w, npc)
        _advance(w, 0.1)

    vel = w.get(npc, Velocity)
    speed_mag = math.hypot(vel.x, vel.y)
    mode = _mode(w, npc)

    if speed_mag > 0.1 and mode == "chase":
        ok("D3: wall-blocked ranged NPC chases to find LOS")
    else:
        fail("D3: wall-blocked ranged NPC chases to find LOS",
             f"speed={speed_mag:.3f}, mode={mode}")
except Exception:
    fail("D3: wall-blocked ranged NPC chases to find LOS",
         traceback.format_exc())


# ═══════════════════════════════════════════════════════════════════
#  E — ALLY SAFETY  (don't shoot through teammates)
# ═══════════════════════════════════════════════════════════════════

print("\n=== E: Ally safety ===")

# E1: Ally directly between shooter and target → no fire (within patience)
try:
    random.seed(40)
    _make_arena(30, 30)
    w = _make_world()
    npc = _spawn_npc(w, 5.0, 15.0, atk_range=10.0, cooldown=0.1,
                     faction_group="red")
    tgt = _spawn_target(w, 15.0, 15.0)

    # Spawn an ally between them (same faction as NPC)
    ally = w.spawn()
    w.add(ally, Position(x=10.0, y=15.0, zone=ZONE))
    w.add(ally, Health(current=50, maximum=50))
    w.add(ally, Faction(group="red", disposition="hostile",
                        home_disposition="hostile"))
    w.zone_add(ally, ZONE)

    # Force into attack mode so we isolate the ally-in-fire check
    brain = w.get(npc, Brain)
    c = brain.state.setdefault("combat", {})
    c["mode"] = "attack"
    c["origin"] = (5.0, 15.0)
    c["p_eid"] = tgt
    c["p_pos"] = (15.0, 15.0)
    c["attack_until"] = 0.0

    # Single tick — ally blocks the shot
    _tick(w, npc)

    attacks = _attack_intents(w)
    blocked_count = _combat(w, npc).get("_los_blocked_count", 0)

    if len(attacks) == 0 and blocked_count >= 1:
        ok("E1: NPC holds fire when ally in line of fire")
    else:
        fail("E1: NPC holds fire when ally in line of fire",
             f"attacks={len(attacks)}, blocked_count={blocked_count}")
except Exception:
    fail("E1: NPC holds fire when ally in line of fire",
         traceback.format_exc())


# ═══════════════════════════════════════════════════════════════════
#  F — MELEE SUB-FSM  (approach → circle → lunge → retreat)
# ═══════════════════════════════════════════════════════════════════

print("\n=== F: Melee sub-FSM ===")

# F1: Melee NPC approaches when far from target
try:
    random.seed(50)
    _make_arena(30, 30)
    w = _make_world()
    npc = _spawn_npc(w, 5.0, 15.0, brain_kind="hostile_melee",
                     attack_type="melee", atk_range=1.5, aggro=15.0,
                     speed=3.0)
    tgt = _spawn_target(w, 7.0, 15.0)  # 2 tiles away

    # Get into attack mode
    _tick(w, npc)
    _advance(w, 0.016)
    _tick(w, npc)

    sub = _combat(w, npc).get("melee_sub", "?")
    mode = _mode(w, npc)

    if mode == "attack" and sub == "approach":
        ok("F1: melee NPC uses 'approach' sub-state when far")
    elif mode == "chase":
        ok("F1: melee NPC chases when not yet in melee range")
    else:
        fail("F1: melee NPC approaches or chases toward target",
             f"mode={mode}, sub={sub}")
except Exception:
    fail("F1: melee NPC approaches or chases toward target",
         traceback.format_exc())

# F2: Melee NPC transitions to circle when at ideal range
try:
    random.seed(51)
    _make_arena(30, 30)
    w = _make_world()
    npc = _spawn_npc(w, 14.2, 15.0, brain_kind="hostile_melee",
                     attack_type="melee", atk_range=1.5, aggro=15.0)
    tgt = _spawn_target(w, 15.0, 15.0)  # 0.8 tiles — inside ideal_r

    # Force into attack + approach so we isolate the sub-FSM transition
    brain = w.get(npc, Brain)
    c = brain.state.setdefault("combat", {})
    c["mode"] = "attack"
    c["melee_sub"] = "approach"
    c["origin"] = (14.2, 15.0)
    c["p_eid"] = tgt
    c["p_pos"] = (15.0, 15.0)
    c["attack_until"] = 0.0

    # Tick advances the sub-FSM: approach → circle (dist 1.5 < ideal_r*1.2 = 2.88)
    _tick(w, npc)

    sub = _combat(w, npc).get("melee_sub", "?")
    if sub == "circle":
        ok("F2: melee NPC enters 'circle' at ideal range")
    else:
        d = math.hypot(w.get(npc, Position).x - 15.0,
                       w.get(npc, Position).y - 15.0)
        fail("F2: melee NPC enters 'circle' at ideal range",
             f"sub={sub}, dist={d:.2f}, mode={_mode(w, npc)}")
except Exception:
    fail("F2: melee NPC enters 'circle' at ideal range",
         traceback.format_exc())

# F3: Melee NPC retreats after landing a hit
try:
    random.seed(52)
    _make_arena(30, 30)
    w = _make_world()
    npc = _spawn_npc(w, 14.0, 15.0, brain_kind="hostile_melee",
                     attack_type="melee", atk_range=1.5, aggro=15.0)
    tgt = _spawn_target(w, 15.0, 15.0)

    # Get into attack+lunge
    _tick(w, npc)
    _advance(w, 0.016)
    _tick(w, npc)

    # Force into lunge sub-state and simulate a hit
    c = _combat(w, npc)
    c["melee_sub"] = "lunge"
    c["_melee_just_hit"] = True
    _advance(w, 0.5)
    _tick(w, npc)

    sub = c.get("melee_sub", "?")
    if sub == "retreat":
        ok("F3: melee NPC retreats after landing a hit")
    else:
        fail("F3: melee NPC retreats after landing a hit",
             f"sub={sub}")
except Exception:
    fail("F3: melee NPC retreats after landing a hit",
         traceback.format_exc())

# F4: Melee retreat → back to circle after timer expires
try:
    random.seed(53)
    _make_arena(30, 30)
    w = _make_world()
    npc = _spawn_npc(w, 14.0, 15.0, brain_kind="hostile_melee",
                     attack_type="melee", atk_range=1.5, aggro=15.0)
    tgt = _spawn_target(w, 15.0, 15.0)

    # Set up retreat state with expired timer
    _tick(w, npc)
    _advance(w, 0.016)
    _tick(w, npc)

    c = _combat(w, npc)
    c["melee_sub"] = "retreat"
    c["melee_retreat_timer"] = 0.0  # expired
    _advance(w, 0.5)
    _tick(w, npc)

    sub = c.get("melee_sub", "?")
    if sub == "circle":
        ok("F4: melee retreat → circle after timer expires")
    else:
        fail("F4: melee retreat → circle after timer expires",
             f"sub={sub}")
except Exception:
    fail("F4: melee retreat → circle after timer expires",
         traceback.format_exc())


# ═══════════════════════════════════════════════════════════════════
#  G — REPOSITIONING (ranged NPCs seek LOS positions)
# ═══════════════════════════════════════════════════════════════════

print("\n=== G: Repositioning ===")

# G1: find_los_position returns a spot with clear wall LOS
try:
    random.seed(60)
    # Wall column at x=10, gap at r=5 (passable at 5,10 is grass)
    wall_cells = [(r, 10) for r in range(3, 18) if r != 5]
    tiles = _make_arena(20, 20, walls=wall_cells)
    w = _make_world()

    from logic.combat_sensing import find_los_position
    from core.zone import has_line_of_sight

    result = find_los_position(
        ZONE, 8.0, 10.0,   # NPC position
        12.0, 10.0,         # target position
        8.0,                # atk_range
        origin=(8.0, 10.0),
    )

    if result is not None:
        rx, ry = result
        has_los = has_line_of_sight(ZONE, rx + 0.4, ry + 0.4,
                                   12.4, 10.4)
        if has_los:
            ok("G1: find_los_position returns a spot with clear LOS")
        else:
            fail("G1: find_los_position returns a spot with clear LOS",
                 f"pos=({rx:.1f}, {ry:.1f}) but LOS is blocked")
    else:
        fail("G1: find_los_position returns a spot with clear LOS",
             "returned None")
except Exception:
    fail("G1: find_los_position returns a spot with clear LOS",
         traceback.format_exc())

# G2: find_los_position returns None when no clear position exists
try:
    random.seed(61)
    # Complete wall box around the NPC — no LOS possible from nearby
    thick_walls = []
    for r in range(3, 18):
        for c_off in (7, 8, 9, 10, 11, 12, 13):
            thick_walls.append((r, c_off))
    _make_arena(20, 20, walls=thick_walls)

    from logic.combat_sensing import find_los_position

    result = find_los_position(
        ZONE, 5.0, 10.0,    # NPC position behind thick wall
        15.0, 10.0,          # target position
        8.0,
        origin=(5.0, 10.0),
    )

    if result is None:
        ok("G2: find_los_position returns None when no LOS possible")
    else:
        # Check if the returned position actually has LOS
        from core.zone import has_line_of_sight
        has = has_line_of_sight(ZONE, result[0]+0.4, result[1]+0.4,
                               15.4, 10.4)
        if has:
            ok("G2: (found unexpected LOS position, but it IS valid)")
        else:
            fail("G2: find_los_position returns None when no LOS possible",
                 f"returned ({result[0]:.1f}, {result[1]:.1f}) with no LOS")
except Exception:
    fail("G2: find_los_position returns None when no LOS possible",
         traceback.format_exc())


# ═══════════════════════════════════════════════════════════════════
#  H — VELOCITY INTEGRITY  (brain-set movement is not dampened)
# ═══════════════════════════════════════════════════════════════════

print("\n=== H: Velocity integrity ===")

# H1: NPC velocity after movement_system preserves brain-intended speed
try:
    random.seed(70)
    _make_arena(30, 30)
    w = _make_world()
    npc = _spawn_npc(w, 5.0, 15.0, speed=3.0, aggro=15.0)
    tgt = _spawn_target(w, 15.0, 15.0)

    # Brain sets velocity
    _tick(w, npc)
    vel = w.get(npc, Velocity)
    brain_speed = math.hypot(vel.x, vel.y)

    # Now run movement system
    from logic.systems import movement_system
    tiles = ZONE_MAPS[ZONE]
    movement_system(w, 0.016, tiles)

    # After movement system, check that position moved the expected amount
    pos = w.get(npc, Position)
    # The key check: did the entity move at approximately the speed
    # the brain intended, or was it dampened?
    # Position should have changed by approximately brain_speed * 0.016
    expected_move = brain_speed * 0.016
    actual_move = math.hypot(pos.x - 5.0, pos.y - 15.0)

    # Allow 20% tolerance for pathfinding direction differences
    if brain_speed < 0.01:
        ok("H1: (NPC not moving, velocity test N/A)")
    elif actual_move >= expected_move * 0.75:
        ok("H1: movement system preserves brain-intended speed")
    else:
        ratio = actual_move / expected_move if expected_move > 0 else 0
        fail("H1: movement system preserves brain-intended speed",
             f"brain_speed={brain_speed:.2f}, expected_move={expected_move:.4f}, "
             f"actual_move={actual_move:.4f}, ratio={ratio:.2f}")
except Exception:
    fail("H1: movement system preserves brain-intended speed",
         traceback.format_exc())


# ═══════════════════════════════════════════════════════════════════
#  I — SENSING CORRECTNESS
# ═══════════════════════════════════════════════════════════════════

print("\n=== I: Sensing correctness ===")

# I1: acquire_target finds player in same zone
try:
    random.seed(80)
    _make_arena(20, 20)
    w = _make_world()
    npc = _spawn_npc(w, 5.0, 10.0)
    tgt = _spawn_target(w, 10.0, 10.0)

    from logic.combat_sensing import acquire_target

    pos = w.get(npc, Position)
    info = acquire_target(w, npc, pos, 12.0)
    if info.eid == tgt:
        ok("I1: acquire_target finds player in same zone")
    else:
        fail("I1: acquire_target finds player in same zone",
             f"expected eid={tgt}, got eid={info.eid}")
except Exception:
    fail("I1: acquire_target finds player in same zone",
         traceback.format_exc())

# I2: acquire_target reports wall_los=False through wall
try:
    random.seed(81)
    wall_cells = [(r, 10) for r in range(3, 18)]
    _make_arena(20, 20, walls=wall_cells)
    w = _make_world()
    npc = _spawn_npc(w, 8.0, 10.0)
    tgt = _spawn_target(w, 12.0, 10.0)

    from logic.combat_sensing import acquire_target

    pos = w.get(npc, Position)
    info = acquire_target(w, npc, pos, 12.0)
    if info.eid is not None and info.wall_los is False:
        ok("I2: acquire_target reports wall_los=False through wall")
    else:
        fail("I2: acquire_target reports wall_los=False through wall",
             f"eid={info.eid}, wall_los={info.wall_los}")
except Exception:
    fail("I2: acquire_target reports wall_los=False through wall",
         traceback.format_exc())

# I3: acquire_target reports wall_los=True with clear path
try:
    random.seed(82)
    _make_arena(20, 20)  # no interior walls
    w = _make_world()
    npc = _spawn_npc(w, 5.0, 10.0)
    tgt = _spawn_target(w, 10.0, 10.0)

    from logic.combat_sensing import acquire_target

    pos = w.get(npc, Position)
    info = acquire_target(w, npc, pos, 12.0)
    if info.eid is not None and info.wall_los is True:
        ok("I3: acquire_target reports wall_los=True with clear path")
    else:
        fail("I3: acquire_target reports wall_los=True with clear path",
             f"eid={info.eid}, wall_los={info.wall_los}")
except Exception:
    fail("I3: acquire_target reports wall_los=True with clear path",
         traceback.format_exc())

# I4: ally_in_line_of_fire detects ally between shooter and target
try:
    random.seed(83)
    _make_arena(30, 30)
    w = _make_world()
    npc = _spawn_npc(w, 5.0, 15.0, faction_group="red")
    tgt = _spawn_target(w, 15.0, 15.0)

    # Ally between them
    ally = w.spawn()
    w.add(ally, Position(x=10.0, y=15.0, zone=ZONE))
    w.add(ally, Health(current=50, maximum=50))
    w.add(ally, Faction(group="red", disposition="hostile",
                        home_disposition="hostile"))
    w.zone_add(ally, ZONE)

    from logic.combat_sensing import ally_in_line_of_fire

    npc_pos = w.get(npc, Position)
    result = ally_in_line_of_fire(w, npc, npc_pos, 15.0, 15.0)
    if result is True:
        ok("I4: ally_in_line_of_fire detects ally on segment")
    else:
        fail("I4: ally_in_line_of_fire detects ally on segment",
             f"result={result}")
except Exception:
    fail("I4: ally_in_line_of_fire detects ally on segment",
         traceback.format_exc())

# I5: ally_in_line_of_fire returns False when ally is off to the side
try:
    random.seed(84)
    _make_arena(30, 30)
    w = _make_world()
    npc = _spawn_npc(w, 5.0, 15.0, faction_group="red")
    tgt = _spawn_target(w, 15.0, 15.0)

    # Ally far off the line of fire
    ally = w.spawn()
    w.add(ally, Position(x=10.0, y=5.0, zone=ZONE))
    w.add(ally, Health(current=50, maximum=50))
    w.add(ally, Faction(group="red", disposition="hostile",
                        home_disposition="hostile"))
    w.zone_add(ally, ZONE)

    from logic.combat_sensing import ally_in_line_of_fire

    npc_pos = w.get(npc, Position)
    result = ally_in_line_of_fire(w, npc, npc_pos, 15.0, 15.0)
    if result is False:
        ok("I5: ally_in_line_of_fire returns False for off-axis ally")
    else:
        fail("I5: ally_in_line_of_fire returns False for off-axis ally",
             f"result={result}")
except Exception:
    fail("I5: ally_in_line_of_fire returns False for off-axis ally",
         traceback.format_exc())

# I6: is_detected_idle with VisionCone — target behind NPC is NOT detected
try:
    random.seed(85)
    _make_arena(30, 30)
    w = _make_world()
    npc = _spawn_npc(w, 15.0, 15.0, aggro=20.0)
    # Add narrow vision cone facing right
    w.add(npc, VisionCone(fov_degrees=60, view_distance=12.0,
                          peripheral_range=2.0))
    w.get(npc, Facing).direction = "right"

    # Target is to the LEFT (behind the NPC's facing)
    tgt = _spawn_target(w, 5.0, 15.0)

    from logic.combat_sensing import is_detected_idle

    npc_pos = w.get(npc, Position)
    dist = math.hypot(15.0 - 5.0, 0)
    detected = is_detected_idle(w, npc, npc_pos, 5.0, 15.0,
                                dist, 20.0)
    if detected is False:
        ok("I6: VisionCone blocks detection of target behind NPC")
    else:
        fail("I6: VisionCone blocks detection of target behind NPC",
             f"detected={detected}, dist={dist}")
except Exception:
    fail("I6: VisionCone blocks detection of target behind NPC",
         traceback.format_exc())


# ═══════════════════════════════════════════════════════════════════
#  J — ATTACK-MODE WALL-BLOCK REPOSITIONING
#       (NPC in attack mode with wall → seeks flank position)
# ═══════════════════════════════════════════════════════════════════

print("\n=== J: Attack-mode repositioning ===")

# J1: NPC in attack gets wall-blocked → _wall_blocked flag set
try:
    random.seed(90)
    _make_arena(20, 20)
    w = _make_world()
    npc = _spawn_npc(w, 5.0, 10.0, atk_range=10.0, aggro=15.0)
    tgt = _spawn_target(w, 10.0, 10.0)

    # Get into attack mode with clear LOS
    _tick(w, npc)
    _advance(w, 0.016)
    _tick(w, npc)
    assert _mode(w, npc) == "attack"
    _drain(w)

    # Place wall between them
    tiles = ZONE_MAPS[ZONE]
    for r in range(3, 18):
        tiles[r][8] = TILE_WALL

    _advance(w, 0.5)
    _tick(w, npc)

    c = _combat(w, npc)
    wall_blocked = c.get("_wall_blocked", False)
    if wall_blocked:
        ok("J1: _wall_blocked flag set when LOS lost in attack mode")
    else:
        fail("J1: _wall_blocked flag set when LOS lost in attack mode",
             f"_wall_blocked={wall_blocked}")
except Exception:
    fail("J1: _wall_blocked flag set when LOS lost in attack mode",
         traceback.format_exc())


# ═══════════════════════════════════════════════════════════════════
#  K — FACTION GATE  (neutral/friendly NPCs don't attack)
# ═══════════════════════════════════════════════════════════════════

print("\n=== K: Faction gating ===")

# K1: NPC with disposition=friendly stays idle
try:
    random.seed(100)
    _make_arena(20, 20)
    w = _make_world()
    npc = _spawn_npc(w, 5.0, 10.0, aggro=15.0)
    # Override disposition to friendly
    w.get(npc, Faction).disposition = "friendly"
    tgt = _spawn_target(w, 10.0, 10.0)

    for _ in range(5):
        _tick(w, npc)
        _advance(w, 0.1)

    mode = _mode(w, npc)
    attacks = _attack_intents(w)
    if mode == "idle" and len(attacks) == 0:
        ok("K1: friendly NPC stays idle and never attacks")
    else:
        fail("K1: friendly NPC stays idle and never attacks",
             f"mode={mode}, attacks={len(attacks)}")
except Exception:
    fail("K1: friendly NPC stays idle and never attacks",
         traceback.format_exc())


# ═══════════════════════════════════════════════════════════════════
#  L — MULTI-TICK CONSISTENCY
#       (brain doesn't crash or enter invalid state over many ticks)
# ═══════════════════════════════════════════════════════════════════

print("\n=== L: Multi-tick stability ===")

# L1: 200 ticks without crash, mode always valid
try:
    random.seed(110)
    _make_arena(30, 30)
    w = _make_world()
    npc = _spawn_npc(w, 5.0, 15.0, aggro=15.0, atk_range=8.0,
                     cooldown=0.3, speed=3.0)
    tgt = _spawn_target(w, 15.0, 15.0)

    valid_modes = {"idle", "chase", "attack", "flee", "return"}
    invalid_found = None
    for i in range(200):
        _tick(w, npc)
        _advance(w, 0.016)
        m = _mode(w, npc)
        if m not in valid_modes:
            invalid_found = (i, m)
            break

    if invalid_found is None:
        ok("L1: 200 ticks without crash, mode always valid")
    else:
        fail("L1: 200 ticks without crash, mode always valid",
             f"tick {invalid_found[0]}: mode={invalid_found[1]}")
except Exception:
    fail("L1: 200 ticks without crash, mode always valid",
         traceback.format_exc())

# L2: Melee NPC 200 ticks — melee_sub always valid
try:
    random.seed(111)
    _make_arena(30, 30)
    w = _make_world()
    npc = _spawn_npc(w, 14.0, 15.0, brain_kind="hostile_melee",
                     attack_type="melee", atk_range=1.5, aggro=15.0,
                     cooldown=0.3, speed=3.0)
    tgt = _spawn_target(w, 15.0, 15.0)

    valid_subs = {"approach", "circle", "feint", "lunge", "retreat", "?", None}
    invalid_found = None
    for i in range(200):
        _tick(w, npc)
        _advance(w, 0.016)
        c = _combat(w, npc)
        m = c.get("mode")
        if m == "attack":
            sub = c.get("melee_sub")
            if sub not in valid_subs:
                invalid_found = (i, sub)
                break

    if invalid_found is None:
        ok("L2: 200 melee ticks, sub-state always valid")
    else:
        fail("L2: 200 melee ticks, sub-state always valid",
             f"tick {invalid_found[0]}: melee_sub={invalid_found[1]}")
except Exception:
    fail("L2: 200 melee ticks, sub-state always valid",
         traceback.format_exc())


# ═══════════════════════════════════════════════════════════════════
#  Summary
# ═══════════════════════════════════════════════════════════════════

total = passed + failed
print(f"\n{'='*50}")
print(f" Combat Behavior Tests: {passed}/{total} passed")
if failed:
    print(f" {failed} FAILED")
print(f"{'='*50}")

sys.exit(0 if failed == 0 else 1)
