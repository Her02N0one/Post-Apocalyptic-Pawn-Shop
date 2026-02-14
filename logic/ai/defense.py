"""logic/ai/defense.py — Defensive / survival AI helpers.

Dodge reactions, healing, and faction reset on return-to-origin.
"""

from __future__ import annotations
import random
import math
from core.ecs import World
from components import (
    Brain, HomeRange, Health, Inventory, ItemRegistry,
    Identity, Faction, HitFlash,
)
from logic.ai.perception import find_player, find_nearest_enemy, hp_ratio
from core.tuning import get as _tun


def try_dodge(world: World, eid: int, brain: Brain,
              pos, vel, s: dict, dt: float, game_time: float) -> bool:
    """On a fresh hit, dash perpendicular. Returns True if dodging."""
    hf = world.get(eid, HitFlash)
    if hf is None or hf.remaining < 0.08:
        return False
    if s.get("dodge_until", 0.0) > game_time:
        return False
    # Dodge away from the nearest threat (player or enemy)
    p_eid, p_pos = find_player(world)
    if p_pos is None or p_pos.zone != pos.zone:
        p_eid, p_pos = find_nearest_enemy(world, eid, max_range=8.0)
    if p_pos is None:
        return False
    dx = p_pos.x - pos.x
    dy = p_pos.y - pos.y
    d = math.hypot(dx, dy)
    if d < 0.05:
        return False
    patrol = world.get(eid, HomeRange)
    dodge_speed = (patrol.speed if patrol else 2.0) * _tun("ai.helpers", "dodge_speed_mult", 3.0)
    direction = 1 if random.random() > 0.5 else -1
    vel.x = (-dy / d) * direction * dodge_speed
    vel.y = (dx / d) * direction * dodge_speed
    s["dodge_until"] = game_time + _tun("ai.helpers", "dodge_duration", 1.5)
    return True


def try_heal(world: World, eid: int, brain: Brain, s: dict,
             game_time: float) -> bool:
    """If HP is low and entity has consumables, use the best one."""
    if s.get("heal_until", 0.0) > game_time:
        return False
    hp = hp_ratio(world, eid)
    if hp > _tun("ai.helpers", "heal_hp_threshold", 0.4):
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
    s["heal_until"] = game_time + _tun("ai.helpers", "heal_cooldown", 5.0)
    return True


def reset_faction_on_return(world: World, eid: int):
    """When a combat entity returns home, reset disposition."""
    faction = world.get(eid, Faction)
    if faction and faction.disposition != faction.home_disposition:
        faction.disposition = faction.home_disposition
