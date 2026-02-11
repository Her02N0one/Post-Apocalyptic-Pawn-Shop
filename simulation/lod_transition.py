"""simulation/lod_transition.py — LOD promotion and demotion.

Handles the transition of entities between high-LOD (real-time,
Position + Brain) and low-LOD (event-driven, SubzonePos + scheduler).

The world state must be consistent across transitions — no items
appearing or disappearing, no entities teleporting, no combat
outcomes changing.
"""

from __future__ import annotations
import random
from typing import Any

from components import (
    Position, Velocity, Health, Identity,
    Brain, Lod, Collider, Hurtbox, Facing, Player,
)
from components.simulation import SubzonePos, TravelPlan
from simulation.subzone import SubzoneGraph


# ═════════════════════════════════════════════════════════════════════
#  PROMOTION: Low → High LOD
# ═════════════════════════════════════════════════════════════════════


def promote_entity(world: Any, eid: int, graph: SubzoneGraph,
                   scheduler: Any, game_time: float) -> bool:
    """Promote an off-screen entity to high-LOD (real-time simulation).

    1. Read SubzonePos → determine tile position
    2. Cancel scheduled events
    3. Create real Position from subzone anchor
    4. Activate Brain and high-LOD components
    5. Set LOD grace period

    Returns True if promotion succeeded.
    """
    szp = world.get(eid, SubzonePos)
    if szp is None:
        return False

    node = graph.get_node(szp.subzone)
    if node is None:
        # No node data — can't promote without knowing where to place
        return False

    # 1. Determine tile position from subzone anchor
    ax, ay = node.anchor
    # Add some randomness so entities don't stack
    offset_x = random.uniform(-2.0, 2.0)
    offset_y = random.uniform(-2.0, 2.0)
    tile_x = float(ax) + offset_x
    tile_y = float(ay) + offset_y

    # Verify the position is passable
    from core.zone import is_passable
    if not is_passable(szp.zone, tile_x, tile_y):
        # Try anchor directly
        tile_x, tile_y = float(ax), float(ay)
        if not is_passable(szp.zone, tile_x, tile_y):
            # Try random spots near anchor
            from core.zone import random_passable_spot
            spot = random_passable_spot(szp.zone, float(ax), float(ay), 6.0)
            if spot:
                tile_x, tile_y = spot
            # else use anchor anyway

    # 2. Cancel all scheduled events
    scheduler.cancel_entity(eid)

    # 3. Replace SubzonePos with real Position
    zone = szp.zone
    world.remove(eid, SubzonePos)
    world.add(eid, Position(x=tile_x, y=tile_y, zone=zone))
    world.zone_add(eid, zone)

    # Ensure Velocity exists
    if not world.has(eid, Velocity):
        world.add(eid, Velocity())

    # 4. Activate Brain
    brain = world.get(eid, Brain)
    if brain:
        brain.active = True
        # Set goal based on what entity was doing
        plan = world.get(eid, TravelPlan)
        if plan and not plan.complete:
            # Was traveling — brain will navigate to destination
            brain.state["_sim_destination"] = plan.destination
            brain.state["_sim_was_traveling"] = True

    # Remove TravelPlan (high-LOD brain handles movement)
    world.remove(eid, TravelPlan)

    # 5. Set LOD level and grace period
    lod = world.get(eid, Lod)
    if lod:
        lod.level = "high"
        lod.transition_until = game_time + 0.5
    else:
        world.add(eid, Lod(level="high", transition_until=game_time + 0.5))

    # Ensure combat-relevant components exist
    if world.has(eid, Health):
        if not world.has(eid, Collider):
            world.add(eid, Collider())
        if not world.has(eid, Hurtbox):
            world.add(eid, Hurtbox())
    if not world.has(eid, Facing):
        world.add(eid, Facing())

    name = "?"
    ident = world.get(eid, Identity)
    if ident:
        name = ident.name
    print(f"[LOD] Promoted {name} (eid={eid}) to high LOD at "
          f"({tile_x:.1f}, {tile_y:.1f}) in {zone}")

    return True


# ═════════════════════════════════════════════════════════════════════
#  DEMOTION: High → Low LOD
# ═════════════════════════════════════════════════════════════════════


