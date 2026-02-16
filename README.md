# Post-Apocalyptic Pawn Shop

A top-down 2D survival RPG built from scratch in Python + pygame, featuring a
custom ECS engine, multi-zone world, off-screen simulation, and data-driven
design. Everything from combat AI to village economies runs on the same
entity-component-system architecture, with all gameplay numbers tunable via
TOML files that hot-reload at the press of a key.

---

## Quick Start

```bash
# Clone and enter the project
git clone <repo-url> && cd Post-Apocalyptic-Pawn-Shop

# Install dependencies (Python 3.9+)
pip install pygame nbtlib tomli

# Run the game
python main.py
```

The game opens into the **settlement** zone by default. If no `.nbt` zone files
are found, it falls back to a blank 50×50 grass map in editor mode.

---

## Controls

| Key | Action |
|---|---|
| **WASD** | Move |
| **Left-click** | Attack / interact |
| **E** | Interact with nearby NPC or container |
| **Tab** | Open inventory |
| **F1** | Toggle debug overlay |
| **F3** | Scene picker (Museum, Zoo, Gym) |
| **F4** | Hot-reload tuning.toml |
| **F5** | Quick-save |
| **F9** | Quick-load |
| **F11** | Toggle fullscreen |
| **Esc** | Close modal / menu |

---

## Architecture

### ECS Engine (`core/ecs.py`)

Entities are plain integers. Components are Python objects stored in
per-type buckets (`dict[type, dict[int, Any]]`). Queries iterate the
smallest matching bucket first for efficiency.

- **Zone index** — O(1) spatial lookups via `world.query_zone()` and
  `world.nearby(zone, x, y, radius)`
- **Resource singletons** — `GameClock`, `Camera`, `ItemRegistry`, etc.
  stored at entity ID -1
- **Deferred cleanup** — `world.kill()` marks, `world.purge()` sweeps
  once per frame

### Scene Stack (`core/scene.py`, `core/app.py`)

Scenes are pushed/popped onto a stack; only the top scene is active.
The main game loop runs at 60 FPS: `events → update(dt) → draw(surface)`.

### Data-Driven Design

All gameplay constants live in [`data/tuning.toml`](data/tuning.toml) (310
lines covering combat, AI, perception, economy, particles, and more). Press
**F4** to hot-reload without restarting.

Entities are defined in TOML:
- [`data/characters.toml`](data/characters.toml) — NPCs, containers, settlements
- [`data/items.toml`](data/items.toml) — weapons, consumables, armor
- [`data/loot_tables.toml`](data/loot_tables.toml) — Minecraft-style weighted loot pools
- [`data/subzones.toml`](data/subzones.toml) — world graph for off-screen simulation
- [`data/portals.toml`](data/portals.toml) — inter-zone connections

---

## Project Structure

