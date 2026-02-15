"""logic/actions/interact.py — Interaction, dialogue, looting, and trade.

The wasteland runs on trust and fear.  Steal if you dare — but
get caught by a villager and word will spread.  Guards don't
forgive.  Take what you want when nobody's looking.
"""

from __future__ import annotations
from components import (
    Player, Position, Identity, Inventory, Equipment,
    Loot, LootTableRef, ItemRegistry, Faction, Dialogue, Ownership,
    Locked, GameClock,
)
from logic.loot_tables import LootTableManager
from logic.actions import OpenDialogueIntent, OpenTransferIntent
from logic.crime import make_theft_callback, make_lockpick_callback


# ── Generalized interact ───────────────────────────────────────────

def player_interact_nearby(app):
    """Player presses E — interact with the nearest entity.

    Returns an intent object the scene maps to a modal, or None.

    Dispatch order:
      1. Dialogue (friendly/neutral NPCs with a Dialogue component)
      2. Container / loot (existing transfer logic)
    """
    res = app.world.query_one(Player, Position)
    if not res:
        return
    player_eid, _, player_pos = res

    # Find nearest interactable entity within 2.5 tiles
    best = None
    best_dist_sq = 2.5 * 2.5
    for eid, pos, dsq in app.world.nearby(
        player_pos.zone, player_pos.x, player_pos.y, 2.5, Position,
    ):
        if app.world.has(eid, Player):
            continue
        # Must be interactable: Dialogue, Loot, LootTableRef, or container Inventory
        has_dialogue = app.world.has(eid, Dialogue)
        has_loot = (app.world.has(eid, Loot) or app.world.has(eid, LootTableRef))
        is_container = (
            app.world.has(eid, Inventory) and app.world.has(eid, Identity)
            and app.world.get(eid, Identity).kind in ("container", "object")
        )
        if not (has_dialogue or has_loot or is_container):
            continue
        if dsq < best_dist_sq:
            best = eid
            best_dist_sq = dsq

    if best is None:
        print("[INTERACT] Nothing nearby")
        return None

    # Dispatch by entity type
    if app.world.has(best, Dialogue):
        faction = app.world.get(best, Faction)
        if faction and faction.disposition == "hostile":
            print("[INTERACT] They don't want to talk.")
            return None
        return _build_dialogue_intent(app, best)

    # Fall through to container/loot
    return player_loot_nearby(app)


def _build_dialogue_intent(app, npc_eid: int):
    """Build an OpenDialogueIntent for the given NPC."""
    dialogue = app.world.get(npc_eid, Dialogue)
    if not dialogue:
        return None

    npc_name = "NPC"
    if app.world.has(npc_eid, Identity):
        npc_name = app.world.get(npc_eid, Identity).name

    from logic.dialogue import DialogueManager
    from logic.dialogue import QuestLog

    manager = app.world.res(DialogueManager)
    tree = None
    if manager and dialogue.tree_id:
        tree = manager.get_tree(dialogue.tree_id)

    if tree is None and dialogue.greeting:
        tree = {
            "root": {
                "text": dialogue.greeting,
                "choices": [{"label": "[Leave]", "action": "close"}],
            }
        }

    if tree is None:
        print(f"[DIALOGUE] {npc_name} has nothing to say.")
        return None

    quest_log = app.world.res(QuestLog)
    print(f"[DIALOGUE] Talking to {npc_name}")
    return OpenDialogueIntent(
        tree=tree, npc_name=npc_name, npc_eid=npc_eid, quest_log=quest_log,
    )


def open_npc_trade(app, npc_eid: int):
    """Return a transfer intent for trading with an NPC.

    Willing traders (``can_trade = True``) allow free two-way exchange.
    Other NPCs: taking is theft — succeeds if nobody sees, but
    witnesses report to the settlement.
    """
    res = app.world.query_one(Player, Position)
    if not res:
        return None
    player_eid = res[0]

    npc_name = "NPC"
    if app.world.has(npc_eid, Identity):
        npc_name = app.world.get(npc_eid, Identity).name

    # Ensure NPC has an inventory
    npc_inv = _ensure_container_inventory(app, npc_eid)

    if not app.world.has(player_eid, Inventory):
        app.world.add(player_eid, Inventory())
    player_inv = app.world.get(player_eid, Inventory)

    equip = app.world.get(player_eid, Equipment)
    registry = app.world.res(ItemRegistry)

    # Determine if taking from this NPC is theft
    owner_faction, on_steal = _get_theft_info(app, npc_eid)

    mode = "Trading with" if not owner_faction else "Browsing"
    print(f"[TRADE] {mode} {npc_name}")
    return OpenTransferIntent(
        player_inv=player_inv.items,
        container_inv=npc_inv.items,
        equipment=equip,
        registry=registry,
        title="Your Bag",
        container_title=npc_name,
        owner_faction=owner_faction,
        on_steal=on_steal,
    )


# ── Container / Transfer ───────────────────────────────────────────

