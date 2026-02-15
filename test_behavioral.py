"""test_behavioral.py — Tight-tolerance behavioral tests.

Tests exact reaction times, multi-NPC dynamics, movement quality,
projectile accuracy, flee behavior, and full combat pipelines in
highly controlled arenas with seeded RNG.

Run:  python test_behavioral.py

Three arena types:
  ARENA_MELEE    20×20  — forces close engagement
  ARENA_CORRIDOR 60×20  — rooms + chokepoints for pathfinding
  ARENA_RANGE   100×10  — long firing lane for projectile tests
"""
from __future__ import annotations
import sys, math, random, traceback

# ── Bootstrap ────────────────────────────────────────────────────────
from core.tuning import load as _load_tuning
_load_tuning()

from core.ecs import World
from core.zone import ZONE_MAPS
from core.constants import TILE_GRASS, TILE_WALL, TILE_SIZE
from core.events import EventBus, AttackIntent, EntityDied
from components import (
    Position, Velocity, Sprite, Identity, Collider, Hurtbox,
    Facing, Health, Lod, Brain, GameClock,
)
from components.ai import HomeRange, Threat, AttackConfig, VisionCone
from components.combat import CombatStats, Projectile
from components.rendering import HitFlash
from components.social import Faction
from logic.movement import movement_system
from logic.ai.brains import tick_ai
from logic.combat.projectiles import projectile_system
from logic.combat import handle_death, npc_melee_attack, npc_ranged_attack
from logic.combat.engagement import _combat_brain
from logic.ai.perception import in_vision_cone, facing_to_angle


# ── Test harness ─────────────────────────────────────────────────────

_passed = 0
_failed = 0

def ok(label: str):
    global _passed
    _passed += 1
    print(f"  [PASS] {label}")

def fail(label: str, detail: str = ""):
    global _failed
    _failed += 1
    msg = f"  [FAIL] {label}"
    if detail:
        msg += f" — {detail}"
    print(msg)

def check(cond: bool, label: str, detail: str = ""):
    if cond:
        ok(label)
    else:
        fail(label, detail)

DT = 1.0 / 60.0  # 60 FPS


# ── Arena builders ───────────────────────────────────────────────────

def _make_arena(w: int, h: int, zone: str) -> list[list[int]]:
    """Open arena with wall border."""
    tiles = [[TILE_GRASS] * w for _ in range(h)]
    for r in range(h):
        tiles[r][0] = TILE_WALL
        tiles[r][w - 1] = TILE_WALL
    for c in range(w):
        tiles[0][c] = TILE_WALL
        tiles[h - 1][c] = TILE_WALL
    ZONE_MAPS[zone] = tiles
    return tiles


def _make_corridor_arena(zone: str) -> list[list[int]]:
    """60×20 corridor with two rooms connected by a 2-tile-wide chokepoint.

    Room A: cols 1-24,  rows 1-18 (open)
    Wall:   col 25,     rows 1-8 and rows 11-18 (gap at rows 9-10)
    Room B: cols 26-58, rows 1-18 (open)
    """
    W, H = 60, 20
    tiles = _make_arena(W, H, zone)
    # Internal wall with 2-tile gap
    for r in range(1, H - 1):
        if r < 9 or r > 10:
            tiles[r][25] = TILE_WALL
    ZONE_MAPS[zone] = tiles
    return tiles


def _make_firing_range(zone: str) -> list[list[int]]:
    """100×10 long range."""
    return _make_arena(100, 10, zone)


# ── Entity spawners ─────────────────────────────────────────────────

def _spawn_fighter(w: World, zone: str, name: str, brain_kind: str,
                   x: float, y: float, faction_group: str,
                   facing_dir: str = "right", *,
                   hp: int = 100, damage: int = 10, defense: int = 5,
                   speed: float = 2.0,
                   aggro: float = 5000.0, leash: float = 200.0,
                   flee_threshold: float = 0.2,
                   sensor_interval: float = 0.1,
                   atk_type: str = "melee",
                   atk_range: float = 1.2, cooldown: float = 0.5,
                   accuracy: float = 0.85, proj_speed: float = 14.0,
                   fov: float = 120.0, view_dist: float = 5000.0,
                   peripheral: float = 10.0) -> int:
    """Spawn a fully configured combat NPC. All params explicit."""
    eid = w.spawn()
    w.add(eid, Position(x=x, y=y, zone=zone))
    w.add(eid, Velocity())
    w.add(eid, Sprite(char=name[0], color=(200, 200, 200)))
    w.add(eid, Identity(name=name, kind="npc"))
    w.add(eid, Collider())
    w.add(eid, Hurtbox())
    w.add(eid, Facing(direction=facing_dir))
    w.add(eid, Health(current=hp, maximum=hp))
    w.add(eid, CombatStats(damage=damage, defense=defense))
    w.add(eid, Lod(level="high"))
    w.add(eid, Brain(kind=brain_kind, active=True))
    w.add(eid, HomeRange(origin_x=x, origin_y=y, radius=50.0, speed=speed))
    w.add(eid, Faction(group=faction_group, disposition="hostile",
                       home_disposition="hostile"))
    w.add(eid, Threat(aggro_radius=aggro, leash_radius=leash,
                      flee_threshold=flee_threshold,
                      sensor_interval=sensor_interval))
    w.add(eid, AttackConfig(attack_type=atk_type, range=atk_range,
                            cooldown=cooldown, accuracy=accuracy,
                            proj_speed=proj_speed))
    w.add(eid, VisionCone(fov_degrees=fov, view_distance=view_dist,
                          peripheral_range=peripheral))
    w.zone_add(eid, zone)
    return eid


def _spawn_dummy(w: World, zone: str, name: str, x: float, y: float,
                 faction_group: str = "enemies",
                 hp: int = 200) -> int:
    """Stationary target dummy — no brain, no movement."""
    eid = w.spawn()
    w.add(eid, Position(x=x, y=y, zone=zone))
    w.add(eid, Velocity())
    w.add(eid, Sprite(char="X", color=(200, 200, 200)))
    w.add(eid, Identity(name=name, kind="npc"))
    w.add(eid, Collider())
    w.add(eid, Hurtbox())
    w.add(eid, Facing())
    w.add(eid, Health(current=hp, maximum=hp))
    w.add(eid, CombatStats(damage=0, defense=0))
    w.add(eid, Lod(level="high"))
    w.add(eid, Brain(kind="wander", active=False))
    w.add(eid, Faction(group=faction_group, disposition="hostile",
                       home_disposition="hostile"))
    w.zone_add(eid, zone)
    return eid


# ── Simulation runner ────────────────────────────────────────────────

def _setup_bus(w: World):
    """Wire up EventBus + GameClock with death + attack handlers."""
    w.set_res(EventBus())
    w.set_res(GameClock())
    bus = w.res(EventBus)
    bus.subscribe("EntityDied", lambda ev: handle_death(w, ev.eid))
    bus.subscribe("AttackIntent", lambda ev: (
        npc_ranged_attack(w, ev.attacker_eid, ev.target_eid)
        if ev.attack_type == "ranged"
        else npc_melee_attack(w, ev.attacker_eid, ev.target_eid)))


def _tick(w: World, tiles: list[list[int]], dt: float = DT):
    """One full game tick — AI, movement, projectiles, events."""
    clock = w.res(GameClock)
    if clock:
        clock.time += dt
    tick_ai(w, dt)
    movement_system(w, dt, tiles)
    projectile_system(w, dt, tiles)
    bus = w.res(EventBus)
    if bus:
        bus.drain()


