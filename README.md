# Post-Apocalyptic Pawn Shop (PAPS)

A top-down 2D survival RPG built from scratch with Python and pygame. You play as a shopkeeper trying to survive in a post-apocalyptic settlement — trading, fighting, and navigating a world where NPCs live their own lives even when you're not watching.

![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)
![pygame 2.6](https://img.shields.io/badge/pygame-2.6-green)

---

## Table of Contents

- [Quick Start](#quick-start)
- [Controls](#controls)
- [Architecture Overview](#architecture-overview)
- [Entity-Component-System](#entity-component-system)
- [World & Zones](#world--zones)
- [AI & Brain System](#ai--brain-system)
- [Combat](#combat)
- [Off-Screen Simulation](#off-screen-simulation)
- [LOD System](#lod-system)
- [Crime & Reputation](#crime--reputation)
- [UI & Modal System](#ui--modal-system)
- [Data Pipeline](#data-pipeline)
- [Tuning & Hot-Reload](#tuning--hot-reload)
- [Developer Tools](#developer-tools)
- [Test Scenes](#test-scenes)
- [Project Structure](#project-structure)
- [Codebase Stats](#codebase-stats)

---

## Quick Start

```bash
# Clone
git clone <repo-url>
cd Post-Apocalyptic-Pawn-Shop

# Set up venv
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Generate zone maps (first time only)
python data/generate_zones.py

# Run
python main.py
```

### Requirements

- **Python 3.10+** (uses `match` statements, `X | Y` unions)
- **pygame 2.6+** (with `pygame.SCALED` support)
- **nbtlib** — Zone file I/O (falls back to custom binary format if missing)
- **tomli** — TOML parsing for Python < 3.11 (Python 3.11+ uses built-in `tomllib`)

---

## Controls

### Gameplay

| Key | Action |
|-----|--------|
| **WASD** | Move |
| **LMB** | Attack (melee or ranged based on weapon) |
| **RMB** | Ranged attack (if equipped) |
| **E** | Interact (talk, loot, trade) |
| **I** / **Tab** | Toggle inventory |
| **1–4** | Weapon hotbar |
| **F** | Fast-forward (10×), **Shift+F** for 30× |
| **F1** | Debug tools overlay |
| **F3** | Scene picker (test scenes) |
| **F4** | Hot-reload `tuning.toml` |
| **F5** | Spawn test entities |
| **F7** | Save game |
| **F8** | Toggle debug overlay |
| **F9** | Toggle grid |
| **F10** | Toggle all-zone rendering |
| **F11** | Toggle fullscreen |
| **F12** | Dump entity state to console |

### Tile Editor

| Key | Action |
|-----|--------|
| **` (backtick)** | Toggle editor mode |
| **LMB** | Paint tile / place teleporter |
| **Shift+drag** | Rectangle fill |
| **RMB** | Delete teleporter |
| **[** / **]** | Change brush size |
| **0–6** | Select tile type |
| **T** | Toggle teleporter mode |
| **A** | Set zone anchor |
| **N** | New zone (prompts name) |
| **Ctrl+S** | Save zone to `.nbt` |
| **Escape** | Exit editor |

---

## Architecture Overview

```
main.py                 ← Bootstrap: create App, load data, spawn player, run
│
├── core/               ← Framework layer
│   ├── app.py          ← Pygame window, main loop, scene stack
│   ├── ecs.py          ← Entity-Component-System world
│   ├── scene.py        ← Abstract Scene base class
│   ├── events.py       ← EventBus (pub/sub decoupling)
│   ├── tuning.py       ← Data-driven constants from TOML
│   ├── data.py         ← TOML → ECS entity loader
│   ├── zone.py         ← Zone tile maps, portals, passability
│   ├── nbt.py          ← Zone file I/O (NBT or custom binary)
│   ├── save.py         ← Game state persistence (JSON)
│   └── constants.py    ← Tile IDs, colors, TILE_SIZE (32px)
│
├── components/         ← 42 dataclass components across 10 modules
│   ├── spatial.py      ← Position, Velocity, Collider, Facing, Hurtbox
│   ├── rendering.py    ← Identity, Sprite, HitFlash
│   ├── rpg.py          ← Health, Hunger, Needs, Inventory, Equipment
│   ├── combat.py       ← Combat, Loot, LootTableRef, Projectile
│   ├── ai.py           ← Brain, Patrol, Threat, AttackConfig, Task, Memory, GoalSet
│   ├── social.py       ← Faction, Dialogue, Ownership, CrimeRecord, Locked
│   ├── resources.py    ← GameClock, Camera, Meta, Lod, ZoneMetadata, Player
│   ├── simulation.py   ← SubzonePos, TravelPlan, Home, Stockpile, WorldMemory
│   ├── item_registry.py ← ItemRegistry (item data lookup)
│   └── dev_log.py      ← DevLog (ring-buffer event log)
│
├── logic/              ← Game systems and AI
│   ├── tick.py         ← Per-frame system orchestration
│   ├── systems.py      ← Movement (axis-separated collision), input, item pickup
│   ├── combat.py       ← Damage formula, death, loot drops, faction alerts
│   ├── combat_engagement.py ← Combat FSM (idle→chase→attack→flee→return)
│   ├── pathfinding.py  ← A* with wall-margin penalty, 8-directional
│   ├── projectiles.py  ← Projectile physics, collision, damage falloff
│   ├── particles.py    ← Lightweight particle effects
│   ├── sensors.py      ← Periodic AI perception (hostiles, damage, hunger, crime)
│   ├── goals.py        ← Priority-based goal system (7 goal types)
│   ├── mob_goals.py    ← Per-brain-kind goal/sensor templates
│   ├── needs_system.py ← Hunger drain, auto-eating, food production
│   ├── lod_system.py   ← Zone-based LOD tier assignment
│   ├── crime.py        ← Witness detection, theft, lockpicking, reputation
│   ├── dialogue.py     ← Dialogue tree registry
│   ├── quests.py       ← Quest tracking and global flags
│   ├── loot_tables.py  ← Weighted random loot rolls
│   ├── entity_factory.py ← Schema-driven entity spawning
│   ├── input_manager.py ← Intent-based input with context switching
│   ├── actions/        ← Player action API (attack, interact, inventory)
│   └── brains/         ← AI brain modules (wander, villager, combat, registry)
│
├── simulation/         ← Off-screen world simulation
│   ├── world_sim.py    ← Top-level orchestrator (facade)
│   ├── subzone.py      ← World topology graph (Dijkstra pathfinding)
│   ├── scheduler.py    ← Priority-queue event loop
│   ├── events.py       ← Scheduler event handlers (arrive, eat, work, rest, combat)
│   ├── decision.py     ← NPC decision cycle (5-priority behavioral stack)
│   ├── travel.py       ← Route planning and movement
│   ├── stat_combat.py  ← Off-screen DPS-based combat resolution
│   ├── lod_transition.py ← High↔Low LOD entity transitions
│   ├── checkpoint.py   ← Arrival evaluation (detection, discovery, encounters)
│   └── economy.py      ← Settlement stockpile management
│
├── scenes/             ← Game screens
│   ├── world_scene.py  ← Main gameplay scene
│   ├── world_draw.py   ← Rendering functions (tiles, entities, HUD, debug)
│   ├── world_helpers.py ← Input routing, intent handling, timers
│   ├── zone_manager.py ← Zone loading and portal transitions
│   ├── editor_controller.py ← Tile editor state and logic
│   ├── debug_scene.py  ← F1 developer tools (4 tabs)
│   ├── scene_picker.py ← F3 scene selection menu
│   ├── gym_scene.py    ← Pathfinding & movement test arena
│   ├── museum_scene.py ← System exhibit demos (4 tabs)
│   └── zoo_scene.py    ← Entity bestiary (auto-populated grid)
│
├── ui/                 ← Modal UI framework
│   ├── modal.py        ← Abstract Modal + ModalStack
│   ├── commands.py     ← Command pattern (CloseModal, HealPlayer, etc.)
│   ├── dialogue_modal.py ← Dialogue tree conversation UI
│   ├── inventory_modal.py ← Player inventory with equip/use/drop
│   ├── transfer_modal.py ← Two-panel container↔player transfer
│   └── helpers.py      ← Shared drawing utilities
│
├── data/               ← Content definitions
│   ├── characters.toml ← 9 NPCs + 7 containers (starting world population)
│   ├── items.toml      ← 12 items (6 weapons + 6 consumables)
│   ├── loot_tables.toml ← 3 loot tables (weighted random rolls)
│   ├── subzones.toml   ← 15-node world topology graph
│   ├── portals.toml    ← Inter-zone teleporter connections
│   ├── tuning.toml     ← ~155 gameplay constants (hot-reloadable)
│   └── generate_zones.py ← Zone map generator script
│
├── zones/              ← Binary tile maps (.nbt)
│   ├── settlement.nbt  ← 40×40 walled settlement
│   ├── road.nbt        ← 60×20 connecting road
│   ├── ruins.nbt       ← 40×40 raider-infested ruins
│   ├── overworld.nbt   ← Hub zone
│   └── test.nbt        ← Test zone
│
└── saves/              ← JSON save files (slot-based)
```

---

## Entity-Component-System

The game uses a custom ECS framework (`core/ecs.py`). Entities are plain integers. Components are Python dataclasses stored by type. Systems are standalone functions that query the world.

```python
w = World()
e = w.spawn()
w.add(e, Position(x=5.0, y=3.0, zone="settlement"))
w.add(e, Health(current=100, maximum=100))

for eid, pos, hp in w.query(Position, Health):
    pos.x += 1
    hp.current -= 5
```

### Key Design Decisions

- **Dictionary-of-dictionaries storage** — simple, no archetypes. `{ComponentType: {eid: instance}}`
- **Query optimization** — iterates the smallest component bucket first
- **Deferred deletion** — `kill()` marks dead; `purge()` cleans (once per frame)
- **Zone index** — O(1) lookup of entities by zone via `zone_entities("settlement")`
- **Resources as pseudo-entities** — singletons stored at entity ID `-1` (GameClock, Camera, EventBus, etc.)

### Component Inventory (42 components)

| Category | Components |
|----------|-----------|
| **Spatial** | `Position`, `Velocity`, `Collider`, `Facing`, `Hurtbox` |
| **Rendering** | `Identity`, `Sprite`, `HitFlash` |
| **RPG** | `Health`, `Hunger`, `Needs`, `Inventory`, `Equipment` |
| **Combat** | `Combat`, `Loot`, `LootTableRef`, `Projectile` |
| **AI** | `Brain`, `Patrol`, `Threat`, `AttackConfig`, `Task`, `Memory`, `GoalSet` |
| **Social** | `Faction`, `Dialogue`, `Ownership`, `CrimeRecord`, `Locked` |
| **Resources** | `GameClock`, `Camera`, `Meta`, `Lod`, `ZoneMetadata`, `Player` |
| **Simulation** | `SubzonePos`, `TravelPlan`, `Home`, `Stockpile`, `MemoryEntry`, `WorldMemory` |
| **Other** | `ItemRegistry`, `DevLog` |

---

## World & Zones

The game world consists of multiple tile-based zones connected by portals.

### Zones

| Zone | Size | Description | Threat |
|------|------|-------------|--------|
| **Settlement** | 40×40 | Walled town with gate, market, farm, well, houses, storehouse | None |
| **Road** | 60×20 | Connecting road with crossroads and hidden cache | Low |
| **Ruins** | 40×40 | Collapsed buildings, raider camp, pharmacy | High |

### Tile Types

| ID | Type | Passable | Color |
|----|------|----------|-------|
| 0 | Void | No | Black |
| 1 | Grass | Yes | Green |
| 2 | Dirt | Yes | Brown |
| 3 | Stone | Yes | Grey |
| 4 | Water | Yes (penalized) | Blue |
| 5 | Wood Floor | Yes | Tan |
| 6 | Wall | No | Dark grey |
| 9 | Teleporter | Yes | Cyan |

### Portal System

Zones are connected via portal tiles defined in `data/portals.toml`. Walking onto a portal tile teleports the player to the linked zone:

```
Settlement ←→ Road ←→ Ruins
```

The editor supports placing and editing portal tiles with destination zones.

---

## AI & Brain System

NPCs are driven by a **brain registry** pattern. Each entity's `Brain.kind` string maps to a tick function that runs every frame (when active and not in low-LOD).

### Brain Types

| Brain | Behavior |
|-------|----------|
| **wander** | A*-based random walk within patrol radius |
| **villager** | Schedule-driven daily cycle: morning work → midday eat → afternoon socialize → evening rest. Crime panic, hunger override, communal meals |
| **hostile_melee** | Combat FSM with melee attacks |
| **hostile_ranged** | Combat FSM with ranged attacks (projectiles) |
| **guard** | Combat FSM with no fleeing (flee_threshold=0) |

### Combat FSM

All hostile/guard brains share a unified combat finite state machine (`logic/combat_engagement.py`):

```
idle → chase → attack → flee → return → idle
                ↑                  │
                └──────────────────┘
```

- **Idle**: Wander or stand still until a target is detected
- **Chase**: A*-pathfind toward the target
- **Attack**: Execute melee or ranged attack (data-driven by `AttackConfig`)
- **Flee**: Run away when HP drops below `flee_threshold`
- **Return**: Pathfind back to patrol origin, reset faction disposition

### Targeting

1. Search for the player in the same zone
2. If no player found, find the nearest entity from a **different faction group** (enables NPC-vs-NPC combat)
3. Sensor-throttled: expensive target acquisition runs every `sensor_interval` seconds; cheap velocity output runs every frame

### Friendly-Fire Prevention

- **Melee**: Suppressed when a same-faction ally stands near the target
- **Ranged**: Line-of-fire capsule test — if an ally is between shooter and target within 0.6 tiles, fire is suppressed and the entity strafes to reposition

### Goal System

A priority-based goal system (`logic/goals.py`) provides higher-level behavior:

| Priority | Goal | Trigger |
|----------|------|---------|
| 1 | Attack Target | Hostile detected via sensors |
| 2 | Flee | HP below flee threshold |
| 3 | Eat | Hunger critical |
| 4 | Forage | No food and hungry |
| 5 | Return Home | After combat or displacement |
| 7 | Wander | Default roaming |
| 8 | Idle | Lowest priority fallback |

---

## Combat

### Damage Formula

```
raw = base_damage + weapon_bonus - target_armor
damage = max(1, raw) × uniform(0.8, 1.2) × crit_multiplier
```

- **Crit chance**: 10% (configurable), **crit multiplier**: 1.5×
- **Knockback**: Pushes target away from attacker
- **Hit flash**: White sprite flash for 0.1s on damage

### Weapons

| Weapon | Type | Damage | Special |
|--------|------|--------|---------|
| Knife | Melee | 12 | Fast (0.2s CD), short reach |
| Hoe | Melee | 8 | Long reach, high knockback |
| Baseball Bat | Melee | 14 | Balanced |
| Pistol | Ranged | 20 | Accurate, medium range |
| Hunting Rifle | Ranged | 35 | High damage, long range |
| Shotgun | Ranged | 12×5 | 5 pellets, wide spread |

### Ranged Combat

- Projectiles are full entities with `Position`, `Velocity`, physics
- **Damage falloff**: 100% at origin → 50% at max range
- **Accuracy spread**: Configurable per weapon (0.6 for shotgun → 0.92 for rifle)
- **Faction-aware**: Projectiles skip same-faction entities (no friendly fire)

### Death & Loot

On death: blood particles → loot drop (items + loot table rolls) → `world.kill()`. The player is exempt from permadeath.

---

## Off-Screen Simulation

NPCs continue to live when the player isn't watching. The simulation layer operates on an abstract **subzone graph** — a weighted graph of locations where off-screen entities move, work, eat, fight, and rest.

### Subzone Graph

15 nodes across 3 zones, connected by weighted edges (travel time in game-minutes). Loaded from `data/subzones.toml`.

```
Settlement:
  sett_gate ── sett_market ── sett_well ── sett_farm
                   │              │
              sett_residential  sett_storehouse

Road:
  road_sett_end ── road_crossroads ── road_ruins_end
                        │
                   road_hidden_cache

Ruins:
  ruins_entrance ── ruins_collapsed_bldg ── ruins_deep ── ruins_pharmacy
       │                    │
  ruins_raider_camp ────────┘
```

### Event-Driven Scheduler

The simulation runs on a **priority-queue event scheduler** — entities post their next state change to a time-ordered heap. Between events they cost zero CPU.

Event types: `ARRIVE_NODE`, `HUNGER_CRITICAL`, `FINISH_SEARCH`, `FINISH_WORK`, `FINISH_EAT`, `REST_COMPLETE`, `DECISION_CYCLE`, `COMBAT_RESOLVED`, `COMMUNAL_MEAL`.

### NPC Decision Cycle

When an NPC needs to decide what to do, a 5-priority behavioral stack evaluates in order:

1. **Survival** — HP < 30%? Find shelter and rest
2. **Critical Needs** — Hungry? Eat from inventory → stockpile → scavenge
3. **Duty/Role** — Farmer: work fields. Guard: patrol. Raider: supply runs
4. **Discretionary** — 30% chance to explore an unvisited adjacent node
5. **Default** — Return home if away; otherwise wander or idle

### Stat-Based Combat Resolution

When hostile entities share a subzone node, combat is resolved via stats:
- **DPS model**: `effective_DPS = (base + weapon) × attack_speed`
- **Time-to-kill**: `TTK = target_HP / attacker_DPS`
- **Periodic flee checks**: Every 2 game-minutes, check if projected HP ratio crosses flee threshold
- **Flee roll**: Speed-based success probability
- **Loot**: Winner takes loser's inventory

### Checkpoint System

When an NPC arrives at a node, a 4-phase pipeline runs:
1. **Presence Check** — Detect entities at the same or adjacent nodes (visibility-weighted)
2. **Discovery** — Write observations into `WorldMemory` (locations, containers, threats)
3. **Interrupt** — Critical hunger → eat; low HP + shelter → rest
4. **Continue/Arrive** — Resume travel or begin next decision cycle

### Word-of-Mouth Memory

NPCs have a `WorldMemory` component — a key-value store of time-stamped observations. When friendly NPCs meet:
- They share `location:`, `threat:`, and `crime:` memories
- A witness tells a guard about a crime → the guard tells other settlers → eventually all guards go hostile toward the criminal
- Memories expire (configurable TTL), so old crimes fade

---

## LOD System

Entities exist at three detail levels based on **zone proximity** — not Euclidean distance:

| Level | Condition | Behavior |
|-------|-----------|----------|
| **High** | Same zone as player, near | Full simulation: real-time movement, rendering, A* pathfinding |
| **Medium** | Same zone as player, far | Brains run, entity moves, but reduced visual detail |
| **Low** | Different zone | Event-driven simulation via scheduler (no Position, no rendering) |

### LOD Transitions

- **Promotion** (low → high): `SubzonePos` → `Position` (placed at portal or subzone anchor), `Brain` activated, combat components attached
- **Demotion** (high → low): `Position` → `SubzonePos`, scheduled events posted, brain deactivated. Mid-combat entities are resolved immediately via stat combat
- **Grace period**: Prevents brain execution for a few frames after promotion to avoid stale-data issues

---

## Crime & Reputation

### Theft System

Taking items from owned containers triggers a witness check:
1. Scan for non-hostile NPCs within `witness_radius` (8 tiles)
2. Each witness records the crime in their `WorldMemory`
3. Armed witnesses (guards) turn immediately hostile
4. Civilians flee for `crime_flee_duration` (20s)
5. Crime memories propagate via word-of-mouth when NPCs meet

### Lockpicking

Locked containers (`Locked` component) require a lockpick attempt:
- Difficulty 0: 100%, Difficulty 1: 75%, Difficulty 2: 50%, Difficulty 3: 25%
- Always triggers a witness check, regardless of success

### Reputation Decay

Crime records have a TTL (default 1200s / 20 game-minutes). Old crimes are forgotten during `WorldMemory.purge_stale()`.

---

## UI & Modal System

The UI uses a **command pattern** — modals never directly mutate game state. They return `UICommand` objects that the scene processes.

### Modal Stack

Multiple modals can render simultaneously (stacked overlays), but only the **topmost** modal receives input.

### Modals

| Modal | Purpose | Features |
|-------|---------|----------|
| **DialogueModal** | NPC conversation | Tree navigation, conditional choices (quest-flag gated), trade/flag actions |
| **InventoryModal** | Player inventory | Equip/unequip, use consumables, drop items/stacks |
| **TransferModal** | Container transfer | Two-panel layout, theft detection, lockpicking, auto-unequip |

### Command Types

| Command | Effect |
|---------|--------|
| `CloseModal` | Pop topmost modal |
| `HealPlayer(amount)` | Apply HP healing |
| `OpenTrade(npc_eid)` | Close dialogue, open trade |
| `SetFlag(flag)` | Set quest flag |

---

## Data Pipeline

All game content is defined in TOML files and loaded into the ECS at startup.

```
characters.toml ──→ entity_factory.py ──→ ECS World (9 NPCs + 7 containers)
items.toml ────────→ ItemRegistry ──────→ Referenced by inventory/equipment/loot
loot_tables.toml ──→ LootTableManager ──→ Container loot generation
subzones.toml ─────→ SubzoneGraph ──────→ Off-screen NPC movement
portals.toml ──────→ zone_manager.py ───→ Inter-zone teleporters
tuning.toml ───────→ core/tuning.py ───→ All gameplay constants
generate_zones.py ─→ zones/*.nbt ──────→ Tile maps loaded at runtime
```

### Items (12 total)

- **Melee weapons** (3): Knife, Hoe, Baseball Bat
- **Ranged weapons** (3): Pistol, Hunting Rifle, Shotgun
- **Consumables** (6): Canned Beans, Dried Meat, Stew, Ration, Bandages, Antibiotics

### NPCs (9 total)

- **Settlers** (5): Old Pete (farmer), Maria (farmer), Beck (guard), Hale (guard), Nessa (trader)
- **Loners** (1): Dex (wanderer)
- **Raiders** (3): Scar, Mag, Vex

---

## Tuning & Hot-Reload

All gameplay constants live in `data/tuning.toml` (~155 values). Press **F4** in-game to hot-reload without restarting.

Systems read values via:
```python
from core.tuning import get
knockback = get("combat.melee", "default_knockback", 3.0)
```

### Tuning Categories

| Section | Examples |
|---------|----------|
| `combat.melee` | knockback, crit chance/mult, damage variance, reach |
| `combat.ranged` | accuracy, projectile speed, max range, spread |
| `combat.engagement` | Chase/flee/kite speed multipliers, transition thresholds |
| `ai.helpers` | Path recompute interval, dodge/heal cooldowns, idle timers |
| `ai.villager` | Day length (300s), schedule phases, eat/forage/greet timers |
| `ai.wander` | Pick interval, destination attempts, min radius |
| `lod` | High LOD radius, grace period, check interval |
| `needs` | Hunger thresholds, eat cooldown, storehouse refill rate |
| `crime` | Witness radius, memory TTL, flee duration |
| `pathfinding` | Max distance, wall margin penalty, tile costs |
| `particles` | Max count, burst configs per effect type |
| `defaults.*` | Default component values for health, hunger, patrol, threat, etc. |

---

## Developer Tools

### Debug Overlay (F1)

Four-tab fullscreen inspector:

| Tab | Feature |
|-----|---------|
| **AI Observer** | Live NPC table (name, faction, mode, HP, hunger, position, LOD). Sidebar with full brain state dump and per-entity DevLog |
| **ECS Browser** | Filterable entity list with expandable component details. Color-coded by type |
| **Entity Editor** | Live-edit any scalar field on any entity. Changes logged to DevLog |
| **Event Log** | Scrollable DevLog feed with category filters (combat, attack, brain, error, etc.) |

### Debug Overlay (F8)

In-world overlay showing:
- Per-NPC labels (faction, brain state, combat mode, threat/attack config)
- Aggro and leash radius circles
- Line-of-fire rays with X markers when blocked
- A* path visualization (dashed lines)
- FPS, entity count, LOD tier counts
- Simulation info for off-screen entities

### Other Debug Keys

| Key | Action |
|-----|--------|
| **F5** | Spawn test entities (raider, gunner, brute, chest, trader, settler) |
| **F7** | Save game state to `saves/slot0.json` |
| **F9** | Toggle tile grid |
| **F10** | Show entities from all zones |
| **F12** | Dump full entity table to console |

---

## Test Scenes

Accessible via **F3** (scene picker):

### Gym Scene
Movement and pathfinding sandbox. Three preset layouts (Open, Maze, Rooms). Paint walls with LMB, set A* goals with RMB. Three NPC walkers with path visualization. Dual metrics panels (movement stats and pathfinding stats).

### Zoo Scene
Auto-populated entity bestiary. Reads `characters.toml` and `items.toml`, spawns each in a labeled grid cell. Tab to toggle between characters and items. Click to inspect with full component sidebar dump.

### Museum Scene
Four-tab system demo:
1. **AI Brains** — 5 NPCs with different brain types (wander, villager, guard, melee, ranged)
2. **Combat** — Blue team vs. Red team (melee + ranged per side) with cover blocks and live status
3. **LOD Demo** — 15 NPCs with distance-based LOD tier visualization
4. **Pathfinding** — Wall painting with pre-built corridors, A* path visualization with calc timing

---

## Project Structure

### Rendering

- **Virtual surface**: Fixed 960×640, SDL handles scaling/letterboxing via `pygame.SCALED`
- **Tile size**: 32×32 pixels
- **Entity rendering**: Single-character sprites with color, sorted by layer
- **Particle system**: Lightweight (`__slots__`), capped at 512, with gravity/drag/fade

### Pathfinding

- **A* with 8-directional movement** and Chebyshev heuristic
- **Wall-margin penalty**: Pre-computes wall-adjacent tiles (all 8 neighbors); soft penalty keeps paths away from walls without blocking narrow gaps
- **Agent hitbox centering**: 0.8×0.8 tile hitbox, waypoints offset for center alignment
- **Diagonal corner-cutting prevention**: Checks cardinal adjacency before allowing diagonal moves

### Save System

Game state persists to `saves/slot0.json`:
- Player position, zone, inventory, equipment, health, hunger, crime record
- All entity states (position or simulation position, health, inventory, brain state)
- Scheduler event queue for simulation continuity

### Event Bus

Decoupled system communication via `EventBus` (stored as a world resource):
- `EntityDied`, `EntityHit`, `AttackIntent`, `FactionAlert`, `ProjectileHit`
- `CrimeWitnessed`, `ZoneChanged`, `TuningReloaded`
- Handlers subscribe by event class name; `drain()` processes FIFO with breadth-first re-emission

---

## Codebase Stats

| Metric | Count |
|--------|-------|
| Python source files | 86 |
| Total lines of Python | ~19,700 |
| ECS components | 42 |
| TOML data files | 6 |
| Zone map files | 5 |
| Tuning constants | ~155 |
| Items defined | 12 |
| NPCs defined | 9 |
| Subzone nodes | 15 |
| Brain types | 5 |
| Goal types | 7 |
| Event types | 8 |
| Scheduler event types | 9 |
| Scenes | 7 (world, debug, gym, museum, zoo, scene picker, editor) |
| UI modals | 3 (dialogue, inventory, transfer) |
