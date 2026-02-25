# Post-Apocalyptic Pawn Shop

**"Shopkeeper"** — A post-apocalyptic pawn shop management game built on a custom 2.5D raycasting engine in Python/C with Pygame.

---

## Table of Contents

- [Overview](#overview)
- [How the 2.5D Rendering Works](#how-the-25d-rendering-works)
  - [Architecture at a Glance](#architecture-at-a-glance)
  - [Phase 0 — Background Fill](#phase-0--background-fill)
  - [Phase 1 — Wall Raycasting (DDA)](#phase-1--wall-raycasting-dda)
  - [Phase 2A — Floor Step Walls](#phase-2a--floor-step-walls)
  - [Phase 2B — Floor Casting (Multi-Tier)](#phase-2b--floor-casting-multi-tier)
  - [Phase 3A — Ceiling Step Walls](#phase-3a--ceiling-step-walls)
  - [Phase 3B — Ceiling Casting (Multi-Tier)](#phase-3b--ceiling-casting-multi-tier)
  - [Phase 4 — Deferred Walls (Short + Thin)](#phase-4--deferred-walls-short--thin)
  - [Phase 5 — Entity Billboards](#phase-5--entity-billboards)
  - [Lighting and Fog System](#lighting-and-fog-system)
  - [Texture Pipeline](#texture-pipeline)
  - [Vertical Look (Y-Shearing)](#vertical-look-y-shearing)
- [Zone Data Model](#zone-data-model)
- [The Zone Editor](#the-zone-editor)
  - [3D Sculpting View](#3d-sculpting-view)
  - [Raycaster Preview](#raycaster-preview)
  - [Editor Tools](#editor-tools)
- [Rendering Capabilities](#rendering-capabilities)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
- [Future Plans](#future-plans)

---

## Overview

The engine renders first-person environments using a Wolfenstein/Doom-style raycasting approach, extended well beyond the classic formula with:

- **Per-cell floor and ceiling heights** (Doom-style sectors)
- **Multi-tier floor/ceiling casting** for overlapping elevation tiers
- **Short walls, thin walls, tall walls, and transparent walls**
- **Overlay walls** (free-form non-grid-aligned geometry)
- **Per-face directional textures** (different textures on N/S/E/W faces)
- **Stacked texture segments** (multiple textures per wall face at different heights)
- **Per-cell spatial lighting** (Doom-style sector lighting)
- **Distance fog with exponential falloff** and day/night cycle
- **Entity billboard rendering** with z-buffer clipping
- **A full 3D sculpting editor** with ImGui panels and real-time raycaster preview

The hot rendering path is written in C (`_ray_render.c`, 2270 lines) and compiled as a Python C extension, achieving real-time framerates at 640×360 internal resolution.

---

## How the 2.5D Rendering Works

### Architecture at a Glance

```
                     ┌──────────────────────────┐
                     │   Zone JSON (tile grid,   │
                     │  heights, textures, etc.)  │
                     └────────────┬───────────────┘
                                  │ load
                                  ▼
                     ┌──────────────────────────┐
                     │    RayRenderer (Python)   │
                     │  • Packs zone data into   │
                     │    flat C-compatible bufs  │
                     │  • Manages framebuffer    │
                     │  • Calls C render_frame() │
                     └────────────┬───────────────┘
                                  │
          ┌───────────────────────┼────────────────────────┐
          ▼                       ▼                        ▼
   _fast_cast.c            _ray_render.c            _fast_walls.c
   (DDA wall cast,         (Full-frame renderer:     (Wall geometry
    Python fallback)        walls, floors, ceilings,  pre-computation
                            entities, lighting)        for Python path)
          │                       │                        │
          ▼                       ▼                        ▼
   WallSlice tuples        RGB framebuffer (direct)  Geometry tuples
   (for Python renderer)   + per-pixel depth buffer  (for Python renderer)
```

There are **two rendering paths**:

1. **C Renderer** (`_ray_render.c`) — The primary path. Renders directly into a pre-allocated RGB framebuffer in a single C call. Used by `RayRenderer`.
2. **Python Renderer** (`raycaster.py` + `fp_walls.py` + `fp_surfaces.py`) — The original Python path with optional `_fast_cast.c` and `_fast_walls.c` acceleration. Used by the in-game first-person scene.

Both follow the same fundamental algorithm: DDA raycasting for walls, row-sweep for floors/ceilings.

### Phase 0 — Background Fill

Before any geometry is drawn, the framebuffer is filled:

- **Exterior zones**: A vertical gradient from deep blue (top) to light blue (bottom) simulates sky above the horizon line; dark brown-grey below for ground.
- **Interior zones**: A dark gradient simulates an enclosed ceiling above; same ground below.
- The **per-pixel depth buffer** is initialized to `MAX_DEPTH` (32 tiles).

### Phase 1 — Wall Raycasting (DDA)

For each screen column (640 columns at default resolution):

1. **Ray setup**: A ray is cast from the camera position through the corresponding column of the virtual screen plane. The camera plane width is derived from the FOV (default 60°).

2. **DDA stepping**: The Digital Differential Analyzer walks the ray through the tile grid cell-by-cell (up to 64 steps). At each cell boundary:

   - **Occlusion tracking**: Projects the traversed cell's ceiling and floor heights to screen-Y coordinates. Maintains running `clip_top` / `clip_bot` limits — if intervening cells have ceilings or floors that occlude parts of the column, later geometry is clipped.

   - **Step-wall collection**: When floor or ceiling height changes between adjacent cells, records a `StepWallHit` with perpendicular distance, texture U coordinate, and both cells' heights. These are rendered in Phase 2A/3A without redundant DDA re-traces.

   - **Non-solid cells**: Checks for thin walls (mid-cell intersection), transparent walls, and short walls — all recorded as deferred hits for Phase 4.

   - **Solid cells**: The DDA terminates. The wall column is rendered.

3. **Overlay wall testing**: After the DDA walk, each screen column tests against free-form wall segments (line segments not bound to the grid) using 2D ray-segment intersection.

4. **Wall column rendering**: The wall's screen extent is computed from the perpendicular distance and the cell's floor/ceiling heights. Two sub-paths:

   - **Segmented**: If the face has stacked texture segments (e.g., brick on the bottom half, plaster on top), each segment is rendered independently with proper V-mapping.
   - **Simple**: Standard single-texture column with optional `v_scale` stretching.

   **Tall walls** extend upward above the ceiling using a repeating alt-texture. **AO shadows** darken pixels near wall bases within 6 tiles.

### Phase 2A — Floor Step Walls

Uses `StepWallHit` data collected during Phase 1 (zero redundant DDA work). When adjacent cells have different floor heights, the vertical face between them is rendered as a textured wall column. Supports segmented textures. Per-pixel depth testing prevents overwriting closer geometry.

### Phase 2B — Floor Casting (Multi-Tier)

A row-sweep algorithm renders textured floors:

1. **Tier collection**: All unique floor heights below the camera are gathered and sorted highest-first (nearest drawn first for correct occlusion).

2. **Scanline sweep**: For each pixel row below the horizon:
   - Each pixel tests against floor tiers from nearest to farthest.
   - The ray is projected onto the floor plane at the tier's height.
   - The world-space intersection point determines the tile cell and texture UV.
   - The floor texture is sampled and shaded with:
     - **Checkerboard tint** (alternating tiles dimmed to ~82% for visual grid separation)
     - **Height brightness boost** (elevated floors appear slightly brighter)
     - **Per-cell spatial lighting**
     - **Distance fog**

### Phase 3A — Ceiling Step Walls

Mirror of Phase 2A for ceiling-height transitions between adjacent cells. Also handles `upper_wall_height` extensions — wall-like surfaces above the normal ceiling height.

### Phase 3B — Ceiling Casting (Multi-Tier)

Mirror of Phase 2B, only active for **interior zones**. Sweeps from the horizon upward. Cells with ceiling height ≥ 10.0 are treated as **open sky** — the Phase 0 background shows through. Overhead floors (viewing an elevated floor from below) are rendered with extra dimming (59% vs ceiling's 70%).

### Phase 4 — Deferred Walls (Short + Thin)

All deferred hits from Phase 1 are sorted far-to-near and rendered:

- **Short walls** (e.g., counters, railings): Rendered at reduced height anchored to floor level. If the camera is above a short wall, a **counter-top surface** is drawn (horizontal floor-cast technique constrained to the tile bounds).
- **Thin walls**: Mid-cell intersections (fences, window frames).
- **Transparent walls**: Pixels at magenta `(255, 0, 255)` are skipped for see-through fences and bars.
- All per-pixel depth-tested against previously rendered geometry.

### Phase 5 — Entity Billboards

A separate C function (`render_entities`) renders entities as camera-facing billboards:

- Entities are sorted far-to-near.
- **Textured billboards**: Sampled from the tile atlas with fog tinting and entity color modulation. Near-black pixels are transparent.
- **Untextured billboards**: Colored rectangles with head/body shading and edge darkening.
- Per-pixel z-buffer clipping against the world depth buffer.

### Lighting and Fog System

Three independent lighting layers combine multiplicatively:

| Layer | Source | Effect |
|-------|--------|--------|
| **Distance fog** | 256-entry LUT, exponential decay | Brightness drops off with `exp(-dist/16 × 1.8)`, clamped to a minimum of 20/255 |
| **Directional shading** | Wall face orientation | EW faces receive a warm shadow tint `(175, 168, 155)/256` — gives depth perception |
| **Spatial lighting** | Per-cell `light_levels` grid (0.0–1.0) | Doom-style sector lighting — dim rooms, bright exteriors |
| **Day/night cycle** | `dn` factor (0.0 night – 1.0 day) | Modulates fog ambient: `ambient = 200 + 55 × dn`, brightness = `fog × (0.4 + 0.6 × dn)` |

### Texture Pipeline

All textures are **64×64 pixel PNG files** stored in `assets/textures/tiles/`. Currently 34 textures.

At renderer init, `RayRenderer._build_atlas()` packs all tile textures into a single flat RGB buffer (`num_tiles × 64 × 64 × 3 bytes`), which the C code indexes by tile ID for zero-overhead sampling.

Texture features per tile (via `TileDef`):
- `texture_key` — primary texture
- `tex_n`, `tex_s`, `tex_e`, `tex_w` — per-compass-face overrides
- `texture_front` / `texture_back` — rotational overrides
- `alt_texture` — tall wall extension repeat texture
- `v_scale` — vertical texture scale (0.5 = texture covers 2 world-units)
- `height_scale` — wall height multiplier (< 1.0 = counter/railing)

### Vertical Look (Y-Shearing)

The renderer implements vertical mouselook via **horizon-line shifting** — the classic 2.5D approach:

```
horizon_shift = tan(pitch) × screen_height
```

This shifts the horizon line up or down, causing walls to appear taller/shorter and floors/ceilings to slide. Combined with per-cell height variation, this gives a convincing sense of 3D without true perspective projection.

---

## Zone Data Model

Zones are JSON files in `zones/` loaded into a `Zone` dataclass. Each zone is a 2D grid of cells with rich per-cell data:

| Field | Type | Description |
|-------|------|-------------|
| `tiles` | `str[][]` | Tile ID grid (e.g. `"grass"`, `"brick_wall"`) |
| `rotations` | `int[][]` | Per-cell rotation (0–3, 90° increments) |
| `floor_heights` | `float[][]` | Per-cell floor height (0.0 = ground level) |
| `ceil_heights` | `float[][]` | Per-cell ceiling height (10.0 = open sky) |
| `floor_textures` | `str[][]` | Per-cell floor texture override |
| `ceil_textures` | `str[][]` | Per-cell ceiling texture override |
| `wall_textures` | `str[][]` | Per-cell wall texture (all 4 faces) |
| `face_textures` | `str[][][4]` | Per-cell per-face texture [N, S, E, W] |
| `light_levels` | `float[][]` | Per-cell spatial lighting (0.0–1.0) |
| `wall_segments` | `seg[][][4]` | Per-face stacked texture segments |
| `floor_step_textures` | `str[][][4]` | Textures for floor-height transition faces |
| `ceil_step_textures` | `str[][][4]` | Textures for ceiling-height transition faces |
| `floor_step_segments` | `seg[][][4]` | Stacked segments on floor step walls |
| `ceil_step_segments` | `seg[][][4]` | Stacked segments on ceiling step walls |
| `upper_wall_height` | `float[][]` | Override wall height above ceiling |
| `overlay_walls` | `OverlayWall[]` | Free-form wall segments (fences, diagonals) |
| `portals` | `Portal[]` | Zone-to-zone transition links |
| `entities` | `dict[]` | Spawned entity descriptors |

A cell can simultaneously be:
- A solid wall (floor at or above ceiling, or wall-type tile)
- A walkable floor with custom elevation
- An interior ceiling at any height (or open sky)
- Textured differently on each of its 4 cardinal faces
- Split into multiple vertical texture bands per face

This gives Doom-like sector geometry within a Wolfenstein-style grid.

---

## The Zone Editor

The standalone zone editor (`zone_editor.py`, 1466 lines) provides a full 3D editing environment with real-time preview.

### 3D Sculpting View

A software-rendered 3D wireframe/solid view using Pygame's polygon drawing, composited through OpenGL:

- **Fly camera** (WASD + mouse) with sprint/slow modifiers
- **Face-shaded filled boxes** with per-face brightness multipliers and back-face culling
- **Ray-AABB picking** for precise cell/face targeting
- **Depth-sorted rendering** (painter's algorithm, back-to-front)
- **Visual overlays**: Grid, ceiling grid, axis indicators, segment boundary markers, selection highlights, tool previews

### Raycaster Preview

Press **Tab** to switch to the actual C raycaster rendering the zone in real time at full resolution — see exactly what the player will see while editing.

### Editor Tools

| # | Tool | Description |
|---|------|-------------|
| 1 | **Sculpt** | Raise/lower floor and ceiling heights. LMB raises, RMB lowers. Configurable snap grid (0.0625–1.0). Supports ceiling sculpting (dig down / fill up). |
| 2 | **Paint** | Apply textures to wall faces, floors, ceilings. Hold for continuous drag-paint. Eyedropper (MMB). Scrollable texture palette. |
| 3 | **Fill** | Flood-fill connected surfaces with a texture. Stops at height changes and segment boundaries. |
| 4 | **Erase** | Reset cells to default state (flat ground, open sky). Can reset height only or textures only. |
| 5 | **Detail** | Split wall faces into vertical texture segments. Merge segments. Paint individual segments. |
| 6 | **Select** | Rectangular area selection. Batch fill, clear, or reset operations on the selection. |

All tools support **undo/redo** (Ctrl+Z / Ctrl+Y) via snapshot-based history.

The ImGui UI provides:
- **Tool panel** with texture picker and context-sensitive hints
- **Zone browser** to load any zone from `zones/`
- **Properties panel** showing cell coordinates, heights, textures, segments, and face overrides
- **Status bar** with zone name, dimensions, mode, active tool, and camera position
- **New Zone / Save As dialogs** with validation

---

## Rendering Capabilities

### What the Engine Can Do Today

- **Variable-height floors and ceilings** — stairs, pits, elevated platforms, sunken rooms
- **Interior and exterior zones** — ceilings or open sky per-cell
- **34 hand-painted 64×64 textures** — walls, floors, terrain, furniture
- **Per-face texturing** — 4 independent compass-face textures per cell
- **Stacked texture segments** — multiple textures per wall face at different heights (wainscoting, trim, brick-to-plaster transitions)
- **Short walls** — counters, railings, half-walls (< 1.0 height scale) with see-through and counter-top surfaces
- **Thin walls** — mid-cell geometry for fences and window frames
- **Tall walls** — extend above ceiling with repeating alt-texture
- **Transparent walls** — magenta-keyed see-through fences and bars
- **Overlay walls** — free-form line-segment walls not bound to the grid (diagonal walls, partitions)
- **Per-cell spatial lighting** — Doom-style sector brightness
- **Day/night fog cycle** — exponential distance fog with ambient modulation
- **Directional wall shading** — EW faces darker than NS for depth perception
- **Checkerboard floor tint** — subtle grid visualization on floors
- **AO shadows** — darkened pixels at wall bases
- **Entity billboards** — textured or flat-colored sprites with z-buffer clipping
- **Height-aware collision** — step-up/step-down limits, head clearance checks
- **Portal system** — zone-to-zone transitions with 4-state fade
- **Full 3D zone editor** with real-time raycaster preview

### Performance

The C renderer (`_ray_render.c`) renders directly into a pre-allocated framebuffer with zero Python object allocation in the hot loop. At 640×360:

- **DDA wall casting**: Up to 64 steps per ray, 640 rays per frame
- **Floor/ceiling casting**: Multi-tier row-sweep with per-pixel depth testing
- **Entity billboards**: Sorted far-to-near with atlas texture sampling
- **Fog/lighting**: Per-pixel multiplication using pre-computed 256-entry LUT

The C extension is compiled with `-O2 -ffast-math` for maximum throughput.

---

## Project Structure

```
├── main.py                  # Entry point — launches App with MainMenu
├── zone_editor.py           # Standalone 3D zone editor (ImGui + OpenGL)
├── build_ext.py             # Builds C extensions
│
├── core/
│   ├── app.py               # App class — scene stack, game loop
│   ├── ecs.py               # Entity-Component-System (World, EventBus)
│   ├── zones.py             # Zone dataclass, JSON load/save
│   ├── tiles/               # Tile registry, TileDef, TOML bootstrap
│   ├── session.py           # Game session (zone transitions, save/load)
│   └── ...
│
├── systems/
│   ├── _ray_render.c        # Full-frame C raycaster (2270 lines)
│   ├── _fast_cast.c         # C-accelerated DDA wall casting (331 lines)
│   ├── _fast_walls.c        # C wall geometry pre-computation (242 lines)
│   ├── ray_renderer.py      # Python wrapper for _ray_render.c (853 lines)
│   ├── raycaster.py         # Pure-Python DDA raycaster (573 lines)
│   ├── textures.py          # TextureAtlas — PNG loading, 64×64 tiles
│   └── ...
│
├── editor/
│   └── view_3d/             # 3D editor modules (mixins)
│       ├── editor.py         # Zone3DEditor assembler class
│       ├── rendering.py      # Draw loop, HUD, face highlighting
│       ├── primitives.py     # _line3d, _box, _filled_box
│       ├── tools_sculpt.py   # Floor/ceiling height editing
│       ├── tools_paint.py    # Texture painting
│       ├── tools_fill.py     # Flood-fill
│       ├── tools_segment.py  # Stacked texture segments
│       └── ...
│
├── scenes/
│   └── world/
│       ├── firstperson.py    # In-game first-person scene
│       ├── fp_walls.py       # Wall rendering (Python path)
│       ├── fp_surfaces.py    # Floor/ceiling rendering
│       ├── fp_entities.py    # Billboard entities
│       ├── fp_lighting.py    # Day/night, fog LUT
│       └── topdown.py        # Top-down view scene
│
├── zones/                    # Zone JSON files (13 zones)
├── assets/textures/tiles/    # 64×64 PNG textures (34 textures)
├── data/                     # TOML data files (items, loot, recipes)
└── tests/                    # Unit and benchmark tests
```

---

## Getting Started

### Requirements

- Python 3.10+
- GCC (for building C extensions)
- System dependencies: SDL2 (for Pygame)

### Setup

```bash
# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate

# Install Python dependencies
pip install pygame numpy PyOpenGL "imgui[glfw]" tomli msgpack nbtlib

# Build C extensions (required for the raycaster)
python build_ext.py build_ext --inplace

# Run the game
python main.py

# Run the zone editor
python zone_editor.py
```

### Editor Controls

| Input | Action |
|-------|--------|
| **W/A/S/D** | Fly camera |
| **Mouse** | Look (when captured) |
| **Click viewport** | Capture mouse |
| **Escape** | Release mouse |
| **Tab** | Toggle 3D Editor / Raycaster Preview |
| **1-6** | Select tool |
| **LMB/RMB** | Primary/secondary tool action |
| **MMB** | Eyedropper (Paint tool) |
| **Scroll** | Tool-specific (height adjust, palette cycle) |
| **Ctrl+S** | Save zone |
| **Ctrl+Z/Y** | Undo / Redo |

---

## Future Plans

### Rendering Enhancements
- **Dynamic point lights** — Torch flicker, lantern glow, muzzle flash with light falloff computed per-pixel during floor/ceiling casting
- **Light propagation** — BFS/flood-based light spread from source tiles into neighbouring cells, replacing static `light_levels` grids
- **Animated textures** — Frame-cycling for water, fire, blinking lights (atlas sub-frame indexing)
- **Skybox rendering** — Replace flat sky gradient with a wraparound panoramic texture mapped to the camera angle
- **Sprite rotation** — 8-way Doom-style billboard octants (data structures already defined in `BillboardSprite.octant`)
- **Parallax floor/ceiling** — Offsetting texture samples by height delta for a subtle depth illusion on flat surfaces
- **Multi-layer transparency** — Order-independent rendering of stacked transparent walls (currently limited to 4 per ray)
- **Shadow mapping** — Projecting wall shadows onto floors using pre-computed shadow volumes per light source

### Editor Improvements
- **Lighting editor** — Per-cell light level painting with real-time preview in the raycaster view
- **Overlay wall editor** — Visual placement of free-form wall segments (diagonal walls, fences)
- **Entity placement** — Drag-and-drop entity spawning with prefab selection
- **Copy/paste regions** — Clipboard operations for selected areas across zones
- **Multi-zone portal editor** — Visual portal link creation between loaded zones
- **Heightmap import** — Load elevation data from images for terrain generation

### Gameplay Systems
- **Combat system** — Real-time first-person melee/ranged combat with the existing weapon definitions
- **NPC AI and dialogue** — Driven by the existing dialogue generation system and entity interaction framework
- **Inventory and trade** — The pawn shop transaction loop using the item registry and loot tables
- **Day/night cycle** — Dynamic `dn` factor affecting fog, lighting, NPC behaviour, and beast spawning
- **Procedural zone generation** — Runtime generation of wasteland zones using the structure templates in `data/structures/`
- **Save system completion** — Full game state serialization beyond the current zone-level saves

### Engine
- **GPU-accelerated renderer** — Port the C raycaster to an OpenGL fragment shader for massively parallel per-pixel computation
- **Texture resolution scaling** — Support 128×128 or 256×256 textures for close-up detail
- **Audio system** — Positional audio using per-tile sound categories already defined in TileDef
- **Modding support** — Hot-reload of TOML data files and texture PNGs, custom tile registration via `data/custom_tiles.toml`