def _ensure_container_inventory(app, container_eid: int) -> Inventory:
    """Make sure a container entity has an Inventory component."""
    if app.world.has(container_eid, Inventory):
        return app.world.get(container_eid, Inventory)

    items: dict[str, int] = {}

    if app.world.has(container_eid, LootTableRef):
        ltr = app.world.get(container_eid, LootTableRef)
        mgr = app.world.res(LootTableManager)
        if mgr:
            rolled = mgr.roll(ltr.table_name)
            for item_id in rolled:
                items[item_id] = items.get(item_id, 0) + 1
            print(f"[LOOT] Rolled table '{ltr.table_name}': {rolled}")

    if app.world.has(container_eid, Loot):
        loot = app.world.get(container_eid, Loot)
        if not loot.looted and loot.items:
            for item_id in loot.items:
                items[item_id] = items.get(item_id, 0) + 1
        loot.looted = True

    inv = Inventory(items=items)
    app.world.add(container_eid, inv)
    return inv


def player_loot_nearby(app):
    """Find nearest lootable and return a transfer intent, or None.

    Owned containers can be looted — but if an NPC sees you, they'll
    remember and tell others.  Guards respond with force.
    """
    res = app.world.query_one(Player, Position)
    if not res:
        return None
    player_eid, _, player_pos = res

    best = None
    best_dist_sq = 2.0 * 2.0
    for eid, pos, dsq in app.world.nearby(
        player_pos.zone, player_pos.x, player_pos.y, 2.0, Position,
    ):
        if not (app.world.has(eid, Loot) or app.world.has(eid, LootTableRef)
                or (app.world.has(eid, Inventory) and app.world.has(eid, Identity)
                    and app.world.get(eid, Identity).kind in ("container", "object"))):
            continue
        if dsq < best_dist_sq:
            best = eid
            best_dist_sq = dsq

    if best is None:
        print("[LOOT] Nothing to loot nearby")
        return None

    container_eid = best
    container_name = "Container"
    if app.world.has(container_eid, Identity):
        container_name = app.world.get(container_eid, Identity).name

    container_inv = _ensure_container_inventory(app, container_eid)

    if not app.world.has(player_eid, Inventory):
        app.world.add(player_eid, Inventory())
    player_inv = app.world.get(player_eid, Inventory)

    equip = app.world.get(player_eid, Equipment)
    registry = app.world.res(ItemRegistry)

    # Check if this container is owned — theft triggers witnesses
    owner_faction, on_steal = _get_theft_info(app, container_eid)

    # Check if this container is locked
    is_locked, on_lockpick = _get_lock_info(app, container_eid)

    print(f"[LOOT] Opened {container_name}")
    return OpenTransferIntent(
        player_inv=player_inv.items,
        container_inv=container_inv.items,
        equipment=equip,
        registry=registry,
        title="Your Bag",
        container_title=container_name,
        owner_faction=owner_faction,
        on_steal=on_steal,
        locked=is_locked,
        on_lockpick=on_lockpick,
    )


# ── Theft detection ─────────────────────────────────────────────────

def _get_theft_info(app, eid: int) -> tuple[str, callable | None]:
    """Determine if taking from this entity is theft.

    Returns (owner_faction, on_steal_callback).
    - If owner_faction is empty, taking is free (not theft).
    - If owner_faction is set, taking triggers the on_steal callback
      which checks for witnesses and reports the crime.

    Theft conditions:
    - Entity has Ownership component → owned by that faction
    - Friendly NPC without can_trade → their stuff is theirs
    - Dead NPCs, hostile entities, willing traders → free to loot
    """
    # Dead things are fair game
    from components import Health
    health = app.world.get(eid, Health)
    if health and health.current <= 0:
        return ("", None)

    # Willing trader — free exchange
    dialogue = app.world.get(eid, Dialogue)
    if dialogue and dialogue.can_trade:
        return ("", None)

    # Explicit ownership tag (settlement property)
    ownership = app.world.get(eid, Ownership)
    if ownership:
        clock = app.world.res(GameClock)
        game_time_fn = lambda: clock.time if clock else 0.0
        callback = make_theft_callback(
            app.world, ownership.faction_group, game_time_fn,
        )
        return (ownership.faction_group, callback)

    # Check faction — hostile stuff is fair game
    faction = app.world.get(eid, Faction)
    if faction is None:
        return ("", None)
    if faction.disposition == "hostile":
        return ("", None)

    # Friendly/settler NPC who doesn't trade → taking is theft
    if faction.group in ("settlers", "player"):
        clock = app.world.res(GameClock)
        game_time_fn = lambda: clock.time if clock else 0.0
        callback = make_theft_callback(
            app.world, faction.group, game_time_fn,
        )
        return (faction.group, callback)

    return ("", None)


# ── Lock detection ──────────────────────────────────────────────────

def _get_lock_info(app, eid: int) -> tuple[bool, callable | None]:
    """Check if an entity is locked.

    Returns (is_locked, on_lockpick_callback).
    - If not locked, returns (False, None).
    - If locked, returns (True, callback) where callback() attempts
      to pick the lock and returns (success: bool, message: str).
    """
    lock = app.world.get(eid, Locked)
    if lock is None:
        return (False, None)

    # Determine the owning faction for crime reporting
    ownership = app.world.get(eid, Ownership)
    faction_group = ownership.faction_group if ownership else "settlers"

    clock = app.world.res(GameClock)
    game_time_fn = lambda: clock.time if clock else 0.0
    callback = make_lockpick_callback(
        app.world, lock, faction_group, game_time_fn,
    )
    return (True, callback)