```
main.py                  Entry point — bootstrap → TopDown → run

core/                    Engine layer (no game logic)
  app.py                 Pygame shell, scene stack, game loop
  ecs.py                 Entity-Component-System with zone index
  scene.py               Abstract scene base class
  bootstrap.py           Game initialization (data loading, player creation)
  constants.py           Unit system (1 tile = 1 metre), tile IDs, speeds
  events.py              Event bus (EntityDied, FactionAlert, AttackIntent)
  collision.py           AABB vs tile-grid collision
  data.py                TOML → component deserialization
  nbt.py                 Binary zone file format (read/write)
  zone.py                Zone registry, portals, line-of-sight
  subzone.py             Weighted subzone graph, Dijkstra routing
  tuning.py              Hot-reloadable gameplay constants
  save.py                JSON save/load (player, entities, scheduler)

components/              Pure data — no logic
  spatial.py             Position, Velocity, Collider, Facing, Hurtbox
  rendering.py           Identity, Sprite, HitFlash
  rpg.py                 Health, Hunger, Needs, Inventory, Equipment
  combat.py              CombatStats, Loot, LootTableRef, Projectile
  ai.py                  Brain, HomeRange, Threat, AttackConfig, VisionCone,
                         Task, Memory
  social.py              Faction, Dialogue, Ownership, CrimeRecord, Locked
  offscreen.py           SubzonePos, TravelPlan, Home, Stockpile, WorldMemory
  resources.py           GameClock, Camera, Player, Lod, SpawnInfo
  item_registry.py       Item stat lookup table
  dev_log.py             Ring-buffer debug log

systems/                 All game mechanics
  engine/                Frame pipeline & infrastructure
    tick.py              Per-frame system orchestrator
    input_manager.py     Raw input → named intent mapping
    entity_factory.py    TOML-driven entity spawning
    particles.py         Particle VFX (blood, sparks, muzzle flash)
  movement/              Spatial systems
    physics.py           Velocity integration, wall-sliding, overlap separation
    pathfinding.py       A* with tile penalties, clearance, wall-margin costs
  combat/                Full combat pipeline (14 modules)
    engagement.py        Combat FSM (idle → search → chase → attack → flee)
    melee_fsm.py         Melee sub-states (approach → circle → feint → lunge)
    attacks.py           Hit detection, damage rolls, knockback
    damage.py            Damage application, death handling
    projectiles.py       Bullet physics, accuracy spread, range falloff
    targeting.py         Target selection and priority
    tactical.py          Positioning scorer (cover, spacing, fire-line)
    fireline.py          Friendly-fire avoidance
    alerts.py            Faction alert propagation, combat sounds
    allies.py            Ally coordination
    movement.py          Combat-specific movement (chase, flee, kite, strafe)
    state.py             Combat state tracking
    offscreen.py         Stat-check combat for off-screen encounters
  ai/                    NPC decision-making
    brains.py            Brain registry and per-frame tick dispatcher
    perception.py        Vision cones, facing-based detection, LOS checks
    steering.py          A* path-following, reactive steering fallback
    defense.py           Dodge-on-hit, heal-when-low
    wander.py            Random patrol within HomeRange leash
    villager.py          Schedule-driven daily routine (work → eat → socialize)
    villager_state.py    Villager state persistence
    offscreen.py         Off-screen AI decision cycle (5-tier priority)
  actions/               Player action handlers
    interact.py          NPC talk, container loot, trade, lockpick
    player_attacks.py    Mouse-aimed melee/ranged attacks
  offscreen/             Off-screen world simulation
    manager.py           WorldSim orchestrator
    scheduler.py         Event priority queue (game-time ordered)
    lod.py               LOD promotion / demotion / per-frame sweep
    travel.py            Route planning through subzone graph
    checkpoint.py        Subzone arrival evaluation
    handlers.py          Event resolution (hunger, work, travel, meals)
  items/                 Item operations
    inventory_consume.py Eat, heal, consume from stockpile/container
    loot_tables.py       Weighted random loot generation
  social/                Social simulation
    settlement.py        Village creation, stockpile management, food production
    crime.py             Witness-based theft detection, reputation spreading
    dialogue.py          Dialogue trees, quest tracking (QuestLog)
    faction_disposition.py  Faction mutation (hostile, flee, guard checks)
  scheduling/            Time-driven NPC systems
    needs.py             Hunger drain, starvation, need-priority evaluation
    communal_meals.py    Twice-daily settlement meals
    scheduled_activities.py  Generic recurring activity framework

scenes/                  Game screens
  world/                 Main gameplay scene (tile map, HUD, modals, editor)
  lab/                   Developer lab scenes and debug tools
    museum.py            Interactive exhibit museum (12 system demos)
    zoo.py               Auto-populated entity bestiary
    gym.py               Movement & pathfinding test arena
    debug.py             Developer tools (AI observer, ECS browser, event log)
    picker.py            Jump between test scenes (F3)
    exhibits/            Self-contained system exhibits

ui/                      Modal UI framework
  modal.py               Base modal + modal stack
  inventory_modal.py     Item browsing, equip, consume
  transfer_modal.py      Container ↔ player transfer, theft hooks
  dialogue_modal.py      NPC dialogue with branching choices
  commands.py            UICommand pattern (CloseModal, HealPlayer, SetFlag…)
  helpers.py             Shared drawing utilities

data/                    Game data (TOML + generators)
zones/                   Zone maps (.nbt binary files)
saves/                   Save files (JSON)
```

---

## Key Systems

### Combat

Two parallel pipelines share components but diverge in resolution:

- **On-screen**: Real-time hurtbox AABB overlap, projectile physics with
  accuracy spread, knockback impulse, critical hits, weapon reach. A full
  **melee sub-FSM** (approach → circle → feint → lunge → retreat) and
  **engagement FSM** (idle → searching → chase → attack → flee → return)
  drive NPC behavior.
- **Off-screen**: Stat-check resolution when hostiles share a subzone node,
  producing outcomes consistent with real-time combat.

NPCs hear gunshots (1600 m), shouts (150 m), and melee (40 m). Hearing
bridges into the vision → chase pipeline. **Fire-line awareness** makes NPCs
dodge clear of allied lines of fire. **Tactical positioning** scores
candidates by range, wall cover, ally spacing, and fire-line clearance.

### AI

Pluggable brain types registered at startup:

| Brain | Behavior |
|---|---|
| `wander` | Random patrol within HomeRange leash |
| `villager` | 4-phase daily schedule — work, eat, socialize, rest |
| `hostile_melee` | Chase + melee FSM engagement |
| `hostile_ranged` | Chase + ranged kiting with accuracy |

