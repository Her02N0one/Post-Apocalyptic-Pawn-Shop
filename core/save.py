"""core/save.py — Game state persistence (separate from zone templates).

Save files (JSON) store only runtime state:
- Player position, inventory, health, hunger
- Entity positions and state (high-LOD living entities or low-LOD task data)
- Container state (which loot has been scavenged)
- Flags, quests, etc.

Zone files (NBT) store only static template data:
- Tile layout
- Entity spawn definitions (not their runtime state)
- Loot table specs
- Points of interest
- Anchors

When loading a game:
1. Load zone NBT (static template)
2. Load save JSON (runtime state overlay)
3. Merge: spawn entities from NBT, then override positions/state from save
"""

from __future__ import annotations
import json
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from core.app import App


SAVES_DIR = Path("saves")


def get_save_file(slot: int = 0) -> Path:
    """Get the path for a save slot."""
    SAVES_DIR.mkdir(parents=True, exist_ok=True)
    return SAVES_DIR / f"slot{slot}.json"


def _save_entity_common(world, eid: int, ent_data: dict[str, Any]) -> None:
    """Append shared fields (identity, health, hunger, inventory) to ent_data."""
    from components import Identity, Health, Hunger, Inventory, Equipment, Lod
    from components import Task

    if world.has(eid, Identity):
        ident = world.get(eid, Identity)
        ent_data["name"] = ident.name
        ent_data["kind"] = ident.kind

    lod_level = "low"
    if world.has(eid, Lod):
        lod_level = world.get(eid, Lod).level
    ent_data["lod"] = lod_level

    if world.has(eid, Health):
        h = world.get(eid, Health)
        ent_data["health"] = {"current": float(h.current), "maximum": float(h.maximum)}
    if world.has(eid, Hunger):
        hu = world.get(eid, Hunger)
        ent_data["hunger"] = {"current": float(hu.current), "rate": float(hu.rate)}
    if world.has(eid, Inventory):
        inv = world.get(eid, Inventory)
        if inv.items:
            ent_data["inventory"] = dict(inv.items)
    if world.has(eid, Equipment):
        eq = world.get(eid, Equipment)
        ent_data["equipment"] = {"weapon": eq.weapon, "armor": eq.armor}
    if lod_level == "low" and world.has(eid, Task):
        task = world.get(eid, Task)
        ent_data["task"] = {"type": task.type, "progress": float(task.progress)}
    # Save crime record (player only)
    from components.social import CrimeRecord, Locked
    if world.has(eid, CrimeRecord):
        cr = world.get(eid, CrimeRecord)
        ent_data["crime_record"] = {
            "offenses": dict(cr.offenses),
            "total_witnessed": cr.total_witnessed,
            "decay_timer": float(cr.decay_timer),
        }
    # Save lock state (containers)
    if world.has(eid, Locked):
        lock = world.get(eid, Locked)
        ent_data["locked"] = {
            "faction_access": lock.faction_access,
            "difficulty": lock.difficulty,
        }


