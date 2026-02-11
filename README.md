# Post Apocalyptic Pawn Shop

A top-down post-apocalyptic game built with **pygame** and a **custom ECS
(entity-component-system)** engine. Explore tile-based zones, fight hostile
NPCs with melee and ranged weapons, trade with friendly settlers, loot
containers, and edit zones with the built-in tile editor.

> **Status:** early prototype — text-character sprites, no sound, many systems
> still skeletal.

---

## Quick Start

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
python main.py
```

Requires **Python 3.11+** and **pygame 2.x**.
`nbtlib` is pulled in by `requirements.txt` for zone file I/O.

---

## Controls

| Key | Action |
|-----|--------|
| **WASD / Arrows** | Move |
| **Left-click / X** | Attack (melee or ranged depending on weapon) |
| **E** | Interact — talk to NPCs, loot containers |
| **I** | Toggle inventory |
| **1-4** | Quick-swap weapon |
| **Tab** | Toggle debug overlay |
| **G** | Toggle grid |
| **F1** | ECS inspector (debug scene) |
| **F5** | Spawn test entities |
| **Ctrl+S** | Save |
| **F10** | Toggle zone editor |
| **Esc** | Close modal / exit editor |

---

## Architecture

### Boot Sequence

```
main.py
 ├─ App(title, w, h)        # pygame window + clock + World()
 ├─ DataLoader → items.toml  # item entities + ItemRegistry
 ├─ LootTableManager         # loot_tables.toml → world resource
 ├─ load_zones_from_disk()   # zones/*.nbt → ZONE_MAPS
 ├─ load_game_state()        # saves/slot0.json (optional)
 ├─ spawn player entity      # Position, Velocity, Sprite, Health, …
 └─ push WorldScene          # enter main loop
```

### Core Engine (`core/`)

| Module | Lines | Purpose |
|--------|------:|---------|
| `ecs.py` | 140 | Entities are ints. Components stored `dict[type, dict[eid, comp]]`. Zone index for O(1) spatial lookup. Resources at entity -1. Deferred death via `kill`/`purge`. |
| `app.py` | 92 | Pygame shell — window, clock, fonts, scene stack, 60 FPS main loop. |
| `scene.py` | 54 | Abstract `Scene` with `on_enter`, `on_exit`, `handle_event`, `update`, `draw`. |
| `zone.py` | 111 | Module-level caches (`ZONE_MAPS`, `ZONE_ANCHORS`, `ZONE_TELEPORTERS`). Passability checks. |
| `nbt.py` | 151 | Binary NBT read/write for zone tiles, anchors, teleporters, entity spawns. |
| `save.py` | 179 | JSON game-state persistence (player + entity snapshots). |
| `data.py` | 118 | TOML → ECS loader. `DataLoader` maps TOML keys to component constructors. |
| `constants.py` | 29 | Tile IDs, `TILE_SIZE = 32`, colour palette. |

### Components (`components/`)

Seven sub-modules, re-exported from `components/__init__.py`.

| Module | Components |
|--------|-----------|
| `spatial.py` | `Position`, `Velocity`, `Collider`, `Facing`, `Hurtbox` |
| `rendering.py` | `Identity`, `Sprite`, `HitFlash` |
| `rpg.py` | `Health`, `Hunger`, `Inventory`, `Equipment` |
| `combat.py` | `Combat`, `Loot`, `LootTableRef`, `Projectile` |
| `ai.py` | `Brain`, `Task` |
| `social.py` | `Faction`, `Dialogue` |
| `resources.py` | `Camera`, `Meta`, `Lod`, `ZoneMetadata`, `Player` |
| `item_registry.py` | `ItemRegistry` (world resource — item lookup table) |

### Logic (`logic/`)

| Module | Lines | Purpose |
|--------|------:|---------|
| `systems.py` | 145 | `movement_system`, `input_system`, `item_pickup_system` |
| `brains.py` | 598 | Brain registry + 4 AIs: `wander`, `hostile_melee`, `hostile_ranged`, `guard`. Faction gates, dodge, self-heal. |
| `combat.py` | 328 | Damage model (`attack_entity`), death, knockback, hit flash, faction alert propagation, NPC attack wrappers. |
| `actions.py` | 522 | Player actions: attack (melee/ranged), interact, loot, inventory, trade. Returns `AttackResult` for visuals. |
| `entity_factory.py` | 419 | Data-driven entity spawning from descriptor dicts + convenience `spawn_test_dummy`. |
| `dialogue.py` | 96 | `DialogueManager` resource + built-in dialogue trees (trader, settler). |
| `quests.py` | 38 | `QuestLog` resource — flags, active/completed quests. |
| `loot_tables.py` | 127 | Weighted random loot generation from TOML tables. |
| `particles.py` | 132 | `ParticleManager` — burst emitter, per-frame physics, fade/gravity. |
| `projectiles.py` | 147 | `projectile_system` — bullet movement, wall/hurtbox collision, damage falloff. |
| `input_manager.py` | 268 | Intent-based input: 4 contexts (GAMEPLAY/UI/EDITOR/TEXT), `just()`/`held()`/`movement()`. |

### UI (`ui/`)

| Module | Lines | Purpose |
|--------|------:|---------|
| `modal.py` | 112 | Abstract `Modal` base + `ModalStack` manager. |
| `commands.py` | 41 | Command objects: `CloseModal`, `HealPlayer`, `OpenTrade`, `SetFlag`. |
| `helpers.py` | 65 | Shared draw utils: overlay, title bar, item row rendering. |
| `inventory_modal.py` | 312 | Single-panel inventory — equip, use, drop. |
| `transfer_modal.py` | 296 | Dual-panel loot/trade modal. |
| `dialogue_modal.py` | 163 | Conversation tree navigation + action dispatch. |

### Scenes (`scenes/`)

| Module | Lines | Purpose |
|--------|------:|---------|
| `world_scene.py` | 607 | Main gameplay: input routing, system dispatch, camera, zone transitions. |
| `world_draw.py` | 408 | Pure rendering functions: tiles, entities, HUD, debug overlay, particles. |
| `debug_scene.py` | 120 | ECS inspector overlay — browse entities and components. |
| `editor_controller.py` | 405 | Tile editor: paint, teleporters, zone management, NBT export. |

### Data (`data/`)

| File | Content |
|------|---------|
| `items.toml` | 10 items — 3 melee weapons, 3 ranged weapons, 4 consumables. |
| `loot_tables.toml` | 3 loot tables (basic/treasure/empty chest). |
| `characters.toml` | 1 NPC template (disabled). |
| `test_entities.py` | 3 combat dummies, 2 containers, 2 friendly NPCs (trader + settler). |

---

## Key Patterns

### Brain Registration

```python
def _hostile_melee_brain(world, eid, brain, dt): ...
register_brain("hostile_melee", _hostile_melee_brain)
```

Brains store per-entity state in `brain.state` (a dict). `run_brains(world, dt)`
dispatches to the registered function for each `Brain.kind`.

### UI Command Flow

```
Modal.handle_event(event)
  → list[UICommand]
  → WorldScene._route_ui_event() applies each:
      CloseModal  → modals.pop()
      HealPlayer  → mutate Health
      OpenTrade   → pop dialogue, push TransferModal
      SetFlag     → QuestLog.set_flag()
