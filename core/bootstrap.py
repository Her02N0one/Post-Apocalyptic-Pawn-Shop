"""core/bootstrap.py — Game bootstrap helpers.

Extracted from main.py to keep the entry point clean and readable.
Handles:
  - Component registration with the DataLoader
  - Zone resolution (NBT vs fresh install)
  - Player creation / save restoration
  - NPC + container spawning from characters.toml
"""

from __future__ import annotations

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib
from pathlib import Path
from typing import TYPE_CHECKING

from components import (
    Position, Velocity, Sprite, Identity,
    Health, Hunger, Inventory, SpawnInfo, Brain, HomeRange, Threat, AttackConfig,
    Player, Camera, Collider, ZoneMetadata, CombatStats, Loot, HitFlash,
    LootTableRef, Facing, Hurtbox, Equipment,
)
from core.data import DataLoader
from core import zone as core_zone
from core.save import load_game_state
from logic.entity_factory import spawn_from_descriptor
from logic.loot_tables import LootTableManager
from logic.particles import ParticleManager

if TYPE_CHECKING:
    from core.app import App


# ── Component registration ───────────────────────────────────────────

def register_components(loader: DataLoader) -> None:
    """Register all component types the DataLoader can deserialise."""
    loader.register("position", Position)
    loader.register("velocity", Velocity)
    loader.register("sprite", Sprite)
    loader.register("identity", Identity)
    loader.register("spawn_info", SpawnInfo)
    loader.register("brain", Brain)
    loader.register("home_range", HomeRange)
    loader.register("threat", Threat)
    loader.register("attack_config", AttackConfig)
    loader.register("health", Health)
    loader.register("hunger", Hunger)
    loader.register("inventory", Inventory)
    loader.register("collider", Collider)
    loader.register("combat_stats", CombatStats)
    loader.register("loot", Loot)
    loader.register("hitflash", HitFlash)
    loader.register("loot_table_ref", LootTableRef)


# ── Data loading ─────────────────────────────────────────────────────

def load_game_data(app: App) -> None:
    """Load TOML data files and set world resources."""
    loader = DataLoader(app.world)
    register_components(loader)
    loader.load_items("data/items.toml")

    loot_mgr = LootTableManager.from_file("data/loot_tables.toml")
    app.world.set_res(loot_mgr)


# ── Zone resolution ─────────────────────────────────────────────────

def resolve_zone(default_zone: str = "settlement"):
    """Determine starting zone and whether we need editor mode.

    Returns (tiles, start_zone, editor_mode).

    Strategy:
      1. If the zone was loaded from disk → use its tiles, normal mode.
      2. Otherwise → create a 50×50 grass field, start in editor mode.
    """
    core_zone.load_zones_from_disk()
    core_zone.load_portals()

    if default_zone in core_zone.ZONE_MAPS:
        tiles = core_zone.ZONE_MAPS[default_zone]
        return tiles, default_zone, False

    # Fresh install — generate a blank map
    tiles = [[1] * 50 for _ in range(50)]
    core_zone.ZONE_MAPS[default_zone] = tiles
    core_zone.ZONE_ANCHORS[default_zone] = (25.0, 25.0)
    return tiles, default_zone, True


# ── Player creation ──────────────────────────────────────────────────

def create_player(app: App, default_zone: str, editor_mode: bool) -> int:
    """Spawn the player entity, restoring from save if available.

    Returns (player_eid, start_zone) — start_zone may differ from
    default_zone if the save file places the player elsewhere.
    """
    player = app.world.spawn()

    start_zone = default_zone

    if not editor_mode:
        start_zone = _restore_or_place_player(
            app, player, default_zone,
        )
    else:
        app.world.add(player, Position(x=0.0, y=0.0, zone=default_zone))
        app.world.zone_add(player, default_zone)

    # Common components every player needs
    app.world.add(player, Velocity())
    app.world.add(player, Sprite(char="@", color=(255, 255, 100), layer=10))
    app.world.add(player, Identity(name="You", kind="player"))
    app.world.add(player, Health())
    app.world.add(player, Hunger(current=80.0, maximum=100.0, rate=0.5))
    if not app.world.has(player, Inventory):
        app.world.add(player, Inventory())
    app.world.add(player, CombatStats(damage=5.0, defense=0.0))
    app.world.add(player, Player(speed=6.0))
    if not app.world.has(player, Equipment):
        app.world.add(player, Equipment())
    app.world.add(player, Facing(direction="down"))
    app.world.add(player, Hurtbox(ox=0.0, oy=0.0, w=0.8, h=0.8))

    return player, start_zone


