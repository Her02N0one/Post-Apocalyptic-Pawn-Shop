# Editor Module Reference

> **Post-Apocalyptic Pawn Shop — Zone Editor**
>
> Comprehensive API reference for the `editor/` package.
> Covers every public class, function, constant, data structure,
> inter-module connection, and key implementation detail.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [editor/ (top-level)](#2-editor-top-level)
3. [editor/app/](#3-editorapp)
4. [editor/app/panels_pkg/](#4-editorapppanels_pkg)
5. [editor/commands/](#5-editorcommands)
6. [editor/view_3d/](#6-editorview_3d)

---

## 1. Architecture Overview

### Technology Stack

| Layer | Technology |
|-------|-----------|
| Window / Input | pygame 2 |
| GL compositing | OpenGL (fullscreen-quad blit of pygame surfaces) |
| Immediate-mode UI | pyimgui (imgui) with `PygameRenderer` |
| 3D rendering | Software rasteriser on pygame `Surface` (projected polygons, no GPU shading) |
| Data format | TOML (entity/tile defs, items, loot), JSON (zone files, session, saves) |

### Composition Model

The editor is split into two main composite classes, each assembled from
many mixins via multiple inheritance:

```
ZoneEditorApp            (editor/app/app.py)
  ├── PanelsMixin        (panels_pkg/__init__.py)
  │     ├── MenuBarMixin
  │     ├── ToolboxMixin
  │     ├── InspectorMixin
  │     └── OverlaysMixin
  ├── DialogsMixin
  ├── ViewportMixin
  ├── RaycasterMixin
  ├── EventsMixin
  ├── AssetBrowserMixin
  ├── DataViewersMixin
  ├── EntityCreatorMixin
  ├── EntityTexturesMixin
  └── DialogPropertyBridge

Zone3DEditor             (editor/view_3d/editor.py)
  ├── RenderingMixin     (rendering.py)
  ├── DrawPrimitivesMixin(primitives.py)
  ├── GeometryMixin      (geometry.py)
  ├── UndoMixin          (undo.py)
  ├── SaveMixin          (save.py)
  ├── SculptMixin        (tools_sculpt.py)
  ├── PaintMixin         (tools_paint.py)
  ├── FillMixin          (tools_fill.py)
  ├── EraseMixin         (tools_erase.py)
  ├── SelectMixin        (tools_select.py)
  ├── SegmentMixin       (tools_segment.py)
  ├── StampMixin         (tools_stamp.py)
  ├── EntityMixin        (tools_entity.py)
  ├── BoxMixin           (tools_box.py)
  ├── Layer2Mixin        (tools_layer2.py)
  ├── QuadMixin          (tools_quad.py)
  ├── PortalMixin        (tools_portal.py)
  ├── CurveMixin         (tools_curve.py)
  └── OverlayWallMixin   (tools_overlay.py)
```

### Key Patterns

| Pattern | Description |
|---------|-------------|
| **Input Stack** | Priority-ordered `InputStack` of `InputContext` objects. Events dispatch top→bottom; a context can block propagation. |
| **Command Bus** | `CommandBus` dispatches frozen `Command` dataclasses to registered handler functions. Manages undo snapshots. Phase 0 = incremental adoption wrapping existing mixin methods. |
| **Event Bus** | `EventBus` (pub/sub) emits typed event dataclasses (`StateChanged`, `SelectionChanged`, `ToolChanged`, `ViewDirtied`). |
| **UID-based Selection** | `SelectionStore` (Phase 2) replaces index-based `SelectionState`. Objects identified by persistent integer UIDs. Bridge properties on `Zone3DEditor` translate between legacy `_*_selected` index fields and UIDs. |
| **Dialog Manager** | Tracks open/close state of floating and modal dialogs. `DialogPropertyBridge` generates `show_*` property descriptors that route through the manager. |
| **Keybind Registry** | Centralized catalog of `Keybind` dataclasses with rebinding, conflict detection, scope/condition filtering, and JSON persistence of user overrides. |
| **Snapshot Undo** | `UndoMixin._snapshot()` captures full zone state (all grids + object lists). Type-specific fast copiers replace `deepcopy`. |

---

## 2. editor/ (top-level)

### `__init__.py`

Package docstring only. No public exports.

---

### `input_context.py`

#### Classes

| Class | Bases | Description |
|-------|-------|-------------|
| `InputContext` | `ABC` | Abstract base for input-event consumers. |
| `InputStack` | — | Priority-ordered stack of `InputContext` instances. |

#### `InputContext` (Abstract)

```python
class InputContext(ABC):
    name: str                       # human-readable identifier
    blocks_below: bool = True       # if True, lower contexts don't receive events

    @abstractmethod
    def handle_event(self, event: pygame.event.Event) -> bool: ...
    def on_push(self) -> None: ...
    def on_pop(self) -> None: ...
```

#### `InputStack`

```python
class InputStack:
    def push(self, ctx: InputContext) -> None
    def pop(self, ctx: InputContext) -> None
    def dispatch(self, event: pygame.event.Event) -> bool   # top→bottom
    def is_captured(self) -> bool                            # any context blocks?
```

**Connections:** Used by `ZoneEditorApp.__init__()` to manage global shortcuts,
viewport capture, and stamp capture contexts.

---

### `contexts.py`

Three concrete `InputContext` subclasses:

| Context | Priority | `blocks_below` | Description |
|---------|----------|----------------|-------------|
| `GlobalShortcutsContext` | pushed first | `False` | Intercepts Ctrl+Z/Y, Ctrl+S, Ctrl+C/V, Ctrl+D, Esc, F-keys, hotbar, camera bookmarks. Queries `_is_global_shortcut()`. |
| `CapturedViewportContext` | pushed on mouse capture | `True` | Forwards events to `Zone3DEditor._on_keydown/_on_click/_on_scroll/_on_mouseup`. |
| `StampCaptureContext` | pushed during stamp naming | `True` | Intercepts key events for typing a capture name; delegates to `_stamp_capture_key/_commit`. |

#### Key Constants

```python
_GLOBAL_ACTIONS: frozenset[str]  # {"undo", "redo", "save", "copy", "paste", ...}
_NUM_KEYS: dict[int, int]        # pygame.K_0..K_9 → 0..9
```

#### Helper

```python
def _is_global_shortcut(kb: KeybindRegistry, key: int, mod: int) -> bool
```

---

### `fly_camera.py`

Pure math module — no classes, no state.

#### Functions

```python
def wasd_2d(yaw, forward, backward, left, right, speed, dt)
    → (dx, dz)

def forward_3d(yaw, pitch) → (fx, fy, fz)

def right_3d(yaw) → (rx, ry, rz)

def wasd_3d(yaw, pitch, forward, backward, strafe_left, strafe_right,
            up, down, speed, dt)
    → (dx, dy, dz)

def clamp_pitch(pitch) → float
```

#### Constants

```python
MOUSE_SENS    = 0.003
KB_TURN_SPEED = 2.5
PITCH_LIMIT   = math.pi * 0.45
```

---

### `keybinds.py`

#### Constants

```python
MOD_NONE  = 0
MOD_SHIFT = pygame.KMOD_SHIFT
MOD_CTRL  = pygame.KMOD_CTRL
MOD_ALT   = pygame.KMOD_ALT
```

#### Dataclass

```python
@dataclass
class Keybind:
    action: str           # e.g. "sculpt.raise_floor"
    key: int              # pygame key constant
    mod: int              # modifier mask (MOD_NONE, MOD_SHIFT, etc.)
    category: str         # "Camera", "Sculpt", "Paint", etc.
    description: str      # human-readable label
    scope: str = ""       # tool scope for check()
    condition: str = ""   # extra condition tag
```

#### Class

```python
class KeybindRegistry:
    def register(self, kb: Keybind) -> None
    def check(self, action: str, key: int, mod: int,
              scope: str = "", condition: str = "") -> bool
    def key_for(self, action: str) -> int
    def conflicts(self, key: int, mod: int, scope: str = "") -> list[Keybind]
    def rebind(self, action: str, key: int, mod: int) -> None
    def save_overrides(self, path: Path) -> None
    def load_overrides(self, path: Path) -> None
    def by_category(self) -> dict[str, list[Keybind]]
    def all_keybinds(self) -> list[Keybind]
```

#### Factory

```python
def create_default_registry() -> KeybindRegistry
```

Registers ~70 keybinds across categories: Camera, Sculpt, Paint, Segment,
Select, Entity, Box, Quad, Portal, Curve, Overlay, Stamp, Display, Help, Global.

---

### `dialog_manager.py`

#### Class

```python
class DialogManager:
    FLOATING = "floating"
    MODAL    = "modal"

    def open(self, name: str, category: str = FLOATING) -> None
    def close(self, name: str) -> None
    def toggle(self, name: str, category: str = FLOATING) -> None
    def is_open(self, name: str) -> bool
    def close_any(self) -> bool        # close most-recently-opened (Esc)
    def open_dialogs(self) -> list[str]
```

#### Mixin + Factory

```python
class DialogPropertyBridge:
    # Provides 17 show_* property descriptors (e.g. show_asset_browser,
    # show_resize_dialog, etc.) routed through DialogManager.

def _make_dialog_prop(name: str) -> property
```

---

### `zone_ops.py`

Pure zone-mutation utilities with no editor dependency.

```python
DEFAULT_FLOOR  = 0.0
SKY_HEIGHT     = 1000.0
LAYER_NONE     = -1000.0

def reset_cell(zone, r: int, c: int, open_tile: str) -> None
def clear_cell_textures(zone, r: int, c: int) -> None
```

---

## 3. editor/app/

### `__init__.py`

Re-exports `ZoneEditorApp`.

---

### `app.py` — `ZoneEditorApp`

The top-level editor application. Composes all app-level mixins.

#### `__init__(self, zone_path=None)`

- Initialises pygame display (1600×900), OpenGL context, imgui
- Restores session (last zone, camera bookmarks, recent files)
- Creates `InputStack`, `DialogManager`, `KeybindRegistry`
- Loads or creates default zone
- Creates `Zone3DEditor` (3D viewport), `TextureAtlas`, `RayRenderer`

#### Zone Management

```python
def _create_default_zone(self) -> Zone
def _attach_zone(self, zone: Zone) -> None       # wire up 3D editor + raycaster
def _load_zone(self, path: str) -> None
def _create_new_zone(self, w: int, h: int) -> None
def _save_zone(self) -> None
```

#### Unsaved-Changes Guard

```python
def _request_guarded(self, action_name: str, callback: Callable) -> None
def _execute_guarded_action(self, confirmed: bool) -> None
```

Prompts "Save / Discard / Cancel" before destructive operations.

#### Mouse Capture

```python
def _capture_mouse(self) -> None    # pushes CapturedViewportContext
def _release_mouse(self) -> None    # pops context, restores cursor
```

#### Main Loop

```python
def run(self) -> None   # 60 fps, event pump → InputStack, imgui render, GL blit
```

#### Camera Bookmarks

```python
_bookmarks: list[dict]  # up to 10 save/recall slots (Ctrl+Shift+1..0 / Ctrl+1..0)
```

#### Session Persistence

Saves/restores: last zone path, camera position, recent files, window state.

---

### `constants.py`

```python
WINDOW_W, WINDOW_H = 1600, 900
LEFT_PANEL_W       = 200
RIGHT_PANEL_W      = 320
STATUS_BAR_H       = 28
RAY_W, RAY_H       = 640, 480
MOVE_SPEED         = 4.0
```

---

### `viewport.py` — `ViewportMixin`

```python
class ViewportMixin:
    def _init_viewport(self) -> None       # GL setup: framebuffer, texture, fullscreen quad VAO
    def _render_viewport(self) -> None     # Zone3DEditor.draw() → surface → GL texture upload → quad draw
```

Uses OpenGL: `glTexImage2D` to upload the pygame surface each frame.

---

### `events.py` — `EventsMixin`

```python
class EventsMixin:
    def _handle_events(self) -> None          # pygame event pump
    def _sync_input_contexts(self) -> None    # ensure correct contexts on stack
    def _flash_transient(self, msg, dur, col) # HUD flash message
```

---

### `raycaster.py` — `RaycasterMixin`

```python
class RaycasterMixin:
    def _draw_raycaster_preview(self) -> None   # 2D first-person preview using engine.ray_renderer
    def _update_raycaster_camera(self) -> None  # syncs from 3D editor camera via fly_camera.wasd_2d
```

---

### `theme.py`

```python
def setup_theme() -> None   # dark imgui theme (called once at startup)
```

---

### `session_cfg.py`

```python
def load_session(path: Path) -> dict
def save_session(path: Path, data: dict) -> None
def push_recent(session: dict, filepath: str) -> None
```

---

### `asset_browser.py` — `AssetBrowserMixin`

Floating texture browser window.

```python
class AssetBrowserMixin:
    def _draw_asset_browser(self) -> None     # category tabs, GL thumbnail cache, import/delete
    def _import_texture(self, path: str) -> None
    def _delete_texture(self, name: str) -> None
```

**Category tabs:** Walls, Floors, Ceilings, Decals, All.

---

### `data_viewers.py` — `DataViewersMixin`

Four read-only TOML data browsers.

```python
class DataViewersMixin:
    def _draw_entity_viewer(self) -> None
    def _draw_item_viewer(self) -> None
    def _draw_loot_viewer(self) -> None
    def _draw_preset_viewer(self) -> None
```

---

### `dialogs.py` — `DialogsMixin`

Nine ImGui dialogs:

| Dialog | Purpose |
|--------|---------|
| Resize | Resize zone with 2D/3D/4D grid helpers and object relocation |
| Validate | Check zone for issues (orphaned entities, missing textures) |
| Export | Top-down PNG export |
| New Zone | Create zone with dimensions |
| Load | File browser |
| Zone Settings | Name, anchor, skybox, sky_color, first_person |
| Confirm Quit | Unsaved changes guard |
| Confirm New | Unsaved changes guard |
| Error | Display error messages |

#### Key Internal Helpers

```python
def _resize_grid_2d(grid, old_h, old_w, new_h, new_w, default) -> list
def _resize_grid_3d(grid, old_h, old_w, new_h, new_w, default) -> list  # face_textures [r][c][4]
def _resize_grid_4d(grid, old_h, old_w, new_h, new_w, default) -> list  # segments [r][c][4][segs]
def _relocate_objects(zone, dr, dc) -> None
def _export_top_down(zone, path) -> None
```

---

### `entity_creator.py` — `EntityCreatorMixin`

Full entity type authoring dialog.

```python
class EntityCreatorMixin:
    def _draw_entity_creator(self) -> None    # create/edit/delete entity types
    def _draw_entity_type_form(self) -> None  # name, sprite, color, scale, states, render_type
    def _save_entity_type(self) -> None       # writes to custom_entities.toml via entity_writer
```

Supports billboard and prism render types with per-face texture assignment.

---

### `entity_textures.py` — `EntityTexturesMixin`

Sprite sheet status manager.

```python
class EntityTexturesMixin:
    def _check_entity_textures(self) -> dict  # staleness detection per entity type
    def _rebuild_texture(self, etype: str) -> None
    def _draw_texture_status(self) -> None
```

---

### `entity_writer.py`

CRUD for `data/custom_entities.toml`.

```python
def load_custom_entities(path: Path) -> dict
def save_custom_entities(path: Path, data: dict) -> None  # hand-rolled TOML serialiser
def add_entity_type(path: Path, name: str, definition: dict) -> None
def update_entity_type(path: Path, name: str, definition: dict) -> None
def delete_entity_type(path: Path, name: str) -> None
```

---

## 4. editor/app/panels_pkg/

### `__init__.py` — `PanelsMixin`

Composes `MenuBarMixin`, `ToolboxMixin`, `InspectorMixin`, `OverlaysMixin`.

```python
class PanelsMixin(MenuBarMixin, ToolboxMixin, InspectorMixin, OverlaysMixin):
    def _build_ui(self) -> None           # master UI layout entry point
    def _section_header(self, label) -> bool
    def _draw_splitters(self) -> None     # vertical splitter between panels
    def _global_state_bar(self) -> None   # top bar: mode, tool, layer indicators
    def _properties_panel(self) -> None   # right-side panel dispatch
    def _status_bar(self) -> None         # bottom bar: zone info, dirty indicator
```

---

### `menu_bar.py` — `MenuBarMixin`

```python
class MenuBarMixin:
    def _menu_bar(self) -> None
```

Menus: **File** (New, Open, Save, Recent, Quit) · **Edit** (Undo, Redo, Copy, Paste, Duplicate) · **View** (Wireframe, Axes, Floors, Walls, Ceilings, Entities, HUD, Layer 1/2, Isolate) · **Zone** (Resize, Validate, Export, Settings) · **Data** (Entity/Item/Loot/Preset viewers) · **Window** (Asset Browser, Entity Creator, Texture Status).

---

### `toolbox.py` — `ToolboxMixin`

Left panel containing mode/tool selection, palettes, and tool controls.

```python
class ToolboxMixin:
    def _left_panel(self) -> None
```

Sections:
- **Mode tabs** (Architecture, Surface, Props, Logic)
- **Sub-tool buttons** (tool-specific within mode)
- **Texture palette** (scrollable, colour-chip grid, hotbar binding)
- **Preset palette** (stamp tool)
- **Entity palette** (entity tool, with preview)
- **Tool controls** (snap, grid, layer2 target)
- **Hints** (context-sensitive keyboard shortcuts)

---

### `inspectors.py` — `InspectorMixin`

Right panel: context-sensitive property editors.

#### Cell Inspector

```python
def _draw_cell_inspector(self) -> None
```

Displays and edits: floor/ceil heights, tile type, textures (floor/ceil/wall + per-face N/S/E/W), segments, light level, reflectivity, fog density. For L2: floor2/ceil2 heights and textures.

#### Bulk Inspector (multi-cell selection)

```python
def _draw_bulk_inspector(self) -> None
```

Batch editors: floor height, ceiling height, tile type, textures, lighting, paste mask checkboxes. Displays mixed-value summaries. Sub-helpers:

```python
def _draw_bulk_layer1(self) -> None
def _draw_bulk_layer2(self) -> None
```

#### Object Inspectors

| Method | Object Type |
|--------|-------------|
| `_draw_entity_inspector()` | Entity: position, angle, state, scale, prism geometry |
| `_draw_prism_inspector()` | Prism (box): position, size, yaw, collision, per-face textures |
| `_draw_quad_inspector()` | Quad: position, size, angle, texture, two-sided, collision |
| `_draw_portal_inspector()` | Portal: source cell/face, dest coords, angle offset |
| `_draw_curve_inspector()` | Curve: center, radius, arc angles, height, base_y, texture |
| `_draw_overlay_wall_inspector()` | Overlay wall: endpoints, height, texture, transparent, blocks |

#### Zone Settings

```python
def _draw_zone_settings(self) -> None   # size, anchor, first_person, skybox, sky_color
def _draw_camera_info(self) -> None
```

#### Helper Functions

```python
def _paint_target_label(self) -> str
def _parse_relative_value(text: str, current: float) -> float | None
def _collect_cell_values(self, prop_fn) -> list
def _summarise_values(values) -> str
def _batch_set_cell_prop(self, setter_fn) -> None
def _draw_cell_properties(self, title, props) -> None
```

#### Paste Mask Constants

```python
PASTE_MASK_HEIGHTS   = "heights"
PASTE_MASK_TEXTURES  = "textures"
PASTE_MASK_ENTITIES  = "entities"
PASTE_MASK_SEGMENTS  = "segments"
PASTE_MASK_LIGHTING  = "lighting"
```

---

### `overlays.py` — `OverlaysMixin`

```python
class OverlaysMixin:
    def _draw_help_overlay(self) -> None     # full keyboard shortcut reference card
    def _draw_keybind_editor(self) -> None   # full rebind UI: action list, key capture, conflict warning
```

---

## 5. editor/commands/

### Architecture

The command system follows a **Command + Handler + Bus** pattern:

```
Command (frozen dataclass)  →  CommandBus.execute()  →  handler function
                                     ↓
                             EventBus.emit(StateChanged)
```

- **Phase 0:** Handlers wrap existing mixin methods using `suppress_undo()` / `detect_change()` / `suppress_and_detect()` context managers.
- **Phase 1:** Some handlers (erase, paint) directly mutate zone data.
- Undo is managed by the bus: a snapshot is taken before the first command in a logical operation.

---

### `base.py`

#### Dataclasses

```python
@dataclass(frozen=True)
class Command:
    """Base for all commands. Subclass and add fields."""
    pass

@dataclass(frozen=True)
class BatchCommand:
    commands: tuple[Command, ...]
```

#### Classes

```python
class EventBus:
    def subscribe(self, event_type: type, callback: Callable) -> None
    def emit(self, event: object) -> None

class CommandBus:
    event_bus: EventBus

    def register(self, cmd_type: type[Command], handler: Callable) -> None
    def execute(self, cmd: Command) -> Any
    def execute_continuation(self, cmd: Command) -> Any   # no undo push (mid-drag)
    def _execute_batch(self, batch: BatchCommand) -> Any
```

#### Context Managers

```python
@contextmanager
def suppress_undo() -> Iterator[None]
    """Prevent UndoMixin._push_undo() from creating a snapshot."""

@contextmanager
def detect_change() -> Iterator[dict]
    """Yield a dict; handler sets d["changed"] = True if zone was modified."""

@contextmanager
def suppress_and_detect() -> Iterator[dict]
    """Combines suppress_undo + detect_change."""
```

---

### `events.py`

```python
@dataclass(frozen=True)
class StateChanged: pass         # zone data modified

@dataclass(frozen=True)
class SelectionChanged:
    cells: frozenset[tuple[int, int]]
    objects: frozenset[tuple[str, int]]

@dataclass(frozen=True)
class ToolChanged:
    tool: str

@dataclass(frozen=True)
class ViewDirtied: pass          # viewport needs redraw
```

---

### Command Files

Each file defines a set of frozen `Command` dataclasses and a `register_*_handlers(bus, editor)` function.

#### `sculpt_cmds.py` — 17 commands

| Command | Fields | Description |
|---------|--------|-------------|
| `SculptFloorRaise` | — | Raise aimed floor by snap_y |
| `SculptFloorLower` | — | Lower aimed floor |
| `SculptCeilLower` | — | Lower ceiling (room shorter) |
| `SculptCeilRaise` | — | Raise ceiling (room taller) |
| `SculptToggleCeiling` | — | Add/remove ceiling (T key) |
| `SculptResetCeiling` | — | Reset ceiling to default (R) |
| `SculptResetFloor` | — | Reset floor to default (R) |
| `SculptClearCell` | — | Full cell reset (Del) |
| `SculptBatchMakeWall` | — | Convert to wall (H), selection-aware |
| `SculptBatchMakeOpen` | — | Convert to open (Shift+H), selection-aware |
| `SculptAdjustUpperWall` | `modifier: int` | U/Shift+U/Ctrl+U upper wall |
| `SculptScrollUpperWall` | `direction: int` | Scroll on ceiling |
| `SculptExtendFloor` | `cell, direction` | Scroll-extend floor |
| `SculptExtendWallCeiling` | `cell, direction` | Scroll on wall cell |
| `SculptFlattenFloors` | — | Flatten selection floors (L) |
| `SculptFlattenCeilings` | — | Flatten selection ceilings (Shift+L) |
| `SculptApplyCellToSelection` | — | Copy aimed → selection |

#### `paint_cmds.py` — 12 commands

| Command | Fields | Description |
|---------|--------|-------------|
| `PaintFace` | — | Paint aimed face |
| `PaintAllFaces` | — | Paint all faces of cell (Shift+click) |
| `EraseFace` | — | Erase aimed face texture |
| `PaintPrismFace` | `index, face` | Paint prism face (None = all) |
| `ErasePrismFace` | `index, face` | Erase prism face |
| `PaintQuad` | `index` | Paint quad texture |
| `EraseQuad` | `index` | Erase quad texture |
| `FloodFill` | — | BFS flood fill (Ctrl+click) |
| `FloodClear` | — | BFS flood clear (Ctrl+RMB) |
| `SelectionFillTexture` | — | Fill selection with current texture |
| `SelectionClearTextures` | — | Clear selection textures |
| `ContinuousPaint` | — | Per-frame paint during LMB drag |

#### `erase_cmds.py` — 3 commands

| Command | Description |
|---------|-------------|
| `EraseCell` | Full cell reset via `zone_ops.reset_cell()` |
| `EraseHeight` | Reset heights, cleanup orphaned segments |
| `EraseTexturesOnly` | Clear face textures only |

#### `object_cmds.py` — 31 commands

Covers six object types:

**Entity** (4): `EntityPlace`, `EntityDelete(index)`, `EntityMove`, `EntityRotate(direction)`

**Box/Prism** (7): `BoxPlace`, `BoxDelete(index)`, `BoxMove`, `BoxRotate90`, `BoxRotateFine(direction)`, `BoxAdjustSize(direction, axis)`, `BoxShiftZ(direction)`

**Quad** (7): `QuadPlace`, `QuadDelete(index)`, `QuadMove`, `QuadRotate(direction)`, `QuadAdjustSize(direction)`, `QuadToggleTwosided`, `QuadPaint`

**Portal** (2): `PortalPlace`, `PortalDelete`

**Curve** (7): `CurvePlace`, `CurveDelete(index)`, `CurveMove`, `CurveAdjustRadius(direction)`, `CurveAdjustAngleStart(direction)`, `CurveAdjustAngleEnd(direction)`, `CurvePaint`

**Overlay** (6): `OverlayFinishPlace`, `OverlayDelete(index)`, `OverlayMove`, `OverlayAdjustHeight(direction)`, `OverlayToggleTransparent`, `OverlayPaint`

#### `select_cmds.py` — 3 commands

| Command | Fields | Description |
|---------|--------|-------------|
| `SelScroll` | `direction, ceiling` | Batch raise/lower selected cells |
| `SelDelete` | — | Reset all selected cells |
| `SelResetCells` | — | Clear selection |

#### `segment_cmds.py` — 3 commands

`SegmentSplit`, `SegmentMerge`, `SegmentPaint`

#### `stamp_cmds.py` — 1 command

`StampApply`

#### `misc_cmds.py` — 3 commands

`ClipboardPaste`, `DuplicateSelection`, `ObjectDeleteSelected`

#### `l2_cmds.py` — 14 commands

`L2Raise(shift, ctrl)`, `L2Lower(shift)`, `L2Paint`, `L2EraseSingle`,
`L2PaintSelection`, `L2EraseSelection`, `L2Scroll(direction)`, `L2Reset`,
`L2SelScroll(direction)`, `L2FlattenFloors`, `L2FlattenCeilings`,
`L2ToggleCeil`, `L2SelectionReset`, `L2DeleteAimed`

---

## 6. editor/view_3d/

### `__init__.py`

Re-exports: `SelectionState`, `ObjectLayer`, math helpers, picking functions, `Zone3DEditor`, all constants.

---

### `constants.py`

#### Modes & Tools

```python
MODE_ARCH    = "architecture"
MODE_SURF    = "surface"
MODE_PROPS   = "props"
MODE_LOGIC   = "logic"

MODE_TOOLS = {
    MODE_ARCH:  ("sculpt", "segment"),
    MODE_SURF:  ("paint",),
    MODE_PROPS: ("box", "quad", "curve", "overlay"),
    MODE_LOGIC: ("entity", "portal"),
}

TOOLS      = ("sculpt", "paint", "segment", "entity", "box")
UTIL_TOOLS = ("select", "stamp", "quad", "portal", "curve", "overlay")
ALL_TOOLS  = TOOLS + UTIL_TOOLS
```

#### View Modes

```python
VIEW_LIT     = "lit"
VIEW_PATHING = "pathing"
```

#### Paste Mask Flags

```python
PASTE_MASK_HEIGHTS, PASTE_MASK_TEXTURES, PASTE_MASK_ENTITIES,
PASTE_MASK_SEGMENTS, PASTE_MASK_LIGHTING
PASTE_MASK_ALL = (all five)
```

#### Visual Constants

~40 colour constants (`COL_TOOL_WALL`, `COL_TOOL_PAINT`, `COL_AXIS_X`, etc.),
`TOOL_COLORS` dict, `TOOL_LABELS` dict, `TOOL_HINTS` dict (comprehensive per-tool action/key documentation).

#### Geometry Constants

```python
SNAP_Y_OPTIONS = [0.25, 0.5, 1.0, 0.125, 0.0625]
FLOOR_MIN, FLOOR_MAX, CEIL_MIN, CEIL_MAX = ...
SKY_HEIGHT = 1000.0
DEFAULT_FLOOR, DEFAULT_CEIL = 0.0, 1.0
FACE_IDX = {"north": 0, "south": 1, "east": 2, "west": 3}
_FACE_DEFS  # 6-tuple: (corner_indices, outward_normal, brightness_multiplier)
```

#### Camera

```python
FLY_SPEED   = 6.0
FLY_SPRINT  = 2.5
HOTBAR_SIZE = 10
```

#### Utility Key Bindings

```python
UTIL_KEYS = {K_b: "select", K_p: "stamp", K_i: "quad", K_o: "portal",
             K_SEMICOLON: "curve", K_l: "overlay"}
```

#### Texture Palette

```python
def _ensure_palette() -> list[str]   # lazy-built from TILE_REGISTRY: walls → floors → rest
```

---

### `math3d.py`

Software 3D math for the viewport renderer.

#### Constants

```python
NEAR_CLIP = 0.05
FAR_CLIP  = 80.0
FOV_DEG   = 75
```

#### Functions

```python
def _extract_frustum_planes(vp: list[float]) -> list[tuple[float, float, float, float]]
def _aabb_in_frustum(planes, x0, y0, z0, x1, y1, z1) -> bool
def _visible_cell_set(planes, W, H, floor_heights, ceil_heights) -> set[tuple[int,int]]

def _perspective(fov_deg, aspect, near, far) -> list[float]   # 4×4 column-major
def _mat4_mul(a, b) -> list[float]                             # 4×4 multiply
def _build_view_matrix(eye, yaw, pitch) -> list[float]         # look-at from Euler

def _project(vp, x, y, z, hw, hh) -> tuple[float,float,float] | None
def _project_line(vp, x0,y0,z0, x1,y1,z1, hw, hh)
    -> tuple[tuple[float,float], tuple[float,float]] | None    # near-plane clipped
def _project_poly(vp, corners, hw, hh) -> list[tuple[int,int]] | None
    # Sutherland-Hodgman near-plane clip + projection
```

---

### `picking.py`

Ray-intersection utilities.

```python
@dataclass
class _CellHit:
    t: float                    # ray parameter
    col: int
    row: int
    part: str                   # "floor", "ceiling", "wall", "floor2", "ceiling2"
    face: str                   # "north", "south", "east", "west", "top", "bot", "ground"
    hit_y: float                # world Y at hit point

def _ray_vs_aabb(ox, oy, oz, fx, fy, fz, x0, y0, z0, x1, y1, z1)
    -> tuple[float, str] | None     # (t, face_name)

def _ray_vs_obb(ox, oy, oz, fx, fy, fz, cx, cz, w, h, d, base_y, yaw)
    -> tuple[float, str] | None     # yaw-rotated oriented bounding box
```

---

### `selection.py` — `SelectionState` (Legacy)

Index-based selection (being replaced by `SelectionStore`).

```python
class SelectionState:
    cells: set[tuple[int, int]]
    objects: set[tuple[str, int]]       # (type_tag, index)
    anchor: tuple[int, int] | None
    ceiling_mode: bool

    # Cell operations
    def add_cell(self, r, c) -> None
    def select_all_cells(self, zone) -> None
    def begin_rect(self, r, c) -> None
    def update_rect(self, r, c) -> None
    def finish_rect(self, zone) -> set    # Bresenham line + filled rectangle
    def cancel_rect(self) -> None

    # Object operations
    def select_object(self, type_tag, idx) -> None
    def add_object(self, type_tag, idx) -> None
    def toggle_object(self, type_tag, idx) -> None
    def select_objects_in_rect(self, zone, rmin, cmin, rmax, cmax) -> None

    # Queries
    def has_cells/has_objects/has_anything/bounds/contains_cell/contains_object
    def iter_cells/iter_objects/cell_count/object_count

    # Index maintenance
    def on_object_deleted(self, type_tag, idx) -> None    # fix indices after deletion
    def on_object_inserted(self, type_tag, idx) -> None   # fix indices after insertion

    # Properties
    @property
    def rect_in_progress -> bool
    @property
    def rect_preview -> tuple | None
```

---

### `selection_store.py` — `SelectionStore` (Phase 2, UID-based)

Drop-in replacement for `SelectionState` with UID-based object identity.

```python
class SelectionStore:
    cells: set[tuple[int, int]]
    ceiling_mode: bool

    def __init__(self, event_bus: EventBus | None = None)

    # Object operations (UID-based)
    def select_object(self, type_tag: str, uid: int) -> None
    def add_object(self, type_tag: str, uid: int) -> None
    def toggle_object(self, type_tag: str, uid: int) -> None
    def deselect_object(self, uid: int) -> None
    def select_objects_in_rect(self, zone, rmin, cmin, rmax, cmax) -> None

    # Primary (focused) object
    @property
    def primary_uid -> int | None
    @property
    def primary_type -> str | None
    def primary_index(self, zone) -> int | None    # resolve UID → list index

    # Queries
    def is_object_selected(self, uid) -> bool
    def has_cells/has_objects/has_anything/cell_count/object_count
    def iter_cells/iter_objects
    def selected_uids_by_type(self, type_tag) -> list[int]
    def bounds() -> tuple | None
    def contains_cell/contains_object

    # Object lifecycle
    def on_object_deleted(self, uid) -> None     # no index fixup needed
    def on_object_inserted(self, type_tag, uid) -> None   # no-op

    # Backward compat
    @property
    def objects -> set[tuple[str, int]]    # read-only {(type_tag, uid), ...}

    # Internal
    def _emit_changed(self) -> None        # emits SelectionChanged via EventBus
```

#### Helper Functions

```python
def uid_of(obj: dict) -> int | None
def resolve_index(zone, type_tag: str, uid: int) -> int | None
```

---

### `objects.py` — `ObjectLayer`

Unified cross-type object operations.

```python
class ObjectLayer:
    ed: Zone3DEditor

    def get_store(self, obj_type: str) -> list | None
    def find_aimed(self) -> tuple[str, int] | None       # scan all types, return closest
    def any_selected(self) -> tuple[str, int] | None      # check all types for selection

    def select(self, hit: tuple[str, int], add: bool = False) -> None
    def toggle_select(self, hit: tuple[str, int]) -> None
    def deselect_all(self) -> None
    def deselect_type(self, obj_type: str) -> None

    def delete_selected(self) -> bool      # grouped by type, descending index order
    def move_selected_to_aimed(self) -> bool

    def total_count(self) -> int
    def selected_count(self) -> int
    @staticmethod
    def type_label(obj_type: str) -> str
```

**Dispatch tables:** `_STORES`, `_SELECTED_FIELDS`, `_FIND_METHODS`,
`_SELECT_METHODS`, `_DELETE_METHODS`, `_MOVE_METHODS`, `_DESELECT_METHODS`.

---

### `geometry.py` — `GeometryMixin`

Cell bounding-box computation for the 3D viewport.

```python
class GeometryMixin:
    def _cell_boxes(self, r, c) -> list[tuple[str, float, float]]
        # cached per frame; returns [(part, y_bottom, y_top), ...]

    def _compute_cell_boxes(self, r, c) -> list[tuple[str, float, float]]
        # floor mass (ground → fh), wall mass (fh → ch), ceiling mass (ch → top)
        # adjacent-cell extension for upper wall heights

    def _ceil_mass_top(self, r, c) -> float
        # effective top of ceiling mass (max of uwh and adjacent floor heights)

    def _layer_cell_boxes(self, r, c) -> list[tuple[str, float, float]]
        # respects active_layer and isolate_layer settings
        # filters L1/L2 boxes, adds floor2/ceiling2 parts
```

---

### `undo.py` — `UndoMixin`

```python
class UndoMixin:
    _undo_stack: list[dict]
    _redo_stack: list[dict]

    def _snapshot(self) -> dict       # captures all grids + object lists
    def _restore(self, snap: dict) -> None
    def _push_undo(self) -> None      # push current state, clear redo
    def undo(self) -> None
    def redo(self) -> None
```

#### Fast Copiers (replace `deepcopy`)

```python
def _copy_grid(grid)      # 2D: [[val, ...], ...]
def _copy_grid_3d(grid)   # 3D: [[[val, ...], ...], ...]  (face_textures)
def _copy_grid_4d(grid)   # 4D: [[[[seg, ...], ...], ...], ...]  (segments)
def _copy_dict_list(lst)  # [{...}, ...]  (entities, boxes, quads, etc.)
def _copy_overlay_walls(lst)  # [OverlayWall(...), ...]
```

---

### `primitives.py` — `DrawPrimitivesMixin`

```python
class DrawPrimitivesMixin:
    def _line3d(self, surface, vp, hw, hh, x0,y0,z0, x1,y1,z1, color, width)
    def _box(self, surface, vp, hw, hh, x0,y0,z0, x1,y1,z1, color, width)
        # 12-edge wireframe

    def _filled_box(self, surface, vp, hw, hh, x0,y0,z0, x1,y1,z1,
                    base_color, edge_color, edge_width, alpha=255,
                    face_colors=None, wireframe=False)
        # Face-shaded with backface culling, alpha blending via scratch surface

    def _filled_rotated_box(self, surface, vp, hw, hh,
                            cx, cz, w, h, d, base_y, yaw,
                            base_color, edge_color, edge_width, alpha=255,
                            face_colors=None, wireframe=False)
        # Yaw-rotated prism rendering
```

---

### `save.py` — `SaveMixin`

```python
class SaveMixin:
    def _save(self) -> None   # delegates to zone.save_to_file(GameRegistry)
```

---

### `rendering.py` — `RenderingMixin`

2224 lines. The main 3D viewport renderer.

#### Entry Point

```python
def draw(self, surface, dt) -> None
```

Draw order:
1. Skybox panorama (`_draw_skybox_bg`)
2. Axes (`_draw_axes`)
3. Cell boxes with face shading (`_draw_cell_boxes`)
4. Surface markers (`_draw_surface_markers`) — height-level wireframe indicators
5. Segment boundary rings (`_draw_seg_boundary_rings`)
6. Layer 2 slabs (`_draw_layer2_slabs`) — floor2/ceil2 with opacity control
7. Entities (`_draw_entities`) — solid shaded boxes + direction arrows + labels + ghost preview
8. Boxes/prisms (`_draw_boxes`) — rotated shaded boxes + ghost
9. Quads (`_draw_quads`) — vertical rectangles with diagonal crosses + ghost
10. Portals (`_draw_portals`) — face outlines + translucent fill + dest line
11. Curves (`_draw_curves`) — arc wireframes + ghost
12. Overlay walls (`_draw_overlay_walls`) — vertical rectangles + placement ghost
13. Selection highlight (`_draw_selection_highlight`) — per-cell translucent slabs
14. Face highlight + preview (`_draw_face_hl_and_preview`) — aimed face, prism/quad face, merge target
15. Crosshair (`_draw_crosshair`) — tool-coloured, L2 diamond badge
16. Action context (`_draw_action_context`) — LMB/RMB/Scroll hint overlay
17. Hotbar (`_draw_hotbar`) — 10 texture quick-access slots
18. HUD (`_draw_hud`) — layer/mode/tool/selection/snap/tex/cell info

#### Key Sub-methods

```python
def _draw_skybox_bg(self, surface, vp, hw, hh)
    # Cylindrical panorama: samples skybox image by yaw+pitch angle mapping

def _draw_cell_boxes(self, surface, vp, hw, hh, zone, W, H, visible)
    # Depth-sorted filled boxes with face colours from textures
    # Layer ghosting: L1 translucent when L2 active, hidden when isolating

def _draw_layer2_slabs(self, surface, vp, hw, hh, zone, W, H, visible)
    # Separate L2 floor/ceil slabs with per-face step texture colours

def _draw_cell_segments(self, surface, vp, hw, hh, r, c, part, alpha)
    # Overdraw per-segment colour bands on multi-segment faces

def _draw_face_highlight(self, surface, vp, hw, hh, hit)
    # Translucent polygon on aimed face, respecting segment bands

def _draw_prism_face_hl / _draw_quad_face_hl / _draw_object_face_poly
    # Object face highlighting for paint tool

def _draw_merge_target(self, surface, vp, hw, hh)
    # Red line on nearest segment boundary (segment tool)
```

#### Colour Resolution

```python
def _resolve_floor_tex(self, r, c) -> str    # floor_textures → tile fallback
def _resolve_ceil_tex(self, r, c) -> str     # ceil_textures → "concrete" fallback
def _get_box_color(self, r, c, part) -> tuple[int,int,int]
def _get_face_colors(self, r, c, part) -> list[tuple[int,int,int]]   # 6 per _FACE_DEFS
def _apply_cell_effects(self, col, r, c, part) -> tuple[int,int,int]
    # light_level → fog_density → reflectivity tinting
def _tile_color(texture: str) -> tuple[int,int,int]   # from TILE_COLORS registry
def _darken(color, factor) -> tuple[int,int,int]
def _largest_seg_tex(segs, fallback) -> str   # tallest segment's texture
```

---

### `editor.py` — `Zone3DEditor`

1968 lines. The core 3D editor class composing all 17+ tool mixins.

#### Construction

```python
class Zone3DEditor(RenderingMixin, DrawPrimitivesMixin, SculptMixin,
                   PaintMixin, FillMixin, SelectMixin, SegmentMixin,
                   StampMixin, EntityMixin, BoxMixin, Layer2Mixin,
                   QuadMixin, PortalMixin, CurveMixin, OverlayWallMixin,
                   GeometryMixin, UndoMixin, SaveMixin):

    def __init__(self, zone, atlas, kb, event_bus=None)
```

Init sets up:
- Camera state (position, yaw, pitch)
- Tool state (mode, tool, snap, texture index, hotbar)
- Command bus + handler registration
- Selection store (Phase 2 `SelectionStore` + bridge properties)
- Object layer (`ObjectLayer`)
- Layer 2 state
- Clipboard, paste mask, preview state
- Visibility toggles (walls, floors, ceilings, entities, HUD, axes, wireframe)

#### Phase 2 Bridge Properties

```python
# These translate between legacy _*_selected index fields and UID-based SelectionStore:
@property
def _ent_selected(self) -> int | None     # getter resolves UID → index
@_ent_selected.setter                      # setter looks up UID from zone.entities[idx]

# Same pattern for:
_box_selected, _quad_selected, _curve_selected, _ow_selected, _portal_selected
```

#### Handler Registration

```python
def _register_all_handlers(self) -> None
    # Calls all register_*_handlers() functions from editor/commands/
```

#### Command Helpers

```python
def _sculpt_cmd(self, cmd_class) -> bool     # shorthand for single-cell sculpt commands
def batch_or_single(self, cmd_class, batch_cmd_class=None) -> bool
```

#### Input Dispatch

```python
def _on_keydown(self, event) -> bool
```

Full keybind dispatch covering:
1. Undo/redo (Ctrl+Z/Y)
2. Mode switching (F1-F4)
3. Tool switching (number keys within mode, Tab cycle)
4. Utility tool toggles (B=select, P=stamp, I=quad, O=portal, ;=curve, L=overlay)
5. Hotbar slots (6-0 bare, Alt+1-0)
6. Selection operations (Esc, Ctrl+A, Shift+A contiguous, L/Shift+L flatten, T ceiling toggle, H wall)
7. Layer controls (`, Tab for isolation)
8. Selection-aware batch operations
9. Display toggles (F10 axes)
10. Tool-specific keys (U=upper wall, R=reset, T=ceiling/state, H=wall, Del, G=snap, X=layer/ceil mode, M=stamp mode)
11. Help overlay (?)

```python
def _on_click(self, event) -> bool
```

Per-tool click handling:
- **Sculpt:** L1/L2 raise/lower, selection-aware ceiling operations
- **Paint:** Prism/quad/cell face painting, flood fill, eyedropper, L2 paint
- **Select:** Rectangle selection start/complete
- **Segment:** Split/merge/paint
- **Stamp:** Apply/capture
- **Entity/Box/Quad/Curve/Overlay:** Place/select/move/deselect/delete with Ctrl+click = toggle, Shift+click = add
- **Portal:** Place/delete
- Universal MMB eyedropper fallback

```python
def _on_scroll(self, event) -> bool
```

Per-tool scroll:
- Paint/segment: cycle texture palette
- Stamp: cycle presets
- Entity: cycle type / Shift = rotate
- Box: width/depth/height / Shift = fine rotate / Ctrl = height
- Quad/Overlay: texture cycle / Shift = rotate/height
- Portal: cycle portals
- Curve: radius / Shift = start angle / Ctrl = end angle
- Select/Sculpt: batch raise/lower, snap grid, extend floor/wall

```python
def _on_mouseup(self, event) -> bool    # LMB release tracking for continuous paint
```

#### Update Loop

```python
def update(self, dt, mouse_captured) -> None
```

Per-frame: clear geometry cache, camera movement (WASD + mouse-look + collision),
aim update (`_update_aim`), continuous paint execution.

#### Raycasting / Picking

```python
def _update_aim(self) -> None
    # Ray from camera forward → nearest cell box or ground plane
    # Uses _layer_cell_boxes for layer-aware picking
    # Updates self.aimed: _CellHit | None

def _compute_preview(self) -> None
    # Computes preview_line / preview_box for sculpt/segment tools

def _forward(self) -> tuple[float, float, float]
```

#### Camera Collision

```python
def _collides_xz(self, x, z, y, radius) -> bool
    # Circle-vs-AABB collision with wall tiles and floor/ceiling bounds
```

#### Clipboard

```python
def _clipboard_copy(self) -> None      # copies full cell state (heights, textures, segments, L2, entities)
def _clipboard_paste(self) -> None     # pastes to selection or aimed cell, respects paste mask
```

#### Duplicate

```python
def _duplicate_selection(self) -> None  # Ctrl+D: clone selected cells +1 row/col
```

#### Smart Selection

```python
def _select_contiguous(self, r, c) -> None   # flood-fill select by matching heights
def _select_similar(self) -> None             # select all cells with matching properties (Shift+G)
```

---

### Tool Mixins

#### `tools_sculpt.py` — `SculptMixin` (839 lines)

Floor/ceiling/wall geometry manipulation.

```python
# Core single-cell operations
def _floor_raise_at(self, r, c) -> bool
def _floor_lower_at(self, r, c) -> bool
def _ceiling_lower_at(self, r, c) -> bool    # room shorter
def _ceiling_raise_at(self, r, c) -> bool    # room taller

# Tool entry points (dispatch to batch or single)
def _tool_floor_raise/lower(self) -> bool
def _tool_ceiling_lower/raise/delete(self) -> bool
def _toggle_ceiling(self) -> bool            # add/remove ceiling (T key)
def _reset_ceiling/floor(self) -> bool       # R key

# Clear and convert
def _clear_cell(self) -> bool                # Del key
def _make_wall/open(self, r, c) -> None
def _batch_make_wall/open(self) -> bool      # H / Shift+H, selection-aware

# Upper wall height
def _adjust_upper_wall_height(self, mod) -> bool   # U key (raise/lower/reset)
def _scroll_upper_wall/ceiling_height(self, direction) -> None
def _batch_raise/lower/reset_upper_wall(self) -> bool

# Scroll-extend (preserve gap)
def _extend_floor(self, r, c, direction) -> None
def _extend_wall_ceiling(self, r, c, direction) -> None

# Batch flatten
def _flatten_floors/ceilings(self) -> bool   # L / Shift+L

# Cell property application
def _apply_cell_to_selection(self) -> bool

# Segment auto-management
def _shift_ceil_mass(self, r, c, old_ch, delta) -> None
def _sync_tile_type(self, r, c) -> None
def _trim_floor_segments(self, r, c, new_fh) -> None
def _clear_ceil_segments(self, r, c) -> None
```

#### `tools_paint.py` — `PaintMixin` (475 lines)

```python
def _paint_update_aim(self) -> None          # per-frame: track closest prism/quad face
def _paint(self) -> bool                     # cell face painting with segment awareness
def _paint_all(self) -> bool                 # all 4 faces + floor + ceiling + L2
def _erase_face(self) -> bool
def _pick_texture(self) -> None              # eyedropper
def _continuous_paint(self) -> bool          # per-frame drag paint
def _paint_prism/erase_prism/pick_prism_texture(self, idx, face) -> None
def _paint_quad/erase_quad/pick_quad_texture(self, idx) -> None
```

#### `tools_fill.py` — `FillMixin` (399 lines)

```python
def _fill(self) -> bool           # Ctrl+LMB flood fill
def _fill_clear(self) -> bool     # Ctrl+RMB flood clear
def _flood_fill(self, r, c, tex: str | None) -> None   # BFS
def _classify_fill_target(self, part, face) -> str
    # Returns one of 9 modes: "floor", "ceiling", "wall_n/s/e/w",
    # "step_floor", "step_ceil", "l2_floor", "l2_ceil"
def _fill_can_spread(self, r, c, nr, nc, mode) -> bool
    # Boundary checks: height, type, texture, segment count
```

#### `tools_erase.py` — `EraseMixin`

```python
def _erase_cell(self) -> bool              # full reset via zone_ops.reset_cell
def _erase_height(self) -> bool            # L1/L2 height reset with segment cleanup
def _erase_cell_textures(self) -> bool
def _erase_textures_only(self) -> bool
```

#### `tools_select.py` — `SelectMixin` (400 lines)

```python
def _sel_click(self) -> None               # rectangle select: begin/extend/finish
def _sel_rclick(self) -> None              # cancel or clear
def _sel_delete(self) -> None              # delete aimed entity/object
def _sel_cancel(self) -> None
def _sel_toggle_ceiling_mode(self) -> None # X key
def _sel_scroll(self, direction, ceiling) -> bool   # batch raise/lower with gap preservation
def _sel_fill_texture(self) -> bool
def _sel_clear_textures(self) -> bool
def _sel_reset_cells(self) -> bool
def _has_selection(self) -> bool
def _apply_to_selection(self, fn) -> bool  # apply fn(r, c) to all selected cells
def _sel_bounds(self) -> tuple | None
```

#### `tools_segment.py` — `SegmentMixin` (300 lines)

```python
def _seg_face_info(self) -> tuple | None
    # Returns (r, c, fi, segs, y_bot, y_top, hit_y, seg_type)
    # seg_type: "wall", "floor_step", "ceil_step", "l2_floor_step", "l2_ceil_step"
def _seg_arrays(self) -> tuple
def _aimed_segment_idx(self) -> int
def _seg_split(self) -> bool       # LMB: split face at crosshair Y
def _seg_merge(self) -> bool       # RMB: merge nearest boundary
def _seg_paint(self) -> bool       # MMB: paint aimed segment

# Auto-segment helpers
def _auto_segment_floor/ceil/uwh(self, r, c) -> None
def _auto_trim_floor(self, r, c) -> None
```

#### `tools_stamp.py` — `StampMixin`

```python
def _stamp_apply(self) -> bool
def _stamp_capture_begin(self) -> None
def _stamp_capture_key(self, event) -> bool
def _stamp_capture_commit(self) -> None
def _stamp_cycle(self, direction) -> None
def _stamp_cycle_mode(self) -> None
def _stamp_current(self) -> Preset | None
def _stamp_current_mode(self) -> str
```

Uses `core.presets.apply_preset()` / `capture_preset()`.

#### `tools_entity.py` — `EntityMixin` (300 lines)

```python
def _ent_current_type(self) -> str
def _ent_current_def(self) -> EntityDef | None
def _ent_cycle_palette(self, direction) -> None
def _ent_find_aimed(self) -> int | None     # ray-AABB (billboard) or ray-OBB (prism)
def _ent_world_pos(self) -> tuple[float, float] | None
def _ent_place(self) -> bool                 # with UID assignment
def _ent_select/deselect(self, idx) -> None
def _ent_delete(self, idx) -> bool
def _ent_move_to_aimed(self) -> bool
def _ent_rotate(self, direction) -> bool     # 8-dir angle snapping for prisms
def _ent_cycle_state(self) -> None
```

#### `tools_box.py` — `BoxMixin` (335 lines)

```python
def _box_find_aimed(self) -> int | None      # ray-OBB for each prism
def _box_find_aimed_face(self) -> tuple | None
def _box_snap_pos(self, wx, wz) -> tuple     # quarter-cell grid snap
def _box_stack_height(self, wx, wz, w, d) -> float  # auto-stack on geometry + prisms
def _box_place(self) -> bool                 # with per-face textures
def _box_select/deselect/delete(self, idx)
def _box_move_to_aimed(self) -> bool
def _box_rotate_90/rotate_fine(self, direction) -> bool
def _box_adjust_size(self, direction, axis) -> bool
def _box_shift_z(self, direction) -> bool
def _box_toggle_snap(self) -> None
```

#### `tools_layer2.py` — `Layer2Mixin` (493 lines)

Secondary floor/ceiling layer editing.

```python
LAYER_NONE = -1000.0    # sentinel for "no L2 data"

@property
def _layer2_effective_target(self) -> str   # "floor2" or "ceil2"

def _layer2_ensure_grids(self) -> None      # lazy-init floor2_heights, ceil2_heights, etc.
def _layer2_raise_at/lower_at(self, r, c) -> bool
def _layer2_raise/lower(self, shift, ctrl=False) -> bool
def _layer2_paint(self) -> bool
def _layer2_toggle_target(self) -> None     # switch floor2 ↔ ceil2
def _layer2_scroll(self, direction) -> bool
def _layer2_scroll_upper_wall2(self, direction) -> bool
def _layer2_reset_at(self, r, c) -> bool
def _layer2_reset/sel_scroll(self, direction) -> bool
def _layer2_paint_at/erase_at(self, r, c) -> bool
def _layer2_pick_texture(self) -> None
def _layer2_flatten_floors/ceilings(self) -> bool
def _layer2_toggle_ceil(self) -> bool
def _layer2_delete_aimed(self) -> bool
```

#### `tools_quad.py` — `QuadMixin` (300 lines)

```python
def _quad_find_aimed(self) -> int | None     # thin-slab AABB
def _quad_find_aimed_t(self) -> tuple | None
def _quad_place(self) -> bool                # with grid snap
def _quad_select/deselect/delete(self, idx)
def _quad_move_to_aimed/rotate/adjust_size/toggle_twosided/paint
```

#### `tools_portal.py` — `PortalMixin` (300 lines)

```python
def _portal_find_at_face(self) -> int | None  # search by cell+face (not ray-picked)
def _portal_place/delete/cycle/deselect
```

Portals are wall-face-based: `{cell: [r, c], face: 0-3, dest_x, dest_y, angle_offset}`.

#### `tools_curve.py` — `CurveMixin` (300 lines)

```python
def _curve_find_aimed(self) -> int | None    # bounding-box AABB
def _curve_place(self) -> bool               # 180° half-circle default
def _curve_select/deselect/delete/move_to_aimed
def _curve_adjust_radius/adjust_angle_start/adjust_angle_end/paint
```

#### `tools_overlay.py` — `OverlayWallMixin` (300 lines)

Two-click placement workflow.

```python
def _ow_begin_place(self) -> None            # stores start point
def _ow_finish_place(self) -> bool           # creates OverlayWall
def _ow_find_aimed(self) -> int | None       # midpoint ray distance
def _ow_hit_world(self) -> tuple | None      # ground-plane intersection
def _ow_select/deselect/delete/move_to_aimed
def _ow_adjust_height/toggle_transparent/paint
```

Uses `core.zones.zone.OverlayWall` dataclass.

---

### `cell_ops.py`

Backwards-compatible re-exports from `editor.zone_ops`:

```python
from editor.zone_ops import reset_cell, clear_cell_textures, DEFAULT_FLOOR, SKY_HEIGHT, LAYER_NONE
```

---

## Zone Data Model Summary

The zone is a 2D grid of cells, each with:

| Grid | Dimensions | Type | Description |
|------|-----------|------|-------------|
| `tiles` | [H][W] | `str` | Tile type key (wall or open) |
| `floor_heights` | [H][W] | `float` | Floor elevation |
| `ceil_heights` | [H][W] | `float` | Ceiling elevation (SKY_HEIGHT = open sky) |
| `floor_textures` | [H][W] | `str` | Floor texture override |
| `ceil_textures` | [H][W] | `str` | Ceiling texture override |
| `wall_textures` | [H][W] | `str` | Wall texture (uniform) |
| `face_textures` | [H][W][4] | `str` | Per-face textures (N/S/E/W) |
| `floor_step_textures` | [H][W][4] | `str` | Floor step face textures |
| `ceil_step_textures` | [H][W][4] | `str` | Ceiling step face textures |
| `wall_segments` | [H][W][4][segs] | `[str, float]` | Wall segments: [(texture, y_top), ...] |
| `floor_step_segments` | [H][W][4][segs] | `[str, float]` | Floor step segments |
| `ceil_step_segments` | [H][W][4][segs] | `[str, float]` | Ceiling step segments |
| `upper_wall_height` | [H][W] | `float` | Extended wall above ceiling |
| `light_levels` | [H][W] | `float` | 0.0–1.0 ambient brightness |
| `reflect_map` | [H][W] | `int` | Floor reflectivity (0–255) |
| `fog_density` | [H][W] | `float` | Fog amount |
| **Layer 2** | | | |
| `floor2_heights` | [H][W] | `float` | Secondary floor (-1000 = none) |
| `ceil2_heights` | [H][W] | `float` | Secondary ceiling |
| `floor2_textures` | [H][W] | `str` | L2 floor texture |
| `ceil2_textures` | [H][W] | `str` | L2 ceiling texture |
| `upper_wall_height2` | [H][W] | `float` | L2 extended wall |
| **Object lists** | | | |
| `entities` | `list[dict]` | | `{type, x, y, angle, state, uid, overrides}` |
| `boxes` | `list[dict]` | | `{x, y, z, w, h, d, yaw, uid, textures, collision}` |
| `quads` | `list[dict]` | | `{x, z, base_y, width, height, angle, texture, two_sided, uid}` |
| `render_portals` | `list[dict]` | | `{cell, face, dest_x, dest_y, angle_offset, uid}` |
| `curves` | `list[dict]` | | `{cx, cy, radius, angle_start, angle_end, height_scale, base_y, texture, uid}` |
| `overlay_walls` | `list[OverlayWall]` | | `OverlayWall(x1, y1, x2, y2, height_scale, texture, transparent, blocks, uid)` |
