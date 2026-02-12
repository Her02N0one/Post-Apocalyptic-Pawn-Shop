"""logic/brains/villager.py — Schedule-driven village NPC brain.

Villagers follow a daily schedule mapped to a recurring in-game day
cycle.  Each day lasts ``DAY_LENGTH`` game-seconds and cycles through
four periods::

    morning   →  work (patrol/tend resources near home)
    midday    →  eat  (walk to pantry subzone, pause to eat)
    afternoon →  socialize (walk to market/well, idle near others)
    evening   →  rest (return home, stand still)

The brain also handles:
* **Destination walking** — when promoted from low-LOD with a pending
  travel destination (``_sim_was_traveling``), the NPC walks toward
  the relevant portal / subzone anchor first.
* **Crime panic** — fleeing from the player briefly after witnessing
  a crime.
* **Needs override** — interrupt the schedule when hunger is critical.

This brain is intended for peaceful village NPCs (farmers, traders).
Combat-capable variants should extend hostile_melee/guard instead.
"""

from __future__ import annotations
import random
import math
from core.ecs import World
from components import (
    Brain, Patrol, Position, Velocity, Needs, Hunger, Inventory,
    Identity, Faction,
)
from core.zone import is_passable, ZONE_PORTALS, ZONE_MAPS
from logic.brains._helpers import find_player, move_away
from logic.brains import register_brain
from logic.pathfinding import find_path, path_next_waypoint


# ── Tuning constants ──────────────────────────────────────────────────

# A full in-game "day" cycle (seconds of game time).
DAY_LENGTH = 300.0  # 5 real minutes = one day

# Period boundaries as fractions of DAY_LENGTH.
_PERIODS = [
    (0.00, 0.30, "morning"),    # 0-30 %
    (0.30, 0.45, "midday"),     # 30-45 %
    (0.45, 0.75, "afternoon"),  # 45-75 %
    (0.75, 1.00, "evening"),    # 75-100 %
]

EAT_PAUSE = 2.0
EAT_THRESHOLD = 0.4

# Subzones considered "social" gathering points — NPCs walk toward these
_SOCIAL_SUBZONES = {"sett_market", "sett_well"}
_WORK_SUBZONES = {"sett_farm", "sett_storehouse"}

# How close is "arrived" for walk-toward behaviour (tiles)
_ARRIVE_DIST = 2.5
_SOCIAL_DIST = 4.0   # how far to look for other NPCs to greet

# Stuck detection: give up walking if position barely changes
_STUCK_CHECK_INTERVAL = 1.0   # sample every N seconds
_STUCK_MOVE_THRESHOLD = 0.3   # must move at least this far per sample
_STUCK_STRIKES = 3            # give up after N consecutive stuck samples


# ── Helpers ───────────────────────────────────────────────────────────

def _time_of_day(game_time: float) -> str:
    """Return current period name based on game clock."""
    frac = (game_time % DAY_LENGTH) / DAY_LENGTH
    for lo, hi, name in _PERIODS:
        if lo <= frac < hi:
            return name
    return "evening"


def _subzone_anchor(world: World, subzone_id: str):
    """Return anchor tile coords for a subzone, or None."""
    from simulation.subzone import SubzoneGraph
    graph = world.res(SubzoneGraph)
    if graph is None:
        return None
    node = graph.get_node(subzone_id)
    return node.anchor if node else None


def _portal_pos_for_zone(zone: str) -> tuple[float, float] | None:
    """Return the spawn position of the portal endpoint in *zone*."""
    for portal in ZONE_PORTALS:
        if portal.side_a.zone == zone:
            return portal.side_a.spawn
        if portal.side_b.zone == zone:
            return portal.side_b.spawn
    return None