```

Modals never touch the ECS directly — they emit commands.

### Entity Spawning

Two paths converging on the same component bundle:

1. **Descriptor-driven** — `spawn_from_descriptor(world, dict, zone)` reads a
   data dict and adds matching components. Used by zone spawns and test entities.
2. **Keyword builder** — `spawn_test_dummy(world, zone, *, …)` for quick
   combat NPC creation with explicit params.

### Faction System

- `Faction(group, disposition, home_disposition, alert_radius)`
- Attacking a non-hostile entity flips it and nearby same-group allies to
  `"hostile"` via `alert_nearby_faction()`.
- Combat brains gate on `disposition == "hostile"` before engaging.
- When leashing home, `disposition` resets to `home_disposition`.

---

## Project Stats

| Metric | Value |
|--------|-------|
| Python files | 44 |
| Total lines (approx.) | ~6,000 |
| Components | 22 dataclasses |
| Brain types | 4 (wander, hostile_melee, hostile_ranged, guard) |
| Items defined | 10 |
| Zones | 2 (overworld, test) |
| UI modals | 3 (inventory, transfer, dialogue) |

---

## Refactor Plan

The codebase works but has grown organically. Here's a prioritised plan to make
it more maintainable before adding major features. Each phase is independent and
can be done in a single session.

### Phase 1 — Tame the God-files

**Goal:** no file over ~300 lines, clear single-responsibility.

| Current file | Lines | Split into |
|-------------|------:|------------|
| `scenes/world_scene.py` | 607 | Extract zone loading/teleport into `scenes/zone_manager.py`. Extract attack state + cooldown into a `CombatState` component or small `scenes/combat_hud.py` helper. The scene becomes pure routing. |
| `logic/brains.py` | 598 | Move to `logic/brains/` package: `__init__.py` (registry + `run_brains`), `wander.py`, `hostile_melee.py`, `hostile_ranged.py`, `guard.py`, `_helpers.py` (shared move/dodge/heal). |
| `logic/actions.py` | 522 | Split into `logic/actions/combat.py` (melee/ranged attack), `logic/actions/interact.py` (dialogue/loot/trade), `logic/actions/inventory.py` (toggle, equip). Keep `logic/actions/__init__.py` re-exporting. |
| `logic/entity_factory.py` | 419 | Replace the giant if/elif chain with a **component registry** (see Phase 3). Short-term: extract `spawn_test_*` into `data/test_spawner.py`. |

### Phase 2 — Fix the Layering / Dependency Direction

**Goal:** `logic/` never imports from `ui/`. Scenes bridge the two.

| Problem | Fix |
|---------|-----|
| `actions.py` imports `InventoryModal`, `TransferModal`, `DialogueModal` | Actions return intent objects (e.g. `OpenInventory`, `OpenDialogue(npc_eid)`, `OpenLoot(container_eid)`). WorldScene maps intents → modal pushes. |
| `actions.py._open_dialogue` constructs a `DialogueModal` | Move modal construction into `WorldScene._handle_interact_result()`. Action returns the data (tree, npc_name, npc_eid). |
| `projectiles.py` uses deferred imports for `handle_death`, `alert_nearby_faction` | Pass callback or use a lightweight event emitter (Phase 4) to decouple. |

### Phase 3 — Component-descriptor Registry

**Goal:** `spawn_from_descriptor` becomes table-driven instead of a 200-line if chain.

```python
# entity_factory.py
_COMP_BUILDERS: dict[str, Callable[[dict], Any]] = {}

