"""logic/combat_engagement.py — Combat AI orchestrator.

Thin coordinator that wires together:

  - ``combat_sensing``  — target acquisition, LOS checks
  - ``combat_movement`` — velocity-producing behaviours
  - ``combat`` (module)  — attack execution / damage

The FSM (idle -> chase -> attack -> flee -> return) lives entirely in
``_update_fsm`` — a short, readable block of pure transitions.
Movement and sensing are delegated completely, so every concern is
independently testable and debuggable.
"""

from __future__ import annotations
import random
import math

from core.ecs import World
from components import (
    Brain, Patrol, Threat, AttackConfig,
    Position, Velocity, Facing,
)
from components import Faction, Health, Identity
from components.dev_log import DevLog
from logic.brains import register_brain
from logic.brains._helpers import (
    hp_ratio, face_toward, should_engage, try_dodge, try_heal,
    reset_faction_on_return,
)
from logic import combat_sensing as sense
from logic import combat_movement as move
from core.tuning import get as _tun
from core.events import EventBus, AttackIntent


# ── Utilities ────────────────────────────────────────────────────────

def _update_facing_from_vel(world: World, eid: int, vel):
    """Set Facing to match current velocity."""
    if abs(vel.x) < 0.01 and abs(vel.y) < 0.01:
        return
    facing = world.get(eid, Facing)
    if facing is None:
        return
    if abs(vel.x) >= abs(vel.y):
        facing.direction = "right" if vel.x > 0 else "left"
    else:
        facing.direction = "down" if vel.y > 0 else "up"


def _log(world: World, eid: int, cat: str, msg: str, t: float = 0.0, **kw):
    log = world.res(DevLog)
    if log is None:
        return
    ident = world.get(eid, Identity)
    name = ident.name if ident else f"e{eid}"
    log.record(eid, cat, msg, name=name, t=t, **kw)


# ── Main entry point ────────────────────────────────────────────────

def _combat_brain(world: World, eid: int, brain: Brain, dt: float,
                  game_time: float = 0.0):
    """Unified combat FSM: idle -> chase -> attack -> flee -> return."""
    pos = world.get(eid, Position)
    vel = world.get(eid, Velocity)
    if not pos or not vel:
        return

    patrol = world.get(eid, Patrol)
    threat = world.get(eid, Threat)
    atk_cfg = world.get(eid, AttackConfig)
    if not threat or not atk_cfg:
        return

    s = brain.state
    c = s.setdefault("combat", {})
    if "origin" not in c:
        c["origin"] = (pos.x, pos.y)
    c.setdefault("mode", "idle")

    # Stagger sensor timing so groups don't all tick on the same frame
    if not c.get("_staggered"):
        c["_staggered"] = True
        threat.last_sensor_time = game_time - random.uniform(
            0.0, threat.sensor_interval)

    is_ranged = atk_cfg.attack_type == "ranged"

    # ── 1. SENSE (throttled) ─────────────────────────────────────
    sensor_due = (game_time - threat.last_sensor_time) >= threat.sensor_interval
    skip_movement = False
    if sensor_due:
        threat.last_sensor_time = game_time
        skip_movement = _run_sensor_tick(
            world, eid, brain, pos, vel, patrol, threat, atk_cfg,
            c, is_ranged, dt, game_time,
        )

    # ── 2. MOVE (every frame, unless dodge overrode velocity) ────
    if not skip_movement:
        _run_movement(world, eid, pos, vel, patrol, atk_cfg,
                      c, is_ranged, dt, game_time)


# ── Sensor tick ──────────────────────────────────────────────────────

def _run_sensor_tick(world, eid, brain, pos, vel, patrol, threat, atk_cfg,
                     c, is_ranged, dt, game_time) -> bool:
    """Acquire target, update FSM, attempt attacks.

    Returns True if movement should be skipped this frame (dodge).
    """
    # Faction gate — not hostile? Just idle.
    if not should_engage(world, eid):
        c["mode"] = "idle"
        return False

    # ── Target acquisition ───────────────────────────────────────
    target = sense.acquire_target(world, eid, pos, threat.aggro_radius)
    if target.eid is None:
        c["p_eid"] = None
        c["p_pos"] = None
        if c["mode"] != "idle":
            _log(world, eid, "combat", "target lost → idle", game_time)
        c["mode"] = "idle"
        return False

    c["p_eid"] = target.eid
    c["p_pos"] = (target.x, target.y)

    # ── Defensive reactions ──────────────────────────────────────
    if c["mode"] in ("chase", "attack"):
        if try_dodge(world, eid, brain, pos, vel, c, dt, game_time):
            return True           # dodge set velocity — skip movement
        try_heal(world, eid, brain, c, game_time)

    # ── FSM transitions ──────────────────────────────────────────
    _update_fsm(world, eid, pos, threat, atk_cfg, c, target,
                is_ranged, game_time)

    # ── Attack execution ─────────────────────────────────────────
    if c["mode"] == "attack":
        _try_attack(world, eid, pos, atk_cfg, c, target,
                    is_ranged, game_time)

    return False


