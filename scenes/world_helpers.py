"""scenes/world_helpers.py — Extracted helpers for WorldScene.

Functions that previously lived as methods on WorldScene.  Each takes
a ``scene`` parameter (the WorldScene instance) so they can read/write
scene state without being class methods.
"""

from __future__ import annotations
import pygame
from components import (
    Player, Position, Identity, Inventory, Equipment,
    ItemRegistry, Health, HitFlash, Lod, Velocity, Sprite,
)
from logic.input_manager import InputContext
from ui import CloseModal, HealPlayer, OpenTrade, SetFlag
from ui import DialogueModal, TransferModal, InventoryModal


# ── Input context ────────────────────────────────────────────────────

def update_input_context(scene):
    """Sync InputManager context with scene state."""
    if scene.editor.text_input_active:
        scene.input.context = InputContext.TEXT
    elif scene.modals.is_open:
        scene.input.context = InputContext.UI
    elif scene.editor_active:
        scene.input.context = InputContext.EDITOR
    else:
        scene.input.context = InputContext.GAMEPLAY


# ── UI command routing ───────────────────────────────────────────────

def route_ui_event(scene, event: pygame.event.Event, app):
    """Delegate event to the modal stack and process returned commands."""
    cmds = scene.modals.handle_event(event)
    for cmd in cmds:
        if isinstance(cmd, CloseModal):
            scene.modals.pop()
        elif isinstance(cmd, HealPlayer):
            res = app.world.query_one(Player, Health)
            if res:
                _, _, hp = res
                hp.current = min(hp.maximum, hp.current + cmd.amount)
        elif isinstance(cmd, OpenTrade):
            scene.modals.pop()  # close dialogue
            from logic.actions import open_npc_trade
            intent = open_npc_trade(app, cmd.npc_eid)
            if intent:
                _apply_intent(scene, intent)
        elif isinstance(cmd, SetFlag):
            from logic.quests import QuestLog
            ql = app.world.res(QuestLog)
            if ql:
                ql.set_flag(cmd.flag, cmd.value)


def _apply_intent(scene, intent):
    """Map an action intent to a UI modal and push it onto the stack."""
    from logic.actions import OpenDialogueIntent, OpenTransferIntent, OpenInventoryIntent

    if isinstance(intent, OpenDialogueIntent):
        scene.modals.push(DialogueModal(
            tree=intent.tree,
            npc_name=intent.npc_name,
            npc_eid=intent.npc_eid,
            quest_log=intent.quest_log,
        ))
    elif isinstance(intent, OpenTransferIntent):
        scene.modals.push(TransferModal(
            player_inv=intent.player_inv,
            container_inv=intent.container_inv,
            equipment=intent.equipment,
            registry=intent.registry,
            title=intent.title,
            container_title=intent.container_title,
            owner_faction=intent.owner_faction,
            on_steal=intent.on_steal,
            locked=intent.locked,
            on_lockpick=intent.on_lockpick,
        ))
    elif isinstance(intent, OpenInventoryIntent):
        scene.modals.push(InventoryModal(
            player_inv=intent.player_inv,
            equipment=intent.equipment,
            registry=intent.registry,
            title=intent.title,
        ))


# ── Weapon utilities ─────────────────────────────────────────────────

def weapon_hotkey(scene, app, slot: int):
    """Quick-swap weapon via number keys 1-4."""
    res = app.world.query_one(Player, Position)
    if not res:
        return
    player_eid = res[0]
    inv = app.world.get(player_eid, Inventory)
    equip = app.world.get(player_eid, Equipment)
    registry = app.world.res(ItemRegistry)
    if not inv or not equip or not registry:
        return
    weapons = sorted(
        item_id for item_id, qty in inv.items.items()
        if qty > 0 and registry.item_type(item_id) == "weapon"
    )
    if slot >= len(weapons):
        if equip.weapon:
            print(f"[EQUIP] Unequipped {registry.display_name(equip.weapon)}")
            equip.weapon = ""
        return
    chosen = weapons[slot]
    if equip.weapon == chosen:
        equip.weapon = ""
        print(f"[EQUIP] Unequipped {registry.display_name(chosen)}")
    else:
        equip.weapon = chosen
        print(f"[EQUIP] Equipped {registry.display_name(chosen)}")


def start_attack_cooldown(scene, app):
    """Set attack cooldown from weapon data (data-driven)."""
    res = app.world.query_one(Player, Position)
    if not res:
        scene.attack_cooldown = 0.25
        scene.attack_cooldown_max = 0.25
        return
    player_eid = res[0]
    equip = app.world.get(player_eid, Equipment)
    registry = app.world.res(ItemRegistry)
    if equip and equip.weapon and registry:
        cd = registry.weapon_cooldown(equip.weapon)
    else:
        cd = 0.2  # fists
    scene.attack_cooldown = cd
    scene.attack_cooldown_max = cd


# ── Gameplay intent processing ───────────────────────────────────────

