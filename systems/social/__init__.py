"""systems.social — Crime, dialogue, faction disposition, and settlements.

Modules
-------
crime                — witness-based crime detection and reputation
dialogue             — dialogue trees and quest tracking
faction_disposition  — faction mutation helpers (hostile, flee, guard checks)
settlement           — village creation, stockpile management, food production
"""

from .crime import (                                            # noqa: F401
    find_witnesses,
    report_theft,
    make_theft_callback,
    make_lockpick_callback,
    npc_knows_crimes,
    guard_crime_reaction,
)
from .dialogue import (                                         # noqa: F401
    QuestLog,
    DialogueManager,
    load_builtin_trees,
)
from .faction_disposition import (                              # noqa: F401
    is_guard,
    entity_display_name,
    make_hostile,
    make_flee,
    activate_hostile_or_flee,
)
from .settlement import (                                       # noqa: F401
    create_settlement,
    get_settlement_stockpile,
    settlement_needs,
    deposit_to_stockpile,
    withdraw_from_stockpile,
    tick_settlement_economy,
    add_to_stockpile,
    settlement_food_production,
)
