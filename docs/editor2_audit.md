# Editor2 — Architecture Audit

> Qt + OpenGL zone editor rewrite.
> Audited: March 19, 2026 • **1,754 lines** across **14 Python source files**

---

## Stack

| Layer | Technology |
|-------|------------|
| Language | Python 3.11.9 |
| GUI | PySide6-Essentials 6.10.2 (`QMainWindow`, `QOpenGLWidget`, dock panels) |
| Rendering | OpenGL 3.3 Core Profile via PyOpenGL |
| Textures | Pillow (PNG load → `GL_TEXTURE_2D_ARRAY`) |
| Math | NumPy (`float32` vertex buffers, 4×4 matrices) |
| GPU | NVIDIA GeForce RTX 3060 |

---

## File Inventory

| File | Lines | Purpose |
|------|------:|---------|
| `__init__.py` | 3 | Package marker, NullHandler for logging |
| `camera.py` | 61 | FPS camera — projection/view matrices, WASD vectors |
| `atlas.py` | 140 | `GL_TEXTURE_2D_ARRAY` tile atlas (128×128, NEAREST) |
| `mesh.py` | 222 | Zone → vertex buffer builder (`pos3 bright3 uv2 layer1`) |
| `picking.py` | 208 | Screen-to-world ray casting, cell/face hit detection |
| `core.py` | 157 | Command bus — `SetCellFieldCmd`, `SetFaceFieldCmd`, `BatchCmd`, undo/redo |
| `tools/__init__.py` | 47 | `Tool` protocol, `Overlay`/`OverlayMode`, `quad_to_tris` helper |
| `tools/paint.py` | 199 | Face texture paint tool (drag, shift-all-faces, eyedropper) |
| `tools/sculpt.py` | 169 | Floor/ceiling height sculpt tool (raise/lower, drag) |
| `tools/tile_type.py` | 117 | Tile type assignment tool (drag, eyedropper) |
| `panels/inspector.py` | 58 | Paint tool dock panel (texture palette, hover info) |
| `panels/sculpt_inspector.py` | 69 | Sculpt tool dock panel (step size, hover info, heights) |
| `panels/tile_inspector.py` | 93 | Tile type dock panel (category tree, hover info) |
| `viewport.py` | 489 | `QOpenGLWidget` — shaders, input, overlays, crosshair, FPS camera |
| `main.py` | 421 | `EditorWindow` — menus, tool switching, zone lifecycle, entry point |
| **Total** | **2,244** | *(includes `panels/__init__.py` — 1 line, and `__pycache__/`)* |
| **Source only** | **1,754** | *(excluding `__pycache__/` and empty `__init__` files)* |

---

## Architecture

```
EditorWindow (QMainWindow)
├── ZoneViewport (QOpenGLWidget)  — central widget
│   ├── Camera                    — FPS camera (WASD + mouse)
│   ├── TileAtlas                 — GL texture array
│   ├── Scene shader              — textured geometry
│   ├── Overlay shader            — flat-colour tool overlays
│   ├── Crosshair                 — NDC triangle-quads (FPS mode)
│   └── Tool (protocol)          — active tool receives input
├── Inspector Dock (QDockWidget)  — swappable panel per tool
│   ├── PaintInspector            — texture palette + hover info
│   ├── SculptInspector           — step size + height readout
│   └── TileTypeInspector         — tile palette by category
├── CommandBus                    — executes/undoes zone mutations
│   ├── SetCellFieldCmd           — zone.field[r][c] = value
│   ├── SetFaceFieldCmd           — zone.field[r][c][face] = value
│   └── BatchCmd                  — groups commands for undo
├── File Menu                     — New / Open / Recent / Save / Save As / Quit
├── Tools Menu                    — Paint (1) / Sculpt (2) / Tile Type (3)
└── Debug Menu                    — Perf overlay (F3) / Log Level / Dump Stats (F4)
```

---

## Rendering Pipeline

### Vertex Format (9 floats = 36 bytes per vertex)

| Attribute | Location | Components | Purpose |
|-----------|----------|------------|---------|
| `a_pos` | 0 | `vec3` | World-space position |
| `a_color` | 1 | `vec3` | Face brightness (directional lighting) |
| `a_uv` | 2 | `vec2` | Texture coordinates |
| `a_texLayer` | 3 | `float` | Index into `GL_TEXTURE_2D_ARRAY` |

### Shaders

- **Scene shader** — samples `sampler2DArray` with per-face brightness
- **Overlay shader** — flat `u_color` (RGBA), supports `GL_TRIANGLES`, `GL_LINES`, `GL_LINE_STRIP`
- **Crosshair** — 2 triangle-quads in NDC space, identity VP, depth test disabled, cull face disabled

### Mesh Rebuild

- Full zone mesh is rebuilt on every `zone_changed` signal
- Coalesced via dirty flag: `mark_mesh_dirty()` → single `rebuild_mesh()` at start of `paintGL`
- Context-aware: skips `makeCurrent()`/`doneCurrent()` when already inside `paintGL`

### Texture Atlas

