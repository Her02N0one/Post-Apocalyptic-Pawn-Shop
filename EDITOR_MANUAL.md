# Post-Apocalyptic Pawn Shop — Map Editor Manual

> Comprehensive reference for the PAPS zone/map editor.
> Covers every panel, tool, keybind, inspector field, modal, and first-person editing workflow.

---

## Table of Contents

1. [Prerequisites & Setup](#1-prerequisites--setup)
2. [Getting Started](#2-getting-started)
3. [Interface Layout](#3-interface-layout)
4. [Menu Bar](#4-menu-bar)
5. [Zone Navigation Bar](#5-zone-navigation-bar)
6. [Toolbar](#6-toolbar)
7. [Canvas (Map Viewport)](#7-canvas-map-viewport)
8. [Left Panels](#8-left-panels)
9. [Inspector (Right Panel)](#9-inspector-right-panel)
10. [First-Person Editor](#10-first-person-editor)
11. [Modal Dialogs](#11-modal-dialogs)
12. [Overlay Editors](#12-overlay-editors)
13. [Entity System](#13-entity-system)
14. [Tile System](#14-tile-system)
15. [Zone Management](#15-zone-management)
16. [Portal Linking Workflow](#16-portal-linking-workflow)
17. [First-Person Visual Rules](#17-first-person-visual-rules)
18. [Task-Based Workflows](#18-task-based-workflows)
19. [Keyboard Shortcut Reference](#19-keyboard-shortcut-reference)
20. [Mouse Reference](#20-mouse-reference)
21. [Project Directory Structure](#21-project-directory-structure)

---

## 1. Prerequisites & Setup

### System Requirements

| Requirement | Value |
|-------------|-------|
| **Python**  | 3.9 or later |
| **OS**      | Windows, macOS, or Linux |
| **Display** | 960 × 640 minimum (editor opens at 80 % of display resolution) |

### Dependencies

All Python dependencies are listed in `requirements.txt`:

```
pygame-ce >= 2.4       # Rendering, input, window management
nbtlib >= 0.17         # Binary export (.mpz format)
numpy                  # Floor/ceiling rendering, visplane math
tomli >= 2.0.0         # TOML parsing (items, tuning, tile defs)
msgpack >= 1.0.0       # Binary save format
```

Install with:

```bash
pip install -r requirements.txt
```

> **Note:** `pygame-ce` (Community Edition) is required, not the legacy `pygame` package. If you already have `pygame` installed, uninstall it first: `pip uninstall pygame && pip install pygame-ce`.

### First-Boot Behavior

On first launch, the editor auto-creates any missing directories:

| Directory | Created If Missing | Purpose |
|-----------|--------------------|---------|
| `zones/` | Yes | Zone map JSON files |
| `templates/` | Yes | Template editor data |
| `templates/rooms/` | Yes | Room variant data |
| `saves/` | Yes (game only) | Save game slots |
| `logs/` | Yes (game only) | Performance logs |
| `assets/textures/tiles/` | Yes | Imported tile PNGs |
| `assets/models/tiles/` | Yes | Tile definition TOMLs |
| `data/` | No (must exist) | Game data files |

If no zone is specified on the command line, the editor opens with a blank unnamed 30×20 zone. The zone is not saved to disk until you press **Ctrl+S** or **File → Save**.

---

## 2. Getting Started

### Launching the Editor

```bash
python editor_main.py                # open a blank unnamed zone
python editor_main.py playground     # open a specific zone by name
```

The editor window opens at 80 % of your display resolution (minimum 960 × 640) and is freely resizable. Frame rate is locked to 60 FPS.

### Launching the Game

```bash
python main.py                       # launches the game (not the editor)
```

### First Steps

1. **File → New Zone…** to create a fresh zone, or **File → Open Zone…** to load an existing one.
2. Select a tile from the **Tile Palette** on the left.
3. Use the **Brush** tool (B) and left-click on the canvas to paint.
4. Press **P** for a first-person preview, or **F** to enter full first-person editing.
5. Press **Ctrl+S** to save.

---

## 3. Interface Layout

The editor is composed of fixed chrome regions arranged around a central canvas.

```
┌──────────────────────────────────────────────────────────────────┐
│  Menu Bar                                                        │
├──────────────────────────────────────────────────────────────────┤
│  Zone Navigation Bar                                             │
├──────────────────────────────────────────────────────────────────┤
│  Toolbar (Select · Brush · Eraser · Fill · Picker)               │
├────────────┬───────────────────────────────────┬─────────────────┤
│ Panel Tabs │                                   │                 │
│────────────│         Canvas / Map               │   Inspector    │
│            │                                   │   (3 tabs)     │
│ Left Panel │                                   │                 │
│ (context-  │        (or FP Preview)            │  Zone / Tile   │
│  dependent)│                                   │  / Entity      │
│            │                                   │                 │
├────────────┴───────────────────────────────────┴─────────────────┤
│  Status Bar                                                      │
└──────────────────────────────────────────────────────────────────┘
```

### Scaling

All measurements scale with window height: **scale = max(0.75, window_height / 640)**. The helper `Layout.s(px)` converts design-pixels to screen-pixels.

### Panel Sizing

| Region       | Default Width                              | User-Resizable |
|--------------|--------------------------------------------|----------------|
| Left Panel   | `max(s(130), min(s(200), 16 % of width))`  | Yes (drag splitter) |
| Inspector    | `max(s(210), min(s(320), 24 % of width))`  | Yes (drag splitter) |
| Canvas       | Remaining space (min `s(200)`)             | Automatic |

If the canvas would shrink below `s(200)`, the inspector is narrowed first (down to `s(160)`), then the left panel (down to `s(80)`). Drag the splitter handles between panels to resize manually.

### Draw Order (back → front)

1. Background fill
2. Chrome panel backgrounds and borders
3. Canvas (map tiles, grid, entities)
4. Zone nav bar, toolbar, status bar
5. Left panel tabs and content
6. Minimap (floats over canvas)
7. Inspector
8. Pending-placement hint banner
9. First-person preview (PIP or fullscreen)
10. Panel splitter handles
11. Chrome overlays
12. Menu bar and dropdown menus
13. Modal dialogs (topmost)

---

## 4. Menu Bar

The menu bar sits at the top of the window. Click a menu name to open its dropdown. Click outside or press Esc to close.

### File

| Item              | Shortcut | Action |
|-------------------|----------|--------|
| New Zone…         |          | Open the New Zone modal |
| Open Zone…        |          | Open the zone picker list |
| Save              | Ctrl+S   | Save current zone to `zones/<name>.json` |
| Save As…          |          | Save under a new name |
| Rename Zone…      |          | Rename the current zone file |
| —                 |          | *(separator)* |
| Quit              |          | Close the editor |

### Edit

| Item              | Shortcut | Action |
|-------------------|----------|--------|
| Undo              | Ctrl+Z   | Revert last change |
| Redo              | Ctrl+Y   | Reapply undone change |
| —                 |          | *(separator)* |
| Delete Entity     | Delete   | Delete the selected entity |

### View

| Item              | Shortcut | Action |
|-------------------|----------|--------|
| Toggle Grid       | G        | Show / hide the tile grid overlay (✓ when on) |
| Toggle Minimap    | M        | Show / hide the minimap (✓ when on) |
| —                 |          | *(separator)* |
| FP Preview        | P        | Toggle first-person PIP window |
| FP Edit Mode      | F        | Enter first-person fullscreen editing |
| —                 |          | *(separator)* |
| Brush Size +      | ]        | Increase brush size (max 9) |
| Brush Size −      | [        | Decrease brush size (min 1) |
| —                 |          | *(separator)* |
| Tile Palette      |          | Switch left panel (• when active) |
| Entity Presets    |          | " |
| Texture Browser   |          | " |
| Portals           |          | " |
| Room Templates    |          | " |
| Zone List         |          | " |

### Tools

| Item    | Shortcut | Action |
|---------|----------|--------|
| Select  | V        | Switch to Select tool (• when active) |
| Brush   | B        | Switch to Brush tool |
| Eraser  | E        | Switch to Eraser tool |
| Fill    | I        | Switch to Fill tool |
| Picker  |          | Switch to Picker (eyedropper) tool |

### Editors

| Item             | Action |
|------------------|--------|
| Room Templates   | Open the template editor overlay |
| Loot Tables      | Open the loot table editor overlay |
| —                | *(separator)* |
| Entity Forge     | Open the entity forge overlay |

### Export

| Item              | Action |
|-------------------|--------|
| Import Texture…   | Browse for a PNG and import into the texture atlas |
| —                 | *(separator)* |
| Export .mpz (bin) | Export current zone to binary `.mpz` format |
| Export All .mpz   | Export every JSON zone to `.mpz` |

---

## 5. Zone Navigation Bar

Sits directly below the menu bar.

| Element | Description |
|---------|-------------|
| **◀ Back** | Navigate to the previous zone in history (grayed when unavailable) |
| **▶ Forward** | Navigate to the next zone in history |
| **Zone name** | Displays the current zone name. An asterisk `*` appears when unsaved changes exist. An **FP** badge appears if the zone's First Person flag is set. |
| **→ connected zones** | Clickable tabs for every portal target zone, allowing quick navigation |

---

## 6. Toolbar

A horizontal strip of equal-width buttons spanning the full window width, directly below the zone nav bar. The active tool is highlighted.

| Button   | Shortcut | Tool Constant |
|----------|----------|---------------|
| Select   | V        | `Tool.SELECT` |
| Brush    | B        | `Tool.BRUSH` |
| Eraser   | E        | `Tool.ERASER` |
| Fill     | I        | `Tool.FILL` |
| Picker   |          | `Tool.PICKER` |

### Tool Behaviors

**Select** — Click an entity to select it and open the Entity inspector tab. Click empty tile to inspect it (Tile tab). With a pending prefab/forge archetype, click to place the entity. Drag a selected entity to reposition it.

**Brush** — Left-click or drag to paint the current tile onto the map. Brush size (1–9) determines the area painted per stroke (adjustable with `[` / `]`).

**Eraser** — Left-click or drag to replace tiles with the configured *erase tile* (default: grass, changeable in the Zone inspector tab).

**Fill** — Left-click to flood-fill a contiguous region of matching tiles with the current tile (4-connected).

**Picker** — Left-click a tile on the canvas to "eyedrop" it: the tile becomes the selected tile and the tool switches to Brush automatically.

---

## 7. Canvas (Map Viewport)

The canvas renders the 2D tile grid and all entities.

### Navigation

| Input               | Action |
|---------------------|--------|
| Middle-click + drag | Pan the camera |
| Scroll wheel        | Zoom in/out (×1.15 per notch, range 0.15 – 6.0) |

### Mouse Actions by Tool

| Tool    | Left-click                              | Left-drag              | Right-click                     |
|---------|-----------------------------------------|------------------------|---------------------------------|
| Select  | Place pending entity / select entity / inspect tile | Drag entity           | Deselect entity; cancel pending |
| Brush   | Paint tile (push undo)                  | Continuous paint       | Deselect entity                 |
| Eraser  | Erase tile (push undo)                  | Continuous erase       | Deselect entity                 |
| Fill    | Flood-fill region (push undo)           | —                      | Deselect entity                 |
| Picker  | Eyedrop tile → switch to Brush          | —                      | Deselect entity                 |

### Entity Interaction (Select Tool)

1. **Placing:** Click a prefab/forge entry in the Entity panel → cursor enters placement mode → left-click canvas to place. Right-click or Esc to cancel.
2. **Selecting:** Left-click an existing entity to select it. The inspector switches to the Entity tab.
3. **Dragging:** With an entity selected, left-click and drag to reposition it (snaps to tile centers). Release to confirm.
4. **Deleting:** Press Delete with an entity selected.

### Grid & Minimap

- **G** toggles the grid overlay.
- **M** toggles the minimap, which floats in the upper-left of the canvas area.

---

## 8. Left Panels

Six interchangeable panels, selectable via the **panel tabs** (two rows of three tabs) or the **View** menu.

| Tab       | Panel                | Purpose |
|-----------|----------------------|---------|
| Tiles     | Tile Palette         | Browse and select tiles for painting |
| Entities  | Entity Panel         | Browse prefabs and forge archetypes for placement |
| Textures  | Texture Browser      | Browse imported textures |
| Portals   | Portal Panel         | Manage portal entities |
| Templates | Room Template Panel  | Browse and manage room templates |
| Zones     | Zone Panel           | List and switch between zone files |

### 8.1 Tile Palette

A searchable, scrollable grid of tile swatches grouped by type.

- **Filter bar** at the top: type to filter tiles by name, ID, or texture key. Press Esc to clear.
- **Group headers**: Floor, Wall, Half_Wall, Platform, Door, Liquid. Click the arrow (▸/▾) to collapse or expand a group.
- **Swatches**: Display texture thumbnails from the atlas (fallback: solid color). The selected tile has an accent border.
- **Left-click** a swatch to select it. If the current tool is not Brush, Fill, or Eraser, it switches to Brush.
- **Right-click** a swatch to open the **Tile Editor Modal** for that tile (edit name, color, type, textures, etc.).
- **"+ Add Tile"** button at the bottom opens the Tile Editor in creation mode.
- **Scroll** with the mouse wheel to browse.

### 8.2 Entity Panel

A unified list combining built-in prefabs and Entity Forge archetypes.

- Each entry shows an icon (based on kind), display name, and kind label. Forge items are marked with `[F]`.
- **Kind icons**: ☺ npc · ✦ item · □ container · ☠ beast · ○ dummy · ■ prop · ☻ player
- **Click** an entry to begin placement mode: sets `pending_prefab`, switches to Select tool, and toasts the name.
- The currently pending prefab is highlighted.

### 8.3 Texture Browser

Browse all textures loaded in the atlas. Useful for verifying imported assets.

### 8.4 Portal Panel

Lists portal entities in the current zone with their target zones.

### 8.5 Room Template Panel

Browse room templates for the template editor system.

### 8.6 Zone Panel

- Lists all JSON zone files in the `zones/` directory (refreshed every 2 seconds).
- The current zone is highlighted with an accent color.
- **Click** a zone name to load it.

---

## 9. Inspector (Right Panel)

Three tabs along the top: **Zone**, **Tile**, **Entity**. The active tab depends on context (selecting a tile switches to Tile tab, selecting an entity switches to Entity tab, etc.).

### 9.1 Zone Tab

Displays and edits zone-level properties plus a full entity listing.

| Field          | Widget        | Editable | Notes |
|----------------|---------------|----------|-------|
| **Name**       | TextField     | Yes      | Press Enter to rename the zone |
| **Width**      | NumberField   | Yes      | 5 – 200; triggers `resize_zone()` |
| **Height**     | NumberField   | Yes      | 5 – 200; triggers `resize_zone()` |
| **First Person** | Checkbox   | Yes      | Marks zone as first-person |
| **Portals**    | KV read-only  | No       | Count of portal entities |
| **Entities**   | KV read-only  | No       | Count of non-portal entities |
| **Erase Tile** | Dropdown      | Yes      | Selects which tile the Eraser paints (default: grass) |

**Entity List** — Below the zone properties, every entity in the zone is listed as a clickable row showing `prefab: name`. Clicking a row selects that entity and switches to the Entity tab.

### 9.2 Tile Tab

Read-only properties for the tile under the cursor or the last-inspected tile.

| Section     | Fields |
|-------------|--------|
| **Header**  | `TILE: <name>` |
| **Properties** | ID, Type (floor/wall/etc.), Category, Flags (solid, wall, transparent, half, platform, liquid, farmland), Height (2 decimal places) |
| **Textures** | Default texture key, per-face overrides (N/S/E/W/Top as applicable) |
| **Preview**  | 64×64 texture thumbnail from atlas |
| **Color**    | Color swatch with RGB values |

### 9.3 Entity Tab

Fully editable component inspector for the selected entity.

| Section          | Fields | Widget Types |
|------------------|--------|--------------|
| **Header**       | `ENTITY: <name>` | Label |
| **Identity**     | ID (text), Prefab (dropdown of all prefabs), Name (text), Kind (dropdown: npc, player, item, container, dummy, prop, beast, ground_item, crop) | TextField, Dropdown |
| **Forge ref**    | Archetype name (read-only, if set) | KV |
| **Dev Notes**    | Notes (text), Tags (comma-separated text) | TextField |
| **Position**     | X (−500 to 500, step 0.5), Y (−500 to 500, step 0.5) | NumberField |
| **Sprite**       | Char (single character), Layer (0–20, integer), Color (RGB) | TextField, NumberField, ColorField |
| **Collider** *(if present)* | Width (0.1–5, step 0.1), Height (0.1–5, step 0.1), Solid (checkbox) | NumberField, Checkbox |
| **Health** *(if present)* | Current (0–9999, step 5), Max (1–9999, step 5) | NumberField |
| **TileEntity** *(if present)* | Type (dropdown: container, crop, ground_item), Loot table (dropdown), Item ID (dropdown, if ground_item), Quantity (1–999), Already Looted (checkbox) | Dropdown, NumberField, Checkbox |
| **WallSprite** *(if present)* | Texture (text), Width (0–10, step 0.05), Height, Elevation | TextField, NumberField |
| **Inventory** *(if present)* | Per-item rows: `item_id: count` | KV read-only |
| **Facing** *(if present)* | Direction (dropdown: up, down, left, right) | Dropdown |
| **Dialogue** *(if present)* | Bark (text) | TextField |
| **Portal** *(if present)* | Target zone (text), Target row, Target col, Exit direction (dropdown), Tiles (read-only) | TextField, NumberField, Dropdown |
| **Extras**       | Any unknown keys preserved from JSON, shown read-only (truncated to 40 chars) | KV read-only |

**Actions:**
- **"Add Component…"** button opens the Add Component modal, listing components not yet attached: collider, health, tile_entity, wall_sprite, inventory, facing, dialogue, sprite, combat_stats.
- **"Delete Entity"** button removes the entity after confirmation.

---

## 10. First-Person Editor

A Minecraft-creative-style first-person view for building and previewing zones in 3D. The raycaster renders walls, floors, and entities using the zone's tile data and texture atlas.

### Activating

| Key | Action |
|-----|--------|
| **P** | Toggle PIP (picture-in-picture) preview in the top-right of the canvas |
| **F** | Enter fullscreen first-person editing mode |
| **Tab** | Toggle between PIP and fullscreen (while FP is active) |
| **Esc** | Fullscreen → PIP. PIP → close FP entirely. |

### PIP Mode

A small preview window (`min(400, canvas_w/2)` × `min(300, canvas_h/2)`) in the top-right corner of the canvas. Shows a passive view. Controls are limited to movement and keyboard turning.

**PIP HUD:**
- Top-left: `FP Preview (x, y)`
- Below: `WASD=Move  Arrows=Turn  Tab=Edit  Esc=Close`

### Fullscreen Mode

The FP view fills the entire canvas area. Mouse is grabbed for mouselook. Full editing controls are available.

### Movement

| Key       | Action |
|-----------|--------|
| W         | Move forward |
| S         | Move backward |
| A         | Strafe left |
| D         | Strafe right |
| Shift     | Sprint (×2.0 speed) |
| Mouse     | Mouselook (horizontal, 0.003 rad/pixel) |
| ← / →    | Keyboard turning (PIP only, 2.5 rad/s) |

**Movement speed:** 4.0 tiles/second (8.0 sprinting). The camera checks 4 corners with a 0.2-tile collision margin against solid tiles. **Noclip** bypasses all collision (enabled by default; toggle with **C**).

### Hotbar

A row of 10 slots displayed at the bottom center of the screen. Each slot holds a tile ID and shows a texture thumbnail.

| Input        | Action |
|--------------|--------|
| **1 – 9**    | Select hotbar slots 0 – 8 |
| **0**        | Select hotbar slot 9 |
| **Scroll wheel** | Cycle through slots |

**Default hotbar:** wall, brick_wall, stone, grass, concrete, door, wood_floor, carpet, sand, void.

The active slot has an accent border. Slot numbers are displayed above each thumbnail.

### Tile Picker Overlay

Press **T** to open a full-viewport overlay for assigning tiles to hotbar slots.

- Title: *"TILE PICKER (click to assign, Esc to close)"*
- Tiles displayed in a grid, grouped by category with headers: `--- CategoryName (count) ---`
- 6 px gaps between swatches, auto-fit to viewport width
- **Hover** a tile: accent border and name tooltip
- **Left-click**: Assigns the tile to the current hotbar slot, closes the picker, toasts the assignment
- **Right-click / Esc / T**: Close the picker without changes
- **Scroll wheel**: Vertical scroll (30 px per notch)
- The picker absorbs all events while open.

### Tile Placement

| Input          | Action |
|----------------|--------|
| **Left-click** | **Place tile.** If aiming at a wall and there is an empty cell in front of it, the tile is placed in that empty cell (wall-building). If aiming at a floor, the tile is painted onto the aimed cell. |
| **Right-click** | **Eyedropper.** Picks the aimed tile into the current hotbar slot. |
| **Middle-click** | **Erase.** Replaces the aimed cell with the configured erase tile. |
| **Ctrl+Z**     | Undo |
| **Ctrl+Y**     | Redo |

### Ghost Preview

A transparent overlay showing where a tile will be placed:

- **Wall ghost:** A textured column rendered at the ghost cell position with pulsing alpha and outline.
- **Floor ghost:** A projected polygon on the floor plane with tile-color tint and pulsing alpha.
- Both display a label with the tile name.

### Crosshair

A gap-center cross (4 line segments, ±3 to ±8 px). In fullscreen, the crosshair is tinted to match the target tile's color.

### Noclip

Enabled by default. Toggle with **C**. When active, an orange **NOCLIP** indicator appears in the top-right. Noclip disables all movement collision, allowing the camera to pass through walls freely — useful for building corridors and enclosed rooms.

### Fullscreen HUD

| Position      | Content |
|---------------|---------|
| Top-left      | Camera position `(x, y)` |
| Below          | `Aim: TileName [row, col] (wall/floor)` |
| Below          | `Click: build/paint [row, col]` (when ghost is valid) |
| Top-right     | `NOCLIP` indicator (orange, when active) |
| Bottom-center | 10-slot hotbar with thumbnails |
| Bottom         | `WASD=Move  Shift=Sprint  T=Tiles  C=Noclip  Esc=Exit` |

### Constants

| Constant     | Value   | Meaning |
|--------------|---------|---------|
| MAX_DEPTH    | 24.0    | Raycast distance in tiles |
| RAY_STEP     | 4       | DDA stepping resolution |
| MOVE_SPEED   | 4.0     | Tiles per second |
| SPRINT_MULT  | 2.0     | Sprint speed multiplier |
| MOUSE_SENS   | 0.003   | Radians per pixel of mouse movement |
| HOTBAR_SLOTS | 10      | Number of hotbar slots |

---

## 11. Modal Dialogs

Modals appear as centered panels over a darkened overlay (black, alpha 180). Press **Esc** to close any modal. While a modal is active, all input is directed to it.

### Text Input Modal

A single text field with a label. Used for Save As and Rename operations.

- **Enter** confirms the input.
- **Esc** cancels.

### New Zone Modal

Create a new zone with:

| Field   | Widget      | Default | Range |
|---------|-------------|---------|-------|
| Name    | TextField   | *(empty)* | — |
| Width   | NumberField | 30      | 5 – 200 |
| Height  | NumberField | 20      | 5 – 200 |

**Enter** creates the zone. **Esc** cancels.

### Zone Picker Modal

A scrollable list of all zones in the `zones/` directory. The current zone is highlighted. Scroll with the mouse wheel.

- **Click** a zone to load it.
- **Esc** or **Tab** to cancel.

### Add Component Modal

Displays a list of components that are not yet attached to the selected entity. Available components:

- collider, health, tile_entity, wall_sprite, inventory, facing, dialogue, sprite, combat_stats

**Click** a component to add it with default values. **Esc** to cancel.

### Tile Editor Modal

A full-featured tile creation/editing dialog.

| Field          | Widget                     | Notes |
|----------------|----------------------------|-------|
| Name           | TextField                  | Tile display name |
| Color          | RGB sliders (draggable)    | Base color |
| Type           | Dropdown                   | floor, wall, half_wall, platform, door, liquid |
| Transparent    | Checkbox                   | Extra flag |
| Farmland       | Checkbox                   | Extra flag |
| Texture key    | TextField                  | PNG asset key |
| Face textures  | Per-slot text fields       | Slots depend on tile type (see §14) |
| Height scale   | Slider                     | 0.05 – 1.0 |
| Category       | Dropdown                   | Existing categories + "New Category…" |
| Preview        | 64×64 texture thumbnail    | Live preview |

**Buttons:** Update/Create, Delete (edit mode only), Cancel, Import PNG.

---

## 12. Overlay Editors

Full-screen editor overlays that take over the entire window. Open them from the **Editors** menu. Close them to return to the map editor. While an overlay is active, the map editor is not drawn and all events are routed to the overlay.

### 12.1 Loot Table Editor

**Open:** Editors → Loot Tables

A two-panel overlay for editing `data/loot_tables.toml`. All changes are held in memory until you press **Save**.

#### UI Layout

```
┌────────────────────────────────────────────────────────────┐
│  [Close]  [Save]  [New Table]    LOOT TABLE EDITOR         │
├──────────────┬─────────────────────────────────────────────┤
│ table_1      │  TABLE: table_1                             │
│ table_2  ●   │  Description: …  [Delete Table]             │
│ table_3      │                                             │
│              │  [Add Pool]                                  │
│              │  ┌───── Pool 0 ──── [Edit] [Delete] ───┐   │
│              │  │ Item      Weight  Min  Max           │   │
│              │  │ bandage   10      1    3    [×]      │   │
│              │  │ medkit    5       1    1    [×]      │   │
│              │  │ [Add Entry]                          │   │
│              │  └──────────────────────────────────────┘   │
│              │                                             │
│              │  ┌───── Pool 1 ──── [Edit] [Delete] ───┐   │
│              │  │ …                                    │   │
└──────────────┴─────────────────────────────────────────────┘
```

- **Left panel**: Scrollable list of table names. Click to select. Current table has a bullet (●).
- **Right panel**: Detail view of the selected table.

#### Loot Math — Weighted Lottery

Each **pool** is rolled independently. Within a pool, each entry has a **weight** (integer). The total weight is the sum of all entries. The probability of an entry being selected is:

$$P(\text{entry}) = \frac{\text{weight}}{\text{total weight of pool}}$$

When the pool is rolled, exactly one entry is selected. The resulting item count is a random integer in `[min_count, max_count]`.

**Example:** A pool with `bandage:10, medkit:5, nothing:85` has total weight 100. The bandage has a 10 % chance, the medkit 5 %, and "nothing" (empty result) 85 %.

Multiple pools in the same table are rolled independently — the player can receive items from every pool, one pool, or none.

#### Actions

| Button | Action |
|--------|--------|
| **Close** | Return to the map editor (unsaved changes are lost) |
| **Save** | Write all tables to `data/loot_tables.toml` |
| **New Table** | Opens a text field to name a new table |
| **Delete Table** | Removes the selected table |
| **Add Pool** | Appends an empty pool to the selected table |
| **Edit** (pool) | Toggle inline editing of all entry fields in the pool |
| **Delete** (pool) | Removes the pool |
| **Add Entry** | Appends a blank entry (item: `""`, weight: 1, min: 1, max: 1) |
| **×** (entry) | Removes that entry from the pool |

All text and number fields are inline-editable: click a cell to type.

### 12.2 Template Editor

**Open:** Editors → Room Templates

A full-screen overlay for creating zone templates — reusable blueprints that generate randomized zones at **bake time**.

#### Concepts

| Concept | Definition |
|---------|-----------|
| **Template** | A master layout defining overall size, base tiles, fixed entities, portals, and rectangular **slots**. Stored as `templates/<name>.json`. |
| **Slot** | A rectangular region within a template with a name, position (x, y), size (w, h), and a set of **tags**. At bake time, a matching room variant fills the slot. |
| **Room Variant** | A small tilemap with entities and tags. Stored as `templates/rooms/<name>.json`. Rooms are matched to slots by tag intersection and size constraint. |
| **Baking** | The process of converting a template into a concrete zone by filling each slot with a randomly chosen matching room variant. |

#### Template JSON Format

```json
{
  "name": "apartment_block",
  "width": 50,
  "height": 40,
  "base_tiles": [[0, 0, ...], ...],
  "slots": [
    { "name": "bedroom_1", "x": 2, "y": 3, "w": 10, "h": 8,
      "tags": ["bedroom"], "required": true }
  ],
  "fixed_entities": [ { "id": "...", "prefab": "...", ... } ],
  "portals": [ ... ]
}
```

#### Room Variant JSON Format

```json
{
  "name": "cozy_bedroom",
  "tags": ["bedroom"],
  "width": 10,
  "height": 8,
  "tiles": [[1, 1, ...], ...],
  "entities": [ { "id": "bed_1", ... } ]
}
```

#### Slot Matching & Baking Algorithm

1. For each slot, gather all room variants whose **tags intersect** the slot's tags.
2. Filter by size: the room's width must be ≤ slot width, and height ≤ slot height.
3. Pick one matching room at random (optionally seeded for reproducibility).
4. Center the room within the slot and paste its tiles over the base grid.
5. Append the room's entities with positions offset by the slot's origin.
6. If no room matches a **required** slot, the slot is filled with tile ID 1 (wall) as a placeholder.

#### UI Workflow

1. **Select or create** a template from the left panel list.
2. **Edit base tiles** — the template's background tilemap.
3. **Add slots** — define rectangular regions and assign tags (e.g., `bedroom`, `kitchen`, `corridor`).
4. **Create room variants** in the rooms panel and tag them to match slot requirements.
5. **Bake** — click the Bake button to produce a concrete zone. Optionally provide a seed for reproducible output.
6. **Save** the resulting zone as a normal zone JSON.

### 12.3 Entity Forge

**Open:** Editors → Entity Forge

A full-screen no-code editor for creating **ForgeArchetype** entries — reusable entity definitions stored in `data/custom_entities.toml`. Forge archetypes appear in the Entity Panel marked with `[F]` and can be placed on the map just like built-in prefabs.

#### Forge vs. Prefabs

| Aspect | Built-in Prefabs | Forge Archetypes |
|--------|-----------------|------------------|
| Defined in | `systems/spawner.py` (code) | `data/custom_entities.toml` (data) |
| Editable at runtime | No | Yes (via Entity Forge) |
| Kinds | player, npc, item, container, beast, dummy, ground_item, crop, prop | tile, box, billboard |
| Placement | Entity Panel click → canvas | Entity Panel click → canvas (marked `[F]`) |
| ID format | System-defined (e.g., `merchant`, `chest`) | User-defined (e.g., `mossy_column`, `red_barrel`) |

#### UI Layout

```
┌──────────────────────────────────────────────────────────────┐
│  ENTITY FORGE                          [New] [Dup] [Del]     │
│                                        [Save] [Close]        │
├──────────────┬───────────────────────────────────────────────┤
│ [All][tile]  │  IDENTITY                                     │
│ [box][bill]  │  ID:   ________    Name: ________             │
│              │  Kind: [dropdown]  Tags: ________             │
│ mossy_column │                                               │
│ red_barrel ● │  DEV NOTES                                    │
│ shelf_unit   │  Notes: ________                              │
│              │                                               │
│              │  TILE PROPERTIES                               │
│              │  Texture: ________  Floor Z: [0.00]           │
│              │  Ceiling Z: [1.00]  Solid: [✓]               │
│              │  Transparent: [ ]                              │
│              │                                               │
│              │  PREVIEW                                       │
│              │  ┌──────────┐                                 │
│              │  │  (live)  │                                 │
│              │  └──────────┘                                 │
└──────────────┴───────────────────────────────────────────────┘
```

#### Three Archetype Kinds

| Kind | Description | Key Properties |
|------|------------|----------------|
| **tile** | Wall or floor surface | `texture_key`, `floor_z`, `ceiling_z`, `solid`, `transparent` |
| **box** | 3D rectangular prism | `width`, `depth`, `height`, `z_offset`, `color`, `solid`, `texture_key` |
| **billboard** | 2D sprite that faces the camera | `sprite_char`, `sprite_color`, `scale`, `directional`, `sprite_sheet` |

The property panel changes dynamically based on which kind is selected in the Kind dropdown.

#### Forge Workflow

1. **Create**: Click **New** to create a blank archetype (default kind: box).
2. **Edit**: Fill in the ID, name, kind, and kind-specific properties. All fields update live.
3. **Preview**: The preview box at the bottom shows a visual representation.
4. **Save**: Click **Save** (or **Close** — you'll be prompted). Data is written to `data/custom_entities.toml`.
5. **Place**: Close the forge, switch to the Entities panel. Your archetype appears with `[F]`. Click to place.
6. **Duplicate**: Select an archetype and click **Dup** to clone it with a `_copy0` suffix.
7. **Delete**: Click **Del** to permanently remove the archetype.

#### Filter Tabs

The left panel has filter tabs: **All**, **tile**, **box**, **billboard**. Click a tab to show only archetypes of that kind. The currently selected archetype has a bullet indicator.

---

## 13. Entity System

Entities are stored as `EntityDef` dataclass instances. Each has a core identity and optional components.

### Core Fields

| Field            | Type       | Description |
|------------------|------------|-------------|
| `id`             | str        | Unique identifier |
| `prefab`         | str        | Base prefab template name |
| `position`       | EDPosition | Always present (x, y as floats) |
| `dev_notes`      | str        | Developer notes |
| `tags`           | list[str]  | Freeform tags |
| `forge_archetype`| str        | Forge archetype ID (if forge-created) |
| `extras`         | dict       | Unknown keys preserved verbatim during round-trip |

### Components

All components are optional (absent = `None`). Add them via the Entity inspector's "Add Component…" button.

| Component       | Fields | Defaults |
|-----------------|--------|----------|
| **EDIdentity**  | name (str), kind (str) | `""`, `"npc"` |
| **EDPosition**  | x (float), y (float) | `0.0`, `0.0` |
| **EDSprite**    | char (str), color (list[int]), layer (int) | `"?"`, `[200,200,200]`, `5` |
| **EDCollider**  | w (float), h (float), solid (bool) | `0.6`, `0.6`, `True` |
| **EDHealth**    | current (float), maximum (float) | `100.0`, `100.0` |
| **EDTileEntity**| tile_type (str), item_id (str), item_qty (int), loot_table (str), looted (bool) | `"container"`, `""`, `1`, `""`, `False` |
| **EDWallSprite**| texture_key (str), width (float), height (float), elevation (float) | `""`, `1.0`, `1.0`, `0.0` |
| **EDInventory** | items (dict[str, int]) | `{}` |
| **EDFacing**    | direction (str) | `"down"` |
| **EDDialogue**  | bark (str) | `""` |
| **EDCombatStats**| damage (float), attack_range (int), attack_cooldown (float), hostile (bool) | `5.0`, `1`, `2.0`, `False` |
| **EDPortal**    | tiles (list), target_zone (str), target_pos (list[float]), exit_direction (str) | `[]`, `""`, `[0.0,0.0]`, `"up"` |

### Entity Kinds

player · npc · item · container · dummy · beast · ground_item · crop · prop

### Prefab Placement Flow

1. Click a prefab/forge entry in the Entity panel.
2. The tool switches to Select and a placement hint appears.
3. Left-click the canvas at the desired tile.
4. The entity is created with prefab defaults and added to the zone.
5. Right-click or Esc cancels placement.

---

## 14. Tile System

### Data Format

Tile definitions live as individual **TOML** files in `assets/models/tiles/`.
Each file's stem is the tile ID (e.g. `assets/models/tiles/mossy_stone.toml` → ID `mossy_stone`).

```toml
name = "Mossy Stone"
type = "wall"
category = "Walls"
color = [80, 90, 70]
sound = "stone"

texture = "mossy_stone"
texture_front = "mossy_stone_front"
texture_back = "mossy_stone_back"
```

### Tile Types

| Type       | Geometry                | Default Flags |
|------------|-------------------------|---------------|
| FLOOR      | Walkable ground         | *(none)* |
| WALL       | Full-height wall        | SOLID, WALL |
| HALF_WALL  | Partial-height wall     | SOLID, WALL, HALF_WALL |
| PLATFORM   | Elevated surface        | SOLID, PLATFORM |
| DOOR       | Wall-height, passable   | WALL (not solid) |
| LIQUID     | Floor-level liquid      | LIQUID |

### Tile Flags (TF)

| Flag        | Bit    | Meaning |
|-------------|--------|---------|
| SOLID       | 1 << 0 | Blocks movement |
| WALL        | 1 << 1 | Has wall geometry |
| TRANSPARENT | 1 << 2 | Allows light/sight through walls |
| LIQUID      | 1 << 3 | Liquid surface |
| FARMLAND    | 1 << 4 | Farmable ground |
| HALF_WALL   | 1 << 5 | Half-height wall |
| PLATFORM    | 1 << 6 | Elevated platform |

### Tile Definition Fields

| Field          | Type              | Default     | Description |
|----------------|-------------------|-------------|-------------|
| id             | str               | —           | Unique identifier (filename stem) |
| name           | str               | —           | Display name |
| color          | (int, int, int)   | —           | RGB base color |
| type           | TileType          | FLOOR       | Geometry type |
| flags          | TF                | NONE        | Behavior flags |
| texture_key    | str               | `""` → id   | PNG asset key (falls back to id) |
| texture_front  | str               | `""`        | Directional front-face texture override |
| texture_back   | str               | `""`        | Directional back-face texture override |
| height_scale   | float             | 1.0         | Wall height multiplier |
| category       | str               | "Terrain"   | Palette grouping |
| sound          | str               | "stone"     | Footstep sound |

### Directional Texture Model

Each tile has a default `texture` (used for all faces), plus optional `texture_front`
and `texture_back` overrides. Which world face maps to "front" or "back" depends on the
tile's **rotation** (0–3):

| Rotation | Front Face | Back Face | Mnemonic |
|----------|------------|-----------|----------|
| 0 (N)    | south      | north     | Default orientation |
| 1 (E)    | west       | east      | 90° clockwise |
| 2 (S)    | north      | south     | 180° |
| 3 (W)    | east       | west      | 270° clockwise |

Faces that don't match front or back use the default `texture`.

### Tile Rotation

Each cell in the zone grid has a parallel **rotation** value (0–3) stored in the
`rotations` grid. The rotation determines which direction the tile's "front" faces.

- **R key** (editor or FP fullscreen): Cycle pending rotation → N → E → S → W
- **Paint / Fill / FP place**: The pending rotation is stored in the placed cell
- **Erase**: Resets rotation to 0

### Built-in Categories

Terrain · Floors · Walls · Openings · Barriers · Platforms · Custom

### Constants

| Constant    | Value | Meaning |
|-------------|-------|---------|
| TILE_SIZE   | 32    | Pixels per tile in the 2D editor |
| TILE_METRES | 1.0   | In-game metres per tile |

---

## 15. Zone Management

### File Format

Zones are stored as JSON in the `zones/` directory:

```json
{
  "name": "zone_name",
  "width": 30,
  "height": 20,
  "anchor": [0, 0],
  "first_person": false,
  "tiles": [["grass", "grass", ...], ...],
  "rotations": [[0, 0, ...], ...],
  "portals": [...],
  "entities": [...]
}
```

The `rotations` grid is parallel to `tiles` — each value (0–3) specifies the
tile's directional rotation for that cell. Omitted or missing `rotations` defaults
all cells to 0.

Portals are stored separately from entities for backward compatibility but are treated as entities internally.

### Operations

| Operation       | How to Access | Notes |
|-----------------|---------------|-------|
| **New Zone**    | File → New Zone… | Specify name, width (5–200), height (5–200). Default: 30×20. |
| **Open Zone**   | File → Open Zone… *or* Zone panel *or* zone nav | Loads from `zones/<name>.json` |
| **Save**        | File → Save (Ctrl+S) | Writes to `zones/<name>.json` |
| **Save As**     | File → Save As… | Prompts for new name |
| **Rename**      | File → Rename Zone… *or* Zone tab Name field | Renames the file on disk |
| **Resize**      | Zone tab Width/Height fields | Clamps 5–200. New area filled with grass. Existing tiles copied where they fit. |

### Undo / Redo

- **Depth limit**: 80 snapshots.
- **Snapshot**: Deep copy of the entire tile grid and entity list.
- **Push**: Every paint, erase, fill, entity place/delete/drag, and resize pushes an undo snapshot. Performing a new action clears the redo stack.
- **Ctrl+Z**: Undo (pops from undo stack, pushes to redo).
- **Ctrl+Y**: Redo (pops from redo stack, pushes to undo).

### Zone History Navigation

The zone nav bar maintains a browser-style back/forward history. Loading a new zone pushes it onto the stack. The ◀/▶ buttons traverse the stack.

---

## 16. Portal Linking Workflow

Portals connect two zones. When the player walks over a portal's tiles in-game, they are teleported to the target zone at the specified position.

### Creating a Portal

1. Switch to the **Entities** panel (left panel → Entities tab).
2. Click the **portal** prefab — this enters placement mode.
3. Left-click the canvas tile where you want the portal to appear.
4. The portal entity is created with default values. Select it to open the **Entity tab** in the inspector.

### Configuring Portal Properties

In the Entity inspector's Portal component section, fill in:

| Field | Description | Example |
|-------|-------------|---------|
| **Target zone** | The filename (without `.json`) of the destination zone | `house_interior` |
| **Target row** | The row (Y) coordinate the player arrives at in the target zone | `5` |
| **Target col** | The column (X) coordinate the player arrives at | `12` |
| **Exit direction** | The direction the player faces after teleporting: `up`, `down`, `left`, `right` | `down` |
| **Tiles** | Read-only list of tile coordinates this portal occupies | Auto-populated |

### Finding Target Coordinates

To determine the target row/col:

1. **Open the target zone** — File → Open Zone, or click a zone name in the Zone panel.
2. **Hover over the destination tile** on the canvas.
3. **Read the status bar** — it shows `(col, row)` in the bottom-left. The `col` is your target col and `row` is your target row.
4. **Go back** to the source zone (◀ button in the zone nav bar) and enter the coordinates in the portal inspector.

> **Tip:** The zone nav bar's ◀/▶ buttons maintain a browser-style history, making it easy to flip between source and target zones while configuring portals.

### Bi-Directional Portals

Portals are **one-way** by default. If you want the player to be able to return, you must create a second portal in the target zone that points back to the source zone:

1. Open the **target zone**.
2. Place a portal entity at the tile where the player arrives (the `target_row`, `target_col` from step 1).
3. Set its **Target zone** to the original source zone.
4. Set its **Target row/col** to a tile near the source portal.
5. Set its **Exit direction** to face away from the return portal.

### Portal Display on Canvas

- Portal tiles are drawn with a tinted overlay and a pulsing ring (magenta for unselected, accent for selected).
- The portal's target zone is shown as a label below the entity icon.
- The **Portal Panel** (left panel → Portals tab) lists all portal entities in the current zone with their destinations.
- The **Zone Navigation Bar** shows clickable tabs for every connected zone, enabling quick navigation.

### Common Portal Patterns

| Pattern | Setup |
|---------|-------|
| **Door between rooms** | Single-tile portal on each side of a door, pointing to the other zone's door tile |
| **Zone boundary** | Row of portal tiles along the map edge, target zone's opposite edge |
| **Staircase** | Portal on a platform tile, target at a different elevation in the target zone |
| **One-way trap** | Portal with no return portal in the target zone |

---

## 17. First-Person Visual Rules

This section explains how the raycaster renders geometry and entities in the first-person view.

### Rendering Pipeline

The FP view draws in this order (back to front):

1. **Floor & Ceiling** — flat-shaded horizontal planes based on tile colors
2. **Walls** — textured vertical columns cast by the DDA raycaster
3. **Half-walls & Entities** — interleaved in **painter's order** (far to near) so half-walls correctly occlude entities behind them
4. **HUD** — crosshair, hotbar, position info, noclip indicator

### Wall Rendering

Each column of the screen casts a ray from the camera. When a ray hits a wall tile, a textured vertical strip is drawn. Key rules:

| Property | Behavior |
|----------|----------|
| **Full walls** (height_scale = 1.0) | Extend from floor to ceiling, completely opaque |
| **Short walls** (height_scale < 1.0) | Bottom-aligned — the wall grows upward from the floor. A wall with `height_scale = 0.5` is half the height of a full wall. |
| **Half-walls** (`HALF_WALL` flag) | Rendered as **deferred strips** — not drawn with full walls but interleaved with entity billboards in painter's order. This allows entities to appear behind half-walls when farther away, and in front when closer. |
| **Transparent walls** (`TRANSPARENT` flag) | The raycaster continues casting through transparent walls, rendering the wall strip but also anything behind it. Used for fences, glass, or bars. |
| **Doors** (`DOOR` type) | Full wall height but **not solid** — the player can walk through them. Rendered with wall textures. |

### Directional Textures on Walls

Each wall tile can have up to three textures: `texture` (default), `texture_front`, and `texture_back`. Which world face maps to "front" or "back" depends on the tile's **rotation**:

| Rotation | Front → World Face | Back → World Face |
|----------|--------------------|-------------------|
| 0 (N) | South | North |
| 1 (E) | West | East |
| 2 (S) | North | South |
| 3 (W) | East | West |

Faces that aren't designated front or back use the default `texture`. If a directional texture is blank, the default texture is used.

### Entity Billboard Rendering

Entities in the FP view are rendered as **billboards** — 2D sprites projected into 3D space. They always face the camera (unless `is_billboard = False`, in which case facing affects apparent width).

#### Projection Rules

| Property | Value | Notes |
|----------|-------|-------|
| **Max render distance** | 14.0 tiles | Entities beyond this are culled |
| **Detail distance** | 5.0 tiles | Name tags and health bars are hidden beyond this |
| **Z-buffer check** | Per-column | Billboard columns behind a wall are not drawn |

#### Entity Visual Sizing

Each entity's sprite character determines its visual size via the `ENTITY_VIS` lookup:

| Character | Height Scale | Width Scale | Billboard? | Example |
|-----------|-------------|-------------|-----------|---------|
| D, N, M, V | 0.75 | 0.50 | Yes | NPC characters |
| O | 0.45 | 0.45 | Yes | Barrels |
| ☆ | 0.25 | 0.20 | Yes | Small items |
| ≡ | 0.60 | 0.70 | No | Shelves |
| □ | 0.40 | 0.45 | No | Crates |
| ■ | 0.35 | 0.40 | No | Safes |
| Default | 0.60 | 0.50 | Yes | Any unlisted character |

**Billboard = Yes**: The sprite always faces the camera at full width.
**Billboard = No**: The sprite is **facing-aware** — its apparent width is scaled by `max(0.20, |cos(facing_angle − view_angle)|)`. Objects viewed from the side appear narrower.

#### Textured Billboards

Certain sprite characters map to pre-defined texture keys:

| Character | Texture Key |
|-----------|-------------|
| ≡ | shelf |
| □ | crate |
| ■ | safe |
| ═ | table |
| ▒ | bookshelf |
| O | barrel |

If an entity has a matching texture in the atlas, it renders as a textured rectangle instead of a colored glyph. Otherwise, a font-rendered glyph is used.

#### Entity Fog & Distance Shading

Entity billboards receive distance-based fog identical to walls: a fog LUT darkens sprites proportionally to their distance. The fog rate is controlled by the `dn` (day/night) parameter.

### Platform Elevation

Entities standing on a **platform** tile (tiles with the `PLATFORM` flag and `height_scale > 0`) are visually elevated. The billboard's base shifts upward by the platform's `height_scale` value. This creates the illusion of entities standing on raised surfaces.

### Verticality Limitations

The current raycaster is a **2.5D engine** (like classic Doom):

- **No true vertical stacking** — you cannot have rooms above other rooms.
- **No Z-axis movement** — the camera is always at a fixed eye height.
- **Platforms are visual only** — they raise entity billboards but don't create true multi-level geometry.
- **Ceilings are uniform** — the ceiling plane is flat, drawn as a gradient. Per-tile ceiling heights are not rendered.
- **No vertical aiming** — the crosshair is always at the horizon.

### WallSprite Entities

Entities with a `WallSprite` component are rendered as part of the wall system rather than as billboards. They appear as textured rectangles attached to wall surfaces with configurable width, height, and elevation. Common uses: paintings, signs, shelving mounted on walls.

---

## 18. Task-Based Workflows

Step-by-step guides for common editor tasks.

### How to Create a Functional Room

1. **Create or open a zone**: File → New Zone or File → Open Zone.
2. **Set room dimensions**: In the Zone inspector tab, set Width and Height (e.g., 15×12).
3. **Paint walls**: Select `wall` (or `brick_wall`, `stone`, etc.) from the Tile Palette. Use the Brush tool (B) to paint the perimeter.
4. **Paint the floor**: Select a floor tile (e.g., `wood_floor`, `concrete`). Fill the interior with the Fill tool (I), or brush it manually.
5. **Add a door**: Select the `door` tile. Paint it over one wall tile to create an entrance. Doors are wall-height but not solid.
6. **Place furniture**: Switch to the Entities panel. Click a furniture prefab (e.g., `shelf`, `table`). Click the canvas to place it.
7. **Preview in 3D**: Press **F** to enter first-person mode. Walk around the room. Press **Esc** to return.
8. **Save**: Ctrl+S.

### How to Create an NPC with Dialogue and Loot

1. **Place the NPC**: In the Entities panel, click a character prefab (e.g., `merchant`, `wanderer`). Click the canvas to place.
2. **Select the NPC**: Switch to Select tool (V), click the NPC on the canvas. The inspector opens to the Entity tab.
3. **Set identity**: In the Identity section, set a display **Name** (e.g., "Old Jim"), **Kind** = `npc`.
4. **Set sprite**: In the Sprite section, set **Char** to a letter (e.g., `N`), choose a **Color**.
5. **Add dialogue**: If the Dialogue component isn't present, click **"Add Component…"** → **dialogue**. Set the **Bark** text (e.g., "Got anything to trade?").
6. **Add inventory**: Click **"Add Component…"** → **inventory**. Inventory items are defined in JSON; edit the zone file directly or use tile_entity for loot containers.
7. **Add health** (optional): Click **"Add Component…"** → **health**. Set **Current** and **Max** HP values.
8. **Save**: Ctrl+S.

### How to Connect Two Zones with Portals

See [§16. Portal Linking Workflow](#16-portal-linking-workflow) for the complete step-by-step guide. Quick summary:

1. Open zone A. Place a `portal` entity at the exit tile.
2. In the inspector, set **Target zone** = zone B's name, and **Target row/col** = the arrival tile in zone B.
3. Open zone B. Place a `portal` entity at the arrival tile.
4. Set its **Target zone** = zone A, **Target row/col** = the exit tile in zone A.
5. Save both zones.

### How to Create a Loot Container

1. **Place entity**: Entities panel → click `chest` (or `crate`, `barrel`). Click the canvas.
2. **Select it**: Switch to Select tool, click the container.
3. **Configure TileEntity**: In the Entity tab, find the **TileEntity** section. Set **Type** = `container`.
4. **Assign a loot table**: Set **Loot table** to a defined table name (e.g., `common_loot`). If you need to create one, open Editors → Loot Tables first.
5. **Save**: Ctrl+S.

When the player interacts with this container in-game, the loot table is rolled to generate items.

### How to Set Up a Zone for First-Person Play

1. **Paint solid walls** around the playable area (the raycaster needs walls to cast rays against).
2. **Paint floor tiles** inside the playable area (empty/void tiles render as pits).
3. **Enable FP flag**: In the Zone inspector tab, check **First Person**.
4. **Place a player spawn**: Entities panel → `player_spawn`. Click the canvas at the desired spawn location.
5. **Test**: Press **F** to enter fullscreen FP mode. Walk around with WASD.
6. **Build in FP**: Use the hotbar (1-9, 0) to select tiles. Left-click to place, right-click to eyedrop, middle-click to erase.
7. **Use noclip**: If you get stuck inside walls, press **C** to toggle noclip (enabled by default).

### How to Import and Use Custom Textures

1. **Prepare the texture**: Create a 64×64 PNG image for the tile face.
2. **Import**: Menu → Export → Import Texture…. Browse to the PNG file.
3. **The texture** is copied to `assets/textures/tiles/<filename>.png` and loaded into the atlas.
4. **Assign to a tile**: Open the Tile Editor (right-click a tile in the palette, or "Add Tile"). Set the **Texture key** field to the filename stem (without `.png`).
5. **Directional textures**: Set **Texture Front** and/or **Texture Back** to different texture keys for per-face variation.
6. **Use rotation**: Press **R** to cycle the tile's orientation before painting. Rotation determines which world face maps to front/back.

### How to Use the Entity Forge

1. Open **Editors → Entity Forge**.
2. Click **New** to create a blank archetype.
3. Set the **ID** (lowercase, underscores, e.g., `tall_shelf`).
4. Set the **Kind** dropdown: `tile`, `box`, or `billboard`.
5. Fill in kind-specific properties (texture, dimensions, sprite, etc.).
6. Click **Save** to write to `data/custom_entities.toml`.
7. Click **Close** to return to the editor.
8. In the **Entities panel**, your forge entry appears with `[F]`. Click to place.

---

## 19. Keyboard Shortcut Reference

### Global Shortcuts (2D Editor)

| Shortcut  | Action |
|-----------|--------|
| Ctrl+S    | Save zone |
| Ctrl+Z    | Undo |
| Ctrl+Y    | Redo |
| G         | Toggle grid |
| M         | Toggle minimap |
| \[        | Brush size − 1 |
| \]        | Brush size + 1 |
| P         | Toggle FP Preview (PIP) |
| F         | Enter FP Edit (fullscreen) |
| Delete    | Delete selected entity |
| Escape    | Cancel pending placement |
| R         | Rotate tile (cycle N → E → S → W) |
| V         | Select tool |
| B         | Brush tool |
| E         | Eraser tool |
| I         | Fill tool |
| 0 – 9     | Select Nth tile from registry; switch to Brush |

### First-Person Shortcuts (Fullscreen)

| Shortcut    | Action |
|-------------|--------|
| W/A/S/D     | Move |
| Shift       | Sprint |
| Mouse       | Look (horizontal) |
| Left-click  | Place tile |
| Right-click | Eyedropper |
| Middle-click| Erase tile |
| 1 – 9, 0   | Select hotbar slot |
| Scroll      | Cycle hotbar slot |
| T           | Open tile picker |
| R           | Rotate tile |
| C           | Toggle noclip |
| Ctrl+Z      | Undo |
| Ctrl+Y      | Redo |
| Tab         | Switch to PIP |
| Esc         | Exit to PIP |

### First-Person Shortcuts (PIP)

| Shortcut  | Action |
|-----------|--------|
| W/A/S/D   | Move |
| ← / →    | Keyboard turning |
| Tab       | Switch to fullscreen |
| Esc       | Close FP preview |

---

## 20. Mouse Reference

### Canvas (2D)

| Button         | Action |
|----------------|--------|
| Left-click     | Tool action (see §7) |
| Left-drag      | Continuous paint/erase or entity drag |
| Middle-click   | Pan camera |
| Right-click    | Deselect / cancel placement |
| Scroll wheel   | Zoom (×1.15 per notch, 0.15 – 6.0) |

### First-Person (Fullscreen)

| Button         | Action |
|----------------|--------|
| Left-click     | Place tile |
| Right-click    | Eyedropper |
| Middle-click   | Erase tile |
| Mouse motion   | Look around |
| Scroll wheel   | Cycle hotbar slot |

### Panels

| Button         | Action |
|----------------|--------|
| Left-click     | Select item / toggle / edit field |
| Right-click    | Context menu (tile palette: edit tile) |
| Scroll wheel   | Scroll panel content |

---

## Event Priority

When multiple UI elements overlap, events are consumed in this priority order (first handler that accepts the event wins):

1. QUIT signal
2. Entity Forge overlay
3. Loot Table Editor overlay
4. Template Editor overlay
5. Modal dialogs
6. Global keyboard shortcuts
7. Menu bar dropdowns
8. Zone navigation bar
9. Toolbar
10. Panel splitter drag handles
11. FP fullscreen (consumes all events)
12. Panel tabs
13. Left panel content
14. Inspector
15. FP PIP mode
16. Canvas

---

## Status Bar

The status bar sits at the very bottom of the window.

| Section | Content |
|---------|---------|
| Left    | Hover info: `(col, row) tile=id(name) WxH z=Zoom ent=EntityName` (entity name only in Select mode) |
| Center  | Toast messages (fade after a few seconds) |
| Right   | Keyboard hints: `^S ^Z ^Y  G:Grid M:Map [:- ]:+ F:FP` |

---

*This manual reflects the current state of the editor codebase. Keep it updated as features change.*

---

## 21. Project Directory Structure

All paths are defined in `core/paths.py` — the single source of truth.

```
assets/                          # Client-side resources (art, audio, FX)
  textures/
    tiles/                       # 64×64 PNGs, one per tile texture key
  sounds/                        # Sound effects & ambient audio
  models/
    tiles/                       # Tile definitions (one .toml per tile)
  particles/                     # Particle effect definitions
  lang/                          # Localization / string tables

data/                            # Game data definitions (all TOML)
  functions/                     # Data-driven functions
  loot_tables.toml               # Loot table definitions
  items.toml                     # Item definitions
  characters.toml                # NPC / character archetypes
  tuning.toml                    # Game tuning parameters
  population_presets.toml        # Zone population configs
  subzones.toml                  # Sub-zone descriptors
  room_types.toml                # Room type definitions
  portals.toml                   # Portal definitions
  custom_entities.toml           # Entity Forge archetypes
  tags/                          # Tag groups
  predicates/                    # Condition predicates
  recipes/                       # Crafting recipes
  structures/                    # Structure templates

zones/                           # Zone map files (JSON)
templates/                       # Editor templates
saves/                           # Save game slots
logs/                            # Performance logs
```
