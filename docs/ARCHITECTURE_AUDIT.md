# Architecture Audit — Post-Apocalyptic Pawn Shop

**Date:** 2025-01-XX  
**Scope:** Full codebase read-only review  
**Engine:** Pygame 2.x, Python 3.11, custom ECS, Wolfenstein-style DDA raycaster

---

## Table of Contents

1. [High-Level Architecture](#1-high-level-architecture)
2. [core/ecs.py — Entity Component System](#2-coreecspy)
3. [core/types.py — Shared Enums](#3-coretypespy)
4. [core/tiles.py — Tile Registry](#4-coretilespy)
5. [core/constants.py — Global Constants](#5-coreconstantspy)
6. [core/zones.py — Zone Loading](#6-corezonespy)
7. [core/scene.py — Scene Base Class](#7-corescenepy)
8. [core/app.py — Application Shell](#8-coreapppy)
9. [core/session.py — Game Session](#9-coresessionpy)
10. [core/events.py — Event Bus](#10-coreeventspy)
11. [core/save.py — Persistence](#11-coresavepy)
12. [components/\_\_init\_\_.py — Component Definitions](#12-componentsinitpy)
13. [systems/textures.py — Procedural Textures](#13-systemstexturespy)
14. [systems/raycaster.py — DDA Raycasting](#14-systemsraycasterpy)
15. [systems/physics.py — Movement & Collision](#15-systemsphysicspy)
16. [systems/pathfinding.py — A\* & LOS](#16-systemspathfindingpy)
17. [systems/interaction.py — Entity Interaction](#17-systemsinteractionpy)
18. [systems/spawner.py — Entity Spawning](#18-systemsspawnerpy)
19. [systems/beast_spawner.py — Hostile Mobs](#19-systemsbeast_spawnerpy)
20. [systems/item_registry.py — Item Database](#20-systemsitem_registrypy)
21. [systems/lod.py — Level of Detail](#21-systemslodpy)
22. [systems/combat_sim.py — Off-Screen Combat](#22-systemscombat_simpy)
23. [systems/zone_sim.py — Off-Screen Simulation](#23-systemszone_simpy)
24. [systems/dialogue_gen.py — Dialogue Generation](#24-systemsdialogue_genpy)
25. [scenes/world/topdown.py — Top-Down View](#25-scenesworldtopdownpy)
26. [scenes/world/firstperson.py — First-Person View](#26-scenesworldfirstpersonpy)
27. [scenes/world/fp_renderer.py — Renderer Object](#27-scenesworldfp_rendererpy)
28. [scenes/world/fp_walls.py — Wall Drawing](#28-scenesworldfp_wallspy)
29. [scenes/world/fp_surfaces.py — Floor/Ceiling/Tint](#29-scenesworldfp_surfacespy)
30. [scenes/world/fp_entities.py — Billboard Entities](#30-scenesworldfp_entitiespy)
31. [scenes/world/fp_interact.py — FP Interaction](#31-scenesworldfp_interactpy)
32. [scenes/world/fp_hud.py — Heads-Up Display](#32-scenesworldfp_hudpy)
33. [scenes/world/fp_lighting.py — Lighting & Fog](#33-scenesworldfp_lightingpy)
34. [scenes/world/fp_perflog.py — Performance Logger](#34-scenesworldfp_perflogpy)
35. [scenes/editor.py — Map Editor](#35-sceneseditorpy)
36. [scenes/ — Menu Scenes](#36-scenes--menus)
37. [scenes/ — Debug/Exhibit Scenes](#37-scenes--debug--exhibits)
38. [ui/ — Modal UI System](#38-ui--modal-system)
39. [data/ — TOML Data Files](#39-data--toml-data)
40. [zones/ — Zone JSON Maps](#40-zones--json-maps)
41. [logic/ and simulation/ — Stub Directories](#41-logic-and-simulation)
42. [main.py — Entry Point](#42-mainpy)
43. [Cross-Cutting Concerns](#43-cross-cutting-concerns)
44. [Architectural Issues Summary](#44-architectural-issues-summary)
45. [Recommendations](#45-recommendations)

---

## 1. High-Level Architecture

```
main.py
  └─ App  (core/app.py)
       ├─ Scene stack  (push/pop)
       │    ├─ MainMenu → SaveSlotMenu → TopDown ↔ FirstPerson
       │    ├─ PauseMenu (overlay)
       │    ├─ SettingsMenu (overlay)
       │    ├─ DebugMenu → ExhibitLOD / LiveLOD / MapEditor
       │    └─ CombatExhibit (legacy, broken imports)
       ├─ World  (core/ecs.py)
       │    ├─ Entities (int IDs, component stores)
       │    ├─ Resources (typed singletons)
       │    ├─ EventBus (subscribe/emit/flush)
       │    └─ Zone index (auto-updated)
       └─ Session  (core/session.py)
            ├─ Zone loading / portal transitions
            ├─ Save / Load
            ├─ ZoneSim (off-screen zones)
            ├─ BeastSpawner
            └─ WorldClock, Timers, Restocking
```

**Key design patterns:**
- **Custom ECS**: entities are plain ints, typed `Component` dataclasses, a `Resources` singleton store.
- **Scene stack**: App pushes/pops `Scene` instances. Overlays (pause, settings) sit on top of gameplay.
- **Dual-LOD**: Fine-grained `Position` (float) for active zone, `CoarsePos` (int tile) for off-screen simulation.
- **Monkey-patching**: FP sub-modules attach free functions to the `FirstPerson` and `Renderer` classes at import time.
- **Data-driven**: TOML for item/character/tuning definitions, JSON for zone maps, prefab-based spawning.
- **Procedural textures**: All textures generated at runtime (64×64 per tile type).

---

## 2. core/ecs.py

**Purpose:** Custom Entity Component System — the backbone of the entire game state.

**Key classes/functions:**
| Symbol | Signature | Notes |
|--------|-----------|-------|
| `Component` | `@dataclass` base | `_persist: ClassVar[bool] = False` flag for save/load |
| `Resources` | `.set(obj)`, `.get(T)`, `.try_get(T)` | Typed singleton store keyed by class |
| `World` | `.spawn() → int`, `.kill(eid)`, `.purge()` | Entity lifecycle |
| | `.add(eid, comp)`, `.get(eid, T)`, `.has(eid, T)`, `.remove(eid, T)` | Component CRUD |
| | `.query(*types)`, `.query_one(*types)` | Typed queries with `@overload` |
| | `.query_zone(zone, *types)` | Zone-scoped query |
| | `.all_of(T)` | Iterate all entities with component T |
| | `.zone_entities(zone)` | Returns entity set from zone index |
| | `.events` | `EventBus` instance |

**Connections:** Imported by virtually every module. `components/__init__.py` defines all concrete components. `core/save.py` reads `_persist` flags.

**Issues:**
- **Zone index coupling**: `add()` auto-updates the zone index when it detects a `Position` component by checking `hasattr(comp, 'zone')`. This is a fragile duck-typing check — `CoarsePos` also has `.zone` but is NOT indexed the same way. The index only tracks `Position`-based entities.
- **O(n) queries**: `query()` and `all_of()` iterate over all entities. No spatial acceleration.
- **EventBus embedded in World**: The `EventBus` is an attribute of `World`, coupling event infrastructure to the ECS.

---

## 3. core/types.py

**Purpose:** Shared enums.

| Symbol | Values |
|--------|--------|
| `Direction` | `UP`, `DOWN`, `LEFT`, `RIGHT` |
| `EntityKind` | `PLAYER`, `NPC`, `ITEM`, `CONTAINER`, `DUMMY`, `BEAST`, `GROUND_ITEM`, `CROP` |

**Issues:** Minimal — this is clean. `EntityKind` is used everywhere for identity tagging.

---

## 4. core/tiles.py

**Purpose:** Flag-based tile system. Defines all 35 built-in tile types.

**Key symbols:**
| Symbol | Type | Notes |
|--------|------|-------|
| `TF` | `IntFlag` | `SOLID`, `WALL`, `TRANSPARENT`, `LIQUID`, `FARMLAND`, `HALF_WALL`, `PLATFORM` |
| `TileDef` | `@dataclass` | `id, name, color, flags, texture_key, height_scale` |
| `TILE_DEFS` | `list[TileDef]` | 35 entries (indices 0–34) |
| `SOLID_IDS`, `WALL_IDS`, `HALF_WALL_IDS`, `PLATFORM_IDS`, `DOOR_IDS` | `frozenset[int]` | Pre-computed lookup sets |
| `TILE_COLORS` | `dict[int, tuple]` | tile_id → RGB |
| `TILE_NAMES` | `dict[int, str]` | tile_id → display name |
| `tile_def(id)` | `→ TileDef | None` | Lookup by ID |

**Connections:** Used by rendering (textures, raycaster, surfaces), physics (collision), editor, zone loading.

**Issues:**
- The tile registry is static (list initialized at module level). No clean way to add mod tiles.
- `height_scale` is baked into `TileDef` but only consumed by the raycaster.

---

## 5. core/constants.py

**Purpose:** Global numeric constants and legacy tile ID aliases.

| Symbol | Value | Notes |
|--------|-------|-------|
| `TILE_SIZE` | 32 | Pixels per tile in top-down view |
| `DAY_LENGTH` | 300.0 | Seconds for a full day cycle |
| `TILE_METRES` | 1.0 | 1 tile = 1 metre |
| `TILE_VOID` … `TILE_RAILING` | 0–34 | Legacy aliases re-exported from `core.tiles` |

**Issues:**
- **Two systems for tile IDs**: `TILE_WALL`, `TILE_STONE`, etc. are legacy aliases that duplicate the `TileDef.id` values in `tiles.py`. Dangerous — if tile ordering changes, these break silently.
- `DAY_LENGTH` is defined here *and* `tuning.toml` has its own time constants. Dual source of truth.

---

## 6. core/zones.py

**Purpose:** Load zone data from `zones/<name>.json`.

| Symbol | Signature | Notes |
|--------|-----------|-------|
| `Portal` | `@dataclass(target_zone, target_row, target_col, tiles, exit_direction)` | Portal definition |
| `Zone` | `@dataclass(name, width, height, tiles, anchor, portals, entities, first_person)` | Full zone data |
| `load_zone(name)` | `→ Zone` | Reads and parses JSON |
| `list_zones()` | `→ list[str]` | Glob `zones/*.json` |

**Connections:** Used by `Session`, `ZoneSim`, `ExhibitLOD`, `LiveLOD`, `Editor`.

**Issues:**
- Every call to `load_zone()` re-reads and re-parses the JSON file from disk. No caching.
- Portal `exit_direction` defaults to `"up"` — overloaded meaning.

---

## 7. core/scene.py

**Purpose:** Abstract base class for all scenes.

```python
class Scene:
    def on_enter(self, app): ...
    def on_exit(self, app): ...
    def handle_event(self, event, app): ...
    def update(self, dt, app): ...
    def draw(self, surface, app): ...
```

**Issues:** Clean and minimal. No issues.

---

## 8. core/app.py

**Purpose:** Pygame initialization, main loop, scene stack management.

| Symbol | Signature | Notes |
|--------|-----------|-------|
| `App.__init__` | `(title, width, height)` | `pygame.SCALED` display, 3 font sizes, `World` instance |
| `.push_scene(s)` | | Calls `on_enter` |
| `.pop_scene()` | | Calls `on_exit`, then `on_enter` on new top |
| `.clear_scenes()` | | Pop all |
| `.run()` | | Main loop: events → update → draw, 100 FPS cap |
| `.toggle_fullscreen()` | | F11 |
| `.draw_text()`, `.draw_text_bg()` | | Text rendering helpers |
| `.mouse_pos()` | | Virtual-resolution-aware mouse position |

**Connections:** Owns the `World` instance. Passed to every Scene method.

**Issues:**
- **App owns World**: The ECS `World` is an attribute of `App`, meaning it persists across scenes. This is intentional (shared state between TopDown ↔ FirstPerson), but `ExhibitLOD` creates its own separate `World`, leading to two patterns.
- **Scene stack is `list[Scene]`** stored as `app._scenes` (underscore = private), but `SaveSlotMenu` directly manipulates `len(app._scenes)` to pop back to the menu. Encapsulation leak.
- **dt smoothing**: dt is capped at 0.05s and alpha-smoothed. This is good for frame-rate stability.

---

## 9. core/session.py

**Purpose:** Owns the full game-state pipeline: zone loading, portal transitions, save/load, world clock, background simulation.

**Key class: `Session`** (~512 lines)

| Method | Signature | Notes |
|--------|-----------|-------|
| `new_game(start_zone)` | | Spawns entities, sets up zone |
| `save(slot)` / `load(slot)` | | Delegates to `core.save` |
| `check_portals(dt)` | | Detects player on portal tiles, starts fade |
| `update_transition(dt)` | | Fade-out → teleport → fade-in state machine |
| `_execute_teleport()` | | Moves player, demotes old zone, promotes new zone, rebuilds transients |
| `tick_world(dt)` | | WorldClock, Timers, ZoneSim, BeastSpawner, restocking |

**Connections:** Used by `TopDown` and `FirstPerson` as their shared state owner. Imports `systems/lod`, `systems/zone_sim`, `systems/beast_spawner`, `systems/spawner`, `core/save`.

**Issues:**
- **God object tendency**: Session manages zone loading, portal transitions (with a 4-state fade machine), save/load, world clock, timer ticking, beast spawning, and item restocking. It's ~512 lines and growing.
- **`ALL_ZONES` hardcoded list**: `ALL_ZONES = ["pawn_shop", "campsite", "crossroads", ...]` is a hardcoded list that must match the `zones/` directory. Should use `list_zones()`.
- **Transition state machine**: The fade-in/fade-out/auto-walk logic uses float states and boolean flags (`_transitioning`, `_transition_phase`, `_auto_walk_timer`). This is complex enough to warrant its own class.
- **`descriptor_index`**: Stores all original entity descriptors by UID so transients can be rebuilt after load. This is a clever pattern but creates a parallel data structure that must stay in sync.

---

## 10. core/events.py

**Purpose:** Lightweight publish-subscribe event bus.

| Symbol | Signature | Notes |
|--------|-----------|-------|
| `EventBus.subscribe(name, callback)` | | Register handler |
| `EventBus.emit(name, **kwargs)` | | Queue event |
| `EventBus.flush()` | | Drain queued events, invoke handlers |
| Events | `EntityDied`, `DamageDealt`, `ZoneTransition`, `ItemPickedUp`, `InteractionEvent` | Named string events |

**Issues:**
- **String-keyed events**: Events are identified by string names, not types. No compile-time safety.
- **No unsubscribe**: No way to remove a listener. If a scene subscribes but the subscription isn't cleaned up, it leaks.
- The `EventBus` lives on `World.events`, coupling it to the ECS layer.

---

## 11. core/save.py

**Purpose:** Serialize/deserialize entities with `_persist = True` components.

| Symbol | Signature | Notes |
|--------|-----------|-------|
| `save_game(world, zone, slot)` | | Writes `saves/slot_N.json` |
| `load_game(slot)` | `→ dict` | Reads JSON |
| `restore_entity(world, entry)` | | Rebuilds entity from save data |
| `has_save(slot)` | `→ bool` | File existence check |
| `delete_save(slot)` | | Remove save file |
| `SAVES_DIR` | `Path` | `saves/` directory |

**Connections:** Called by `Session.save()` / `Session.load()`. Component registry auto-built from `components` module.

**Issues:**
- **Component registry auto-population**: Iterates `components` module attributes to build a `{name: class}` map at import time. If a component is renamed, old saves become unloadable without migration.
- **No versioning**: Save files have no schema version. Adding/removing fields will break old saves silently.
- **Enum handling**: Has special-case code for `Direction` and `EntityKind` enums. This should be generalized.

---

## 12. components/\_\_init\_\_.py

**Purpose:** All component dataclasses and resource singletons.

**Components** (all `@dataclass`):
| Component | Persisted | Key Fields |
|-----------|-----------|------------|
| `Position` | ✅ | `x, y, zone, elevation` |
| `Velocity` | ❌ | `x, y` |
| `Facing` | ❌ | `direction: Direction` |
| `Collider` | ❌ | `w, h, solid` |
| `Sprite` | ❌ | `char, color, layer` |
| `Identity` | ❌ | `name, kind: EntityKind, tags: set` |
| `Health` | ✅ | `current, maximum` |
| `Inventory` | ✅ | `items: dict[str, int]` |
| `TileEntity` | ✅ | `tile_type, tiles, item_id, item_qty, loot_table, looted` |
| `PrefabRef` | ✅ | `prefab, uid` |
| `Player` | ❌ | `speed` |
| `CoarsePos` | ✅ | `row, col, zone, speed` |
| `Timers` | ✅ | `active: dict[str, float]` |
| `CombatStats` | ✅ | `damage, defense, cooldown` |

**Resources:**
| Resource | Key Fields |
|----------|------------|
| `Camera` | `x, y, zoom` |
| `GameClock` | `time, paused` |
| `WorldClock` | `elapsed, day_phase, day, time_scale` |
| `WorldEventEntry` | `message, zone, category, time` |
| `WorldEventLog` | `entries[], unread, capacity` |

**Issues:**
- **`Identity` is not persisted** but contains the entity's name and kind. After load, names are rebuilt from `PrefabRef` + descriptor index. If the descriptor changes, the loaded entity's name changes too.
- **`CombatStats`** only has `damage, defense, cooldown` — it lacks weapon type, range, etc. Combat resolution in `combat_sim.py` is very simplified.
- **`Timers.active`** is a mutable dict stored as a component. Multiple systems write to it (portal cooldowns, movement cooldowns, attack cooldowns, restocking timers). This is a shared mutable state antipattern.

---

## 13. systems/textures.py

**Purpose:** Procedural 64×64 texture generation for all tile types.

**Key class: `TextureAtlas`** (~988 lines)

| Method | Signature | Notes |
|--------|-----------|-------|
| `.get(tile_id)` | `→ Surface` | Lazy-generates texture |
| `.sample(tile_id, u, v)` | `→ (r, g, b)` | Direct pixel lookup (for floor rendering) |

**~30 generator functions**: `_gen_wall`, `_gen_stone`, `_gen_grass`, `_gen_dirt`, `_gen_wood`, `_gen_water`, `_gen_sand`, `_gen_teleporter`, `_gen_metal`, `_gen_concrete`, `_gen_tile_floor`, `_gen_rubble`, `_gen_gateway`, `_gen_bookshelf`, `_gen_crate`, `_gen_barrel`, `_gen_window`, `_gen_pillar`, `_gen_counter_top`, `_gen_railing`, `_gen_carpet`, `_gen_brick_wall`, `_gen_wood_panel`, `_gen_cracked_floor`, `_gen_stone_floor`, `_gen_shelf_wall`, `_gen_stone_platform`, `_gen_wood_platform`, `_gen_metal_platform`, `_gen_crate_stack`, `_gen_table`, `_gen_curb`, `_gen_stool`, `_gen_step`, `_gen_noise`.

Texture key → generator mapping via `_KEY_GENERATORS` dictionary.

**Connections:** Used by `fp_walls.py` (wall column texturing), `fp_surfaces.py` (floor color sampling), `fp_entities.py` (prop textures).

**Issues:**
- **988 lines** of procedural pixel art. Each generator is ~20-40 lines of manual pixel manipulation. This works but is hard to iterate on visually.
- **No hot-reload**: Textures are generated once and cached. Changing a generator requires restarting.
- Textures are Pygame `Surface` objects — no GPU atlas. Each `sample()` call does a Python-level pixel lookup.

---

## 14. systems/raycaster.py

**Purpose:** DDA raycasting algorithm for wall rendering.

| Symbol | Signature | Notes |
|--------|-----------|-------|
| `WallSlice` | `namedtuple` | One vertical wall column's data |
| `BillboardSprite` | `namedtuple` | Projected entity billboard |
| `cast_walls(px, py, angle, fov, num_rays, tiles, ...)` | `→ list[WallSlice]` | DDA with half-wall support |
| `project_entities(entities, px, py, angle, fov, sw, sh)` | `→ list[BillboardSprite]` | Billboard projection |

**C extensions:** Optional `_fast_cast` and `_fast_walls` modules provide ~50× speedup. Falls back to pure Python gracefully.

**Connections:** Called by `fp_walls.py` for wall casting, `fp_entities.py` for entity projection.

**Issues:**
- **Height-scale cache**: Uses a dict `_HS_CACHE` keyed by tile array identity (`id(tiles)`). If the tiles list is rebuilt (e.g., zone reload), the cache is invalidated by identity, which is correct but fragile.
- **Flattened tile array**: For the C extension, tiles are flattened to a 1D list and cached. This is rebuilt when `id(tiles)` changes.
- **Trig caching**: Precomputes `cos_table` and `sin_table` per call. Could be cached more aggressively.

---

## 15. systems/physics.py

**Purpose:** WASD movement with axis-separated wall collision.

| Symbol | Signature | Notes |
|--------|-----------|-------|
| `movement_system(world, dt, tiles, portal_tiles)` | | Moves entities, resolves collisions |
| `_hits_wall(x, y, w, h, tiles)` | `→ bool` | AABB-vs-solid-tile check |

**Features:** Axis-separated collision (move X, test, revert; move Y, test, revert). Doorway magnetism nudges the player toward portal tile centers for easier traversal.

**Issues:**
- **Portal magnetism** is a neat idea but it's tightly coupled to the portal detection logic in `Session.check_portals()`. Two systems both need to know about portal tile positions.
- Only handles solid tiles. No slope, height, or trigger volumes.

---

## 16. systems/pathfinding.py

**Purpose:** A\* pathfinding, BFS flood fill, and line-of-sight.

| Symbol | Signature | Notes |
|--------|-----------|-------|
| `astar(tiles, start, goal)` | `→ list[tuple[int,int]]` | A\* with Manhattan heuristic |
| `bfs_reachable(tiles, start)` | `→ set` | Flood fill |
| `random_walkable(tiles)` | `→ (r,c)` | Random non-solid tile |
| `visible_tiles(tiles, r, c, max_range)` | `→ set` | Bresenham LOS rays |
| `entities_in_los(world, eid, max_range)` | `→ list[int]` | Entities visible to eid |
| `_bresenham_los(tiles, r0,c0, r1,c1)` | `→ bool` | Line-of-sight check |

**Connections:** Used by `ZoneSim` for coarse NPC movement and sight, `CombatExhibit` (legacy).

**Issues:**
- **Pure Python A\***: For large zones, this could be slow. ZoneSim caches paths but the pathfinder itself could benefit from a C extension.
- `visible_tiles()` casts rays in all integer directions within range — this is O(range²) per call.

---

## 17. systems/interaction.py

**Purpose:** Find nearest interactable entity and emit interaction events.

| Symbol | Signature | Notes |
|--------|-----------|-------|
| `nearest_interactable(world)` | `→ (eid, dist) | None` | Facing-direction filtered, `INTERACT_RANGE = 1.8` |
| `try_interact(world, events)` | `→ bool` | Emits `InteractionEvent` |
| `set_camera_angle(angle)` | | Module-level mutable state for FP camera override |

**Issues:**
- **Module-level mutable state**: `_camera_angle` is a module global modified by `set_camera_angle()`. This is implicit shared state between `FirstPerson` and the interaction system.

---

## 18. systems/spawner.py

**Purpose:** Data-driven entity spawning with prefab defaults.

| Symbol | Signature | Notes |
|--------|-----------|-------|
| `spawn_from_descriptor(world, desc, zone)` | `→ int` | Spawn entity from dict descriptor |
| `spawn_zone_entities(world, entities, zone)` | `→ list[int]` | Batch spawn |
| `rebuild_transients(world, descriptor_index)` | | Post-load: re-attach non-persistent components |
| `_PREFAB_DEFAULTS` | `dict[str, dict]` | ~18 prefabs (npc, merchant, container, crop, etc.) |

**Connections:** Used by `Session.new_game()`, `Session._execute_teleport()`, `fp_interact.py` (ground item spawning).

**Issues:**
- **Prefab defaults hardcoded in Python**: `_PREFAB_DEFAULTS` is a large dict literal in the source. Should arguably live in a TOML/JSON file for data-driven configuration.
- **`_merged()` helper** is defined as a local function inside `spawn_from_descriptor` and again inside `rebuild_transients`. Duplicated merge logic.

---

## 19. systems/beast_spawner.py

**Purpose:** Periodically spawns hostile beasts in outdoor zones.

| Symbol | Signature | Notes |
|--------|-----------|-------|
| `BeastSpawner` | class | `tick(dt, world, active_zone)` |
| `OUTDOOR_ZONES` | `frozenset` | `outskirts, crossroads, campsite, playground` |
| `MAX_BEASTS_PER_ZONE` | 3 | Hard cap |
| `SPAWN_INTERVAL` | 45s | |
| Templates | 3 | Feral Dog, Rad-Rat, Wasteland Crawler |

**Issues:**
- **Hardcoded zone list**: `OUTDOOR_ZONES` duplicates the zone names that also appear in `Session.ALL_ZONES`. Zone metadata (indoor/outdoor, biome) should live in zone data.
- Beast templates are dicts hardcoded in the class. Should be data-driven.

---

## 20. systems/item_registry.py

**Purpose:** Load item definitions from `data/items.toml`.

| Symbol | Signature | Notes |
|--------|-----------|-------|
| `ItemDef` | `@dataclass` | `id, data` (raw TOML dict) |
| `ItemRegistry` | class | `.ids()`, `.get(id)`, `.display_name(id)`, `.item_type(id)`, `.to_descriptor(id)` |

**Issues:**
- **Thin wrapper**: `ItemDef` is essentially `(id, raw_dict)`. No typed fields for damage, heal, etc. All access goes through `data.get("field")`.
- Loaded once at construction, no hot-reload.

---

## 21. systems/lod.py

**Purpose:** Level-of-detail transitions: promote (coarse → fine) and demote (fine → coarse).

| Symbol | Signature | Notes |
|--------|-----------|-------|
| `promote(world, eid)` | | `CoarsePos` → `Position` (float coords from tile center) |
| `demote(world, eid)` | | `Position` → `CoarsePos` (quantize to tile) |
| `sync_zone_lod(world, active_zone)` | | Bulk promote active zone NPCs, demote others |
| `tick_timers(world, dt)` | | Decrement all `Timers.active` entries, remove expired |

**Issues:**
- `tick_timers()` is in `lod.py` — it has nothing to do with LOD. It's misplaced here.
- `sync_zone_lod` skips entities that are `Player`-tagged, which is correct but implicit.

---

## 22. systems/combat_sim.py

**Purpose:** Off-screen (coarse) combat resolution.

| Symbol | Signature | Notes |
|--------|-----------|-------|
| `resolve_coarse_combat(world, eid_a, cp_a, eid_b, cp_b, tiles)` | | Damage exchange between entities in LOS |

**Features:** Damage with ±20% variance, CombatStats-based defense, attack cooldown via `Timers`, death handling (kill entity, emit event, add to event log).

**Issues:**
- Very simplified: no weapon types, no positioning, no cover, no factions. Any two entities in LOS fight automatically.
- Called from `ZoneSim._sight_checks()` which does O(n²) pairwise checks per zone tick.

---

## 23. systems/zone_sim.py

**Purpose:** Off-screen zone simulation. NPCs move, see each other, fight, and use portals in zones the player isn't in.

**Key class: `ZoneSim`** (~431 lines)

| Symbol | Signature | Notes |
|--------|-----------|-------|
| `ZoneSim.__init__(world, tick_interval)` | | Default 2.0s tick |
| `.load_zone(name)` | | Cache tiles + portals for a zone |
| `.accumulate(dt)` | | Tick all off-screen zones |
| `.tick_zone(zone_name)` | | Portal checks, A\* movement, sight checks, combat |

**`ZoneCache`**: `@dataclass(tiles, width, height, portals, walkable)`.

**Connections:** `Session.tick_world()` drives it. Uses `pathfinding.astar()`, `combat_sim.resolve_coarse_combat()`.

**Issues:**
- **2-second tick interval** means NPCs move at most once per 2 seconds (they take 1-step A\* paths). This feels sluggish compared to real-time.
- **All NPC targets are random walkable tiles** — there's no goal-directed behavior (e.g., go home, patrol routes, go to work).
- **Portal traverse for NPCs**: NPCs can teleport between zones, which is cool, but there's no scheduling or intentionality — they stumble onto portals.

---

## 24. systems/dialogue_gen.py

**Purpose:** Procedurally generates dialogue trees based on context.

| Symbol | Signature | Notes |
|--------|-----------|-------|
| `build_npc_dialogue(world, npc_eid)` | `→ dict` | Contextual dialogue tree |

**Features:** Considers time-of-day, NPC health, zone, recent world events. Branches for trade, give item, ask about events. Returns a dict tree consumed by `DialogueModal`.

**Issues:**
- Dialogue is generated from hardcoded Python templates. Not data-driven.
- The tree structure is a raw dict, not a typed model.

---

## 25. scenes/world/topdown.py

**Purpose:** Top-down tile-based gameplay scene. The "overhead" view.

**Key class: `TopDown(Scene)`** (~918 lines)

**Features:** WASD movement, E interact, I inventory, Tab debug, F4 editor, F5/F9 save/load, Enter to switch to FP mode. Tile rendering, entity rendering, camera follow. Platform interaction, ground item pickup, container loot rolling, NPC dialogue.

**Connections:** Creates `Session` or receives it. Can push `FirstPerson`, `PauseMenu`, `MapEditor`.

**Issues:**
- **918 lines** — too large. Mixes input handling, game logic (loot rolling, item pickup), UI concerns (status text, debug overlays), and rendering in one class.
- **Duplicated interaction logic**: Ground item pickup, container opening, and NPC dialogue are implemented *separately* in both `topdown.py` and `fp_interact.py`. The implementations diverge.
- **Direct `app.world` access**: Queries world directly rather than through a system layer. Business logic (loot rolling) is inline.

---

## 26. scenes/world/firstperson.py

**Purpose:** First-person raycasted view. The main gameplay mode.

**Key class: `FirstPerson(Scene)`** (~803 lines)

**Render pipeline:**
1. Floor/ceiling (`fp_surfaces.draw_floor_ceiling`)
2. Walls (`fp_walls.draw_walls`) → returns deferred half-walls
3. Visplane tops (`fp_surfaces.draw_visplane_tops`)
4. Entities interleaved with half-walls (`fp_entities.draw_entities`)
5. Day/night tint (`fp_surfaces.draw_day_night`)
6. Upscale from half-resolution to display
7. HUD (`fp_hud.HUD.draw_hud`)

**Features:** Smooth acceleration/friction movement, sprint, dash (Space), head bob, view sway, mouse look, damage flash, built-in profiler overlay (F6).

**Rendering:** Internal rendering at `_RSCALE = 2` (half resolution), upscaled via `pygame.transform.scale`.

**Connections:** Imports `fp_interact.*` functions as methods. Owns a `Renderer`, `HUD`, `PerfLogger`, `ModalStack`. Uses `Session` for zone/portal logic.

**Issues:**
- **Monkey-patching pattern**: `fp_interact.py` defines free functions like `_do_interact(self, app)` that take `FirstPerson` as the first argument, then are referenced via `fp_interact._do_interact(self, app)` inside `FirstPerson`. This isn't true monkey-patching (they're called explicitly), but it's an unusual pattern that makes the class boundary unclear.
- **Half-resolution rendering**: `_RSCALE = 2` is hardcoded. Not configurable.
- **803 lines**: Manageable given the split to submodules, but `update()` still has complex physics (acceleration, friction, sprint, dash, head bob, view sway, collision) inline.

---

## 27. scenes/world/fp_renderer.py

**Purpose:** Owns GPU-side caches for the FP render pipeline.

**Key class: `Renderer`**

| Feature | Notes |
|---------|-------|
| Strip cache | Generational cache (dict of column Surfaces with free-list recycling) |
| Glyph cache | Font rendering cache |
| Entity canvas | Reusable `Surface` for zero-allocation entity drawing |
| Numpy tile arrays | Pre-computed floor colour arrays |
| `warmup()` | Pre-allocates common caches |

**Connections:** Methods from `fp_walls`, `fp_surfaces`, `fp_entities` are attached to this class's instances at module level via imports.

**Issues:**
- **Method injection pattern**: The Renderer class's methods are actually defined in separate modules (`fp_walls.draw_walls`, `fp_surfaces.draw_floor_ceiling`, etc.) and attached to Renderer instances. This is an uncommon pattern. It means the Renderer class definition doesn't show its full API — you must read 4 separate files to understand what it can do.

---

## 28. scenes/world/fp_walls.py

**Purpose:** Cast rays and draw wall columns with texture mapping.

| Symbol | Signature | Notes |
|--------|-----------|-------|
| `draw_walls(self, surface, ...)` | `→ list` | Returns deferred half-wall slices for painter's ordering |

**Features:** Generational strip cache with free-list recycling. C-accelerated geometry via `_fast_walls`. Handles full walls (batch blitted) and half-walls (deferred). `RAY_STEP = 4` (one ray per 4 pixels).

**Issues:**
- The strip cache logic is complex (~150 lines of cache management). Effective but hard to debug.
- `RAY_STEP = 4` is hardcoded. Should be tunable.

---

## 29. scenes/world/fp_surfaces.py

**Purpose:** Floor, ceiling, and day/night tint rendering.

| Symbol | Signature | Notes |
|--------|-----------|-------|
| `draw_floor_ceiling(self, surface, ...)` | | Numpy-vectorized floor rendering |
| `draw_visplane_tops(self, surface, ...)` | | Doom-style platform top surfaces |
| `draw_day_night(self, surface, ...)` | | Time-based color overlay |

**Features:** Uses numpy for vectorized floor pixel calculations. Tile-accurate floor colours (each pixel samples the correct tile's ground colour). Gradient bands for ceiling. Interior detection to skip ceiling gradient indoors.

**Issues:**
- Floor rendering is the heaviest part of drawing. Numpy helps but it's still per-pixel.
- `draw_visplane_tops()` draws platform top faces — a nice Doom-inspired feature.

---

## 30. scenes/world/fp_entities.py

**Purpose:** Billboard entity rendering interleaved with deferred half-walls.

| Symbol | Signature | Notes |
|--------|-----------|-------|
| `draw_entities(self, surface, ...)` | | Sort + interleave entities and half-wall slices by depth |
| `_draw_one_billboard(...)` | | Shared-canvas rendering (zero Surface allocation per entity) |
| `PROP_GLYPHS` | `dict` | EntityKind → glyph character mapping |
| `ENTITY_VIS` | `dict` | EntityKind → visual tuning (scale, color) |

**Features:** Fog, z-clipping per column, health bars, name tags. Prop textures for items. Shared canvas approach avoids per-entity Surface allocation.

**Issues:**
- **445 lines** for entity drawing — the interleaving with half-walls adds significant complexity.
- Entity visual configuration (`PROP_GLYPHS`, `ENTITY_VIS`) is hardcoded in Python. Should be data-driven.

---

## 31. scenes/world/fp_interact.py

**Purpose:** Interaction logic for FP mode: interact, inventory, containers, loot, platform surfaces.

**Functions (attached to `FirstPerson`):**
| Function | Notes |
|----------|-------|
| `_do_interact(self, app)` | E key handler — finds nearest interactable, dispatches to container/NPC/generic |
| `_open_npc_dialogue(self, app, npc_eid)` | Opens `DialogueModal` |
| `_open_inventory(self, app)` | Opens `InventoryModal` |
| `_spawn_ground_item(self, app, item_id, qty)` | Creates ground item entity near player |
| `_pickup_ground_item(self, app, eid, te)` | Adds to player inventory, kills entity |
| `_open_container(self, app, eid, te)` | Opens `TransferModal`, rolls loot |
| `_try_platform_interact(self, app)` | Raycast to find platform tile, open as container |
| `_get_platform_entity(self, app, col, row, tid)` | Find or create entity for platform tile |
| `_roll_loot(self, table_id)` | Read `loot_tables.toml`, weighted random loot |

**Issues:**
- **`_roll_loot` reads TOML from disk on every call** — no caching of loot table data.
- **Platform entity creation** (`_get_platform_entity`) spawns a new entity for every platform tile the player interacts with, with no cleanup. Over a long session, this could leak entities.
- **Duplicated logic with `topdown.py`**: Both scenes implement their own container opening, loot rolling, and pickup logic.

---

## 32. scenes/world/fp_hud.py

**Purpose:** HUD overlays — health bar, crosshair, minimap, compass, notifications, debug info.

**Key class: `HUD`** (~445 lines)

| Method | Notes |
|--------|-------|
| `draw_hud(surface, app, sw, sh, modals_open, session)` | Health bar, inventory count, crosshair, zone name, world clock, interaction prompt, status label, controls hint |
| `draw_notifications(surface, app)` | Toast notifications from `WorldEventLog` |
| `draw_compass(surface, sw, player_angle)` | Compass bar with labeled cardinal points |
| `draw_minimap(surface, app, px, py, sw, sh, player_angle, session)` | Cached tile minimap with entity dots and FOV cone |
| `draw_debug(surface, app, px, py, player_angle, zone_name)` | FPS, position, entity count, time |

**Connections:** Reads from `WorldClock`, `WorldEventLog`, `GameClock`, interaction system.

**Issues:**
- Minimap cache invalidation uses `id(tiles)` (Python object identity), which works but is fragile.
- 445 lines is reasonable given the scope.

---

## 33. scenes/world/fp_lighting.py

**Purpose:** Pure-function day/night cycle and fog calculations.

| Symbol | Signature | Notes |
|--------|-----------|-------|
| `build_fog_lut(ambient, dn)` | `→ list[int]` | 256-entry fog brightness LUT |
| `compute_fog_params(dn)` | `→ (fog_rate, ambient, fog_lut)` | |
| `day_night_factor(wc)` | `→ float` | 0.0 (night) to 1.0 (day) |
| `lerp_color(a, b, t)` | `→ (r, g, b)` | |

**Issues:** Clean, no pygame dependency. Good separation. Fog LUT cache limited to 8 entries.

---

## 34. scenes/world/fp_perflog.py

**Purpose:** Per-frame CSV performance logger.

**Key class: `PerfLogger`**

| Method | Notes |
|--------|-------|
| `toggle()` / `start()` / `stop()` | Logging lifecycle |
| `begin_frame()` | Reset per-frame row |
| `record(key, value)` | Set column |
| `record_ms(key, seconds)` | Timing in ms |
| `end_frame(fps)` | Flush row to CSV |

**Features:** ~30 CSV columns capturing per-stage timings, cache sizes, entity counts, player state. Zero overhead when inactive (single `if` check).

**Issues:** Clean design. Writes to `logs/perf_<timestamp>.csv`. File handle cleanup in `__del__` (fragile but acceptable).

---

## 35. scenes/editor.py

**Purpose:** Full-featured tile map editor.

**Key class: `MapEditor(Scene)`** (~1822 lines)

**Features:**
- Tile painting with variable brush sizes (1-8)
- Flood fill (Shift+click)
- Eyedropper (Alt+click)
- Entity placement, drag, rename, delete
- **Portal Wizard** — 3-step visual portal linking:
  1. Pick entry direction
  2. Pick destination zone
  3. Click destination tile on a preview map
- Anchor placement
- Minimap overview
- Undo/redo stack
- Zone picker (Tab to list all zones)
- Resize dialog
- New zone creation
- Save to JSON

**Connections:** Reads/writes zone JSON files. Uses tile registry. Independent of ECS (works with raw data).

**Issues:**
- **1822 lines** — the largest file in the codebase. Should be split into submodules (like FP was split).
- **`PortalWizard`** nested class handles a multi-step modal workflow inside the editor scene. This is sophisticated but adds ~300 lines of complex UI state management.
- **Direct JSON manipulation**: The editor works with raw dicts/lists for entities, not ECS components. This means the editor's entity format must stay in sync with the spawner's expected format.
- Screen resolution (960×640) is hardcoded in several places within the wizard and panel drawing code.

---

## 36. scenes/ — Menus

### main_menu.py
`MainMenu(Scene)` — title screen with New Game, Continue, Settings, Quit. Keyboard + mouse navigation.

### pause_menu.py
`PauseMenu(Scene)` — overlay with Resume, Save, Settings, Debug, Main Menu, Quit. Semi-transparent background.

### save_slots.py
`SaveSlotMenu(Scene)` — 3-slot picker for new/load. Shows zone name and play time per slot. Delete confirmation overlay.

### settings_menu.py
`SettingsMenu(Scene)` — FPS cap (30/60/100/uncapped), fullscreen toggle. Settings are session-only (not persisted to disk).

**Issues:**
- All menu scenes follow the same pattern: cursor index, render loop, `_select()` dispatch. Could be generalized into a reusable `MenuScene` base class.
- Settings not persisted to disk — lost on restart.

---

## 37. scenes/ — Debug / Exhibits

### debug_menu.py
`DebugMenu(Scene)` — accessible from pause menu. Links to LOD Exhibit, Live LOD Viewer, Map Editor.

### live_lod.py
`LiveLOD(Scene)` — read-only LOD state viewer for the current session. Shows minimap per zone with entity dots (promoted/fine vs demoted/coarse). Zone tab navigation.

### exhibit_lod.py
`ExhibitLOD(Scene)` — standalone sandbox (~830 lines). Creates its own `World`, spawns NPCs, demonstrates portal transitions and dual-LOD simulation. Split-screen: active zone on left, off-screen coarse view on right. Useful for testing but large.

### exhibits/combat_exhibit.py  
`CombatExhibit` (~246 lines) — **BROKEN**. Imports non-existent modules:
```python
from components.ai import VisionCone
from components.combat import Combat, Projectile
from components.social import Faction
from logic.systems import movement_system
from logic.brains import run_brains
from logic.projectiles import projectile_system
from logic.combat import handle_death, npc_melee_attack, npc_ranged_attack
from scenes.exhibits.base import Exhibit
from scenes.exhibits.helpers import spawn_combat_npc
```
These modules (`components.ai`, `components.combat`, `components.social`, `logic.systems`, `logic.brains`, `logic.projectiles`, `logic.combat`, `scenes.exhibits.base`, `scenes.exhibits.helpers`) do not exist in the current codebase. This file is leftover from a previous architecture and will crash on import.

---

## 38. ui/ — Modal System

### modal.py
`Modal` abstract base with `handle_event()`, `update()`, `draw()`. `ModalStack` manages push/pop, routes events to top modal, draws all layers.

### dialogue_modal.py
`DialogueModal(Modal)` — tree-based NPC dialogue with choices. Navigates nodes, executes actions (close, open_trade, set_flag, heal).

### inventory_modal.py
`InventoryModal(Modal)` — player bag view. Use consumable (heals), drop single/stack, mouse and keyboard support.

### transfer_modal.py
`TransferModal(Modal)` — two-panel container ↔ player transfer. Move items left/right, keyboard and mouse.

### commands.py
Frozen dataclass commands: `CloseModal`, `HealPlayer`, `OpenTrade`, `SetFlag`. Used as return values from modal actions.

### helpers.py
`sorted_items()`, `draw_overlay()`, `draw_title_bar()`, `draw_item_row()` — shared UI drawing utilities.

**Issues:**
- The command pattern (`commands.py`) is used by `DialogueModal` but the commands are handled inline in `FirstPerson` and `TopDown`. There's no command dispatcher.
- `InventoryModal` and `TransferModal` directly mutate `Inventory.items` dicts. No event emission for item changes.

---

## 39. data/ — TOML Data Files

### items.toml (~180 lines)
13 items: knife, hoe, bat (melee weapons), pistol, rifle, shotgun (ranged), canned_beans, dried_meat, stew, ration (consumables), bandages, antibiotics (medical). Each has type, style, damage/heal stats, identity, sprite.

### characters.toml (~699 lines)
Full NPC definitions with components: identity, subzone_pos, home, spawn_info, brain, home_range, sprite, health, combat_stats, hunger, inventory, equipment, faction, dialogue. References modules that **don't exist** in the current codebase (SubzonePos, Brain, HomeRange, Hunger, Equipment, Faction, Dialogue components).

**This is a forward-looking data file** — the components it references (Brain, Faction, Hunger, etc.) haven't been implemented yet. Currently unused by any code.

### portals.toml
3 portal definitions linking settlement ↔ road ↔ ruins. References zones (settlement, road, ruins, overworld, test) that **don't exist** as JSON files in `zones/`.

**Currently unused** — portals are defined in zone JSON files, not this TOML.

### subzones.toml (~195 lines)
15 subzone nodes across 3 zones (settlement, road, ruins) with connections, threat levels, resources, shelter flags, visibility. Graph-based world topology.

**Currently unused** — the ZoneSim operates on tile-level data, not subzone nodes.

### tuning.toml (~310 lines)
Comprehensive gameplay constants: melee combat, ranged combat, engagement FSM (chase, attack, flee, strafe), detection ranges, faction disposition, NPC needs, day/night cycle, farming, economy, LOD budgets. Well-structured with SI units documented.

**Partially unused** — many values reference systems that don't exist yet (Brain FSM, factions, farming, economy).

### loot_tables.toml
3 tables: `basic_chest` (food/medical), `treasure_chest` (weapons + supplies), `empty_chest`. Minecraft-style weighted random pools.

---

## 40. zones/ — JSON Maps

6 zone files: `pawn_shop.json`, `campsite.json`, `crossroads.json`, `house_interior.json`, `outskirts.json`, `playground.json`.

Each contains: `name`, `width`, `height`, `tiles` (2D int array), `anchor` (spawn point), `portals` (with target_zone/row/col/exit_direction), `entities` (spawn descriptors), `first_person` (boolean).

**Issues:**
- Zone sizes vary (playground is largest at ~30×20, pawn_shop is 14×12). All small enough for A\* without issues.
- `portals.toml` defines portals for zones that don't exist as JSON files. The actual portals are embedded in the zone JSON files.

---

## 41. logic/ and simulation/

### logic/
Contains only `brains/` subdirectory with an empty `__pycache__/`. No source files. This was likely a previous architecture for NPC AI brains that has been removed or never completed.

### simulation/
Contains only `__pycache__/`. No source files. Another stub/leftover directory.

**These directories should be removed** or documented as planned future work.

---

## 42. main.py

```python
from core.app import App
from scenes.main_menu import MainMenu

def main():
    app = App(title="Shopkeeper", width=960, height=640)
    app.push_scene(MainMenu())
    app.run()

if __name__ == "__main__":
    main()
```

Clean bootstrap. 18 lines. No issues.

---

## 43. Cross-Cutting Concerns

### 43.1 Duplicated Logic
The most significant architectural issue is **duplicated game logic between TopDown and FirstPerson**:
- Ground item pickup
- Container opening and loot rolling
- NPC dialogue initiation
- Inventory management
- Portal transition detection

Both scenes implement these independently, leading to potential divergence.

### 43.2 Data Files vs. Code Disconnect
Several TOML data files reference systems/components that don't exist:
- `characters.toml` → Brain, Faction, Hunger, SubzonePos, HomeRange, Equipment, Dialogue
- `portals.toml` → zones that don't exist (settlement, road, ruins)
- `subzones.toml` → subzone topology system (not implemented)
- `tuning.toml` → engagement FSM, factions, farming, economy (not implemented)

These appear to be forward-looking designs for a simulation layer that hasn't been built yet.

### 43.3 Hardcoded Zone Lists
Zone names are hardcoded in multiple places:
- `Session.ALL_ZONES`
- `BeastSpawner.OUTDOOR_ZONES`
- `ExhibitLOD` default zone selection

Should use `list_zones()` and zone metadata.

### 43.4 Module-Level Mutable State
Several modules use module-level mutable globals:
- `interaction.py`: `_camera_angle`
- `raycaster.py`: `_HS_CACHE`, `_FLAT_CACHE`
- `fp_lighting.py`: `_fog_lut_cache`
- `textures.py`: `TextureAtlas` caches

This makes testing and multi-instance scenarios difficult.

### 43.5 Dead Code
- `scenes/exhibits/combat_exhibit.py` — broken imports, cannot run
- `logic/` and `simulation/` directories — empty
- `logic/brains/` — empty
- `data/portals.toml` and `data/subzones.toml` — unused by any code
- `data/characters.toml` — references unimplemented components

---

## 44. Architectural Issues Summary

| Severity | Issue | Location |
|----------|-------|----------|
| 🔴 High | Duplicated game logic between TopDown and FirstPerson | `topdown.py`, `fp_interact.py` |
| 🔴 High | `combat_exhibit.py` has broken imports (will crash) | `scenes/exhibits/combat_exhibit.py` |
| 🟡 Medium | `Session` is a god object (~512 lines, 7+ responsibilities) | `core/session.py` |
| 🟡 Medium | `editor.py` is 1822 lines — needs decomposition | `scenes/editor.py` |
| 🟡 Medium | `topdown.py` is 918 lines with mixed concerns | `scenes/world/topdown.py` |
| 🟡 Medium | Hardcoded zone lists in 3+ locations | session.py, beast_spawner.py, exhibit_lod.py |
| 🟡 Medium | No save-file versioning | `core/save.py` |
| 🟡 Medium | `_roll_loot` reads TOML from disk per call | `fp_interact.py` |
| 🟡 Medium | Dead code and stale data files | `combat_exhibit.py`, `logic/`, `simulation/`, `portals.toml` |
| 🟡 Medium | `_PREFAB_DEFAULTS` hardcoded in Python, not data | `systems/spawner.py` |
| 🟢 Low | `tick_timers()` misplaced in `lod.py` | `systems/lod.py` |
| 🟢 Low | Module-level mutable state in interaction, raycaster | Multiple |
| 🟢 Low | String-keyed events with no unsubscribe | `core/events.py` |
| 🟢 Low | Settings not persisted to disk | `scenes/settings_menu.py` |
| 🟢 Low | `load_zone()` re-reads JSON every call (no cache) | `core/zones.py` |
| 🟢 Low | Menu scenes share identical cursor/render pattern | `scenes/*.py` |

---

## 45. Recommendations

### Priority 1 — Fix Broken Code
1. **Remove or fix `combat_exhibit.py`**. It imports 9 non-existent modules.
2. **Clean up `logic/` and `simulation/` directories** — remove or add a README noting planned work.

### Priority 2 — Reduce Duplication
3. **Extract shared gameplay logic** (pickup, container, dialogue, loot) into a `systems/gameplay.py` or similar module that both TopDown and FirstPerson call.
4. **Generalize menu scenes** with a `MenuScene` base class to eliminate the repeated cursor/render/select pattern.

### Priority 3 — Decompose Large Files
5. **Split `editor.py`** into submodules: `editor_core.py`, `editor_draw.py`, `editor_wizard.py`, `editor_entities.py`.
6. **Split `topdown.py`** into input handling, rendering, and gameplay logic modules (following the FP pattern).
7. **Extract transition logic from `Session`** into a `TransitionManager` class.

### Priority 4 — Data-Driven Improvements
8. **Move `_PREFAB_DEFAULTS`** to a TOML/JSON file.
9. **Move beast templates** to data files.
10. **Cache loot tables** on first read instead of re-reading TOML per container open.
11. **Add zone metadata** (indoor/outdoor, biome, display name) to zone JSON files to eliminate hardcoded zone lists.

### Priority 5 — Robustness
12. **Add save-file versioning** with a migration system.
13. **Cache `load_zone()` results** — zone data is immutable at runtime.
14. **Persist settings** to `settings.json`.

### Priority 6 — Future Architecture
15. The TOML data files (characters.toml, subzones.toml, tuning.toml) outline an ambitious simulation layer with NPC brains, factions, needs, farming, and economy. When implementing these, use the existing ECS + data-driven patterns rather than the abandoned `logic/brains` approach.