def _check_stuck(v: dict, pos, game_time: float) -> bool:
    """Return True when an NPC hasn't made meaningful progress.

    Call every frame during a directed walk. Samples position once per
    ``_STUCK_CHECK_INTERVAL`` seconds and increments a strike counter
    when the NPC hasn't moved at least ``_STUCK_MOVE_THRESHOLD`` tiles.
    After ``_STUCK_STRIKES`` consecutive stuck samples → True (give up).
    Resets automatically when the NPC makes progress.
    """
    last_check = v.get("stuck_check_t")
    if last_check is not None and game_time - last_check < _STUCK_CHECK_INTERVAL:
        return False

    v["stuck_check_t"] = game_time
    prev = v.get("stuck_check_pos")
    if prev is None:
        v["stuck_check_pos"] = (pos.x, pos.y)
        v["stuck_strikes"] = 0
        return False

    moved = math.hypot(pos.x - prev[0], pos.y - prev[1])
    v["stuck_check_pos"] = (pos.x, pos.y)

    if moved < _STUCK_MOVE_THRESHOLD:
        strikes = v.get("stuck_strikes", 0) + 1
        v["stuck_strikes"] = strikes
        if strikes >= _STUCK_STRIKES:
            v["stuck_strikes"] = 0
            v.pop("stuck_check_pos", None)
            return True
    else:
        v["stuck_strikes"] = 0
    return False


# How often to recompute the A* path (seconds)
_PATH_RECOMPUTE_INTERVAL = 1.5

# Offsets to try when the direct path is blocked (radians).
_STEER_OFFSETS = [0.0, 0.4, -0.4, 0.8, -0.8, 1.2, -1.2,
                  math.pi * 0.5, -math.pi * 0.5,
                  math.pi * 0.75, -math.pi * 0.75]


def _walk_toward(pos, vel, tx: float, ty: float, speed: float,
                 dt: float, state: dict | None = None,
                 game_time: float = 0.0) -> float:
    """Set velocity to walk toward (tx, ty) using A* pathfinding.

    Computes an A* path from the entity's current tile to the goal tile,
    caches it in *state*, then follows waypoints each frame.  Falls back
    to reactive steering if A* returns no path (e.g. zone not loaded).
    Returns the straight-line distance to the target.
    """
    dx = tx - pos.x
    dy = ty - pos.y
    dist = math.hypot(dx, dy)
    if dist < 0.3:
        vel.x, vel.y = 0.0, 0.0
        return dist

    # ── Try A* path (cached) ─────────────────────────────────────────
    if state is not None:
        path = state.get("_path")
        path_target = state.get("_path_target")
        path_time = state.get("_path_time", 0.0)
        need_recompute = (
            path is None
            or path_target is None
            or abs(path_target[0] - tx) > 1.5
            or abs(path_target[1] - ty) > 1.5
            or (game_time - path_time) > _PATH_RECOMPUTE_INTERVAL
        )

        if need_recompute:
            new_path = find_path(pos.zone, pos.x, pos.y, tx, ty, max_dist=48)
            state["_path"] = new_path
            state["_path_target"] = (tx, ty)
            state["_path_time"] = game_time
            path = new_path

        if path is not None and len(path) > 0:
            wp = path_next_waypoint(path, pos.x, pos.y, reach=0.45)
            if wp is not None:
                wx, wy = wp
                wdx = wx - pos.x
                wdy = wy - pos.y
                wd = math.hypot(wdx, wdy)
                if wd > 0.05:
                    vel.x = (wdx / wd) * speed
                    vel.y = (wdy / wd) * speed
                    return dist
            else:
                # Path exhausted — we've arrived
                vel.x, vel.y = 0.0, 0.0
                state["_path"] = None
                return dist

    # ── Fallback: reactive steering ──────────────────────────────────
    base_angle = math.atan2(dy, dx)

    for offset in _STEER_OFFSETS:
        a = base_angle + offset
        sx = math.cos(a) * speed
        sy = math.sin(a) * speed
        near = 0.15
        if (is_passable(pos.zone, pos.x + sx * near, pos.y + sy * near) and
                is_passable(pos.zone, pos.x + sx * dt, pos.y + sy * dt)):
            vel.x = sx
            vel.y = sy
            return dist

    # Every direction blocked — stop
    vel.x, vel.y = 0.0, 0.0
    return dist


