"""scenes/zone_manager.py — Zone loading and portal transitions.

Stand-alone functions that operate on a WorldScene instance.  The
primary interzone travel mechanism is the **portal system** defined
in ``data/portals.toml`` (see :pymod:`core.zone`).  Legacy per-zone
teleporters in NBT files are kept as a fallback.
"""

from __future__ import annotations
from core.zone import (
    ZONE_MAPS, ZONE_TELEPORTERS, ZONE_ANCHORS,
    portal_lookup_for_zone, find_safe_spawn,
)
from components import Player, Position, GameClock


def load_zone(scene, zone: str):
    """Replace the current scene tile map with the named zone map and
    stamp portal / teleporter tiles for that zone.
    """
    if zone not in ZONE_MAPS:
        return
    src = ZONE_MAPS[zone]
    scene.tiles = [row[:] for row in src]
    scene.map_h = len(scene.tiles)
    scene.map_w = len(scene.tiles[0]) if scene.tiles else 0

    # ── Build unified teleporter dict for the editor ─────────────────
    scene.editor.teleporters = {}

    # 1. Portal entries (primary)
    for (r, c), (tz, sr, sc, pid) in portal_lookup_for_zone(zone).items():
        scene.editor.teleporters[(r, c)] = {
            "zone": tz, "r": int(sr), "c": int(sc), "portal_id": pid,
        }
        if 0 <= r < scene.map_h and 0 <= c < scene.map_w:
            scene.tiles[r][c] = 9

    # 2. Legacy NBT teleporters (fallback — skipped if portal exists)
    for (r, c), tgt in ZONE_TELEPORTERS.get(zone, {}).items():
        if (r, c) not in scene.editor.teleporters:
            scene.editor.teleporters[(r, c)] = tgt
            if 0 <= r < scene.map_h and 0 <= c < scene.map_w:
                scene.tiles[r][c] = 9

    scene.zone = zone


def check_player_teleport(scene, app):
    """If the player steps on a portal / teleporter tile, move them."""
    res = app.world.query_one(Player, Position)
    if not res:
        return
    eid, _, pos = res
    # Use entity centre (0.8×0.8 hitbox starts at pos) for tile lookup
    r = int(pos.y + 0.4)
    c = int(pos.x + 0.4)
    key = (r, c)

    # ── Portal lookup (primary) ──────────────────────────────────────
    zone_portals = portal_lookup_for_zone(scene.zone)
    if key in zone_portals:
        target_zone, spawn_r, spawn_c, _pid = zone_portals[key]
        if target_zone not in ZONE_MAPS:
            return
        old_zone = scene.zone
        load_zone(scene, target_zone)
        pos.zone = target_zone
        app.world.zone_set(eid, target_zone)
        # Resolve a wall-free landing spot
        pos.x, pos.y = find_safe_spawn(target_zone, spawn_r, spawn_c)
        _notify_zone_change(scene, app, old_zone)
        return

    # ── Legacy teleporter fallback ───────────────────────────────────
    if key not in scene.editor.teleporters:
        return
    target = scene.editor.teleporters[key]
    old_zone = scene.zone

    if isinstance(target, str):
        target_zone = target
        if target_zone not in ZONE_MAPS:
            return
        load_zone(scene, target_zone)
        anchor = ZONE_ANCHORS.get(target_zone, (15.0, 15.0))
        pos.zone = target_zone
        app.world.zone_set(eid, target_zone)
        pos.x, pos.y = anchor
    elif isinstance(target, dict):
        target_zone = target.get("zone")
        if not target_zone or target_zone not in ZONE_MAPS:
            return
        load_zone(scene, target_zone)
        pos.zone = target_zone
        app.world.zone_set(eid, target_zone)
        if "r" in target and "c" in target:
            pos.x, pos.y = find_safe_spawn(
                target_zone, int(target["r"]), int(target["c"]),
            )
        else:
            anchor = ZONE_ANCHORS.get(target_zone, (15.0, 15.0))
            pos.x, pos.y = anchor
    else:
        return

    _notify_zone_change(scene, app, old_zone)


def _notify_zone_change(scene, app, old_zone: str):
    """Notify simulation of zone change for LOD transitions."""
    if hasattr(scene, 'world_sim') and scene.world_sim and scene.world_sim.active:
        if scene.zone != old_zone:
            clock = app.world.res(GameClock)
            game_minutes = clock.time if clock else 0.0
            scene.world_sim.on_zone_change(app.world, scene.zone,
                                           game_minutes)
