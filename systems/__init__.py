"""systems — All game mechanics, on-screen and off-screen.

On-screen systems run every frame via tick.py.  Off-screen systems
run on an event queue via scheduler.py + event_dispatch.py.  The seam
between the two modes is lod_transition.py.

Subpackages
-----------
combat/     — engagement FSM, damage, targeting, projectiles, movement
              + offscreen.py (stat-check combat for off-screen encounters)
ai/         — brain registry, perception, steering, defense, wander, villager
              + offscreen.py (off-screen AI decision cycle)
actions/    — player action handlers (attacks, interact, inventory)

Per-frame modules
-----------------
tick             — per-frame system orchestrator (+ input & pickup systems)
physics          — physics / collision
pathfinding      — A* navigation
needs            — NPC hunger & eating
input_manager    — raw input → intent mapping
particles        — VFX particle simulation
crime            — crime & law system
dialogue         — dialogue trees + quest tracking

Off-screen scheduling
---------------------
scheduler        — WorldScheduler event priority queue
event_dispatch   — event resolution handlers for the scheduler
lod_transition   — LOD promotion / demotion + per-frame LOD sweep
world_sim        — top-level simulation manager
travel           — route planning through the subzone graph
node_arrival     — checkpoint evaluation at subzone arrivals
economy          — village economic loop (farming, stockpiles, food production)
scheduled_activities — generic data-driven recurring communal events
communal_meals   — meal activity configuration

Other
-----
entity_factory   — entity creation from TOML data
loot_tables      — loot table manager
lod              — backward-compat re-export (see lod_transition)
"""