def _pick_target_for_period(world: World, period: str, zone: str,
                            home_subzone: str):
    """Choose a target subzone for the current schedule period."""
    if period == "morning":
        # Walk to a work area (prefer farm/storehouse)
        for sz in _WORK_SUBZONES:
            a = _subzone_anchor(world, sz)
            if a:
                return a
    elif period == "midday":
        # Head to market to eat
        a = _subzone_anchor(world, "sett_market")
        return a
    elif period == "afternoon":
        # Socialize — pick a random social spot
        sz = random.choice(list(_SOCIAL_SUBZONES))
        a = _subzone_anchor(world, sz)
        return a
    elif period == "evening":
        # Return home
        if home_subzone:
            a = _subzone_anchor(world, home_subzone)
            if a:
                return a
    return None


def _nearby_npc(world: World, eid: int, pos, radius: float):
    """Find the nearest other friendly NPC with a position."""
    best_eid = None
    best_dist = radius
    for oid, opos in world.all_of(Position):
        if oid == eid or opos.zone != pos.zone:
            continue
        if not world.has(oid, Brain):
            continue
        fac = world.get(oid, Faction)
        if fac and fac.disposition == "hostile":
            continue
        d = math.hypot(opos.x - pos.x, opos.y - pos.y)
        if d < best_dist:
            best_dist = d
            best_eid = oid
    return best_eid


# ── Main brain ────────────────────────────────────────────────────────

