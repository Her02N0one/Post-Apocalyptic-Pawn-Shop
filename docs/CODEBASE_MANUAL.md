# Post-Apocalyptic Pawn Shop — Codebase Manual

> **Comprehensive instruction manual for the entire project.**
---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Technology Stack & Dependencies](#2-technology-stack--dependencies)
3. [Directory Structure](#3-directory-structure)
4. [Core Architecture](#4-core-architecture)
   - 4.1 [Application Shell (`core/app.py`)](#41-application-shell)
   - 4.2 [Entity-Component System (`core/ecs.py`)](#42-entity-component-system)
   - 4.3 [Event Bus (`core/events.py`)](#43-event-bus)
   - 4.4 [Scene System (`core/scene.py`)](#44-scene-system)
   - 4.5 [Type Definitions (`core/types.py`)](#45-type-definitions)
   - 4.6 [Path Constants (`core/paths.py`)](#46-path-constants)
   - 4.7 [Global Constants (`core/constants.py`)](#47-global-constants)
   - 4.8 [Font Cache (`core/fonts.py`)](#48-font-cache)
5. [Tile System (`core/tiles/`)](#5-tile-system)
6. [Zone System (`core/zones/`)](#6-zone-system)
7. [Entity Definitions (`core/entity_defs.py`)](#7-entity-definitions)
8. [Components (`components/`)](#8-components)
9. [Session & World Ticker](#9-session--world-ticker)
   - 9.1 [Session (`core/session.py`)](#91-session)
   - 9.2 [Zone Transitions (`core/transition.py`)](#92-zone-transitions)
   - 9.3 [World Ticker (`core/world_ticker.py`)](#93-world-ticker)
10. [Save System (`core/save.py`)](#10-save-system)
11. [Cell Presets (`core/presets.py`)](#11-cell-presets)
12. [Engine](#12-engine)
    - 12.1 [Raycaster (`engine/raycaster.py`)](#121-raycaster)
    - 12.2 [Ray Renderer (`engine/ray_renderer.py`)](#122-ray-renderer)
    - 12.3 [Texture Atlas (`engine/textures.py`)](#123-texture-atlas)
    - 12.4 [C Extensions](#124-c-extensions)
13. [Entity Texture Pipeline](#13-entity-texture-pipeline)
    - 13.1 [Billboard Sprite Sheets](#131-billboard-sprite-sheets)
    - 13.2 [Prism Net Textures](#132-prism-net-textures)
    - 13.3 [TOML Sidecar Format](#133-toml-sidecar-format)
    - 13.4 [Texture Key Scheme](#134-texture-key-scheme)
    - 13.5 [Generator Script (`gen_entity_textures.py`)](#135-generator-script)
14. [Systems](#14-systems)
    - 14.1 [Spawner](#141-spawner)
    - 14.2 [Physics](#142-physics)
    - 14.3 [LOD (Level of Detail)](#143-lod)
    - 14.4 [Zone Simulator](#144-zone-simulator)
    - 14.5 [Pathfinding](#145-pathfinding)
    - 14.6 [Combat](#146-combat)
    - 14.7 [Interaction & Gameplay](#147-interaction--gameplay)
    - 14.8 [Items & Loot](#148-items--loot)
    - 14.9 [Dialogue](#149-dialogue)
    - 14.10 [Beast Spawner](#1410-beast-spawner)
15. [Game Scenes](#15-game-scenes)
    - 15.1 [Main Menu](#151-main-menu)
    - 15.2 [Top-Down View](#152-top-down-view)
    - 15.3 [First-Person View](#153-first-person-view)
    - 15.4 [HUD](#154-hud)
    - 15.5 [Pause & Settings](#155-pause--settings)
    - 15.6 [Debug Scenes](#156-debug-scenes)
16. [UI System](#16-ui-system)
17. [Zone Editor](#17-zone-editor)
    - 17.1 [Architecture & Composition](#171-architecture--composition)
    - 17.2 [Input System](#172-input-system)
    - 17.3 [Command Bus](#173-command-bus)
    - 17.4 [3D Viewport Renderer](#174-3d-viewport-renderer)
    - 17.5 [Selection System](#175-selection-system)
    - 17.6 [Tool Mixins](#176-tool-mixins)
    - 17.7 [Panels & UI](#177-panels--ui)
    - 17.8 [Undo System](#178-undo-system)
18. [Data Files](#18-data-files)
19. [Build System](#19-build-system)
20. [Testing](#20-testing)
21. [Complete Data Flow](#21-complete-data-flow)

---

## 1. Project Overview

**Post-Apocalyptic Pawn Shop** (PAPS) is a Wolfenstein-style post-apocalyptic survival game with a custom software raycasting engine, an ECS (Entity-Component-System) architecture, and a full-featured 3D zone editor. The game features:

- A retro first-person raycaster with textured walls, multi-height floors/ceilings, lighting, fog, portals, and box/quad/curve geometry
- A top-down fallback view for zones not marked as first-person
- An off-screen world simulation running all zones simultaneously at low resolution
- An NPC dialogue tree system, loot tables, containers, combat, and pathfinding
- A standalone imgui-based zone editor with 17+ editing tools, undo/redo, multi-layer support, and real-time 3D preview
- A sprite sheet–based entity texture pipeline with TOML sidecar metadata

**Entry points:**
- `main.py` — Launches the game (`App` → `MainMenu` scene)
- `zone_editor.py` — Launches the standalone zone editor (`ZoneEditorApp`)
- `gen_entity_textures.py` — CLI tool for entity texture generation

---

## 2. Technology Stack & Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `pygame` | ≥ 2.0.0 | Window, input, 2D rendering, image loading |
| `numpy` | any | Array operations, zone data compilation |
| `tomli` | ≥ 2.0.0 | TOML parsing (Python < 3.11 fallback) |
| `msgpack` | ≥ 1.0.0 | Binary zone file serialisation |
| `PyOpenGL` | ≥ 3.1.0 | GL compositing in the zone editor |
| `PyOpenGL_accelerate` | ≥ 3.1.0 | PyOpenGL C speedups |
| `imgui[pygame]` | ≥ 2.0.0 | Immediate-mode GUI for the zone editor |

**Python versions:** System Python 3.9 for tests; `.venv` Python 3.10 for the editor.

**C extensions** (optional, compiled via `build_ext.py`):
- `engine._fast_cast` — C-accelerated DDA raycaster (~50× speedup)
- `engine._fast_walls` — Batch wall geometry computation
- `engine._ray_render` — Complete frame renderer (walls, floors, ceilings, entities, particles, SSAO)

All C extensions use OpenMP for multi-threaded parallelism. The engine provides pure-Python fallbacks when extensions are unavailable.

---

## 3. Directory Structure

```
Post-Apocalyptic-Pawn-Shop/
├── main.py                    # Game entry point
├── zone_editor.py             # Editor entry point
├── gen_entity_textures.py     # Texture pipeline CLI
├── build_ext.py               # C extension build script
├── requirements.txt           # Python dependencies
│
├── core/                      # Framework layer
│   ├── app.py                 #   Pygame application shell + main loop
│   ├── ecs.py                 #   Entity-Component-System
│   ├── events.py              #   Typed event bus
│   ├── scene.py               #   Abstract scene interface
│   ├── session.py             #   Game session lifecycle
│   ├── transition.py          #   Portal transitions + screen fades
│   ├── world_ticker.py        #   Background world simulation
│   ├── save.py                #   Save/load system
│   ├── entity_defs.py         #   Entity type definitions
│   ├── constants.py           #   Magic numbers + re-exports
│   ├── types.py               #   Direction/EntityKind enums
│   ├── paths.py               #   All filesystem path constants
│   ├── fonts.py               #   Global font cache
│   ├── presets.py             #   Cell preset (model) system
│   ├── tiles/                 #   Tile type registry
│   │   ├── types.py           #     TileType enum, TF flags, TileDef dataclass
│   │   ├── registry.py        #     TILE_REGISTRY, lookup tables, LUT builders
│   │   ├── crud.py            #     Tile CRUD operations
│   │   └── io.py              #     TOML serialisation
│   └── zones/                 #   Zone data structures + I/O
│       ├── zone.py            #     Zone dataclass, OverlayWall, Portal
│       ├── io.py              #     Binary .zone file reader/writer
│       ├── compiler.py        #     Zone → numpy array compilation
│       ├── format.py          #     Binary format specification
│       └── game_registry.py   #     Bidirectional str↔uint16 asset registry
│
├── components/                # ECS component definitions
│   └── __init__.py            #   All Component/Resource dataclasses
│
├── engine/                    # Rendering engine
│   ├── raycaster.py           #   DDA raycaster (Python + C fast path)
│   ├── ray_renderer.py        #   C renderer wrapper + buffer management
│   ├── textures.py            #   TextureAtlas + sprite sheet extraction
│   ├── _fast_cast.c           #   C extension: DDA raycaster
│   ├── _fast_walls.c          #   C extension: wall geometry batch
│   ├── _ray_render.c          #   C extension: full frame renderer
│   ├── _ray_render.h          #   Shared C header (inline helpers)
│   ├── _ray_entities.c        #   C extension: entity + particle rendering
│   └── _ray_debug.c           #   C extension: depth viz + SSAO
│
├── systems/                   # Gameplay logic systems
│   ├── spawner.py             #   Entity factory
│   ├── physics.py             #   Movement + collision
│   ├── lod.py                 #   LOD level transitions
│   ├── zone_sim.py            #   Off-screen zone simulation
│   ├── pathfinding.py         #   A*, BFS, LOS algorithms
│   ├── combat_sim.py          #   Off-screen combat resolution
│   ├── beast_spawner.py       #   Creature spawning
│   ├── interaction.py         #   Interaction detection
│   ├── gameplay.py            #   Interaction dispatch hub
│   ├── containers.py          #   Container/inventory/dialogue opening
│   ├── items.py               #   Item pickup/drop
│   ├── item_registry.py       #   Item type definitions (from items.toml)
│   ├── loot.py                #   Loot table rolling
│   └── dialogue_gen.py        #   NPC dialogue tree generation
│
├── scenes/                    # Game screens
│   ├── main_menu.py           #   Title screen
│   ├── save_slots.py          #   Save slot selection
│   ├── pause_menu.py          #   In-game pause overlay
│   ├── settings_menu.py       #   FPS/fullscreen settings
│   ├── debug_menu.py          #   Developer tools menu
│   ├── exhibit_lod.py         #   LOD system demo scene
│   ├── live_lod.py            #   Read-only LOD viewer
│   └── world/                 #   Main gameplay scenes
│       ├── topdown.py         #     Top-down tile-based view
│       ├── firstperson.py     #     First-person raycaster view
│       ├── fp_renderer.py     #     FP renderer (Python fallback)
│       ├── fp_walls.py        #     Wall raycasting
│       ├── fp_surfaces.py     #     Floor/ceiling rendering
│       ├── fp_entities.py     #     Entity billboard rendering
│       ├── fp_wall_entities.py#     Wall-mounted entity rendering
│       ├── fp_hud.py          #     HUD rendering
│       ├── fp_interact.py     #     FP interaction delegation
│       ├── fp_lighting.py     #     Fog/lighting computation
│       └── fp_perflog.py      #     Performance CSV logger
│
├── ui/                        # Modal UI system
│   ├── modal.py               #   Modal/ModalStack base classes
│   ├── commands.py            #   UICommand types (CloseModal, HealPlayer, etc.)
│   ├── helpers.py             #   Shared drawing utilities
│   ├── inventory_modal.py     #   Player inventory overlay
│   ├── transfer_modal.py      #   Container↔player transfer
│   └── dialogue_modal.py      #   NPC conversation tree
│
├── editor/                    # Zone editor application
│   ├── input_context.py       #   InputContext/InputStack abstractions
│   ├── contexts.py            #   Global shortcuts, viewport, stamp contexts
│   ├── fly_camera.py          #   WASD + mouse-look math
│   ├── keybinds.py            #   Keybind registry (~70 bindings)
│   ├── dialog_manager.py      #   Float/modal dialog state tracker
│   ├── zone_ops.py            #   Zone mutation utilities
│   ├── app/                   #   Editor application class + mixins
│   │   ├── app.py             #     ZoneEditorApp (main class)
│   │   ├── viewport.py        #     GL viewport blit
│   │   ├── events.py          #     Event pump
│   │   ├── raycaster.py       #     FP preview panel
│   │   ├── dialogs.py         #     9 imgui dialogs
│   │   ├── asset_browser.py   #     Texture browser
│   │   ├── data_viewers.py    #     TOML data browsers
│   │   ├── entity_creator.py  #     Entity type authoring
│   │   ├── entity_textures.py #     Sprite sheet status
│   │   ├── entity_writer.py   #     Custom entity TOML CRUD
│   │   ├── theme.py           #     imgui dark theme
│   │   ├── session_cfg.py     #     Session persistence
│   │   └── constants.py       #     Window dimensions
│   ├── commands/              #   Command bus system
│   │   ├── base.py            #     Command/CommandBus/EventBus
│   │   ├── events.py          #     Editor event types
│   │   ├── sculpt_cmds.py     #     17 sculpt commands
│   │   ├── paint_cmds.py      #     12 paint commands
│   │   ├── erase_cmds.py      #     3 erase commands
│   │   ├── object_cmds.py     #     31 object commands
│   │   ├── select_cmds.py     #     3 selection commands
│   │   ├── segment_cmds.py    #     3 segment commands
│   │   ├── stamp_cmds.py      #     1 stamp command
│   │   ├── misc_cmds.py       #     3 misc commands
│   │   └── l2_cmds.py         #     14 layer-2 commands
│   ├── panels_pkg/            #   imgui panel mixins
│   │   ├── menu_bar.py        #     File/Edit/View/Zone/Data/Window menus
│   │   ├── toolbox.py         #     Left panel: mode/tool/palette
│   │   ├── inspectors.py      #     Right panel: cell/bulk/object inspectors
│   │   └── overlays.py        #     Help/keybind overlays
│   └── view_3d/               #   3D viewport core
│       ├── editor.py          #     Zone3DEditor (1968 lines, 17+ mixins)
│       ├── constants.py       #     Modes, tools, colours, layout
│       ├── rendering.py       #     Viewport renderer (2224 lines)
│       ├── math3d.py          #     Software 3D projection + clipping
│       ├── picking.py         #     Ray-AABB/OBB intersection
│       ├── primitives.py      #     Line/box/filled-box drawing
│       ├── geometry.py        #     Cell bounding-box computation
│       ├── selection.py       #     Legacy index-based selection
│       ├── selection_store.py #     Phase 2 UID-based selection
│       ├── objects.py         #     Cross-type object layer
│       ├── undo.py            #     Snapshot-based undo/redo
│       ├── save.py            #     Zone save delegation
│       ├── tools_sculpt.py    #     Floor/ceiling/wall geometry
│       ├── tools_paint.py     #     Texture painting
│       ├── tools_fill.py      #     Flood fill
│       ├── tools_erase.py     #     Cell/height/texture erasing
│       ├── tools_select.py    #     Rectangle/contiguous selection
│       ├── tools_segment.py   #     Wall segment split/merge
│       ├── tools_stamp.py     #     Preset stamp application
│       ├── tools_entity.py    #     Entity placement/manipulation
│       ├── tools_box.py       #     Prism box editing
│       ├── tools_layer2.py    #     Secondary floor/ceiling layer
│       ├── tools_quad.py      #     Vertical quad panels
│       ├── tools_portal.py    #     Zone portal placement
│       ├── tools_curve.py     #     Curved wall arcs
│       └── tools_overlay.py   #     Freeform overlay walls
│
├── data/                      # Game data files
│   ├── entity_defs.toml       #   Entity type registry
│   ├── items.toml             #   Item definitions
│   ├── loot_tables.toml       #   Loot generation tables
│   ├── custom_entities.toml   #   Editor-created entities
│   ├── custom_tiles.toml      #   Editor-created tiles
│   └── presets/               #   Cell preset recipes (.toml)
│
├── assets/                    # Art and audio assets
│   ├── textures/
│   │   ├── tiles/             #   Tile textures (128×128 PNGs)
│   │   ├── entities/
│   │   │   ├── billboard/     #   Billboard sprite sheets + TOML sidecars
│   │   │   └── prism/         #   Prism net PNGs + TOML sidecars
│   │   └── skyboxes/          #   Panoramic skybox images
│   ├── models/tiles/          #   Tile definition TOMLs
│   ├── sounds/                #   Audio files
│   └── particles/             #   Particle textures
│
├── zones/                     # Zone files (.zone binary)
├── saves/                     # Save files (slot_N.json)
├── templates/                 #   Entity/room templates
├── tests/                     # Test suite
└── build/                     # Compiled C extensions
```

---

## 4. Core Architecture

### 4.1 Application Shell

**File:** `core/app.py`

The `App` class is the outermost game wrapper. It manages the pygame window, the main loop, and a scene stack.

```python
class App:
    def __init__(self, title="Shopkeeper", width=960, height=640)
```

**Key attributes:**
- `screen` — pygame display surface (`RESIZABLE | SCALED`)
- `_render_surface` — fixed-size virtual surface (all drawing targets this)
- `clock` — `pygame.time.Clock` capping at `fps` (default 100)
- `world` — shared `World` (ECS container) instance
- `_scenes` — stack of `Scene` objects
- `dt` — raw delta time (capped at 50ms); `_dt_smooth` — EMA-smoothed (80/20 blend)
- Three debug fonts at sizes 11, 14, 18

**Scene stack operations:**
- `push_scene(scene)` — calls `on_exit` on current top, `on_enter` on new
- `pop_scene()` — pops top, re-enters the one beneath
- `clear_scenes()` — pops all

**Main loop (`run()`):**
1. `clock.tick(fps)` → cap raw `dt` at 0.05s → EMA smooth
2. Event pump: `QUIT` → stop, `F11` → toggle fullscreen, else → `scene.handle_event`
3. `scene.update(dt, app)`
4. `scene.draw(_render_surface, app)` → blit to `screen` → `flip()`
5. `pygame.quit()` on exit

**Coordinate mapping:** `mouse_pos()` returns clamped virtual-surface coordinates (pygame's `SCALED` mode handles DPI mapping).

**Fullscreen toggle:** Switches between `FULLSCREEN | SCALED` and `RESIZABLE | SCALED` modes.

### 4.2 Entity-Component System

**File:** `core/ecs.py`

A typed ECS where entities are integer IDs, components are `Component` subclass instances, and there are no formal "systems" — game logic queries the world directly.

#### Component Base

```python
@dataclass
class Component:
    _persist: ClassVar[bool] = False  # True → survives save/load
```

All game components inherit from this. The `_persist` flag controls serialisation.

#### Resources

```python
class Resources:
    def set(self, resource: Any) -> None       # registers by type
    def get(self, res_type: type[R]) -> R      # raises KeyError if missing
    def try_get(self, res_type: type[R]) -> R | None
    def has(self, res_type: type) -> bool
```

Resources are typed singletons stored on the `World`. Used for `Camera`, `GameClock`, `WorldClock`, `WorldEventLog`.

#### World

```python
class World:
    def __init__(self)
```

**Internal stores:**
- `_next_id: int` — auto-incrementing entity counter
- `_stores: dict[type, dict[int, Component]]` — component-type → {eid → instance}
- `_dead: set[int]` — entities scheduled for removal
- `_zone_index: dict[str, set[int]]` — zone name → entity set (O(1) zone-scoped queries)
- `resources: Resources`
- `events: EventBus` — created inline at construction

**Entity lifecycle:**
- `spawn() → int` — allocates next ID
- `kill(eid)` — marks for deferred removal
- `alive(eid) → bool`
- `purge()` — removes dead entities from all stores + zone index (call once per frame)

**Component operations:**
- `add(eid, comp)` — TypeError if not a Component subclass; auto-indexes zone if Position-like
- `get(eid, comp_type) → T | None`
- `has(eid, comp_type) → bool`
- `remove(eid, comp_type)`

**Queries (typed overloads for 1–3 component types):**
- `query(*types) → Iterator[tuple[int, ...]]` — iterates the smallest store bucket first for efficiency, checks membership in all others
- `query_one(*types) → tuple | None` — first match
- `query_zone(zone, *types) → Iterator` — scoped to zone-indexed entities
- `all_of(comp_type) → Iterator[(int, T)]` — all living entities with that component
- `count(comp_type) → int`

**Zone index:** When a component with a `zone` attribute is added (typically `Position`), the index auto-updates. `set_zone(eid, zone)` moves the entity between buckets and updates the component's `.zone` field. `zone_entities(zone)` returns the set minus dead entities.

### 4.3 Event Bus

**File:** `core/events.py`

A typed event bus using dataclass events (no magic strings).

```python
class EventBus:
    def subscribe(event_type, handler)        # permanent handler
    def subscribe_once(event_type, handler)   # auto-removed after first call
    def unsubscribe(event_type, handler)
    def emit(event)                           # queues for flush()
    def emit_immediate(event)                 # synchronous delivery
    def flush()                               # delivers all queued (call once/frame)
    def clear()                               # removes all handlers + queue
    @property
    def pending -> int                        # queue length
```

**Event delivery:** `flush()` snapshots the queue, clearing it before delivery. This prevents handlers that emit new events from causing infinite loops. Each handler is wrapped in `try/except` — a failing handler doesn't block others.

**Predefined event types:**

| Event | Fields | When Emitted |
|-------|--------|--------------|
| `EntityDied` | `entity, killer` | Entity HP reaches 0 |
| `DamageDealt` | `target, amount, source` | Damage applied |
| `ZoneTransition` | `entity, target_zone, target_x, target_y` | Portal traversal |
| `ItemPickedUp` | `entity, item_name, quantity` | Ground item collected |
| `InteractionEvent` | `player, target` | E key interaction |

### 4.4 Scene System

**File:** `core/scene.py`

Abstract interface for every screen in the game:

```python
class Scene:
    def on_enter(self, app: App)                            # pushed or revealed
    def on_exit(self, app: App)                             # popped or covered
    def handle_event(self, event: pygame.event.Event, app)  # single event
    def update(self, dt: float, app: App)                   # advance simulation
    def draw(self, surface: pygame.Surface, app: App)       # render
```

All methods are no-ops by default. The `App` holds a stack; only the topmost scene receives events and draws.

### 4.5 Type Definitions

**File:** `core/types.py`

Canonical enums replacing magic strings:

```python
class Direction(Enum):    UP, DOWN, LEFT, RIGHT
class EntityKind(Enum):   PLAYER, NPC, ITEM, CONTAINER, DUMMY, BEAST, GROUND_ITEM, CROP, PROP
```

**Wall face constants:**
```python
FACE_NORTH = 0, FACE_SOUTH = 1, FACE_EAST = 2, FACE_WEST = 3
FACE_NAMES = ("north", "south", "east", "west")
```

**`face_from_side(side, ray_dir_x, ray_dir_y) → int`** — Derives compass face index from the DDA raycaster's `side` (0 = X boundary, 1 = Y boundary) + ray direction signs. Used by both the raycaster and renderer.

### 4.6 Path Constants

**File:** `core/paths.py`

Single source of truth for all project filesystem paths. All are `Path` objects resolved at import time relative to `PROJECT_ROOT` (parent of `core/`).

Key paths:
- `PROJECT_ROOT` — repository root
- `ZONES_DIR` — `zones/`
- `DATA_DIR` — `data/`
- `SAVES_DIR` — `saves/`
- `TEXTURES_DIR` — `assets/textures/`
- `TILE_TEX_DIR` — `assets/textures/tiles/`
- `BILLBOARD_TEX_DIR` — `assets/textures/entities/billboard/`
- `PRISM_TEX_DIR` — `assets/textures/entities/prism/`
- `SKYBOXES_DIR` — `assets/textures/skyboxes/`
- `TILES_TOML_DIR` — `assets/models/tiles/`
- `LOOT_TABLES_PATH` — `data/loot_tables.toml`
- `ITEMS_PATH` — `data/items.toml`

### 4.7 Global Constants

**File:** `core/constants.py`

All distances are in **tiles** (1 tile = 1 metre).

| Constant | Value | Meaning |
|----------|-------|---------|
| `DAY_LENGTH` | 300.0 | Real seconds per in-game day |
| `TILE_SIZE` | 32 | Pixels per tile (rendering only) |

**Tile-ID aliases:** `TILE_VOID`, `TILE_GRASS`, `TILE_DIRT`, `TILE_STONE`, `TILE_WATER`, `TILE_WOOD_FLOOR`, `TILE_WALL`, `TILE_DOOR`, `TILE_WINDOW`, `TILE_HALF_WALL`, `TILE_LOW_WALL`.

**Reference speeds:** Walk 1.2–1.5 m/s, Patrol 2.0, Run 5.0, Sprint 7.5. Detection range hierarchy from 3m peripheral to 30m LOD zone.

### 4.8 Font Cache

**File:** `core/fonts.py`

```python
def get_font(size, *, family="monospace") → pygame.font.Font
```
Clamped 8–72, snapped to even sizes. Cached by `(family, size)` key.

---

## 5. Tile System

**Package:** `core/tiles/`

### TileDef Dataclass

`core/tiles/types.py` defines the core types:

```python
class TileType(Enum):   FLOOR, WALL, HALF_WALL, PLATFORM, DOOR, LIQUID

class TF(IntFlag):       # Tile flags
    NONE, SOLID, WALL, TRANSPARENT, LIQUID, FARMLAND,
    HALF_WALL, PLATFORM, THIN_WALL, TALL_WALL
```

```python
@dataclass(frozen=True)
class TileDef:
    id: str                    # unique key ("brick_wall")
    name: str                  # display name ("Brick Wall")
    color: tuple[int,int,int]  # fallback colour
    type: TileType
    flags: TF
    texture_key: str           # default texture
    texture_front/back: str    # front/back face overrides
    tex_n/tex_s/tex_e/tex_w    # directional face textures
    alt_texture: str           # variation texture
    height_scale: float        # vertical sizing
    v_scale: float
    anim_frames/stride/ticks   # animation parameters
    category: str              # UI grouping
    sound: str                 # footstep sound
```

**Face texture resolution:** `tex_for_face(face, rotation)` checks per-face fields first, falls back to `texture_key`.

### Registry

`core/tiles/registry.py` maintains:

- `TILE_REGISTRY: dict[str, TileDef]` — master tile dictionary
- **Derived frozensets:** `SOLID_IDS`, `WALL_IDS`, `HALF_WALL_IDS`, `PLATFORM_IDS`, `DOOR_IDS`
- **Compact int mapping:** `tile_str_to_int()`, `tile_int_to_str()`, `grid_to_ints()` — for numpy array conversion and C interop
- **LUT builders** (called by the renderer): `wall_lut()`, `half_wall_lut()`, `hs_lut()` (height_scale), `transparent_lut()`, `thin_wall_lut()`, `solid_int_set()`, `anim_lut()`, etc.
- **Extra texture key registration:** `register_extra_key(key)` — adds non-tile textures (entity sprites) to the global atlas index. `all_texture_keys()` returns all registered keys.

### I/O

`core/tiles/io.py` loads tile definitions from `assets/models/tiles/*.toml` at import time. Each TOML file defines one tile.

### CRUD

`core/tiles/crud.py` provides `register_tile()`, `update_tile()`, `delete_tile()` for runtime tile management (used by the editor).

---

## 6. Zone System

**Package:** `core/zones/`

### Zone Dataclass

`core/zones/zone.py` defines the central `Zone` class with 50+ fields:

**Core:** `name`, `width`, `height`, `anchor` (player spawn tile)

**Navigation grid (2D, per-cell):**
- `tiles[H][W]` — tile-type ID strings
- `rotations[H][W]` — per-cell rotation

**Height geometry (2D, per-cell, float):**
- `floor_heights`, `ceil_heights` — primary floor/ceiling elevations
- `floor2_heights`, `ceil2_heights` — secondary layer (Layer 2)
- `upper_wall_height`, `upper_wall_height2` — extended wall above ceiling

**Textures (2D and 3D, per-cell, string):**
- `floor_textures`, `ceil_textures`, `wall_textures` — uniform per-cell
- `face_textures[H][W][4]` — per-face (N/S/E/W) overrides
- `floor_step_textures[H][W][4]`, `ceil_step_textures[H][W][4]` — step face textures
- `floor2_textures`, `ceil2_textures` — Layer 2 textures

**Segments (4D, per-cell, per-face, variable-length):**
- `wall_segments[H][W][4][segs]` — stacked texture bands: `[(texture, y_top), ...]`
- `floor_step_segments`, `ceil_step_segments` — step face bands

**Lighting/atmosphere:**
- `light_levels[H][W]` — 0.0–1.0 ambient brightness
- `fog_density[H][W]` — per-cell fog
- `fog_color` — zone fog tint colour
- `sky_color` — `(r, g, b)` tuple overriding the compile-time sky gradient top colour; wired through Python → C dict → `fill_background` params
- `skybox` — skybox image name
- `reflect_map[H][W]` — floor reflectivity (0–255)

**Slopes:** `floor_slope_dx`, `floor_slope_dy`, `floor_slope_div` — per-cell slope deltas.

**Object lists:**
- `entities: list[dict]` — `{type, x, y, angle, state, uid, overrides}`
- `boxes: list[dict]` — prism parameters + per-face textures
- `quads: list[dict]` — vertical rectangular panels
- `render_portals: list[dict]` — view into other zones (visual portals)
- `curves: list[dict]` — arc wall segments
- `overlay_walls: list[OverlayWall]` — freeform line-segment walls (`x1, y1, x2, y2, height_scale, base_y, texture, transparent, flags`)

**UID system:** `next_uid() → str` generates monotonically increasing unique IDs. `ensure_uids()` assigns UIDs to objects missing them.

**Connectivity:**
- `portals: dict[str, Portal]` — zone-to-zone connections. Each `Portal` has `tiles: list[(r,c)]`, `target_zone`, `target_row`, `target_col`, `exit_direction`.

### Binary Zone Format

`core/zones/io.py` handles `.zone` file I/O:

```
Header (12 bytes): magic(0x5A4F4E45) | version(2) | flags(2) | W(2) | H(2)
Chunks: chunk_id(4 ASCII) | length(4) | payload(length)
```

| Chunk | Contents |
|-------|----------|
| `NAVI` | Navigation bitmask grid (uint16 per cell) |
| `ELEV` | Floor + ceiling heights (float32 arrays) |
| `RNDR` | Texture index grids, light levels (uint16) |
| `ENTY` | Entities, portals, overlay walls, all editor grids (msgpack) |

**NAV bitmask bits:** `NAV_SOLID` (bit 0), `NAV_BLOCK_NORTH/SOUTH/EAST/WEST` (1–4), `NAV_WATER` (5), `NAV_HAZARD` (6), `NAV_INTERIOR` (7), `NAV_PLATFORM` (8), `NAV_DOOR` (9), `NAV_PORTAL` (10), `NAV_HALF_WALL` (11).

`load_binary_zone(filepath, sim_only=False)` reads the file; `sim_only=True` skips the RNDR chunk for faster off-screen loading.

### Zone Compilation

`core/zones/compiler.py` converts a `Zone` to numpy arrays via `compile_zone_to_arrays()`:
1. Tile strings → `uint16` arrays
2. Derives NAV bitmask per cell
3. Resolves texture priority: `face_textures > wall_textures > TileDef.texture_key`
4. String texture keys → `uint16` via `GameRegistry`

### Typed Zone Objects (`core/zones/objects.py`)

Zone placeables (entities, boxes, quads, curves, render portals) are stored as **typed dataclasses** that support the full dict protocol.  The `_DictBridge` mixin provides `obj["key"]`, `obj.get(k)`, `"key" in obj`, `dict(obj)`, `.items()`, etc., so typed objects are transparent drop-in replacements for the `dict[str, Any]` values they supersede.

| Class | Key fields | Notes |
|-------|-----------|-------|
| `Quad` | `uid, x, z, base_y, angle, width, height, texture, collision, two_sided` | `from_dict()` handles legacy `cell`/`pos` format |
| `Box` | `uid, x, y, z, w, h, d, yaw, textures, collision` | `textures` is `dict[str, str]` keyed by face |
| `Curve` | `uid, cx, cy, radius, angle_start, angle_end, height_scale, base_y, texture, flags` | |
| `RenderPortal` | `uid, cell, face, dest_x, dest_y, angle_offset` | `face` is 0–3 (N/S/E/W) |
| `EntityDescriptor` | `uid, id, type, x, y, angle, state, overrides, extra` | Extended DictBridge — `extra` dict merges transparently into key namespace |

**`_DictBridge.__setitem__`** rejects unknown keys with `KeyError` for Quad/Box/Curve/RenderPortal (correct — audit confirmed no ad-hoc writes).  `EntityDescriptor` overrides this to route unknown keys into its `extra` dict, preserving legacy keys like `sprite`, `prefab`, `tile_entity`.

**Serialisation:** `serialize_objects(objs)` converts a mixed list of typed objects and plain dicts to plain dicts for msgpack.  Used by `io.py` on the save path.  `from_dict()` on each class handles the reverse on load.

### Zone Validation (`core/zones/validation.py`)

`validate_zone(zone, *, entity_registry=None, tile_registry=None, texture_dir=None)` runs all structural and semantic checks on a loaded Zone, returning a sorted list of `ZoneIssue(severity, category, message, location)`:

| Check | Category | Severity | What it catches |
|-------|----------|----------|----------------|
| Grid dimensions | `grid` | error | Any 2D/3D grid with wrong row/col count vs `zone.width`/`height` |
| Geometry | `geometry` | warning | Floor above ceiling, mismatched secondary layers, degenerate boxes (w/h/d ≤ 0) |
| UID uniqueness | `uid` | error | Duplicate UIDs across all object lists; warning for uid=0 |
| Entity validity | `entity` | error/warn | Missing type (error), unknown type (warning if registry provided), out-of-bounds position (warning) |
| Render portals | `portal` | error/warn | Cell out of bounds, invalid face, destination out of bounds |
| Zone portals | `portal` | error | Empty target_zone, portal tiles out of bounds |
| Textures | `texture` | warning | Texture keys with no `.png` asset on disk (only when `texture_dir` provided) |
| Tiles | `tile` | warning | Tile IDs not in tile registry (only when `tile_registry` provided) |
| Anchor | `anchor` | warning | Missing or out-of-bounds player spawn point |
| Overlay walls | `geometry` | warning | Zero-length overlay walls |
| Deferred budget | `deferred` | warning | Per-column worst-case deferred hit count exceeds `MAX_DEF_PER_COL` (16); uses conservative cell-overlap geometry analysis |

**Editor integration:** Both `_do_save()` in `editor/app/app.py` and the Zone → Validate Zone dialog in `editor/app/dialogs.py` pass all three optional registries (`entity_registry=entity_registry()`, `tile_registry=TILE_REGISTRY`, `texture_dir=TILE_TEX_DIR`), so all 13 checks run every time — including the four opt-in checks for unknown entity types, unknown tile IDs, missing texture assets, and deferred-hit budget analysis (requires `tile_registry` to identify transparent/thin tiles).  Errors flash an in-editor warning and log to console.  Warnings log only.  Validation never blocks save — the zone is already in memory and the user needs the file to iterate.  The validation HUD (persistent bar above the status bar) displays the issue count after every save; clicking "Details" opens the Validate Zone dialog with the full `ZoneIssue` list.

**Convenience:** `zone.validate(**kwargs)` is a thin wrapper that forwards to `validate_zone()`.

### Game Registry

`core/zones/game_registry.py` — Bidirectional `str ↔ uint16` asset ID registry with namespaces (`tile`, `texture`, `prefab`). Used for compact binary zone storage.

---

## 7. Entity Definitions

**File:** `core/entity_defs.py`

Unified entity type definitions loaded from `data/entity_defs.toml`.

### EntityDef Dataclass

```python
@dataclass(frozen=True)
class EntityDef:
    id: str                           # unique type key
    display_name: str                 # human-readable name
    category: str                     # grouping ("characters", "props", "gameplay")
    render_type: str                  # "billboard", "8way", or "prism"
    color: tuple[int,int,int]         # fallback colour
    scale: float                      # visual scale multiplier
    directional: bool                 # True = 8-way facing
    states: tuple[str, ...]           # animation states ("idle", "walk", "hurt")
    sprite_key: str                   # atlas key prefix
    frame_width: int                  # sprite cell width (pixels, default 32)
    frame_height: int                 # sprite cell height (pixels, default 128)
    width/depth/height/elevation      # prism geometry (world units)
    textures: tuple[...]              # frozen face→key pairs (prism)
    movable: bool                     # can be pushed/relocated
    components: tuple[...]            # frozen nested component defaults
```

**Key methods:**
- `component_defaults() → {key: {field: value}}` — mutable copy for the spawner
- `texture_map() → {face: texture_key}` — mutable copy of prism face textures
- `face_dimensions(face) → (w, h)` — world-space dimensions per face
- `face_tex_size(face_w, face_h, base_px, ref_dim) → (px_w, px_h)` — pixel dimensions for texture generation, aligned to 4px

### Registry

- `entity_registry() → dict[str, EntityDef]` — lazy-loaded from `data/entity_defs.toml`
- `entity_palette() → list[str]` — sorted by category then name
- `get_entity_def(type_id) → EntityDef | None`

### Texture Key Generation

```python
def entity_texture_keys() → list[str]
```

Generates the complete ordered list of texture keys for the atlas:

**Prism entities:** One key per face — `"vending_machine:front"`, `"vending_machine:side"`, etc.

**Billboard entities:** Keys follow pattern `sprite_key:state_frameIdx_facing` (directional) or `sprite_key:state_frameIdx` (non-directional):
- `"dummy:idle_0_s"`, `"dummy:idle_0_sw"`, ..., `"dummy:walk_3_se"`, ...
- `"candle:lit_0"`, `"candle:lit_1"`, ..., `"candle:unlit_0"`

Frame counts per state are read from TOML sidecar files via `_read_state_frames()`. If no sidecar exists, defaults to 1 frame per state.

### Constants

```python
FACING_LABELS_8 = ("s", "sw", "w", "nw", "n", "ne", "e", "se")
```

This order matches the C renderer's facing index: Entity facing angle 0° = south, incrementing counter-clockwise.

---

## 8. Components

**File:** `components/__init__.py`

All ECS component and resource types, defined as dataclasses inheriting `Component`.

### Entity Components

| Component | Persisted | Fields | Purpose |
|-----------|-----------|--------|---------|
| `Position` | ✓ | `x, y: float`, `zone: str` | Fine-grained world location |
| `Velocity` | ✗ | `x, y: float` | Movement vector (tiles/sec) |
| `Facing` | ✗ | `direction: Direction` | Cardinal facing |
| `Collider` | ✗ | `w, h, ox, oy: float`, `solid: bool` | AABB hitbox with offset |
| `Sprite` | ✗ | `char, color, layer`, `billboard_mode`, `sprite_key` | Visual representation; `billboard_mode` 0=static, 1=8-way |
| `Identity` | ✗ | `name: str`, `kind: EntityKind` | Display name + classification |
| `Health` | ✓ | `current, maximum: float` | Hit points |
| `Inventory` | ✓ | `items: dict[str, int]` | Item ID → quantity |
| `TileEntity` | ✓ | `tile_type, item_id, item_qty, tiles, loot_table, looted` | Tile-based interaction data |
| `WallSprite` | ✓ | `texture_key, width, height, elevation` | 3D wall-mounted sprite |
| `PrismShape` | ✗ | `width, depth, height, elevation, yaw, textures: dict, movable` | Oriented 3D box |
| `PrefabRef` | ✓ | `uid: str`, `prefab: str` | Template link for transient rebuild |
| `Player` | ✗ | `speed: float` (default 6.0) | Marks player entity |
| `CoarsePos` | ✓ | `row, col: int`, `zone: str`, `speed: float` | Integer-tile position for off-screen sim |
| `Timers` | ✓ | `active: dict[str, float]` | Named cooldown timers |
| `CombatStats` | ✓ | `damage, attack_range, attack_cooldown, hostile: bool` | Combat parameters |

### Resource Types

| Resource | Fields | Purpose |
|----------|--------|---------|
| `Camera` | `x, y` | Viewport centre |
| `GameClock` | `time` | Real-time accumulator |
| `WorldClock` | `real_time, world_time, day, day_phase, paused, time_scale` | In-game clock; 4 time scales (1×/5×/30×/120×); `day_phase` in [0,1] |
| `WorldEventLog` | `entries: list[WorldEventEntry]`, `max_entries`, `unread` | Scrolling event journal |
| `WorldEventEntry` | `message, zone, time, category` | Single log entry |

### Persistence Model

Only components with `_persist = True` are serialised to save files. Transient components (`Sprite`, `Collider`, `Identity`, `Velocity`, etc.) are rebuilt from entity definitions and zone descriptors on load via `spawner.rebuild_transients()`.

---

## 9. Session & World Ticker

### 9.1 Session

**File:** `core/session.py`

The `Session` class manages the game data pipeline — zone loading, entity spawning, save/load. Scenes never touch zone files directly.

```python
class Session(TransitionMixin, WorldTickerMixin):
    def __init__(self, world: World)
```

**Key attributes:**
- `world`, `zone_name`, `tiles`, `rotations`, `map_w/map_h`
- `visited_zones: set[str]`
- `first_person: bool` — from zone data
- Height arrays: `floor_heights`, `ceil_heights`, `floor2_heights`, `ceil2_heights`
- Texture arrays: `floor_textures`, `ceil_textures`
- `_portal_map: {(row,col): (target_zone, row, col, exit_dir)}`
- Background sim: `zone_sim` (1s tick), `beast_spawner`, `_restock_timer` (60s)
- Fade state: `fade_alpha`, `_fade_direction`, `_fade_speed`, `_pending_teleport`
- Auto-walk state: `auto_walk_active/timer/duration/dx/dy`

**Methods:**
- `new_game(start_zone)` — loads zone template, spawns player at anchor, spawns zone entities, initialises resources (`Camera`, `GameClock`, `WorldClock`, `WorldEventLog`), starts background sim
- `save(slot) → Path` — delegates to `save_game()`
- `load(slot) → bool` — clears entities, loads zone template, restores entities from save, rebuilds transients, restores clocks
- `_load_zone_template(name) → Zone` — loads tiles/heights/textures into session attrs, caches entity descriptors, builds portal map

### 9.2 Zone Transitions

**File:** `core/transition.py`

`TransitionMixin` provides portal traversal with screen-fade animation.

**Fade sequence:**
1. `check_portals()` — player on portal tile → starts fade-out (`_fade_direction=1`)
2. `update_transition(dt)` — ticks fade alpha toward 1.0
3. At alpha 1.0: `_execute_teleport()` — loads new zone, spawns entities on first visit, syncs LOD, repositions player, sets facing, starts 0.6s auto-walk in exit direction
4. Fade-in: `_fade_direction=-1` → alpha falls to 0.0

**Auto-walk:** After teleport, the player walks automatically for `auto_walk_duration` seconds in the exit direction at speed 4.0, preventing immediate re-triggering of the portal.

### 9.3 World Ticker

**File:** `core/world_ticker.py`

`WorldTickerMixin` drives the background world simulation. Called from `scene.update()` each frame.

**`tick_world(dt)` sequence:**
1. **WorldClock** — advances `real_time`, `world_time` (scaled by `DAY_LENGTH`), `day_phase`, `day` counter. Respects `paused` flag.
2. **Timers** — `tick_timers(world, scaled_dt)` decrements all active timers.
3. **ZoneSim** — off-screen NPC movement + combat.
4. **BeastSpawner** — creature spawning.
5. **Container restocking** — every 120s, resets `looted` containers.
6. **Purge** — `world.purge()` removes dead entities.

**Known zones:** `["playground", "pawn_shop", "house_interior", "outskirts", "crossroads", "campsite"]`

---

## 10. Save System

**File:** `core/save.py`

### Format

JSON file `saves/slot_N.json` with keys:
- `"zone"` — current zone name
- `"clock"` — game clock time
- `"world_clock"` — `{real_time, world_time, day, day_phase}`
- `"visited_zones"` — sorted list
- `"entities"` — list of `{eid, ComponentName: {field: value}, ...}`

### Serialisation

Only `_persist=True` components are serialised. The component registry is lazily built by scanning `components.__init__` for all `Component` subclasses.

- `save_game(world, zone, slot, *, visited_zones) → Path`
- `load_game(slot) → dict | None` — returns raw JSON or None if missing/corrupt
- `restore_entity(world, entry) → int` — spawns entity, attaches recognised persistent components
- `has_save(slot) → bool`
- `delete_save(slot)`

Transient components must be rebuilt separately via `spawner.rebuild_transients()`.

---

## 11. Cell Presets

**File:** `core/presets.py`

The preset system provides reusable "recipes" for configuring zone cells — heights, textures, and wall segments.

```python
@dataclass(frozen=True)
class CellPreset:
    id, name, category, color
    apply_mode: str   # "replace", "stack_floor", "stack_ceil", "merge"
    floor_height/ceil_height/upper_wall_height  # None = leave unchanged
    floor_texture/ceil_texture/wall_texture
    face_textures   # N/S/E/W tuple
    floor_step_textures/ceil_step_textures
    wall_segments/floor_step_segments/ceil_step_segments
    # Layer 2 fields...
```

**Apply modes:**
- **replace** — Full overwrite of cell data; derives tile type from gap (solid wall if < 0.1m)
- **stack_floor** — Raises floor, creates step segment at old height
- **stack_ceil** — Lowers ceiling, creates ceiling step segment
- **merge** — Writes only non-None fields, leaves tile type alone

**Key functions:**
- `apply_preset(zone, r, c, preset, *, wall_tile, open_tile, mode_override)` — stamps recipe onto a cell
- `capture_preset(zone, r, c, preset_id, name, category, apply_mode) → CellPreset` — snapshots a cell's state
- `register_preset(preset, *, save=True)` — add/replace in registry + optional disk persist
- `load_presets()` — loads all `.toml` files from `data/presets/`

---

## 12. Engine

### 12.1 Raycaster

**File:** `engine/raycaster.py`

Wolfenstein-style DDA raycaster producing per-column wall slices and projected entity billboards.

#### WallSlice

```python
WallSlice = namedtuple(..., 13 fields)
# screen_x, distance, height, tile_id, side, tex_x, height_scale,
# ray_dir_x, ray_dir_y, wall_x, map_x, map_y, face
```

#### Core Function

```python
def cast_walls(px, py, angle, fov, screen_w, screen_h, tiles,
               *, wall_tiles=None, step=1) → list[WallSlice]
```

For each screen column, casts a ray via DDA through the tile grid:
- **Full solid walls** — stops the ray
- **Half-walls** — records hit, continues
- **Transparent walls** — records hit, continues
- **Thin walls** — intersects at cell midpoint, continues

Emits slices in painter's order: solid wall first, then transparent far-to-near, then half-walls far-to-near.

**Caching:** Pre-computed trig tables (quantised to 2048 angles), height-scale LUT, flat tile array (cached by generation counter).

**C fast path:** Routes to `_fast_cast.cast_walls` when the C extension is available and default wall tiles are used. Passes pre-built LUT bytearrays (wall/half/hs/transparent/thin).

#### Entity Projection

```python
def project_entities(px, py, angle, fov, screen_w, screen_h, entities)
    → list[BillboardSprite]
```

Projects world entities into screen-space billboards using camera-plane inverse determinant. Supports elevation offset. Returns sorted far→near.

#### Z-Buffer

```python
def build_zbuffer(slices, screen_w, step) → list[float]
```

Per-column depth buffer from wall slices.

### 12.2 Ray Renderer

**File:** `engine/ray_renderer.py` (2013 lines)

Python wrapper for the C rendering extension. Manages buffer construction, zone data serialisation, and provides a clean API.

#### RayRenderer Class

```python
class RayRenderer:
    def __init__(self, zone, atlas, *, sw=640, sh=360, fov=π/2, dn=1.0, pitch_max=0.3π)
```

Requires the C extension. Allocates:
- Framebuffer: `sw × sh × 3` bytes (RGB)
- Z-buffer: `sw × 8` bytes (float64 per column)
- Per-pixel depth: `sw × sh × 4` bytes (float32)
- pygame Surface wrapping the framebuffer (zero-copy)

#### Rendering Pipeline

```python
def render(self, px, py, angle, cam_h=0.5, pitch=0.0) → pygame.Surface
```

Passes 60+ keys to the C `render_frame`. Includes tile grids, atlas, heights, textures, segments, fog, lights, decals, quads, boxes, curves, slopes, portals, skybox, animations, multi-layer data, lens distortion, reflections.

The C renderer executes in 5 phases:
1. **Background** — Skybox panorama or gradient (sky gradient top colour overridden by `sky_color` zone field when present)
2. **Walls (DDA)** — Full/half/transparent/thin/tall walls, boxes (OBB ray-slab), quads (line-segment), curves (ray-circle), deferred hits
3. **Floor** — Multi-tier row-sweep textured floor with per-pixel depth, fog, lighting, bump mapping, decals, slopes
4. **Ceiling** — Multi-tier ceiling with skybox threshold
5. **Deferred walls** — Composite short/thin/transparent walls and box faces far→near with alpha blending

**Deferred-hit budget:** `MAX_DEF_PER_COL = 16` (defined in `_ray_render.h`).  Each column can hold at most 16 deferred hits from transparent/thin walls, overlay walls, quads, boxes, and curves.  Exceeding this silently drops geometry — no crash or log.  The `_check_deferred_budget` validation check in `core/zones/validation.py` performs conservative static analysis to warn at authoring time when any cell's worst-case count exceeds 16.

```python
def render_entities(self, px, py, angle) → None
```

Renders entity billboards after `render()`. Packs each entity as 12 doubles:
```
[x, y, r, g, b, h_scale, w_scale, base_tex, facing_angle, n_facings, anim_offset, flags]
```

**Multi-facing sprite selection:** The C renderer computes the relative angle from camera to entity minus the entity's facing angle, selecting one of 8 frames from the atlas.

**base_tex resolution:** For directional entities, looks up `sprite_key:first_state_0_s`; for non-directional, `sprite_key:first_state_0`.

```python
def render_particles(self, px, py, angle, particles, dt) → None
def apply_ssao(self, strength=0.45, radius=6, bias=0.15) → None
```

#### Buffer Construction

`_build_buffers(zone, atlas, dn)` serialises ~30+ zone attributes into flat C-compatible arrays:
- Tile grid → int32
- Cell-solid map → uint8 (solid if full-height wall or gap < 0.1)
- Atlas → packed RGBA `[num_tiles × TEX_SIZE × TEX_SIZE × 4]`
- Floor/ceiling heights → float64
- Texture overrides → int32
- Face-tex grid → int32 (N/S/E/W per cell)
- Wall segments → offset/count/tex/ytop arrays
- Step-wall segments
- Fog LUT, fog volumes, light levels, point lights, shadow maps
- Decals, quads, boxes (including entity prisms!), curves, slopes
- Multi-layer data, portals, reflective floors, lens distortion, skybox

**Entity prisms:** `_collect_entity_prisms()` converts entities with `render_type == "prism"` to 14-double box data: `[cx, cz, w, h, d, base_y, yaw, tex_n, tex_s, tex_e, tex_w, tex_top, tex_bot, flags]`.

**Overlay wall packing:** 8-double stride per wall: `[x1, y1, x2, y2, height_scale, base_y, tile_id, flags]`.  C reads `base_y` and sets `DeferredHit.base_y` (sentinel `−1e9` when `base_y == 0`).

**sky_color:** `_build_buffers` reads `zone.sky_color` (tuple or None) → stored as `self._sky_color` → passed in ctx dict as `"sky_color"`.  C extracts via `PyDict_GetItemString` and overrides the compiled-in `SKY_TOP_R/G/B` gradient defaults.

#### Height Queries

```python
def floor_height_at(self, x, y, current_fh=None) → float
def ceil_height_at(self, x, y) → float
def can_step_to(self, x, y, current_fh, ...) → bool
```

Height-aware collision: validates step-up (max 0.5m), step-down (max 1.0m), and head clearance (min 0.4m) across both primary and Layer-2 surfaces.

#### Particle System

```python
class ParticleBuffer:
    # 14 doubles per particle: [x,y,z, vx,vy,vz, life,max_life, r,g,b, size, tex_id, flags]
    def emit(self, x, y, z, vx, vy, vz, life, r, g, b, size, tex_id, flags)
    def emit_burst(self, x, y, z, count, spread, speed, life, r, g, b, size)
    def sweep_dead(self)
```

### 12.3 Texture Atlas

**File:** `engine/textures.py`

Manages all texture loading, caching, and entity sprite-sheet/net extraction.

**Constants:** `TEX_SIZE = 128` (all textures are 128×128).

#### TextureAtlas Class

```python
class TextureAtlas:
    def get(tile_id) → Surface           # tile texture by ID
    def get_by_key(key) → Surface        # arbitrary key with structured entity key support
    def sample(tile_id, u, v) → (r,g,b)  # UV sampling
    def ensure_all()                      # pre-load all
    def invalidate(tile_id)              # drop cache
```

#### Key resolution order in `_load_texture_by_key(key)`:

1. **Billboard sprite sheet cell** — keys like `"dummy:idle_0_s"`:
   - Parses suffix with `_parse_billboard_suffix()` → `(state, frame_idx, facing)`
   - Loads `entities/billboard/<type_id>_sheet.png` + TOML sidecar
   - Extracts cell at `(column=facing_index, row=states[state].row + frame_idx)`

2. **Prism net face** — keys like `"vending_machine:front"`:
   - Loads `entities/prism/<type_id>_net.png` + TOML sidecar
   - Extracts pixel rect defined in `[faces.<suffix>]`

3. **Flat key fallback** — `assets/textures/tiles/<key>.png`

#### Billboard Sheet Extraction

```python
def _load_sheet_info(type_id) → (sheet_surf, cell_w, cell_h, n_cols, n_rows) | None
def _extract_sheet_cell(type_id, state, frame_idx, facing) → Surface | None
def _parse_billboard_suffix(suffix) → (state, frame_idx, facing) | None
```

Grid layout: **columns** = facing directions (S, SW, W, NW, N, NE, E, SE); **rows** = animation frames grouped by `[states.X]` sections. Non-directional entities have 1 column.

`_parse_billboard_suffix()` handles both formats:
- `"idle_0_s"` → `("idle", 0, "s")` — directional
- `"lit_3"` → `("lit", 3, None)` — non-directional

#### Prism Net Extraction

```python
def _load_net_info(type_id) → (net_surface, faces_dict) | None
def _extract_net_face(type_id, face_suffix) → Surface | None
```

Extracts `{x, y, w, h}` pixel rects for named faces from the cross-pattern unfold image.

#### Texture Import

```python
def import_texture(source_path, tile_id=None, *, key=None) → Path
def browse_and_import(tile_id=None, *, key=None) → Path | None  # tkinter file dialog
```

### 12.4 C Extensions

Built via `build_ext.py` with `python build_ext.py build_ext --inplace`.

**Compiler flags:** `-O2 -ffast-math -fopenmp` (Linux/macOS), `/openmp` (Windows).

#### Shared Header (`_ray_render.h`, 811 lines)

All helpers are `static inline` — zero cross-translation-unit linking.

**Key constants:**
| Constant | Value | Purpose |
|----------|-------|---------|
| `MAX_STEPS` | 64 | Max DDA iterations |
| `MAX_DEPTH` | 32.0 | Max render distance |
| `FOG_LUT_LEN` | 256 | Fog lookup table size |
| `PL_STRIDE` | 8 | Doubles per point light |
| `BX_STRIDE` | 14 | Doubles per freeform box |

**Key inline functions:**
- `sample_tex(atlas, ts, tid, u, v, r,g,b,a)` — RGBA atlas sampling
- `fog_val(fog_lut, dist)` / `fog_vol(fog_lut, dist, accum)` — distance/volume fog
- `apply_bump(atlas, ts, tid, u, v, strength, r,g,b)` — luminance-gradient bump mapping
- `resolve_anim_tid(anim_lt, tid, anim_tick)` — animated texture frame selection
- `accumulate_lights(lights, lg, ci, wx, wy, wz, sm, out_r, out_g, out_b)` — point light + shadow
- `build_light_grid / build_shadow_maps` — spatial indexing
- `los_check(cell_solid, ...)` — simplified DDA line-of-sight

#### `_ray_render.c` (3172 lines)

Exports `render_frame(ctx_dict)`. The main 2800+ line function renders walls via DDA with 6+ wall types, multi-tier floor/ceiling scanlines, OBB box rendering, quad/curve intersection, portal tracing, volume fog, point lighting, decals, bump mapping, slopes, Layer-2, reflections, lens distortion, and animated textures.

#### `_ray_entities.c` (557 lines)

Exports `render_entities(dict)` and `render_particles(dict)`.

Entity rendering: Sort far→near, compute camera-relative transform, multi-facing sprite selection (relative angle → 8-way index), per-pixel depth-tested textured billboards with fog and colour tinting.

Particle rendering: Tick (velocity, gravity, lifetime, air damping), sort, render as textured quads or radial-falloff circles with alpha.

#### `_ray_debug.c` (190 lines)

- `depth_to_grayscale(fb, depth_px, sw, sh)` — logarithmic depth visualisation
- `ssao_pass(dict)` — fixed 16-sample disc kernel, per-pixel occlusion via depth comparison

#### `_fast_cast.c` (331 lines)

C port of the Python `cast_walls()`. Same DDA algorithm but ~50× faster. Accepts pre-built LUT buffers.

#### `_fast_walls.c` (242 lines)

Batch geometry computation for all wall slices. Returns 20-field tuples with packed cache keys for efficient Python Surface caching.

---

## 13. Entity Texture Pipeline

The entity texture system uses a uniform pipeline: definition (TOML) → generation (sprite sheet/net PNG) → sidecar (layout TOML) → extraction (atlas loader at runtime).

### 13.1 Billboard Sprite Sheets

**Layout:** A single PNG containing a grid of sprite cells.

```
Columns (left to right) = facing directions
  Directional: S, SW, W, NW, N, NE, E, SE (8 columns)
  Non-directional: 1 column

Rows (top to bottom) = animation frames, grouped by state
  Each state occupies N consecutive rows (one per animation frame)
  Total rows = sum of all state frame counts
```

**Example — `crawler` (directional, 3 states: idle(1) + crawl(4) + hurt(1)):**
```
         S    SW    W    NW    N    NE    E    SE
Row 0:  idle frame 0 across all 8 facings
Row 1:  crawl frame 0 across all 8 facings
Row 2:  crawl frame 1 across all 8 facings
Row 3:  crawl frame 2 across all 8 facings
Row 4:  crawl frame 3 across all 8 facings
Row 5:  hurt frame 0 across all 8 facings
```

**Cell dimensions** are per-entity — stored as `frame_width` / `frame_height` in the entity definition.

### 13.2 Prism Net Textures

**Layout:** A cross-pattern box unfold in a single PNG:

```
              ┌──top──┐
     ┌──left──┼─front──┼─right─┬──back──┐
     └────────┼────────┼───────┴────────┘
              └─(bot)──┘
```

Face pixel dimensions are computed proportionally from the prism's world-space dimensions (width/depth/height), with a reference base of 256px for the largest dimension, aligned to 4px boundaries.

If east and west use the same texture key, they share a single "side" face in the net.

### 13.3 TOML Sidecar Format

Every sprite sheet/net has a companion `.toml` file describing its layout.

**Billboard sidecar (`<type_id>_sheet.toml`):**
```toml
[grid]
frame_width  = 48
frame_height = 32
columns = ["S", "SW", "W", "NW", "N", "NE", "E", "SE"]

[states.idle]
row    = 0       # starting row offset
frames = 1       # number of animation frames

[states.crawl]
row    = 1
frames = 4

[states.hurt]
row    = 5
frames = 1

[meta]
entity_def_hash = "a1b2c3d4e5f6"
```

**Prism sidecar (`<type_id>_net.toml`):**
```toml
[faces.front]
x = 64
y = 32
w = 256
h = 192

[faces.back]
x = 384
y = 32
w = 256
h = 192

# ... more faces ...

[meta]
entity_def_hash = "f6e5d4c3b2a1"
```

The `entity_def_hash` is a SHA-256 fingerprint of the entity's visual properties. The generator warns if the definition has changed since the sheet was created.

### 13.4 Texture Key Scheme

All keys follow the format `sprite_key:suffix`:

**Billboard (directional):** `sprite_key:state_frameIdx_facing`
- Examples: `dummy:idle_0_s`, `dummy:walk_3_ne`, `crawler:crawl_2_sw`

**Billboard (non-directional):** `sprite_key:state_frameIdx`
- Examples: `candle:lit_0`, `candle:unlit_0`, `vent_grate:default_0`

**Prism:** `sprite_key:face`
- Examples: `vending_machine:front`, `vending_machine:side`, `vending_machine:top`

### 13.5 Generator Script

**File:** `gen_entity_textures.py`

CLI tool that generates labelled template sprite sheets for artists to paint over.

**Usage:**
```bash
# Generate all entity templates
python gen_entity_textures.py

# Generate specific entity
python gen_entity_textures.py crawler --force

# With per-state frame counts
python gen_entity_textures.py crawler --frames 'idle=1,crawl=4,hurt=1'

# Override cell dimensions
python gen_entity_textures.py crawler --cell-width 48 --cell-height 32

# List all entity types
python gen_entity_textures.py --list
```

**Template features:**
- Checkerboard fill showing allocated cell space
- 1px white border + corner markers
- Header: state name (top-left) + frame number (top-right)
- Footer: facing label (bottom-left)
- Dark background bars behind text for readability
- Custom 5×7 pixel font with auto-scaling and auto-rotation to fit cells

**Billboard generation (`generate_billboard_textures`):**
- Default cell size from `edef.frame_width` / `edef.frame_height`
- `n_facings` from entity def (`directional` → 8, else 1)
- `frames_per_state` from CLI or defaults to 1
- Writes `<type_id>_sheet.png` + `<type_id>_sheet.toml` to `billboard/`

**Prism generation (`generate_prism_textures`):**
- Computes proportional pixel dimensions per face
- Generates gradient-filled face placeholders with labels
- Cross-pattern layout in single PNG
- Writes `<type_id>_net.png` + `<type_id>_net.toml` to `prism/`

**Change detection:** `_check_def_changed()` compares the stored hash in the TOML against the current definition's fingerprint and warns if they diverge.

**Artist workflow:**
1. `python gen_entity_textures.py goblin` — generates template
2. Artist opens the sheet in an image editor and paints over the labelled cells
3. Run the game — the engine reads cells directly from the sheet at runtime

---

## 14. Systems

### 14.1 Spawner

**File:** `systems/spawner.py`

The main entity factory.

```python
def spawn_from_descriptor(world, desc, zone) → eid
```

1. `_resolve_type(desc)` — looks up type in `entity_registry()` or falls back to `_LEGACY_PREFAB_MAP`
2. `_BUILDERS` dispatch table maps component keys to builder functions:
   - `"position"`, `"identity"`, `"sprite"`, `"collider"`, `"health"`, `"inventory"`, `"tile_entity"`, `"wall_sprite"`, `"prism_shape"`, `"combat"`, `"coarse_pos"`, `"facing"`, `"player"`
3. Each builder adds the corresponding component to the entity

**Batch spawn:** `spawn_zone_entities(world, entities, zone)` processes a zone's entity list.

**Transient rebuild:** `rebuild_transients(world, descriptor_index)` reconstructs non-persisted components after save/load using `PrefabRef` data.

### 14.2 Physics

**File:** `systems/physics.py`

```python
def movement_system(world, dt, tiles, portal_tiles,
                    floor_heights, ceil_heights,
                    floor2_heights, ceil2_heights,
                    player_fh) → new_player_fh
```

For each entity with `Position` + `Velocity`:
1. Apply `vel × dt` to position
2. **Axis-separated collision:** Test X movement independently from Y — enables wall-sliding
3. **Height-aware collision:** Check `MAX_STEP_UP` (0.5m), `MAX_STEP_DOWN` (1.0m), `HEAD_CLEARANCE` (0.4m) against both floor layers
4. **Portal detection:** If player steps on a portal tile, returns the portal for zone transition
5. **Doorway nudge:** Gentle centering force toward portal tile centres for smooth traversal

### 14.3 LOD

**File:** `systems/lod.py`

Level-of-detail transitions between per-frame and per-tick simulation:

- `promote(world, eid)` — `CoarsePos` → `Position` + `Velocity(0,0)` (entity enters active zone)
- `demote(world, eid)` — `Position` → `CoarsePos` (entity leaves active zone; snaps to integer tile)
- `sync_zone_lod(world, active_zone)` — bulk transition after zone change: promotes all in active zone, demotes all others
- `tick_timers(world, dt)` — decrements all `Timers.active` values, prunes expired

### 14.4 Zone Simulator

**File:** `systems/zone_sim.py`

Off-screen zone simulation running at 1 Hz.

```python
class ZoneSim:
    def __init__(self, tick_interval=1.0)
    def load_zone(self, name, zone)       # cache tile array + portals
    def tick(self, dt, active_zone) → int  # fires coarse ticks on inactive zones
```

**Per-zone tick logic:**
1. **Clean dead entities** (hp ≤ 0)
2. **Portal traversal** — NPCs near portals with 3s bounce cooldown
3. **Movement** — A* waypoint pathfinding to random walkable targets; speed-based position updates
4. **Sight checks** — O(n²) pairwise LOS; hostile pairs → `combat_sim.resolve_coarse_combat()`

### 14.5 Pathfinding

**File:** `systems/pathfinding.py`

- `astar(tiles, start, goal, max_steps=800) → list[(r,c)] | None` — A* with Manhattan heuristic, 4-directional, skips `SOLID_IDS`
- `bfs_reachable(tiles, start, max_dist) → set[(r,c)]` — flood-fill BFS
- `random_walkable(tiles, origin, min_dist, max_dist) → (r,c) | None` — random tile in range (20 candidates)
- `visible_tiles(tiles, origin, max_range=12) → set[(r,c)]` — Bresenham LOS raycast
- `entities_in_los(tiles, origin, entities, max_range) → list` — filters by LOS

### 14.6 Combat

**File:** `systems/combat_sim.py`

Off-screen pairwise combat resolution:

```python
def resolve_coarse_combat(world, eid_a, cp_a, eid_b, cp_b, tiles)
```

1. LOS check via `entities_in_los`
2. For each hostile entity: `_apply_attack()`:
   - Damage = base × random(0.8, 1.2)
   - Enforces cooldown via `Timers`
   - Death detection (hp ≤ 0 → `world.kill()`)
   - Logs to `WorldEventLog`

### 14.7 Interaction & Gameplay

**Files:** `systems/interaction.py`, `systems/gameplay.py`

**Interaction detection:**
```python
def nearest_interactable(world) → (eid, dist) | None
```
Finds closest entity in player's facing direction using dot-product scoring. Range: `INTERACT_RANGE = 1.8` tiles.

**Gameplay dispatch (`gameplay.py`):**
- `do_interact_td()` — top-down E-key handler with priority: nearby TileEntity (container → `open_container`, ground item → `pickup_ground_item`) > NPC → `open_npc_dialogue` > Platform fallback
- `do_interact_fp()` — first-person version with angular range checks and raymarching at 0.8/1.2/1.6 tiles

### 14.8 Items & Loot

**Files:** `systems/item_registry.py`, `systems/items.py`, `systems/loot.py`

**Item registry:** Loads `data/items.toml`. `ItemDef` dataclass: `id, type, style, name, kind, char, color, fields`.

**Loot tables (`loot.py`):** Minecraft-style weighted pool rolls:
1. `rolls + random(0, bonus_rolls)` → integer roll count
2. Weighted random selection from pool entries
3. Per entry: `random(min_count, max_count)` quantity

**Containers (`containers.py`):**
- `open_container()` — first-open loot roll, then pushes `TransferModal`
- `open_inventory()` — pushes `InventoryModal` with drop callback
- `open_npc_dialogue()` — builds tree, pushes `DialogueModal`

### 14.9 Dialogue

**File:** `systems/dialogue_gen.py`

Generates dialogue trees from NPC context:
- Time-of-day greeting
- Health status line
- Zone-specific flavour text
- Recent world event references

Output: `{"root": {"text": "...", "choices": [{"label": ..., "next": ..., "action": ...}]}, ...}`

### 14.10 Beast Spawner

**File:** `systems/beast_spawner.py`

Spawns creatures in outdoor zones every 45 seconds. Picks random walkable tiles via `pathfinding.random_walkable()`. Caps at 3 beasts per zone.

**Beast templates:** Feral Dog (hp=30, dmg=6), Rad-Rat (hp=15, dmg=4), Wasteland Crawler (hp=50, dmg=10).

---

## 15. Game Scenes

### 15.1 Main Menu

**File:** `scenes/main_menu.py`

Title screen with New Game, Continue, Settings, Quit. Keyboard (W/S + Enter) and mouse navigation.

### 15.2 Top-Down View

**File:** `scenes/world/topdown.py` (689 lines)

Tile-based top-down view. Owns `Session`, `ModalStack`, `ItemRegistry`.

**Controls:** WASD movement, E interact, I inventory, Tab debug panel, F5 save, F9 load, Enter → first-person, comma/period → time scale.

**Update loop:** Ticks `WorldClock`, `ZoneSim`, `BeastSpawner`, `movement_system`, processes modal commands.

**Portal handling:** Saves current zone entities, loads target zone, `sync_zone_lod()`, spawns player at target.

### 15.3 First-Person View

**File:** `scenes/world/firstperson.py` (860 lines)

Doom-style raycaster view. Creates a `RayRenderer` at half resolution (`_RSCALE=2`).

**Constants:** `TURN_SPEED=3.5`, `MOUSE_SENSITIVITY=0.004`, `DASH_SPEED=12`, `DASH_DURATION=0.15`, `EYE_HEIGHT=0.5`.

**Controls:** WASD + mouse look, Shift sprint, Space dash, E interact, I inventory, F6 perf log, F12 screenshot.

**Rendering pipeline (C renderer path):**
1. `renderer.render(px, py, angle, cam_h, pitch)` — walls + floors + ceilings
2. `renderer.render_entities(px, py, angle)` — billboards
3. `renderer.render_particles(...)` — particles
4. Optional `renderer.apply_ssao()` — ambient occlusion
5. HUD overlay

**Python fallback path (`fp_renderer.py`):**
- `draw_walls()` — DDA raycasting every 4 columns with interpolation
- `draw_floor_ceiling()` — vectorised numpy scanline rendering
- `draw_entities()` — far→near billboard compositing
- `draw_wall_entities()` — wall-mounted sprite/prism rendering

### 15.4 HUD

**File:** `scenes/world/fp_hud.py`

Renders: health bar, crosshair, minimap (top-right), compass, zone name, world clock, interaction prompt, toast notifications, controls hint bar, debug overlay (toggled with Tab).

### 15.5 Pause & Settings

- `scenes/pause_menu.py` — Resume, Save, Settings, Debug, Main Menu, Quit
- `scenes/settings_menu.py` — FPS cap cycling, fullscreen toggle
- `scenes/save_slots.py` — 3-slot save system with delete confirmation

### 15.6 Debug Scenes

- `scenes/debug_menu.py` — LOD Exhibit, Live LOD Viewer, Map Editor (subprocess)
- `scenes/exhibit_lod.py` — Standalone LOD demonstration with minimap + A* paths
- `scenes/live_lod.py` — Read-only LOD state viewer showing per-zone entity counts

---

## 16. UI System

**Package:** `ui/`

### Modal Architecture

```python
class Modal(ABC):
    def update(self, dt)
    def handle_event(self, event) → list[UICommand]
    def draw(self, surface, app)

class ModalStack:
    def push(modal) / pop()
    def handle_event(event) → list[UICommand]  # forwards to topmost only
    def draw(surface, app)                      # draws all bottom → top
```

**Design principle:** Modals are decoupled from game logic. They return `UICommand` objects that scenes process:

| Command | Fields | Purpose |
|---------|--------|---------|
| `CloseModal` | — | Pop topmost modal |
| `HealPlayer` | `amount` | Heal player HP |
| `OpenTrade` | `npc_eid` | Open trade UI |
| `SetFlag` | `flag, value` | Set quest/state flag |

### Modals

**`InventoryModal`** — Single-panel inventory overlay. W/S or mouse to navigate, Enter to use (consumables decrement + `HealPlayer`), Q to drop single, X to drop stack.

**`TransferModal`** — Two-panel container ↔ player transfer. A/D to switch panels, Enter to transfer.

**`DialogueModal`** — NPC conversation tree renderer. Navigates `{node_id: {text, choices}}` tree. Choice actions: `"close"`, `"open_trade"`, `"set_flag:name:value"`, `"next"`.

---

## 17. Zone Editor

### 17.1 Architecture & Composition

**Entry point:** `zone_editor.py` → `editor.app.ZoneEditorApp`

The editor is composed of two main composite classes assembled from mixins:

```
ZoneEditorApp (editor/app/app.py)
  ├── PanelsMixin (panels_pkg/)
  │     ├── MenuBarMixin      — File/Edit/View/Zone/Data/Window menus
  │     ├── ToolboxMixin      — Left panel: mode/tool/palette
  │     ├── InspectorMixin    — Right panel: cell/bulk/object inspectors
  │     └── OverlaysMixin     — Help/keybind overlays
  ├── DialogsMixin            — 9 imgui dialog windows
  ├── ViewportMixin           — GL framebuffer blit
  ├── RaycasterMixin          — FP preview panel
  ├── EventsMixin             — Pygame event pump
  ├── AssetBrowserMixin       — Texture file browser
  ├── DataViewersMixin        — TOML data browsers
  ├── EntityCreatorMixin      — Entity type authoring
  ├── EntityTexturesMixin     — Sprite sheet status
  └── DialogPropertyBridge    — show_* property routing

Zone3DEditor (editor/view_3d/editor.py)
  ├── RenderingMixin          — 3D viewport drawing (2224 lines)
  ├── DrawPrimitivesMixin     — Line/box/filled-box primitives
  ├── GeometryMixin           — Cell bounding-box computation
  ├── UndoMixin               — Snapshot-based undo/redo
  ├── SaveMixin               — Zone file persistence
  ├── SculptMixin             — Floor/ceiling/wall geometry
  ├── PaintMixin              — Texture painting
  ├── FillMixin               — Flood fill
  ├── EraseMixin              — Cell/height/texture erasing
  ├── SelectMixin             — Rectangle/contiguous selection
  ├── SegmentMixin            — Wall segment split/merge/paint
  ├── StampMixin              — Preset stamp application
  ├── EntityMixin             — Entity placement/rotation
  ├── BoxMixin                — Prism box editing
  ├── Layer2Mixin             — Secondary floor/ceiling layer
  ├── QuadMixin               — Vertical quad panels
  ├── PortalMixin             — Zone portal placement
  ├── CurveMixin              — Curved wall arcs
  └── OverlayWallMixin        — Freeform overlay walls
```

**Window:** 1600×900 pygame display with OpenGL context. imgui renders over an OpenGL fullscreen quad that displays the pygame 3D viewport Surface.

### 17.2 Input System

**Input Stack:** Priority-ordered list of `InputContext` objects. Events dispatch top→bottom; a context can block propagation via `blocks_below = True`.

```python
class InputContext(ABC):
    name: str
    blocks_below: bool = True
    def handle_event(self, event) → bool  # True = consumed

class InputStack:
    def push/pop(ctx)
    def dispatch(event) → bool
```

**Concrete contexts:**
1. `GlobalShortcutsContext` — Intercepts Ctrl+Z/Y, Ctrl+S, Ctrl+C/V, Esc, F-keys, camera bookmarks. `blocks_below=False`.
2. `CapturedViewportContext` — Active during mouse capture. Forwards all events to `Zone3DEditor` handlers. `blocks_below=True`.
3. `StampCaptureContext` — Active during preset naming. Intercepts key events for text input. `blocks_below=True`.

### 17.3 Command Bus

**Pattern:** Frozen `Command` dataclasses → `CommandBus.execute()` → registered handler function → `EventBus.emit(StateChanged)`.

```python
@dataclass(frozen=True)
class Command: pass

class CommandBus:
    def register(cmd_type, handler)
    def execute(cmd) → Any                    # takes undo snapshot
    def execute_continuation(cmd) → Any       # no undo push (mid-drag)

class EventBus:
    def subscribe(event_type, callback)
    def emit(event)
```

**Context managers for handler implementation:**
- `suppress_undo()` — prevents UndoMixin from creating a snapshot
- `detect_change()` — yields dict; handler sets `d["changed"] = True` if zone was modified
- `suppress_and_detect()` — combines both

**Editor events:**
- `StateChanged` — zone data modified
- `SelectionChanged` — cells/objects selection changed
- `ToolChanged` — active tool switched
- `ViewDirtied` — viewport needs redraw

**Command inventory:** 87 defined commands across 10 files:
- `sculpt_cmds.py` — 17 commands (floor raise/lower, ceiling operations, wall convert, upper wall, extend, flatten)
- `paint_cmds.py` — 12 commands (face paint, flood fill, selection fill, continuous paint)
- `erase_cmds.py` — 3 commands (cell reset, height reset, texture clear)
- `object_cmds.py` — 31 commands (entity/box/quad/portal/curve/overlay CRUD + manipulation)
- `select_cmds.py` — 3 commands (batch scroll, delete, reset)
- `segment_cmds.py` — 3 commands (split, merge, paint)
- `stamp_cmds.py` — 1 command (apply preset)
- `misc_cmds.py` — 3 commands (clipboard paste, duplicate, delete selected)
- `l2_cmds.py` — 14 commands (Layer-2 equivalents of sculpt/paint/select operations)

### 17.4 3D Viewport Renderer

**File:** `editor/view_3d/rendering.py` (2224 lines)

Software-rasterised 3D view using projected polygons (no GPU shading).

**Projection math (`math3d.py`):**
- `_perspective(fov, aspect, near, far)` — 4×4 perspective matrix
- `_build_view_matrix(eye, yaw, pitch)` — Euler-angle look-at matrix
- `_project(vp, x, y, z, hw, hh)` — world → screen with near-plane clip
- `_project_poly(vp, corners, hw, hh)` — Sutherland-Hodgman near-plane clipping
- `_visible_cell_set(frustum_planes, W, H, heights)` — AABB frustum culling

**Draw order in `draw(surface, dt)`:**
1. Skybox panorama (cylindrical angular mapping)
2. Axes (XYZ lines)
3. Cell boxes — depth-sorted, face-shaded from texture colours, with backface culling
4. Surface markers — height-level wireframe indicators
5. Segment boundary rings
6. Layer 2 slabs — floor2/ceil2 with opacity control
7. Entities — solid coloured boxes + direction arrows + labels + ghost preview
8. Boxes/prisms — rotated shaded boxes
9. Quads — vertical rectangles with diagonal crosses
10. Portals — face outlines + translucent fill + destination line
11. Curves — arc wireframes
12. Overlay walls — vertical rectangles + placement ghost
13. Selection highlight — per-cell translucent slabs
14. Face highlight + preview — aimed face, prism/quad face, merge target
15. Crosshair — tool-coloured, Layer-2 diamond badge
16. Action context — LMB/RMB/Scroll hint overlay
17. Hotbar — 10 texture quick-access slots
18. HUD — layer/mode/tool/selection/snap/texture/cell info

**Picking (`picking.py`):**
- `_ray_vs_aabb(origin, forward, box_min, box_max)` — standard AABB intersection
- `_ray_vs_obb(origin, forward, cx, cz, w, h, d, base_y, yaw)` — yaw-rotated oriented bounding box
- `_CellHit` — result with `t, col, row, part, face, hit_y`

### 17.5 Selection System

**Legacy (`selection.py`):** Index-based `SelectionState` with `cells: set[(r,c)]` and `objects: set[(type_tag, index)]`. Rectangle selection via Bresenham line.

**Phase 2 (`selection_store.py`):** UID-based `SelectionStore` — objects identified by persistent integer UIDs rather than list indices.

```python
class SelectionStore:
    def select_object(type_tag, uid)
    def toggle_object(type_tag, uid)
    @property primary_uid → int | None      # focused object
    def primary_index(zone) → int | None    # resolve UID → list index
    def selected_uids_by_type(type_tag) → list[int]
```

**Bridge properties** on `Zone3DEditor` translate between legacy `_*_selected` index fields and UID-based selection — allowing incremental migration without breaking existing code.

**Object Layer (`objects.py`):** Unified cross-type operations with dispatch tables for select/delete/move across all object types (entity, box, quad, portal, curve, overlay).

### 17.6 Tool Mixins

The editor has 4 modes and 11 tools:

| Mode | Tools |
|------|-------|
| Architecture | Sculpt, Segment |
| Surface | Paint |
| Props | Box, Quad, Curve, Overlay |
| Logic | Entity, Portal |
| (Utility) | Select, Stamp |

**Sculpt** — Floor/ceiling height manipulation. Single-cell and batch operations. Snap grid (0.25/0.5/1.0/0.125/0.0625). Upper wall height control. Extend (gap-preserving scroll). Flatten selection. Auto-segment management.

**Paint** — Texture painting on individual faces, all faces, or selections. Eyedropper (pick from aimed). Flood fill (BFS) with 9 modes (floor, ceiling, wall_n/s/e/w, step_floor, step_ceil, l2_floor, l2_ceil). Continuous paint during drag.

**Segment** — Wall face subdivision. Split at crosshair Y position, merge nearest boundary, paint individual segments.

**Select** — Rectangle selection (click + drag). Contiguous selection (Shift+A — flood-fill by matching heights). Batch raise/lower, delete, fill, clear.

**Stamp** — Cell preset application. Capture (save aimed cell as preset), apply (stamp preset onto aimed or selection).

**Entity** — Placement from entity palette, selection, movement (drag to aimed), rotation (8-way snap), state cycling, deletion.

**Box** — Prism placement with grid snap and auto-stacking, selection, 90°/fine rotation, size adjustment, Z-shift, per-face texture painting.

**Quad** — Vertical panel placement, rotation, size adjustment, two-sided toggle, texture painting.

**Portal** — Wall-face-based portal placement/deletion, destination linking.

**Curve** — Arc wall placement, radius/angle adjustment, texture painting.

**Overlay** — Two-click freeform wall placement, height/transparency/texture control.

**Layer 2** — Secondary floor/ceiling layer with all sculpt/paint/select operations mirrored. Toggle between floor2/ceil2 target. Isolation mode (show only active layer).

### 17.7 Panels & UI

**Menu bar:** File (New, Open, Save, Recent, Quit), Edit (Undo/Redo, Copy/Paste, Duplicate), View (Wireframe, Axes, Floors, Walls, Ceilings, Entities, HUD, Layer 1/2, Isolate), Zone (Resize, Validate, Export, Settings), Data (Entity/Item/Loot/Preset viewers), Window (Asset Browser, Entity Creator, Texture Status).

**Left panel (Toolbox):** Mode tabs, sub-tool buttons, texture palette (scrollable grid with hotbar), preset palette, entity palette with preview, tool controls (snap, grid, layer2 target), context-sensitive hints.

**Right panel (Inspector):** Context-sensitive property editors:
- **Cell inspector** — floor/ceil heights, tile type, textures, segments, lighting, reflectivity, fog
- **Bulk inspector** — batch editors for multi-cell selection with mixed-value summaries
- **Object inspectors** — entity, prism, quad, portal, curve, overlay wall properties

**Dialogs:** Resize (with object relocation), Validate Zone (runs `validate_zone()` with full registries, displays `ZoneIssue` objects with severity/category/message/location), Export (top-down PNG), New Zone, Load, Zone Settings, Confirm Quit/New, Error.

**Validation HUD:** Persistent bar above the status bar drawn by `_draw_validation_hud()` in `PanelsMixin`. Shows error/warning counts from the last save. "Details" button opens the Validate Zone dialog with the full issue list.

**Asset Browser:** Floating texture browser with category tabs (Walls, Floors, Ceilings, Decals, All), GL thumbnail cache, import/delete.

**Keybind registry:** ~70 keybinds across 15 categories with rebinding, conflict detection, JSON persistence. Help overlay displays full shortcut reference.

### 17.8 Undo System

**File:** `editor/view_3d/undo.py`

Snapshot-based undo/redo. `_snapshot()` captures **all** zone grids and object lists. Type-specific fast copiers replace `deepcopy` for performance:

```python
def _copy_grid(grid)        # 2D
def _copy_grid_3d(grid)     # 3D (face_textures)
def _copy_grid_4d(grid)     # 4D (segments)
def _copy_dict_list(lst)    # [{...}, ...]
def _copy_overlay_walls(lst)
```

Undo stack + redo stack. Snapshot taken before first command in a logical operation (the command bus manages this). `Ctrl+Z` / `Ctrl+Y`.

---

## 18. Data Files

### Entity Definitions (`data/entity_defs.toml`)

Each top-level key is an entity type with component sub-tables:

```toml
[crawler]
display_name = "Wasteland Crawler"
category = "characters"
render_type = "billboard"
directional = true
states = ["idle", "crawl", "hurt"]
scale = 0.5
frame_width = 48
frame_height = 32

[crawler.identity]
name = "Wasteland Crawler"
kind = "beast"

[crawler.health]
current = 40
maximum = 40

[crawler.combat]
damage = 8
attack_range = 1.5
hostile = true

[crawler.sprite]
char = "B"
color = [60, 120, 60]
billboard_mode = 1    # 8-way
```

**Defined types:** `dummy`, `player`, `test`, `vent_grate`, `candle`, `wall_lamp`, `sign_post`, `crawler`, `vending_machine`, `ground_item`, `loot_socket`, `spawn_point`, `trigger_zone`.

### Items (`data/items.toml`)

Weapons (knife, hoe, bat, pistol, rifle, shotgun) and consumables (canned_beans, dried_meat, stew, ration, bandages, antibiotics). Each has `[id.identity]` and `[id.sprite]` sub-tables plus type-specific fields (damage, heal, accuracy, range, etc.).

### Loot Tables (`data/loot_tables.toml`)

Minecraft-style weighted pools. Tables: `basic_chest`, `treasure_chest`, `empty_chest`.

### Cell Presets (`data/presets/*.toml`)

Reusable cell recipes: `brick_wall`, `open_ground`, `stone_platform`, `wooden_counter`, `segmented_brick`.

---

## 19. Build System

**File:** `build_ext.py`

Uses setuptools to compile C extensions:

```bash
python build_ext.py build_ext --inplace
```

**Extensions:**
| Module | Sources | Purpose |
|--------|---------|---------|
| `engine._fast_cast` | `_fast_cast.c` | DDA raycaster |
| `engine._fast_walls` | `_fast_walls.c` | Wall geometry batch |
| `engine._ray_render` | `_ray_render.c`, `_ray_entities.c`, `_ray_debug.c` | Full frame renderer |

**Compiler flags:** `-O2 -ffast-math -fopenmp` (Linux/macOS), `/openmp` (Windows).

If compilation fails, the engine uses pure-Python fallbacks defined in `engine/raycaster.py` and `scenes/world/fp_*.py`.

---

## 20. Testing

Test suite in `tests/` covers:
- `test_ecs.py` — ECS world operations
- `test_events.py` — Event bus subscribe/emit/flush
- `test_save.py` — Save/load round-trip
- `test_raycaster.py` — DDA wall casting correctness
- `test_ray_render.py` — C renderer integration
- `test_render_edge_cases.py` — Renderer edge cases
- `test_pathfinding.py` — A*/BFS/LOS algorithms
- `test_interaction.py` — Interaction detection
- `test_lod.py` — LOD promote/demote/sync
- `test_command_bus.py` — Editor command bus
- `test_editor_tools.py` — Editor tool operations
- `test_editor_renderer.py` — 3D viewport rendering
- `test_erase_handlers.py` — Erase command handlers
- `test_selection_store.py` — UID-based selection
- `test_input_stack.py` — Input context dispatch
- `test_handler_coverage.py` — Command handler registration
- `test_session6.py` — Validation HUD, CF_TRANSPARENT flag & migration, zone preview, registry-backed validation, sky_color wiring, overlay wall base_y, deferred budget validation (51 tests)
- Benchmark scripts: `bench_render.py`, `bench_ceiling.py`, `bench_micro.py`

---

## 21. Complete Data Flow

### Game Boot Sequence

```
main.py
  └→ App(title, width, height)
       ├→ pygame.init(), display setup (RESIZABLE | SCALED)
       ├→ World() (ECS container)
       └→ push_scene(MainMenu)

MainMenu → user selects "New Game"
  └→ SaveSlots("new") → user picks slot
       └→ Session(app.world)
            ├→ session.new_game("playground")
            │    ├→ _load_zone_template("playground")
            │    │    ├→ loads .zone binary file
            │    │    ├→ populates tiles, heights, textures arrays
            │    │    └→ builds portal map
            │    ├→ spawn player at anchor tile
            │    ├→ spawn_zone_entities(world, zone.entities, zone_name)
            │    ├→ set resources: Camera, GameClock, WorldClock, WorldEventLog
            │    └→ _init_background_sim() → loads all zones into ZoneSim
            └→ push_scene(TopDown or FirstPerson)
```

### Frame Loop (First-Person)

```
App.run():
  clock.tick(100)                    # cap FPS
  dt = smoothed delta time

  for event in pygame.event.get():
    scene.handle_event(event)        # mouse look, key presses

  scene.update(dt):
    session.tick_world(dt):
      1. WorldClock.advance(dt)
      2. tick_timers(dt)
      3. ZoneSim.tick(dt)            # off-screen NPC movement + combat
      4. BeastSpawner.tick(dt)       # creature spawning
      5. Container restocking
      6. world.purge()               # remove dead entities

    movement_system(dt):
      1. velocity → position
      2. axis-separated collision
      3. height-aware step checks
      4. portal detection

    session.update_transition(dt):
      1. fade alpha interpolation
      2. teleport at alpha=1.0
      3. auto-walk after teleport

  scene.draw(surface):
    renderer.render(px, py, angle, cam_h, pitch)    # C extension
      Phase 0: Background (skybox)
      Phase 1: DDA walls + boxes + quads + curves + portals
      Phase 2: Multi-tier textured floors + bump + decals
      Phase 3: Multi-tier textured ceilings
      Phase 4: Deferred wall compositing

    renderer.render_entities(px, py, angle)           # billboards
    renderer.render_particles(px, py, angle, dt)      # particles
    renderer.apply_ssao()                             # ambient occlusion
    hud.draw()                                        # health, minimap, etc.
    modal_stack.draw()                                # any open modal

  screen.blit(surface)
  pygame.display.flip()
```

### Entity Texture Data Flow

```
data/entity_defs.toml
  │
  ├→ entity_registry() loads EntityDef instances
  │     ├─ frame_width, frame_height (per-entity cell dimensions)
  │     ├─ states, directional, render_type
  │     └─ sprite_key
  │
  ├→ gen_entity_textures.py
  │     ├─ Billboard: generates <type_id>_sheet.png + .toml sidecar
  │     │     Grid: columns=facings, rows=sum(frames per state)
  │     │     TOML: [grid] + [states.X] sections with row offsets
  │     └─ Prism: generates <type_id>_net.png + .toml sidecar
  │           Cross pattern: face rects described in [faces.X]
  │
  ├→ entity_texture_keys() → ordered list of atlas keys
  │     Billboard: "sprite:state_frame_facing" or "sprite:state_frame"
  │     Prism: "sprite:face"
  │
  └→ TextureAtlas.get_by_key(key)
        ├─ _parse_billboard_suffix() → (state, frame_idx, facing)
        ├─ _load_sheet_info() → loads PNG + TOML sidecar
        ├─ _extract_sheet_cell() → extracts cell at correct row/col
        │     row = states[state].row + frame_idx
        │     col = facing index in columns array
        └─ Resizes to TEX_SIZE (128×128) for atlas packing

RayRenderer._build_buffers():
  atlas → packed RGBA [num_tiles × 128 × 128 × 4]
  entity base_tex = atlas index of "sprite:first_state_0_s"
  n_facings = 8 (or 1)
  anim_offset = per-frame texture offset

C render_entities():
  relative_angle = camera→entity angle - entity facing angle
  octant = quantise to 0..7
  tex_id = base_tex + octant + anim_offset * n_facings
  sample from packed atlas, depth-test, fog, tint
```

### Editor Data Flow

```
zone_editor.py → ZoneEditorApp
  ├→ pygame + OpenGL + imgui init
  ├→ Zone3DEditor(zone, atlas, keybinds, event_bus)
  │     ├→ CommandBus + handler registration
  │     ├→ SelectionStore (UID-based)
  │     └→ ObjectLayer (cross-type dispatch)
  │
  ├→ Main loop (60 fps):
  │     1. Event pump → InputStack.dispatch()
  │     2. Zone3DEditor.update(dt)
  │     │     ├→ Camera WASD + mouse look (fly_camera math)
  │     │     ├→ Camera collision (circle vs cell AABBs)
  │     │     ├→ _update_aim() → ray picks cell/face/object
  │     │     └→ Continuous paint execution
  │     3. imgui frame:
  │     │     ├→ _menu_bar()
  │     │     ├→ _left_panel() (toolbox, palettes)
  │     │     ├→ _properties_panel() (inspectors)
  │     │     ├→ _status_bar()
  │     │     └→ Dialogs (resize, settings, etc.)
  │     4. Zone3DEditor.draw(surface, dt) → 3D viewport
  │     5. GL texture upload → fullscreen quad blit
  │     6. imgui render over GL
  │
  └→ Save: Zone → compile_zone_to_arrays() → save_binary_zone() → .zone file
```

---

## Appendix: Architectural Hardening (Session 2)

This section documents the defensive measures added in a focused
architecture-improvement pass.  Each subsection maps to a specific risk
identified in the original audit.

### A1 — C Renderer Dict Validation (`engine/render_schema.py`)

**Problem:** The four C entry points (`render_frame`, `render_entities`,
`render_particles`, `ssao_pass`) accept an untyped Python `dict` with
60+ keys total.  A missing or mis-typed key causes a segfault in C code
with no Python traceback.

**Fix:** New module `engine/render_schema.py` defines per-entry-point
schema tables (`RENDER_FRAME_REQUIRED`, `RENDER_ENTITIES_REQUIRED`, etc.)
listing every key, its expected type, and whether it's mandatory.  Type
tags: `INT`, `FLOAT`, `BUF_R`, `BUF_W`, `OPT_INT`, `OPT_FLOAT`,
`OPT_BUF`, `OPT_TUPLE`.  Four validator functions
(`validate_render_frame()`, etc.) check the dict against the schema at
runtime, raising `RenderSchemaError` for missing keys, wrong types, or
unknown keys.

Validation is **opt-in** via the environment variable
`PAPS_VALIDATE_RENDER=1` to avoid overhead in release builds.
`ray_renderer.py` conditionally imports and calls the validators before
each C function call.

### A2 — Transient Rebuild Guard (`core/ecs.py`, `core/save.py`, `systems/spawner.py`)

**Problem:** After `restore_entity()` recreates entities from a save,
transient components (sprites, colliders) haven't been rebuilt.  If any
system reads them before `rebuild_transients()`, it gets stale or missing
data silently.

**Fix:**
- `World._transients_valid: bool` flag — set to `False` by
  `restore_entity()`, set to `True` at the end of `rebuild_transients()`.
- `World.assert_transients_valid()` — raises `RuntimeError` if called
  while the flag is `False`.  Systems that depend on transients should
  call this as a precondition.

### A3 — PrefabRef Version Detection (`core/entity_defs.py`, `components/__init__.py`, `systems/spawner.py`)

**Problem:** When an entity definition in TOML changes (new components,
different textures), previously-saved entities carry stale transient
data.  There was no way to detect this mismatch.

**Fix:**
- `EntityDef.def_version` — a SHA-1 hash (12 hex chars) of the
  definition's component structure, textures, and render type.
- `PrefabRef.def_version: str` — stored at spawn time.
- `rebuild_transients()` compares the current `EntityDef.def_version`
  against the stored `PrefabRef.def_version` and logs a warning on
  mismatch, identifying exactly which entity outdated.

### A4 — ZoneSim Tick Cap (`systems/zone_sim.py`)

**Problem:** At high `WorldClock.time_scale`, the accumulator could
accrue many seconds per real frame, causing hundreds of coarse ticks in
a single frame and dropping FPS.

**Fix:**
- `MAX_TICKS_PER_FRAME = 10` — the tick loop caps at 10 iterations.
- Excess accumulator time beyond `2× tick_interval` is discarded to
  prevent spiral-of-death lag buildup.

### A5 — Stable Atlas Index Map (`core/tiles/registry.py`)

**Problem:** Adding a new entity type (texture key) could shift all
existing atlas indices, silently breaking any zone that was saved with
the old numbering.

**Fix:** `data/_atlas_index_map.json` stores a persistent `key → index`
mapping.  Once a key is assigned an index, it keeps that index forever.
New keys get the next available index.  The registry loads this map on
startup and saves it after registering new keys.

### A6 — Zone Generation Tracking (`core/zones/zone.py`, `engine/ray_renderer.py`, `editor/view_3d/editor.py`)

**Problem:** The editor's `self.dirty` bool and the renderer's
`update_zone()` had no way to tell whether the zone data had actually
changed, causing either redundant full rebuilds or missed updates.

**Fix:**
- `Zone._generation: int` — monotonic counter bumped by
  `bump_generation()`.
- `RayRenderer._zone_generation: int` — tracks the last generation it
  compiled.  `update_zone()` skips the rebuild if generation hasn't
  changed (unless `force=True`).
- `Zone3DEditor.dirty` is now a `@property` — the setter automatically
  calls `zone.bump_generation()` when set to `True`, so all 50+ mixin
  sites that write `self.dirty = True` get tracked automatically.

### A7 — Session Decomposition (`core/zone_map.py`, `core/status_bar.py`, `core/session.py`)

**Problem:** Session was a flat bag of 30+ attributes mixing zone
layout, HUD state, portal data, animation state, and sim objects.

**Fix:** Extracted two focused data objects:
- **`ZoneMap`** — dataclass holding the 12 zone-layout attributes
  (`tiles`, `rotations`, `floor_heights`, etc.) with a
  `load_from_zone(zd)` method.
- **`StatusBar`** — lightweight toast-message holder with `show(msg,
  duration)` and `tick(dt)`.

Session now composes these as `self.zone_map` and `self.status_bar`,
with **property shims** (`@property tiles`, `@property status`, etc.)
that delegate to the composed objects.  All existing consumer code
(`session.tiles`, `session.status = ...`) works unchanged.  New code
should prefer `session.zone_map.tiles` and `session.status_bar.show()`.

### A8 — Portal Positional Bounce Prevention (`systems/zone_sim.py`)

**Problem:** NPC portal bounce prevention used a 3-second `PORTAL_CD`
timer.  This was imprecise — an NPC might sit idle on a portal for
seconds after arrival, or a fast NPC might bounce back after the timer
expired but before it actually moved off.

**Fix:** Replaced the timer with a `_portal_arrivals: dict[int,
tuple[int, int]]` mapping each entity to the tile it arrived at.  The
portal is skipped while the entity remains on its arrival tile.  Once it
moves away (checked at the start of `_check_portal`), the entry is
cleared and the entity can use portals normally.  This mirrors the
player's `_portal_arrival` mechanism exactly.

### Remaining Tech Debt

These items were identified but not addressed in this pass:

1. **Zone3DEditor size** — the class is ~2000 lines across 17+ mixin
   files.  Consider splitting into a scene-graph + tool-controller
   pattern, where each editing tool is an independent object rather than
   a mixin method.

2. **`WorldTickerMixin.ALL_ZONES` hard-coded list** — new zones require
   editing this list.  Should scan the zones directory at startup or use
   a registry.

3. **Entity descriptor index not zone-scoped** — `_descriptor_index`
   maps uid → descriptor globally.  If two zones use the same uid for
   different entities, the last loaded wins.  Consider scoping by zone
   name.

4. **Session property shims** — the backward-compat properties on
   Session should be systematically removed over time, migrating
   consumers to read `session.zone_map.*` and `session.status_bar.*`
   directly.

---

*This document was generated from the complete codebase of Post-Apocalyptic Pawn Shop.*
