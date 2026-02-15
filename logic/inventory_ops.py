"""logic/inventory_ops.py — Canonical inventory item operations.

Centralises the "find best consumable → consume → apply effect"
pattern that was previously copy-pasted across 5+ locations:
  - logic/needs.py  (npc_eat_from_inventory, _npc_eat_communal)
  - logic/ai/defense.py  (try_heal)
  - simulation/communal_meals.py  (_try_communal_container)
  - simulation/events.py  (_try_eat_from_stockpile)

Public API
----------
``consume_item``           — decrement item count, delete if zero
``find_best_consumable``   — scan inventory for highest-value consumable
``is_food_item``           — unified food-keyword matching
``consume_best_food``      — find + consume + restore hunger
``consume_best_heal``      — find + consume + restore health
"""

from __future__ import annotations
from typing import Any

# ── Shared food keywords (consistent across all systems) ─────────────

FOOD_KEYWORDS = frozenset({"food", "stew", "ration", "beans", "meat", "dried"})
"""Words that indicate an item is edible when no ItemRegistry is available."""


def is_food_item(item_id: str) -> bool:
    """Return True if *item_id* looks like food (keyword match fallback)."""
    low = item_id.lower()
    return any(kw in low for kw in FOOD_KEYWORDS)


# ── Core inventory mutation ──────────────────────────────────────────

def consume_item(inv, item_id: str, count: int = 1) -> bool:
    """Decrement *item_id* in *inv.items* by *count*.  Delete if zero.

    Returns True if the item was available and consumed.
    """
    qty = inv.items.get(item_id, 0)
    if qty < count:
        return False
    inv.items[item_id] = qty - count
    if inv.items[item_id] <= 0:
        del inv.items[item_id]
    return True


# ── Best-consumable query ────────────────────────────────────────────

def find_best_consumable(inv, registry, field: str = "food_value",
                         fallback_value: float = 25.0,
                         ) -> tuple[str | None, float]:
    """Return ``(item_id, value)`` of the best consumable by *field*.

    If *registry* is None, falls back to keyword matching with
    ``FOOD_KEYWORDS`` (for food) or returns (None, 0.0).
    """
    best_id: str | None = None
    best_val = 0.0

    if registry is None:
        # Keyword fallback (only meaningful for food)
        if field == "food_value":
            for item_id, qty in inv.items.items():
                if qty <= 0:
                    continue
                if is_food_item(item_id):
                    if fallback_value > best_val:
                        best_val = fallback_value
                        best_id = item_id
        return best_id, best_val

    for item_id, qty in inv.items.items():
        if qty <= 0:
            continue
        if registry.item_type(item_id) != "consumable":
            continue
        val = registry.get_field(item_id, field, 0.0)
        if val > best_val:
            best_val = val
            best_id = item_id

    return best_id, best_val


# ── Compound helpers ─────────────────────────────────────────────────

def consume_best_food(world: Any, eid: int) -> bool:
    """Find + consume the best food item from entity's inventory.

    Restores hunger and optionally heals.  Returns True if NPC ate.
    This is the canonical "eat from own inventory" used by all systems.
    """
    from components import Hunger, Health, Inventory, ItemRegistry, Identity
    from logic.faction_ops import entity_display_name

    hunger = world.get(eid, Hunger)
    inv = world.get(eid, Inventory)
    if hunger is None or inv is None:
        return False

    registry = world.res(ItemRegistry)
    best_id, best_food = find_best_consumable(inv, registry, "food_value")
    if best_id is None:
        return False

    # Consume
    consume_item(inv, best_id)
    hunger.current = min(hunger.maximum, hunger.current + best_food)

    # Bonus heal if the item has a heal value
    if registry:
        heal = registry.get_field(best_id, "heal", 0.0)
        if heal > 0:
            health = world.get(eid, Health)
            if health:
                health.current = min(health.maximum, health.current + heal)

    name = entity_display_name(world, eid)
    food_name = registry.display_name(best_id) if registry else best_id
    print(f"[NEEDS] {name} ate {food_name} (+{best_food:.0f} hunger)")
    return True


def consume_best_heal(world: Any, eid: int) -> tuple[str | None, float]:
    """Find + consume the best healing item from inventory.

    Returns ``(item_id, heal_amount)`` or ``(None, 0.0)`` if nothing
    was consumed.
    """
    from components import Health, Inventory, ItemRegistry

    inv = world.get(eid, Inventory)
    if inv is None:
        return None, 0.0

    registry = world.res(ItemRegistry)
    if registry is None:
        return None, 0.0

    best_id, best_heal = find_best_consumable(inv, registry, "heal")
    if best_id is None:
        return None, 0.0

    consume_item(inv, best_id)

    health = world.get(eid, Health)
    if health:
        health.current = min(health.maximum, health.current + best_heal)

    return best_id, best_heal


def consume_from_container(container_inv, hunger, registry,
                           *, heal_health=None) -> bool:
    """Eat best food from a container inventory.

    Shared by both high-LOD ``_npc_eat_communal`` and low-LOD
    ``_try_communal_container``.  Returns True if food was consumed.

    ``heal_health``: if a Health component is provided, also apply
    any heal value on the consumed item.
    """
    best_id, best_food = find_best_consumable(container_inv, registry,
                                               "food_value")
    if best_id is None:
        return False

    consume_item(container_inv, best_id)
    hunger.current = min(hunger.maximum, hunger.current + best_food)

    if heal_health and registry:
        heal = registry.get_field(best_id, "heal", 0.0)
        if heal > 0:
            heal_health.current = min(heal_health.maximum,
                                      heal_health.current + heal)
    return True