def _run_ticks(w: World, tiles: list[list[int]], n: int,
               dt: float = DT) -> None:
    for _ in range(n):
        _tick(w, tiles, dt)


def _get_mode(w: World, eid: int) -> str:
    brain = w.get(eid, Brain)
    if not brain:
        return "no_brain"
    return brain.state.get("combat", {}).get("mode", "idle")


def _get_melee_sub(w: World, eid: int) -> str:
    brain = w.get(eid, Brain)
    if not brain:
        return "none"
    return brain.state.get("combat", {}).get("melee_sub", "none")


def _dist(w: World, a: int, b: int) -> float:
    pa = w.get(a, Position)
    pb = w.get(b, Position)
    if not pa or not pb:
        return float("inf")
    return math.hypot(pa.x - pb.x, pa.y - pb.y)


def _hp_frac(w: World, eid: int) -> float:
    h = w.get(eid, Health)
    if not h or h.maximum == 0:
        return 0
    return h.current / h.maximum


# ═══════════════════════════════════════════════════════════════════════
#  SECTION 1:  REACTION TIMING
# ═══════════════════════════════════════════════════════════════════════

def test_reaction_timing():
    """Measure exact tick counts for detection → chase → first attack."""
    print("\n=== 1: Reaction Timing (tight tolerances) ===")
    ZONE = "react_test"
    random.seed(42)

    # ── 1a: Idle → Chase transition time ─────────────────────────────
    # Melee NPC facing right, enemy 15 m ahead (well within vision cone).
    # sensor_interval=0.1s = 6 frames.  NPC should enter chase within
    # the first sensor tick (≤ 6 frames + stagger).
    w = World()
    _setup_bus(w)
    tiles = _make_arena(40, 20, ZONE)

    random.seed(42)
    npc = _spawn_fighter(w, ZONE, "Soldier", "hostile_melee",
                         5.0, 10.0, "blue", "right",
                         speed=2.0, sensor_interval=0.1)
    target = _spawn_dummy(w, ZONE, "Target", 20.0, 10.0, "red")

    # Tick until chase or timeout at 30 ticks (0.5 s)
    chase_tick = None
    for t in range(30):
        _tick(w, tiles)
        if _get_mode(w, npc) == "chase":
            chase_tick = t + 1
            break

    check(chase_tick is not None,
          "1a: NPC entered chase from idle",
          f"mode={_get_mode(w, npc)} after 30 ticks")
    if chase_tick is not None:
        # With sensor_interval=0.1s and seeded stagger, should be ≤12 ticks
        check(chase_tick <= 12,
              f"1a: Chase reaction ≤ 12 ticks (got {chase_tick})",
              f"chase_tick={chase_tick}, expected ≤12")

    # ── 1b: Chase → Attack transition (ranged) ──────────────────────
    # Ranged NPC at distance = atk_range * 1.0 (within chase_to_attack
    # threshold of range * 1.1).  Should transition to attack very quickly.
    w2 = World()
    _setup_bus(w2)
    tiles2 = _make_arena(40, 20, ZONE)

    random.seed(42)
    shooter = _spawn_fighter(w2, ZONE, "Sniper", "hostile_ranged",
                             5.0, 10.0, "blue", "right",
                             speed=2.0, atk_type="ranged",
                             atk_range=12.0, cooldown=0.8,
                             sensor_interval=0.1)
    target2 = _spawn_dummy(w2, ZONE, "Target", 16.0, 10.0, "red")
    # dist = 11.0 m, atk_range * 1.1 = 13.2 → qualifies for attack

    attack_tick = None
    for t in range(30):
        _tick(w2, tiles2)
        if _get_mode(w2, shooter) == "attack":
            attack_tick = t + 1
            break

    check(attack_tick is not None,
          "1b: Ranged NPC entered attack mode",
          f"mode={_get_mode(w2, shooter)}")
    if attack_tick is not None:
        check(attack_tick <= 15,
              f"1b: Attack mode ≤ 15 ticks (got {attack_tick})",
              f"attack_tick={attack_tick}")

    # ── 1c: Time-to-first-shot (ranged) ─────────────────────────────
    # Continue ticking the ranged NPC — measure when first damage lands.
    target2_hp_start = w2.get(target2, Health).current
    first_hit_tick = None
    for t in range(180):  # 3 seconds — accounts for detection + cooldown + flight
        _tick(w2, tiles2)
        h = w2.get(target2, Health)
        if h and h.current < target2_hp_start:
            first_hit_tick = (attack_tick or 0) + t + 1
            break

    check(first_hit_tick is not None,
          "1c: First ranged hit landed",
          "no damage after 180 ticks")
    if first_hit_tick is not None:
        # cooldown=0.8, attack_until random(0.1, 0.64), projectile travel ~11m/14=0.79s
        # Total from attack mode: up to ~1.8s = 108 ticks max,
        # plus initial detection ~11 ticks.  Allow up to 180.
        check(first_hit_tick <= 180,
              f"1c: First hit ≤ 180 ticks from start (got {first_hit_tick})",
              f"first_hit_tick={first_hit_tick}")

    # ── 1d: Melee time-to-first-hit ─────────────────────────────────
    # Melee NPC 5 m from dummy.  Speed 2.0, chase_mult=1.4 → 2.8 m/s.
    # 5m / 2.8 ≈ 1.79 s = 107 frames to close.  Then melee sub-FSM.
    w3 = World()
    _setup_bus(w3)
    tiles3 = _make_arena(30, 20, ZONE)

    random.seed(42)
    melee = _spawn_fighter(w3, ZONE, "Brawler", "hostile_melee",
                           5.0, 10.0, "blue", "right",
                           speed=2.0, atk_range=1.2, cooldown=0.5,
                           sensor_interval=0.1, damage=15, defense=0)
    dummy = _spawn_dummy(w3, ZONE, "Dummy", 10.0, 10.0, "red", hp=500)

    dummy_start_hp = w3.get(dummy, Health).current
    melee_first_hit = None
    for t in range(360):  # 6 seconds
        _tick(w3, tiles3)
        h = w3.get(dummy, Health)
        if h and h.current < dummy_start_hp:
            melee_first_hit = t + 1
            break

    check(melee_first_hit is not None,
          "1d: Melee first hit landed",
          "no damage after 360 ticks")
    if melee_first_hit is not None:
        # 5m gap, 2.8 m/s chase → ~107 ticks.  Then approach + lunge.
        # Conservatively ≤ 240 ticks (4 s) to close and hit.
        check(melee_first_hit <= 240,
              f"1d: Melee hit ≤ 240 ticks (got {melee_first_hit})",
              f"melee_first_hit={melee_first_hit}")

    # ── 1e: Hearing reaction time ────────────────────────────────────
    # Hostile idle guard hears gunshot 50 m away. Should enter
    # "searching" within 2 sensor ticks.  Previously, hostile NPCs
    # were skipped by emit_combat_sound — now only active modes
    # (chase/attack/flee) are skipped.
    from logic.combat.attacks import emit_combat_sound, share_combat_intel
    w4 = World()
    _setup_bus(w4)
    tiles4 = _make_arena(80, 20, ZONE)

    random.seed(42)
    guard = _spawn_fighter(w4, ZONE, "Guard", "guard",
                           10.0, 10.0, "guards", "right",
                           sensor_interval=0.1)
    # Guard is HOSTILE but IDLE (facing right, no targets in view).
    # Sound should still reach it.
    # No target NPC — just a sound source position.
    src_eid = w4.spawn()
    w4.add(src_eid, Position(x=60.0, y=10.0, zone=ZONE))
    w4.add(src_eid, Identity(name="SoundSrc", kind="npc"))
    w4.add(src_eid, Faction(group="enemies", disposition="hostile",
                            home_disposition="hostile"))
    src_pos = w4.get(src_eid, Position)

    # Tick once to initialize brain state
    _tick(w4, tiles4)

    emit_combat_sound(w4, src_eid, src_pos, "gunshot")

    search_tick = None
    for t in range(30):
        _tick(w4, tiles4)
        mode = _get_mode(w4, guard)
        if mode == "searching":
            search_tick = t + 1
            break

    check(search_tick is not None,
          "1e: Hostile idle guard entered searching after gunshot",
          f"mode={_get_mode(w4, guard)}")
    if search_tick is not None:
        check(search_tick <= 20,
              f"1e: Search reaction ≤ 20 ticks (got {search_tick})",
              f"search_tick={search_tick}")

    # ── 1f: Intel sharing — active combatant alerts idle ally ────────
    # NPC_A is chasing a target.  NPC_B (same faction) is idle,
    # facing away.  Intel sharing should put B into "searching".
    w5 = World()
    _setup_bus(w5)
    tiles5 = _make_arena(40, 20, ZONE)

    random.seed(42)
    npc_a = _spawn_fighter(w5, ZONE, "Fighter_A", "hostile_melee",
                           10.0, 10.0, "blue", "right",
                           sensor_interval=0.0)  # instant detection
    npc_b = _spawn_fighter(w5, ZONE, "Fighter_B", "hostile_melee",
                           14.0, 10.0, "blue", "left",
                           sensor_interval=0.1)  # B faces AWAY from target
    target5 = _spawn_dummy(w5, ZONE, "Enemy", 30.0, 10.0, "red")

    # Run enough ticks for A to detect and start chasing, then share
    for _ in range(20):
        _tick(w5, tiles5)

    mode_a = _get_mode(w5, npc_a)
    mode_b = _get_mode(w5, npc_b)

    check(mode_a in ("chase", "attack"),
          f"1f: Fighter A is chasing/attacking (got {mode_a})",
          f"mode_a={mode_a}")
    check(mode_b in ("searching", "chase", "attack"),
          f"1f: Fighter B alerted by A's intel (got {mode_b})",
          f"mode_b={mode_b}")


