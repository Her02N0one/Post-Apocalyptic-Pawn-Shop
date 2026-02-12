"""
main.py — Bootstrap

1. Create the app
2. Register component types with the data loader
3. Load data files → entities
4. Create the player
5. Push the starting scene
6. Run
"""

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    import tomli as tomllib
from pathlib import Path
from core.app import App
from core.data import DataLoader
from components import (
    Position, Velocity, Sprite, Identity,
    Health, Hunger, Inventory, Meta, Brain, Patrol, Threat, AttackConfig,
    Player, Camera, Collider, ZoneMetadata, Combat, Loot, HitFlash, LootTableRef,
    Facing, Hurtbox, Equipment,
)
from logic.loot_tables import LootTableManager
from logic.particles import ParticleManager
from logic.entity_factory import spawn_from_descriptor
from scenes.world_scene import WorldScene
from core import zone as core_zone
from core.save import load_game_state

def main():
    app = App(title="Shopkeeper", width=960, height=640)

    # -- Register components the data loader knows about --
    loader = DataLoader(app.world)
    loader.register("position", Position)
    loader.register("velocity", Velocity)
    loader.register("sprite", Sprite)
    loader.register("identity", Identity)
    loader.register("meta", Meta)
    loader.register("brain", Brain)
    loader.register("patrol", Patrol)
    loader.register("threat", Threat)
    loader.register("attack_config", AttackConfig)
    loader.register("health", Health)
    loader.register("hunger", Hunger)
    loader.register("inventory", Inventory)
    loader.register("collider", Collider)
    loader.register("combat", Combat)
    loader.register("loot", Loot)
    loader.register("hitflash", HitFlash)
    loader.register("loot_table_ref", LootTableRef)

    # -- Load game data --
    loader.load_items("data/items.toml")
    # NPCs / character data currently disabled: loader.load("data/characters.toml")

    # -- Load loot tables as a world resource --
    loot_mgr = LootTableManager.from_file("data/loot_tables.toml")
    app.world.set_res(loot_mgr)

    # -- Create player --
    player = app.world.spawn()
    DEFAULT_ZONE = "settlement"

    # -- Load zones from disk (must happen before scene creation) --
    core_zone.load_zones_from_disk()
    core_zone.load_portals()

    # -- Zone Resolution Strategy --
    # 1. Check if the zone was loaded from disk.
    # 2. If yes, use its dimensions for metadata.
    # 3. If no, create a default 50x50 map in memory and start in editor mode.

    start_zone = DEFAULT_ZONE  # Track which zone to start in
    
    if DEFAULT_ZONE in core_zone.ZONE_MAPS:
        # Scenario A: Zone loaded from NBT
        tiles = core_zone.ZONE_MAPS[DEFAULT_ZONE]
        editor_mode = False
        
        # Restore player from save file if present
        save_data = load_game_state()
        if save_data and save_data.get('player'):
            player_data = save_data['player']
            # Use the saved zone if it exists and is loaded
            saved_zone = player_data.get('zone', DEFAULT_ZONE)
            if saved_zone in core_zone.ZONE_MAPS:
                start_zone = saved_zone
            app.world.add(player, Position(
                x=float(player_data.get('x', 25.0)),
                y=float(player_data.get('y', 25.0)),
                zone=saved_zone
            ))
            app.world.zone_add(player, saved_zone)
            # Restore inventory
            saved_inv = player_data.get('inventory')
            if saved_inv:
                app.world.add(player, Inventory(items=dict(saved_inv)))
            # Restore equipment
            saved_eq = player_data.get('equipment')
            if saved_eq:
                app.world.add(player, Equipment(
                    weapon=saved_eq.get('weapon', ''),
                    armor=saved_eq.get('armor', ''),
                ))
            # Restore crime record
            saved_cr = player_data.get('crime_record')
            if saved_cr:
                from components.social import CrimeRecord
                cr = CrimeRecord(
                    offenses=dict(saved_cr.get('offenses', {})),
                    total_witnessed=saved_cr.get('total_witnessed', 0),
                    decay_timer=saved_cr.get('decay_timer', 0.0),
                )
                app.world.add(player, cr)
        else:
            # No save, use zone anchor
            anchor = core_zone.ZONE_ANCHORS.get(DEFAULT_ZONE, (15.0, 15.0))
            app.world.add(player, Position(x=anchor[0], y=anchor[1], zone=DEFAULT_ZONE))
            app.world.zone_add(player, DEFAULT_ZONE)

    else:
        # Scenario B: No zone found (Fresh install)
        # Create default 50x50 grass field
        tiles = [[1] * 50 for _ in range(50)]
        core_zone.ZONE_MAPS[DEFAULT_ZONE] = tiles
        core_zone.ZONE_ANCHORS[DEFAULT_ZONE] = (25.0, 25.0)
        
        # Start in editor mode at 0,0
        editor_mode = True
        app.world.add(player, Position(x=0.0, y=0.0, zone=DEFAULT_ZONE))
        app.world.zone_add(player, DEFAULT_ZONE)

    # -- Common Player Setup --
    app.world.add(player, Velocity())
    app.world.add(player, Sprite(char="@", color=(255, 255, 100), layer=10))
    app.world.add(player, Identity(name="You", kind="player"))
    app.world.add(player, Health())
    app.world.add(player, Hunger(current=80.0, maximum=100.0, rate=0.5))
    if not app.world.has(player, Inventory):
        app.world.add(player, Inventory())
    app.world.add(player, Combat(damage=5.0, defense=0.0))  # Unarmed base stats
    app.world.add(player, Player(speed=6.0))
    if not app.world.has(player, Equipment):
        app.world.add(player, Equipment())   # weapon / armor slots
    app.world.add(player, Facing(direction="down"))
    app.world.add(player, Hurtbox(ox=0.0, oy=0.0, w=0.8, h=0.8))

    # -- Resources --
    app.world.set_res(Camera())
    app.world.set_res(ParticleManager())

    # -- Register Zone Metadata --
    # Crucial: Must use dimensions of the *actual* tiles we resolved above
    width = len(tiles[0]) if tiles else 0
    height = len(tiles)
    app.world.set_res(ZoneMetadata(name=DEFAULT_ZONE, width=width, height=height, chunk_size=8))

    # -- Spawn NPCs and containers from characters.toml --
    _spawn_characters(app)

    # -- Start --
    app.push_scene(WorldScene(editor_mode=editor_mode, zone_name=start_zone))
    app.run()