def register_comp_builder(key: str, builder):
    _COMP_BUILDERS[key] = builder

# Then for each component:
register_comp_builder("health", lambda d: Health(
    current=float(d.get("current", 100)),
    maximum=float(d.get("maximum", 100)),
))
```

Also unify `spawn_test_dummy` into `spawn_from_descriptor` — the keyword
builder becomes a thin wrapper that builds a descriptor dict and calls the
generic path.

### Phase 4 — Event Bus

**Goal:** decouple combat → faction → particles → death → loot.

Introduce a simple synchronous event bus as a world resource:

```python
@dataclass
class EventBus:
    _listeners: dict[type, list[Callable]] = field(default_factory=dict)

    def emit(self, event): ...
    def on(self, event_type, handler): ...
```

Events: `DamageDealt`, `EntityDied`, `FactionAlerted`, `ItemPickedUp`,
`DialogueStarted`. Systems subscribe during init. Eliminates the current web
of direct function calls and deferred imports.

### Phase 5 — Clean Up Dead / Skeletal Systems

| What | Action |
|------|--------|
| `Hunger` component + `rate` field | Either implement a proper hunger tick system or remove entirely. Currently it's just a number on the HUD. |
| `Task` component | Used by save/load for low-LOD entities but no task system exists. Document intent or remove. |
| `characters.toml` + loader line | Decide: either wire it up or delete it. Currently dead code. |
| LOD management | `Lod` is on every entity but only used as a gate. Either build a real chunk-based activation system or simplify to a bool. |
| `Meta` component | Only used by `spawn_zone_entities` dedup check. Could be replaced by a zone-level flag. |

### Phase 6 — `main.py` Cleanup

**Goal:** `main.py` is < 40 lines.

Extract into:
- `core/bootstrap.py` → `create_player(world, zone)`, `load_all_data(world)`,
  `resolve_starting_zone()`, `apply_save(world)`.
- `main.py` becomes:
  ```python
  from core.app import App
  from core.bootstrap import setup
  app = App("Post Apocalyptic Pawn Shop", 1024, 768)
  setup(app)
  app.run()
  ```

### Phase 7 — Future Feature Prep

These aren't refactors but architectural preps that become easy after the
above:

| Feature | Depends on | Prep |
|---------|-----------|------|
| Real sprites/textures | — | Add `SpriteSheet` resource + `render_system` that replaces char drawing |
| Sound effects | Event bus | Listeners that play sounds on `DamageDealt`, `EntityDied`, etc. |
| Crafting | Component registry | New `Recipe` resource + `CraftingModal` |
| Quest trees | Event bus + QuestLog | Quests listen for events, auto-advance stages |
| NPC schedules | Brain package | New `schedule` brain that reads a timetable |
| Multiplayer prep | ECS | Separate World stepping from rendering; deterministic `dt` |

### Suggested Order

```
Phase 1 (god-files)      ← do first, biggest quality-of-life win
Phase 2 (layering)       ← do second, prevents things getting worse
Phase 6 (main.py)        ← quick win, 30 min
Phase 3 (comp registry)  ← do before adding more component types
Phase 5 (dead systems)   ← housekeeping, any time
Phase 4 (event bus)      ← do before sound/quests
Phase 7 (feature prep)   ← as needed per feature
```