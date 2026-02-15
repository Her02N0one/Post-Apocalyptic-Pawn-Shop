"""logic/combat/engagement.py — Combat AI orchestrator.

Thin coordinator that wires together:

  - ``combat_sensing``  — target acquisition, LOS checks
  - ``combat_movement`` — velocity-producing behaviours
  - ``combat`` (module)  — attack execution / damage

The FSM (idle -> searching -> chase -> attack -> flee -> return) lives
entirely in ``_update_fsm`` — a short, readable block of pure
transitions.  Movement and sensing are delegated completely, so every
concern is independently testable and debuggable.

The **searching** state bridges hearing and vision: when an NPC hears
a loud sound (gunshot, shout) it enters ``searching`` — walking toward
the sound source and scanning with its vision cone.  If the target is
spotted, the NPC transitions to ``chase``; otherwise it times out and
returns to ``idle``.
"""

from __future__ import annotations
import random
import math

from core.ecs import World
from components import (
    Brain, HomeRange, Threat, AttackConfig,
    Position, Velocity, Facing,
)
from components import Faction, Health, Identity
from components.dev_log import DevLog
from logic.ai.brains import register_brain
from logic.ai.perception import hp_ratio, should_engage
from logic.ai.steering import face_toward
from logic.ai.defense import try_dodge, try_heal, reset_faction_on_return
from logic.ai.brains import _log
from logic.combat import targeting as sense
from logic.combat import movement as move
from logic.combat.fireline import get_ally_fire_lines, fire_line_dodge_vector, request_clear_fire_line
from logic.combat.tactical import find_tactical_position, find_chase_los_waypoint
from logic.combat.allies import PointProxy
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


# ── Main entry point ────────────────────────────────────────────────

def _combat_brain(world: World, eid: int, brain: Brain, dt: float,
                  game_time: float = 0.0):
    """Unified combat FSM: idle -> chase -> attack -> flee -> return."""
    pos = world.get(eid, Position)
    vel = world.get(eid, Velocity)
    if not pos or not vel:
        return

    patrol = world.get(eid, HomeRange)
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
    # Faction gate — not hostile?  Searching NPCs may continue;
    # everyone else idles.
    if not should_engage(world, eid):
        if c["mode"] != "searching":
            c["mode"] = "idle"
            return False

    # ── Target acquisition ───────────────────────────────────────
    target = sense.acquire_target(world, eid, pos, threat.aggro_radius)
    if target.eid is None:
        c["p_eid"] = None
        c["p_pos"] = None
        if c["mode"] == "searching":
            # No target nearby — check search timer
            if game_time >= c.get("search_until", 0.0):
                c["mode"] = "idle"
                _log(world, eid, "combat",
                     "searching → idle (timed out, no target)", game_time)
            return False
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

    # ── Refresh LOS flags from fresh sensor data ────────────────
    if is_ranged:
        c["_wall_blocked"] = not target.wall_los
        if target.wall_los:
            # LOS regained — find a good firing spot for next time
            c.pop("_repos_target", None)

    # ── Chase wall-block: find a tile with LOS instead of charging
    #    blindly at a wall the NPC can't see through. ─────────────
    if c["mode"] == "chase" and not target.wall_los:
        fire_lines = c.get("_fire_lines")
        wp = find_chase_los_waypoint(
            pos.zone, pos.x, pos.y, target.x, target.y,
            max_search=8.0, fire_lines=fire_lines,
        )
        if wp:
            c["_chase_los_wp"] = wp
            _log(world, eid, "combat",
                 f"chase wall-blocked → rerouting to LOS tile "
                 f"({wp[0]:.1f},{wp[1]:.1f})", game_time)
        else:
            c.pop("_chase_los_wp", None)
    elif c["mode"] == "chase" and target.wall_los:
        c.pop("_chase_los_wp", None)

    # ── Fire-line awareness: cache ally fire lanes ───────────────
    c["_fire_lines"] = get_ally_fire_lines(world, eid, pos)

    # ── Tactical repositioning (ranged only) ─────────────────────
    #    Active fire-line communication: if this NPC's shot is
    #    blocked by an ally, TELL the ally to move.
    if is_ranged and c["mode"] == "attack" and target.ally_in_fire:
        blocker = sense.find_blocking_ally(
            world, eid, pos, target.x, target.y)
        if blocker is not None:
            request_clear_fire_line(
                world, blocker,
                (pos.x, pos.y), (target.x, target.y),
            )

    # ── Check if WE were asked to clear someone's fire-line ──────
    if is_ranged and c["mode"] in ("attack", "chase"):
        _maybe_start_tactical_repos(
            world, eid, pos, atk_cfg, c, target, game_time)

    # ── FSM transitions ──────────────────────────────────────────
    _update_fsm(world, eid, pos, threat, atk_cfg, c, target,
                is_ranged, game_time)
    # ── Share intel with nearby idle allies ───────────────────────
    if c["mode"] in ("chase", "attack") and target.eid is not None:
        from logic.combat.alerts import share_combat_intel
        share_combat_intel(world, eid, pos,
                           (target.x, target.y), game_time)
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

    elif mode == "searching":
        if game_time >= c.get("search_until", 0.0):
            c["mode"] = "idle"
            _log(world, eid, "combat",
                 "searching → idle (timed out)", game_time)
        elif sense.is_detected_idle(world, eid, pos, target.x, target.y,
                                    dist, threat.aggro_radius):
            c["mode"] = "chase"
            # Flip faction to hostile so chase persists
            from logic.faction_ops import make_hostile
            make_hostile(world, eid, reason="spotted target",
                         game_time=game_time)
            _log(world, eid, "combat",
                 f"searching → chase (spotted, dist={dist:.1f})",
                 game_time)

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
            # Patience exhausted — recheck wall LOS before firing
            if not target.wall_los:
                _log(world, eid, "combat",
                     "force-fire blocked by wall", game_time)
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
        from logic.combat.attacks import npc_ranged_attack, npc_melee_attack
        if attack_type == "ranged":
            npc_ranged_attack(world, attacker_eid, target_eid)
        else:
            npc_melee_attack(world, attacker_eid, target_eid)