def demote_entity(world: Any, eid: int, graph: SubzoneGraph,
                  scheduler: Any, game_time: float) -> bool:
    """Demote a high-LOD entity to low-LOD (event-driven simulation).

    1. Determine which subzone they're in from tile position
    2. Record current state
    3. Replace Position with SubzonePos
    4. Deactivate Brain
    5. Schedule appropriate events

    Returns True if demotion succeeded.
    """
    # Don't demote the player
    if world.has(eid, Player):
        return False

    pos = world.get(eid, Position)
    if pos is None:
        return False

    # 1. Find which subzone the entity is in
    node = graph.nearest_node_to_tile(pos.zone, int(pos.x), int(pos.y))
    if node is None:
        # No subzone data for this zone — can't demote
        return False

    # 2. Preserve current state (HP, hunger, inventory already on components)
    brain = world.get(eid, Brain)
    was_fighting = False
    if brain:
        was_fighting = brain.state.get("attack_target") is not None

    # If mid-combat, resolve it immediately via stat-check
    if was_fighting:
        target_eid = brain.state.get("attack_target")
        if target_eid and world.alive(target_eid):
            from simulation.stat_combat import stat_check_combat
            result = stat_check_combat(world, eid, target_eid)
            if result.loser_eid == eid and not result.loser_fled:
                # Entity died in combat resolution
                from simulation.stat_combat import _handle_death
                _handle_death(world, eid, node.id, scheduler, game_time)
                return True

    # 3. Replace Position with SubzonePos
    zone = pos.zone
    world.remove(eid, Position)
    world.add(eid, SubzonePos(zone=zone, subzone=node.id))

    # Remove velocity (not needed in low-LOD)
    vel = world.get(eid, Velocity)
    if vel:
        vel.x = 0.0
        vel.y = 0.0

    # 4. Deactivate Brain
    if brain:
        brain.active = False
        brain.state.clear()

    # 5. Set LOD level
    lod = world.get(eid, Lod)
    if lod:
        lod.level = "low"
    else:
        world.add(eid, Lod(level="low"))

    # 6. Schedule events based on current activity
    _schedule_initial_events(world, eid, node.id, graph,
                             scheduler, game_time)

    name = "?"
    ident = world.get(eid, Identity)
    if ident:
        name = ident.name
    print(f"[LOD] Demoted {name} (eid={eid}) to low LOD at "
          f"subzone={node.id}")

    return True


# ═════════════════════════════════════════════════════════════════════
#  ZONE TRANSITION
# ═════════════════════════════════════════════════════════════════════


def on_player_enter_zone(world: Any, new_zone: str,
                         graph: SubzoneGraph, scheduler: Any,
                         game_time: float) -> tuple[int, int]:
    """Handle player entering a zone: promote relevant entities,
    demote entities in the old zone.

    Returns (promoted_count, demoted_count).
    """
    promoted = 0
    demoted = 0

    # Promote: entities with SubzonePos in the new zone
    entities_to_promote = []
    for eid, szp in world.all_of(SubzonePos):
        if szp.zone == new_zone and world.alive(eid):
            entities_to_promote.append(eid)

    for eid in entities_to_promote:
        if promote_entity(world, eid, graph, scheduler, game_time):
            promoted += 1

    # Demote: entities with Position NOT in the new zone
    # (and not the player)
    entities_to_demote = []
    for eid, pos in world.all_of(Position):
        if pos.zone != new_zone and not world.has(eid, Player):
            if world.alive(eid):
                entities_to_demote.append(eid)

    for eid in entities_to_demote:
        if demote_entity(world, eid, graph, scheduler, game_time):
            demoted += 1

    print(f"[LOD] Zone transition to {new_zone}: "
          f"promoted={promoted}, demoted={demoted}")

    return promoted, demoted


def demote_all_non_player(world: Any, graph: SubzoneGraph,
                          scheduler: Any, game_time: float) -> int:
    """Demote every non-player entity with a Position to low-LOD.

    Useful for bootstrapping: call after spawning all entities to
    move them into the event queue.
    """
    demoted = 0
    entities = []
    for eid, pos in world.all_of(Position):
        if not world.has(eid, Player) and world.alive(eid):
            entities.append(eid)

    for eid in entities:
        if demote_entity(world, eid, graph, scheduler, game_time):
            demoted += 1
    return demoted


# ═════════════════════════════════════════════════════════════════════
#  HELPERS
# ═════════════════════════════════════════════════════════════════════


def _schedule_initial_events(world: Any, eid: int, node_id: str,
                             graph: SubzoneGraph, scheduler: Any,
                             game_time: float) -> None:
    """Schedule initial events for a newly demoted entity based on
    their current state / activity.
    """
    # Schedule hunger prediction
    from simulation.events import _schedule_hunger_event
    _schedule_hunger_event(world, eid, scheduler, game_time)

    # Schedule a decision cycle
    scheduler.post(
        time=game_time + random.uniform(1.0, 5.0),
        eid=eid,
        event_type="DECISION_CYCLE",
        data={"node": node_id},
    )


def is_high_lod(world: Any, eid: int) -> bool:
    """Check if an entity is currently high-LOD.

    Used by the scheduler to skip events for entities that are
    being simulated in real-time.
    """
    lod = world.get(eid, Lod)
    if lod and lod.level == "high":
        return True
    # Also check if entity has a Position and is in the player's zone
    if world.has(eid, Position) and not world.has(eid, SubzonePos):
        return True
    return False
