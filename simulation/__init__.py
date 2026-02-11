"""simulation — Off-screen persistent world simulation.

This package implements the event-driven world scheduler that runs
all entities not currently visible to the player.  Every NPC exists
persistently, eats, sleeps, travels, fights, and dies under the same
rules regardless of distance from the player.

Submodules
----------
subzone         SubzoneNode, SubzoneGraph — world topology
scheduler       WorldScheduler — event priority queue
events          Event resolution functions (ARRIVE_NODE, HUNGER_CRITICAL, etc.)
travel          Route planning through the subzone graph
checkpoint      Checkpoint evaluation at subzone arrivals
stat_combat     Stat-check combat resolution for off-screen encounters
lod_transition  LOD promotion / demotion when the player moves zones
decision        One-shot AI decision cycle (priority stack)
economy         Village economic loop (farming, stockpiles, trade)
"""