# ── Per-frame movement ───────────────────────────────────────────────

_SCAN_DIRS = ("right", "down", "left", "up")


def _search_rotate_facing(world, eid, pos, c, game_time):
    """Rotate NPC facing during *searching* to sweep their vision cone."""
    facing = world.get(eid, Facing)
    if facing is None:
        return
    src = c.get("search_source")
    if src is None:
        return
    dist_to_src = math.hypot(src[0] - pos.x, src[1] - pos.y)
    if dist_to_src < 2.0:
        # Close to sound source — scan in cardinal directions
        start = c.get("_search_start", game_time)
        elapsed = game_time - start
        interval = _tun("combat.engagement", "search_scan_interval", 0.8)
        idx = int(elapsed / interval) % 4
        facing.direction = _SCAN_DIRS[idx]
    else:
        # Still walking toward source — face that direction
        face_toward(world, eid, PointProxy(src[0], src[1]))


def _maybe_start_tactical_repos(world, eid, pos, atk_cfg, c, target,
                                game_time):
    """Initiate a tactical reposition if needed (fire-line / clump).

    Called during the sensor tick.  Sets ``c['_tac_repos']`` to a
    destination the NPC should pathfind toward on subsequent movement
    frames, replacing the old passive velocity nudge entirely.

    Triggers:
      1. An ally explicitly asked us to clear their fire-line
         (``c['_clear_fire_line']`` set by ``request_clear_fire_line``).
      2. We're standing in any ally's fire-line ourselves.
      3. We're too close to another ally (anti-clump).

    We skip if a reposition is already active and not yet expired.
    """
    # Already repositioning?  Don't override until it expires.
    if c.get("_tac_repos") and c.get("_tac_repos_until", 0.0) > game_time:
        return

    fire_lines = c.get("_fire_lines", [])
    need_repos = False

    # Trigger 1 — explicit callout from an ally
    callout = c.pop("_clear_fire_line", None)
    if callout is not None:
        need_repos = True

    # Trigger 2 — self-detection of standing in a fire-line
    if not need_repos and fire_lines:
        nx, ny = fire_line_dodge_vector(pos.x, pos.y, fire_lines)
        if nx != 0.0 or ny != 0.0:
            need_repos = True

    # Trigger 3 — anti-clump: too close to an ally
    ally_positions = sense.get_ally_positions(world, eid, pos)
    clump_dist = _tun("combat.tactical", "ally_min_distance", 3.0)
    if not need_repos:
        for ax, ay in ally_positions:
            if math.hypot(pos.x - ax, pos.y - ay) < clump_dist:
                need_repos = True
                break

    if not need_repos:
        return

    # Find a good tactical position
    tx, ty = target.x, target.y
    rp = find_tactical_position(
        pos.zone, pos.x, pos.y, tx, ty,
        atk_cfg.range,
        fire_lines=fire_lines,
        ally_positions=ally_positions,
        origin=c.get("origin"),
    )
    if rp is not None:
        c["_tac_repos"] = rp
        c["_tac_repos_until"] = (
            game_time + _tun("combat.tactical", "repos_timeout", 3.0)
        )


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

    elif mode == "searching":
        src = c.get("search_source", (pos.x, pos.y))
        search_speed = p_speed * _tun(
            "combat.engagement", "search_speed_mult", 0.6)
        move.searching(pos, vel, src[0], src[1], search_speed, c, dt)
        _search_rotate_facing(world, eid, pos, c, game_time)

    elif mode == "chase" and p_cache:
        chase_mult = (_tun("combat.engagement", "chase_mult_ranged", 1.2)
                      if is_ranged
                      else _tun("combat.engagement", "chase_mult_melee", 1.4))
        # If wall-blocked, pathfind to LOS waypoint instead of target
        chase_wp = c.get("_chase_los_wp")
        if chase_wp:
            cx, cy = chase_wp
            # Check if we've reached the LOS waypoint
            if math.hypot(pos.x - cx, pos.y - cy) < 1.0:
                c.pop("_chase_los_wp", None)
                move.chase(pos, vel, p_cache[0], p_cache[1],
                           p_speed * chase_mult, c, game_time)
            else:
                move.chase(pos, vel, cx, cy,
                           p_speed * chase_mult, c, game_time)
        else:
            move.chase(pos, vel, p_cache[0], p_cache[1],
                       p_speed * chase_mult, c, game_time)
        face_toward(world, eid, PointProxy(p_cache[0], p_cache[1]))

    elif mode == "attack" and p_cache:
        px, py = p_cache
        face_toward(world, eid, PointProxy(px, py))
        dist = math.hypot(pos.x - px, pos.y - py)
        if is_ranged:
            # ── Tactical reposition takes priority ───────────────
            tac = c.get("_tac_repos")
            tac_until = c.get("_tac_repos_until", 0.0)
            if tac and game_time < tac_until:
                rx, ry = tac
                d_repos = math.hypot(pos.x - rx, pos.y - ry)
                if d_repos < _tun("combat.tactical",
                                  "repos_arrive_dist", 0.8):
                    # Arrived — clear reposition target
                    c.pop("_tac_repos", None)
                    c.pop("_tac_repos_until", None)
                else:
                    move.tactical_reposition(
                        pos, vel, rx, ry, p_speed, c, game_time)
                    return
            elif tac:
                # Timeout expired — clear stale repos
                c.pop("_tac_repos", None)
                c.pop("_tac_repos_until", None)

            # When wall-blocked, find a flanking position with LOS
            wall_blk = c.get("_wall_blocked", False)
            if wall_blk and not c.get("_repos_target"):
                fire_lines = c.get("_fire_lines")
                ally_positions = sense.get_ally_positions(
                    world, eid, pos)
                rp = find_tactical_position(
                    pos.zone, pos.x, pos.y, px, py,
                    atk_cfg.range,
                    fire_lines=fire_lines,
                    ally_positions=ally_positions,
                    origin=c.get("origin"))
                if rp:
                    c["_repos_target"] = rp
            move.ranged_attack(
                pos, vel, px, py, dist, atk_cfg.range, p_speed,
                c, dt,
                wall_blocked=wall_blk,
                los_blocked=c.get("_los_blocked", False),
                game_time=game_time,
                repos_target=c.get("_repos_target"),
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

def tick_combat_fsm(world: World, eid: int, brain: Brain, dt: float,
                     game_time: float = 0.0) -> None:
    _combat_brain(world, eid, brain, dt, game_time)


# Register under all three brain kinds so existing entities work unchanged
register_brain("hostile_melee", _combat_brain)
register_brain("hostile_ranged", _combat_brain)
register_brain("guard", _combat_brain)