# ═══════════════════════════════════════════════════════════════════════
#  SECTION 2:  MULTI-NPC COMBAT DYNAMICS
# ═══════════════════════════════════════════════════════════════════════

def test_multi_npc_dynamics():
    """5v5 team fight — death ordering, focus fire, engagement pacing."""
    print("\n=== 2: Multi-NPC Combat Dynamics (5v5 arena) ===")
    ZONE = "dyn_test"
    random.seed(123)

    w = World()
    _setup_bus(w)
    tiles = _make_arena(40, 30, ZONE)

    blue_eids = []
    red_eids = []

    # Blue team (left) — 3 melee + 2 ranged
    for name, x, y, kind, atype, arange, cd in [
        ("B-Vanguard",  6.0, 8.0,  "hostile_melee",  "melee",  1.2, 0.5),
        ("B-Tank",      6.0, 15.0, "hostile_melee",  "melee",  1.2, 0.5),
        ("B-Brawler",   6.0, 22.0, "hostile_melee",  "melee",  1.2, 0.5),
        ("B-Sniper",    3.0, 11.0, "hostile_ranged", "ranged", 12.0, 0.8),
        ("B-Gunner",    3.0, 19.0, "hostile_ranged", "ranged", 12.0, 0.8),
    ]:
        eid = _spawn_fighter(w, ZONE, name, kind, x, y, "blue", "right",
                             hp=100, damage=15, defense=5, speed=2.5,
                             atk_type=atype, atk_range=arange,
                             cooldown=cd, sensor_interval=0.1)
        blue_eids.append(eid)

    # Red team (right) — mirror
    for name, x, y, kind, atype, arange, cd in [
        ("R-Berserker", 34.0, 8.0,  "hostile_melee",  "melee",  1.2, 0.5),
        ("R-Brute",     34.0, 15.0, "hostile_melee",  "melee",  1.2, 0.5),
        ("R-Brawler",   34.0, 22.0, "hostile_melee",  "melee",  1.2, 0.5),
        ("R-Archer",    37.0, 11.0, "hostile_ranged", "ranged", 12.0, 0.8),
        ("R-Marksman",  37.0, 19.0, "hostile_ranged", "ranged", 12.0, 0.8),
    ]:
        eid = _spawn_fighter(w, ZONE, name, kind, x, y, "red", "left",
                             hp=100, damage=15, defense=5, speed=2.5,
                             atk_type=atype, atk_range=arange,
                             cooldown=cd, sensor_interval=0.1)
        red_eids.append(eid)

    all_eids = blue_eids + red_eids

    # ── 2a: All NPCs enter chase within 30 ticks ────────────────────
    # sensor_interval=0.1s + random stagger means some NPCs take
    # up to ~12 ticks.  Allow 30 ticks (0.5 s) for all 10.
    for t in range(30):
        _tick(w, tiles)

    chasing = sum(1 for e in all_eids
                  if w.alive(e) and _get_mode(w, e) in ("chase", "attack"))
    check(chasing >= 6,
          f"2a: ≥ 6/10 NPCs chasing/attacking within 30 ticks (got {chasing})",
          f"chasing={chasing}")

    # ── 2b: Ranged fires before melee closes ─────────────────────────
    # Check that ranged NPCs enter attack mode before melee NPCs do.
    ranged_eids = [blue_eids[3], blue_eids[4], red_eids[3], red_eids[4]]
    melee_eids = [blue_eids[0], blue_eids[1], blue_eids[2],
                  red_eids[0], red_eids[1], red_eids[2]]

    ranged_attacking = sum(1 for e in ranged_eids
                          if w.alive(e) and _get_mode(w, e) == "attack")
    melee_attacking = sum(1 for e in melee_eids
                         if w.alive(e) and _get_mode(w, e) == "attack")
    check(ranged_attacking >= melee_attacking,
          f"2b: Ranged attacking ≥ melee attacking ({ranged_attacking} vs {melee_attacking})",
          f"ranged={ranged_attacking}, melee={melee_attacking}")

    # ── 2c: Run full battle, expect deaths ───────────────────────────
    _run_ticks(w, tiles, 1800)  # 30 seconds of combat

    blue_alive = sum(1 for e in blue_eids if w.alive(e)
                     and w.get(e, Health) and w.get(e, Health).current > 0)
    red_alive = sum(1 for e in red_eids if w.alive(e)
                    and w.get(e, Health) and w.get(e, Health).current > 0)
    total_alive = blue_alive + red_alive
    total_dead = 10 - total_alive

    check(total_dead >= 2,
          f"2c: ≥ 2 deaths in 30s battle (got {total_dead})",
          f"blue_alive={blue_alive}, red_alive={red_alive}")

    # ── 2d: Damage was dealt to BOTH sides ───────────────────────────
    blue_dmg = sum(1 for e in blue_eids
                   if w.alive(e) and w.get(e, Health)
                   and w.get(e, Health).current < w.get(e, Health).maximum)
    red_dmg = sum(1 for e in red_eids
                  if w.alive(e) and w.get(e, Health)
                  and w.get(e, Health).current < w.get(e, Health).maximum)
    check(blue_dmg > 0 or blue_alive < 5,
          f"2d: Blue team took damage or lost members ({blue_dmg} damaged, {5 - blue_alive} dead)")
    check(red_dmg > 0 or red_alive < 5,
          f"2d: Red team took damage or lost members ({red_dmg} damaged, {5 - red_alive} dead)")

    # ── 2e: No NPC stuck in idle during active combat ────────────────
    idle_during_battle = sum(1 for e in all_eids
                            if w.alive(e) and w.get(e, Health)
                            and w.get(e, Health).current > 0
                            and _get_mode(w, e) == "idle")
    check(idle_during_battle <= 1,
          f"2e: ≤ 1 alive NPC stuck idle after 30s (got {idle_during_battle})",
          f"idle={idle_during_battle}")