- `GL_TEXTURE_2D_ARRAY`, 128×128 per layer, `GL_NEAREST` filtering
- Layer 0 = magenta/black checkerboard (missing texture)
- Layers 1–N = sorted tile registry keys + extra on-disk PNGs
- `atlas.tile_keys` — registry-only subset (excludes entity textures like vending faces)
- `atlas.keys` — all keys including extras

---

## Coordinate System

| Axis | Meaning | Convention |
|------|---------|------------|
| X | East | `col` index, camera `right()` |
| Y | Up | Height (floor/ceil) |
| Z | South | `row` index, camera `forward()` at yaw=0 |

- Grid cells occupy `[col, col+1] × [row, row+1]` in XZ
- `yaw = 0` faces +Z (south), increases CW
- `pitch > 0` looks up
- Front face winding: `GL_CW`

---

## Camera

| Parameter | Value |
|-----------|-------|
| FOV | 75° vertical |
| Near clip | 0.05 |
| Far clip | 80.0 |
| Move speed | 4.0 units/sec |
| Sprint multiplier | 2.5× (Shift) |
| Mouse sensitivity | 0.003 rad/px |

### Controls

| Input | Action |
|-------|--------|
| WASD | Move (forward/back/strafe) |
| Shift | Sprint |
| Space / Ctrl | Fly up / down |
| Right-click | Capture mouse → FPS mode |
| Escape | Release mouse / Close window |
| Enter | Capture mouse |
| Mouse move (captured) | Look around |

---

## Picking System

- `screen_to_ray(sx, sy, vp_w, vp_h, camera)` — unprojects screen pixel to world ray
- `pick_cell(...)` — scans ±16 cells around camera, tests ray vs each cell's AABBs
- Returns `CellHit(t, col, row, part, face, hit_y)` — closest hit
- Ground plane test at Y=0 as fallback

### Face Enum

| Face | Value | `face_tex_idx` |
|------|-------|----------------|
| NORTH | 0 | 0 |
| SOUTH | 1 | 1 |
| EAST | 2 | 2 |
| WEST | 3 | 3 |
| TOP | 4 | None |
| BOT | 5 | None |
| GROUND | 6 | None |

---

## Command System

All zone mutations go through `CommandBus` for undo/redo support.

### Commands

| Command | Fields | Description |
|---------|--------|-------------|
| `SetCellFieldCmd` | `row, col, field, new_value` | Sets `zone.<field>[r][c]` |
| `SetFaceFieldCmd` | `row, col, face_idx, field, new_value` | Sets `zone.<field>[r][c][i]` |
| `BatchCmd` | `commands[], desc` | Groups commands into one undo step |

### Batch Support

- `begin_batch(desc, defer_signal=False)` — starts accumulating
- `commit_batch()` — pushes as single undo entry, emits `zone_changed` if deferred
- `cancel_batch()` — undoes all accumulated, emits `zone_changed`
- `defer_signal=True` — suppresses per-command `zone_changed` emission (used by shift-paint to avoid N mesh rebuilds)

---

## Tools

### Tool Protocol

```python
class Tool(Protocol):
    name: str
    on_changed: Callable[[], None] | None
    def on_mouse_move(sx, sy, vp_w, vp_h) -> None
    def on_mouse_press(sx, sy, vp_w, vp_h, button) -> None
    def on_mouse_release(sx, sy, vp_w, vp_h, button) -> None
    def overlays() -> list[Overlay]
```

### Button Mapping

| Qt Button | Tool `button` value |
|-----------|---------------------|
| Left | 1 |
| Right | (captures mouse — not forwarded) |
| Middle | 3 |
| Other | 2 |

### Paint Tool (key: 1)

| Action | Effect |
|--------|--------|
| Left-click | Paint `current_texture` on hit face |
| Left-drag | Drag-paint (batched undo, same-cell skip) |
| Shift+click | Paint all 6 faces of the block |
| Shift+drag | Drag-paint all faces (deferred signal, same-cell skip) |
| Middle-click | Eyedropper — pick texture from hit face |

**Texture Resolution** (for eyedropper sampling):
- `_get_face_tex_keys(zone, r, c, part)` → `[top, bot, N, S, W, E]`
- Walls: `face_textures` → `wall_textures` → `tiles`
- Floors: `floor_textures` → `tiles`
- Ceilings: `ceil_textures` → `"concrete"`

**Overlays**: Cyan highlight on hover face (all 6 faces when Shift held)

### Sculpt Tool (key: 2)

| Action | Effect |
|--------|--------|
| Left-click | Raise height by step |
| Shift+click | Lower height by step |
| Left-drag | Raise across cells (batched, same-cell skip) |
| Shift+drag | Lower across cells |

**Field Selection** (automatic based on hit):
- Floor top/ground/sides → `floor_heights`
- Ceiling top/bottom/sides → `ceil_heights`
- Wall top → `ceil_heights`, wall bottom → `floor_heights`

**Settings**: Step size 0.05–5.0 (default 0.25), heights clamped to [-10, 20]

**Overlays**: Green = raise, Red = lower (follows Shift state)

