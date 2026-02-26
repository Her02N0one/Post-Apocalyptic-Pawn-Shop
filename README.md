# Post-Apocalyptic Pawn Shop

A 2.5D post-apocalyptic survival RPG built with Python and pygame, featuring a Doom-style raycasting engine, a full 3D zone editor, and an entity-component-system architecture.

You play as a shopkeeper surviving in the wasteland — scavenging, trading, and managing your pawn shop while navigating a world filled with NPCs, beasts, and loot.

---

## Table of Contents

- [Features](#features)
- [Screenshots](#screenshots)
- [Requirements](#requirements)
- [Installation](#installation)
- [Zone Editor](#zone-editor)
- [Project Structure](#project-structure)
- [Architecture](#architecture)
  - [Rendering Engine](#rendering-engine)
  - [Entity-Component-System](#entity-component-system)
  - [Zone Data Model](#zone-data-model)
  - [Game Systems](#game-systems)
- [Controls](#controls)
- [Tests](#tests)
- [License](#license)

---

## Features

- **Dual-view gameplay** — seamless top-down and first-person raycaster perspectives
- **C-accelerated 2.5D renderer** — textured walls, floors, ceilings with per-cell heights, Doom-style sector lighting, fog, and entity billboards
- **3D zone editor** — fly-camera wireframe sculpting with ImGui panels, real-time raycaster preview (Tab to toggle)
- **7 editor tools** — Sculpt, Paint, Fill, Erase, Segment, Select, Stamp (Model) with undo/redo
- **Cell preset system** — TOML-driven presets with 4 apply modes (replace, stack floor, stack ceiling, merge) and in-editor capture-with-naming
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

| Requirement | Purpose | Required? |
|-------------|---------|-----------|
| **Python 3.11.9** | Runtime — this specific version is tested and required | Yes |
| **pip** | Package installer (bundled with Python) | Yes |
| **C compiler** | Compile the native rendering extensions (~50× faster) | Strongly recommended |
| **Git** | Clone the repository | Yes (or download ZIP) |

### Python Packages

All packages are listed in `requirements.txt` and installed automatically by pip:

| Package | Version | What it does |
|---------|---------|-------------|
| `pygame` | ≥ 2.0.0 | Windowing, input, 2D drawing, audio |
| `numpy` | any | Height-map arrays, fast zone data marshalling |
| `msgpack` | ≥ 1.0.0 | Binary serialisation for zone entity/portal data |
| `tomli` | ≥ 2.0.0 | TOML parsing for tile definitions, presets, items, loot tables |
| `PyOpenGL` | ≥ 3.1.0 | OpenGL bindings (used by the ImGui renderer in the zone editor) |
| `PyOpenGL_accelerate` | ≥ 3.1.0 | Native acceleration for PyOpenGL |
| `imgui[pygame]` | ≥ 2.0.0 | Immediate-mode GUI panels in the zone editor |

### C Compiler (for the native renderer)

The raycasting engine has three C source files that compile into Python extensions for dramatically faster rendering. **Without them the game still works** — it falls back to a pure-Python renderer — but frame rates will be much lower.

<details>
<summary><strong>Windows</strong></summary>

Install the **Microsoft C++ Build Tools** (free):

1. Go to https://visualstudio.microsoft.com/visual-cpp-build-tools/
2. Download and run the **Build Tools for Visual Studio** installer.
3. In the installer, select **"Desktop development with C++"**.
   - The only component you strictly need is **"MSVC v14x — C++ build tools"** and the **Windows SDK**. The installer will select these by default.
4. Click Install. (~2–6 GB download depending on components.)
5. After installation, open a **new** terminal so `cl.exe` is on your PATH.

You can verify the compiler is available:

```powershell
cl
# Should print "Microsoft (R) C/C++ Optimizing Compiler ..."
```

> **Tip:** If `cl` isn't found, open the "Developer Command Prompt for VS" or "x64 Native Tools Command Prompt" from the Start menu — these set up the correct PATH automatically. You can also run `python build_ext.py` from that prompt.

</details>

<details>
<summary><strong>Linux</strong></summary>

Most distributions ship GCC. If not:

```bash
# Debian / Ubuntu
sudo apt update && sudo apt install build-essential python3-dev

# Fedora
sudo dnf install gcc python3-devel

# Arch
sudo pacman -S gcc
```

Verify:
```bash
gcc --version
```

</details>

<details>
<summary><strong>macOS</strong></summary>

Install the Xcode command-line tools (includes `clang`):

```bash
xcode-select --install
```

Verify:
```bash
clang --version
```

</details>

---

## Installation

### Step 1 — Clone the repository

```bash
git clone https://github.com/your-username/Post-Apocalyptic-Pawn-Shop.git
cd Post-Apocalyptic-Pawn-Shop
```

### Step 2 — Create a virtual environment

A virtual environment keeps the project's packages isolated from your system Python.

**Windows (PowerShell):**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

> If you get an "execution policy" error, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` first, then try again.

**Windows (Command Prompt):**
```cmd
python -m venv .venv
.venv\Scripts\activate.bat
```

**Linux / macOS:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

You should see `(.venv)` at the start of your terminal prompt.

### Step 3 — Install Python dependencies

```bash
pip install -r requirements.txt
```

This installs pygame, numpy, msgpack, tomli, PyOpenGL, and imgui. Takes about a minute on a typical connection.

### Step 4 — Compile C extensions (optional but recommended)

```bash
python build_ext.py build_ext --inplace
```

This compiles three native extensions into the `engine/` directory:

| Extension | Source | What it accelerates |
|-----------|--------|-------------------|
| `_ray_render` | `engine/_ray_render.c` (~2300 LOC) | Full-frame raycasting: walls, floors, ceilings, sprites — the entire render pass |
| `_fast_cast` | `engine/_fast_cast.c` | DDA wall casting (used by the pure-Python renderer if `_ray_render` isn't available) |
| `_fast_walls` | `engine/_fast_walls.c` | Wall segment rendering (texture-banded walls) |

On **Windows** the output files are `.pyd`; on **Linux/macOS** they are `.so`.

**If compilation fails** (no C compiler, wrong SDK, etc.) the game will still run — the engine detects missing extensions at import time and falls back to `engine/raycaster.py` (pure Python). You'll see a message like:

```
[engine] C extension not available, using pure-Python renderer
```

**Common issues:**

| Problem | Fix |
|---------|-----|
| `cl` not found (Windows) | Open a "Developer Command Prompt for VS" or add MSVC to PATH |
| `gcc` not found (Linux) | `sudo apt install build-essential python3-dev` |
| `Python.h` not found | Install `python3-dev` (Linux) or confirm your venv uses the correct Python |
| Build succeeds but import fails | Make sure you ran with `--inplace` so the `.pyd`/`.so` lands in `engine/` |

### Step 5 — Run

```bash
# Launch the game
python main.py

# Launch the zone editor
python zone_editor.py

# Launch the zone editor with an existing zone
python zone_editor.py pawn_shop
```

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
| **Stamp (Model)** | Apply/capture cell presets with 4 apply modes (replace, stack, merge) |
| **Undo/Redo** | Snapshot-based history (Ctrl+Z / Ctrl+Y) |
| **Raycaster Preview** | Tab toggles between editor and first-person preview |

### Editor Controls

**3D Editor (mouse captured):**

| Key | Action |
|-----|--------|
| W/S/A/D | Fly camera |
| Mouse | Look around |
| 1–7 | Select tool (7 = Stamp/Model) |
| LMB | Primary tool action |
| RMB | Secondary tool action (Stamp: capture → name) |
| MMB | Paint / eyedropper |
| Scroll | Tool-specific (extend, cycle texture, adjust) |
| G | Cycle snap height (1/16, 1/8, 1/4, 1/2, 1) |
| M | Cycle stamp apply mode (replace/stack_floor/stack_ceil/merge) |
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
│   ├── presets.py           # Cell preset system (apply modes, capture, TOML I/O)
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
│       ├── tools_stamp.py   # Stamp (Model) preset apply/capture
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
│   ├── custom_entities.toml # User-defined entities
│   └── presets/             # Cell preset definitions (TOML)
│       ├── brick_wall.toml  # Full-height wall (floor_height=10)
│       ├── open_ground.toml # Flat ground
│       ├── stone_platform.toml  # Raised platform (stack_floor)
│       ├── wooden_counter.toml  # Half-height counter (stack_floor)
│       └── segmented_brick.toml # Segmented brick wall
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
| `floor_heights` | `float[H][W]` | Floor elevation per cell (10.0 = solid wall column) |
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

### Cell Preset System

Cell presets (`core/presets.py`) are reusable TOML recipes that describe the complete state of a cell — heights, textures, wall segments, and apply behaviour. They power the **Stamp (Model)** tool in the editor.

**Apply modes** control how a preset interacts with the existing cell:

| Mode | Behaviour |
|------|-----------|
| `replace` | Overwrite all non-None fields. Default. |
| `stack_floor` | Add the preset's height on top of the current floor; creates a step segment at the old floor level. Good for platforms and counters. |
| `stack_ceil` | Subtract from the ceiling downward; creates hanging geometry. |
| `merge` | Only apply fields that are still at their default values; existing customisation is preserved. |

**Wall cells** are expressed purely through height: when `floor_height >= ceil_height` the cell becomes a solid column. No separate boolean or type flag — the geometry itself determines wall-ness.

**Capture** requires intentional naming: RMB in the Stamp tool enters a HUD naming prompt. Type a name and press Enter to save the aimed cell as a new preset TOML under `data/presets/`.

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