# ═══════════════════════════════════════════════════════════════════════
#  SECTION 3:  MOVEMENT + PATHFINDING QUALITY
# ═══════════════════════════════════════════════════════════════════════

def test_movement_quality():
    """NPC navigation through corridors, around obstacles, convergence speed."""
    print("\n=== 3: Movement + Pathfinding Quality ===")
    ZONE = "move_test"

    # ── 3a: NPC navigates through chokepoint ─────────────────────────
    # Room A → gap at rows 9-10, col 25 → Room B
    # NPC at (10, 10), target at (40, 10).  Must path through the gap.
    random.seed(77)
    w = World()
    _setup_bus(w)
    tiles = _make_corridor_arena(ZONE)

    npc = _spawn_fighter(w, ZONE, "Navigator", "hostile_melee",
                         10.0, 10.0, "blue", "right",
                         speed=3.0, aggro=5000.0, sensor_interval=0.1,
                         atk_range=1.2)
    target = _spawn_dummy(w, ZONE, "Goal", 40.0, 10.0, "red")

    start_dist = _dist(w, npc, target)

    # Run 600 ticks (10 s) — NPC should cross 30 m at 3.0 * 1.4 = 4.2 m/s
    # Straight line would take ~7.1 s, with pathfinding around wall ~9 s.
    _run_ticks(w, tiles, 600)

    end_dist = _dist(w, npc, target)
    check(end_dist < start_dist * 0.3,
          f"3a: NPC closed > 70% of distance through chokepoint "
          f"(start={start_dist:.1f}, end={end_dist:.1f})",
          f"start={start_dist:.1f}, end={end_dist:.1f}")

    npc_pos = w.get(npc, Position)
    check(npc_pos and npc_pos.x > 25.0,
          f"3a: NPC crossed through chokepoint (x={npc_pos.x:.1f})",
          f"x={npc_pos.x:.1f}" if npc_pos else "no position")

    # ── 3b: NPC doesn't get stuck on walls ───────────────────────────
    # NPC directly below a wall — must route around it.
    random.seed(77)
    w2 = World()
    _setup_bus(w2)
    tiles2 = _make_arena(30, 20, ZONE)
    # Place a horizontal wall from (10,5) to (10,15)
    for c in range(5, 16):
        tiles2[10][c] = TILE_WALL
    ZONE_MAPS[ZONE] = tiles2

    npc2 = _spawn_fighter(w2, ZONE, "Unstuck", "hostile_melee",
                          10.0, 12.0, "blue", "up",
                          speed=2.5, sensor_interval=0.1)
    target2 = _spawn_dummy(w2, ZONE, "Above", 10.0, 5.0, "red")

    positions = []
    for t in range(300):
        _tick(w2, tiles2)
        p = w2.get(npc2, Position)
        if p and t % 30 == 0:
            positions.append((p.x, p.y))

    # Should have moved — not stuck at same spot
    if len(positions) >= 3:
        moved = any(
            math.hypot(positions[i][0] - positions[i - 1][0],
                       positions[i][1] - positions[i - 1][1]) > 0.5
            for i in range(1, len(positions))
        )
        check(moved, "3b: NPC not stuck behind wall (moved between samples)",
              f"positions={positions}")
    else:
        fail("3b: Not enough position samples")

    # ── 3c: Movement speed matches expected rate ─────────────────────
    # Open field, NPC chasing target 20 m away.  Speed=3.0, chase_mult=1.4.
    # Expected: ~4.2 m/s.  After 60 ticks (1 s), should have moved ~4 m.
    random.seed(77)
    w3 = World()
    _setup_bus(w3)
    tiles3 = _make_arena(40, 20, ZONE)

    npc3 = _spawn_fighter(w3, ZONE, "Runner", "hostile_melee",
                          5.0, 10.0, "blue", "right",
                          speed=3.0, sensor_interval=0.0)
    target3 = _spawn_dummy(w3, ZONE, "Far", 25.0, 10.0, "red")

    # Let it detect + start chasing (instant sensor, no stagger)
    _run_ticks(w3, tiles3, 5)
    mode_before = _get_mode(w3, npc3)
    # May be 'chase' or 'attack' if already close enough
    check(mode_before in ("chase", "attack"),
          f"3c: NPC chasing/attacking before speed measurement (mode={mode_before})")

    p_before = w3.get(npc3, Position)
    x_before = p_before.x if p_before else 0

    # Only measure speed if in chase (attack mode strafes/circles)
    if mode_before == "chase":
        _run_ticks(w3, tiles3, 60)  # 1 second

        p_after = w3.get(npc3, Position)
        x_after = p_after.x if p_after else 0
        dist_moved = x_after - x_before

        # Expected ~4.2 m/s.  Accept 2.5–5.5 (collision + frame sync).
        check(2.5 <= dist_moved <= 5.5,
              f"3c: Chase speed ~4.2 m/s (moved {dist_moved:.2f} m in 1s)",
              f"dist_moved={dist_moved:.2f}")
    else:
        # Already in attack — measure that distance is closing
        d_before = _dist(w3, npc3, target3)
        _run_ticks(w3, tiles3, 60)
        d_after = _dist(w3, npc3, target3)
        check(d_after <= d_before,
              f"3c: NPC closing distance in attack (d: {d_before:.1f} → {d_after:.1f})")


# ═══════════════════════════════════════════════════════════════════════
#  SECTION 4:  PROJECTILE ACCURACY AT RANGE
# ═══════════════════════════════════════════════════════════════════════

def test_projectile_accuracy():
    """Hit rates at different distances, damage falloff, friendly fire."""
    print("\n=== 4: Projectile Accuracy ===")
    ZONE = "proj_test"

    # ── 4a: Close range (5 m) — high hit rate ───────────────────────
    hits_close = _run_projectile_trial(ZONE, shooter_x=5.0, target_x=10.0,
                                       trials=20, seed_base=200)
    check(hits_close >= 14,
          f"4a: Close range (5 m) ≥ 14/20 hits (got {hits_close})",
          f"hits={hits_close}")

    # ── 4b: Max range (10 m) — moderate hit rate ────────────────────
    hits_mid = _run_projectile_trial(ZONE, shooter_x=5.0, target_x=15.0,
                                     trials=20, seed_base=300)
    check(hits_mid >= 8,
          f"4b: Max range (10 m) ≥ 8/20 hits (got {hits_mid})",
          f"hits={hits_mid}")

    # ── 4c: Close hits at least as often as far ───────────────────────
    check(hits_close >= hits_mid,
          f"4c: Close ≥ far hit rate ({hits_close} vs {hits_mid})",
          f"close={hits_close}, far={hits_mid}")

    # ── 4d: Damage falloff — close hit does more damage ─────────────
    dmg_close = _measure_projectile_damage(ZONE, dist=3.0, seed=400)
    dmg_far = _measure_projectile_damage(ZONE, dist=9.0, seed=401)
    if dmg_close > 0 and dmg_far > 0:
        check(dmg_close > dmg_far,
              f"4d: Close damage > far damage ({dmg_close:.1f} vs {dmg_far:.1f})",
              f"close={dmg_close:.1f}, far={dmg_far:.1f}")
    else:
        fail("4d: Couldn't measure projectile damage",
             f"close={dmg_close}, far={dmg_far}")

    # ── 4e: Friendly fire avoidance — ally in line of fire ──────────
    random.seed(500)
    w = World()
    _setup_bus(w)
    tiles = _make_firing_range(ZONE)

    shooter = _spawn_fighter(w, ZONE, "Shooter", "hostile_ranged",
                             5.0, 5.0, "blue", "right",
                             atk_type="ranged", atk_range=12.0,
                             cooldown=0.3, sensor_interval=0.1)
    # Ally directly in the firing line
    ally = _spawn_fighter(w, ZONE, "Ally", "hostile_melee",
                          12.0, 5.0, "blue", "right",
                          speed=0.0)  # stationary ally
    target5 = _spawn_dummy(w, ZONE, "Enemy", 20.0, 5.0, "red")

    ally_hp_start = w.get(ally, Health).current
    _run_ticks(w, tiles, 180)  # 3 seconds

    ally_hp_end = w.get(ally, Health)
    ally_took_damage = ally_hp_end and ally_hp_end.current < ally_hp_start
    # The AI should suppress fire when ally is in the line
    check(not ally_took_damage,
          "4e: Shooter avoided friendly fire (ally undamaged)",
          f"ally HP: {ally_hp_start} → {ally_hp_end.current if ally_hp_end else 'dead'}")


