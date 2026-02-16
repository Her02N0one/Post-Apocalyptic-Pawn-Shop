"""systems/scheduling/scheduled_activities.py — Data-driven recurring activities.

A ``ScheduledActivity`` defines a recurring communal event:

- **When**: times of day (game-minutes) that the activity fires
- **Where**: the subzone node entities gather at
- **Who**: faction/role filter
- **What**: a callback invoked when the entity arrives at the node
- **Duration**: how long the activity takes before returning to duties

The communal mealtime is the first (and currently only) activity
built on this system.  Future activities — training drills, shift
changes, communal prayer, marketplace hours — plug into the same
scaffolding by adding another ``ScheduledActivity`` entry and
registering it.

Public API
----------
``ScheduledActivity``       — dataclass defining a recurring activity
``COMMUNAL_MEAL``           — the meal activity definition
``handle_activity``         — generic handler for activity events
``schedule_activities``     — bootstrap first round of activity events
``register_activity``       — register an activity on the scheduler
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable

from components import Health, Hunger, Inventory, Identity, ItemRegistry, Faction
from components.offscreen import SubzonePos
from core.subzone import SubzoneGraph
from systems.social.faction_disposition import entity_display_name


# ── Activity definition ──────────────────────────────────────────────

@dataclass
class ScheduledActivity:
    """A recurring communal activity definition.

    Parameters
    ----------
    name : str
        Human-readable name (for logging).
    event_type : str
        Scheduler event type string (e.g. ``"COMMUNAL_MEAL"``).
    gathering_node : str
        Subzone node where entities gather.
    times : list[float]
        Times of day (game-minutes, 0–1440) when the activity fires.
    duration : float
        How long (game-minutes) the activity takes at the node.
    day_length : float
        Length of a game day in game-minutes.
    group_filter : str
        Only entities whose ``Faction.group`` matches participate.
    delay_check : Callable[[Any, int], bool] | None
        If provided, entities for which this returns True get a
        delayed start (e.g. guards eat after civilians).
    delay_amount : float
        Extra game-minutes added for delayed entities.
    on_arrive : Callable | None
        ``on_arrive(world, eid, scheduler, game_time, current_node)``
        Called when the entity reaches the gathering node.  If None,
        the entity simply waits ``duration`` minutes and returns.
    on_fallback : Callable | None
        ``on_fallback(world, eid, scheduler, game_time, current_node)``
        Called when the entity can't reach the gathering node.
    """
    name: str
    event_type: str
    gathering_node: str
    times: list[float]
    duration: float = 10.0
    day_length: float = 300.0   # default = core.constants.DAY_LENGTH (real seconds)
    group_filter: str = ""
    delay_check: Callable[[Any, int], bool] | None = None
    delay_amount: float = 0.0
    on_arrive: Callable | None = None
    on_fallback: Callable | None = None


# ── Generic handler ──────────────────────────────────────────────────

def handle_activity(activity: ScheduledActivity, world: Any, eid: int,
                    event_type: str, data: dict, scheduler: Any,
                    game_time: float,
                    graph: SubzoneGraph | None = None) -> None:
    """Generic handler for a scheduled activity event.

    1. Validate entity is alive and eligible.
    2. If already at the gathering node → run ``on_arrive`` callback.
    3. Otherwise → plan route and travel there, re-fire on arrival.
    4. If unreachable → run ``on_fallback`` callback.
    """
    if not world.alive(eid):
        return

    szp = world.get(eid, SubzonePos)
    if szp is None:
        return

    # Eligibility check
    if activity.group_filter:
        faction = world.get(eid, Faction)
        if not faction or faction.group != activity.group_filter:
            return

    current_node = szp.subzone

    # Already at gathering point → activity callback
    if current_node == activity.gathering_node:
        _run_activity(activity, world, eid, scheduler,
                      game_time, current_node)
        return

    # Navigate to gathering point
    if graph:
        from systems.offscreen.travel import plan_route, begin_travel

        route = plan_route(graph, current_node, activity.gathering_node)
        if route:
            begin_travel(world, eid, route, graph, scheduler, game_time)
            eta = graph.total_path_time(route.path, current_node)
            scheduler.post(
                time=game_time + eta + 0.1,
                eid=eid,
                event_type=activity.event_type,
                data={"phase": "arrive"},
            )
            _log(activity, world, eid, f"heading to {activity.name}")
            return

    # Can't reach gathering point — fallback
    if activity.on_fallback:
        activity.on_fallback(world, eid, scheduler, game_time,
                             current_node)
    _post_return(activity, scheduler, eid, current_node, game_time)


def _run_activity(activity: ScheduledActivity, world, eid,
                  scheduler, game_time, current_node):
    """Execute the activity at the gathering node."""
    if activity.on_arrive:
        activity.on_arrive(world, eid, scheduler, game_time,
                           current_node)

    _log(activity, world, eid, f"finished {activity.name}")

    # Schedule next occurrence for this entity
    is_delayed = (activity.delay_check is not None
                  and activity.delay_check(world, eid))
    _schedule_next_for(activity, scheduler, eid, game_time, is_delayed)

    # Return to duties after activity duration
    _post_return(activity, scheduler, eid, current_node, game_time)


def _post_return(activity, scheduler, eid, node, game_time):
    """Post a DECISION_CYCLE after the activity finishes."""
    scheduler.post(game_time + activity.duration, eid,
                   "DECISION_CYCLE", {"node": node})


# ── Scheduling helpers ───────────────────────────────────────────────

def next_occurrence(activity: ScheduledActivity,
                    game_time: float) -> float:
    """Return the absolute game_time of the next activity occurrence."""
    time_in_day = game_time % activity.day_length
    for t in activity.times:
        if t > time_in_day + 1.0:
            return game_time + (t - time_in_day)
    # Wrap to next day
    return game_time + (activity.day_length - time_in_day) + activity.times[0]


def _schedule_next_for(activity, scheduler, eid, game_time, is_delayed):
    """Schedule the next activity event for a single entity."""
    nxt = next_occurrence(activity, game_time)
    delay = activity.delay_amount if is_delayed else 0.0
    scheduler.post(nxt + delay, eid, activity.event_type, {})


def _iter_eligible(activity, world):
    """Yield entity IDs eligible for an activity regardless of LOD state.

    Uses Faction.group (which persists across LOD transitions) instead
    of SubzonePos, so entities promoted to high-LOD aren't skipped.
    When the scheduler fires the event, the handler already guards
    against high-LOD entities — the important thing is that they stay
    *in the schedule* so they don't drift out of the cycle.
    """
    if activity.group_filter:
        for eid, faction in world.all_of(Faction):
            if faction.group == activity.group_filter and world.alive(eid):
                yield eid
    else:
        # No group filter — all entities with SubzonePos (backward compat)
        for eid, _szp in world.all_of(SubzonePos):
            if world.alive(eid):
                yield eid


def schedule_activities(activity: ScheduledActivity, world: Any,
                        scheduler: Any, game_time: float) -> int:
    """Bootstrap: schedule the first round of activity events.

    Finds all eligible entities (matching group filter, any LOD)
    and posts the next occurrence of the activity for each.

    Returns the count of events scheduled.
    """
    # Find next occurrence (bootstrap — use looser +0 threshold)
    time_in_day = game_time % activity.day_length
    nxt = None
    for t in activity.times:
        if t > time_in_day:
            nxt = game_time + (t - time_in_day)
            break
    if nxt is None:
        nxt = (game_time + (activity.day_length - time_in_day)
               + activity.times[0])

    count = 0
    for eid in _iter_eligible(activity, world):
        is_delayed = (activity.delay_check is not None
                      and activity.delay_check(world, eid))
        delay = activity.delay_amount if is_delayed else 0.0
        scheduler.post(nxt + delay, eid, activity.event_type, {})
        count += 1

    # Also schedule the next-next occurrence so the cycle continues
    _schedule_recurring(activity, world, scheduler, nxt)

    return count


def _schedule_recurring(activity, world, scheduler, last_time):
    """Post the next recurring batch after *last_time*.

    Scans by Faction group (not SubzonePos) so entities that spent
    time in high-LOD stay in the schedule when they return to low-LOD.
    """
    nxt = next_occurrence(activity, last_time)
    for eid in _iter_eligible(activity, world):
        is_delayed = (activity.delay_check is not None
                      and activity.delay_check(world, eid))
        delay = activity.delay_amount if is_delayed else 0.0
        scheduler.post(nxt + delay, eid, activity.event_type, {})


def register_activity(activity: ScheduledActivity, scheduler: Any,
                      graph: SubzoneGraph | None = None) -> None:
    """Register the activity's event handler on the scheduler."""
    scheduler.register_handler(
        activity.event_type,
        lambda w, e, et, d, s, gt, a=activity, g=graph:
            handle_activity(a, w, e, et, d, s, gt, graph=g),
    )


# ── Logging helper ───────────────────────────────────────────────────

def _log(activity, world, eid, msg):
    from components.dev_log import log_event
    name = entity_display_name(world, eid)
    log_event(world, eid, "schedule", msg, name=name)