### Tile Type Tool (key: 3)

| Action | Effect |
|--------|--------|
| Left-click | Set `zone.tiles[r][c]` to selected tile ID |
| Left-drag | Drag-paint tile type (batched, same-cell skip) |
| Middle-click | Eyedropper — pick tile ID from hit cell |

**Palette**: `QTreeWidget` grouped by category (Terrain, Floors, Walls, etc.) via `tiles_by_category()`

**Overlays**: Orange highlight on top face of hovered cell

---

## Inspector Panels

### PaintInspector
- Current texture label
- Hover info: `(row, col) part.FACE`
- Texture palette: `QListWidget` filtered to `atlas.tile_keys` (registry only)
- Click palette entry → sets `tool.current_texture`

### SculptInspector
- Hover info: `(row, col) part.FACE`
- Target field name (e.g. `floor_heights`)
- Current height value at hover cell
- Step size `QDoubleSpinBox` (0.05–5.0)
- Usage hints

### TileTypeInspector
- Selected tile ID label
- Hover info: `(row, col) part.FACE`
- Current cell tile info (name + ID)
- Tile palette: `QTreeWidget` grouped by category (`tiles_by_category()`)
- Click palette entry → sets `tool.current_tile`
- Usage hints

---

## Zone Lifecycle (File Menu)

| Action | Shortcut | Description |
|--------|----------|-------------|
| New Zone | Ctrl+N | Dialog for width × height (4–128), creates empty zone |
| Open Zone | Ctrl+O | Lists `.zone` files, loads selected |
| Recent Zones | — | Submenu of last 12 opened zones |
| Save | Ctrl+S | Saves to `zones/<name>.zone` |
| Save As | Ctrl+Shift+S | Prompts for name |
| Quit | Ctrl+Q | Guards unsaved changes |

### Zone Switching (`_attach_zone`)

1. Creates new `CommandBus` for the zone
2. Resets viewport zone, camera position, rebuilds mesh
3. Creates fresh `PaintTool` + `SculptTool` + `TileTypeTool` for the new zone
4. Re-activates the current tool (preserves tool selection across zones)
5. Updates inspector panel

### Session Persistence

- Shared `editor_session.json` with old editor (via `editor.app.session_cfg`)
- Stores `last_zone` and `recent_zones` (MRU, max 12)
- Loaded on startup, saved on zone switch and close

---

## Debug / Profiling

| Feature | Shortcut | Description |
|---------|----------|-------------|
| Perf overlay | F3 | Status bar: FPS, frame time, rebuild time, tri count |
| Dump stats | F4 | Dialog: zone size, tri count, FPS, undo/redo depth, camera pos |
| Log level | Menu | Switch editor2 logger between DEBUG / INFO / WARNING |

### Perf Tracking

- Frame times: 120-sample rolling `deque`, measured per `paintGL`
- Rebuild timing: measured per `rebuild_mesh()`, logged at DEBUG
- Perf label updates at 500ms interval (only when enabled)

---

## Known Limitations / TODO

### Not Yet Implemented
- **Upper wall height** — `upper_wall_height` editing
- **Secondary layers** — `floor2_heights`, `ceil2_heights`, `upper_wall_height2`
- **Floor/ceiling slopes** — `floor_slope_dx`, `floor_slope_dy`
- **Entity placement** — placing/moving entities in the zone
- **Wall segments** — per-face wall segment editing
- **Grid overlay** — world-space grid lines for spatial reference
- **Wireframe mode** — toggle wireframe rendering
- **Selection tool** — select cells for batch operations
- **Copy/paste** — cell range clipboard
- **Undo history panel** — visual undo/redo stack
- **Multi-zone view** — minimap or zone list with preview

### Performance
- Full mesh rebuild on every zone change (Python-side vertex gen)
- Could benefit from incremental mesh updates (per-cell VBO patching)
- `build_zone_mesh` uses Python lists → could move to NumPy or C extension
- Picking scans ±16 cells — fine for 20×20, may need spatial index for large zones

### Rendering
- No MSAA in current format setup (configured but not verified)
- No skybox or ambient lighting
- No entity rendering (entities exist in zone data but aren't drawn)
- Texture tiles are 128×128 — no mipmap generation

---

## Coexistence with Old Editor

`editor2/` is a standalone package alongside the original `editor/`. Both coexist cleanly:

| Aspect | Detail |
|--------|--------|
| Directory | `editor2/` lives next to `editor/`, no shared modules |
| Zone files | Both read/write `zones/*.zone` via `core.zones.load_zone` / `save_zone` |
| Session | Shared `editor_session.json` via `editor.app.session_cfg` (recent zones, last zone) |
| Tile registry | Both use `core.tiles.registry` — same tile definitions |
| Entry point | Old: `python -m editor.main` / New: `python -m editor2.main [zone]` |
| Safe to run both | Yes — no file locking, but avoid editing the same zone simultaneously |

The old editor remains the production path for features not yet ported (entities, wall segments, slopes, secondary layers). Use it freely alongside `editor2` without risk of breaking either.
