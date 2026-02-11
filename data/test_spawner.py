"""data/test_spawner.py — Test entity spawning utilities.

Reads from ``data/test_entities.py`` tables and creates test dummies,
NPCs, and containers via the generic ``spawn_from_descriptor`` path
or the convenience ``spawn_test_dummy`` builder.
"""

from __future__ import annotations
from core.ecs import World
from components import (
    Position, Velocity, Sprite, Identity, Brain, Patrol, Threat, AttackConfig,
    Collider, Health, Inventory, Equipment, Facing,
    Lod, Hurtbox, Combat, Faction,
)


def spawn_test_entities(world: World, zone: str) -> list[int]:
    """Spawn test dummies, NPCs, and containers.

    Reads from data/test_entities.py and assembles them via
    ``spawn_test_dummy`` (for dummies) or ``spawn_from_descriptor``
    (for containers and NPCs).
    """
    from data.test_entities import TEST_DUMMIES, TEST_CONTAINERS, TEST_NPCS
    from logic.entity_factory import spawn_from_descriptor

    eids: list[int] = []

    for _key, data in TEST_DUMMIES.items():
        desc = dict(data)
        pos = desc.get("position", {})
        brain_data = desc.get("brain", {})
        equip_data = desc.get("equipment", {})
        faction_data = desc.get("faction", {})
        inv_data = desc.get("inventory", {})
        patrol_data = desc.get("patrol", brain_data)  # fallback to brain for old-style
        threat_data = desc.get("threat", brain_data)
        atk_data = desc.get("attack_config", brain_data)
        spawn_x = float(pos.get("x", 5.0))
        spawn_y = float(pos.get("y", 5.0))

        eid = spawn_test_dummy(
            world, zone,
            x=spawn_x, y=spawn_y,
            name=desc.get("identity", {}).get("name", "Dummy"),
            char=desc.get("sprite", {}).get("char", "D"),
            color=tuple(desc.get("sprite", {}).get("color", (180, 100, 100))),
            hp=float(desc.get("health", {}).get("maximum", 30.0)),
            damage=float(desc.get("combat", {}).get("damage", 5.0)),
            defense=float(desc.get("combat", {}).get("defense", 0.0)),
            brain_kind=brain_data.get("kind", "wander"),
            brain_active=bool(brain_data.get("active", False)),
            patrol_radius=float(patrol_data.get("patrol_radius", patrol_data.get("radius", 5.0))),
            patrol_speed=float(patrol_data.get("patrol_speed", patrol_data.get("speed", 2.0))),
            aggro_radius=float(threat_data.get("aggro_radius", 8.0)),
            leash_radius=float(threat_data.get("leash_radius", 15.0)),
            flee_threshold=float(threat_data.get("flee_threshold", 0.2)),
            attack_type=atk_data.get("attack_type", "ranged" if brain_data.get("kind") == "hostile_ranged" else "melee"),
            attack_range=float(atk_data.get("attack_range", atk_data.get("range", 1.2))),
            attack_cooldown=float(atk_data.get("attack_cooldown", atk_data.get("cooldown", 0.5))),
            weapon=equip_data.get("weapon", ""),
            armor=equip_data.get("armor", ""),
            faction_group=faction_data.get("group", ""),
            faction_disposition=faction_data.get("disposition", "hostile"),
            faction_alert_radius=float(faction_data.get("alert_radius", 10.0)),
            inventory_items=inv_data.get("items") if inv_data else None,
        )
        print(f"[SPAWN] Spawned {desc.get('identity', {}).get('name', '?')} at ({spawn_x}, {spawn_y})")
        eids.append(eid)

    # NPCs via generic descriptor (trader, settler, etc.)
    for _key, data in TEST_NPCS.items():
        desc = dict(data)
        eid = spawn_from_descriptor(world, desc, zone)
        # Force Lod to high so brains run in test mode
        if world.has(eid, Lod):
            world.get(eid, Lod).level = "high"
        pos = data.get("position", {})
        name = data.get("identity", {}).get("name", "?")
        print(f"[SPAWN] Spawned {name} at ({pos.get('x', 0)}, {pos.get('y', 0)})")
        eids.append(eid)

    for _key, data in TEST_CONTAINERS.items():
        desc = dict(data)
        eid = spawn_from_descriptor(world, desc, zone)
        pos = data.get("position", {})
        name = data.get("identity", {}).get("name", "?")
        print(f"[SPAWN] Spawned {name} at ({pos.get('x', 25.0)}, {pos.get('y', 25.0)})")
        eids.append(eid)

    return eids


def spawn_test_dummy(
    world: World,
    zone: str,
    *,
    x: float = 10.0,
    y: float = 10.0,
    name: str = "Test Dummy",
    char: str = "D",
    color: tuple = (180, 100, 100),
    hp: float = 30.0,
    damage: float = 5.0,
    defense: float = 0.0,
    brain_kind: str = "wander",
    brain_active: bool = False,
    patrol_radius: float = 5.0,
    patrol_speed: float = 2.0,
    aggro_radius: float = 8.0,
    leash_radius: float = 15.0,
    attack_type: str = "melee",
    attack_range: float = 1.2,
    attack_cooldown: float = 0.5,
    flee_threshold: float = 0.2,
    weapon: str = "",
    armor: str = "",
    faction_group: str = "",
    faction_disposition: str = "hostile",
    faction_alert_radius: float = 10.0,
    inventory_items: dict[str, int] | None = None,
) -> int:
    """Spawn a minimal test-dummy entity.

    The test dummy is the *bare-minimum* NPC archetype: something you
    can hit, that has health, occupies space, and optionally fights.
    Returns the entity ID.
    """
    eid = world.spawn()

    world.add(eid, Identity(name=name, kind="dummy"))
    world.add(eid, Position(x=x, y=y, zone=zone))
    world.zone_add(eid, zone)
    world.add(eid, Sprite(char=char, color=color, layer=5))
    world.add(eid, Health(current=hp, maximum=hp))
    world.add(eid, Combat(damage=damage, defense=defense))
    world.add(eid, Collider())
    world.add(eid, Hurtbox())
    world.add(eid, Velocity())
    world.add(eid, Facing())
    world.add(eid, Equipment(weapon=weapon, armor=armor))
    items: dict[str, int] = {}
    if weapon:
        items[weapon] = 1
    if armor:
        items[armor] = 1
    if inventory_items:
        for iid, qty in inventory_items.items():
            items[iid] = items.get(iid, 0) + qty
    if items:
        world.add(eid, Inventory(items=items))
    if faction_group:
        world.add(eid, Faction(
            group=faction_group,
            disposition=faction_disposition,
            home_disposition=faction_disposition,
            alert_radius=faction_alert_radius,
        ))
    world.add(eid, Brain(kind=brain_kind, active=brain_active))
    world.add(eid, Patrol(
        origin_x=x, origin_y=y,
        radius=patrol_radius,
        speed=patrol_speed,
    ))
    if brain_kind in ("hostile_melee", "hostile_ranged", "guard"):
        world.add(eid, Threat(
            aggro_radius=aggro_radius,
            leash_radius=leash_radius,
            flee_threshold=flee_threshold,
        ))
        world.add(eid, AttackConfig(
            attack_type=attack_type,
            range=attack_range,
            cooldown=attack_cooldown,
        ))
    world.add(eid, Lod(level="high", chunk=(0, 0)))

    return eid
