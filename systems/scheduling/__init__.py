"""systems.scheduling — NPC needs, scheduled activities, and communal meals.

Modules
-------
needs                — hunger drain, starvation damage, need-priority evaluation
scheduled_activities — generic data-driven recurring communal events
communal_meals       — meal activity configuration and callbacks
"""

from .needs import hunger_system, auto_eat_system               # noqa: F401
from .scheduled_activities import (                             # noqa: F401
    ScheduledActivity,
    handle_activity,
    schedule_activities,
    next_occurrence,
    register_activity,
)
from .communal_meals import (                                   # noqa: F401
    handle_communal_meal,
    schedule_meal_events,
    COMMUNAL_MEAL_ACTIVITY,
    DAY_LENGTH,
    MEAL_TIMES,
    MEAL_DURATION,
    GUARD_DELAY,
    COMMUNAL_NODE,
)