def process_gameplay_intents(scene, app):
    """Handle all discrete gameplay intents for the current frame."""
    from logic.actions import (
        player_attack, player_interact_nearby, player_toggle_inventory,
    )
    from logic.entity_factory import spawn_test_entities
    from core.save import save_game_state
    from core.zone import ZONE_MAPS

    inp = scene.input

    if inp.just("toggle_debug"):
        scene.show_debug = not scene.show_debug
    if inp.just("toggle_grid"):
        scene.show_grid = not scene.show_grid
    if inp.just("debug_scene"):
        from scenes.debug_scene import DebugScene
        app.push_scene(DebugScene())
    if inp.just("entity_dump"):
        dump_entity_debug(app)
    if inp.just("toggle_zones"):
        scene.show_all_zones = not scene.show_all_zones
    if inp.just("spawn_test"):
        spawn_test_entities(app.world, scene.zone)
    if inp.just("save"):
        save_path = save_game_state(app)
        print(f"[SAVE] Game saved to {save_path}")

    if inp.just("attack") and scene.attack_cooldown <= 0:
        atk = player_attack(app, scene)
        if atk is not None:
            scene.attack_active = atk.melee_active
            scene.attack_timer = atk.melee_timer
            scene.attack_direction = atk.melee_direction
            if atk.muzzle_flash_timer > 0:
                scene.muzzle_flash_timer = atk.muzzle_flash_timer
                scene.muzzle_flash_start = atk.muzzle_flash_start
                scene.muzzle_flash_end = atk.muzzle_flash_end
        start_attack_cooldown(scene, app)

    if inp.just("interact"):
        if not scene.modals.is_open:
            intent = player_interact_nearby(app)
            if intent is not None:
                _apply_intent(scene, intent)
    if inp.just("inventory"):
        if not scene.modals.is_open:
            intent = player_toggle_inventory(app)
            if intent is not None:
                _apply_intent(scene, intent)

    for slot in range(4):
        if inp.just(f"weapon_{slot + 1}"):
            weapon_hotkey(scene, app, slot)

    if inp.just("toggle_editor"):
        scene.editor_active = True
        scene.editor.selected_tile = 1
        scene.editor.brush_size = 1
        if scene.zone not in ZONE_MAPS:
            scene.tiles = [[1] * 30 for _ in range(30)]
            scene.map_h = 30
            scene.map_w = 30
            scene.editor.teleporters = {}
        scene.editor.teleporter_mode = False
        scene.editor._pending_tp = None


# ── Tooltip scanning ─────────────────────────────────────────────────

def update_tooltips(scene, app, mw):
    """Scan entities near the mouse cursor and set tooltip state."""
    scene.tooltip_eid = None
    scene.tooltip_text = ""
    scene.tooltip_hp = None
    if mw and not scene.editor_active and not scene.modals.is_open:
        mx, my = mw
        best_dist = 1.2
        for eid, pos, ident in app.world.query(Position, Identity):
            if pos.zone != scene.zone:
                continue
            if app.world.has(eid, Player):
                continue
            dx = pos.x + 0.4 - mx
            dy = pos.y + 0.4 - my
            d = (dx * dx + dy * dy) ** 0.5
            if d < best_dist:
                best_dist = d
                scene.tooltip_eid = eid
                scene.tooltip_text = ident.name
                if app.world.has(eid, Health):
                    hp = app.world.get(eid, Health)
                    scene.tooltip_hp = (hp.current, hp.maximum)


# ── Timer ticking ────────────────────────────────────────────────────

def tick_timers(scene, dt: float, app):
    """Tick attack cooldown, melee timer, muzzle flash, and hit-flash."""
    if scene.attack_cooldown > 0:
        scene.attack_cooldown -= dt

    if scene.attack_active:
        scene.attack_timer -= dt
        if scene.attack_timer <= 0:
            scene.attack_active = False

    if scene.muzzle_flash_timer > 0:
        scene.muzzle_flash_timer -= dt

    expired = []
    for eid, flash in app.world.all_of(HitFlash):
        flash.remaining -= dt
        if flash.remaining <= 0:
            expired.append(eid)
    for eid in expired:
        app.world.remove(eid, HitFlash)


# ── Debug dump ───────────────────────────────────────────────────────

def dump_entity_debug(app):
    """Print a compact table of entities and their key components to console."""
    dump = app.world.debug_dump()
    print("--- ENTITY DUMP ---")
    print(f"total entities: {len(dump)}")
    counts = {"pos": 0, "lod": 0}
    for eid, comps in sorted(dump.items()):
        name = "<no-name>"
        pos_s = "-"
        lod_s = "-"
        vel_s = "-"
        spr = "?"
        for c in comps:
            if isinstance(c, Identity):
                name = c.name
            if isinstance(c, Position):
                pos_s = f"({c.x:.1f},{c.y:.1f}) z={c.zone}"
                counts["pos"] += 1
            if isinstance(c, Lod):
                lod_s = c.level
                counts["lod"] += 1
            if isinstance(c, Velocity):
                vel_s = f"({c.x:.2f},{c.y:.2f})"
            if isinstance(c, Sprite):
                spr = c.char
        print(f"eid={eid:3} name={name:12} spr={spr} pos={pos_s:20} lod={lod_s:6} vel={vel_s}")
    print(f"positions: {counts['pos']}  lods: {counts['lod']}")
    print("--- END DUMP ---")