def _villager_brain(world: World, eid: int, brain: Brain, dt: float,
                    game_time: float = 0.0):
    """Schedule-driven villager brain."""
    pos = world.get(eid, Position)
    vel = world.get(eid, Velocity)
    if not pos or not vel:
        return

    patrol = world.get(eid, Patrol)
    if patrol is None:
        return

    s = brain.state
    v = s.setdefault("villager", {})
    if "origin" not in v:
        v["origin"] = (pos.x, pos.y)
    v.setdefault("mode", "idle")
    v.setdefault("home_subzone", "")

    needs = world.get(eid, Needs)
    hunger = world.get(eid, Hunger)
    inv = world.get(eid, Inventory)
    mode = v["mode"]

    # ── 0. Destination walk (from LOD promotion) ─────────────────────
    if s.get("_sim_was_traveling"):
        dest = s.pop("_sim_destination", None)
        s.pop("_sim_was_traveling", None)
        if dest:
            # Find target position — portal or subzone anchor
            target = _subzone_anchor(world, dest)
            if target is None:
                target = _portal_pos_for_zone(pos.zone)
            if target:
                v["mode"] = "travel"
                v["travel_target"] = target
                mode = "travel"

    if mode == "travel":
        tt = v.get("travel_target")
        if tt:
            dist = _walk_toward(pos, vel, tt[0], tt[1], patrol.speed, dt,
                               state=v, game_time=game_time)
            if dist < _ARRIVE_DIST:
                v["mode"] = "idle"
                v.pop("travel_target", None)
                v.pop("_path", None)
                vel.x, vel.y = 0.0, 0.0
            elif _check_stuck(v, pos, game_time):
                v["mode"] = "idle"
                v["origin"] = (pos.x, pos.y)
                vel.x, vel.y = 0.0, 0.0
        else:
            v["mode"] = "idle"
        return

    # ── 1. Crime panic: flee the player briefly ──────────────────────
    flee_until = s.get("crime_flee_until", 0.0)
    if flee_until > game_time:
        p_eid, p_pos = find_player(world)
        if p_pos and p_pos.zone == pos.zone:
            move_away(pos, vel, p_pos.x, p_pos.y, patrol.speed * 1.6)
            return

    # ── 2. Critical hunger override ──────────────────────────────────
    if mode not in ("eat", "forage") and needs and needs.priority == "eat":
        if hunger and (hunger.current / max(hunger.maximum, 0.01)) < EAT_THRESHOLD:
            has_food = inv is not None and len(inv.items) > 0
            if has_food:
                v["mode"] = "eat"
                v["eat_until"] = game_time + EAT_PAUSE
                mode = "eat"
            else:
                v["mode"] = "forage"
                v["forage_until"] = game_time + random.uniform(8.0, 15.0)
                mode = "forage"

    # ── Eat ──────────────────────────────────────────────────────────
    if mode == "eat":
        vel.x, vel.y = 0.0, 0.0
        if v.get("eat_until", 0.0) <= game_time:
            v["mode"] = "idle"
        return

    # ── Forage ───────────────────────────────────────────────────────
    if mode == "forage":
        if v.get("forage_until", 0.0) <= game_time:
            v["mode"] = "return"
            return
        _wander_step(patrol, pos, vel, v, dt, speed_mult=1.3, game_time=game_time)
        return

    # ── Return ───────────────────────────────────────────────────────
    if mode == "return":
        ox, oy = v.get("origin", (pos.x, pos.y))
        dist = math.hypot(pos.x - ox, pos.y - oy)
        if dist < _ARRIVE_DIST:
            v["mode"] = "idle"
            vel.x, vel.y = 0.0, 0.0
            return
        _walk_toward(pos, vel, ox, oy, patrol.speed, dt,
                     state=v, game_time=game_time)
        if _check_stuck(v, pos, game_time):
            v["mode"] = "idle"
            v["origin"] = (pos.x, pos.y)
            vel.x, vel.y = 0.0, 0.0
        return

    # ── 3. Schedule-driven behavior ──────────────────────────────────
    period = _time_of_day(game_time)
    old_period = v.get("period", "")

    if period != old_period:
        # Period changed — pick a new target
        v["period"] = period
        v["schedule_target"] = None
        v["socializing"] = False
        v["greet_cooldown"] = 0.0
        v.pop("_path", None)           # invalidate cached A* path

        target = _pick_target_for_period(
            world, period, pos.zone, v.get("home_subzone", ""))
        if target:
            v["schedule_target"] = target
            v["mode"] = "schedule_walk"
            mode = "schedule_walk"

    # ── Schedule walk ────────────────────────────────────────────────
    if mode == "schedule_walk":
        tgt = v.get("schedule_target")
        if tgt:
            dist = _walk_toward(pos, vel, tgt[0], tgt[1], patrol.speed, dt,
                               state=v, game_time=game_time)
            if dist < _ARRIVE_DIST:
                v["mode"] = "schedule_idle"
                v["origin"] = (pos.x, pos.y)
                v.pop("_path", None)
                vel.x, vel.y = 0.0, 0.0
            elif _check_stuck(v, pos, game_time):
                # Can't reach target — idle where we are
                v["mode"] = "schedule_idle"
                v["origin"] = (pos.x, pos.y)
                vel.x, vel.y = 0.0, 0.0
        else:
            v["mode"] = "idle"
        return

    # ── Schedule idle (arrived at schedule target) ────────────────────
    if mode == "schedule_idle":
        # In afternoon period, try to socialize with nearby NPCs
        if period == "afternoon":
            v.setdefault("greet_cooldown", 0.0)
            if game_time >= v.get("greet_cooldown", 0.0):
                neighbor = _nearby_npc(world, eid, pos, _SOCIAL_DIST)
                if neighbor is not None:
                    npos = world.get(neighbor, Position)
                    if npos:
                        # Face toward neighbor and pause
                        _walk_toward(pos, vel, npos.x, npos.y,
                                     patrol.speed * 0.3, dt,
                                     state=v, game_time=game_time)
                        v["greet_cooldown"] = game_time + random.uniform(3.0, 8.0)
                        return
            # Otherwise gentle wander at the social spot
            _wander_step(patrol, pos, vel, v, dt, speed_mult=0.4, game_time=game_time)
            return

        if period == "evening":
            # Stand still at home
            vel.x, vel.y = 0.0, 0.0
            return

        # Morning/midday — gentle patrol at work/eat location
        _wander_step(patrol, pos, vel, v, dt, speed_mult=0.5, game_time=game_time)
        return

    # ── Default idle (wander) ────────────────────────────────────────
    _wander_step(patrol, pos, vel, v, dt, game_time=game_time)