# ── FSM transitions ─────────────────────────────────────────────────

def _update_fsm(world, eid, pos, threat, atk_cfg, c, target,
                is_ranged, game_time):
    """Pure state transitions — reads sensor data, mutates ``c['mode']``."""
    mode = c["mode"]
    dist = target.dist
    ox, oy = c.get("origin", (pos.x, pos.y))
    home_dist = math.hypot(pos.x - ox, pos.y - oy)
    cur_hp = hp_ratio(world, eid)
    can_flee = threat.flee_threshold > 0.0

    if mode == "idle":
        if sense.is_detected_idle(world, eid, pos, target.x, target.y,
                                  dist, threat.aggro_radius):
            c["mode"] = "chase"
            _log(world, eid, "combat",
                 f"idle → chase (dist={dist:.1f})", game_time)

    elif mode == "chase":
        if can_flee and cur_hp <= threat.flee_threshold:
            c["mode"] = "flee"
            _log(world, eid, "combat",
                 f"chase → flee (hp={cur_hp:.0%})", game_time)
        elif home_dist > threat.leash_radius:
            c["mode"] = "return"
            _log(world, eid, "combat",
                 f"chase → return (leash={home_dist:.1f})", game_time)
        elif is_ranged and dist <= atk_cfg.range * _tun(
                "combat.engagement", "ranged_chase_to_attack", 1.1):
            if target.wall_los:
                c["mode"] = "attack"
                if c.get("attack_until", 0.0) < 1.0:
                    c["attack_until"] = game_time + random.uniform(
                        0.1, atk_cfg.cooldown * 0.8)
                _log(world, eid, "combat",
                     f"chase → attack (ranged, dist={dist:.1f})", game_time)
        elif not is_ranged and dist <= atk_cfg.range:
            c["mode"] = "attack"
            c["melee_sub"] = "approach"
            if c.get("attack_until", 0.0) < 1.0:
                c["attack_until"] = game_time + random.uniform(
                    0.0, atk_cfg.cooldown * 0.5)
            _log(world, eid, "combat",
                 f"chase → attack (melee, dist={dist:.1f})", game_time)

    elif mode == "attack":
        if can_flee and cur_hp <= threat.flee_threshold:
            c["mode"] = "flee"
            _log(world, eid, "combat",
                 f"attack → flee (hp={cur_hp:.0%})", game_time)
        elif dist > threat.leash_radius:
            c["mode"] = "return"
            _log(world, eid, "combat",
                 f"attack → return (dist={dist:.1f})", game_time)
        elif is_ranged and dist > atk_cfg.range * _tun(
                "combat.engagement", "ranged_attack_to_chase", 1.8):
            c["mode"] = "chase"
            _log(world, eid, "combat",
                 "attack → chase (too far)", game_time)
        elif not is_ranged and dist > atk_cfg.range * _tun(
                "combat.engagement", "melee_attack_to_chase", 1.6):
            c["mode"] = "chase"
            _log(world, eid, "combat",
                 "attack → chase (melee lost range)", game_time)

    elif mode == "flee":
        if cur_hp > threat.flee_threshold * _tun(
                "combat.engagement", "flee_recovery_mult", 2.5
        ) or dist > threat.aggro_radius:
            c["mode"] = "return"
            _log(world, eid, "combat", "flee → return", game_time)

    elif mode == "return":
        if math.hypot(pos.x - ox, pos.y - oy) < _tun(
                "combat.engagement", "return_arrive_dist", 1.0):
            c["mode"] = "idle"
            reset_faction_on_return(world, eid)
            _log(world, eid, "combat", "returned home → idle", game_time)
        elif dist <= threat.aggro_radius * _tun(
                "combat.engagement", "return_reaggro_factor", 0.6):
            c["mode"] = "chase"
            _log(world, eid, "combat",
                 "return interrupted → chase", game_time)


# ── Attack execution ─────────────────────────────────────────────────

