# Zone Editor — Architectural Reference

> **Scope.** This document describes the complete structure, control flow,
> input routing, UI layout, data model, command system, rendering
> pipelines, and interaction principles of the standalone Zone Editor
> (`zone_editor.py`) as of 2026-03-07.  It is written to be precise
> enough that structural weaknesses are visible through the description
> itself — if a problem exists in the code, it should be identifiable
> from this document alone.

---

## Table of Contents

1. [Entry Point & Lifecycle](#1--entry-point--lifecycle)
2. [Composition Architecture](#2--composition-architecture)
3. [Input System](#3--input-system)
4. [View Modes](#4--view-modes)
5. [Mode / Tool System](#5--mode--tool-system)
6. [Command Bus & Event Bus](#6--command-bus--event-bus)
7. [Selection System](#7--selection-system)
8. [Undo / Redo](#8--undo--redo)
9. [Picking / Aiming](#9--picking--aiming)
10. [UI Layout](#10--ui-layout)
11. [Dialog Manager](#11--dialog-manager)
12. [Zone Data Model](#12--zone-data-model)
13. [Persistence](#13--persistence)
14. [Zone Operations (Dialogs)](#14--zone-operations-dialogs)
15. [Asset Browser](#15--asset-browser)
16. [Keybind System](#16--keybind-system)
17. [Camera System](#17--camera-system)
18. [Rendering Pipeline Comparison](#18--rendering-pipeline-comparison)
19. [Preset System](#19--preset-system)
20. [Core Engine Dependencies](#20--core-engine-dependencies)
21. [Cross-Cutting Concerns](#21--cross-cutting-concerns)
22. [File Map](#22--file-map)

---

## 1  Entry Point & Lifecycle

```
zone_editor.py              22-line launcher: parses sys.argv[1], instantiates ZoneEditorApp
  └─ editor/app/            application package
       ├─ __init__.py        re-exports ZoneEditorApp
       └─ app.py             ZoneEditorApp class — __init__ (~150 lines) + run()
```

`ZoneEditorApp(zone_name).run()` is the entire public API.  `run()` is a
synchronous `while running:` loop at a 60 FPS target with no separate
threads, no async, no coroutines.  Every subsystem — input polling,
camera movement, raycasting, 3D rendering, ImGui panel construction,
and GL blitting — executes serially inside a single frame tick.

### 1.1  Frame Sequence

```
┌──────────────────────────────────────────────────────────┐
│  clock.tick(60) → dt                                     │
│  ↓                                                       │
│  _process_events()          # drain pygame event queue   │
│    ├─ QUIT         → _should_keep_running_after_quit()   │
│    ├─ VIDEORESIZE  → rescale panels, invalidate viewport │
│    ├─ uncaptured   → forward to imgui                    │
│    └─ all events   → input_stack.dispatch(event, self)   │
│  ↓                                                       │
│  if mouse_captured:                                      │
│    ├─ 3D mode: editor_3d.update(dt)  (camera + aim)     │
│    └─ 2D mode: _update_raycaster(dt) (WASD + look)      │
│  ↓                                                       │
│  _render_frame()                                         │
│    ├─ _render_viewport()  → pygame Surface               │
│    │    ├─ 3D: editor_3d.draw(surface)                   │
│    │    └─ 2D: renderer.render() + scale                 │
│    ├─ upload_surface() → GL texture (glTexImage2D)       │
│    ├─ _draw_fullscreen_quad()  (viewport behind ImGui)   │
│    └─ imgui.new_frame() → _build_ui() → imgui.render()  │
│  ↓                                                       │
│  pygame.display.flip()                                   │
└──────────────────────────────────────────────────────────┘
```

### 1.2  Initialization Sequence (`__init__`)

The constructor (~150 lines in `app.py`) creates the entire editor in
strict serial order:

1. **Pygame + OpenGL** — `pygame.display.set_mode()` with `OPENGL|DOUBLEBUF|RESIZABLE`
2. **ImGui** — `imgui.create_context()` + pygame-OpenGL renderer
3. **Theme** — `setup_theme()` applies ~30 colour overrides
4. **Asset registry** — `GameRegistry` for tile/texture/prefab string↔uint16 mapping
5. **Session** — `load_session()` from `editor_session.json` (MRU, layout, bookmarks)
6. **Input stack** — `InputStack` with `GlobalShortcutsContext` pushed as bottom layer
7. **Dialog manager** — `DialogManager` replacing scattered boolean flags
8. **Zone loading** — load from disk or create default 20×20 blank zone
9. **3D editor** — `Zone3DEditor(zone, registry)` with its own 18-mixin tree
10. **Raycaster** — `RayRenderer(zone, atlas, 640, 360, fov, dn, pitch_max)`
11. **Viewport state** — GL texture ID, pygame Surface, dirty flag
12. **Dialog state** — ~20 groups of booleans, strings, ints for each dialog
13. **Camera** — raycaster camera state (`px`, `py`, `angle`, `pitch`, `cam_h`)
14. **Bookmarks** — camera pose snapshots keyed by zone name
15. **Mixin init** — `_ab_init()` (asset browser caches)

**Weakness:** The constructor sets ~120+ instance attributes across a
flat namespace.  There is no structured state object, no dataclass for
configuration, no validation.  If any attribute is misspelled or
reordered, failures are silent and deferred to runtime.

**Weakness:** The GL upload path calls `glTexImage2D` with a fresh
`pygame.image.tostring()` every dirty frame.  For a 1600×900 viewport
this is ~5.5 MB of CPU→GPU transfer per frame.  A `_vp_dirty` flag
avoids re-upload when idle, but any camera movement forces a full
re-upload.  No PBO, no texture streaming, no partial updates.

**Weakness:** The viewport surface is software-rendered (pygame
`Surface.blit` / per-pixel C raycaster), then uploaded to a GL texture
solely so it can be drawn behind the ImGui overlay.  This dual-pipeline
(pygame SW + OpenGL HW) exists because ImGui's pygame integration
requires an OpenGL context, but the 3D editor and raycaster are entirely
CPU-rendered.  GL is used for nothing except the viewport quad and ImGui
draw calls.

---

## 2  Composition Architecture

`ZoneEditorApp` uses **cooperative multiple inheritance** (mixins) to
split responsibilities across files.  The MRO is:

```
ZoneEditorApp
 ├─ DialogPropertyBridge   editor/dialog_manager.py      property descriptors for dialog state
 ├─ EventsMixin            editor/app/events.py           input event routing + transient flash
 ├─ ViewportMixin          editor/app/viewport.py         GL quad rendering + surface upload
 ├─ RaycasterMixin         editor/app/raycaster.py        2D preview camera + movement
 ├─ PanelsMixin            editor/app/panels_pkg/         ImGui UI composition
 │    ├─ MenuBarMixin        panels_pkg/menu_bar.py       top menu bar
 │    ├─ ToolboxMixin        panels_pkg/toolbox.py        left panel
 │    ├─ InspectorMixin      panels_pkg/inspectors.py     right panel (1,723 lines)
 │    └─ OverlaysMixin       panels_pkg/overlays.py       help + keybind editor
 ├─ DialogsMixin           editor/app/dialogs.py          modal dialogs (1,106 lines)
 ├─ AssetBrowserMixin      editor/app/asset_browser.py    texture browser
 └─ DataViewersMixin       editor/app/data_viewers.py     TOML data browsers
```

**9 mixins** (counting `DialogPropertyBridge`) compose the application.
`PanelsMixin` is itself a 4-mixin diamond.  Total application-layer code:
~3,500 lines across 11 files.

There are **no formal interfaces** between mixins.  Every mixin reads
and writes attributes on `self` by convention.  The entire set of shared
state (zone, editor_3d, renderer, dirty flag, panel widths, dialog
booleans, session dict, transient flash state) is implicitly declared in
`__init__` and accessed freely by any mixin.

**Weakness:** This is a flat namespace with ~120+ mutable attributes on a
single object.  There is no access control, no type checking at the
boundary, and no way to determine which attributes a mixin requires or
modifies without reading its source.  Adding a new mixin or renaming an
attribute risks silent breakage.

**Weakness:** The `Zone3DEditor` (`editor_3d`) is itself a massive mixin
tree (18 mixins) that the app reaches into directly (`self.editor_3d.snap_idx`,
`self.editor_3d._undo()`, `self.editor_3d.selection`, etc.).  There is
no façade or command interface between the app layer and the editor's
internal state — the app treats the editor's private attributes as
public API.

---

## 3  Input System

### 3.1  Input Stack Architecture

Input routing uses a **stack-based context system** defined in
`editor/input_context.py`:

```
InputContext (ABC)
  name: str
  blocks_below: bool = False
  handle_event(event, app) → bool   # True = consumed
  on_push(app) / on_pop(app)         # lifecycle hooks

InputStack
  push(ctx, app) / pop(app) / remove(name, app)
  dispatch(event, app)   # walk top→bottom, stop on consume or blocks_below
  is_captured             # checks for "captured_viewport" context
```

The stack always contains `GlobalShortcutsContext` at the bottom.  When
the viewport is captured, `CapturedViewportContext` is pushed on top.

### 3.2  `GlobalShortcutsContext` (editor/contexts.py)

Handles input when uncaptured (and any events that bubble through from
captured state):

```
Ctrl+S           → save
Ctrl+Shift+S     → save as
Ctrl+Z           → undo (via editor_3d._undo())
Ctrl+Y / Ctrl+Shift+Z → redo
TAB              → toggle 3D/2D view
Ctrl+N           → new zone (guarded)
Ctrl+F           → find/replace texture
Shift+1-9        → recall camera bookmark
Ctrl+Shift+1-9   → save camera bookmark
Enter/F5         → capture viewport
Escape           → close dialog → quit
LMB on viewport  → capture viewport
```

### 3.3  `CapturedViewportContext` (editor/contexts.py)

Pushed when the viewport captures input.  Lifecycle hooks call
`app._do_capture_mouse()` / `app._do_release_mouse()` (hide/show cursor,
grab/ungrab).

**Escape priority chain:**
1. *(StampCaptureContext sits above — intercepts Escape during naming)*
2. Deselect object-layer objects (entity, box, quad, curve, overlay)
3. Cancel active cell selection / rectangle drag
4. Pop self (release mouse) → uncaptured

Steps 2–3 keep the viewport captured.  Step 4 pops the context and
releases the mouse.  Selection is clearable by Escape regardless of the
active tool (not limited to the `"select"` tool).

**Event routing:**
- Global shortcuts (detected via `_is_global_shortcut()` helper) are **not
  consumed** — they bubble down to `GlobalShortcutsContext`
- All other keys forwarded to `editor_3d.handle_event()`
- Mouse events forwarded to `editor_3d` in 3D view
- Scroll events forwarded with transient UI feedback

### 3.3b  `StampCaptureContext` (editor/contexts.py)

Pushed by the per-event **input context sync** (`_sync_input_contexts()`
in `events.py`) when `editor_3d._capture_pending` is True and the tool
is `"stamp"`.  This context intercepts **all KEYDOWN** events for
preset-name typing:

- **Printable characters** → appended to name buffer
- **Backspace** → delete last character
- **Enter** → commit (via `_stamp_capture_key() → _stamp_capture_commit()`),
  then pop self
- **Escape** → pop self; `on_pop()` cancels naming

Non-key events (mouse, scroll) pass through to `CapturedViewportContext`
below so the viewport keeps rendering.

The sync runs **before every event** in the `_process_events()` pump,
ensuring that state changes from the previous event (e.g.
`_stamp_capture_begin()` setting `_capture_pending = True`) are reflected
on the stack in time for the very next event.

**Weakness:** `_is_global_shortcut()` checks the keybind registry for a
hardcoded list of `_GLOBAL_ACTIONS` plus manually coded combos
(Ctrl+Shift+S, Ctrl+N, Ctrl+F, bookmark combos).  Adding a new global
shortcut requires updating both the registry and this function.

**Weakness:** When captured, imgui receives *no* events at all (the
`process_event` call is skipped).  This means no ImGui widget can be
interacted with while editing, and any stale imgui mouse state from the
instant before capture can produce ghost hover highlights in the next
uncaptured frame.  The mitigation is `_clear_imgui_input_state()` which
manually zeroes every imgui input flag — a brittle band-aid that must be
updated if imgui's API changes.

### 3.4  Keyboard Dispatch in 3D Editor

Within the `CapturedViewportContext`, events reach `editor_3d.handle_event()`
→ `_on_keydown()`, a ~250-line method with strict priority order:

```
Priority 1:  Modifier combos       Ctrl+S, Ctrl+Z/Y, Ctrl+A/D/C/V, Ctrl+1-5, Alt+I
Priority 2:  Mode switches          F1–F4 (Arch/Surface/Props/Logic)
Priority 3:  Sub-tool selection     1–5 within current mode
Priority 4:  Select tool toggle     B
Priority 5:  Utility toggles        P (stamp), I (quad), O (portal), ; (curve)
Priority 6:  Tab = cycle tools
Priority 7:  Selection batch ops    X, T, H, L, U, Del (only when selection active)
Priority 8:  Display toggles        F10 (axes)
Priority 9:  Per-tool actions       R (reset/rotate), G (snap), M (stamp mode)
Priority 10: Help                   ?
```

**Note:** Escape and stamp-capture-naming are no longer handled here.
Escape is resolved by the InputStack (see §3.3).  Stamp naming is
intercepted by `StampCaptureContext` (see §3.3b) before events reach
this method.
```

Implemented as ~60+ `kb.check()` calls against the `KeybindRegistry`,
each passing `scope=tool` so the registry enforces tool-scoping
structurally.

**Weakness:** The scope field on keybinds is a pipe-delimited string
(`"sculpt|select|paint"`) and the registry's `check()` method enforces
scope matching strictly — non-global keybinds only fire when the caller
passes a matching scope.  Scope is always enforced (never bypassed).

### 3.5  Click Dispatch in 3D Editor

`_on_click()` uses a tool-priority `if/elif` chain (~250 lines):

```
tool="sculpt"  → floor/ceiling raise/lower (LMB/RMB), eyedropper (MMB)
tool="paint"   → paint/erase/eyedropper, flood-fill (Ctrl+LMB), prism/quad paint
tool="select"  → rectangle, line, toggle (LMB), clear (RMB), flood-select
tool="segment" → split/merge/paint (LMB/RMB/MMB)
tool="stamp"   → apply/capture (LMB/RMB)
tool="entity"  → place/select/move/delete (context-dependent LMB/RMB)
tool="box"     → place/select/move/delete (context-dependent LMB/RMB)
tool="quad"    → same pattern
tool="portal"  → place/delete (LMB/RMB)
tool="curve"   → same pattern
tool="overlay" → two-click placement / select / move / delete
fallback: MMB  → universal eyedropper
```

Most tool blocks dispatch through the **command bus** (see §6), wrapping
the operation in a `cmd_bus.execute(SomeCommand(...))` call.  Some blocks
still call legacy mixin methods directly.

### 3.6  Scroll Dispatch

`_on_scroll()` (~150 lines): palette cycling, object resizing/rotation,
snap cycling, or batch height adjustment — all depending on tool +
modifiers + selection state.  Dispatches through command bus for
mutation operations.

---

## 4  View Modes

### 4.1  3D Wireframe Editor (`Zone3DEditor`)

The primary editing view.  Software-rendered using pygame line/polygon
drawing with a custom perspective projection pipeline.

```
Zone3DEditor (editor/view_3d/editor.py — 1,981 lines)
 ├─ RenderingMixin      rendering.py (2,197 lines)  draw(), skybox, HUD, all visual output
 ├─ DrawPrimitivesMixin primitives.py (277 lines)   _line3d, _box, _filled_box, _filled_rotated_box
 ├─ SculptMixin         tools_sculpt.py (839 lines) floor/ceiling height, cell type, upper wall
 ├─ PaintMixin          tools_paint.py (474 lines)  texture painting/erasing/eyedropper
 ├─ FillMixin           tools_fill.py (398 lines)   BFS flood-fill across surfaces
 ├─ EraseMixin          tools_erase.py (114 lines)  cell reset, height reset, texture clear
 ├─ SelectMixin         tools_select.py (284 lines) rectangular selection + batch ops
 ├─ SegmentMixin        tools_segment.py (282 lines) wall segment split/merge/paint/auto
 ├─ StampMixin          tools_stamp.py (149 lines)  preset apply/capture with naming
 ├─ EntityMixin         tools_entity.py (255 lines) entity CRUD + palette cycling
 ├─ BoxMixin            tools_box.py (334 lines)    freeform prism CRUD + auto-stacking
 ├─ Layer2Mixin         tools_layer2.py (492 lines) secondary floor/ceiling layer
 ├─ QuadMixin           tools_quad.py (257 lines)   two-sided quad/fence CRUD
 ├─ PortalMixin         tools_portal.py (102 lines) render portal CRUD
 ├─ CurveMixin          tools_curve.py (219 lines)  curved wall CRUD
 ├─ OverlayWallMixin    tools_overlay.py (266 lines) free-form overlay wall CRUD
 ├─ GeometryMixin       geometry.py (167 lines)     cell box computation + layer filtering
 ├─ UndoMixin           undo.py (226 lines)         snapshot undo/redo
 └─ SaveMixin           save.py (31 lines)          zone serialisation
```

**18 mixins**, one `__init__` in `editor.py`, estimated total:
**~8,900 lines** for the 3D editor alone.

#### Key `Zone3DEditor` Attributes (set in `__init__`)

| Category | Attributes |
|:---------|:-----------|
| **Camera** | `cam_x`, `cam_y`, `cam_z`, `yaw`, `pitch` |
| **Snap** | `snap_y`, `snap_idx`, `SNAP_Y_OPTIONS` |
| **Texture** | `tex_idx`, `current_texture`, `hotbar` (10 slots), `hotbar_slot` |
| **Tool** | `tool` (str), `_prev_tool`, `mode` (arch/surf/props/logic) |
| **Layers** | `active_layer` (1 or 2), `isolate_layer` (bool), `_sculpt_layer2` property |
| **Clipboard** | `_clipboard` (dict), `_paste_mask` (bitfield) |
| **Buses** | `event_bus` (EventBus), `cmd_bus` (CommandBus) |
| **Selection** | `selection` (SelectionStore), `objects` (ObjectLayer) |
| **Aim** | `aimed` (_CellHit or None), `_cell_box_cache` (dict) |
| **Undo** | `_undo_stack`, `_redo_stack`, `_UNDO_MAX=50` |
| **Visibility** | `show_walls/floors/ceilings/entities/axes/hud`, `wireframe` |
| **Flash** | `_flash_text`, `_flash_timer`, `_flash_color` |
| **Keybinds** | `kb` (KeybindRegistry) |

#### Phase 2 Selection Bridge

Properties `_ent_selected`, `_box_selected`, `_quad_selected`,
`_portal_selected`, `_curve_selected`, `_ow_selected` use
`_sel_bridge_get(type_tag)` / `_sel_bridge_set(type_tag, value)` to
translate between legacy integer-index selection and UID-based
`SelectionStore`.  This maintains backward compatibility during the
selection migration.

#### Rendering Pipeline

```
draw(surface)
 ├─ _draw_skybox_bg()             cylindrical panorama w/ yaw+pitch
 ├─ build mat_vp (view × proj)    _build_view_matrix × _perspective
 ├─ _extract_frustum_planes()     6 normalised Hessian planes
 ├─ _visible_cell_set()           check all cells against frustum
 ├─ _draw_axes()                  X/Y/Z coloured lines
 ├─ depth-sort visible cells (back-to-front)
 ├─ for each cell:
 │    ├─ _draw_cell_boxes()       _filled_box() per part (floor, ceiling, wall)
 │    │    with per-face colours from _get_face_colors()
 │    ├─ _draw_cell_segments()    segment colour band overdraw
 │    ├─ _draw_surface_markers()  height indicator lines
 │    └─ _draw_seg_boundary_rings()
 ├─ _draw_layer2_slabs()          L2 floor2/ceiling2 with face shading
 ├─ _draw_entities()              solid OBB boxes + direction arrows + labels
 ├─ _draw_boxes()                 rotated shaded prisms + ghost preview
 ├─ _draw_quads()                 vertical rectangles + diagonal cross
 ├─ _draw_portals()               face outlines + translucent fill + destination lines
 ├─ _draw_curves()                arc wireframes (16 sample points per curve)
 ├─ _draw_overlay_walls()         vertical rectangles + transparency/passability indicators
 ├─ _draw_selection_highlight()   green translucent cell overlay + rect preview
 ├─ _draw_face_hl_and_preview()   aimed face accent + prism/quad highlights + merge target
 ├─ _draw_crosshair()             tool-coloured + L2 badge + height ticks
 ├─ _draw_action_context()        LMB/RMB/Scroll hints near crosshair
 ├─ _draw_hotbar()                10-slot texture palette at bottom edge
 └─ _draw_hud()                   top-left status text
```

**Weakness:** The entire scene is rendered with **per-vertex software
projection** (`_project()` for every box corner, line endpoint, polygon
vertex).  No spatial acceleration structures; all cells within frustum
are iterated.  For a 100×100 zone, this means projecting ~8000+ vertices
per frame in Python with O(n log n) back-to-front sort.

**Weakness:** Drawing uses `pygame.draw.line` and
`pygame.draw.polygon` on a software Surface.  No batching, no vertex
buffers, no GPU-accelerated wireframe.  Every line is a separate
Python → C call through pygame's SDL wrapper.

**Weakness:** Back-to-front sort is **per-cell**, not per-face.  Two
overlapping cells can produce incorrect draw order for individual faces.
Alpha blending uses a scratch `pygame.Surface` created per translucent
face — a workaround for pygame's lack of per-pixel alpha in polygon draws.

### 4.2  Raycaster Preview (`RaycasterMixin`)

A real-time 2.5D raycaster view using the C-extended `RayRenderer`.
WASD movement with noclip toggle, collision detection, and smooth camera
interpolation.

```
_update_raycaster(dt)
 ├─ mouse look → yaw, pitch (clamped ±0.30π via _PITCH_MAX)
 ├─ WASD → 2D displacement (resolved from keybind registry with fallback)
 ├─ try_move() with axis-separated collision using renderer.can_step_to()
 └─ camera height lerp toward player_fh + EYE_HEIGHT
```

Camera state is transferred between 3D↔2D when toggling (Tab):

```
3D → 2D: cam_x→px, cam_z→py, yaw→angle (+90° offset), pitch clamped
2D → 3D: px→cam_x, py→cam_z, angle→yaw (-90° offset), pitch copied
```

Raycaster-specific keys: `I` (toggle interior flag), `G` (toggle noclip).

**Weakness:** The coordinate conventions differ between the two views.
The 3D editor uses (cam_x, cam_z) with yaw=0→+Z, while the raycaster
uses (px, py) with angle=0→+X.  The 90° offset on toggle is easy to get
wrong and has no validation.

**Weakness:** The raycaster has its own pitch limit
(`_PITCH_MAX = π*0.30`) defined as a class variable, while the 3D editor
uses `clamp_pitch()` from `fly_camera.py` with `PITCH_LIMIT = π*0.45`.
The two views have different vertical look ranges with no shared constant.

---

## 5  Mode / Tool System

### 5.1  Mode State Machine

The editor has a **two-tier** selection system: **Mode** (editing category)
and **Tool** (specific operation).

```
Modes (F1–F4):                          Constants in view_3d/constants.py
  ┌──────────┬─────────────────────────────────────┐
  │ arch     │ sculpt, segment                     │
  │ surface  │ paint                               │
  │ props    │ box, quad, curve, overlay            │
  │ logic    │ entity, portal                      │
  └──────────┴─────────────────────────────────────┘

Utility tools (toggle with dedicated key, mode-independent):
  B → select    P → stamp    I → quad    O → portal    ; → curve
```

The mode→tool mapping is defined in `MODE_TOOLS` (dict in
`view_3d/constants.py`).  Switching modes auto-selects the first tool in
the new mode's list if the current tool is not present.

Each mode has labels, icons, colours, and descriptions defined in parallel
dicts (`MODE_LABELS`, `MODE_ICONS`, `MODE_COLORS`, `MODE_DESCRIPTIONS`).

Tool metadata is similarly parallel: `TOOL_LABELS`, `TOOL_COLORS`,
`TOOL_HINTS` (per-tool action description strings).

`_leave_tool(old)` provides cleanup when switching tools (e.g. cancelling
in-progress overlay wall placement).

**Weakness:** The utility tool keys (I, O, ;) overlap with the mode tool
set.  Quad is in `MODE_TOOLS["props"]` as a regular tool *and*
accessible as a utility toggle via `I`.  Portal is in
`MODE_TOOLS["logic"]` *and* accessible via `O`.  Two code paths enter
the same tool — mode's number key vs. utility toggle — with slightly
different state (the toggle preserves `_prev_tool`, the mode switch
does not).

**Weakness:** `mode` and `tool` are independent strings with no enforced
relationship.  You can be in mode `"arch"` with tool `"entity"` if
manual attribute mutation bypasses mode-switch guards.  Guards only run
on the switch action, not on access.

### 5.2  Active Layer

`active_layer: int` (1 or 2) plus `isolate_layer: bool`.

- **Layer 1:** Primary floor/ceiling/wall grids.
- **Layer 2:** Secondary floor2/ceil2 for catwalks, bridges, pits.
  Uses sentinel `LAYER_NONE = -1000.0` for "no L2 data".

`_sculpt_layer2` is a property alias returning `active_layer == 2`.

**Layer routing is fragmented:** `SculptMixin`, `PaintMixin`,
`SelectMixin`, and `Layer2Mixin` each independently check
`self._sculpt_layer2` and branch to different grid accessors.
`Layer2Mixin` provides `_layer2_ensure_grids()` for lazy allocation.

**Weakness:** Layer awareness is opt-in per tool method.  A tool that
forgets to check the layer writes to L1 silently.  There is no
layer-dispatch abstraction (e.g. a method returning the correct height
grid for the active layer); each call site manually tests and branches.

---

## 6  Command Bus & Event Bus

### 6.1  Architecture

The `editor/commands/` package provides a typed command-dispatch layer
for centralised mutation and undo management:

```
editor/commands/
  __init__.py          re-exports Command, BatchCommand, CommandBus, EventBus
  base.py              Command (frozen dataclass), BatchCommand, EventBus, CommandBus
  events.py            StateChanged, SelectionChanged, ToolChanged, ViewDirtied
  sculpt_cmds.py       19 sculpt commands + handlers
  paint_cmds.py        12 paint/erase/fill commands + handlers
  erase_cmds.py         3 eraser commands + handlers
  l2_cmds.py           14 layer-2 commands + handlers
  object_cmds.py       27 object commands + handlers (entity/box/quad/portal/curve/overlay)
  segment_cmds.py       3 segment commands + handlers
  select_cmds.py        3 selection batch commands + handlers
  stamp_cmds.py         1 stamp command + handler
  misc_cmds.py          3 miscellaneous commands + handlers (clipboard, duplicate, object delete)
```

**Total: 85 command dataclasses, 85 handler closures, 9 registration functions.**

### 6.2  Command Protocol

```python
@dataclass(frozen=True)
class Command:
    """Immutable mutation descriptor."""

@dataclass(frozen=True)
class BatchCommand(Command):
    children: tuple[Command, ...]   # executed under single undo entry
```

All commands are frozen dataclasses.  They carry parameters but no logic
— the handler provides the implementation.

### 6.3  CommandBus

```
CommandBus
  _handlers: dict[type → Callable[[Command], bool]]
  _editor:   Zone3DEditor reference
  _event_bus: EventBus reference

  register(cmd_type, handler)
  execute(cmd)                # push undo → ensure face textures → handle → dirty → emit
  execute_continuation(cmd)   # NO undo push (for drag-paint/continuous strokes)
  _execute_batch(batch)       # single undo → iterate children → single emit
  undo() / redo()             # delegates to editor._undo() / editor._redo()
```

**Lifecycle of `execute(cmd)`:**
1. `editor._push_undo()` — full zone snapshot
2. `editor._ensure_face_textures()` — lazy grid allocation
3. Look up handler for `type(cmd)`, invoke it
4. Set `editor.dirty = True`
5. `event_bus.emit(StateChanged(source_command=cmd))`

For `BatchCommand`: step 1 happens once, step 3 repeats per child.

**`execute_continuation(cmd)`** skips step 1 entirely — used for drag
gestures where the initial click already pushed undo.  Does not support
`BatchCommand`.

### 6.4  Handler Factory Pattern

Every handler is a closure produced by a factory:

```python
def _make_floor_raise_handler(editor):
    def _handle(cmd):
        return editor._floor_raise_at(cmd.cell[0], cmd.cell[1])
    return _handle
```

This avoids module-level `editor` references and makes handlers
independently testable.  Each `*_cmds.py` module exposes one
`register_*_handlers(bus, editor)` function that bulk-registers all
its handlers.

### 6.5  Undo Suppression Helpers

Many legacy mixin methods call `_push_undo()` internally.  Since the bus
already pushes undo before the handler runs, a duplicate push would
corrupt the stack.  Three helpers in `base.py` handle this:

| Helper | Technique | Use Case |
|:-------|:----------|:---------|
| `suppress_undo(editor, fn, *a)` | Monkey-patches `_push_undo` to `lambda: None` | Methods that return `bool` AND call `_push_undo` |
| `detect_change(editor, fn, *a)` | Saves `dirty`, zeroes it, calls fn, checks flip | Methods that don't return `bool` and don't push undo |
| `suppress_and_detect(editor, fn, *a)` | Combines both | Void methods that DO call `_push_undo` |

Each restores the original `_push_undo` in a `finally` block.

**Weakness:** Monkey-patching `_push_undo` at the instance level is the
central workaround for incremental migration.  It is fragile: if a method
calls `_push_undo` on a different object (e.g. through `ObjectLayer`),
the patch doesn't apply.  If two commands nest (which shouldn't happen
but has no guard), the patch can restore to the wrong function.

**Weakness:** The `detect_change` pattern relies on `editor.dirty` as a
signal for "did the handler actually mutate?"  But `dirty` is never
*unset* by the bus — it's only set to `True`.  So `detect_change` must
temporarily zero it and restore after, which means if a concurrent
mechanism checks `dirty` during the handler, it sees a false negative.

### 6.6  EventBus

```
EventBus
  _subs: dict[event_type → list[callback]]
  subscribe(type, cb) / unsubscribe(type, cb) / emit(event)
```

Synchronous delivery, no queue.  Currently only `StateChanged` is emitted
by the bus.  `SelectionChanged` is emitted by `SelectionStore`.
`ToolChanged` and `ViewDirtied` are defined but not yet emitted.

### 6.7  Command Coverage by Tool

| Tool | Migrated to Commands? | Command Count |
|:-----|:----------------------|:--------------|
| Sculpt (L1) | **Yes** | 19 |
| Paint (L1) | **Yes** | 12 |
| Erase | **Yes** | 3 |
| Layer 2 | **Yes** | 14 |
| Segment | **Yes** | 3 |
| Stamp | **Yes** | 1 |
| Entity | **Yes** | 4 |
| Box | **Yes** | 7 |
| Quad | **Yes** | 7 |
| Portal | **Yes** | 2 |
| Curve | **Yes** | 7 |
| Overlay Wall | **Yes** | 6 |
| Clipboard/Misc | **Yes** | 3 |
| Select (batch) | **Yes** | 3 |

All mutation paths are now routed through the command bus.  The legacy
`_push_undo()` calls inside mixin methods are suppressed by the bus
handlers using the helpers above.  Both paths share the same undo/redo
stacks.

---

## 7  Selection System

### 7.1  SelectionStore (Phase 2 — Current)

`editor/view_3d/selection_store.py` (430 lines) — the **UID-based**
single source of truth:

```
SelectionStore
  cells:       set[(row, col)]        grid cell selection
  _selected:   set[uid]               object UIDs
  _uid_types:  dict[uid → type_tag]   type lookup
  _primary:    uid | None             inspector target
  ceiling_mode: bool                  floor vs ceiling for batch ops
  anchor:      (row, col) | None      selection anchor cell
  _rect_origin / _rect_end            in-progress rectangle drag
  event_bus:   EventBus               emits SelectionChanged
```

**Cell API:** `select_cell`, `add_cell`, `toggle_cell`, `select_rect`,
`add_rect`, `select_line` (Bresenham), `select_all_cells`, `clear`

**Rectangle API:** `begin_rect`, `update_rect`, `finish_rect`,
`cancel_rect`, `rect_in_progress`, `rect_preview`

**Object API (UID-based):** `select_object(type_tag, uid)`,
`add_object`, `toggle_object`, `deselect_object`, `deselect_type`,
`deselect_all_objects`

**Primary selection:** `primary_uid`, `primary_type`,
`primary_index(zone)` — resolves UID to list index via linear scan

**Queries:** `is_object_selected(uid)`, `selected_uids_by_type`,
`iter_objects()` → yields `(type_tag, uid)`

**Backward compat:** `objects` property → `{(type_tag, uid), ...}` for
code still using the old interface.

### 7.2  SelectionState (Phase 1 — Legacy, retained)

`editor/view_3d/selection.py` (290 lines) — index-based selection.
Retained but being superseded.  Uses raw list indices, not UIDs.

`on_object_deleted(type_tag, index)` and `on_object_inserted(type_tag, index)`
shift indices — must be called manually at every insertion/deletion site.

### 7.3  ObjectLayer (Unified Dispatch)

`editor/view_3d/objects.py` (408 lines) — bridges tool-specific methods
with the selection system:

```
ObjectLayer
  _STORES:           type_tag → zone list name
  _FIND_METHODS:     type_tag → _*_find_aimed
  _SELECT_METHODS:   type_tag → _*_select
  _DESELECT_METHODS: type_tag → _*_deselect
  _DELETE_METHODS:   type_tag → _*_delete
  _MOVE_METHODS:     type_tag → _*_move_to_aimed

  find_aimed(types)     raycast all types, depth-sort, return closest
  select(hit, add)      UID multi-select + legacy singleton bridge
  toggle_select(hit)    toggle in/out of selection
  deselect_all()        clear all object selections
  delete_selected()     delete all selected (UID multi-select or singleton)
  move_selected_to_aimed()
```

**Weakness:** UID resolution uses linear scans through zone object lists
(`resolve_index(zone, type_tag, uid)`).  For zones with hundreds of
objects per type, this is O(n) per lookup.

**Weakness:** The `SelectionStore` bridge properties in `Zone3DEditor`
(`_ent_selected`, `_box_selected`, etc.) translate between UID and index
on every access.  This dual representation requires bidirectional sync.
A code path that sets `_ent_selected = idx` bypasses the store;
a path that modifies the store bypasses the legacy field.  Consistency
depends on all code flowing through the bridge.

---

## 8  Undo / Redo

`UndoMixin` (`editor/view_3d/undo.py`, 226 lines) implements
**snapshot-based** undo.

### 8.1  Snapshot Contents

Each `_push_undo()` deep-copies **every mutable grid and object list**:

```
2D grids (17):   tiles, floor_heights, ceil_heights, wall_textures,
                 floor_textures, ceil_textures, light_levels, rotations,
                 upper_wall_height, reflect_map, floor_slope_dx/dy/div,
                 floor2_heights, ceil2_heights, floor2_textures,
                 ceil2_textures, upper_wall_height2, fog_density, fog_color

3D grids (3):    face_textures, floor_step_textures, ceil_step_textures

4D grids (3):    wall_segments, floor_step_segments, ceil_step_segments

Object lists:    entities, boxes, quads, curves, render_portals, overlay_walls
```

Fast copiers: `_copy_grid` (2D), `_copy_grid_3d`, `_copy_grid_4d`,
`_copy_dict_list` (entities/boxes/quads), `_copy_overlay_walls`
(dataclass replace).

### 8.2  Stack Mechanics

- `_push_undo()` → take snapshot, push to `_undo_stack`, clear `_redo_stack`
- `_undo()` → push current state to redo, restore top of undo
- `_redo()` → push current state to undo, restore top of redo
- `_UNDO_MAX = 50`
- `_flash(text, duration, color)` for visual feedback

### 8.3  Memory Cost Analysis

For a 100×100 zone, one undo snapshot is approximately:
- 17 × 2D grids × 10,000 cells = 170,000 list items
- 3 × 3D grids × 10,000 × 4 = 120,000 sub-lists
- 3 × 4D grids × 10,000 × 4 = 120,000+ nested sub-lists

With `_UNDO_MAX = 50`, the stack can hold up to 50 × (410,000+ copied
list items) ≈ **20+ million** Python objects in memory.

**Weakness:** No differential/incremental undo, no compression, no disk
offload.  Every `_push_undo()` pays a full zone copy cost.  For large
zones, this causes a visible hitch.

**Weakness:** The command bus always pushes undo before the handler runs,
even if the handler ultimately makes no change (returns False / no-op).
This wastes a snapshot slot.  The bus does not pop the undo entry on
no-op.

**Weakness:** Continuous paint (LMB held drag) pushes one undo on the
initial click via `execute()`, then subsequent frames use
`execute_continuation()` which skips undo.  This relies on the caller
correctly tracking whether this is the first click vs. a continuation.
A logic error here either pushes too many undo entries (every drag step)
or too few (no undo at all).

---

## 9  Picking / Aiming

Every frame during `update()`, `_update_aim()` casts a ray from the
camera and finds the nearest cell box or ground plane hit.

```
_update_aim()
  ├─ Ground plane check (y=0 intersection)
  ├─ Frustum-filtered cell search
  │    ├─ for each visible cell: _layer_cell_boxes(r,c) → [(part, ybot, ytop)]
  │    └─ for each box:  _ray_vs_aabb() → (t, face_name)
  ├─ Select nearest hit → self.aimed (_CellHit)
  ├─ _compute_preview()    → sculpt ghost indicators (preview_line, preview_box)
  └─ _paint_update_aim()   → prism/quad hover detection for paint tool
```

`_CellHit` dataclass: distance `t`, cell `(col, row)`, `part`
(wall/floor/ceiling/floor2/ceiling2), `face` (north/south/east/west/
top/bot/ground), and `hit_y` (world Y at intersection).

### 9.1  Cell Box Generation

`GeometryMixin._cell_boxes(r, c)` (cached per frame via `_cell_box_cache`):
- Floor mass: `(floor, fh, fh + SLAB)` where `SLAB = 0.04`
- Ceiling mass: `(ceiling, ch, ch + uwh + SLAB)`
- Wall boxes: fill gaps between floor top and ceiling bottom
- Neighbour step walls (when adjacent floor heights differ)
- Sky exposure check

`_layer_cell_boxes(r, c)` filters by `active_layer` + `isolate_layer`,
adds L2 floor2/ceiling2 slabs.

### 9.2  Object Picking

Object picking runs **after** cell picking via separate per-type methods:

| Method | Object Type | Intersection |
|:-------|:------------|:-------------|
| `_ent_find_aimed()` | Entity | Ray-AABB, depth-sorted vs cell hit |
| `_box_find_aimed()` | Prism | `_ray_vs_obb()` (yaw-rotated) |
| `_box_find_aimed_face()` | Prism face | Ray-OBB → face name for paint |
| `_quad_find_aimed()` | Quad | Thin-slab AABB |
| `_curve_find_aimed()` | Curve | Bounding-box AABB approximation |
| `_ow_find_aimed()` | Overlay wall | Midpoint distance test |

`ObjectLayer.find_aimed(types)` unifies these: runs all per-type
iterators, sorts by estimated camera distance, returns closest hit.

**Weakness:** Each per-type find method iterates the **full** object list
independently.  No spatial index (BVH, octree, grid).  This is O(n)
per type per frame.

**Weakness:** Cell picking is brute-force over all frustum-visible cells
with 3–8 AABB tests per cell.  For large zones (~1000+ visible cells),
this is the dominant per-frame cost alongside vertex projection.

---

## 10  UI Layout

### 10.1  Fixed Three-Column Layout

```
┌─────────────────────────────────────────────────────────────┐
│ Menu Bar (full width)    File│Edit│View│Zone│Data│Window│FPS │
├─────────────────────────────────────────────────────────────┤
│ State Bar (Layer│View│Tab│Undo/Redo/Save│Keybinds)          │
├──────────┬──────────────────────────────────────┬───────────┤
│  Left    │        Central Viewport              │  Right    │
│  Panel   │    (3D wireframe or raycaster)       │  Panel    │
│          │                                      │           │
│ Toolbox  │    [capture hint / transient flash]  │ Inspector │
│ Palette  │                                      │ Cell      │
│ Snap     │                                      │ Object    │
│ Controls │                                      │ Zone      │
│ Select   │                                      │ Camera    │
├──────────┴──────────────────────────────────────┴───────────┤
│ Status Bar (zone name, mode, tool, layer, pos, selection)   │
└─────────────────────────────────────────────────────────────┘
```

Panel dimensions: `MENU_BAR_H=22`, `STATE_BAR_H=32`, `STATUS_BAR_H=28`,
`LEFT_PANEL_W=280`, `RIGHT_PANEL_W=250` (all configurable, persisted
in session).  Draggable splitters use invisible ImGui windows with
`invisible_button`.

### 10.2  Left Panel (ToolboxMixin — 469 lines)

```
_left_panel()
  ├─ _draw_tool_buttons()       2×2 mode grid + sub-tools + utility toggles
  ├─ _draw_snap_buttons()       Y-snap presets (1/16 → 1)
  ├─ _draw_brush_or_preset()    one of:
  │    ├─ _draw_texture_palette()   scrollable tile list with colour swatches
  │    ├─ _draw_preset_palette()    scrollable preset list (stamp tool)
  │    └─ _draw_entity_palette()    category-grouped entity list
  ├─ _draw_controls_section()   context-sensitive keybind hints
  └─ _draw_selection_info()     selection counts + clear/select all/delete
```

**Weakness:** The texture palette is a flat alphabetical list.  No
search/filter, no favourites, no categories, no thumbnails.  With many
custom tiles, finding the right texture requires scrolling.  The hotbar
(10 quick-slots at viewport bottom) mitigates this partially but has
no persistence across sessions.

### 10.3  Right Panel (InspectorMixin — 1,723 lines)

The largest single UI file.

```
_properties_panel()
  ├─ Zone header (name, size, dirty indicator)
  ├─ Object inspector (if any object selected):
  │    ├─ Entity:  position XYZ, angle, type, state, scale, loot, properties
  │    ├─ Prism:   position/size/yaw, texture per face (6 fields)
  │    ├─ Quad:    position/size/yaw, texture, two-sided toggle
  │    ├─ Portal:  cell/face, destination zone/cell/offset
  │    ├─ Curve:   center, radius, angle range, height, texture
  │    └─ Overlay: x1/y1/x2/y2, texture, height_scale, transparent, blocks
  ├─ Cell inspector (single cell or bulk):
  │    ├─ Coordinates + layer indicator
  │    ├─ Wall/open toggle
  │    ├─ Floor/ceil height input w/ relative expressions (=N, +N, -N, *N)
  │    ├─ Sky toggle (set ceil to 10.0 sentinel)
  │    ├─ Upper wall height
  │    ├─ Per-face textures (N/S/E/W) with autocomplete
  │    ├─ Segment tree view (per-face, expandable)
  │    └─ Layer 2 geometry fields (floor2/ceil2 heights, textures)
  ├─ Display toggles (walls/floors/ceilings/entities/wireframe)
  ├─ Zone list (all zones with switch/delete)
  ├─ Zone settings (skybox, sky colour, anchor)
  └─ Camera info (position, angles)
```

**Weakness:** The inspector always shows either aimed-cell data or
bulk-selection data, never both.  Multi-selected cells replace the
single-cell inspector with a summarised bulk view.  Individual cells
within a selection cannot be inspected without clearing the selection.

**Weakness:** Bulk inspector supports relative expressions (`+0.25`,
`-0.5`, `*2`) for batch height editing, exposed as raw text input.  No
preview of what the operation will produce; applied immediately on Enter.

### 10.4  Menu Bar (MenuBarMixin — 209 lines)

Six menus: **File** (New/Open/Recent/Save/Save As/Quit), **Edit**
(Undo/Redo/Find-Replace/Copy/Paste/Duplicate), **View** (3D/2D toggle/
display visibility), **Zone** (Resize/Settings/Duplicate/Validate/Export),
**Data** (Entity Defs/Items/Loot Tables/Presets viewers), **Window**
(Texture Browser/Keybind Editor/Help).

Plus FPS counter in the far right.

### 10.5  Overlays (OverlaysMixin — 316 lines)

**Help overlay** (`?` key): full-window modal showing all keybinds
grouped by category.

**Keybind editor** (Window menu / gear button): table of all binds with
category filter, conflicts-only filter, rebind via key capture,
reset-to-default, save to `keybinds.json`.

---

## 11  Dialog Manager

`editor/dialog_manager.py` (155 lines) replaces the old scattered boolean
flags with a centralised system.

### 11.1  DialogManager

Classifies dialogs into two categories:

**FLOATING** (8): find_replace_tex, validate_zone, entity_defs_viewer,
items_viewer, loot_tables_viewer, presets_viewer, keybind_editor,
texture_browser

**MODAL** (7): new_zone, save_as, unsaved_guard, resize_zone,
zone_settings, duplicate_zone, export_image

API: `open(name)`, `close(name)`, `is_open(name)`, `any_modal_open()`,
`any_open()`, `close_any()` (Escape ordering: floating first, then
modals).

### 11.2  DialogPropertyBridge

A mixin that generates Python property descriptors via
`_make_dialog_prop(dialog_name)`:

```python
@property
def show_new_zone(self):
    return self.dialog_manager.is_open("new_zone")

@show_new_zone.setter
def show_new_zone(self, value):
    if value: self.dialog_manager.open("new_zone")
    else:     self.dialog_manager.close("new_zone")
```

This provides drop-in backward compatibility with `self.show_new_zone = True`
patterns in existing code.

**Weakness:** The bridge properties are generated for each dialog name
using string matching.  Adding a new dialog requires adding it to the
`FLOATING`/`MODAL` sets in `DialogManager`, and if the old boolean pattern
was used anywhere, adding a bridge property.  The escape ordering in
`close_any()` is a fixed iteration order, not a stack.

---

## 12  Zone Data Model

The editor operates directly on a `Zone` object (`core/zones/zone.py`,
391 lines).  All grids are nested Python lists.

### 12.1  Zone Class

```python
@dataclass
class Zone:
    name: str
    width: int
    height: int
    anchor: tuple[int, int]
    first_person: bool
    skybox: str
    sky_color: tuple[int, int, int]
    # ... all grids and object lists below
```

Methods: `save_to_file()`, `load_from_file()` (classmethod),
`next_uid()`, `ensure_uids()`.

### 12.2  Per-Cell Grids (2D: `[row][col]`)

| Grid | Type | Default | Purpose |
|:-----|:-----|:--------|:--------|
| `tiles` | str | "grass" | Tile type ID |
| `floor_heights` | float | 0.0 | Floor Y |
| `ceil_heights` | float | 10.0 | Ceiling Y (10.0 = sky sentinel) |
| `wall_textures` | str | "" | Primary wall texture |
| `floor_textures` | str | "" | Floor surface texture |
| `ceil_textures` | str | "" | Ceiling surface texture |
| `light_levels` | float | 1.0 | Per-cell lighting (0–1) |
| `rotations` | int | 0 | Tile rotation (0–3) |
| `upper_wall_height` | float | 0.0 | Wall extension above ceiling |
| `floor2_heights` | float | -1000 | Layer 2 floor (-1000 = none) |
| `ceil2_heights` | float | -1000 | Layer 2 ceiling |
| `floor2_textures` | str | "" | Layer 2 floor texture |
| `ceil2_textures` | str | "" | Layer 2 ceiling texture |
| `upper_wall_height2` | float | 0.0 | Layer 2 upper wall |
| `fog_density` | float | 0.0 | Per-cell fog density |
| `fog_color` | (R,G,B) | (0,0,0) | Per-cell fog colour |
| `floor_slope_dx` | float | 0.0 | Floor slope X gradient |
| `floor_slope_dy` | float | 0.0 | Floor slope Y gradient |
| `floor_slope_div` | int | 0 | Slope subdivision |
| `reflect_map` | int | 0 | Floor reflection flag |

### 12.3  Per-Face Grids (3D: `[row][col][4]` — N/S/E/W)

| Grid | Element Type | Purpose |
|:-----|:-------------|:--------|
| `face_textures` | str | Per-face wall textures |
| `floor_step_textures` | str | Floor step face textures |
| `ceil_step_textures` | str | Ceiling step face textures |

### 12.4  Segment Grids (4D: `[row][col][4][list_of_dicts]`)

| Grid | Segment Dict | Purpose |
|:-----|:-------------|:--------|
| `wall_segments` | `{y, texture}` | Wall face vertical splits |
| `floor_step_segments` | `{y, texture}` | Floor step splits |
| `ceil_step_segments` | `{y, texture}` | Ceiling step splits |

### 12.5  Object Lists

| List | Element | Key Fields |
|:-----|:--------|:-----------|
| `entities` | Dict | x, y, type, angle, state, scale, loot, extra; `pos: {x, y}` (new format) |
| `boxes` | Dict | x, y, z, w, h, d, yaw, textures (per-face dict) |
| `quads` | Dict | x, z, y, w, h, yaw, texture, two_sided |
| `curves` | Dict | cx, cy, radius, angle_start, angle_end, height, texture |
| `render_portals` | Dict | cell, face, dest_zone, dest_cell, dest_face, offset |
| `overlay_walls` | Dataclass `OverlayWall` | x1, y1, x2, y2, texture, height_scale, transparent, blocks |

### 12.6  UID System

Each object dict/dataclass has a `uid` field (integer).  `zone.next_uid()`
provides monotonic unique IDs.  `zone.ensure_uids()` assigns UIDs to
legacy objects that lack them.

### 12.7  Supporting Types

```python
@dataclass
class Portal:           # zone-to-zone transition points
    x: float; y: float; target_zone: str; ...

@dataclass
class OverlayWall:      # free-form wall segments
    x1: float; y1: float; x2: float; y2: float
    texture: str; height_scale: float; transparent: bool; blocks: bool
```

**Weakness:** All grids are plain nested Python lists.  No numpy, no typed
arrays.  Copying a 100×100 grid of floats for undo creates 10,000 new
Python float objects.  Memory layout is cache-unfriendly.

**Weakness:** Zone grids are not fully validated on load.  If a `.zone`
file has mismatched dimensions (e.g. `floor_heights` with 19 rows but
`tiles` with 20), the editor will IndexError at runtime.
`_ensure_face_textures()` patches some grids lazily but not all.

**Weakness:** The "sky" concept uses a sentinel value (`SKY_HEIGHT = 10.0`)
rather than a proper nullable field.  Any ceiling at exactly 10.0 is
treated as "sky" regardless of user intent.  Similarly, Layer 2 uses
`LAYER_NONE = -1000.0` as a sentinel for "no data".

---

## 13  Persistence

### 13.1  Zone Files (Binary `.zone` Format)

Zones are saved as binary `.zone` files via `zone.save_to_file(path, registry)`,
which delegates to `core/zones/io.py`:

**Binary format** (`core/zones/format.py`):
- 12-byte header: magic `0x5A4F4E45` + version(1) + flags + W + H
- **NAVI chunk:** `uint16[H×W]` navigation bitmask per cell
  (SOLID, BLOCK_N/S/E/W, WATER, HAZARD, INTERIOR, PLATFORM, DOOR, PORTAL, HALF_WALL)
- **ELEV chunk:** `float32[H×W×2]` floor + ceiling heights
- **RNDR chunk:** `uint16[H×W×6]` texture indices + `float32[H×W]` light levels
- **ENTY chunk:** msgpack blob with all editor grids (entities, portals,
  overlay walls, all texture grids, all segment grids, all L2 data)

The editor's save button triggers `_save_zone()` → `_do_save()` which
calls `zone.save_to_file()`.

### 13.2  Game Registry (`core/zones/game_registry.py`, 315 lines)

Bidirectional `str ↔ uint16` mapping with namespaces ("tile", "texture",
"prefab").  `NamespaceView` for scoped access.  JSON persistence.

### 13.3  Session File (`editor_session.json`)

```json
{
  "last_zone": "outskirts",
  "recent_zones": ["outskirts", "campsite", "crossroads"],
  "left_panel_w": 280,
  "right_panel_w": 250,
  "window_w": 1600,
  "window_h": 900,
  "view_mode": "3d",
  "show_texture_browser": false,
  "camera_bookmarks": [...]
}
```

Managed by `editor/app/session_cfg.py` (60 lines): `load_session()` →
merge with `_defaults()`, `save_session(cfg)` → best-effort write.
`push_recent(cfg, name)` → MRU list capped at `_MAX_RECENT = 12`.

### 13.4  Keybind Overrides (`keybinds.json`)

User keybind rebinds stored as JSON by the `KeybindRegistry`.

**Weakness:** Session data is saved only on clean quit (`_save_session()`
at end of `run()`).  A crash loses all session state.  No periodic
auto-save of session.

**Weakness:** There is no auto-save for zone data.  Only manual Ctrl+S.
The unsaved-changes guard catches quit/switch/new, but a crash or
kill signal loses all edits.

---

## 14  Zone Operations (Dialogs)

`DialogsMixin` (`editor/app/dialogs.py`, 1,106 lines) implements all
zone-manipulation dialogs.

### 14.1  Unsaved Changes Guard

`_request_guarded(action, payload)` checks `dirty` before destructive
actions:

```
Actions: "quit" → exit, "switch" → load zone, "new" → create blank
```

If dirty: shows Save / Discard / Cancel modal.  Deferred action stored
in `_guard_action` / `_guard_payload`, executed by
`_execute_guarded_action()` after user choice.

**Weakness:** Only three actions are guardable via a string-dispatched
`if/elif`.  Adding new guardable actions requires editing
`_execute_guarded_action`.  Not a callable/callback system.

### 14.2  Resize Zone

Configurable anchor (9 positions: top-left through bottom-right).
`_do_resize_zone_inner()` creates entirely new grids via
`_resize_grid_2d/3d/4d`, plus `_relocate_objects` for entities/boxes/
quads/curves/portals.

**Grids resized:** 17 × 2D, 1 × 2D special (fog_color tuple), 3 × 3D,
3 × 4D, plus all object lists.

Error recovery: wraps inner logic in `try/except` and calls
`editor_3d._undo()` on failure.

### 14.3  Find / Replace Texture

`_count_texture(zone, tex)` / `_replace_texture(zone, find, replace)`:
iterates `_TEXTURE_2D_FIELDS` (6 fields), `_TEXTURE_3D_FIELDS` (3 fields),
`_SEGMENT_FIELDS` (3 fields), plus object texture fields.  Exact string
match only.

**Weakness:** No regex, no glob, no "starts with".  No preview of changes
before committing.

### 14.4  Validate Zone

`_validate_zone(zone) → list[str]` — 12+ rule checks: grid dimension
consistency, height sanity (floor > ceiling), L2 height consistency,
unknown tiles, entity bound checks, anchor bounds, blank zone detection,
render portal validation, overlay wall bounds, box/quad/curve validation.

**Weakness:** Results are a static string list.  No link from a result
to the offending cell/object — user must navigate manually.

### 14.5  Other Dialogs

| Dialog | Trigger | Description |
|:-------|:--------|:------------|
| New Zone | Ctrl+N | Width/height inputs → blank zone |
| Save As | Ctrl+Shift+S | Name input → save to disk |
| Zone Settings | Zone menu | first_person, skybox, sky_color, anchor |
| Duplicate Zone | Zone menu | Deep-copy under new name |
| Export Image | Zone menu | Top-down tile-colour PNG export |

---

## 15  Asset Browser

`AssetBrowserMixin` (`editor/app/asset_browser.py`, 312 lines): floating
ImGui window with tabbed categories.

**Categories:** `ASSET_CATEGORIES` — Tiles, Skyboxes, Billboards, Other
(each mapped to a directory under `assets/textures/`).

```
_draw_texture_browser()
 ├─ Category tab buttons
 ├─ Refresh button (invalidates cache)
 ├─ Thumbnail grid (GL textures, 64×64, cached in _ab_thumb_cache)
 ├─ Tooltips (filename + dimensions)
 ├─ Detail bar: filename, relative path
 ├─ Apply as Skybox (skybox category only)
 ├─ Delete file
 └─ Import from external path (copy with overwrite-avoidance suffix)
```

**Weakness:** Thumbnails are loaded synchronously on first view via
`_ab_upload_thumbnail()`.  A directory with many large images causes a
frame hitch.  No background loading, no loading indicator.

**Weakness:** The browser cannot set the current brush texture.  It shows
files and can apply skyboxes or delete files, but has no palette
integration.  Users must scroll the left panel palette separately.

---

## 16  Keybind System

### 16.1  Registry Structure (`editor/keybinds.py`, 460 lines)

```
Keybind (mutable dataclass):
  action:      str           e.g. "camera.forward", "sculpt.reset_floor"
  key:         int           pygame key constant
  mods:        int           MOD_SHIFT(1) | MOD_CTRL(2) | MOD_ALT(4)
  scope:       str           pipe-delimited: "sculpt|select|paint" or "global"
  condition:   str           state guard: "selection", "no_selection", "aimed_ceiling"
  description: str           human-readable
  category:    str           grouping: "Camera", "Selection", "Display", etc.
  _override_key / _override_mods   runtime rebind storage

KeybindRegistry:
  register(action, key, mods, scope, condition, description, category)
  check(action, key, pg_mods, scope) → bool
  matches_any_global(key, pg_mods) → bool
  conflicts() → groups with overlapping key+mods+scope+condition
  rebind(action, new_key, new_mods) / reset(action) / reset_all()
  save_overrides(path) / load_overrides(path)
  by_category() / all_binds()
```

**Modifier simplification:** `_simplify_mods()` converts raw pygame
bitmasks to 3-bit flags.

**Properties:** `effective_key`, `effective_mods` (respect overrides),
`is_rebound`, `key_label()`.

`create_default_registry()` populates ~60+ keybinds via factory.

### 16.2  Condition System

The `condition` field adds state-based guards:
- `"selection"` — only match when selection is active
- `"no_selection"` — only match when no selection
- `"aimed_ceiling"` — only match when aimed at ceiling

This allows the same physical key to have different actions based on
editor state (e.g. `H` = make-wall when no selection, batch-make-wall
when selection exists).

### 16.3  Conflict Detection

`conflicts()` groups binds by `(effective_key, effective_mods)` and
reports groups where scope intersection is non-empty.

**Weakness:** Conflicts are computed on demand, not on rebind.  You can
create a conflict and only discover it by manually opening the
conflict view.  No warning at rebind time.

---

## 17  Camera System

### 17.1  Shared Math (`editor/fly_camera.py`, 120 lines)

| Function | Purpose |
|:---------|:--------|
| `wasd_2d(angle, fwd, bwd, left, right, speed, dt)` | Ground-plane displacement |
| `forward_3d(yaw, pitch)` | Unit forward vector |
| `right_3d(yaw)` | Unit right vector |
| `wasd_3d(yaw, pitch, fwd, bwd, left, right, up, down, speed, dt)` | Full 3D displacement |
| `clamp_pitch(pitch)` | Clamp to `±PITCH_LIMIT` (π×0.45) |

Constants: `MOUSE_SENS = 0.003`, `KB_TURN_SPEED = 2.5`, `PITCH_LIMIT = π*0.45`

### 17.2  Comparison

| Property | 3D Editor | Raycaster Preview |
|:---------|:----------|:------------------|
| Movement | 6DOF fly (WASD+Space+C) | Ground-plane WASD |
| Collision | Circle-vs-AABB in XZ (`_collides_xz`) | `can_step_to` height check |
| Yaw | Mouse/Q/E, ±∞ | Mouse, ±∞ |
| Pitch | Mouse, ±0.45π (~81°) | Mouse, ±0.30π (~54°) |
| Speed | `FLY_SPEED=3.0` (×3 sprint) | `MOVE_SPEED=3.0` (×2 sprint, ×0.3 slow) |
| Height | Free Y + floor/ceil clamp | Floor tracking + lerp |

Camera bookmarks (Ctrl+Shift+1-9 / Shift+1-9) save and restore
`(cam_x, cam_y, cam_z, yaw, pitch)` tuples, bound to zone name.
Recalling a bookmark for a different zone triggers a zone switch
(with guard check).

**Weakness:** Bookmarks store absolute world positions.  If a zone is
resized, bookmarks point to incorrect locations.  No validation against
zone bounds on recall.

---

## 18  Rendering Pipeline Comparison

| Aspect | 3D Wireframe Editor | 2.5D Raycaster Preview |
|:-------|:--------------------|:-----------------------|
| Renderer | Pure Python + pygame draw | C extension (`_ray_render.c`) |
| Projection | Perspective matrix (software) | Column-based raycasting |
| Resolution | Window size (1600×900) | 640×360 (upscaled) |
| Surfaces | Shaded polygons + wireframe | Textured walls/floors/ceilings |
| Entities | Coloured OBB boxes | Textured billboards (C ext) |
| Skybox | Panorama blit (pygame) | Angular UV mapping (C) |
| Lighting | Flat per-cell tint | Fog LUT + point lights (C) |
| Performance | CPU-bound, < 30 FPS large zones | GPU-like C loop, 60+ FPS |
| Particles | None | C extension rendering |

### 18.1  RayRenderer (`engine/ray_renderer.py`, 1,838 lines)

The C-backed renderer pre-builds ~40+ flat buffers from the zone data:

- **Map data:** `_tiles_buf` (int32), `_cell_solid` (bytearray), `_wall_buf`
- **Texture atlas:** packed RGBA, `num_tiles × 64 × 64 × 4`
- **Heights:** `_fh_buf`/`_ch_buf` (float64)
- **Texture overrides:** `_ft_buf`/`_ct_buf`, `_face_tex_buf` (int32[H×W×4])
- **LUTs:** fog, thin wall, tall wall, height-scale, alt-texture, transparent, v_scale, animated
- **Objects:** overlay walls (7 doubles/wall), quads (8 doubles/quad), boxes (14 doubles/box), curves (9 doubles/curve)
- **L2:** `_fh2_buf`/`_ch2_buf`/`_ftex2_buf`/`_ctex2_buf`
- **Segments:** offset/count/texture/ytop buffers
- **Step walls:** floor + ceiling step textures, segments, upper wall heights
- **Portals:** portal map + portal data buffers
- **Effects:** fog volumes, point lights, decals, lens distortion, bump mapping, reflections

`render(px, py, angle, cam_h, pitch)` passes a dict of ~60+ named fields
to `_c_render_frame()`.

Runtime update methods: `update_zone()`, `update_heights()`,
`update_textures()`, `set_lens()`, `set_point_lights()`, `set_decals()`,
`set_bump_strength()`.

**Weakness:** There is no shared data path between the two renderers.
Changing a visual property requires implementation in *both* C raycaster
and Python wireframe.  Many raycaster features (bump mapping, reflections,
portal rendering, curved walls, fog volumes, particles) have no 3D editor
visualisation.  The wireframe is a simplified approximation — no WYSIWYG.

### 18.2  3D Math (`editor/view_3d/math3d.py`, 253 lines)

| Function | Purpose |
|:---------|:--------|
| `_perspective(fov, aspect, near, far)` | 4×4 perspective matrix (flat list[16]) |
| `_build_view_matrix(eye, yaw, pitch)` | View matrix from camera state |
| `_mat4_mul(a, b)` | 4×4 matrix multiply |
| `_project(vp, x, y, z, hw, hh)` | World→screen single point |
| `_project_line(vp, ...)` | Projected line with near-plane clipping |
| `_project_poly(vp, corners, hw, hh)` | Projected polygon with Sutherland-Hodgman clipping |
| `_extract_frustum_planes(vp)` | 6 normalised frustum planes |
| `_aabb_in_frustum(planes, aabb)` | AABB-vs-frustum test |
| `_visible_cell_set(planes, W, H)` | Set of visible (r,c) cells |

Constants: `NEAR_CLIP=0.05`, `FAR_CLIP=80.0`, `FOV_DEG=75.0`

### 18.3  Picking (`editor/view_3d/picking.py`, 151 lines)

| Function | Purpose |
|:---------|:--------|
| `_ray_vs_aabb(...)` | Slab-based ray-AABB → `(t, face_name)` |
| `_ray_vs_obb(...)` | Yaw-rotated OBB: transforms ray to local space |
| `_CellHit` | Dataclass: t, col, row, part, face, hit_y |

---

## 19  Preset System

`core/presets.py` (739 lines) — cell template recipes.

### 19.1  CellPreset (Frozen Dataclass)

Captures a full cell configuration: heights (floor, ceil, upper wall,
L2), textures (floor, ceil, wall, per-face[4], step textures), segments
(wall, floor step, ceil step).

**Apply modes:** `replace`, `stack_floor`, `stack_ceil`, `merge`

### 19.2  Operations

| Function | Purpose |
|:---------|:--------|
| `apply_preset(zone, r, c, preset)` | Stamp preset onto cell with mode dispatch |
| `capture_preset(zone, r, c, ...)` | Snapshot cell as new preset |
| `register_preset(name, preset)` | Add to global `PRESET_REGISTRY` |
| `delete_preset(name)` | Remove from registry + disk |
| `load_presets()` | Auto-load all TOML from `data/presets/` |

TOML I/O: `_parse_preset_toml()`, `_save_preset_toml()`.
`load_presets()` is called at import time (module-level side effect).

### 19.3  Editor Integration

`StampMixin` provides the editor tool:
- `_stamp_apply()` → `apply_preset()` on aimed cell
- `_stamp_capture_begin()` → interactive capture with name entry
- Palette cycling via scroll / `M` key for mode cycling
- Dispatched through `StampApply` command

---

## 20  Core Engine Dependencies

### 20.1  ECS (`core/ecs.py`, 257 lines)

The game's entity-component-system, used by the runtime but **not by the
editor** (the editor manipulates zone data directly):

```
Component       base dataclass, _persist: ClassVar[bool]
Resources       typed singleton store (set/get/try_get/has)
World           entity management + component CRUD + zone index + queries
  spawn() / kill() / alive() / purge()
  add() / get() / has() / remove()
  query(*types) → yields (eid, *comps)  — iterates smallest bucket
  zone_entities(zone) → O(1) set
  events: EventBus (core)
```

### 20.2  Core EventBus (`core/events.py`, ~130 lines)

Queue-and-flush pub/sub (distinct from the editor's EventBus):

```
subscribe(type, handler) / subscribe_once() / unsubscribe()
emit(event)           → queue
emit_immediate()      → synchronous
flush()               → deliver all queued (once per frame, snapshot to prevent loops)
```

**Game events:** `EntityDied`, `DamageDealt`, `ZoneTransition`,
`ItemPickedUp`, `InteractionEvent`

### 20.3  Zone Compiler (`core/zones/compiler.py`, 361 lines)

`compile_zone_to_arrays()` → `CompiledZone` dataclass with numpy arrays:
`navi_grid` (uint16), `floor_z/ceil_z` (float32), `textures`
(uint16[H,W,6]), `light_levels` (float32).  Used at runtime for
efficient zone loading; the editor works with raw Python lists.

### 20.4  Entity Definitions (`core/entity_defs.py`)

Loaded from `data/entity_defs.toml`.  Defines entity types (categories,
scales, states, directional flags).  Used by the entity palette in the
editor's left panel.

### 20.5  Tile Registry (`core/tiles/`)

`TILE_REGISTRY`, `TILE_COLORS` — tile type definitions and colour
mappings used by both the editor (palette, rendering colours) and the
raycaster (atlas building).

---

## 21  Cross-Cutting Concerns

### 21.1  Error Handling

All zone I/O and save operations are wrapped in `except Exception` with
transient flash feedback.  No error logging, no error dialog, no stack
trace in the UI.  Errors in tool operations (e.g. IndexError from
corrupted grid dimensions) propagate as unhandled exceptions that crash
the editor.

### 21.2  Testing

Tests exist in `tests/` covering:

| Test File | Lines | Coverage |
|:----------|:------|:---------|
| `test_ecs.py` | 174 | Core ECS CRUD, queries, zone indexing |
| `test_events.py` | 105 | EventBus queue/flush, type isolation |
| `test_save.py` | 215 | Round-trip save/load, persist filtering |
| `test_session.py` | 348 | Session lifecycle, zone loading, portals |
| `test_interaction.py` | 96 | NPC proximity, facing, events |
| `test_raycaster.py` | 105 | DDA slices, entity projection, z-buffer |
| `test_pathfinding.py` | 376 | A*, BFS, line-of-sight |
| `test_command_bus.py` | 380 | Command bus undo, dirty, batch ops |
| `test_editor_tools.py` | 1,813 | Sculpt, paint, segments, entities, selection |
| `test_editor_renderer.py` | 674 | 3D renderer geometry + visual correctness |
| `test_selection_store.py` | 657 | SelectionStore cell/object selection, bulk |
| `test_input_stack.py` | 725 | InputStack, contexts, dialog blocking |
| `test_handler_coverage.py` | 157 | Meta-test: all Commands have handlers (≥80) |
| `test_ray_render.py` | 2,696 | C renderer pixel regression tests |
| `test_render_edge_cases.py` | 755 | Boundary conditions, degenerate geometry |
| `test_wall_segments.py` | 524 | Segment edit + render, stacked textures, undo |
| `test_lod.py` | 566 | Dual-resolution LOD, promote/demote |
| `test_world_features.py` | 293 | Combat, containers, items, dialogue, spawner |

**Total test code: ~11,200+ lines.**

Editor-specific testing now covers: command bus, tools, renderer,
selection store, input stack, handler coverage, and wall segments.
This is significantly more comprehensive than previously documented.

Benchmarks: `bench_render.py` (per-stage C renderer), `bench_micro.py`
(hot paths), `bench_ceiling.py` (ceiling rendering).

### 21.3  Performance Bottlenecks

1. **Software rendering** — O(visible_cells × faces_per_cell × projection_cost).
   No GPU acceleration for the wireframe view.
2. **Full-zone undo snapshots** — O(zone_area × grid_count) per push.
3. **glTexImage2D every frame** — Full viewport re-upload (~5.5 MB).
4. **Brute-force picking** — O(visible_cells) per frame.
5. **Object picking** — O(n) per type per frame, no spatial index.
6. **Synchronous thumbnail loading** — blocks main thread on first access.
7. **UID resolution** — Linear scan through object lists.

### 21.4  State Coupling

The dependency graph between components is dense:

```
ZoneEditorApp ─────── Zone3DEditor ─────── Zone
     │                     │                 │
     ├─ PanelsMixin        ├─ SelectionStore │
     ├─ DialogsMixin       ├─ ObjectLayer    │
     ├─ AssetBrowserMixin  ├─ CommandBus     │
     ├─ DataViewersMixin   ├─ EventBus       │
     └─ InputStack         └─ KeybindRegistry│
                                             │
     RayRenderer ─────────────────────────────┘
```

Every component can reach every other through `self.` attribute access.
The `CommandBus` and `EventBus` provide the only structured communication
channels.  All other interaction is direct attribute mutation.

**Notable coupling points:**
- App reads `editor_3d.selection`, `editor_3d.aimed`, `editor_3d.snap_idx`, etc.
- App calls `editor_3d._undo()`, `editor_3d._redo()`, `editor_3d._push_undo()`
- Panels read zone data, editor state, and selection state
- Inspector writes directly to zone grid cells and object dicts
- `CapturedViewportContext` forwards events to `editor_3d.handle_event()`
- `RayRenderer` builds buffers from zone data; editor calls `update_*` methods

---

## 22  File Map

```
zone_editor.py                         entry point (22 lines)

editor/
  __init__.py                          package docstring
  fly_camera.py                        shared camera math + constants (120 lines)
  keybinds.py                          KeybindRegistry + factory (460 lines)
  input_context.py                     InputContext ABC + InputStack (130 lines)
  contexts.py                          GlobalShortcutsContext + CapturedViewportContext + StampCaptureContext (~400 lines)
  dialog_manager.py                    DialogManager + DialogPropertyBridge (155 lines)

  commands/                            ────── Command Bus Layer ──────
    __init__.py                        re-exports (28 lines)
    base.py                            Command, BatchCommand, CommandBus, EventBus (210 lines)
    events.py                          StateChanged, SelectionChanged, ToolChanged, ViewDirtied (40 lines)
    sculpt_cmds.py                     19 sculpt commands + handlers (320 lines)
    paint_cmds.py                      12 paint/fill commands + handlers (322 lines)
    erase_cmds.py                      3 eraser commands + handlers (72 lines)
    l2_cmds.py                         14 layer-2 commands + handlers (230 lines)
    object_cmds.py                     27 object commands + handlers (525 lines)
    segment_cmds.py                    3 segment commands + handlers (68 lines)
    select_cmds.py                     3 selection batch commands + handlers (70 lines)
    stamp_cmds.py                      1 stamp command + handler (40 lines)
    misc_cmds.py                       3 misc commands + handlers (72 lines)

  app/                                 ────── Application Layer ──────
    __init__.py                        re-exports ZoneEditorApp (17 lines)
    app.py                             ZoneEditorApp class (564 lines)
    constants.py                       window/panel/raycaster config (35 lines)
    theme.py                           imgui dark theme (65 lines)
    events.py                          EventsMixin: input routing (90 lines)
    viewport.py                        ViewportMixin: GL quad rendering (133 lines)
    raycaster.py                       RaycasterMixin: 2D preview camera (114 lines)
    session_cfg.py                     load/save editor_session.json (60 lines)
    asset_browser.py                   AssetBrowserMixin: texture browser (312 lines)
    data_viewers.py                    DataViewersMixin: TOML data browsers (324 lines)
    dialogs.py                         DialogsMixin: all modals + zone ops (1,106 lines)
    panels_pkg/
      __init__.py                      PanelsMixin: _build_ui + splitters + bars (554 lines)
      menu_bar.py                      MenuBarMixin: top menu bar (209 lines)
      toolbox.py                       ToolboxMixin: left panel (469 lines)
      inspectors.py                    InspectorMixin: right panel (1,723 lines)
      overlays.py                      OverlaysMixin: help + keybind editor (316 lines)

  view_3d/                             ────── 3D Editor Layer ──────
    __init__.py                        façade re-exports (50 lines)
    editor.py                          Zone3DEditor main class (1,981 lines)
    constants.py                       modes, tools, colours, hints (431 lines)
    math3d.py                          projection, view matrix, frustum (253 lines)
    picking.py                         ray-AABB/OBB intersection (151 lines)
    geometry.py                        GeometryMixin: cell box computation (167 lines)
    selection.py                       SelectionState (Phase 1 legacy) (290 lines)
    selection_store.py                 SelectionStore (Phase 2 UID-based) (430 lines)
    objects.py                         ObjectLayer: unified dispatch (408 lines)
    undo.py                            UndoMixin: snapshot undo/redo (226 lines)
    save.py                            SaveMixin: zone serialisation (31 lines)
    primitives.py                      DrawPrimitivesMixin: line3d, box, filled_box (277 lines)
    rendering.py                       RenderingMixin: draw() + HUD (2,197 lines)
    cell_ops.py                        reset_cell helper (69 lines)
    tools_sculpt.py                    SculptMixin (839 lines)
    tools_paint.py                     PaintMixin (474 lines)
    tools_fill.py                      FillMixin (398 lines)
    tools_erase.py                     EraseMixin (114 lines)
    tools_select.py                    SelectMixin (284 lines)
    tools_segment.py                   SegmentMixin (282 lines)
    tools_stamp.py                     StampMixin (149 lines)
    tools_entity.py                    EntityMixin (255 lines)
    tools_box.py                       BoxMixin (334 lines)
    tools_layer2.py                    Layer2Mixin (492 lines)
    tools_quad.py                      QuadMixin (257 lines)
    tools_portal.py                    PortalMixin (102 lines)
    tools_curve.py                     CurveMixin (219 lines)
    tools_overlay.py                   OverlayWallMixin (266 lines)

core/                                  ────── Core Engine ──────
  ecs.py                               ECS world (257 lines)
  events.py                            Core EventBus (130 lines)
  types.py                             Direction, EntityKind, face constants (56 lines)
  presets.py                           CellPreset + TOML I/O (739 lines)
  entity_defs.py                       Entity type definitions
  zones/
    zone.py                            Zone, Portal, OverlayWall (391 lines)
    format.py                          Binary .zone format constants (178 lines)
    io.py                              Binary zone read/write (437 lines)
    compiler.py                        Zone → numpy arrays (361 lines)
    game_registry.py                   String↔uint16 registry (315 lines)

engine/                                ────── Rendering Engine ──────
  ray_renderer.py                      RayRenderer: C-backed 2.5D (1,838 lines)
  raycaster.py                         Pure-Python raycaster (fallback)
  textures.py                          TextureAtlas management
  _ray_render.c                        C extension: render_frame, render_entities, etc.
```

### Line Count Summary

| Layer | Files | Lines |
|:------|:------|:------|
| Entry point | 1 | 22 |
| Editor infrastructure | 5 | 1,115 |
| Command bus | 10 | 1,997 |
| Application (app/) | 11 | 3,369 |
| Panels (panels_pkg/) | 4 | 3,271 |
| 3D Editor (view_3d/) | 23 | 8,845 |
| **Editor total** | **54** | **~18,619** |
| Core engine (used by editor) | ~8 | ~2,500 |
| Rendering engine | ~4 | ~3,200 |
| Tests | ~20 | ~11,200 |