def save_game_state(app: "App", slot: int = 0) -> Path:
    """Save current game state (not zone template).
    
    Saves:
    - Player position, inventory, resources
    - All entities (position, health, hunger, state)
    - Zone state (opened containers, flags, etc.)
    - Metadata (timestamp, playtime)
    
    Returns path to save file.
    """
    from components import (
        Position, Inventory, Health, Hunger, Identity,
        Player, Lod, Equipment,
        SubzonePos, Home, WorldMemory,
    )
    
    from components import Task
    
    save_path = get_save_file(slot)
    
    # Build player data
    player_data = None
    res = app.world.query_one(Player, Position)
    if res:
        _, _, pos = res
        player_data = {
            "zone": pos.zone,
            "x": float(pos.x),
            "y": float(pos.y),
        }
        # Add inventory if exists
        inv_res = app.world.query_one(Player, Inventory)
        if inv_res:
            _, _, inv = inv_res
            if inv.items:
                player_data["inventory"] = dict(inv.items)
        # Add equipment if exists
        eq_res = app.world.query_one(Player, Equipment)
        if eq_res:
            _, _, eq = eq_res
            player_data["equipment"] = {"weapon": eq.weapon, "armor": eq.armor}
        # Add health/hunger
        health_res = app.world.query_one(Player, Health)
        if health_res:
            _, _, health = health_res
            player_data["health"] = {"current": float(health.current), "maximum": float(health.maximum)}
        hunger_res = app.world.query_one(Player, Hunger)
        if hunger_res:
            _, _, hunger = hunger_res
            player_data["hunger"] = {"current": float(hunger.current), "rate": float(hunger.rate)}
    
    # Build entity data (for non-player entities)
    entities_data = {}
    # Collect all entities that have Position OR SubzonePos
    seen_eids: set[int] = set()

    for eid, pos in app.world.all_of(Position):
        if app.world.has(eid, Player):
            continue  # Skip player, already saved above
        seen_eids.add(eid)
        
        ent_data: dict[str, Any] = {
            "zone": pos.zone,
            "x": float(pos.x),
            "y": float(pos.y),
            "sim_mode": "high",
        }
        _save_entity_common(app.world, eid, ent_data)
        entities_data[str(eid)] = ent_data

    # Low-LOD entities (have SubzonePos but NOT Position)
    for eid, sp in app.world.all_of(SubzonePos):
        if eid in seen_eids or app.world.has(eid, Player):
            continue
        seen_eids.add(eid)
        ent_data = {
            "sim_mode": "low",
            "subzone_pos": {"zone": sp.zone, "subzone": sp.subzone},
        }
        _save_entity_common(app.world, eid, ent_data)
        # Home
        if app.world.has(eid, Home):
            h = app.world.get(eid, Home)
            ent_data["home"] = {"zone": h.zone, "subzone": h.subzone}
        # WorldMemory
        if app.world.has(eid, WorldMemory):
            wm = app.world.get(eid, WorldMemory)
            ent_data["world_memory"] = [
                {"key": e.key, "data": e.data, "timestamp": e.timestamp, "ttl": e.ttl}
                for e in wm.entries.values()
            ]
        entities_data[str(eid)] = ent_data
    
    # Build zone state (container flags, etc.)
    zone_state = {}
    # Placeholder: can expand this to track which containers have been opened
    # For now, just store basic per-zone data
    
    # Scheduler event queue
    scheduler_data: list[dict] = []
    try:
        from simulation.world_sim import WorldSim
        # Grab the live WorldSim from the active scene
        scene = app._scenes[-1] if app._scenes else None
        if scene and hasattr(scene, "world_sim") and scene.world_sim:
            scheduler_data = scene.world_sim.scheduler.to_list()
    except Exception:
        pass  # simulation package not available

    save_data = {
        "format_version": 2,
        "player": player_data,
        "entities": entities_data,
        "zone_state": zone_state,
        "scheduler_queue": scheduler_data,
    }
    
    with open(save_path, 'w') as f:
        json.dump(save_data, f, indent=2)
    
    return save_path


def load_game_state(app: "App" | None = None, slot: int = 0) -> dict[str, Any] | None:
    """Load game state from save file.
    
    Args:
        app: App instance (optional, not used for file load)
        slot: Save slot number (default 0)
    
    Returns dict with keys: player, entities, zone_state.
    Returns None if save file doesn't exist.
    
    Caller is responsible for:
    1. Loading the zone template (NBT)
    2. Calling this function to get saved state
    3. Merging them (update entity positions from save, spawn any missing from template)
    """
    save_path = get_save_file(slot)
    if not save_path.exists():
        return None
    
    try:
        with open(save_path, 'r') as f:
            data = json.load(f)
        return data
    except Exception as ex:
        print(f"[SAVE] Error loading save file: {ex}")
        return None
