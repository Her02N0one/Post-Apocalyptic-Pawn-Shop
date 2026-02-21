# Post-Apocalyptic Pawn Shop — Map Editor Manual

> Comprehensive reference for the PAPS zone/map editor.
> Covers every panel, tool, keybind, inspector field, modal, and first-person editing workflow.

### How to Use This Manual

Sections 1–18 cover daily editing workflows and UI reference — start here for learning the editor. Sections 19–22 are quick-reference tables for shortcuts, mouse actions, event priority, and the status bar. Section 23 documents the project directory layout. Sections 24–27 are technical appendices for contributors, debuggers, and anyone who needs to understand the rendering pipeline, event routing internals, error handling, or how the game consumes editor data at runtime.

---

## Table of Contents

#### Setup
1. [Prerequisites & Setup](#1-prerequisites--setup)
2. [Getting Started](#2-getting-started)

#### Interface
3. [Interface Layout](#3-interface-layout)
4. [Menu Bar](#4-menu-bar)
5. [Zone Navigation Bar](#5-zone-navigation-bar)
6. [Toolbar](#6-toolbar)
7. [Canvas (Map Viewport)](#7-canvas-map-viewport)
8. [Left Panels](#8-left-panels)
9. [Inspector (Right Panel)](#9-inspector-right-panel)

#### First-Person Editing
10. [First-Person Editor](#10-first-person-editor)
17. [First-Person Visual Rules](#17-first-person-visual-rules)

#### Dialogs & Overlays
11. [Modal Dialogs](#11-modal-dialogs)
12. [Overlay Editors](#12-overlay-editors)

#### Data Systems
13. [Entity System](#13-entity-system)
14. [Tile System](#14-tile-system)

#### Zone Management
15. [Zone Management](#15-zone-management)
16. [Portal Linking Workflow](#16-portal-linking-workflow)

#### Workflows
18. [Task-Based Workflows](#18-task-based-workflows)

#### Quick Reference
19. [Keyboard Shortcut Reference](#19-keyboard-shortcut-reference)
20. [Mouse Reference](#20-mouse-reference)
21. [Event Priority](#21-event-priority)
22. [Status Bar](#22-status-bar)

#### Project Structure
23. [Project Directory Structure](#23-project-directory-structure)

#### Technical Appendices
24. [Texture Atlas](#24-texture-atlas)
25. [Editor State Machine & Event Routing](#25-editor-state-machine--event-routing)
    - [25.1 Modes & Transitions](#251-modes--transitions)
    - [25.2 Event Priority (Detailed)](#252-event-priority-detailed)
    - [25.3 FP Shortcut Audit](#253-fp-shortcut-audit)
    - [25.4 Text Field & Input Conflicts](#254-text-field--input-conflicts)
    - [25.5 Entity Drag Edge Cases](#255-entity-drag-edge-cases)
    - [25.6 State Persistence & Loading](#256-state-persistence--loading)
26. [Error Behavior](#26-error-behavior)
27. [Game Runtime Context](#27-game-runtime-context)

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

**Fill** — Left-click to flood-fill a contiguous region of matching tiles with the current tile (4-connected). Contiguity matches **tile ID only** — rotation is ignored. All filled cells receive the current **pending rotation** (cycled with R), regardless of the original cells' rotations.

**Picker** — Left-click a tile on the canvas to "eyedrop" it: the tile becomes the selected tile and the tool switches to Brush automatically.

See §7 for the complete mouse action table showing how each tool responds to left-click, left-drag, and right-click.

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
| Picker  | Eyedrop tile → switch to Brush. **Does not capture rotation** — only the tile ID. | —                      | Deselect entity                 |

### Entity Interaction (Select Tool)

1. **Placing:** Click a prefab/forge entry in the Entity panel → cursor enters placement mode → left-click canvas to place. Right-click or Esc to cancel.
2. **Selecting:** Left-click an existing entity to select it. The inspector switches to the Entity tab.
3. **Dragging:** With an entity selected, left-click and drag to reposition it. The entity **always snaps to tile centres** — the position is set to `(col + 0.5, row + 0.5)` based on the hovered tile. If an entity was placed at a non-centre position via the inspector (e.g. `3.0, 4.0`), dragging it will snap it to `3.5, 4.5`. Release to confirm.
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

- **Filter bar** at the top: type to filter tiles by name, ID, or texture key. Press Esc to clear. **Note:** The filter bar suffers the same shortcut conflict as inspector text fields (§25). Global shortcuts fire before the palette handler, so typing `g` toggles the grid instead of adding "g" to the filter, `r` cycles rotation, `p` toggles FP preview, etc. Only non-bound characters reach the filter. Additionally, **Esc itself is a global shortcut** (priority 6 — cancels pending placement) that fires before the palette handler (priority 13): if a pending entity placement exists, the first Esc cancels the placement and never reaches the filter bar. Press Esc a second time to clear the filter. The filter uses its own `_filter_active` flag (not `UIContext.focused_id`), but is handled at the same relative priority.
- **Group headers**: `Floor`, `Wall`, `Half_Wall`, `Platform`, `Door`, `Liquid`. Click the arrow (▸/▾) to collapse or expand a group.
- **Swatches**: Display texture thumbnails from the atlas (fallback: solid color). The selected tile has an accent border.
- **Left-click** a swatch to select it. If the current tool is not Brush, Fill, or Eraser, it switches to Brush.
- **Right-click** a swatch to open the **Tile Editor Modal** for that tile (edit name, color, type, textures, etc.).
- **"+ Add Tile"** button at the bottom opens the Tile Editor in creation mode.
- **Scroll** with the mouse wheel to browse.

### 8.2 Entity Panel

A unified list combining built-in prefabs and Entity Forge archetypes.

- **Ordering**: Built-in prefabs are listed first (sorted alphabetically by name), followed by Forge archetypes (sorted alphabetically by ID). The two groups are not visually separated beyond the `[F]` badge on forge items.
- **Duplicate IDs**: No deduplication is performed. If a forge archetype has the same ID as a built-in prefab, both appear in the list. They dispatch different placement actions internally (`select_prefab` vs `select_forge`), so they remain distinct despite the name collision.
- **Search / Filter**: The entity panel has no search or filter bar (unlike the Tile Palette). It is a flat scrollable list.
- Each entry shows an icon (based on kind), display name, and kind label. Forge items are marked with `[F]`.
- **Kind icons**: ☺ npc · ✦ item · □ container · ☠ beast · ○ dummy · ■ prop · ☻ player
- **Click** an entry to begin placement mode: sets `pending_prefab`, switches to Select tool, and toasts the name. If another prefab was already pending, it is **replaced** — there is no need to cancel the previous one first.
- The currently pending prefab is highlighted.

### 8.3 Texture Browser

A grid of square thumbnails showing every `.png` file in the tile textures directory (`assets/textures/tiles/`). The grid auto-fits columns to the panel width.

```
┌──────────────┐
│ ┌──┐┌──┐┌──┐ │
│ │  ││  ││  │ │  Thumbnail
│ └──┘└──┘└──┘ │  grid
│ ┌──┐┌──┐┌──┐ │
│ │  ││  ││  │ │
│ └──┘└──┘└──┘ │
│ ┌──┐┌──┐     │
│ │  ││  │     │
│ └──┘└──┘     │
│ ──────────── │
│  key_name     │  Hover tooltip
└──────────────┘
```

- **Thumbnails** are loaded via `TextureAtlas.get_by_key(key)` and scaled to fit. Missing or unloadable textures appear as dark gray placeholder squares.
- **Hover** a thumbnail to see an accent-colour border and the **texture key name** displayed below it — this is particularly useful for identifying keys to type into tile definitions.
- **Click** a thumbnail — currently shows a toast with the texture key name. No tile-paint assignment or clipboard copy is performed (placeholder action).
- **Not searchable** — there is no filter or search bar. Textures are listed in alphabetical order.
- **No metadata** is displayed (no dimensions, no usage counts, no tile-ID cross-references). The panel is a visual index only.
- The panel has a `refresh()` method that triggers a re-scan on the next draw. It is called automatically when textures are imported.

### 8.4 Portal Panel

A scrollable list of all portal entities in the current zone, sourced from the zone state's portal list.

```
┌──────────────┐
│ ▣ → campsite  │
│   2 tile(s)   │
├──────────────┤
│ ▣ → outskirts │
│   1 tile(s)   │
├──────────────┤
│              │
│  (empty)     │
└──────────────┘
```

- **Each row** displays a portal icon (`▣` in magenta) with an arrow and the **destination zone name** (e.g. `→ campsite`), truncated on narrow panels. A second line shows the portal's tile count (e.g. `"3 tile(s)"`) in dim text.
- **Hover** highlights the row.
- **Click** a portal row to **select that entity in the editor** — this sets `selected_entity`, switches the active tool to Select, and flips the inspector to the Entity tab. The canvas then highlights the selected portal at its tile position, equivalent to clicking the portal on the canvas directly.
- **View-only** — you cannot create or delete portals from this panel. The empty-state hint reads `"No portals."` / `"Use Portal tool"`, directing you to the canvas-based Portal placement workflow (see §16).
- The selected portal row is highlighted with the accent colour matching the canvas selection state.

### 8.5 Room Template Panel

A flat scrollable list of template and room variant files, scanned lazily from the `templates/` and `templates/rooms/` directories.

```
┌──────────────┐
│ ▇ Apartment   │
│   Block       │
├──────────────┤
│ ▇ Warehouse   │
├──────────────┤
│ ▇ Bunker      │
├──────────────┤
│  (empty)     │
└──────────────┘
```

- **Each row** shows a coloured block icon (`▇`) and the template filename, title-cased with underscores replaced by spaces (e.g. `apartment_block.json` → "Apartment Block"). Long names are truncated.
- **Hover** highlights the row.
- **Click** a row — currently shows a toast (`"Template: <filename> (stamp placement TBD)"`). Canvas stamp-placement is **not yet implemented**; this panel is read-only for now.
- **No preview thumbnails**, no add/delete buttons, no search. To create, edit, or delete templates, use the Template Editor overlay (Editors → Room Templates, see §12.2).
- If no templates exist, the panel shows an empty hint: `"No templates."` / `"Editors → Room Templates"`.

### 8.6 Zone Panel

- Lists all JSON zone files in the `zones/` directory (refreshed every 2 seconds).
- The current zone is highlighted with an accent color.
- **Click** a zone name to load it.

---

## 9. Inspector (Right Panel)

Three tabs along the top: **Zone**, **Tile**, **Entity**. The active tab depends on context (selecting a tile switches to Tile tab, selecting an entity switches to Entity tab, etc.). For how inspected fields affect gameplay at runtime (e.g. what `kind` does, how `loot_table` is rolled, how `exit_direction` drives auto-walk), see §27.

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
| **Erase Tile** | Dropdown      | Yes      | Selects which tile the Eraser paints (default: `grass`; see §6 Eraser). **Session-only** — not saved in the zone JSON; resets to `grass` on reload. |

**Entity List** — Below the zone properties, every entity in the zone is listed as a clickable row showing `prefab: name`. Clicking a row selects that entity and switches to the Entity tab.

### 9.2 Tile Tab

Read-only properties for the tile under the cursor or the last-inspected tile.

| Section     | Fields |
|-------------|--------|
| **Header**  | `TILE: <name>` |
| **Properties** | ID, Type (floor/wall/etc.), Category, Flags (solid, wall, transparent, half, platform, liquid, farmland, thin, tall), Height (2 decimal places) |
| **Textures** | Default texture key, Front/Back overrides, per-face overrides (N/S/E/W), Alt texture (tall wall extension) |
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
- **"Add Component…"** button opens the Add Component modal, listing components not yet attached: `collider`, `health`, `tile_entity`, `wall_sprite`, `inventory`, `facing`, `dialogue`, `sprite`, `combat_stats`.
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
| **Scroll wheel** | Cycle through slots |

> ⚠ **Warning:** Number keys (1–9, 0) are shown in the HUD hint but are **intercepted by global shortcuts** (priority 6) before reaching FP fullscreen (priority 11). They select 2D tile palette entries instead of hotbar slots. Use the **scroll wheel** to change hotbar slots.

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
| **Left-click** | **Place tile.** If aiming at a wall and there is an empty (non-wall) cell directly in front of it **from the camera’s perspective**, the tile is placed in that empty cell (wall-building). If the cell in front is also a wall or out of bounds, the aimed cell itself is replaced. If aiming at a floor, the tile is painted onto the aimed cell. Entity positions are not checked — tiles are placed regardless of entities occupying the cell. |
| **Right-click** | **Eyedropper.** Picks the aimed tile into the current hotbar slot. Does **not** capture the cell’s rotation — only the tile ID is copied. To duplicate a rotated tile, eyedrop it and then manually set the rotation with R. |
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

- `collider`, `health`, `tile_entity`, `wall_sprite`, `inventory`, `facing`, `dialogue`, `sprite`, `combat_stats`

**Click** a component to add it with default values. **Esc** to cancel.

### Tile Editor Modal

A full-featured tile creation/editing dialog.

| Field          | Widget                     | Notes |
|----------------|----------------------------|-------|
| Name           | TextField                  | Tile display name |
| Color          | RGB sliders (draggable)    | Base color |
| Type           | Dropdown                   | floor, wall, half_wall, platform, door, liquid |
| Transparent    | Checkbox                   | Extra flag — see-through wall |
| Farmland       | Checkbox                   | Extra flag — tillable soil |
| Thin Wall      | Checkbox                   | Extra flag — mid-cell fence/railing |
| Tall Wall      | Checkbox                   | Extra flag — extends upward with alt texture |
| Sound          | Dropdown                   | Footstep sound category (stone, grass, water, sand, wood, glass, gravel, metal, cloth) |
| Texture key    | TextField                  | PNG asset key |
| Front / Back   | TextFields                 | Directional texture overrides |
| N / S / E / W  | TextFields (2×2 grid)      | Per-face compass texture overrides |
| Alt Tex        | TextField                  | Tall-wall upper extension texture (only effective when Tall Wall is checked) |
| Height scale   | Slider                     | 0.05 – 1.0 |
| Category       | Dropdown                   | Existing categories + "New Category…" |
| Preview        | 64×64 texture thumbnail    | Live preview |

**Buttons:** Update/Create, Duplicate, Delete (edit mode only), Cancel, Import PNG.

> **Tile Editor Modal vs. TOML files**: The Tile Editor modal is a GUI front-end for the TOML definitions in `assets/models/tiles/`. Clicking **Update** (or **Create**) writes the changes to the corresponding `.toml` file **immediately**. All TOML fields are now editable in the modal, including `tall_wall`, `alt_texture`, `thin_wall`, per-face textures (N/S/E/W), and the `sound` dropdown.

---

## 12. Overlay Editors

Full-screen editor overlays that take over the entire window. Open them from the **Editors** menu. Close them to return to the map editor. While an overlay is active, the map editor is not drawn and all events are routed to the overlay.

> **Text fields in overlays work correctly.** Unlike inspector text fields (§25.4), overlay text fields are unaffected by the global shortcut conflict. Overlays consume all events at priorities 2–4, which is *before* global shortcuts at priority 6. Characters like G, R, P, B, E, V, I, and digits can be typed normally into the Loot Table Editor’s inline fields, Entity Forge’s ID/Name/Tags/Texture fields, and the Template Editor’s name dialog.

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

Template `base_tiles` use **string tile IDs** (the same format as zone JSON), despite a legacy docstring in the code claiming integers. The "From Current Zone" import copies string IDs directly from the editor state.

```json
{
  "name": "apartment_block",
  "width": 50,
  "height": 40,
  "base_tiles": [["wall", "wall", ...], ...],
  "slots": [
    { "name": "bedroom_1", "x": 2, "y": 3, "w": 10, "h": 8,
      "tags": ["bedroom"], "required": true }
  ],
  "fixed_entities": [ { "id": "...", "prefab": "...", ... } ],
  "portals": [ ... ]
}
```

> ⚠ **Warning — empty template fallback uses integers.** When creating a template via "+ New Template" (without importing from a zone), the initial `base_tiles` grid is `[]`. The baking algorithm initialises absent base tiles with **integer `0`**, and fills unmatched required slots with **integer `1`**. These are bare integers, not string tile IDs — they do not correspond to any registered tile name and will appear as unknown/fallback tiles in the baked zone. This is a latent type inconsistency. Always use "From Current Zone" to populate base tiles before baking.

#### Room Variant JSON Format

Room variants exported via "Export Room" also use **string tile IDs**, copied directly from the editor’s tile grid.

```json
{
  "name": "cozy_bedroom",
  "tags": ["bedroom"],
  "width": 10,
  "height": 8,
  "tiles": [["wood_floor", "wood_floor", ...], ...],
  "entities": [ { "id": "bed_1", ... } ]
}
```

#### Slot Matching & Baking Algorithm

1. For each slot, gather all room variants whose **tags intersect** the slot's tags.
2. Filter by size: the room's width must be ≤ slot width, and height ≤ slot height.
3. Pick one matching room at random (optionally seeded for reproducibility).
4. Center the room within the slot and paste its tiles over the base grid.
5. Append the room's entities with positions offset by the slot's origin.
6. If no room matches a **required** slot, the slot is filled with **integer `1`** as a placeholder. This is a bare integer, not a string tile ID — baked zones containing unmatched required slots will have type-inconsistent cells that render as unknown/fallback tiles.

#### UI Layout

```
┌────────────────────────────────────────────────────────────┐
│  [Close]  [Save]  [Bake Zone]  ZONE TEMPLATE EDITOR        │
├──────────────┬─────────────────────────────────────────────┤
│ [+ New Tmpl] │  TEMPLATE: apartment_block                  │
│              │                                             │
│ apartment_b… │  [From Current Zone]  [Export Room]          │
│ warehouse  ● │  [Add Slot]                                  │
│ bunker       │                                             │
│              │  SLOTS                                       │
│ ── Rooms ──  │  ┌ slot_0 (2,3 6×6) tags:[] req:✓  [Del] ┐ │
│ cozy_bedrm   │  └────────────────────────────────────────┘ │
│ big_kitchen   │  ┌ slot_1 (10,3 8×8) tags:[] req:✓ [Del] ┐│
│              │  └────────────────────────────────────────┘ │
│              │                                             │
│              │  PREVIEW                                     │
│              │  ┌──────────────────────────────────────┐   │
│              │  │ (base tiles as coloured rectangles   │   │
│              │  │  with slot outlines overlaid)        │   │
│              │  └──────────────────────────────────────┘   │
└──────────────┴─────────────────────────────────────────────┘
```

- **Header bar** — dark strip across the top with **Close**, **Save**, and **Bake Zone** buttons plus the overlay title.
- **Left panel** (≤ 200 px or 1/3 screen) — a **"+ New Template"** button at top, a scrollable list of saved template filenames from `templates/*.json`, and below a separator a **Room Variants** section listing room JSONs from `templates/rooms/`. Click a template name to load it into the right panel. Click a room variant row to **show a toast** with the room’s filename — there is no preview, detail view, or selection action for room variants. They are listed for reference only.
- **Right panel** — the currently loaded template's detail view, or a placeholder (`"No template loaded."`) if nothing is selected.
- **New-template dialog** — a centered 400×100 modal with a text field for the name. Enter = create, Esc = cancel.

#### Adding Slots

Click the **"Add Slot"** button to append a slot with hardcoded defaults:

```python
{"name": "slot_0", "x": 2, "y": 2, "w": 6, "h": 6, "tags": [], "required": True}
```

There is **no drag-to-draw on canvas**. Slots are created with fixed default coordinates and size. Each slot appears as a row in the detail panel showing its name, position, dimensions, tags, and required flag. Click a slot row to select it (highlighted in the list and outlined in the preview). Click **Del** on a row to remove it.

**Slot geometry (x, y, w, h) is not editable in the UI.** There are no sliders, spinners, or text fields for position/size. To adjust slot geometry, edit the template JSON file directly.

#### Editing Base Tiles

There is **no embedded tile palette** in the template editor. The base tile grid is populated via the **"From Current Zone"** button, which snapshots the current zone editor's entire tile grid (and entities/portals) into the template. The intended workflow is:

1. Design the background tilemap in the **main zone editor** (paint, fill, place entities, etc.).
2. Open the Template Editor overlay.
3. Click **"From Current Zone"** to import into the template.

The right panel renders a **mini preview** of the base tiles at the bottom as coloured rectangles (tile ID → hardcoded display colours) with slot outlines overlaid in accent colour.

#### Assigning Tags to Slots

**Tag editing is not yet implemented in the UI.** The code declares a `_tag_field: TextField | None` placeholder that is never instantiated or rendered. Tags default to `[]` on slot creation. To assign tags (needed for slot-matching during baking), edit the template JSON directly:

```json
{ "name": "bedroom_1", "x": 2, "y": 3, "w": 10, "h": 8,
  "tags": ["bedroom", "furnished"], "required": true }
```

#### Actions Summary

| Button | Action |
|--------|--------|
| **Close** | Close overlay, return to map editor |
| **Save** | Write template to `templates/<name>.json` |
| **Bake Zone** | Run baking algorithm → load result as current zone, close overlay |
| **+ New Template** | Open name dialog → create empty template |
| **From Current Zone** | Import map editor's tile grid, entities, and portals as a new template |
| **Export Room** | Export the selected slot’s region (tiles + entities) as a room variant JSON. “Selected” means the slot row last clicked in the detail panel. The file is auto-named `room_{template}_{slotIndex}.json` and written to `templates/rooms/`. No filename prompt. If **no slot is selected**, the click is consumed silently — no toast, no error. |
| **Add Slot** | Append a default 6×6 slot |
| **Del** (slot row) | Delete that slot |
| Slot row click | Select slot (highlight in list + preview outline) |
| Template list click | Load that template |
| Room variant click | Toast with filename (view-only; no preview or selection) |
| Esc | Close overlay |
| Mouse wheel | Scroll the detail panel |

#### Baking Output

Baking does **not** write directly to disk. The baked zone is loaded into the editor’s working state as the current zone (replacing whatever was open). The zone name is set to the template’s name. The baked zone only appears in the `zones/` directory and zone picker **after you manually save** (Ctrl+S). Saving a baked zone whose name matches an existing zone file will **silently overwrite** that file — there is no confirmation dialog.

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
| `extras`         | dict       | Unknown keys preserved verbatim during JSON round-trip. These exist to prevent data loss when a zone file contains entity fields that the current editor version doesn’t understand (e.g., fields added by future game systems or manual JSON edits). Users should not normally add extras manually. If present, they appear as read-only KV rows in the Entity inspector, truncated to 40 characters. |

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

### Placement Lifecycle (Complete Flow)

Entity placement state is described across several sections. Here is the full lifecycle in one place:

1. **Enter placement mode**: Click a prefab in the Entity panel (§8.2) or a forge archetype in the Entity Forge (§12.3). This sets `pending_prefab`, switches the tool to **Select**, and shows a toast with the entity name. If another prefab was already pending, it is silently replaced.
2. **Cursor hint**: While a prefab is pending, a banner appears above the canvas: *"Click to place: EntityName (right-click to cancel)"*. The cursor carries the entity's sprite character.
3. **Place**: Left-click the canvas (Select tool). The entity is created at the clicked tile center with the prefab's default components. An undo snapshot is pushed. `pending_prefab` is cleared.
4. **Cancel**: Right-click or press **Esc** to clear `pending_prefab` without placing. The tool remains on Select.
5. **Tool switch during pending**: Switching tools (B, E, I, V) does **not** cancel the pending prefab — it persists silently. Switching back to Select restores placement mode. Only Esc or right-click explicitly cancels.
6. **Selection persistence**: Selecting an entity remains independent of pending state. You can have a selected entity and a pending prefab simultaneously (the pending prefab takes priority on left-click).

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
tex_n = "mossy_stone_north"
tex_s = "mossy_stone_south"
tex_e = "mossy_stone_east"
tex_w = "mossy_stone_west"

# Optional flags (all default to false if omitted)
transparent = false
thin_wall = false
tall_wall = true
alt_texture = "mossy_stone_upper"
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
|-------------|--------|---------||
| SOLID       | 1 << 0 | Blocks movement |
| WALL        | 1 << 1 | Has wall geometry |
| TRANSPARENT | 1 << 2 | Allows light/sight through walls |
| LIQUID      | 1 << 3 | Liquid surface |
| FARMLAND    | 1 << 4 | Farmable ground |
| HALF_WALL   | 1 << 5 | Half-height wall |
| PLATFORM    | 1 << 6 | Elevated platform |
| THIN_WALL   | 1 << 7 | Mid-cell fence/railing (ray intersects at cell midpoint) |
| TALL_WALL   | 1 << 8 | Extends upward above normal height with alt texture |

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
| tex_n          | str               | `""`        | North-face texture override |
| tex_s          | str               | `""`        | South-face texture override |
| tex_e          | str               | `""`        | East-face texture override |
| tex_w          | str               | `""`        | West-face texture override |
| alt_texture    | str               | `""`        | Tall-wall upper extension texture |
| height_scale   | float             | 1.0         | Wall height multiplier |
| category       | str               | "Terrain"   | Palette grouping |
| sound          | str               | "stone"     | Footstep sound category (see Sound Field below) |

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

#### 2D Canvas Rotation Visibility

In the 2D editor, rotation is **not visually indicated** on placed tiles. All tiles render as unrotated texture swatches regardless of their rotation value. The only visual feedback is the **current pending rotation** displayed in the status bar or toolbar hint when the R key is used. To check a placed tile’s rotation, inspect it in the first-person view where directional textures are rendered correctly.

> **Future improvement**: A rotation arrow overlay on painted tiles would improve 2D editing feedback.

### Built-in Categories

Terrain · Floors · Walls · Openings · Barriers · Platforms · Custom

### Constants

| Constant    | Value | Meaning |
|-------------|-------|---------|
| TILE_SIZE   | 32    | Pixels per tile in the 2D editor |
| TILE_METRES | 1.0   | In-game metres per tile |

### Sound Field

The `sound` field is a string category label selecting which footstep audio to play when the player walks on the tile. Known values (from the Tile Editor dropdown): `stone`, `grass`, `water`, `sand`, `wood`, `glass`, `gravel`, `metal`, `cloth`.

**Current runtime status:** The sound field is fully wired in the data layer — it can be set in TOML files and is editable in the Tile Editor modal via a dropdown selector. However, **no audio system exists yet**. There is no `pygame.mixer` usage anywhere in the codebase. The `_step_phase` variable in the first-person renderer tracks a head-bob footstep timer but is never read for playback. Sound files are expected to live in `assets/sounds/` but this directory does not exist.

The field is pure scaffolding for a future audio system. Setting it has no runtime effect today, but choosing appropriate values future-proofs tiles for when audio is implemented.

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

The `anchor` field specifies the **player spawn point** `[x, y]` in tile coordinates. When the game starts a new session in this zone, the player entity is placed at the anchor position (see §27). Default is `[0, 0]`. The anchor is not currently editable in the editor UI — edit it directly in the JSON if needed. There is no death/respawn system in the current codebase, so the anchor is used **only** for the initial spawn in `new_game()`.

Portals are stored separately from entities for backward compatibility but are treated as entities internally.

### Operations

| Operation       | How to Access | Notes |
|-----------------|---------------|-------|
| **New Zone**    | File → New Zone… | Specify name, width (5–200), height (5–200). Default: 30×20. |
| **Open Zone**   | File → Open Zone… *or* Zone panel *or* zone nav | Loads from `zones/<name>.json` |
| **Save**        | File → Save (Ctrl+S) | Writes to `zones/<name>.json` |
| **Save As**     | File → Save As… | Prompts for new name |
| **Rename**      | File → Rename Zone… *or* Zone tab Name field | Renames the file on disk |
| **Resize**      | Zone tab Width/Height fields | Clamps 5–200. **Anchor: top-left corner.** Existing tiles are preserved from (0,0). The map expands or contracts to the right and bottom edges. New area is filled with `grass` at rotation 0. Entities outside the new bounds are **not** removed. |

### Undo / Redo

- **Depth limit**: 80 snapshots.
- **Snapshot**: Deep copy of the entire tile grid, rotation grid, and entity list.
- **Push**: Every paint, erase, fill, entity place/delete/drag, and resize pushes an undo snapshot. Performing a new action clears the redo stack.
- **Continuous paint (drag)**: A single snapshot is pushed on mouse-down. The entire drag stroke (all tiles painted while the button is held) counts as **one undo operation**.
- **Fill**: One snapshot per fill click.
- **Entity drag**: One snapshot pushed on mouse-up after the drag ends.
- **FP tile placement**: One snapshot per individual tile placed (each click).
- **Inspector field edits**: Changes made in the inspector (renaming, changing kind, adjusting numbers) mark the zone as dirty but do **not** push undo snapshots. These changes are **not undoable**. Only structural operations (Add Component, Delete Entity) push snapshots.
- **Ctrl+Z**: Undo (pops from undo stack, pushes to redo).
- **Ctrl+Y**: Redo (pops from redo stack, pushes to undo).
- **Zone loading**: Loading a new zone (Open, New, zone panel click, nav bar, bake) **destroys the entire undo/redo history**. Both stacks are cleared and a single baseline snapshot of the new zone is pushed. See §25 for details.

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
| **Thin walls** (`THIN_WALL` flag) | The ray intersects at the cell midpoint (0.5 offset) instead of the cell boundary, creating narrow fences or railings that appear centered in the cell. Rays continue through after hitting. |
| **Tall walls** (`TALL_WALL` flag) | After drawing the normal wall, the renderer tiles the `alt_texture` (or default texture) upward from the wall top to the top of the screen. Creates the illusion of tall building facades in exterior areas. |
| **Doors** (`DOOR` type) | Full wall height but **not solid** — the player can walk through them. Rendered with wall textures. |

### Directional Textures on Walls

Each wall tile can have per-face textures: `texture` (default), `texture_front`, `texture_back`, plus per-compass overrides `tex_n`, `tex_s`, `tex_e`, `tex_w`. The per-compass fields take priority over front/back. Which world face maps to "front" or "back" depends on the tile's **rotation**:

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

Entities with a `WallSprite` component are rendered as **free-standing textured rectangles** in 3D space. Despite the name, they are **not attached to any specific wall surface**. The entity’s `Position(x, y)` determines where the rectangle appears in the world, and the `WallSprite` fields control its dimensions:

| Field | Effect |
|-------|--------|
| `texture_key` | Atlas key for the rectangle’s texture. Falls back to entity’s sprite color if empty. |
| `width` | World-space width in tiles (1.0 = full tile) |
| `height` | World-space height in tiles (1.0 = full wall height) |
| `elevation` | Vertical offset from the floor (0.0 = ground level). If the entity is on a platform tile and elevation is 0, the platform’s `height_scale` is used automatically. |

WallSprite entities are rendered using the same raycasting-column technique as tile walls, with per-column z-buffer depth testing. They always face the camera (billboard-style orientation).

**Placement on floor tiles**: A WallSprite entity placed on an open floor with no adjacent walls renders normally — it appears as a floating textured rectangle. There is no requirement for an adjacent wall. Common uses: free-standing signs, pillars, barricades, shelving units.

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
6. **Build in FP**: Use the **scroll wheel** or **T** (tile picker) to select hotbar tiles. Left-click to place, right-click to eyedrop, middle-click to erase.
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

> ⚠ **Warning (FP conflict):** In FP fullscreen, number keys are intended to select hotbar slots, but global shortcuts (priority 6) intercept them first. Numbers always select from the 2D tile palette. Use the scroll wheel to change hotbar slots in FP.

### First-Person Shortcuts (Fullscreen)

> ⚠ **Warning:** Many single-key shortcuts listed below are **intercepted by the global shortcut handler** (priority 6) and never reach the FP fullscreen handler (priority 11). See §25.3 for the full audit of which keys actually work as expected in FP fullscreen.

| Shortcut    | Action |
|-------------|--------|
| W/A/S/D     | Move |
| Shift       | Sprint |
| Mouse       | Look (horizontal) |
| Left-click  | Place tile |
| Right-click | Eyedropper |
| Middle-click| Erase tile |
| Scroll      | Cycle hotbar slot |
| T           | Open tile picker |
| R           | Rotate tile |
| C           | Toggle noclip |
| Ctrl+Z      | Undo |
| Ctrl+Y      | Redo |
| Tab         | Switch to PIP |
| Esc         | Exit to PIP |

> ⚠ **Warning:** Number keys (1–9, 0) are listed in some tooltips as hotbar selectors, but they are intercepted by the global shortcut handler and select 2D tile palette entries instead. Use the scroll wheel to change hotbar slots.

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

## 21. Event Priority

When multiple UI elements overlap, events are consumed in this priority order (first handler that accepts the event wins). See §25 for detailed analysis of edge cases, text field focus conflicts, and FP event pass-through.

1. QUIT signal
2. Entity Forge overlay
3. Loot Table Editor overlay
4. Template Editor overlay
5. Modal dialogs
6. Global keyboard shortcuts (Ctrl+S/Z/Y, G, M, P, F, R, B, E, V, I, `[`, `]`, Del, Esc, 0–9)
7. Menu bar dropdowns (blocks all mouse events when open)
8. Zone navigation bar
9. Toolbar
10. Panel splitter drag handles
11. FP fullscreen (consumes movement, hotbar, tile ops; unhandled keys fall through)
12. Panel tabs
13. Left panel content
14. Inspector
15. FP PIP mode
16. Canvas

---

## 22. Status Bar

The status bar sits at the very bottom of the window.

| Section | Content |
|---------|---------|
| Left    | Hover info: `(col, row) tile=id(name) WxH z=Zoom ent=EntityName`. The `ent=` field shows the entity **under the cursor** (nearest within 0.7 tile radius) and only appears when the **Select** tool is active. It does not show the currently *selected* entity — only the one under the mouse pointer. |
| Center  | Toast messages (fade after a few seconds) |
| Right   | Keyboard hints: `^S ^Z ^Y  G:Grid M:Map [:- ]:+ F:FP` |

---

## 23. Project Directory Structure

All paths are defined in `core/paths.py` — the single source of truth.

```
assets/                          # Client-side resources (art, audio, FX)
  textures/
    tiles/                       # 64×64 PNGs, one per tile texture key
  sounds/                        # Sound effects (placeholder — dir does not exist yet)
  models/
    tiles/                       # Tile definitions (one .toml per tile)
  particles/                     # Particle effect definitions
  lang/                          # Localization / string tables

data/                            # Game data definitions (all TOML)
  tuning.toml                    # Game tuning constants (combat, physics, detection).
                                 #   ACTIVE: hot-reloaded at runtime via F4.
  items.toml                     # Item templates (weapons, consumables, armor).
                                 #   ACTIVE: used by game + editor (loot dropdown).
  loot_tables.toml               # Weighted loot pools for containers.
                                 #   ACTIVE: used by game + editor (Loot Table Editor).
  custom_entities.toml           # Entity Forge archetype output.
                                 #   ACTIVE: written by editor, read by Entity Panel.
  custom_tiles.toml              # Editor-created tile definitions (nearly empty).
                                 #   VESTIGIAL (mislabelled as ACTIVE in prior revisions).
                                 #   `load_custom_tiles()` is a no-op; the Tile Editor
                                 #   reads and writes individual TOMLs in
                                 #   `assets/models/tiles/` exclusively. This file is
                                 #   never loaded by any code path.
  characters.toml                # NPC/character archetypes with brains, factions.
                                 #   VESTIGIAL: referenced in paths.py but never loaded.
  population_presets.toml        # Zone population spawning rules.
                                 #   VESTIGIAL: not imported by any code.
  subzones.toml                  # World topology graph (zones, connections).
                                 #   VESTIGIAL: not imported by any code.
  room_types.toml                # Room type definitions for BSP generation.
                                 #   VESTIGIAL: not imported by any code.
  portals.toml                   # Inter-zone portal definitions.
                                 #   VESTIGIAL: not imported by any code.
                                 #   Actual portals are embedded in zone JSON files.

zones/                           # Zone map files (JSON)
templates/                       # Editor templates
saves/                           # Save game slots
logs/                            # Performance logs
```

> **Note:** The `data/` subdirectories listed in `core/paths.py` (`functions/`, `tags/`, `predicates/`, `recipes/`, `structures/`) **do not exist on disk**. They are path constants defined for a future crafting/scripting system that has not been implemented.

---

## 24. Texture Atlas

The **texture atlas** is an in-memory dictionary of 64×64 `pygame.Surface` objects, one per tile ID or texture key. It is **not** a single stitched image on disk — each texture is a separate PNG file loaded and cached on demand.

### How the Atlas Works

| Aspect | Behavior |
|--------|----------|
| **Data structure** | `TextureAtlas._surfaces: dict[str, pygame.Surface]` |
| **Loading** | **Lazy per-tile.** A texture is loaded from disk the first time `atlas.get(tile_id)` is called. |
| **Eager preload** | The game's `Renderer` calls `atlas.ensure_all()` at startup, which iterates every tile in `TILE_REGISTRY` and loads all textures upfront. The editor does **not** preload — it loads textures on first use. |
| **Invalidation** | `atlas.invalidate(tile_id)` drops the cached surface. The next `get()` re-loads from disk. Used after texture import or tile editing. |
| **Rebuild** | There is no full rebuild trigger. Individual entries are re-loaded on demand. |
| **Resolution** | Every texture is exactly 64×64 pixels (`TEX_SIZE = 64`). Images of other sizes are scaled on load. |

### Atlas Methods

| Method | Input | Returns | Description |
|--------|-------|---------|-------------|
| `get(tile_id)` | Tile ID string | 64×64 Surface | Resolves the tile's `texture_key` via the tile registry, loads `assets/textures/tiles/{key}.png`. Falls back to a solid-colour surface using the tile's `color` field. |
| `get_by_key(key)` | Raw texture key | 64×64 Surface | Loads `assets/textures/tiles/{key}.png` directly (no registry lookup). Falls back to solid grey (80, 80, 80). Used for per-face texture overrides. |
| `invalidate(tile_id)` | Tile ID string | — | Drops cached surface so next `get()` re-loads from disk. |
| `sample(tile_id, u, v)` | Tile ID, UV coords | (r, g, b) | Returns the pixel colour at normalised UV. Used for floor/ceiling rendering. |
| `ensure_all()` | — | — | Eagerly loads every tile in the registry. |

### Tile ID vs. Texture Key vs. Filename Stem

These three concepts are related but distinct:

| Concept | Definition | Example |
|---------|-----------|---------|
| **Tile ID** | The unique identifier for a tile definition. Equals the filename stem of its TOML file in `assets/models/tiles/`. | `mossy_stone` |
| **Texture key** | The PNG filename stem used for the tile's wall/face texture. Stored in `TileDef.texture_key`. If blank, falls back to the tile ID. | `mossy_stone_front` |
| **Filename stem** | The name of any PNG in `assets/textures/tiles/` (without `.png`). | `mossy_stone_front` |

**Key relationships:**

- A tile ID **does not need to match** its texture key. A tile called `fancy_wall` can use `texture_key = "brick"` to reuse the brick texture.
- **Multiple tiles can share one texture key.** Both `brick_wall` and `old_brick_wall` can set `texture_key = "brick"`. Each gets its own cached surface in the atlas (keyed by tile ID), but both load the same PNG.
- When importing a texture (Export → Import Texture…), the PNG is stored at `assets/textures/tiles/{stem}.png`. You then assign the filename stem as a texture key on any tile(s) that should use it.
- Per-face overrides (`texture_front`, `texture_back`) are raw texture keys resolved via `atlas.get_by_key()`, not tile IDs.

### Missing Texture Fallback

| Scenario | Fallback |
|----------|----------|
| `get(tile_id)` — PNG not found | Solid-colour surface using the tile's `color` field from the registry |
| `get(tile_id)` — tile not in registry | Solid grey (80, 80, 80) |
| `get_by_key(key)` — PNG not found | Solid grey (80, 80, 80) |
| Entity billboard — no texture match | Font-rendered glyph of the sprite character |

### Import Texture Workflow (Detailed)

1. **Export → Import Texture…** opens a file browser (tkinter `askopenfilename`).
2. Accepted formats: `.png`, `.jpg`, `.jpeg`, `.bmp`, `.gif`, `.tga`.
3. The image is loaded, **smooth-scaled to 64×64**, and saved as a PNG to `assets/textures/tiles/{filename_stem}.png`.
4. The atlas picks up the new file the next time `get()` or `get_by_key()` is called for that key.
5. To use the imported texture: open the Tile Editor (right-click a tile), set the **Texture key** field to the imported file's stem.

### String IDs and C Extension Performance

Tile IDs are human-readable strings everywhere in the editor and game code. For performance-critical rendering paths (DDA raycasting, wall geometry computation), the engine maintains an automatic **string ↔ integer mapping** (`core/tiles.py`). Conversion happens at the C-extension boundary:

1. `cast_walls()` — the C raycaster works with an integer tile grid. After casting, integer tile IDs are converted back to strings in the returned `WallSlice` data.
2. `draw_walls()` — before calling the C geometry extension, string IDs are converted to ints via `tile_str_to_int()`. After computation, results are converted back via `tile_int_to_str()`.

This mapping is built automatically when tiles are registered and requires no user action. The editor and all game systems use string IDs exclusively.

---

## 25. Editor State Machine & Event Routing

### 25.1 Modes & Transitions

#### Major Editor Modes

The editor uses compositional boolean flags rather than a formal state machine. These are the major modes:

```
┌─────────────────────────────────────────────┐
│              NORMAL 2D EDITING               │
│  (canvas, panels, inspector all active)      │
├──────────────┬──────────────────────────────┤
│              │                              │
│   FP PIP     │   FP FULLSCREEN              │
│   (passive   │   (mouse grabbed,            │
│    preview)  │    full editing controls)     │
│              │                              │
├──────────────┴──────────────────────────────┤
│         OVERLAY EDITORS                      │
│  (Entity Forge / Loot Tables / Templates)    │
│  Takes over the entire window.               │
│  Map editor is not drawn.                    │
├─────────────────────────────────────────────┤
│         MODAL DIALOGS                        │
│  (New Zone / Open Zone / Text Input /        │
│   Tile Editor / Add Component)               │
│  Darkened overlay. Map is still visible.      │
└─────────────────────────────────────────────┘
```

#### Mode Transitions

```
Normal 2D ──P──→ FP PIP ──Tab/F──→ FP Fullscreen
  ↑                ↑ Esc               │ Esc
  │                └───────────────────┘
  │
  ├── Editors menu ──→ Overlay (Forge / Loot / Template)
  │                        │ Close button
  │                        ↓
  │                     Normal 2D
  │
  ├── Various actions ──→ Modal Dialog
  │                         │ Esc / Enter / confirm
  │                         ↓
  └─────────────────── Normal 2D
```

**Critical rule — overlays suppress everything else.** When an overlay is active:
- The map editor, canvas, panels, and inspector are **not drawn**.
- FP PIP remains technically active (`fp_preview.active` is still `True`) but receives no events and is not rendered. It resumes when the overlay closes.
- FP Fullscreen similarly remains in its `fullscreen=True` state but is completely frozen — no events, no rendering. The mouse grab (`set_grab(True)`) **remains active**, which is a latent bug: if an overlay could be opened from FP fullscreen, cursor interaction with the overlay would be broken. In practice, overlays are opened from the menu bar, which requires mouse clicks that are unreachable while the mouse is grabbed (see below).
- Modals cannot be opened from within overlays (no code path reaches `modals.open()`).

**Modals are drawn on top of the map.** When a modal is active:
- The map, canvas, FP PIP, and all panels are still **drawn** (behind the darkened overlay).
- All input events are consumed by the modal — nothing reaches any layer below.

### 25.2 Event Priority (Detailed)

Events are processed by `_handle_events()` in a strict linear priority. The **first handler that accepts** an event (returns `True` or continues) wins. No subsequent handler sees that event.

| Priority | Handler | Accepts | Passes Through |
|----------|---------|---------|----------------|
| 1 | **QUIT signal** | Always | — |
| 2 | **Entity Forge overlay** (if active) | All events | Nothing |
| 3 | **Loot Table Editor** (if active) | All events | Nothing |
| 4 | **Template Editor** (if active) | All events | Nothing |
| 5 | **Modal dialog** (if active) | All events | Nothing |
| 6 | **Global keyboard shortcuts** | Matching key combos (Ctrl+S, Ctrl+Z, Ctrl+Y, G, M, P, F, R, B, E, V, I, `[`, `]`, Delete, Esc, 0–9) | Unmatched keys |
| 7 | **Menu bar** | Clicks on menu area; all mouse events when a dropdown is open | Events outside menu area when closed |
| 8 | **Zone navigation bar** | Clicks on nav elements | Events outside nav bar |
| 9 | **Toolbar** | Clicks on tool buttons | Events outside toolbar |
| 10 | **Panel splitter handles** | Drag events on splitter regions | Events elsewhere |
| 11 | **FP Fullscreen** (if active) | All remaining events (WASD, mouse, hotbar, etc.) | Unhandled keys fall through |
| 12 | **Panel mode tabs** | Clicks on tab buttons | Events elsewhere |
| 13 | **Left panel content** | Clicks/scrolls within panel area | Events outside |
| 14 | **Inspector** | Clicks/scrolls within inspector area | Events outside |
| 15 | **FP PIP** (if active) | Movement keys (WASD, arrows), Esc, Tab. **Keyboard only — no mouse interaction.** Mouse clicks on the PIP rectangle fall through to the canvas (priority 16). | All mouse events; unmatched keys |
| 16 | **Canvas** | All remaining mouse events on the map area | — |

#### Ctrl+S / Ctrl+Z / Ctrl+Y in FP Fullscreen

These shortcuts are handled at priority **6** (global shortcuts), which is **before** FP fullscreen at priority **11**. Therefore Ctrl+S, Ctrl+Z, and Ctrl+Y **always work** regardless of FP mode. FP fullscreen also handles Ctrl+Z and Ctrl+Y internally (calling `state.undo()`/`state.redo()` directly), but the global handler catches them first.

### 25.3 FP Shortcut Audit

#### Global Shortcuts vs. FP Fullscreen (Full Audit)

Because global shortcuts (priority 6) fire before FP fullscreen (priority 11), **all single-key shortcuts are processed by the global handler**, and the FP fullscreen handler never sees them. This produces several surprising or nonsensical results:

| Key | Global Handler Effect | FP Fullscreen **Would** Do | Who Wins | Consequence |
|-----|----------------------|---------------------------|----------|-------------|
| **P** | `toggle()` — sets `active=False`, `fullscreen=False`, calls `_ungrab()` | Never reached | Global | **Abruptly exits both fullscreen and PIP entirely.** Does not toggle PIP; destroys all FP state. |
| **F** | `_do_fp_edit()` | Never reached | Global | **No-op** — guarded by `if not fullscreen`, which is already False. |
| **G** | Toggles `show_grid` | Never reached | Global | Grid toggles in 2D (invisible in FP). No visual indication. |
| **M** | Toggles `show_minimap` | Never reached | Global | Minimap toggles in 2D (invisible in FP). No visual indication. |
| **B** | Sets tool to BRUSH | Never reached | Global | Tool changes in editor state (meaningless in FP but state mutates). |
| **E** | Sets tool to ERASER | Never reached | Global | Same — mutates state silently. |
| **V** | Sets tool to SELECT | Never reached | Global | Same. |
| **I** | Sets tool to FILL | Never reached | Global | Same. |
| **R** | Cycle pending rotation | Cycle pending rotation | Global | Works as expected in both contexts — rotation applies to FP placement. |
| **0–9** | Select Nth tile from sorted TILE_REGISTRY, switch to Brush | Select hotbar slot (1–9→slot 0–8, 0→slot 9) | **Global** | **Number keys select from the 2D tile palette, NOT the FP hotbar.** Hotbar slots can only be changed via the **scroll wheel** in FP fullscreen. The keyboard-based hotbar selection code in `_handle_fullscreen_key()` is unreachable. |
| **Delete** | Delete selected entity | Never reached | Global | Deletes whatever entity is selected in editor state (if any). |
| **Esc** | Cancel pending placement | Exit fullscreen → PIP | Global | **Cancels placement OR exits fullscreen** depending on whether a placement is pending. If no placement pending, the event falls through and FP fullscreen’s Esc handler exits to PIP. |

> ⚠ **Warning — two-press Esc sequence:** If you have a pending entity/tile placement while in FP fullscreen, the first Esc cancels the placement (global handler, priority 6) and the second Esc exits fullscreen to PIP (FP handler, priority 11). This is a common user flow that feels like "Esc doesn’t work" on the first press.
| **[** / **]** | Brush size adjust | Never reached | Global | Brush size changes (irrelevant in FP). |

> ⚠ **Warning:** While in FP fullscreen, avoid pressing P (kills FP entirely), G, M, B, E, V, I (silently mutate 2D state), and 0–9 (select 2D tiles instead of hotbar). Only WASD, Shift, T, C, R, mouse, scroll wheel, Ctrl-modified keys, Tab, and Esc behave as expected.

#### FP Fullscreen vs. Menu Bar (Mouse Grab Conflict)

FP fullscreen calls `pygame.event.set_grab(True)` and `pygame.mouse.set_visible(False)`. The cursor is invisible and confined to the window. The menu bar handler runs at priority 7 (before FP fullscreen at 11) and **theoretically** has a chance to process mouse clicks — but since the cursor is invisible and mouse events are treated as mouselook deltas, the user **cannot practically click the menu bar**. This means:

- **Overlays cannot be opened** from FP fullscreen (they require menu bar clicks).
- **Modal dialogs cannot be opened** from FP fullscreen (no keyboard shortcut opens one).
- The only way to interact with chrome is to **exit fullscreen first** (Esc → PIP → Esc → Normal 2D).
- The priority ordering of menu bar > FP fullscreen is academic for mouse events — the grab makes it unreachable.

**Zone loading cannot occur while in FP fullscreen.** The Zone Panel, Zone Navigation Bar, and File → Open Zone all require mouse clicks on chrome that is unreachable while the mouse is grabbed. No keyboard shortcut loads zones. Exit to Normal 2D first (Esc → PIP → Esc).

#### FP PIP Mouse Events & Focus Model

The PIP is a passive preview rendered as a surface blit in the top-right corner of the canvas. It has **no mouse interaction**:

- **Click events on the PIP rectangle fall through to the canvas.** Clicking where the PIP is displayed will paint/select on the tile underneath it — the PIP does not intercept mouse events.
- **WASD is always-on** when PIP is active. The FP PIP handler (priority 15) consumes WASD/arrow keys regardless of mouse position or focus state. There is no click-to-focus gating — WASD always moves the FP camera and those keystrokes never reach the canvas.
- This means WASD cannot be used for any 2D-mode function while PIP is active (there are currently no WASD bindings in 2D mode, so this is not a conflict in practice).

### 25.4 Text Field & Input Conflicts

#### Text Field Focus & Shortcut Conflicts

The inspector uses `UIContext.focused_id` to track which text field has keyboard focus. When a text field is focused, the field captures typed characters for editing.

**Known limitation:** Global keyboard shortcuts (priority 6) are processed **before** the inspector (priority 14). This means single-key shortcuts (G, R, P, F, B, E, V, I, 0–9, `[`, `]`) **fire even when a text field is focused**. For example, typing "grass" in a name field would trigger G→grid toggle, R→rotation. Only keys without shortcut bindings (A, C, D, H, J, K, etc.) pass through to the text field normally.

**Practical impact:** Inspector text fields are **partially unusable** for values containing shortcut-bound characters. The characters G, R, P, F, B, E, V, I, and digits 0–9 cannot be typed into text fields — they are intercepted as shortcuts before reaching the field. There is **no workaround** within the editor UI. To enter values containing these characters, edit the zone JSON or TOML file directly.

#### Tool Switching Side Effects

| State | Preserved on Tool Switch? | Cleared By |
|-------|--------------------------|------------|
| `pending_prefab` | **Yes** — persists across tool switches | Esc, right-click, or successful placement |
| `selected_entity` | **Yes** — preserved | Clicking empty tile, right-click, or deleting entity |
| `entity_dragging` | **Yes** — not cleared | Mouse-up only |
| `pending_rotation` | **Yes** — preserved | Only changes via R key |

### 25.5 Entity Drag Edge Cases

#### Entity Drag Interruptions

Entity drag state (`entity_dragging`) is set on mouse-down and cleared on mouse-up. If the mouse-up is consumed by another handler (e.g., a modal opens during a drag), the drag flag remains `True` and the entity will continue following the mouse after the modal closes. There is no timeout or guard that auto-clears the drag state.

**Reachability assessment:** This bug is **practically unreachable** in the current codebase. During an entity drag the left mouse button is held down, preventing menu bar clicks. No keyboard shortcut opens a modal or overlay. The only keys that fire during a drag are tool switches (V, B, E, I via global shortcuts), which change `state.tool` but do not open modals. The drag-interrupt scenario would require a code change that introduces a keyboard-triggered modal.

#### Entity Drag off Zone Bounds

When dragging an entity past the zone boundary, the entity position **stops updating** — it stays at its last valid tile position. The `screen_to_tile()` function returns `None` for out-of-bounds coordinates, and the drag handler skips the position update when `hover_tile` is `None`. The entity is **not clamped**, **not deleted**, and **not snapped** — it simply freezes in place until the cursor re-enters the zone area.

Entities **cannot be placed at negative coordinates or beyond zone bounds** via dragging. However, the entity position field is a floating-point coordinate that is not validated programmatically — if you edit position values directly in the inspector (or the zone JSON), out-of-bounds values are accepted without error.

### 25.6 State Persistence & Loading

#### Overlay Close → State Restoration

When an overlay (Entity Forge, Loot Table Editor, Template Editor) is closed, the editor state is **preserved but not refreshed**:

| State | Preserved? | Notes |
|-------|-----------|-------|
| Selected entity | **Yes** | `selected_entity` index is untouched |
| Active tool | **Yes** | `tool` is untouched (exception: if forge placement begins, tool changes to SELECT) |
| Pending prefab | **Yes** | Persists unless cleared by Esc/placement |
| Pending rotation | **Yes** | Unchanged |
| Dirty flag | **Yes** | If the zone was dirty before, it’s still dirty |
| Entity Panel cache | **Stale** | The Entity Panel uses a lazy cache (`_ensure_cache()`) that is **not invalidated** on overlay close. If you create/edit/delete archetypes in the Entity Forge, the panel will show stale data. The `refresh()` method exists but is **never called by any code path** — not by overlay close, not by tab switching, not by zone loading. The only recovery is **restarting the editor**. **Known bug.** |
| FP Preview | **Yes** | `active` and `fullscreen` flags are unchanged. If FP was in PIP mode, it resumes. |
| Undo history | **Yes** | Unchanged by overlay operations |

#### Zone Loading Clears Undo

**Loading a new zone destroys the entire undo/redo history.** The `load_zone()` method calls `history.clear()` (empties both undo and redo deques) and then pushes a single baseline snapshot of the newly loaded zone. This applies to:

- File → Open Zone
- Zone Panel clicks
- Zone Navigation Bar tab clicks and ◀/▶ buttons
- File → New Zone (also clears history)
- Baking a template (loads the result as the current zone)

Combined with the lack of an unsaved-changes dialog, navigating away from a zone is a **one-click, irreversible** operation that discards both unsaved edits and undo history.

#### FP Camera State on Zone Load

**The FP camera position and angle are not reset when a zone is loaded.** Neither `load_zone()` nor `new_zone()` touches the FP preview’s `px`/`py`/`angle` fields. The camera is only positioned on **initial FP activation** (P or F key), which syncs it to the zone centre via `sync_to_anchor((map_w/2, map_h/2))`.

If PIP is active and you load a different zone (via zone panel, nav bar, etc.), the PIP camera stays at its old coordinates — potentially out of bounds on the new, differently-sized map. The PIP will show void/garbage until you toggle FP off and back on (P twice) to re-sync the camera.

#### FP PIP Tick Behaviour During Overlays & Modals

The editor’s `_update(dt)` method runs `fp_preview.update(dt, ...)` unconditionally whenever `fp_preview.active` is True. There is **no guard** checking for active overlays or modals. This means:

- **During overlays** (Forge, Loot, Template): FP `update()` still ticks. If any movement keys were held when the overlay opened, `_keys_held` retains them and the camera **drifts continuously** at `dt`-scaled speed. The drift is invisible (FP is not drawn during overlays) but the camera position diverges. On overlay close, the PIP resumes at the drifted position. **Workaround:** Toggle FP off and back on (press P twice) to re-sync the camera to the zone centre — see “FP Camera State on Zone Load” above.
- **During modals**: FP `update()` still ticks **and** FP PIP is still drawn (modals don’t suppress drawing). However, modal input consumption prevents new keys from reaching FP, so only previously-held keys could cause drift.
- **No physics or other dt-based processing** runs in `update()` beyond WASD movement and keyboard turning, so the only side effect is camera position/angle drift.

#### Unsaved Changes Warning

**There is no confirmation dialog** when loading a new zone with unsaved changes. Clicking a zone in the Zone panel, clicking a connected zone tab in the nav bar, pressing ◀/▶, or using File → Open Zone all load immediately. The `dirty` flag (asterisk in the nav bar) is tracked but never checked before loading. **Save before navigating** to avoid data loss.

---

## 26. Error Behavior

The editor handles error cases with toast messages rather than modal dialogs. Here is how each common error is handled:

### Zone Operations

| Scenario | Behavior |
|----------|----------|
| **Save with no name** | Toast: "No zone name set". Save is aborted. |
| **Save with name** | Writes to `zones/{name}.json`. If file already exists, it is **silently overwritten**. |
| **Open nonexistent zone** | Toast: error message. Zone state is unchanged. |
| **Open corrupt zone JSON** | Toast: error message. Zone state is unchanged. |
| **New zone with empty name** | Name is sanitised to `"untitled"` (path traversal chars stripped, spaces collapsed). |
| **New zone with invalid dimensions** | NumberField enforces 5–200 range; out-of-range values are clamped. |

### Entities

| Scenario | Behavior |
|----------|----------|
| **Place entity outside zone bounds** | No validation — the entity is placed at the specified floating-point coordinates. In-game, it renders in the void (no collision, may be invisible depending on raycaster clipping). |
| **Delete with nothing selected** | Delete key is silently ignored (no toast, no error). |
| **Duplicate entity ID** | No validation — multiple entities can share an ID. The game may behave unpredictably with duplicate IDs. |

### Portals

| Scenario | Behavior |
|----------|----------|
| **Portal target zone doesn't exist** | No editor-side validation. At runtime, when triggered: the screen fades to black, a console error is logged (`"Teleport failed — cannot load '{zone}'"`) , and the player fades back into the current zone. No in-game error message is shown. |
| **Portal target coords outside target zone** | No validation. The player spawns at the specified coordinates regardless. |

### Textures

| Scenario | Behavior |
|----------|----------|
| **Import non-64×64 PNG** | Handled gracefully — the image is **smooth-scaled to 64×64** automatically during import. Any size works. |
| **Import unsupported format** | Raises an error shown in the import modal: only `.png`, `.jpg`, `.jpeg`, `.bmp`, `.gif`, `.tga` are accepted. |
| **Import corrupt/unloadable image** | Error message shown in the import modal with the Pygame error detail. |
| **Reference nonexistent texture key** | Falls back to solid-colour surface (see §24 Missing Texture Fallback). |

### Tile Operations

| Scenario | Behavior |
|----------|----------|
| **Create tile with duplicate ID** | The existing tile definition is overwritten. |
| **Delete tile that's in use on maps** | No validation — the tile is removed from the registry. Zones referencing it will show the ID as an unknown tile (rendered as fallback colour). |

---

## 27. Game Runtime Context

This section explains how the game uses the data produced by the editor, providing context for why certain fields are configured the way they are.

### Zone Loading at Startup

The game's starting zone is **hardcoded** to `"playground"` in `core/session.py`. When a new game begins:

1. `Session.new_game("playground")` is called.
2. `load_zone("playground")` reads `zones/playground.json`, parsing tiles, rotations, portals, and entities.
3. The player entity is spawned at the zone's **anchor** position (`"anchor": [x, y]` in the JSON, default `[15.0, 15.0]`).
4. Zone entities are spawned via `spawn_zone_entities()` using the entity descriptors from the JSON.

There is no "spawn point" entity — the JSON `anchor` field **is** the spawn point.

### How Portals Work at Runtime

1. **Each frame**, the session checks if the player's tile position matches any portal in the current zone's `_portal_map` (a dict of `(row, col) → (target_zone, target_row, target_col, exit_direction)`).
2. If a match is found, a **fade-out** transition begins (~0.5 second black screen).
3. Once fully faded, the target zone is loaded and the player is teleported to `(target_col + 0.5, target_row + 0.5)` — centered in the target tile.
4. A **fade-in** transition reveals the new zone.
5. An **auto-walk** sequence moves the player ~1.5 tiles in the `exit_direction` over 0.6 seconds. Player input is locked during the auto-walk.
6. A **portal arrival suppression** flag prevents the player from immediately triggering the destination portal (cleared once they step off the arrival tile).

If the target zone file doesn't exist, the teleport silently fails: the screen fades to black, a console error is logged, and the player fades back into the original zone.

### How Entities Spawn

When a zone is loaded for the first time in a session, `spawn_zone_entities()` creates ECS entities from the zone's entity descriptors. Each entity descriptor (from the JSON `"entities"` array) is passed to `spawn_from_descriptor()` which:

1. Looks up the prefab defaults from `spawner.py`'s prefab registry.
2. Creates an ECS entity with `Position`, `Identity`, `Sprite`, and any other components defined by the prefab.
3. Applies overrides from the descriptor (name, kind, position, inventory, etc.).

Subsequent visits to the same zone in the same session **do not re-spawn** entities — their state is preserved in the ECS world.

### How Zone Data Maps to Gameplay

| Editor Field | Runtime Effect |
|-------------|---------------|
| `first_person` flag | Determines whether the zone uses the first-person or top-down renderer |
| `anchor` | Player spawn position on new game (initial spawn only — no death/respawn system exists) |
| `tiles` grid | Determines walkability (SOLID flag), wall rendering, floor textures |
| `rotations` grid | Controls directional texture mapping (which face is "front") |
| `sound` (tile field) | **No runtime effect** — scaffolding for a future footstep audio system (see §14) |
| Portal `target_zone` | Which zone file to load on teleport |
| Portal `exit_direction` | The direction the player auto-walks after arriving |
| Entity `kind` | Determines AI behavior (npc → dialogue, beast → hostile, container → lootable) |
| Entity `loot_table` | Which table in `data/loot_tables.toml` is rolled when the player opens the container |
| Entity `health` | Whether the entity can be damaged and destroyed |
| Entity `dialogue.bark` | The text shown when the player interacts with an NPC |

---

*This manual reflects the current state of the editor codebase. Keep it updated as features change.*