def _restore_or_place_player(app: App, player: int,
                             default_zone: str) -> str:
    """Try to restore player from save; fall back to zone anchor.

    Returns the zone the player should start in.
    """
    save_data = load_game_state()
    if save_data and save_data.get("player"):
        return _apply_save_data(app, player, save_data["player"],
                                default_zone)

    # No save — place at zone anchor
    anchor = core_zone.ZONE_ANCHORS.get(default_zone, (15.0, 15.0))
    app.world.add(player, Position(x=anchor[0], y=anchor[1],
                                   zone=default_zone))
    app.world.zone_add(player, default_zone)
    return default_zone


def _apply_save_data(app: App, player: int, player_data: dict,
                     default_zone: str) -> str:
    """Restore player state from a save-data dict. Returns start zone."""
    saved_zone = player_data.get("zone", default_zone)
    if saved_zone not in core_zone.ZONE_MAPS:
        saved_zone = default_zone

    app.world.add(player, Position(
        x=float(player_data.get("x", 25.0)),
        y=float(player_data.get("y", 25.0)),
        zone=saved_zone,
    ))
    app.world.zone_add(player, saved_zone)

    # Inventory
    saved_inv = player_data.get("inventory")
    if saved_inv:
        app.world.add(player, Inventory(items=dict(saved_inv)))

    # Equipment
    saved_eq = player_data.get("equipment")
    if saved_eq:
        app.world.add(player, Equipment(
            weapon=saved_eq.get("weapon", ""),
            armor=saved_eq.get("armor", ""),
        ))

    # Crime record
    saved_cr = player_data.get("crime_record")
    if saved_cr:
        from components.social import CrimeRecord
        cr = CrimeRecord(
            offenses=dict(saved_cr.get("offenses", {})),
            total_witnessed=saved_cr.get("total_witnessed", 0),
            decay_timer=saved_cr.get("decay_timer", 0.0),
        )
        app.world.add(player, cr)

    return saved_zone


# ── World resources ──────────────────────────────────────────────────

def setup_world_resources(app: App, tiles: list[list[int]],
                          default_zone: str) -> None:
    """Register Camera, ParticleManager, ZoneMetadata on the world."""
    app.world.set_res(Camera())
    app.world.set_res(ParticleManager())

    width = len(tiles[0]) if tiles else 0
    height = len(tiles)
    app.world.set_res(ZoneMetadata(
        name=default_zone, width=width, height=height, chunk_size=8,
    ))


# ── NPC / container spawning ────────────────────────────────────────

class ContainerMap:
    """World resource holding subzone → container EID mapping."""
    def __init__(self, mapping: dict[str, list[int]]):
        self.mapping = mapping


def spawn_characters(app: App) -> None:
    """Load data/characters.toml and spawn each entry via entity_factory."""
    char_path = Path("data/characters.toml")
    if not char_path.exists():
        return

    with open(char_path, "rb") as f:
        data = tomllib.load(f)

    from components.simulation import SubzonePos

    count = 0
    container_ids: dict[str, list[int]] = {}

    for char_id, desc in data.items():
        if not isinstance(desc, dict):
            continue
        zone = "settlement"
        if "subzone_pos" in desc and isinstance(desc["subzone_pos"], dict):
            zone = desc["subzone_pos"].get("zone", zone)
        elif "spawn_info" in desc and isinstance(desc["spawn_info"], dict):
            zone = desc["spawn_info"].get("zone", zone)

        eid = spawn_from_descriptor(app.world, desc, zone)
        count += 1

        ident = app.world.get(eid, Identity)
        if ident and ident.kind == "container":
            szp = app.world.get(eid, SubzonePos)
            if szp:
                container_ids.setdefault(szp.subzone, []).append(eid)

    if container_ids:
        app.world.set_res(ContainerMap(container_ids))

    print(f"[MAIN] Spawned {count} characters/containers from characters.toml")
