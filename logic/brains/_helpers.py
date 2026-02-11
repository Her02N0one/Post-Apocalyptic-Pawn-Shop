"""logic/brains/_helpers.py — Shared AI helper functions.

Movement, targeting, faction gating, and defense utilities used by
multiple brain implementations.

Cooldowns use absolute GameClock timestamps rather than ``-= dt``
countdowns to prevent floating-point drift on long-running timers.
"""

from __future__ import annotations
import random
import math
from core.ecs import World
from components import (
    Brain, Patrol, Threat, AttackConfig,
    Position, Velocity, Health, Player, Facing,
    HitFlash, Faction, Inventory, ItemRegistry, Identity,
)
from core.zone import is_passable


# ── Targeting ────────────────────────────────────────────────────────

def find_player(world: World):
    """Return (eid, Position) of the player, or (None, None)."""
    res = world.query_one(Player, Position)
    if res:
        return res[0], res[2]
    return None, None


def dist_pos(a, b) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def hp_ratio(world: World, eid: int) -> float:
    h = world.get(eid, Health)
    if h is None:
        return 1.0
    return h.current / max(1.0, h.maximum)


# ── Movement ─────────────────────────────────────────────────────────

def move_toward(pos, vel, tx: float, ty: float, speed: float):
    dx = tx - pos.x
    dy = ty - pos.y
    d = math.hypot(dx, dy)
    if d < 0.05:
        vel.x, vel.y = 0.0, 0.0
        return
    vel.x = (dx / d) * speed
    vel.y = (dy / d) * speed


def move_away(pos, vel, tx: float, ty: float, speed: float):
    dx = pos.x - tx
    dy = pos.y - ty
    d = math.hypot(dx, dy)
    if d < 0.05:
        vel.x = speed
        vel.y = 0.0
        return
    vel.x = (dx / d) * speed
    vel.y = (dy / d) * speed


def strafe(pos, vel, target_pos, speed: float, direction: int):
    """Move perpendicular to the line toward *target_pos*."""
    dx = target_pos.x - pos.x
    dy = target_pos.y - pos.y
    d = math.hypot(dx, dy)
    if d < 0.05:
        return
    # Rotate 90°
    vel.x = (-dy / d) * direction * speed
    vel.y = (dx / d) * direction * speed


def face_toward(world: World, eid: int, target_pos):
    facing = world.get(eid, Facing)
    if facing is None:
        return
    pos = world.get(eid, Position)
    if pos is None:
        return
    dx = target_pos.x - pos.x
    dy = target_pos.y - pos.y
    if abs(dx) >= abs(dy):
        facing.direction = "right" if dx > 0 else "left"
    else:
        facing.direction = "down" if dy > 0 else "up"


def run_idle(patrol, pos, vel, s: dict, dt: float):
    """Shared idle / slow-wander used by combat brains when no target."""
    s.setdefault("idle_timer", 0.0)
    s.setdefault("idle_dir", (0.0, 0.0))
    s["idle_timer"] -= dt
    if s["idle_timer"] <= 0:
        angle = random.uniform(0, 2 * math.pi)
        speed = random.uniform(patrol.speed * 0.2, patrol.speed * 0.5)
        s["idle_dir"] = (speed * math.cos(angle), speed * math.sin(angle))
        s["idle_timer"] = random.uniform(1.5, 4.0)

    dx, dy = s["idle_dir"]
    ox, oy = s.get("origin", (pos.x, pos.y))

    # Stay near origin
    nx = pos.x + dx * dt
    ny = pos.y + dy * dt
    if (nx - ox) ** 2 + (ny - oy) ** 2 > patrol.radius ** 2:
        to_ox = ox - pos.x
        to_oy = oy - pos.y
        length = max(0.01, math.hypot(to_ox, to_oy))
        spd = patrol.speed * 0.3
        dx = (to_ox / length) * spd
        dy = (to_oy / length) * spd
        s["idle_dir"] = (dx, dy)
        s["idle_timer"] = random.uniform(0.5, 1.0)

    if is_passable(pos.zone, pos.x + dx * dt, pos.y + dy * dt):
        vel.x = dx
        vel.y = dy
    else:
        vel.x, vel.y = 0.0, 0.0
        s["idle_timer"] = 0.1


# ── Faction / defense ───────────────────────────────────────────────

def should_engage(world: World, eid: int) -> bool:
    """Return True if entity should use hostile combat AI.

    No Faction component -> always hostile (backward compat).
    """
    faction = world.get(eid, Faction)
    if faction is None:
        return True
    return faction.disposition == "hostile"


def try_dodge(world: World, eid: int, brain: Brain,
              pos, vel, s: dict, dt: float, game_time: float) -> bool:
    """On a fresh hit, dash perpendicular. Returns True if dodging."""
    hf = world.get(eid, HitFlash)
    if hf is None or hf.remaining < 0.08:
        return False
    if s.get("dodge_until", 0.0) > game_time:
        return False
    p_eid, p_pos = find_player(world)
    if p_pos is None:
        return False
    dx = p_pos.x - pos.x
    dy = p_pos.y - pos.y
    d = math.hypot(dx, dy)
    if d < 0.05:
        return False
    patrol = world.get(eid, Patrol)
    dodge_speed = (patrol.speed if patrol else 2.0) * 3.0
    direction = 1 if random.random() > 0.5 else -1
    vel.x = (-dy / d) * direction * dodge_speed
    vel.y = (dx / d) * direction * dodge_speed
    s["dodge_until"] = game_time + 1.5
    return True


def try_heal(world: World, eid: int, brain: Brain, s: dict,
             game_time: float) -> bool:
    """If HP is low and entity has consumables, use the best one."""
    if s.get("heal_until", 0.0) > game_time:
        return False
    hp = hp_ratio(world, eid)
    if hp > 0.4:
        return False
    inv = world.get(eid, Inventory)
    if inv is None:
        return False
    registry = world.res(ItemRegistry)
    if registry is None:
        return False
    best_id = None
    best_heal = 0.0
    for item_id, qty in inv.items.items():
        if qty <= 0:
            continue
        if registry.item_type(item_id) != "consumable":
            continue
        heal = registry.get_field(item_id, "heal", 0.0)
        if heal > best_heal:
            best_heal = heal
            best_id = item_id
    if best_id is None:
        return False
    health = world.get(eid, Health)
    if health:
        health.current = min(health.maximum, health.current + best_heal)
    inv.items[best_id] -= 1
    if inv.items[best_id] <= 0:
        del inv.items[best_id]
    name = "?"
    if world.has(eid, Identity):
        name = world.get(eid, Identity).name
    print(f"[AI] {name} used {registry.display_name(best_id)} (+{best_heal:.0f} HP)")
    s["heal_until"] = game_time + 5.0
    return True


def reset_faction_on_return(world: World, eid: int):
    """When a combat entity returns home, reset disposition."""
    faction = world.get(eid, Faction)
    if faction and faction.disposition != faction.home_disposition:
        faction.disposition = faction.home_disposition