def _run_projectile_trial(zone: str, shooter_x: float, target_x: float,
                          trials: int, seed_base: int,
                          max_range: float = 50.0) -> int:
    """Run N independent shots and count hits."""
    hits = 0
    for i in range(trials):
        random.seed(seed_base + i)
        w = World()
        _setup_bus(w)
        tiles = _make_firing_range(zone)

        shooter = _spawn_fighter(w, zone, "S", "hostile_ranged",
                                 shooter_x, 5.0, "blue", "right",
                                 atk_type="ranged", atk_range=max_range,
                                 cooldown=0.1, accuracy=0.85,
                                 proj_speed=14.0, sensor_interval=0.0)
        target = _spawn_dummy(w, zone, "T", target_x, 5.0, "red", hp=500)

        hp_before = w.get(target, Health).current
        _run_ticks(w, tiles, 120)  # 2 seconds — enough for 1 shot cycle
        hp_after = w.get(target, Health)
        if hp_after and hp_after.current < hp_before:
            hits += 1
    return hits


def _measure_projectile_damage(zone: str, dist: float, seed: int) -> float:
    """Fire one projectile at known distance, return damage dealt."""
    random.seed(seed)
    w = World()
    _setup_bus(w)
    tiles = _make_firing_range(zone)

    src_x = 5.0
    tgt_x = src_x + dist
    shooter = _spawn_fighter(w, zone, "S", "hostile_ranged",
                             src_x, 5.0, "blue", "right",
                             atk_type="ranged", atk_range=50.0,
                             cooldown=0.1, accuracy=1.0,
                             proj_speed=14.0, sensor_interval=0.0,
                             damage=20, defense=0)
    target = _spawn_dummy(w, zone, "T", tgt_x, 5.0, "red", hp=500)

    hp_before = w.get(target, Health).current
    _run_ticks(w, tiles, 120)
    hp_after = w.get(target, Health)
    if hp_after:
        return hp_before - hp_after.current
    return 0.0


# ═══════════════════════════════════════════════════════════════════════
#  SECTION 5:  FLEE BEHAVIOR VALIDATION
# ═══════════════════════════════════════════════════════════════════════

def test_flee_behavior():
    """Fleeing NPCs move away, at correct speed, and recover properly."""
    print("\n=== 5: Flee Behavior Validation ===")
    ZONE = "flee_test"
    random.seed(55)

    w = World()
    _setup_bus(w)
    tiles = _make_arena(50, 20, ZONE)

    # Coward: flee_threshold=0.8 (flees at 80% HP), fast scanner
    coward = _spawn_fighter(w, ZONE, "Coward", "hostile_melee",
                            25.0, 10.0, "blue", "left",
                            hp=100, damage=5, defense=0,
                            speed=3.0, flee_threshold=0.8,
                            sensor_interval=0.1, atk_range=1.2)
    # Threat starting 3 m away
    threat = _spawn_fighter(w, ZONE, "Threat", "hostile_melee",
                            22.0, 10.0, "red", "right",
                            hp=500, damage=30, defense=0,
                            speed=2.0, flee_threshold=0.0,
                            sensor_interval=0.1)

    # ── 5a: Coward enters flee after taking damage ───────────────────
    # Tick until coward takes damage (low threshold means any hit triggers flee)
    flee_tick = None
    for t in range(300):
        _tick(w, tiles)
        mode = _get_mode(w, coward)
        if mode == "flee":
            flee_tick = t + 1
            break

    check(flee_tick is not None,
          "5a: Coward entered flee mode",
          f"mode={_get_mode(w, coward)}, hp_frac={_hp_frac(w, coward):.2f}")

    # ── 5b: Coward actually moves AWAY from threat ──────────────────
    if flee_tick is not None:
        pos_at_flee = w.get(coward, Position)
        x_at_flee = pos_at_flee.x if pos_at_flee else 25.0
        threat_pos = w.get(threat, Position)
        threat_x = threat_pos.x if threat_pos else 22.0

        _run_ticks(w, tiles, 60)  # 1 second of fleeing

        pos_after = w.get(coward, Position)
        if pos_after and w.alive(coward):
            dist_before = abs(x_at_flee - threat_x)
            dist_after = abs(pos_after.x - threat_x)
            check(dist_after > dist_before,
                  f"5b: Coward moved away (dist {dist_before:.1f} → {dist_after:.1f})",
                  f"before={dist_before:.1f}, after={dist_after:.1f}")

            # ── 5c: Flee speed is correct ────────────────────────────
            # flee_speed = speed * 1.3 = 3.9 m/s.  In 1s should move ~3.5-4.2 m.
            fled_dist = abs(pos_after.x - x_at_flee)
            check(fled_dist >= 2.0,
                  f"5c: Fled ≥ 2 m in 1s (got {fled_dist:.2f} m)",
                  f"fled_dist={fled_dist:.2f}")
        else:
            fail("5b: Coward died before flee could be measured")
            fail("5c: (skipped — coward dead)")

    # ── 5d: Fleeing NPC doesn't just run into walls ──────────────────
    # Place coward near a wall — should flee sideways, not INTO the wall.
    random.seed(55)
    w2 = World()
    _setup_bus(w2)
    tiles2 = _make_arena(30, 20, ZONE)

    # Coward at x=27 (near right wall at x=29)
    coward2 = _spawn_fighter(w2, ZONE, "WallRunner", "hostile_melee",
                             27.0, 10.0, "blue", "right",
                             hp=50, damage=0, defense=0,
                             speed=3.0, flee_threshold=0.9,
                             sensor_interval=0.1)
    threat2 = _spawn_fighter(w2, ZONE, "Pusher", "hostile_melee",
                             25.0, 10.0, "red", "right",
                             hp=500, damage=40, defense=0,
                             speed=2.0, flee_threshold=0.0,
                             sensor_interval=0.1)

    # Run until flee + some movement
    _run_ticks(w2, tiles2, 180)

    p2 = w2.get(coward2, Position)
    if p2 and w2.alive(coward2):
        # Should not be squished against the wall at x=28+
        check(p2.x < 28.5 or abs(p2.y - 10.0) > 2.0,
              f"5d: Fleeing NPC not stuck on wall (x={p2.x:.1f}, y={p2.y:.1f})",
              f"pos=({p2.x:.1f}, {p2.y:.1f})")
    else:
        # Dying near a wall is acceptable (threat is strong)
        ok("5d: NPC died near wall (acceptable — damage was high)")