**Perception** uses vision cones (120° FOV, configurable distance +
peripheral range) with DDA line-of-sight checks against the tile grid.
**Steering** integrates A* pathfinding with reactive fallback offsets.

Off-screen AI runs a 5-tier priority system: survival → critical needs →
duty → discretionary → default. Decisions produce scheduler events rather
than per-frame state changes.

### Off-Screen Simulation

A 3-tier **LOD system** keeps the world alive without simulating everything
in real-time:

| LOD | When | Representation |
|---|---|---|
| **High** | Within 200 m of player | `Position` + `Brain` — full per-frame simulation |
| **Low** | Elsewhere | `SubzonePos` + scheduler events — zero CPU between events |

The **WorldScheduler** is a game-time-ordered priority queue. Entities post
their next meaningful state change (arrive at node, get hungry, finish work)
and sleep until then. On arrival at a subzone node, a **checkpoint** runs:
presence discovery, combat interrupts, memory exchange, and next-event
scheduling.

**WorldMemory** lets NPCs remember threats, locations, and crimes. Memories
propagate NPC-to-NPC at checkpoint encounters — a guard who meets a witness
learns about the player's crimes and turns hostile.

### Social Layer

- **Crime**: Witness-based theft detection within 30 m. Guards react with
  force; civilians flee and spread the word via WorldMemory at subzone
  checkpoints. `CrimeRecord` tracks per-faction offenses on the player.
- **Dialogue**: Tree-based conversations with branching choices, conditions,
  and actions (open trade, set quest flag, close).
- **Factions**: Group disposition (friendly / neutral / hostile) with alert
  propagation — attack one settler and nearby allies respond.

### Economy

Settlements are entities with communal `Stockpile` components. Farmers
produce food via scheduler events, villagers eat from the shared pool, and
surplus/deficit drives NPC scavenging priorities. Storehouses slowly refill
with stew and rations to keep the village fed.

**Loot tables** use a Minecraft-style format: weighted pools with rolls,
bonus rolls, and min/max counts, all defined in TOML.

### Scheduling

The **needs system** drains hunger over time (0.03/s default), applies
starvation damage, and sets need priorities that AI brains react to.
**Communal meals** gather settlers twice daily at the well (06:00 and 18:00
game-time) — guards eat with a 30-minute delay to stay on post.

The `ScheduledActivity` framework generalizes this: define when, where, who,
what, and duration, and the system handles travel, gathering, and return.

---

## Developer Tools

### Debug Overlay (F1)

Four tabs accessible during gameplay:

1. **AI Observer** — Watch any NPC's brain state, current task, needs, and
   decision reasoning in real-time
2. **ECS Browser** — Browse all living entities and their components
3. **Entity Editor** — Modify component values on the fly
4. **Event Log** — Timestamped feed of AI decisions, combat events, and
   system activity

### Test Scenes (F3)

| Scene | Purpose |
|---|---|
| **Museum** | 12 interactive exhibits, each demonstrating a system in isolation |
| **Zoo** | Auto-generated entity bestiary from all TOML data |
| **Gym** | Movement and pathfinding sandbox with preset layouts |

### Hot Reload (F4)

All gameplay constants in `data/tuning.toml` reload instantly — tweak
combat damage, AI perception ranges, hunger rates, or particle effects
without restarting.

---

## Testing

```bash
# Run all tests
python test_museum.py                    # 79 headless integration tests
python -m pytest test_simulation.py      # Simulation layer verification
python -m pytest test_simulation_integration.py  # Multi-system integration
python -m pytest test_behavioral.py      # Tight-tolerance AI behavior
python -m pytest test_combat_behavior.py # Deterministic combat scenarios
python -m pytest test_fixes.py           # Regression tests
```

Tests run headless (no pygame display) and cover the full stack: entity
spawning, physics stepping, combat resolution, AI decision-making, LOD
transitions, save/load round-trips, and off-screen simulation.

---

## Dependencies

| Package | Purpose |
|---|---|
| `pygame` | Rendering, input, audio |
| `nbtlib` | Zone file format (optional — falls back to custom binary) |
| `tomli` | TOML parsing (built-in on Python 3.11+) |

---

## Unit System

All gameplay uses **real-world-ish units** for intuitive tuning:

| Dimension | Unit | Reference |
|---|---|---|
| Distance | 1 tile = 1 metre | A room is 5–8 tiles wide |
| Speed | metres / second | Walk 1.5, run 5, sprint 7.5, bullet 12–18 |
| Time | seconds (real-time) | 300s real = 1 in-game day |
| Hunger | points / second | 0.03/s drain, ~45 min to empty |
