# Post-Apocalyptic Pawn Shop

A 2.5D post-apocalyptic survival RPG built with Python and pygame, featuring a Doom-style raycasting engine, a full 3D zone editor, and an entity-component-system architecture.

You play as a shopkeeper surviving in the wasteland — scavenging, trading, and managing your pawn shop while navigating a world filled with NPCs, beasts, and loot.

---

## Table of Contents

- [Features](#features)
- [Screenshots](#screenshots)
- [Requirements](#requirements)
- [Installation](#installation)
- [Running the Game](#running-the-game)
- [Zone Editor](#zone-editor)
- [Project Structure](#project-structure)
- [Architecture](#architecture)
  - [Rendering Engine](#rendering-engine)
  - [Entity-Component-System](#entity-component-system)
  - [Zone Data Model](#zone-data-model)
  - [Game Systems](#game-systems)
- [Controls](#controls)
- [Building C Extensions](#building-c-extensions)
- [Tests](#tests)
- [License](#license)

---

## Features

- **Dual-view gameplay** — seamless top-down and first-person raycaster perspectives
- **C-accelerated 2.5D renderer** — textured walls, floors, ceilings with per-cell heights, Doom-style sector lighting, fog, and entity billboards
- **3D zone editor** — fly-camera wireframe sculpting with ImGui panels, real-time raycaster preview (Tab to toggle)
- **6 editor tools** — Sculpt, Paint, Fill, Erase, Segment, Select with undo/redo
- **Per-face texture stacking** — wall segments allow multiple textures per face (brick base, window, trim)
- **Height-based geometry** — variable floor/ceiling heights, step walls, upper wall extensions, overlay walls
- **ECS architecture** — typed entity-component-system with persistent save/load
- **Procedural dialogue** — context-aware NPC dialogue based on health, time of day, zone, and world events
- **Off-screen simulation** — combat and zone activity continue in unloaded zones
- **Loot tables** — TOML-driven random item generation
- **Modal UI framework** — inventory, trading, and dialogue modals using a command pattern
- **TOML-driven tile registry** — add new tiles/textures without code changes
- **Binary zone format** — chunked `.zone` files with msgpack entity data and numpy height arrays
- **13 pre-built zones** — campsite, crossroads, pawn shop, outskirts, and more

---

## Screenshots

*Coming soon*

---

## Requirements

- **Python** 3.11+
- **C compiler** (optional, for native renderer acceleration)
  - Windows: [Microsoft C++ Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) (`cl.exe`)
  - Linux/macOS: `gcc` or `clang`

### Python Packages

```
pygame >= 2.0.0
numpy
msgpack >= 1.0.0
tomli >= 2.0.0
PyOpenGL >= 3.1.0
PyOpenGL_accelerate >= 3.1.0
imgui[pygame] >= 2.0.0
```

---

## Installation

```bash
# Clone the repository
git clone https://github.com/your-username/Post-Apocalyptic-Pawn-Shop.git
cd Post-Apocalyptic-Pawn-Shop

# Create and activate a virtual environment
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux/macOS
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Build C extensions (optional but recommended — ~50x faster rendering)
python build_ext.py build_ext --inplace
```

---

## Running the Game

```bash
python main.py
```

The main menu offers **New Game**, **Continue** (if a save exists), **Settings**, and **Quit**.

---

## Zone Editor

The standalone zone editor provides a 3D wireframe sculpting environment with an ImGui panel UI and a live raycaster preview.

```bash
# Launch with a blank zone
python zone_editor.py

# Open an existing zone
python zone_editor.py pawn_shop
```

### Editor Features

| Feature | Description |
|---------|-------------|
| **Sculpt** | Raise/lower floors and ceilings, dig rooms, create terrain |
| **Paint** | Apply textures to floors, ceilings, walls, and individual faces |
| **Fill** | Flood-fill textures bounded by height/segment changes |
| **Erase** | Reset cells, clear textures, flatten heights |
| **Segment** | Split wall faces into stacked texture bands (trim, windows, etc.) |
| **Select** | Rectangular area operations — batch raise/lower, texture, delete |
| **Undo/Redo** | Snapshot-based history (Ctrl+Z / Ctrl+Y) |
| **Raycaster Preview** | Tab toggles between editor and first-person preview |

### Editor Controls

**3D Editor (mouse captured):**

| Key | Action |
|-----|--------|
| W/S/A/D | Fly camera |
| Mouse | Look around |
| 1–6 | Select tool |
| LMB | Primary tool action |
| RMB | Secondary tool action |
| MMB | Paint / eyedropper |
| Scroll | Tool-specific (extend, cycle texture, adjust) |
| G | Cycle snap height (1/16, 1/8, 1/4, 1/2, 1) |
| V | Toggle wall rendering |
| R | Reset aimed cell height |
| Delete | Full cell reset |
| Ctrl+S | Save zone |
| Tab | Switch to raycaster preview |
| Escape | Release mouse to UI panels |

**Raycaster Preview (mouse captured):**

| Key | Action |
|-----|--------|
| W/S/A/D | Walk around |
| Mouse | Look |
| Shift | Sprint |
| Ctrl | Slow walk |
| I | Toggle interior rendering |
| Tab | Switch back to editor |

---

## Project Structure

```
Post-Apocalyptic-Pawn-Shop/
├── main.py                  # Game entry point
├── zone_editor.py           # Standalone 3D zone editor
├── build_ext.py             # C extension build script
├── requirements.txt         # Python dependencies
│
├── core/                    # Engine core
│   ├── app.py               # Pygame application shell & scene stack
│   ├── ecs.py               # Entity-Component-System
│   ├── scene.py             # Base scene class
│   ├── save.py              # JSON save/load system
│   ├── events.py            # Event bus
│   ├── session.py           # Game session state
│   ├── constants.py         # Global constants
│   ├── fonts.py             # Font loading
│   ├── paths.py             # Project directory paths
│   ├── transition.py        # Scene transition effects
│   ├── world_ticker.py      # Background zone simulation ticker
│   ├── types.py             # Enums (Direction, EntityKind, face constants)
│   ├── tiles/               # TOML-driven tile registry
│   │   ├── types.py         # TileDef dataclass, TileType, TF flags
│   │   ├── registry.py      # TILE_REGISTRY, compact-int mapping, LUT builders
│   │   ├── io.py            # TOML parsing
│   │   └── crud.py          # Register/update/delete tiles at runtime
│   └── zones/               # Zone data model & binary I/O
│       ├── zone.py          # Zone dataclass, Portal, OverlayWall
│       ├── io.py            # Binary .zone reader/writer (chunked format)
│       ├── compiler.py      # Zone → flat numpy arrays
│       ├── format.py        # Binary format constants
│       └── game_registry.py # Persistent str↔uint16 asset ID mapping
│
├── engine/                  # Rendering engine
│   ├── ray_renderer.py      # Python wrapper for C raycaster
│   ├── raycaster.py         # Pure-Python DDA raycaster (fallback)
│   ├── textures.py          # Texture atlas (PNG loading, 64×64 tiles)
│   ├── _ray_render.c        # C raycaster — full-frame renderer (~2300 LOC)
│   ├── _fast_cast.c         # C-accelerated DDA wall casting
│   └── _fast_walls.c        # C-accelerated wall segment rendering
│
├── editor/                  # Zone editor subsystem
│   ├── fly_camera.py        # Shared camera math (WASD, mouse look)
│   └── view_3d/             # 3D wireframe editor
│       ├── editor.py        # Zone3DEditor (mixin composition)
│       ├── rendering.py     # draw(), HUD, face highlights
│       ├── primitives.py    # _line3d, _box, _filled_box
│       ├── math3d.py        # 4×4 matrix math, projection, clipping
│       ├── picking.py       # Ray-AABB intersection
│       ├── geometry.py      # Cell box computation
│       ├── constants.py     # Colours, tool definitions, height limits
│       ├── tools_sculpt.py  # Floor/ceiling sculpting
│       ├── tools_paint.py   # Texture painting
│       ├── tools_fill.py    # Flood fill
│       ├── tools_erase.py   # Cell/texture erasing
│       ├── tools_select.py  # Rectangular selection
│       ├── tools_segment.py # Wall segment split/merge
│       ├── undo.py          # Snapshot undo/redo
│       ├── save.py          # Zone serialisation
│       └── cell_ops.py      # Cell-level operations
│
├── scenes/                  # Game scenes
│   ├── main_menu.py         # Title screen
│   ├── save_slots.py        # Save slot selection
│   ├── settings_menu.py     # Settings
│   ├── pause_menu.py        # In-game pause
│   ├── debug_menu.py        # Developer tools
│   ├── editor.py            # In-game tile editor
│   └── world/               # Gameplay viewports
│       ├── topdown.py       # Top-down tile view
│       ├── firstperson.py   # First-person raycaster view
│       ├── fp_renderer.py   # FP rendering pipeline
│       ├── fp_walls.py      # Wall rendering
│       ├── fp_surfaces.py   # Floor/ceiling surfaces
│       ├── fp_entities.py   # Entity billboard rendering
│       ├── fp_lighting.py   # Sector lighting & fog
│       ├── fp_hud.py        # First-person HUD
│       └── fp_interact.py   # FP interaction targeting
│
├── systems/                 # Game systems
│   ├── gameplay.py          # Interaction dispatch (TD + FP)
│   ├── interaction.py       # Entity interaction (range, facing)
│   ├── item_registry.py     # TOML item definitions
│   ├── items.py             # Ground item pickup/spawn
│   ├── loot.py              # Loot table rolling
│   ├── containers.py        # Container/inventory interaction
│   ├── combat_sim.py        # Off-screen coarse combat
│   ├── dialogue_gen.py      # Procedural NPC dialogue
│   ├── spawner.py           # Entity spawning
│   ├── beast_spawner.py     # Hostile creature spawning
│   ├── physics.py           # Movement & collision
│   ├── pathfinding.py       # A* pathfinding
│   ├── zone_sim.py          # Background zone simulation
│   └── lod.py               # Level-of-detail management
│
├── ui/                      # UI framework
│   ├── modal.py             # Modal stack base class
│   ├── commands.py          # Command pattern (CloseModal, HealPlayer, etc.)
│   ├── helpers.py           # UI drawing utilities
│   ├── inventory_modal.py   # Player inventory screen
│   ├── transfer_modal.py    # Container/trade screen
│   └── dialogue_modal.py    # NPC dialogue screen
│
├── components/              # ECS component definitions
├── data/                    # Game data (TOML)
│   ├── items.toml           # Item definitions
│   ├── loot_tables.toml     # Loot table definitions
│   ├── custom_tiles.toml    # User-defined tiles
│   └── custom_entities.toml # User-defined entities
│
├── assets/
│   ├── textures/
│   │   ├── tiles/           # 64×64 PNG tile textures (34 textures)
│   │   └── icon/            # Application icons
│   └── models/
│       └── tiles/           # Tile definition TOML files
│
├── zones/                   # Zone files (.zone binary format)
├── tests/                   # Test suite
├── tools/                   # Migration & demo utilities
└── docs/                    # Design documents & audits
```

---

## Architecture

### Rendering Engine

The renderer is a **Wolfenstein/Doom-style 2.5D raycaster** with modern extensions:

| Feature | Implementation |
|---------|---------------|
| Wall casting | DDA ray marching, one ray per screen column |
| Floor/ceiling | Row-sweep textured casting with per-cell heights |
| Height variation | Independent floor and ceiling heights per cell (Doom sectors) |
| Wall segments | Stacked textures per face — allows brick + window + trim combos |
| Step walls | Automatic side faces at height transitions between cells |
| Upper walls | Configurable wall extensions above the ceiling |
| Overlay walls | Free-form diagonal/partial walls not bound to the grid |
| Entity rendering | Textured billboards with per-pixel depth testing |
| Lighting | Per-cell spatial lighting + exponential distance fog |
| Sky | Gradient sky (exterior) or textured ceiling (interior) |
| Short/thin walls | Half-height counters, fence posts, mid-cell thin walls |

**Performance path:** The engine has three tiers:
1. **C extension** (`_ray_render.c`, ~2300 LOC) — full-frame rendering in native code, ~50× faster
2. **C DDA** (`_fast_cast.c`) — accelerated wall casting used by the pure-Python renderer
3. **Pure Python** (`raycaster.py`) — fallback requiring no compilation

Data flows from `Zone` → `RayRenderer._build_buffers()` (marshals all zone data into flat C-compatible byte arrays) → `_c_render_frame()` (C function writes RGB directly into a pre-allocated framebuffer) → `pygame.Surface`.

### Entity-Component-System

The ECS (`core/ecs.py`) is a typed, Rust-inspired implementation:

- **Entities** are integer IDs
- **Components** subclass `Component` and carry a `_persist` flag for save/load
- **Resources** are singleton objects stored separately from entities
- **Queries** support 1–3 component types with full type narrowing
- **Zone indexing** automatically tracks entity positions for spatial queries

```python
# Example: query all entities with Position and Health
for eid, (pos, hp) in world.query(Position, Health):
    if hp.current <= 0:
        world.despawn(eid)
```

### Zone Data Model

A `Zone` is a named tile grid with rich per-cell properties:

| Property | Type | Description |
|----------|------|-------------|
| `tiles` | `str[H][W]` | Tile IDs from the TOML registry |
| `floor_heights` | `float[H][W]` | Floor elevation per cell |
| `ceil_heights` | `float[H][W]` | Ceiling elevation (≥10 = open sky) |
| `floor_textures` | `str[H][W]` | Floor surface texture override |
| `ceil_textures` | `str[H][W]` | Ceiling surface texture override |
| `wall_textures` | `str[H][W]` | Wall texture override (all 4 faces) |
| `face_textures` | `str[H][W][4]` | Per-face wall texture (N/S/E/W) |
| `wall_segments` | `seg[H][W][4]` | Stacked texture bands per face |
| `light_levels` | `float[H][W]` | Spatial lighting (0.0–1.0) |
| `upper_wall_height` | `float[H][W]` | Wall extension above ceiling |
| `overlay_walls` | `list` | Free-form diagonal wall segments |

Zones are serialised to a **chunked binary format** (`.zone` files):
- **NAVI** — uint16 navigation bitmasks
- **ELEV** — float32 floor/ceiling height arrays
- **RNDR** — uint16 texture indices + float32 lighting
- **ENTY** — msgpack-encoded entities, portals, and metadata

### Game Systems

| System | Purpose |
|--------|---------|
| `gameplay` | Interaction dispatch for both top-down and first-person views |
| `interaction` | Range + facing check to find interactable entities |
| `item_registry` | TOML-driven item database with fast lookup |
| `loot` | Weighted random loot table rolling |
| `containers` | Container/inventory/trade modal opening |
| `combat_sim` | Off-screen coarse combat between entities in unloaded zones |
| `dialogue_gen` | Procedural NPC dialogue based on context (health, time, zone, events) |
| `spawner` | Entity spawning from zone entity descriptors |
| `beast_spawner` | Hostile creature spawning with zone population limits |
| `physics` | Tile-based movement and collision |
| `pathfinding` | A* grid pathfinding |
| `zone_sim` | Background simulation for off-screen zones |
| `lod` | Level-of-detail management for distant entities |

---

## Controls

### In-Game

| Key | Action |
|-----|--------|
| W/A/S/D or Arrow Keys | Move |
| E or Enter | Interact |
| I | Open inventory |
| Escape | Pause menu |
| Tab | Toggle top-down / first-person view |

### First-Person View

| Key | Action |
|-----|--------|
| Mouse | Look around |
| W/S/A/D | Walk |
| Shift | Sprint |
| E | Interact with aimed entity |

---

## Building C Extensions

The C extensions are optional but provide dramatically better rendering performance.

```bash
python build_ext.py build_ext --inplace
```

This compiles three extensions into the `engine/` directory:
- `_ray_render` — full-frame raycasting renderer
- `_fast_cast` — accelerated DDA wall casting
- `_fast_walls` — accelerated wall segment rendering

If compilation fails (no C compiler available), the engine falls back to the pure-Python renderer automatically.

---

## Tests

```bash
# Run the full test suite
python -m pytest tests/

# Run a specific test
python -m pytest tests/test_raycaster.py -v

# Run benchmarks
python tests/bench_render.py
```

---

## License

*To be determined.*