# ── Wandering helper ─────────────────────────────────────────────────

_WANDER_PICK_MIN = 2.0
_WANDER_PICK_MAX = 4.5

def _wander_step(patrol: Patrol, pos, vel, s: dict, dt: float,
                 speed_mult: float = 1.0, game_time: float = 0.0):
    """Perform one frame of A*-backed wander, constrained to patrol radius.

    Picks a random passable tile within patrol radius and follows an
    A* path to it.  Falls back to reactive random walk when the zone
    map is unavailable.
    """
    ox, oy = s.get("origin", (pos.x, pos.y))
    wpath = s.get("_wander_path")
    pick_time = s.get("_wander_pick_t", 0.0)
    pick_ivl = s.get("_wander_pick_ivl", _WANDER_PICK_MAX)

    need_new = (
        wpath is None
        or len(wpath) == 0
        or (game_time - pick_time) > pick_ivl
    )

    if need_new:
        dest = None
        tiles = ZONE_MAPS.get(pos.zone)
        if tiles:
            rows = len(tiles)
            cols = len(tiles[0]) if rows else 0
            for _ in range(6):
                angle = random.uniform(0, 2 * math.pi)
                r = random.uniform(1.5, patrol.radius)
                tx = ox + math.cos(angle) * r
                ty = oy + math.sin(angle) * r
                tr, tc = int(ty), int(tx)
                if 0 <= tr < rows and 0 <= tc < cols and is_passable(pos.zone, tx, ty):
                    dest = (tx, ty)
                    break
        if dest:
            new_path = find_path(pos.zone, pos.x, pos.y, dest[0], dest[1],
                                 max_dist=int(patrol.radius) + 6)
            s["_wander_path"] = new_path
        else:
            s["_wander_path"] = None
        s["_wander_pick_t"] = game_time
        s["_wander_pick_ivl"] = random.uniform(_WANDER_PICK_MIN, _WANDER_PICK_MAX)
        wpath = s.get("_wander_path")

    # Follow path
    if wpath is not None and len(wpath) > 0:
        wp = path_next_waypoint(wpath, pos.x, pos.y, reach=0.45)
        if wp is not None:
            wx, wy = wp
            wdx = wx - pos.x
            wdy = wy - pos.y
            wd = math.hypot(wdx, wdy)
            if wd > 0.05:
                spd = patrol.speed * speed_mult
                vel.x = (wdx / wd) * spd
                vel.y = (wdy / wd) * spd
            else:
                vel.x, vel.y = 0.0, 0.0
            return
        else:
            s["_wander_path"] = None
            vel.x, vel.y = 0.0, 0.0
            return

    # Fallback: reactive random walk
    s.setdefault("timer", 0.0)
    s.setdefault("dir", (0.0, 0.0))

    s["timer"] -= dt
    if s["timer"] <= 0.0:
        angle = random.uniform(0, 2 * math.pi)
        spd = random.uniform(patrol.speed * 0.3,
                             patrol.speed) * speed_mult
        s["dir"] = (spd * math.cos(angle), spd * math.sin(angle))
        s["timer"] = random.uniform(1.0, 3.0)

    dx, dy = s["dir"]

    nx = pos.x + dx * dt
    ny = pos.y + dy * dt
    if (nx - ox) ** 2 + (ny - oy) ** 2 > patrol.radius ** 2:
        to_ox = ox - pos.x
        to_oy = oy - pos.y
        length = max(0.01, math.hypot(to_ox, to_oy))
        spd = patrol.speed * 0.5 * speed_mult
        s["dir"] = ((to_ox / length) * spd, (to_oy / length) * spd)
        s["timer"] = random.uniform(0.5, 1.5)
        dx, dy = s["dir"]

    if is_passable(pos.zone, pos.x + dx * dt, pos.y + dy * dt):
        vel.x = dx
        vel.y = dy
    else:
        vel.x, vel.y = 0.0, 0.0
        s["timer"] = 0.1


register_brain("villager", _villager_brain)
