# Post-Apocalyptic Pawn Shop — Map Editor Manual

> Comprehensive reference for the PAPS zone/map editor.
> Covers every panel, tool, keybind, inspector field, modal, and first-person editing workflow.

---

## Table of Contents

1. [Getting Started](#1-getting-started)
2. [Interface Layout](#2-interface-layout)
3. [Menu Bar](#3-menu-bar)
4. [Zone Navigation Bar](#4-zone-navigation-bar)
5. [Toolbar](#5-toolbar)
6. [Canvas (Map Viewport)](#6-canvas-map-viewport)
7. [Left Panels](#7-left-panels)
8. [Inspector (Right Panel)](#8-inspector-right-panel)
9. [First-Person Editor](#9-first-person-editor)
10. [Modal Dialogs](#10-modal-dialogs)
11. [Overlay Editors](#11-overlay-editors)
12. [Entity System](#12-entity-system)
13. [Tile System](#13-tile-system)
14. [Zone Management](#14-zone-management)
15. [Keyboard Shortcut Reference](#15-keyboard-shortcut-reference)
16. [Mouse Reference](#16-mouse-reference)
17. [Project Directory Structure](#17-project-directory-structure)

---

## 1. Getting Started

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

## 2. Interface Layout

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

## 3. Menu Bar

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

## 4. Zone Navigation Bar

Sits directly below the menu bar.

| Element | Description |
|---------|-------------|
| **◀ Back** | Navigate to the previous zone in history (grayed when unavailable) |
| **▶ Forward** | Navigate to the next zone in history |
| **Zone name** | Displays the current zone name. An asterisk `*` appears when unsaved changes exist. An **FP** badge appears if the zone's First Person flag is set. |
| **→ connected zones** | Clickable tabs for every portal target zone, allowing quick navigation |

---

## 5. Toolbar

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

## 6. Canvas (Map Viewport)

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

## 7. Left Panels

Six interchangeable panels, selectable via the **panel tabs** (two rows of three tabs) or the **View** menu.

| Tab       | Panel                | Purpose |
|-----------|----------------------|---------|
| Tiles     | Tile Palette         | Browse and select tiles for painting |
| Entities  | Entity Panel         | Browse prefabs and forge archetypes for placement |
| Textures  | Texture Browser      | Browse imported textures |
| Portals   | Portal Panel         | Manage portal entities |
| Templates | Room Template Panel  | Browse and manage room templates |
| Zones     | Zone Panel           | List and switch between zone files |

### 7.1 Tile Palette

A searchable, scrollable grid of tile swatches grouped by type.

- **Filter bar** at the top: type to filter tiles by name, ID, or texture key. Press Esc to clear.
- **Group headers**: Floor, Wall, Half_Wall, Platform, Door, Liquid. Click the arrow (▸/▾) to collapse or expand a group.
- **Swatches**: Display texture thumbnails from the atlas (fallback: solid color). The selected tile has an accent border.
- **Left-click** a swatch to select it. If the current tool is not Brush, Fill, or Eraser, it switches to Brush.
- **Right-click** a swatch to open the **Tile Editor Modal** for that tile (edit name, color, type, textures, etc.).
- **"+ Add Tile"** button at the bottom opens the Tile Editor in creation mode.
- **Scroll** with the mouse wheel to browse.

### 7.2 Entity Panel

A unified list combining built-in prefabs and Entity Forge archetypes.

- Each entry shows an icon (based on kind), display name, and kind label. Forge items are marked with `[F]`.
- **Kind icons**: ☺ npc · ✦ item · □ container · ☠ beast · ○ dummy · ■ prop · ☻ player
- **Click** an entry to begin placement mode: sets `pending_prefab`, switches to Select tool, and toasts the name.
- The currently pending prefab is highlighted.

### 7.3 Texture Browser

Browse all textures loaded in the atlas. Useful for verifying imported assets.

### 7.4 Portal Panel

Lists portal entities in the current zone with their target zones.

### 7.5 Room Template Panel

Browse room templates for the template editor system.

### 7.6 Zone Panel

- Lists all JSON zone files in the `zones/` directory (refreshed every 2 seconds).
- The current zone is highlighted with an accent color.
- **Click** a zone name to load it.

---

## 8. Inspector (Right Panel)

Three tabs along the top: **Zone**, **Tile**, **Entity**. The active tab depends on context (selecting a tile switches to Tile tab, selecting an entity switches to Entity tab, etc.).

### 8.1 Zone Tab

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

### 8.2 Tile Tab

Read-only properties for the tile under the cursor or the last-inspected tile.

| Section     | Fields |
|-------------|--------|
| **Header**  | `TILE: <name>` |
| **Properties** | ID, Type (floor/wall/etc.), Category, Flags (solid, wall, transparent, half, platform, liquid, farmland), Height (2 decimal places) |
| **Textures** | Default texture key, per-face overrides (N/S/E/W/Top as applicable) |
| **Preview**  | 64×64 texture thumbnail from atlas |
| **Color**    | Color swatch with RGB values |

### 8.3 Entity Tab

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

## 9. First-Person Editor

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

## 10. Modal Dialogs

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
| Face textures  | Per-slot text fields       | Slots depend on tile type (see §13) |
| Height scale   | Slider                     | 0.05 – 1.0 |
| Category       | Dropdown                   | Existing categories + "New Category…" |
| Preview        | 64×64 texture thumbnail    | Live preview |

**Buttons:** Update/Create, Delete (edit mode only), Cancel, Import PNG.

---

## 11. Overlay Editors

Full-screen editor overlays that take over the entire window. Close them to return to the map editor.

### Loot Table Editor

Two-panel layout for editing `data/loot_tables.toml`:

- **Left panel**: Scrollable list of loot tables. Click to select.
- **Right panel**: Selected table detail showing pools, each with entries listing item ID, weight, min_count, and max_count.
- **Actions**: Close, Save, New Table, Add Pool, Add/Delete entries and pools. All fields are inline-editable.

### Template Editor

Full-screen overlay for zone template management.

- **Templates** define rectangular slots filled with room variants at bake time.
- **Template data**: name, width, height, base_tiles, slots, fixed_entities, portals.
- **Room data**: name, tags, width, height, tiles, entities.
- **Baking**: picks random rooms matching each slot's tag and size constraints, pastes tiles and entities.

### Entity Forge

Create reusable entity archetypes with custom component configurations. Forge archetypes appear in the Entity panel marked with `[F]`.

---

## 12. Entity System

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

## 13. Tile System

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

## 14. Zone Management

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

## 15. Keyboard Shortcut Reference

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

## 16. Mouse Reference

### Canvas (2D)

| Button         | Action |
|----------------|--------|
| Left-click     | Tool action (see §6) |
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

## 17. Project Directory Structure

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