def _try_attack(world, eid, pos, atk_cfg, c, target, is_ranged, game_time):
    """Attempt to fire/strike if cooldown is ready."""
    if c.get("attack_until", 0.0) > game_time or target.eid is None:
        return

    if is_ranged:
        if not target.wall_los:
            c["_wall_blocked"] = True
            _log(world, eid, "combat", "LOS blocked by wall", game_time)
            return

        if target.ally_in_fire:
            c["_los_blocked"] = True
            blocked = c.get("_los_blocked_count", 0) + 1
            c["_los_blocked_count"] = blocked
            patience = int(_tun("combat.engagement",
                                "los_blocked_patience", 3))
            if blocked < patience:
                _log(world, eid, "combat",
                     f"ally in fire ({blocked}/{patience})", game_time)
                return
            c["_los_blocked_count"] = 0
            _log(world, eid, "attack",
                 "fired (forced, LOS patience)", game_time)
        else:
            c["_los_blocked"] = False
            c["_los_blocked_count"] = 0
            c["_wall_blocked"] = False
            _log(world, eid, "attack", "fired ranged attack", game_time)

        _emit_attack(world, eid, target.eid, "ranged")
        c["attack_until"] = game_time + atk_cfg.cooldown
    else:
        _emit_attack(world, eid, target.eid, "melee")
        c["attack_until"] = game_time + atk_cfg.cooldown
        c["_melee_just_hit"] = True
        _log(world, eid, "attack", "melee strike", game_time)


def _emit_attack(world, attacker_eid, target_eid, attack_type):
    """Emit via EventBus if available, else direct call."""
    bus = world.res(EventBus)
    if bus:
        bus.emit(AttackIntent(attacker_eid=attacker_eid,
                              target_eid=target_eid,
                              attack_type=attack_type))
    else:
        from logic.combat import npc_ranged_attack, npc_melee_attack
        if attack_type == "ranged":
            npc_ranged_attack(world, attacker_eid, target_eid)
        else:
            npc_melee_attack(world, attacker_eid, target_eid)


# ── Per-frame movement ───────────────────────────────────────────────

def _run_movement(world, eid, pos, vel, patrol, atk_cfg,
                  c, is_ranged, dt, game_time):
    """Delegates to ``combat_movement`` based on current FSM mode."""
    mode = c["mode"]
    p_cache = c.get("p_pos")
    ox, oy = c.get("origin", (pos.x, pos.y))
    p_speed = (patrol.speed if patrol
               else _tun("combat.engagement", "fallback_patrol_speed", 2.0))

    if mode == "idle":
        move.idle(patrol, pos, vel, c, dt)
        _update_facing_from_vel(world, eid, vel)

    elif mode == "chase" and p_cache:
        chase_mult = (_tun("combat.engagement", "chase_mult_ranged", 1.2)
                      if is_ranged
                      else _tun("combat.engagement", "chase_mult_melee", 1.4))
        move.chase(pos, vel, p_cache[0], p_cache[1],
                   p_speed * chase_mult, c, game_time)
        face_toward(world, eid,
                    type("P", (), {"x": p_cache[0], "y": p_cache[1]})())

    elif mode == "attack" and p_cache:
        px, py = p_cache
        face_toward(world, eid, type("P", (), {"x": px, "y": py})())
        dist = math.hypot(pos.x - px, pos.y - py)
        if is_ranged:
            move.ranged_attack(
                pos, vel, px, py, dist, atk_cfg.range, p_speed,
                c, dt,
                wall_blocked=c.get("_wall_blocked", False),
                los_blocked=c.get("_los_blocked", False),
                game_time=game_time,
            )
        else:
            move.melee_attack(pos, vel, px, py, dist,
                              atk_cfg.range, p_speed, c, dt)

    elif mode == "flee" and p_cache:
        move.flee(pos, vel, p_cache[0], p_cache[1],
                  p_speed * _tun("combat.engagement",
                                 "flee_speed_mult", 1.3))

    elif mode == "return":
        ret_mult = (_tun("combat.engagement",
                         "return_speed_mult_melee", 1.5)
                    if not is_ranged else 1.0)
        move.return_home(pos, vel, ox, oy, p_speed * ret_mult,
                         c, game_time)

    else:
        move.idle(patrol, pos, vel, c, dt)


# ── Public API & registration ────────────────────────────────────────

def run_combat_brain(world: World, eid: int, brain: Brain, dt: float,
                     game_time: float = 0.0) -> None:
    _combat_brain(world, eid, brain, dt, game_time)


# Register under all three brain kinds so existing entities work unchanged
register_brain("hostile_melee", _combat_brain)
register_brain("hostile_ranged", _combat_brain)
register_brain("guard", _combat_brain)
