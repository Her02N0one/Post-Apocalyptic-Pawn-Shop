# Zone Editor — Current Visual State (2026-03-02)

Exact description of every visual element the user sees, organized by screen region.

---

## Overall Layout

**Window:** 1600×900 pixels, title "Zone Editor".

The window is divided into five regions stacked/tiled:

```
┌─────────────────────────────────────────────────────────────────────┐
│  MENU BAR  (22px tall, full width)                            FPS  │
├──────────┬──────────────────────────────────────────┬───────────────┤
│          │                                          │               │
│  LEFT    │           3D VIEWPORT                    │   RIGHT       │
│  PANEL   │        (fills remaining space)           │   PANEL       │
│  280px   │                                          │   250px       │
│          │   [HUD top-left]    [crosshair center]   │               │
│          │                                          │               │
│          │   [action hints below crosshair]         │               │
│          │                                          │               │
│          │              [hotbar at bottom]           │               │
├──────────┴──────────────────────────────────────────┴───────────────┤
│  STATUS BAR  (28px tall, full width)                                │
└─────────────────────────────────────────────────────────────────────┘
```

Both side panels are resizable via drag splitters (8px invisible grip zones at their inner edges). Minimum panel width is 200px, maximum is `win_w / 2 - 50`.

When no zone is loaded, both panels show grey "No zone loaded" text. When the mouse is not captured (user hasn't clicked into the viewport), a centred overlay reads "Click viewport or Enter to edit | Esc = quit".

---

## Menu Bar

Standard ImGui main menu bar with three menus and a right-aligned FPS counter.

### File Menu
| Item | Shortcut | Action |
|------|----------|--------|
| New Zone... | | Opens new zone dialog |
| Save | Ctrl+S | Saves current zone |
| Save As... | | Opens save-as dialog |
| Quit | Escape | Quits application |

### Edit Menu
| Item | Shortcut | Action |
|------|----------|--------|
| Undo | Ctrl+Z | Undo last edit |
| Redo | Ctrl+Y | Redo last undo |

### View Menu
| Item | Shortcut | State |
|------|----------|-------|
| 3D Editor | Tab | Radio-style toggle (checked when active) |
| Raycaster Preview | Tab | Radio-style toggle |
| *(separator)* | | |
| Show Axes | F10 | Checkbox |
| Show Walls | V | Checkbox |
| Show Floors | F | Checkbox |
| Show Ceilings | J | Checkbox |
| Show Entities | N | Checkbox |
| *(separator)* | | |
| Wireframe | \\ | Checkbox |

### FPS Counter (right-aligned)
Displays `{fps} FPS  {ms}ms`, colour-coded:
- Green (`0.4, 0.9, 0.4`) if < 10ms
- Yellow (`0.9, 0.9, 0.3`) if 10–20ms
- Red (`0.9, 0.3, 0.3`) if > 20ms

---

## Left Panel ("Toolbox")

A fixed ImGui window at `(0, 22)` sized to `(left_panel_w, win_h - 22 - 28)`. Has `ALWAYS_VERTICAL_SCROLLBAR`. Contains the following sections, drawn top-to-bottom:

### ▁ TOOLS (header: blue-tinted, `0.65, 0.75, 0.95`)

Two rows of buttons laid out in a **2-column grid**.

**Core tools (5 buttons):**
| Button Label | Tool ID | Colour |
|---|---|---|
| `1 SCULPT` | sculpt | `(220, 160, 60)` — amber |
| `2 PAINT` | paint | `(200, 120, 220)` — purple |
| `3 DETAIL` | segment | `(255, 180, 60)` — orange |
| `4 ENTITY` | entity | `(60, 200, 255)` — cyan |
| `5 PRISM` | box | `(255, 180, 60)` — orange |

Each button is `(avail_w - spacing) / 2` wide, 28px tall. Active tool gets a tinted background (`r, g, b, 0.55`) with white text. Inactive tools get dimmed text (`0.65, 0.65, 0.70`).

**Utility tools (5 buttons):**  
Same 2-column grid, 24px tall, slightly dimmer inactive text (`0.55, 0.55, 0.60`). These toggle: clicking an active utility tool returns to the previous core tool.

| Button Label | Tool ID | Colour |
|---|---|---|
| `B SELECT` | select | `(255, 220, 100)` — yellow |
| `P PRESET` | stamp | `(180, 140, 255)` — violet |
| `I QUAD` | quad | `(255, 140, 180)` — pink |
| `O PORTAL` | portal | `(80, 255, 220)` — teal |
| `; CURVE` | curve | `(255, 200, 100)` — gold |

### ▁ SNAP (header: green-tinted, `0.55, 0.75, 0.60`)

A horizontal row of 5 buttons showing snap grid increments:

| Label | Value |
|---|---|
| 1/16 | 0.0625 |
| 1/8 | 0.125 |
| 1/4 | 0.25 (default) |
| 1/2 | 0.5 |
| 1 | 1.0 |

Active snap button gets green background (`0.22, 0.55, 0.35`). Buttons are evenly sized to fill available width, 22px tall.

### ▁ BRUSH / PRESET / ENTITY (context-dependent, below snap)

Shows **one of three sub-panels** depending on active tool:

#### Texture Palette (paint / segment / select tools)
- Header: `▁ BRUSH` (purple-tinted, `0.75, 0.55, 0.85`)
- Current texture: colour swatch (20×20 `color_button`) + name in warm text (`0.95, 0.90, 0.75`) + index count like `(3/42)` in grey
- Scrollable child window (`border=True`) listing all textures:
  - Each row: 12×12 colour swatch + selectable name
  - Selected item is auto-scrolled into view
  - List height: `max(80, min(220, remaining - 200))` pixels

#### Preset Palette (stamp tool)
- Header: `▁ PRESET` (purple-tinted, `0.70, 0.55, 1.0`)
- Current preset: ■ icon + name in warm text + index
- Category shown in grey below
- Scrollable list of all presets from `PRESET_REGISTRY`, same pattern

#### Entity Palette (entity tool)
- Header: `▁ ENTITY` (cyan-tinted, `0.25, 0.78, 1.0`)
- Current entity: colour swatch + display name + index + category
- Directional arrow `➤` shown in blue if entity is directional
- If an entity is selected: `▸ Selected` label + type name
- Scrollable list grouped by category (uppercase separator headers):
  - Each row: 12×12 colour swatch + display name
- Entity count at bottom: `"N entities in zone"` in grey

### ▁ CONTROLS (header: grey-green, `0.55, 0.60, 0.55`)

Displays context-sensitive action hints from `TOOL_HINTS`. The displayed actions change based on tool + aimed surface + selection state.

Format: key label in gold text (`0.80, 0.75, 0.50`) at left, description wrapped at right (starting at x=72).

Below actions, a `keys` summary line in dim olive text (`0.55, 0.55, 0.40`).

**Select tool extras:** Shows `CEILING MODE` or `FLOOR MODE` label (blue or green), `(X to toggle)`, and cell count when selection exists: `□ N cells selected`.

### ▁ SELECTION (header: yellow-green, `0.70, 0.85, 0.50`)

Only appears when cells or objects are selected.

- Cells: `□ N cells  (W×H)` in warm yellow text (`0.85, 0.85, 0.50`) + `CEILING`/`FLOOR` mode label
- Objects: `○ N object(s)` in teal text (`0.50, 0.85, 0.85`)
- Three action buttons in a row: `[Clear]` `[Ct+A]` `[Del]`

### ▁ DISPLAY (header: grey-blue, `0.50, 0.60, 0.65`)

6 checkboxes in a 2-column layout:

| Checkbox | Default |
|---|---|
| Walls (Ct+1) | ✓ |
| Floors (Ct+2) | ✓ |
| Ceilings (Ct+3) | ✓ |
| Entities (Ct+4) | ✓ |
| Axes | ✓ |
| Wire (Ct+5) | ☐ |

In raycaster preview mode, an FOV slider (45°–120°) appears below.

### Switch Button

Full-width button: `"▶ Switch to Preview (Tab)"` or `"✎ Switch to Editor (Tab)"`. 26px tall.

### ▁ ZONES (header: warm, `0.85, 0.75, 0.45`)

- `[+ New Zone]` button (full width, 24px)
- List of all `.zone` files, each as a selectable item
- Currently loaded zone has `▸ ` prefix and gold text (`1.0, 0.82, 0.25`)

---

## Right Panel ("Inspector")

A fixed ImGui window at `(win_w - right_panel_w, 22)`. Contains:

### Zone Header
Zone name in warm gold text (with ` *` if dirty) + `WxH` dimensions in grey. Separator below.

### Object Inspectors (conditional)

Appear **in any tool** when an object is selected. Multiple can stack if multiple types are selected. Each is a collapsing header, default-open.

#### Entity Inspector (`Entity: {type}`)
- Colour swatch + display name
- ID (read-only)
- **X** — `input_float` with ±0.1/0.5 step, clamped to zone bounds
- **Z** — `input_float` with ±0.1/0.5 step
- **Angle** — `slider_float` 0–360° with 8-direction snap, shows compass label (N/NE/E/SE/S/SW/W/NW). Directional arrow `➤` shown if entity is directional
- **State** — combo box listing all states from entity def (only if >1 state)
- **Scale** — `slider_float` 0.1–3.0 + `[Reset]` button
- `[Deselect]` + red `[Delete]` buttons

#### Prism Inspector (`Prism #N`)
- **X** / **Z** / **Base Y** — `input_float` each
- **Width** / **Height** / **Depth** — `slider_float` each (0.25–8.0)
- **Yaw** — `slider_float` 0–360°
- **Collision** checkbox
- Per-face textures (N/S/E/W/top/bot) — read-only labels
- `[Deselect]` + red `[Delete]` buttons

#### Quad Inspector (`Quad #N`)
- **X** / **Z** / **Base Y** — `input_float` each
- **Width** / **Height** — `slider_float` (0.25–5.0)
- **Angle** — `slider_float` 0–360°
- **Tex** — read-only label
- **Two-sided** / **Collision** checkboxes
- `[Deselect]` + red `[Delete]` buttons

#### Portal Inspector (`Portal #N`)
- **Source** — read-only: `(row, col) FACE`
- **Dest X** / **Dest Y** — `input_float` each
- **Angle Off** — `slider_float` ±180°
- `[Deselect]` + red `[Delete]` buttons

#### Curve Inspector (`Curve #N`)
- **CX** / **CY** — `input_float`
- **Radius** — `slider_float` 0.25–10.0
- **Arc Start** / **Arc End** — `slider_float` 0–360°
- **Height** — `slider_float` 0.25–5.0
- **Base Y** — `input_float`
- **Tex** — read-only label
- `[Deselect]` + red `[Delete]` buttons

### Cell Inspector (when aiming at a cell)

Collapsing header showing either `"N Cells Selected  (aimed R,C)"` or `"Cell (R, C)"`.

When selection is active: green `[Clone Aimed → Selection]` button.

**Tile type:** `WALL` (red) or `OPEN` (green) label + `[Toggle]` button.

**▁ GEOMETRY:**
- **Floor** — `input_float` with ±0.25/0.5 step, clamped -5.0 to 10.0
- **Ceil** — `input_float` with ±0.25/0.5 step. Shows `10.0` when sky-open. Sky toggle button (☀/▣)
- **Gap** — read-only, red if < 0.5
- **Upper Wall** — `input_float` 0.0–10.0

**▁ TEXTURES:**
- Wall / Floor / Ceil texture names (read-only labels, `—` if empty)
- **Quick-paint row:** three buttons `[Set Floor]` `[Set Ceil]` `[Set Wall]` that apply the current brush texture to the cell (or selection)
- Current brush name shown below
- Per-face overrides N/S/E/W (read-only)
- Wall segments tree node (if any segments exist): shows face letter + texture + Y position

**Aimed target:** coloured label like `> Floor Surface`, `> N Wall Face`, `> Ceiling Underside`. In paint tool, shows brush vs. current texture comparison.

**Per-cell properties:**
- **Light** — value display + `slider_float` 0.0–1.0
- **Reflect** — value display + `slider_int` 0–255
- **Layer 2** — F2/C2 heights and textures (if any exist or in layer2 mode), target indicator
- **Fog** — value display + `slider_float` 0.0–1.0

If not aiming at a cell: grey text "Aim at a cell to inspect".

### Zone Settings (collapsing header)
- Size: `W × H` (read-only)
- Anchor: two `input_float` fields (Row/Col) + `[Set to Camera]` button
- First Person checkbox

### Camera (collapsing header)
2-column table: X, Y, Z coordinates + Yaw/Pitch in degrees.

---

## 3D Viewport

Software-rendered to a Pygame `Surface`, then uploaded as an OpenGL texture and drawn as a fullscreen quad behind ImGui. The ImGui panels are drawn on top.

### Background
Solid dark colour `(18, 18, 24)`.

### Grid Lines
Currently a no-op (method exists but returns immediately — "static grids removed; cell edges on walls provide structure").

### Axes
Three coloured lines from origin (0,0,0) extending 2 units along each axis:
- X: red `(220, 60, 60)`
- Y: green `(60, 220, 60)`
- Z: blue `(60, 60, 220)`

### Cell Boxes (the main level geometry)
Each cell is a filled box computed from `_cell_boxes()`:

**Wall cells:** Single solid column from `min(0, floor_h)` to `max(ceil_h, floor_h + 0.05, 1.0)`.

**Open cells:** Two masses:
1. **Floor mass** — extends from `min(0, fh - slab_thickness, min_neighbor_fh - slab)` up to `fh + slab_thickness`
2. **Ceiling mass** (if not sky) — from `ch - slab` up to `max(upper_wall_height + slab, ch + slab)`

Each box is depth-sorted back-to-front. Per-face colours come from `_get_face_colors()` (based on tile textures via `TILE_COLORS`). **Wireframe mode** draws only edges.

#### Cell rendering details:
- Aimed cell gets bright yellow edge highlight `(255, 230, 60)`, width 2
- Wall cells get dim edge `(60, 60, 70)`, width 1
- Floor/ceiling masses have no edge outlines (cleaner look)
- Wall segments drawn as orange `(255, 160, 40)` horizontal lines on faces

### Surface Markers
Within 12 cells of camera, open cells with non-zero floor height get green outlines `(180, 230, 140)` at floor level. Cells with non-sky ceilings get blue outlines `(140, 170, 230)` at ceiling level. Both are axis-aligned rectangles drawn with 4 line segments.

### Segment Boundary Rings
Orange horizontal lines at segment split heights on wall faces. Only drawn when walls are visible.

### Layer 2 Slabs
Secondary floor/ceiling surfaces drawn as translucent filled boxes (80px alpha when aimed, 50px otherwise). Purple-ish colours `(160, 120, 200)` for floor2, `(130, 100, 180)` for ceil2.

### Entities
Each entity is a **solid filled box** with lit faces sitting on the floor:
- Half-width derived from `scale * 0.22` (min 0.08)
- Height = scale value
- Colour from entity def
- Selected entity: full alpha 255, bright cyan edge `(60, 255, 255)`, width 3
- Unselected: alpha 200, slightly lighter edge, width 1
- Ghost preview (entity tool, nothing selected): white-blue `(200, 200, 255)`, alpha 100
- **Direction arrow:** For directional entities, a line + arrowhead at mid-height pointing in the entity's angle direction
- **Label:** Entity type name rendered above the box at screen position using 11pt font

### Prisms (Boxes)
Solid rotated filled boxes:
- Selected: gold `(255, 200, 60)`, alpha 255, edge width 3
- Unselected: brown `(200, 160, 80)`, alpha 180, edge width 1
- Ghost: pale gold `(255, 210, 140)`, alpha 80

Support grid-snapping and auto-stacking (ghost shows final placement position).

### Quads
Vertical rectangles drawn as 4 edge lines + 2 diagonal cross lines:
- Selected: pink `(255, 140, 180)`, width 3
- Unselected: dark pink `(200, 110, 140)`, width 2 edges, width 1 diagonals
- Ghost: light pink `(255, 180, 210)`, width 2/1

### Portals
Face-aligned rectangles with translucent fill:
- 4 edge lines around the portal face (N/S/E/W of the cell)
- Translucent polygon fill (alpha 80 selected, 40 unselected)
- Selected: teal `(80, 255, 220)`, width 3
- Unselected: dark teal `(60, 200, 180)`, width 2
- When selected: yellow line from portal face centre to destination point + crosshair marker at destination

### Curves
Arc wireframes sampled at 16 points:
- Bottom arc + top arc (16 segments each)
- 5 vertical edges at 0%, 25%, 50%, 75%, 100% of arc
- Selected: gold `(255, 200, 100)`, width 3, centre crosshair `(255, 255, 200)`
- Unselected: brown `(200, 160, 80)`, width 1
- Ghost: pale gold `(220, 190, 130)`, width 1, 2 vertical edges at endpoints

### Selection Highlight
Selected cells drawn as thin (0.05 unit tall) filled boxes on either the floor or ceiling surface:
- Completed rectangle: alpha 60, width 1
- Partial (only start corner clicked): alpha 100, width 2
- Colour: `COL_TOOL_SELECT (255, 220, 100)` for floor mode, `COL_TOOL_CEILING (120, 160, 220)` for ceiling mode

### Face Highlight + Preview
When aiming at a cell face (not ground):
- Translucent white quad drawn over the aimed face (`(255, 255, 255, 90)`)
- Suppressed when paint tool is aiming at a prism/quad instead
- In paint tool: prism face highlight and quad face highlight drawn separately
- In segment tool: merge-target boundary highlighted in red `(255, 80, 80)`

**Preview box:** Translucent filled box at the preview position (sculpt height preview). Colour varies by tool.

**Preview line:** A perimeter ring or single-face edge showing where a sculpt/segment action will apply. Orange for segment splits.

### Crosshair
Centred on screen. Tool-coloured.
- 4 lines forming a gap-cross: horizontal lines at ±4 to ±14px, vertical same
- Centre dot (radius 2)
- **Layer 2 sub-mode:** Additional diamond outline (20px) + `L2:FLOOR` or `L2:CEIL` badge above, black background with alpha 160
- When aimed: floor height tick (green, left side) and ceiling height tick (blue, left side) as bar indicators. Tick length = `min(value × 8, 20)` pixels.

### Action Context Overlay
Below the crosshair (centred, y = centre + 26px):
- Semi-transparent black background (`alpha 120`, or purple `(60, 30, 80, 150)` in layer2 mode)
- Lists current LMB/RMB/Scroll/key actions in dim grey `(180, 180, 180)`
- When a selection exists in non-sculpt/non-select tools: appends selection batch hints in yellow `COL_TOOL_SELECT`

### Hotbar
10 slots centred at the bottom of the viewport, 12px margin from bottom edge.

- Each slot: 32×32px, 4px gap between slots
- Black background bar with alpha 140
- Each slot filled with the texture colour from `TILE_COLORS` (or dark grey `(50, 50, 50)` if empty)
- Active slot: white border (width 2)
- Other slots: grey border (width 1)
- Slot number label (1-9, 0) in light grey at top-left corner, 11pt font

### HUD (Top-Left)
Overlaid on the viewport at `(6, 6)`:
- Semi-transparent black background `(0, 0, 0, 200)` sized to fit all lines
- 14pt font, each line coloured per-purpose:

**Always shown:**
1. `Tool: {LABEL}` — in tool colour
2. `Snap: {value}` — in cyan `(120, 220, 255)`
3. `Tex: {texture_name}` — in cyan

**Conditional lines:**
- Selection active: `[Sel: WxH  Floor/Ceil]  X=mode  Esc=clear` in selection colour
- Select tool no selection: `Click to start selection`
- Stamp tool: `Preset: {name}`, `Mode: {mode}  (M)`, capture prompt if capturing
- Layer 2: `[Layer 2]  Target: {floor2/ceil2}` in purple
- Quad tool: snap + size/selection info in pink
- Portal tool: selection info in teal
- Curve tool: radius/selection info in gold
- Box(prism) tool: snap + size/selection info in orange

**Aimed cell info (when aiming):**
- Blank separator line
- `Cell: (col, row)  part` — in warm gold `(255, 200, 80)`
- `Floor: {value}` — in green `(180, 230, 140)`
- `Ceil: {value}` (or `SKY`) — in blue `(140, 170, 230)`
- Upper wall height if applicable
- Face name if applicable
- Segment count + aimed segment details (texture, Y range)
- Layer 2 heights in purple if in layer2 mode

---

## Status Bar

Full-width, 28px tall, dark background `(0.06, 0.06, 0.08, 0.98)`.

**3D Editor mode contents (left to right):**
1. Zone name + dirty dot `●` in warm gold
2. `WxH` dimensions in grey
3. `3D EDITOR` or `RAYCASTER` in blue
4. Tool label in tool colour
5. `Snap:{value}` in grey
6. Tool-specific: `Tex:{name}` / `Preset:{name}` / `Ent:{type}` + `SEL` if entity selected
7. `Cell:(col,row)` when aimed

**Right-aligned:** `● EDITING` in green when mouse is captured.

**Raycaster mode:** shows player position + `NOCLIP` in red if active.

---

## Transient Indicator

A floating popup that fades out over 0.4 seconds, shown at viewport centre + 50px vertically. Black background with alpha 65%. Used for action confirmations (e.g., undo/redo notifications). Custom colour per message.

---

## Modal Dialogs

### New Zone Dialog
_(appears when File > New Zone or button clicked)_

### Save As Dialog
_(appears when File > Save As)_

### Unsaved Guard Dialog
_(appears when switching zones or creating new with unsaved changes)_

---

## Help Overlay (? key)

Floating ImGui window, centred, max 480×600. Title bar: "Keyboard Shortcuts (?)". Closable via X button (which also sets `_show_help = False`).

Contains collapsible sections (all default-open):

**TOOLS** — 1/F5 Sculpt, 2/F6 Paint, etc., Tab cycle, utility keys  
**SELECTION** — B enter/exit, LMB+LMB rect, Sh+LMB line, Ct+LMB toggle, Ct+A all, Esc clear, X mode  
**DISPLAY** — Ct+1/V walls, Ct+2/F floors, etc.  
**GLOBAL** — Ct+S save, Ct+Z undo, Ct+Y redo, ? help, Esc  
**HOTBAR** — 6-0 slots 6-10, Alt+1-0 all 10  
**SCULPT** — LMB/RMB raise/lower, Scroll, T/H/L/R/G/U/X  
**PAINT** — LMB paint, Sh+LMB whole cell, Ct+LMB flood, RMB erase, MMB eyedrop, Scroll cycle  
**OBJECTS** — LMB place/select, Ct+LMB toggle, Sh+LMB add, RMB deselect/delete, Del, R rotate, Scroll adjust  

Key column: gold text (`0.90, 0.80, 0.45`), 14-char wide. Description column at x=140.

---

## Colour Conventions Summary

| Purpose | Colour | Used In |
|---------|--------|---------|
| Floor / height-related | Green (`180, 230, 140`) | HUD, surface markers, crosshair ticks |
| Ceiling / height-related | Blue (`140, 170, 230`) | HUD, surface markers, crosshair ticks |
| Aimed cell edge | Bright yellow (`255, 230, 60`) | Cell box outlines |
| Selection | Warm yellow (`255, 220, 100`) | Selection highlight, HUD |
| Segment boundaries | Orange (`255, 160, 40`) | Wall face lines |
| Entity selected | Cyan (`60, 255, 255`) | Entity box edge |
| Prism selected | Gold (`255, 200, 60`) | Prism box edge |
| Quad selected | Pink (`255, 140, 180`) | Quad wireframe |
| Portal selected | Teal (`80, 255, 220`) | Portal face outline |
| Walls (default untextured) | Magenta (`200, 80, 180`) | Cell box faces |
| Floor (default untextured) | Brown (`140, 120, 100`) | Cell box faces |
| Ceiling (default untextured) | Grey-blue (`100, 105, 120`) | Cell box faces |

---

## Rendering Pipeline

1. Pygame Surface created at full window resolution
2. `Zone3DEditor.draw()` called → fills surface with bg colour
3. Draw order: grids (no-op) → axes → cell boxes (depth-sorted) → surface markers → segment boundaries → layer2 slabs → entities → prisms → quads → portals → curves → selection highlight → face highlight + preview → crosshair → action context → hotbar → HUD
4. Surface uploaded to GL texture via `upload_surface()`
5. GL fullscreen quad drawn (orthographic -1..1)
6. ImGui frame rendered on top (panels, menu bar, status bar, overlays)

All 3D projection is software: `_perspective()` → `_build_view_matrix()` → matrix multiply → per-vertex `_project()`. Frustum culling via `_extract_frustum_planes()` + `_visible_cell_set()`. No GPU shading — all faces are flat-coloured with per-face brightness variation simulating directional light.