def _spawn_characters(app: App) -> None:
    """Load data/characters.toml and spawn each entry via entity_factory."""
    char_path = Path("data/characters.toml")
    if not char_path.exists():
        return
    with open(char_path, "rb") as f:
        data = tomllib.load(f)

    from components.simulation import SubzonePos
    count = 0
    container_ids: dict[str, list[int]] = {}   # subzone → [eid, ...]

    for char_id, desc in data.items():
        if not isinstance(desc, dict):
            continue
        # Determine the zone for this entity
        zone = "settlement"
        if "subzone_pos" in desc and isinstance(desc["subzone_pos"], dict):
            zone = desc["subzone_pos"].get("zone", zone)
        elif "meta" in desc and isinstance(desc["meta"], dict):
            zone = desc["meta"].get("zone", zone)

        eid = spawn_from_descriptor(app.world, desc, zone)
        count += 1

        # Track containers so we can register them on subzone nodes
        ident = app.world.get(eid, Identity)
        if ident and ident.kind == "container":
            szp = app.world.get(eid, SubzonePos)
            if szp:
                container_ids.setdefault(szp.subzone, []).append(eid)

    # Attach container EIDs to the subzone graph nodes
    # (done later when WorldSim loads the graph; store on world as a resource for now)
    if container_ids:
        app.world.set_res(_ContainerMap(container_ids))

    print(f"[MAIN] Spawned {count} characters/containers from characters.toml")


class _ContainerMap:
    """Temporary resource holding subzone → container EID mapping."""
    def __init__(self, mapping: dict[str, list[int]]):
        self.mapping = mapping


if __name__ == "__main__":
    main()