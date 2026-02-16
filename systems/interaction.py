"""systems/interaction.py — Nearby-entity interaction.

When the player presses the interact key, find the closest entity
within range in the direction they're facing and emit an
``InteractionEvent``.

    from systems.interaction import try_interact
    try_interact(world, bus)   # called on key press
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from components import Position, Player, Facing, Identity, Collider
from core.types import Direction

if TYPE_CHECKING:
    from core.ecs import World
    from core.events import EventBus

# How far (tiles) the player can reach
INTERACT_RANGE = 1.8


def _facing_offset(d: Direction) -> tuple[float, float]:
    """Return a unit-ish offset vector for the given facing."""
    return {
        Direction.UP:    ( 0.0, -1.0),
        Direction.DOWN:  ( 0.0,  1.0),
        Direction.LEFT:  (-1.0,  0.0),
        Direction.RIGHT: ( 1.0,  0.0),
    }[d]


def nearest_interactable(world: "World") -> tuple[int, float] | None:
    """Find the nearest interactable entity in front of the player.

    Returns ``(entity_id, distance)`` or ``None``.
    """
    result = world.query_one(Player, Position, Facing)
    if result is None:
        return None
    p_eid, _, p_pos, p_face = result

    fdx, fdy = _facing_offset(p_face.direction)

    best_eid: int | None = None
    best_dist = INTERACT_RANGE + 1.0

    for eid, pos, ident in world.query(Position, Identity):
        if eid == p_eid:
            continue
        if pos.zone != p_pos.zone:
            continue

        dx = pos.x - p_pos.x
        dy = pos.y - p_pos.y
        dist = math.hypot(dx, dy)

        if dist > INTERACT_RANGE:
            continue

        # Prefer entities in the direction the player faces
        if dist > 0.01:
            dot = (dx * fdx + dy * fdy) / dist
        else:
            dot = 1.0  # Standing on top — always valid

        # Must be at least vaguely in front (dot > -0.3 allows some leniency)
        if dot < -0.3:
            continue

        # Weight: closer + more aligned = better
        score = dist - dot * 0.5
        if score < best_dist:
            best_dist = score
            best_eid = eid

    if best_eid is not None:
        return (best_eid, best_dist)
    return None


def try_interact(world: "World", bus: "EventBus") -> bool:
    """Attempt an interaction.  Returns True if one was emitted."""
    from core.events import InteractionEvent

    result = world.query_one(Player, Position)
    if result is None:
        return False

    p_eid = result[0]
    found = nearest_interactable(world)
    if found is None:
        return False

    target_eid, _ = found
    bus.emit(InteractionEvent(player=p_eid, target=target_eid))
    return True