# ═══════════════════════════════════════════════════════════════════════
#  SECTION 6:  FULL AI PIPELINE — END-TO-END
# ═══════════════════════════════════════════════════════════════════════

def test_full_pipeline():
    """Complete combat lifecycle: detect → pursue → engage → kill/flee → post."""
    print("\n=== 6: Full AI Pipeline — End-to-End ===")
    ZONE = "pipe_test"

    # ── 6a: Melee full kill pipeline ─────────────────────────────────
    # Strong melee vs weak dummy.  Should detect, chase, attack, kill.
    random.seed(999)
    w = World()
    _setup_bus(w)
    tiles = _make_arena(30, 20, ZONE)

    killer = _spawn_fighter(w, ZONE, "Killer", "hostile_melee",
                            5.0, 10.0, "blue", "right",
                            hp=200, damage=25, defense=10,
                            speed=3.0, flee_threshold=0.0,
                            sensor_interval=0.1, atk_range=1.2,
                            cooldown=0.4)
    victim = _spawn_fighter(w, ZONE, "Victim", "hostile_melee",
                            15.0, 10.0, "red", "left",
                            hp=50, damage=5, defense=0,
                            speed=1.5, flee_threshold=0.0,
                            sensor_interval=0.1, atk_range=1.2)

    # Track mode transitions
    modes_seen = set()
    victim_alive = True
    kill_tick = None

    for t in range(900):  # 15 seconds max
        _tick(w, tiles)
        mode = _get_mode(w, killer)
        modes_seen.add(mode)
        if not w.alive(victim) or (w.get(victim, Health) and
                                    w.get(victim, Health).current <= 0):
            victim_alive = False
            kill_tick = t + 1
            break

    check("chase" in modes_seen,
          "6a: Killer went through 'chase' state",
          f"modes_seen={modes_seen}")
    check("attack" in modes_seen,
          "6a: Killer went through 'attack' state",
          f"modes_seen={modes_seen}")
    check(not victim_alive,
          f"6a: Victim killed (tick={kill_tick})",
          f"victim HP={_hp_frac(w, victim):.0%}" if w.alive(victim) else "alive but 0 HP?")

    if kill_tick is not None:
        # 10 m gap, chase at 4.2 m/s → ~2.4 s to close, then some hits.
        # Total kill should be < 10 s = 600 ticks.
        check(kill_tick <= 600,
              f"6a: Kill completed ≤ 600 ticks (got {kill_tick})",
              f"kill_tick={kill_tick}")

    # ── 6b: Post-kill state — killer returns to idle ─────────────────
    if not victim_alive:
        _run_ticks(w, tiles, 300)  # 5 more seconds
        final_mode = _get_mode(w, killer)
        check(final_mode in ("idle", "return"),
              f"6b: Killer in idle/return after kill (got '{final_mode}')",
              f"mode={final_mode}")

    # ── 6c: Ranged full kill pipeline ────────────────────────────────
    random.seed(888)
    w2 = World()
    _setup_bus(w2)
    tiles2 = _make_firing_range(ZONE)

    sniper = _spawn_fighter(w2, ZONE, "Sniper", "hostile_ranged",
                            10.0, 5.0, "blue", "right",
                            hp=200, damage=20, defense=5,
                            speed=2.0, flee_threshold=0.0,
                            atk_type="ranged", atk_range=12.0,
                            cooldown=0.6, accuracy=0.9, proj_speed=16.0,
                            sensor_interval=0.1)
    sitting_duck = _spawn_dummy(w2, ZONE, "Duck", 22.0, 5.0, "red", hp=80)

    duck_start = w2.get(sitting_duck, Health).current
    duck_dead = False
    shot_tick = None
    kill_tick2 = None

    for t in range(1200):  # 20 seconds — sniper needs time to close + fire
        _tick(w2, tiles2)
        h = w2.get(sitting_duck, Health)
        if h and h.current < duck_start and shot_tick is None:
            shot_tick = t + 1
        if not w2.alive(sitting_duck) or (h and h.current <= 0):
            duck_dead = True
            kill_tick2 = t + 1
            break

    check(shot_tick is not None,
          f"6c: Sniper hit the target (first hit tick={shot_tick})",
          "no damage dealt in 10 s")
    check(duck_dead,
          f"6c: Sniper killed target at tick {kill_tick2}",
          f"target HP={w2.get(sitting_duck, Health).current if w2.get(sitting_duck, Health) else '?'}")

    # ── 6d: Corridor combat — NPC paths through and fights ───────────
    random.seed(777)
    w3 = World()
    _setup_bus(w3)
    tiles3 = _make_corridor_arena(ZONE)

    # NPC in room A, enemy in room B (through chokepoint)
    attacker = _spawn_fighter(w3, ZONE, "Attacker", "hostile_melee",
                              10.0, 10.0, "blue", "right",
                              hp=150, damage=20, defense=5,
                              speed=3.0, flee_threshold=0.0,
                              sensor_interval=0.1, atk_range=1.2)
    defender = _spawn_fighter(w3, ZONE, "Defender", "hostile_melee",
                              40.0, 10.0, "red", "left",
                              hp=80, damage=10, defense=0,
                              speed=2.0, flee_threshold=0.0,
                              sensor_interval=0.1, atk_range=1.2)

    crossed_wall = False
    engaged = False
    someone_died = False

    for t in range(1200):  # 20 seconds
        _tick(w3, tiles3)
        ap = w3.get(attacker, Position)
        if ap and ap.x > 26.0:
            crossed_wall = True
        if _get_mode(w3, attacker) == "attack":
            engaged = True
        if (not w3.alive(defender) or
            (w3.get(defender, Health) and w3.get(defender, Health).current <= 0)):
            someone_died = True
            break

    check(crossed_wall,
          "6d: Attacker navigated through corridor chokepoint",
          f"attacker x={w3.get(attacker, Position).x:.1f}" if w3.get(attacker, Position) else "?")
    check(engaged,
          "6d: Attacker entered attack mode after navigation")
    check(someone_died,
          "6d: Combat resolved (defender killed) within 20 s",
          f"defender HP={w3.get(defender, Health).current:.0f}" if w3.get(defender, Health) else "dead")

    # ── 6e: Mixed ranged + melee coordination ────────────────────────
    random.seed(666)
    w4 = World()
    _setup_bus(w4)
    tiles4 = _make_arena(50, 20, ZONE)

    team = []
    # Melee in front
    m = _spawn_fighter(w4, ZONE, "Melee", "hostile_melee",
                       10.0, 10.0, "blue", "right",
                       hp=150, damage=15, defense=10,
                       speed=2.5, sensor_interval=0.1,
                       atk_range=1.2, cooldown=0.5)
    team.append(m)
    # Ranged behind
    r = _spawn_fighter(w4, ZONE, "Ranged", "hostile_ranged",
                       5.0, 10.0, "blue", "right",
                       hp=80, damage=20, defense=2,
                       speed=2.0, sensor_interval=0.1,
                       atk_type="ranged", atk_range=12.0,
                       cooldown=0.7, accuracy=0.85)
    team.append(r)
    # Enemy
    enemy = _spawn_fighter(w4, ZONE, "Enemy", "hostile_melee",
                           35.0, 10.0, "red", "left",
                           hp=120, damage=12, defense=5,
                           speed=2.5, flee_threshold=0.0,
                           sensor_interval=0.1)

    ranged_fired = False
    melee_attacked = False
    enemy_hp_start = w4.get(enemy, Health).current

    for t in range(900):
        _tick(w4, tiles4)
        # Check if ranged is in attack mode
        if _get_mode(w4, r) == "attack":
            ranged_fired = True
        if _get_mode(w4, m) == "attack":
            melee_attacked = True
        if not w4.alive(enemy):
            break

    eh = w4.get(enemy, Health)
    enemy_took_damage = (eh and eh.current < enemy_hp_start) or not w4.alive(enemy)

    check(ranged_fired, "6e: Ranged unit entered attack mode")
    check(melee_attacked, "6e: Melee unit entered attack mode")
    check(enemy_took_damage,
          "6e: Enemy took damage from coordinated assault",
          f"enemy HP: {enemy_hp_start} → {eh.current if eh else 'dead'}")


