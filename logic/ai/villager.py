"""logic/ai/villager.py — Schedule-driven village NPC brain.

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
    Brain, HomeRange, Position, Velocity, Needs, Hunger, Inventory,
    Identity, Faction, ItemRegistry,
)
from core.zone import is_passable, ZONE_PORTALS, ZONE_MAPS
from logic.ai.perception import find_player
from logic.ai.steering import move_away, move_toward_pathfind
from logic.ai.brains import register_brain
from logic.pathfinding import find_path, path_next_waypoint
from logic.needs import npc_eat_from_inventory
from core.tuning import get as _tun


# ── Tuning helpers (read from data/tuning.toml at call-time) ─────────

def _day_length():
    return _tun("ai.villager", "day_length", 300.0)

def _periods():
    return [
        (_tun("ai.villager", "morning_start", 0.00),
         _tun("ai.villager", "morning_end", 0.30), "morning"),
        (_tun("ai.villager", "midday_start", 0.30),
         _tun("ai.villager", "midday_end", 0.45), "midday"),
        (_tun("ai.villager", "afternoon_start", 0.45),
         _tun("ai.villager", "afternoon_end", 0.75), "afternoon"),
        (_tun("ai.villager", "evening_start", 0.75),
         _tun("ai.villager", "evening_end", 1.00), "evening"),
    ]

# Subzones considered "social" gathering points — NPCs walk toward these
_SOCIAL_SUBZONES = {"sett_market", "sett_well"}
_WORK_SUBZONES = {"sett_farm", "sett_storehouse"}


# ── Helpers ───────────────────────────────────────────────────────────

def _time_of_day(game_time: float) -> str:
    """Return current period name based on game clock."""
    dl = _day_length()
    frac = (game_time % dl) / dl
    for lo, hi, name in _periods():
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
    chk_interval = _tun("ai.villager", "stuck_check_interval", 1.0)
    last_check = v.get("stuck_check_t")
    if last_check is not None and game_time - last_check < chk_interval:
        return False

    v["stuck_check_t"] = game_time
    prev = v.get("stuck_check_pos")
    if prev is None:
        v["stuck_check_pos"] = (pos.x, pos.y)
        v["stuck_strikes"] = 0
        return False

    moved = math.hypot(pos.x - prev[0], pos.y - prev[1])
    v["stuck_check_pos"] = (pos.x, pos.y)

    move_thresh = _tun("ai.villager", "stuck_move_threshold", 0.3)
    if moved < move_thresh:
        strikes = v.get("stuck_strikes", 0) + 1
        v["stuck_strikes"] = strikes
        max_strikes = _tun("ai.villager", "stuck_strikes", 3)
        if strikes >= max_strikes:
            v["stuck_strikes"] = 0
            v.pop("stuck_check_pos", None)
            return True
    else:
        v["stuck_strikes"] = 0
    return False


def _walk_toward(pos, vel, tx: float, ty: float, speed: float,
                 dt: float, state: dict | None = None,
                 game_time: float = 0.0) -> float:
    """Walk toward (tx, ty) using A* with reactive steering fallback.

    Thin wrapper around ``move_toward_pathfind`` with villager-specific
    tuning (larger search radius, slower recompute, reactive steering).
    """
    if state is None:
        state = {}
    return move_toward_pathfind(
        pos, vel, tx, ty, speed, state, game_time,
        tuning_ns="ai.villager",
        max_dist=48,
        arrival_dist=0.3,
        reactive_steering=True,
        dt=dt,
    )


# ── Food consumption ─────────────────────────────────────────────────

# Canonical eat logic lives in ``logic.needs.npc_eat_from_inventory``.
# Previously this file had its own _consume_food — removed to avoid
# 4-way duplication of the same eat-from-inventory algorithm.


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
    """Find the nearest other friendly NPC with a position.

    Uses ``world.nearby()`` for O(1) zone-filtered spatial query.
    """
    best_eid = None
    best_dist_sq = radius * radius
    for oid, opos, _brain, dsq in world.nearby(
        pos.zone, pos.x, pos.y, radius, Position, Brain,
    ):
        if oid == eid:
            continue
        fac = world.get(oid, Faction)
        if fac and fac.disposition == "hostile":
            continue
        if dsq < best_dist_sq:
            best_dist_sq = dsq
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

    patrol = world.get(eid, HomeRange)
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

    arrive_dist = _tun("ai.villager", "arrive_dist", 2.5)

    if mode == "travel":
        tt = v.get("travel_target")
        if tt:
            dist = _walk_toward(pos, vel, tt[0], tt[1], patrol.speed, dt,
                               state=v, game_time=game_time)
            if dist < arrive_dist:
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
            flee_mult = _tun("ai.villager", "crime_flee_speed_mult", 1.6)
            move_away(pos, vel, p_pos.x, p_pos.y, patrol.speed * flee_mult)
            return

    # ── 2. Critical hunger override ──────────────────────────────────
    eat_thresh = _tun("ai.villager", "eat_threshold", 0.4)
    if mode not in ("eat", "forage") and needs and needs.priority == "eat":
        if hunger and (hunger.current / max(hunger.maximum, 0.01)) < eat_thresh:
            has_food = inv is not None and len(inv.items) > 0
            if has_food:
                v["mode"] = "eat"
                eat_pause = _tun("ai.villager", "eat_pause", 2.0)
                v["eat_until"] = game_time + eat_pause
                mode = "eat"
            else:
                v["mode"] = "forage"
                f_min = _tun("ai.villager", "forage_duration_min", 8.0)
                f_max = _tun("ai.villager", "forage_duration_max", 15.0)
                v["forage_until"] = game_time + random.uniform(f_min, f_max)
                mode = "forage"

    # ── Eat ──────────────────────────────────────────────────────────
    if mode == "eat":
        vel.x, vel.y = 0.0, 0.0
        if v.get("eat_until", 0.0) <= game_time:
            # Consume one food item via canonical eat helper
            npc_eat_from_inventory(world, eid)
            v["mode"] = "idle"
        return

    # ── Forage ───────────────────────────────────────────────────────
    if mode == "forage":
        if v.get("forage_until", 0.0) <= game_time:
            # Forage complete — add a food item to inventory
            if inv is not None:
                forage_item = _tun("ai.villager", "forage_item", "ration")
                inv.items[forage_item] = inv.items.get(forage_item, 0) + 1
            v["mode"] = "eat"
            eat_pause = _tun("ai.villager", "eat_pause", 2.0)
            v["eat_until"] = game_time + eat_pause
            return
        forage_spd = _tun("ai.villager", "forage_speed_mult", 1.3)
        _wander_step(patrol, pos, vel, v, dt, speed_mult=forage_spd, game_time=game_time)
        return

    # ── Return ───────────────────────────────────────────────────────
    if mode == "return":
        ox, oy = v.get("origin", (pos.x, pos.y))
        dist = math.hypot(pos.x - ox, pos.y - oy)
        if dist < arrive_dist:
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
            if dist < arrive_dist:
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
            social_dist = _tun("ai.villager", "social_dist", 4.0)
            if game_time >= v.get("greet_cooldown", 0.0):
                neighbor = _nearby_npc(world, eid, pos, social_dist)
                if neighbor is not None:
                    npos = world.get(neighbor, Position)
                    if npos:
                        # Face toward neighbor and pause
                        _walk_toward(pos, vel, npos.x, npos.y,
                                     patrol.speed * 0.3, dt,
                                     state=v, game_time=game_time)
                        gc_min = _tun("ai.villager", "greet_cooldown_min", 3.0)
                        gc_max = _tun("ai.villager", "greet_cooldown_max", 8.0)
                        v["greet_cooldown"] = game_time + random.uniform(gc_min, gc_max)
                        return
            # Otherwise gentle wander at the social spot
            social_spd = _tun("ai.villager", "social_wander_speed_mult", 0.4)
            _wander_step(patrol, pos, vel, v, dt, speed_mult=social_spd, game_time=game_time)
            return

        if period == "evening":
            # Stand still at home
            vel.x, vel.y = 0.0, 0.0
            return

        # Morning/midday — gentle patrol at work/eat location
        morn_spd = _tun("ai.villager", "morning_wander_speed_mult", 0.5)
        _wander_step(patrol, pos, vel, v, dt, speed_mult=morn_spd, game_time=game_time)
        return

    # ── Default idle (wander) ────────────────────────────────────────
    _wander_step(patrol, pos, vel, v, dt, game_time=game_time)


# ── Wandering helper ─────────────────────────────────────────────────

# Wander pick intervals now read from tuning

def _wander_step(patrol: HomeRange, pos, vel, s: dict, dt: float,
                 speed_mult: float = 1.0, game_time: float = 0.0):
    """Perform one frame of A*-backed wander, constrained to patrol radius.

    Picks a random passable tile within patrol radius and follows an
    A* path to it.  Falls back to reactive random walk when the zone
    map is unavailable.
    """
    ox, oy = s.get("origin", (pos.x, pos.y))
    wpath = s.get("_wander_path")
    pick_time = s.get("_wander_pick_t", 0.0)
    w_pick_max = _tun("ai.villager", "wander_pick_max", 4.5)
    pick_ivl = s.get("_wander_pick_ivl", w_pick_max)
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
        w_pick_min = _tun("ai.villager", "wander_pick_min", 2.0)
        s["_wander_pick_ivl"] = random.uniform(w_pick_min, w_pick_max)
        wpath = s.get("_wander_path")

    # Follow path
    if wpath is not None and len(wpath) > 0:
        wp = path_next_waypoint(wpath, pos.x, pos.y,
                                reach=_tun("ai.villager", "waypoint_reach", 0.55))
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
