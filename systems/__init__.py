"""systems — All game mechanics, on-screen and off-screen.

On-screen systems run every frame via engine/tick.py.  Off-screen
systems run on an event queue via the offscreen/ subpackage.  The seam
between the two modes is offscreen/lod.py.

Subpackages
-----------
engine/       — frame pipeline (tick), input, entity spawning, particle VFX
movement/     — physics / collision, A* pathfinding
combat/       — engagement FSM, damage, targeting, projectiles, movement
                + offscreen.py (stat-check combat for off-screen encounters)
ai/           — brain registry, perception, steering, defense, wander, villager
                + offscreen.py (off-screen AI decision cycle)
actions/      — player action handlers (attacks, interact, inventory)
offscreen/    — off-screen world simulation (scheduler, LOD, travel, checkpoints)
items/        — inventory consumption, loot tables
social/       — settlements, crime & law, dialogue trees, faction disposition
scheduling/   — NPC needs, scheduled activities, communal meals
"""