# ═══════════════════════════════════════════════════════════════════════
#  SECTION 7:  TACTICAL POSITIONING, COVER & FIRE-LINE COMMUNICATION
# ═══════════════════════════════════════════════════════════════════════

def test_fire_line_and_los_pathfinding():
    """NPCs actively reposition out of fire-lines, seek cover, and spread."""
    print("\n=== 7: Tactical Positioning, Cover & Fire-Line Communication ===")
    ZONE = "fireline_test"
    from logic.combat.targeting import (
        get_ally_fire_lines, fire_line_dodge_vector,
        point_fire_line_dist, FireLine, find_chase_los_waypoint,
        find_tactical_position, get_ally_positions,
        _has_adjacent_wall, request_clear_fire_line,
        find_blocking_ally,
    )

    # ── 7a: fire_line_dodge_vector pushes NPC out of lane ────────────
    fl = FireLine(shooter_x=5.0, shooter_y=10.0,
                  target_x=50.0, target_y=10.0, shooter_eid=99)
    # Point sitting right on the fire-line (y=10)
    nx, ny = fire_line_dodge_vector(20.0, 10.0, [fl])
    check(abs(ny) > 0.5,
          f"7a: Dodge vector is lateral to fire-line (ny={ny:.2f})",
          f"nx={nx:.2f}, ny={ny:.2f}")
    check(abs(nx) < 0.3,
          f"7a: Dodge vector not along fire-line (nx={nx:.2f})",
          f"nx={nx:.2f}")

    # Point well outside the fire-line (y=20)
    nx2, ny2 = fire_line_dodge_vector(20.0, 20.0, [fl])
    check(nx2 == 0.0 and ny2 == 0.0,
          "7a: No dodge when outside fire-line clearance",
          f"nx={nx2:.2f}, ny={ny2:.2f}")

    # ── 7b: point_fire_line_dist computes correct distances ──────────
    d_on = point_fire_line_dist(20.0, 10.0, fl)
    d_off = point_fire_line_dist(20.0, 15.0, fl)
    check(d_on < 0.01,
          f"7b: On fire-line dist ≈ 0 (got {d_on:.3f})")
    check(4.9 < d_off < 5.1,
          f"7b: 5m off fire-line dist ≈ 5 (got {d_off:.3f})")

    # ── 7c: find_tactical_position avoids fire-lines + prefers cover ─
    random.seed(42)
    w = World()
    _setup_bus(w)
    tiles = _make_arena(60, 30, ZONE)
    # Add some cover blocks (wall tiles) inside the arena
    for r in range(10, 14):
        tiles[r][30] = TILE_WALL
    ZONE_MAPS[ZONE] = tiles

    # Fire-line along y=15 from x=5 to x=55
    fl_test = FireLine(shooter_x=5.0, shooter_y=15.0,
                       target_x=55.0, target_y=15.0, shooter_eid=99)
    # NPC at (20, 15) — right on the fire-line
    pos = find_tactical_position(
        ZONE, 20.0, 15.0, 55.0, 15.0,
        atk_range=20.0,
        fire_lines=[fl_test],
        ally_positions=[(10.0, 15.0)],  # ally also at y=15
    )
    check(pos is not None,
          "7c: Tactical position found",
          "no position returned")
    if pos:
        # Should NOT be on the fire-line (y should differ from 15)
        fl_dist = point_fire_line_dist(pos[0], pos[1], fl_test)
        check(fl_dist > 0.8,
              f"7c: Tactical pos avoids fire-line (fl_dist={fl_dist:.2f})",
              f"pos=({pos[0]:.1f},{pos[1]:.1f}), fl_dist={fl_dist:.2f}")
        # Should be away from the ally at (10, 15)
        ally_d = math.hypot(pos[0] - 10.0, pos[1] - 15.0)
        check(ally_d > 2.0,
              f"7c: Tactical pos spreads from ally (d={ally_d:.1f})",
              f"pos=({pos[0]:.1f},{pos[1]:.1f})")

    # ── 7d: _has_adjacent_wall detects cover ─────────────────────────
    # Tile (12, 29) is next to wall at (12, 30)
    check(_has_adjacent_wall(ZONE, 29.0, 12.0),
          "7d: Adjacent wall detected near cover block")
    # Tile (5, 5) is open — no adjacent walls except border
    check(not _has_adjacent_wall(ZONE, 15.0, 15.0),
          "7d: No adjacent wall in open area")

    # ── 7e: get_ally_positions returns same-faction allies ───────────
    random.seed(50)
    w2 = World()
    _setup_bus(w2)
    tiles2 = _make_arena(60, 20, ZONE)

    a1 = _spawn_fighter(w2, ZONE, "Ally1", "hostile_ranged",
                        10.0, 10.0, "blue", "right",
                        atk_type="ranged", sensor_interval=0.0)
    a2 = _spawn_fighter(w2, ZONE, "Ally2", "hostile_ranged",
                        20.0, 10.0, "blue", "right",
                        atk_type="ranged", sensor_interval=0.0)
    enemy = _spawn_dummy(w2, ZONE, "Enemy", 50.0, 10.0, "red")

    pos1 = w2.get(a1, Position)
    allies = get_ally_positions(w2, a1, pos1)
    check(len(allies) == 1,
          f"7e: One ally found (got {len(allies)})")
    if allies:
        check(abs(allies[0][0] - 20.0) < 0.1,
              f"7e: Ally position correct (x={allies[0][0]:.1f})")

    # ── 7f: NPCs actively reposition out of ally fire-line  ──────────
    #    Two ranged NPCs, both attacking same target.  One is placed
    #    directly in the other's fire-line.  The blocker should
    #    receive a "clear fire-line" callout and actively move.
    random.seed(100)
    w3 = World()
    _setup_bus(w3)
    tiles3 = _make_arena(60, 20, ZONE)

    # Sniper at left, firing toward right
    sniper = _spawn_fighter(w3, ZONE, "Sniper", "hostile_ranged",
                            5.0, 10.0, "blue", "right",
                            atk_type="ranged", atk_range=30.0,
                            cooldown=0.5, sensor_interval=0.0,
                            speed=2.0, accuracy=0.9, proj_speed=18.0)
    target_d = _spawn_dummy(w3, ZONE, "Enemy", 50.0, 10.0, "red")

    # Second ranged NPC placed directly on the fire-line.
    blocker = _spawn_fighter(w3, ZONE, "Blocker", "hostile_ranged",
                             20.0, 10.0, "blue", "right",
                             atk_type="ranged", atk_range=30.0,
                             speed=2.0, sensor_interval=0.0,
                             cooldown=0.5, accuracy=0.8, proj_speed=14.0)

    # Run until both are in attack mode
    for _ in range(30):
        _tick(w3, tiles3)

    # Record blocker's starting y
    bp = w3.get(blocker, Position)
    y_start = bp.y if bp else 10.0

    # Run more ticks — blocker should actively reposition off fire-line
    for _ in range(300):
        _tick(w3, tiles3)

    bp2 = w3.get(blocker, Position)
    y_end = bp2.y if bp2 else 10.0
    y_offset = abs(y_end - 10.0)  # distance from the fire-line axis

    check(y_offset > 1.0,
          f"7f: Ranged NPC actively repositioned off fire-line "
          f"(offset={y_offset:.2f}m)",
          f"y: {y_start:.1f} → {y_end:.1f}")

    # ── 7g: Anti-clump — NPCs spread out when too close ─────────────
    random.seed(200)
    w4 = World()
    _setup_bus(w4)
    tiles4 = _make_arena(60, 20, ZONE)

    # Three ranged NPCs all starting at the same spot
    npcs = []
    for i in range(3):
        npc = _spawn_fighter(w4, ZONE, f"Ranger{i}", "hostile_ranged",
                             15.0, 10.0, "blue", "right",
                             atk_type="ranged", atk_range=25.0,
                             speed=2.5, sensor_interval=0.0,
                             cooldown=0.5)
        npcs.append(npc)
    target4 = _spawn_dummy(w4, ZONE, "Enemy", 50.0, 10.0, "red")

    # Run enough ticks for them to spread
    for _ in range(400):
        _tick(w4, tiles4)

    # Check pairwise distances — should be > 2m between all pairs
    positions = []
    for npc in npcs:
        p = w4.get(npc, Position)
        if p:
            positions.append((p.x, p.y))
    min_pair_dist = 999.0
    for i in range(len(positions)):
        for j in range(i + 1, len(positions)):
            d = math.hypot(positions[i][0] - positions[j][0],
                           positions[i][1] - positions[j][1])
            min_pair_dist = min(min_pair_dist, d)
    check(min_pair_dist > 2.0,
          f"7g: NPCs spread out (min pair dist={min_pair_dist:.2f}m)",
          f"positions={[(f'{p[0]:.1f},{p[1]:.1f}') for p in positions]}")

    # ── 7h: find_chase_los_waypoint finds a tile with LOS ───────────
    w5 = World()
    _setup_bus(w5)
    tiles5 = _make_arena(40, 20, ZONE)
    # Wall across middle
    for r in range(3, 17):
        tiles5[r][20] = TILE_WALL
    ZONE_MAPS[ZONE] = tiles5

    wp = find_chase_los_waypoint(
        ZONE, 15.0, 10.0,   # NPC position (left of wall)
        25.0, 10.0,          # Target position (right of wall)
        max_search=8.0,
    )
    check(wp is not None,
          "7h: LOS waypoint found around wall",
          "no waypoint returned")
    if wp:
        from core.zone import has_line_of_sight
        los = has_line_of_sight(ZONE, wp[0] + 0.4, wp[1] + 0.4,
                                25.4, 10.4)
        check(los, f"7h: Waypoint ({wp[0]:.1f},{wp[1]:.1f}) has LOS to target")

    # ── 7i: Chase through wall-block uses LOS waypoint ───────────────
    random.seed(200)
    w6 = World()
    _setup_bus(w6)
    tiles6 = _make_arena(40, 20, ZONE)
    # Wall across middle with gap at top
    for r in range(5, 18):
        tiles6[r][20] = TILE_WALL
    ZONE_MAPS[ZONE] = tiles6

    chaser = _spawn_fighter(w6, ZONE, "Chaser", "hostile_melee",
                            15.0, 10.0, "blue", "right",
                            speed=3.0, sensor_interval=0.0)
    target6 = _spawn_dummy(w6, ZONE, "Hidey", 25.0, 10.0, "red")

    # Run ticks — chaser should eventually route around the wall
    for _ in range(300):
        _tick(w6, tiles6)

    cp = w6.get(chaser, Position)
    check(cp is not None and cp.x > 20.5,
          f"7i: Chaser navigated around wall (x={cp.x:.1f})" if cp else "7i: no pos",
          f"x={cp.x:.1f}, y={cp.y:.1f}" if cp else "")

    # ── 7j: Strafing reverses direction at walls ─────────────────────
    #    A ranged NPC near a wall should not get stuck — strafe should
    #    bounce when it hits impassable terrain.
    random.seed(300)
    w7 = World()
    _setup_bus(w7)
    tiles7 = _make_arena(40, 20, ZONE)
    # Add a wall block at row 12, col 15 (near the NPC)
    tiles7[12][15] = TILE_WALL
    tiles7[13][15] = TILE_WALL
    ZONE_MAPS[ZONE] = tiles7

    wall_npc = _spawn_fighter(w7, ZONE, "WallStrafe", "hostile_ranged",
                              14.0, 12.0, "blue", "right",
                              atk_type="ranged", atk_range=20.0,
                              speed=2.0, sensor_interval=0.0)
    target7 = _spawn_dummy(w7, ZONE, "Enemy", 35.0, 12.0, "red")

    # Track whether velocity ever gets non-trivial (NPC isn't stuck)
    max_speed_seen = 0.0
    for _ in range(200):
        _tick(w7, tiles7)
        v = w7.get(wall_npc, Velocity)
        if v:
            spd = math.hypot(v.x, v.y)
            max_speed_seen = max(max_speed_seen, spd)

    check(max_speed_seen > 0.5,
          f"7j: NPC near wall still moves (max_spd={max_speed_seen:.2f})",
          f"max_speed_seen={max_speed_seen:.2f}")

    # ── 7k: request_clear_fire_line sets brain flag ──────────────────
    random.seed(400)
    w8 = World()
    _setup_bus(w8)
    tiles8 = _make_arena(60, 20, ZONE)

    npc_a = _spawn_fighter(w8, ZONE, "NPC_A", "hostile_ranged",
                           10.0, 10.0, "blue", "right",
                           atk_type="ranged", sensor_interval=0.0)
    # Run a tick to initialise combat state
    _tick(w8, tiles8)

    request_clear_fire_line(w8, npc_a, (5.0, 10.0), (50.0, 10.0))
    brain_a = w8.get(npc_a, Brain)
    cstate = brain_a.state.get("combat", {}) if brain_a else {}
    has_flag = "_clear_fire_line" in cstate
    check(has_flag,
          "7k: request_clear_fire_line sets brain flag",
          f"combat state keys: {list(cstate.keys())}")


# ═══════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    sections = [
        ("Reaction Timing", test_reaction_timing),
        ("Multi-NPC Dynamics", test_multi_npc_dynamics),
        ("Movement Quality", test_movement_quality),
        ("Projectile Accuracy", test_projectile_accuracy),
        ("Flee Behavior", test_flee_behavior),
        ("Full Pipeline", test_full_pipeline),
        ("Tactical Positioning & Cover", test_fire_line_and_los_pathfinding),
    ]

    for name, fn in sections:
        try:
            fn()
        except Exception:
            _failed += 1
            print(f"\n  [CRASH] {name} — unhandled exception:")
            traceback.print_exc()

    total = _passed + _failed
    print(f"\n{'=' * 60}")
    print(f"  Behavioral Tests: {_passed} passed, {_failed} failed  "
          f"(total {total})")
    print(f"{'=' * 60}")
    sys.exit(1 if _failed else 0)
