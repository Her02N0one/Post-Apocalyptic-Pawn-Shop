"""systems.items — Item generation, consumption, and inventory helpers.

Modules
-------
inventory_consume  — canonical item consumption helpers (eat, heal, etc.)
loot_tables        — weighted loot table manager
"""

from .inventory_consume import (                                # noqa: F401
    is_food_item,
    consume_item,
    find_best_consumable,
    consume_best_food,
    consume_best_heal,
    consume_from_container,
    eat_from_stockpile,
    npc_try_eat_any,
    eat_from_nearby_container,
)
from .loot_tables import LootTableManager                      # noqa: F401
