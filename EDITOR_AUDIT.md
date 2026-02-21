# Editor Codebase Audit & Restructuring Plan

**Date:** 2025  
**Scope:** Full audit of `editor/` — 38 Python files, ~8,926 lines  
**Goal:** Identify every architectural flaw, rendering bug, logic bug, half-baked feature, and propose a concrete restructuring plan.

---

## Table of Contents

- [§1 — Architecture Overview](#1--architecture-overview)
- [§2 — File Inventory](#2--file-inventory)
- [§3 — Dependency Graph](#3--dependency-graph)
- [§4 — Critical Bugs (P0)](#4--critical-bugs-p0)
- [§5 — Important Bugs (P1)](#5--important-bugs-p1)
- [§6 — Rendering Bugs (P2)](#6--rendering-bugs-p2)
- [§7 — Half-Baked Features](#7--half-baked-features)
- [§8 — Design Smells & Structural Issues](#8--design-smells--structural-issues)
- [§9 — Restructuring Plan](#9--restructuring-plan)
- [§10 — Execution Phases](#10--execution-phases)

---

## §1 — Architecture Overview

The editor uses a manual Pygame event loop with immediate-mode drawing.
`EditorApp` in `app.py` owns the window, routes events through a
strict priority chain, and draws sub-systems in painter's order.

**Strengths:**
- Clean DAG — zero circular imports across all 38 files.
- Well-factored panels — `panels_pkg/` has 16 focused modules (52–304 lines each) sharing a `PanelBase` lifecycle.
- Clean mixin decomposition — `ActionsMixin` and `CanvasEventsMixin` keep `app.py` under 500 lines.
- Layered scale system — `Layout` singleton provides responsive geometry with `Layout.s()`.

**Weaknesses (the core problems):**
1. **No focus/input manager** — `UIContext` only tracks which widget has keyboard focus via a bare `int`. There is no centralized "click-away unfocuses text fields", no event bus, no focus-transfer protocol. Every widget must individually handle its own unfocus logic, and many don't.
2. **Event routing is a hardcoded waterfall** — `_handle_events` is a 130-line if/elif chain with ~15 priority tiers. Adding a new overlay or panel requires editing this method. There's no composable focus-stack or input-layer system.
3. **God objects in overlay editors** — `modals.py` (1,320 lines, 6 classes), `inspector.py` (1,093 lines), `fp_preview.py` (1,114 lines) each exceed 900 lines with multiple interleaved responsibilities.
4. **Widget system gaps** — Dropdown limited to 8 items (no scroll), NumberField can't type decimals or negatives, no click-away unfocus, no global keyboard shortcut guard when fields are focused.
5. **Clip rect leaks** — Multiple panels call `set_clip()` without resetting it, causing downstream drawing to be clipped to stale rects.

---

## §2 — File Inventory

| File | Lines | Role |
|------|------:|------|
| `app.py` | 506 | Main loop, event waterfall, draw order |
| `state.py` | 649 | All mutable state, zone I/O, undo, painting |
| `actions.py` | 209 | Dispatch tables (exact + prefix handlers) |
| `canvas.py` | 243 | Tile grid rendering, coordinate transforms |
| `canvas_events.py` | 252 | Canvas mouse/keyboard, entity placement |
| `ui.py` | 978 | Widget toolkit (10 classes + helpers) |
| `layout.py` | 239 | Responsive layout singleton |
| `inspector.py` | 1,093 | Right-panel tabbed inspector |
| `inspector_entries.py` | 114 | Typed entry descriptors for inspector |
| `fp_preview.py` | 1,114 | First-person preview/editor (PIP + fullscreen) |
| `entity_defs.py` | 396 | EntityDef dataclasses |
| `entity_factory.py` | 220 | Prefab + Forge entity creation |
| `entity_forge.py` | 762 | Full-screen archetype creator |
| `forge_registry.py` | 196 | ForgeArchetype TOML registry |
| `modals.py` | 1,320 | 6 modal dialog classes + ModalManager |
| `templates.py` | 721 | Template editor overlay |
| `loot_editor.py` | 519 | Loot table editor overlay |
| `palette_format.py` | 139 | 2D grid → palette compression (pure data) |
| `msgpack_io.py` | 136 | .mpz binary export/import |
| `panels.py` | 17 | Re-export shim (dead weight) |
| `panels_pkg/__init__.py` | 19 | Panel re-exports |
| `panels_pkg/base.py` | 124 | PanelBase abstract class |
| `panels_pkg/chrome.py` | 101 | Background fills / borders |
| `panels_pkg/entity_panel.py` | 148 | Entity browser (left panel) |
| `panels_pkg/menu_bar.py` | 266 | Top menu bar with dropdowns |
| `panels_pkg/minimap.py` | 68 | Small-scale map overview |
| `panels_pkg/panel_tabs.py` | 84 | Left-panel tab strip |
| `panels_pkg/portal_panel.py` | 72 | Portal list (left panel) |
| `panels_pkg/splitter.py` | 93 | Draggable panel dividers |
| `panels_pkg/status_bar.py` | 57 | Bottom status bar |
| `panels_pkg/template_panel.py` | 80 | Template file browser |
| `panels_pkg/texture_panel.py` | 75 | Texture thumbnail browser |
| `panels_pkg/tile_palette.py` | 304 | Tile swatch grid |
| `panels_pkg/toolbar.py` | 68 | Tool selection strip |
| `panels_pkg/zone_nav.py` | 89 | Zone name + nav history |
| `panels_pkg/zone_panel.py` | 52 | Zone list browser |
| **TOTAL** | **~8,926** | |

---

## §3 — Dependency Graph

```
Layer 0 — No editor deps (leaf modules):
    entity_defs, inspector_entries, palette_format, forge_registry

Layer 1 — Data-only deps:
    entity_factory → entity_defs
    state → entity_defs
    msgpack_io → palette_format

Layer 2 — UI foundation:
    ui (standalone), layout (standalone)

Layer 3 — Panel infrastructure:
    panels_pkg/base → ui, layout
    panels_pkg/panel_tabs → ui, layout
    panels_pkg/chrome → ui, layout, panel_tabs

Layer 4 — Concrete panels:
    All panels_pkg/* → base, ui, state, layout

Layer 5 — Canvas & Inspector:
    canvas → ui, state, layout
    inspector → ui, state, layout, canvas, entity_defs, inspector_entries
    canvas_events → state, entity_factory

Layer 6 — Overlay editors:
    modals → ui, state, canvas, entity_factory, layout
    entity_forge → ui, forge_registry, state, layout
    fp_preview → ui, state
    templates → layout, state, ui
    loot_editor → layout, ui, state

Layer 7 — App shell:
    app → everything above
    actions → state (lazy: modals, msgpack_io)
```

**Circular dependencies: None.** The graph is a clean DAG.

---

## §4 — Critical Bugs (P0)

These are bugs that cause incorrect behavior or data loss during normal usage.

### 4.1 — FP camera drift when overlays are active
**Files:** `app.py:394`, `fp_preview.py:460-475`

`_update()` calls `fp_preview.update(dt, ...)` unconditionally when `fp_preview.active` is true. Opening an overlay (Forge, Loot, Templates) does NOT deactivate the FP preview. If WASD keys were held when the overlay opened, `_keys_held` is never cleared and the camera drifts indefinitely behind the overlay.

**Fix:** Clear `_keys_held` in `fp_preview.update()` by checking `pygame.key.get_pressed()`, or guard the update call behind overlay checks, or clear `_keys_held` when overlays activate.

### 4.2 — Global shortcuts fire during FP fullscreen
**Files:** `app.py:208-210`

`_handle_shortcut()` runs BEFORE FP fullscreen event consumption at line 243. All non-Ctrl shortcuts (G, M, R, B, E, V, I, P, F, 0-9, Delete, brackets) fire in FP mode, causing:
- R → double-fires rotation (global + FP)
- G → toggles grid (meaningless in FP)
- B/E/V → changes top-down tool mode from inside FP
- 0-9 → changes tile palette instead of hotbar slots

**Fix:** `_handle_shortcut()` should return `False` for non-Ctrl keys when `fp_preview.fullscreen` is true.

### 4.3 — Inspector focus leaks on tab switch / rebuild
**Files:** `inspector.py:94-97`, `inspector.py:1083-1089`

When switching tabs or rebuilding, old widgets are discarded but `UIContext.focused_id` is never released. The stale focus ID means:
- `ctx.any_focused()` returns True despite no active widget
- Keystrokes are silently swallowed (the focused widget no longer exists)
- New text fields require a click to receive focus

**Fix:** Call `self.ctx.release_focus()` in `force_rebuild()` and `set_tab()`.

### 4.4 — Entity inventory/dialogue components silently dropped on save
**Files:** `entity_defs.py:197-202`

`to_dict()` only serializes `inventory` if `.items` is non-empty, and `dialogue` only if `.bark` is non-empty. An entity with an empty inventory or blank dialogue loses those components on save→load round-trip. This is **data loss.**

**Fix:** Serialize components if they are not `None`, regardless of their content.

### 4.5 — Dropdown limited to 8 items with no scroll
**Files:** `ui.py:691`

`self.options[:8]` hard-caps all dropdowns to 8 visible items. Affected:
- Inspector entity `kind` dropdown has 9 options — "crop" is unreachable
- Tile erase picker may exceed 8 tiles
- Component type list may exceed 8

**Fix:** Add scroll to Dropdown, or at minimum remove the hard cap and add viewport clipping.

### 4.6 — Entity panel `set_clip` never reset
**Files:** `panels_pkg/entity_panel.py:93`

`surface.set_clip(clip)` is called in `draw()` but `set_clip(None)` is never called. The stale clip rect leaks to ALL subsequent draw calls (minimap, inspector, status bar), potentially clipping their output to the entity panel bounds.

**Fix:** Add `surface.set_clip(None)` at the end of `draw()`.

---

## §5 — Important Bugs (P1)

### 5.1 — No FP camera reset on zone load
**Files:** `app.py:150-153`

`_do_load_zone()` loads a new zone but doesn't reposition the FP camera. On smaller zones the camera may be outside map bounds, causing the raycaster to read invalid indices.

### 5.2 — Inspector entity widget cache stale after in-place edits
**Files:** `inspector.py:792-797`

Rebuild triggers on entity INDEX change, geometry change, or tab change — but NOT when entity properties change in-place (e.g., typing a new name). The entity header label shows stale data.

### 5.3 — Inspector tile tab shows stale hover info
**Files:** `inspector.py:696-715`

Tile tab widgets only rebuild when `selected_tile` changes, but hover info uses `hover_tile`, which changes on every mouse move. The rotation/face-texture display is stale.

### 5.4 — NumberField can't type decimals or negatives
**Files:** `ui.py:476-484`

`_apply_text()` re-parses on every keystroke, erasing "." before the fractional part can be typed. The "-" character causes a ValueError on `float("-")` and is immediately discarded.

### 5.5 — Inspector scroll not reset on entity change
**Files:** `inspector.py:792-797`

Switching to an entity with fewer fields can show a blank panel because `scroll_y` is inherited from the previous entity. One-frame glitch before clamping.

### 5.6 — `_keys_held` leaks across FP mode transitions
**Files:** `fp_preview.py:153`, `fp_preview.py:240`

Exiting fullscreen via Escape doesn't clear `_keys_held`. If WASD were held, the camera continues moving in PIP mode until those keys get KEYUP events (which may never arrive if focus was elsewhere).

### 5.7 — Loot editor: no clipping on right panel
**Files:** `loot_editor.py:279-303`

Entries draw without a clip rect. When content exceeds the panel height, entries overflow into the header and left panel.

### 5.8 — Loot editor: pool "Edit" button is dead UI
**Files:** `loot_editor.py:256-260`, `loot_editor.py:396+`

The Edit button is drawn but has no click handler. Pool name, rolls, and bonus_rolls are not editable.

### 5.9 — Entity panel clicks register on scrolled-out items
**Files:** `panels_pkg/entity_panel.py:167-172`

All `_item_rects` are tested including items scrolled above/below the visible area. Clicking in the visible area can select an invisible item whose stale rect overlaps.

### 5.10 — Tile palette clicks register on scrolled-out swatches  
**Files:** `panels_pkg/tile_palette.py:340-344`

Same issue as 5.9 — no visibility check in `handle_event`.

### 5.11 — AddComponentModal missing portal component
**Files:** `modals.py:283`

The hardcoded component list has 9 entries. `EntityDef.COMPONENT_NAMES` has 11 — `portal` is missing. Users can never add a portal component via the UI.

### 5.12 — Modal scroll max uses hardcoded 400
**Files:** `modals.py:1038-1040`

TileEditorModal scroll clamping uses `400` instead of the actual viewport height. On small screens content is unreachable; on large screens content overscrolls.

### 5.13 — Dropdown click-away leaks the click
**Files:** `ui.py:718`

Clicking outside an open dropdown closes it and returns `False`, letting the click pass through to whatever is underneath.

### 5.14 — Menu bar click-away swallows the click
**Files:** `panels_pkg/menu_bar.py:233-235`

Opposite of 5.13: clicking outside the menu dropdown consumes the event. Users must click twice — once to close the menu, once to act.

### 5.15 — Forge `close()` doesn't refresh panels
**Files:** `entity_forge.py:97-103`

After editing/creating forge archetypes and closing, the entity panel shows stale data until manually refreshed.

---

## §6 — Rendering Bugs (P2)

### 6.1 — Minimap entity positions at wrong scale
`minimap.py:75-78` — Entities use position (x,y) which may be world coords, not tile indices. Dots render at wrong positions.

### 6.2 — Minimap has no clip rect
`minimap.py` — Entity/portal dots can overflow the minimap boundary.

### 6.3 — FP hardcoded pixels throughout HUD
`fp_preview.py:900-934` — HUD text offsets, crosshair sizes, hotbar spacing, tile picker dimensions all use raw pixel values instead of `Layout.s()`. Breaks at non-default DPI/resolution.

### 6.4 — FP ghost-cell rendering allocates full-viewport SRCALPHA surface every frame
`fp_preview.py:879-882` — `_draw_ghost_floor()` creates `Surface((sw, sh), SRCALPHA)` per frame. Expensive at high resolutions.

### 6.5 — PIP window uses hardcoded 400×300 cap
`app.py:462-469` — `pw = min(400, L.canvas_w // 2)` and `ph = min(300, ...)` don't scale with window size.

### 6.6 — Inspector dropdown overflows panel boundary
`inspector.py:912-924` — Dropdown lists near the bottom of the inspector can extend below the panel into the status bar.

### 6.7 — Inspector widget y-offsets calculated at build time
`inspector.py` — Widget positions are absolute, set during `_build_*_widgets()`. Window resizes between rebuilds leave widgets at stale y-positions.

### 6.8 — TextInputModal uses hardcoded pixel layout
`modals.py:116-124` — Fixed offsets (16, 38, 388, 74) instead of scaled values.

### 6.9 — Entity forge title bar rects recreated in handle_event
`entity_forge.py:670-674` — `close_r` and `save_r` are computed independently in `draw()` and `handle_event`. Window resize between frames causes hit-test misalignment.

---

## §7 — Half-Baked Features

### 7.1 — Template slot editing (CAN'T edit slot properties)
Slots can only be created (with hardcoded 6×6 default size) and deleted. There is NO way to change a slot's x, y, width, height, name, or tags after creation. The template system is unusable for real level design.

### 7.2 — Template stamp placement (NOT implemented)
No brush/stamp system for painting room variants onto the template grid. Only slot-tag-bake workflow exists.

### 7.3 — Template bake seed (NOT exposed in UI)
`bake_template()` accepts a `seed` parameter but the UI always calls it without one. Every bake produces random results with no reproducibility.

### 7.4 — Loot editor: entry properties are read-only
Weight, min_count, max_count fields are displayed but not editable. Item selection cycles through the entire item list on click — unusable with more than a handful of items.

### 7.5 — Loot editor: pool properties are read-only
Pool name, rolls, and bonus_rolls cannot be edited (Edit button is dead).

### 7.6 — Inspector tile tab is read-only
`handle_event` returns `None` for the tile tab — no interactive widgets. Can inspect but not edit tile properties.

### 7.7 — Inspector entity extras/tags are read-only
Extras display is truncated to 40 chars. Tags are shown as a comma-joined label. Neither is editable from the inspector.

### 7.8 — Inspector inventory is display-only
Item counts are visible but items cannot be added, removed, or edited.

### 7.9 — Tile palette filter bar is hand-rolled
No cursor positioning, text selection, copy/paste, or Home/End. Only character append and backspace. Should use a proper `TextField` widget.

### 7.10 — Entity forge: kind-inappropriate fields saved
`_apply_form()` writes ALL fields (tile + box + billboard) regardless of the selected kind, polluting the archetype TOML with irrelevant data.

### 7.11 — Forge entity tile_type always forced to "container"  
`entity_factory.py:196-203` — Every tile-kind forge entity gets `tile_entity=EDTileEntity(tile_type="container")`. No way to specify "ground_item", "crop", etc. from the forge.

### 7.12 — FP entity representation is placeholder
`fp_preview.py:730-740` — Entities are shown as ASCII character billboards with no actual sprite textures. This is a development placeholder.

### 7.13 — No FP entity placement
The FP editing mode supports tile painting/erasing/picking but not entity placement, move, or deletion.

### 7.14 — `panels.py` is a dead-weight re-export shim
17 lines that re-export from `panels_pkg`. All consumers could import from `panels_pkg` directly.

---

## §8 — Design Smells & Structural Issues

### 8.1 — No centralized focus/input manager

The biggest structural problem. `UIContext` is too primitive — it's just an ID counter with `focused_id`. There's no:
- Click-away unfocus protocol
- Focus-stack for modals/overlays
- Keyboard event capturing layer
- Focus transfer on widget destruction

Every widget must self-manage its focus release, and many don't (see bugs 4.3, 5.6, 5.13).

### 8.2 — Event routing is a fixed waterfall

`_handle_events()` is a ~130-line imperative priority chain. Problems:
- Adding a new overlay requires editing the waterfall
- Overlay priority is implicit in code order, not declarative
- FP fullscreen is checked in two places (lines 243 and 268) at different priority levels
- No composable input layers or event buses

### 8.3 — God object modules

| Module | Lines | Distinct responsibilities |
|--------|------:|--------------------------|
| `modals.py` | 1,320 | 6 modal classes, ModalManager, file I/O, tile registry mutation |
| `fp_preview.py` | 1,114 | Raycasting, WASD controls, hotbar, tile picker, ghost rendering, HUD |
| `inspector.py` | 1,093 | 3 tab builders, scroll, entity property editing, widget lifecycle |
| `ui.py` | 978 | 10 widget classes, Theme, UIContext, draw helpers |

### 8.4 — `panel_mode` lives on MenuBar, not EditorState

The currently active left panel tab is stored on the `MenuBar` instance instead of `EditorState`. This means:
- Panel mode can't be saved/restored with session state
- Anything needing the current panel must hold a MenuBar reference
- It breaks the pattern of EditorState being the single source of truth

### 8.5 — Rect duplication in draw/event pairs

Multiple modules compute layout rects independently in both `draw()` and `handle_event()`, instead of caching them. If a window resize occurs between frames, the rects disagree: entity_forge, zone_picker_modal, loot_editor, templates all have this.

### 8.6 — Data I/O mixed into state.py

`state.py` contains `load_loot_tables()`, `save_loot_tables()`, `load_item_ids()` — TOML I/O functions that have nothing to do with editor state. They belong in a data access module.

### 8.7 — Inconsistent `set_clip` discipline

Some modules set clip rects and never reset them (entity_panel), some always reset (canvas, inspector content area), some never clip at all (minimap, loot_editor right panel). There's no enforced protocol.

---

## §9 — Restructuring Plan

### 9.1 — Phase 1: Fix the Foundation (Bugs + Widgets)

**Goal:** Fix all P0 bugs and the widget system gaps. No structural changes — just correctness.

1. **Fix Dropdown** — Remove 8-item cap, add scroll/viewport clipping, fix click-away leak.
2. **Fix NumberField** — Allow `.` and `-` mid-typing (defer parse until blur/submit).
3. **Fix UIContext** — Add `release_focus()` call in `force_rebuild()`, `set_tab()`, and overlay open/close.
4. **Fix `set_clip` discipline** — Every `draw()` that calls `set_clip` must reset it in a `try/finally`.
5. **Fix entity_defs round-trip** — Serialize inventory/dialogue even when empty.
6. **Fix FP shortcuts** — Guard `_handle_shortcut()` behind `fp_preview.fullscreen`.
7. **Fix FP camera drift** — Clear `_keys_held` on overlay open and mode transitions.
8. **Fix FP camera reset** — Call `sync_to_anchor()` in `_do_load_zone()`.

### 9.2 — Phase 2: Input System Rework

**Goal:** Replace the waterfall event routing with a composable input layer system.

**Design:**
```
class InputLayer:
    """An event consumer with a priority level."""
    priority: int          # Higher = first to receive events
    active: bool
    def handle_event(event) -> bool  # True = consumed

class InputManager:
    """Ordered stack of input layers."""
    layers: list[InputLayer]  # sorted by priority
    
    def dispatch(event):
        for layer in self.layers:
            if layer.active and layer.handle_event(event):
                return
```

**Layers (highest priority first):**
1. **Overlay layer** (forge, loot, templates, modals) — only one active at a time
2. **Menu dropdown layer** — active when a dropdown is open
3. **FP fullscreen layer** — active in fullscreen edit mode
4. **Global shortcuts layer** — keyboard shortcuts (blocked when overlays/text-fields active)
5. **Panel layer** — left panel, inspector, toolbar
6. **Canvas layer** — default fallthrough

**Benefits:**
- Adding a new overlay = registering a layer, not editing a waterfall
- Shortcut conflicts are resolved by layer priority
- Text field focus can block the shortcuts layer
- `InputManager` can own the click-away unfocus logic globally

### 9.3 — Phase 3: Split God Objects

**modals.py → `modals/` package:**
```
modals/
    __init__.py          # ModalManager + re-exports
    base.py              # _BaseModal
    text_input.py        # TextInputModal
    new_zone.py          # NewZoneModal
    zone_picker.py       # ZonePickerModal
    add_component.py     # AddComponentModal
    tile_editor.py       # TileEditorModal  (~500 lines on its own)
```

**inspector.py → `inspector/` package:**
```
inspector/
    __init__.py          # Inspector class (shell: tab switching, scroll, draw)
    zone_tab.py          # Zone tab widget builder
    tile_tab.py          # Tile tab widget builder
    entity_tab.py        # Entity tab widget builder (~500 lines)
    entries.py           # InspectorEntry subclasses (from inspector_entries.py)
```

**fp_preview.py → `fp_preview/` package:**
```
fp_preview/
    __init__.py          # FPPreview facade + state
    controls.py          # WASD + mouse look + key state
    renderer.py          # Raycaster bridge + ghost rendering
    hud.py               # Crosshair, hotbar, tile picker, HUD text
```

**ui.py → `ui/` package:**
```
ui/
    __init__.py          # Re-exports
    theme.py             # Theme colors
    context.py           # UIContext + InputManager
    widgets.py           # Button, TextField, NumberField, etc.
    draw_helpers.py      # draw_text, draw_text_centered, draw_tab_button
```

### 9.4 — Phase 4: State Cleanup

1. **Move `panel_mode` from MenuBar to EditorState** — single source of truth.
2. **Extract data I/O from state.py** — `load_loot_tables`, `save_loot_tables`, `load_item_ids` → new `editor/data_io.py`.
3. **Cache rects** — Introduce a `LayoutRects` struct that is computed once per frame in `Layout.update()` and shared by both `draw()` and `handle_event()`.

### 9.5 — Phase 5: Complete Half-Baked Features

Priority order based on user impact:

1. **Template slot editing** — Add inline fields for x, y, w, h, name, tags.
2. **Loot editor inline editing** — Make entry weight/min/max editable. Add dropdown for item selection. Wire the Edit button.
3. **Template bake seed** — Add a seed NumberField to the UI.
4. **Inspector entity extras editing** — Add text fields for extras values.
5. **Inspector tag editing** — Add a tag editor (comma-separated text field).
6. **Forge tile_type selection** — Add a dropdown to pick tile_entity type.
7. **Template stamp placement** — Longer-term: design a stamp/brush tool for painting rooms.

---

## §10 — Execution Phases

### Phase 1: Bug Fixes (estimated: 1–2 sessions)

| # | Task | Files |
|---|------|-------|
| 1 | Fix Dropdown 8-item cap + scroll | `ui.py` |
| 2 | Fix NumberField decimal/negative input | `ui.py` |
| 3 | Add `release_focus()` to rebuild/tab-switch paths | `inspector.py` |
| 4 | Fix `set_clip` leaks (entity_panel, minimap) | `entity_panel.py`, `minimap.py` |
| 5 | Fix entity_defs empty component round-trip | `entity_defs.py` |
| 6 | Guard shortcuts behind FP fullscreen check | `app.py` |
| 7 | Clear `_keys_held` on overlay open + mode transitions | `fp_preview.py`, `app.py` |
| 8 | Reset FP camera on zone load | `app.py` |
| 9 | Fix loot editor clip rect | `loot_editor.py` |
| 10 | Fix entity/tile panel scroll vs click bounds | `entity_panel.py`, `tile_palette.py` |
| 11 | Fix modal scroll hardcoded max | `modals.py` |
| 12 | Add portal to AddComponentModal | `modals.py` |
| 13 | Fix forge panel refresh on close | `entity_forge.py`, `app.py` |
| 14 | Fix dropdown click-away behavior | `ui.py` |

### Phase 2: Input System (estimated: 1 session)

| # | Task |
|---|------|
| 1 | Design `InputLayer` / `InputManager` classes |
| 2 | Refactor `_handle_events` waterfall into layer registrations |
| 3 | Add global click-away unfocus handler |
| 4 | Add text-field-active shortcut blocking |

### Phase 3: Module Splits (estimated: 1–2 sessions)

| # | Task |
|---|------|
| 1 | Split `modals.py` → `modals/` package (5 files) |
| 2 | Split `inspector.py` → `inspector/` package (5 files) |
| 3 | Split `fp_preview.py` → `fp_preview/` package (4 files) |
| 4 | Split `ui.py` → `ui/` package (4 files) |
| 5 | Remove `panels.py` shim, update imports |

### Phase 4: State + Layout (estimated: 1 session)

| # | Task |
|---|------|
| 1 | Move `panel_mode` to EditorState |
| 2 | Extract data I/O functions to `editor/data_io.py` |
| 3 | Introduce `LayoutRects` cached per-frame rect computation |

### Phase 5: Feature Completion (estimated: 2–3 sessions)

| # | Task |
|---|------|
| 1 | Template slot property editing |
| 2 | Loot editor inline editing + item dropdown |
| 3 | Bake seed UI field |
| 4 | Inspector extras/tag editing |
| 5 | Forge tile_type dropdown |
| 6 | Template stamp placement |

---

## Appendix: Bug Index (Quick Reference)

| ID | Severity | Short Description | File(s) |
|----|----------|-------------------|---------|
| 4.1 | P0 | FP camera drift behind overlays | app.py, fp_preview.py |
| 4.2 | P0 | Global shortcuts fire in FP fullscreen | app.py |
| 4.3 | P0 | Focus leaks on inspector rebuild | inspector.py |
| 4.4 | P0 | Empty inventory/dialogue dropped on save | entity_defs.py |
| 4.5 | P0 | Dropdown 8-item cap, no scroll | ui.py |
| 4.6 | P0 | Entity panel set_clip leak | entity_panel.py |
| 5.1 | P1 | No FP camera reset on zone load | app.py |
| 5.2 | P1 | Inspector entity cache stale on edit | inspector.py |
| 5.3 | P1 | Inspector tile tab stale hover | inspector.py |
| 5.4 | P1 | NumberField can't type decimals/negatives | ui.py |
| 5.5 | P1 | Inspector scroll not reset on entity change | inspector.py |
| 5.6 | P1 | _keys_held leaks across FP transitions | fp_preview.py |
| 5.7 | P1 | Loot editor no clipping on right panel | loot_editor.py |
| 5.8 | P1 | Loot editor Edit button dead | loot_editor.py |
| 5.9 | P1 | Entity panel click-on-scrolled-out items | entity_panel.py |
| 5.10 | P1 | Tile palette click-on-scrolled-out swatches | tile_palette.py |
| 5.11 | P1 | AddComponentModal missing portal | modals.py |
| 5.12 | P1 | Modal scroll hardcoded 400 | modals.py |
| 5.13 | P1 | Dropdown click-away leaks event | ui.py |
| 5.14 | P1 | Menu click-away swallows event | menu_bar.py |
| 5.15 | P1 | Forge close doesn't refresh panels | entity_forge.py |
| 6.1 | P2 | Minimap entity position scale wrong | minimap.py |
| 6.2 | P2 | Minimap no clip rect | minimap.py |
| 6.3 | P2 | FP hardcoded HUD pixels | fp_preview.py |
| 6.4 | P2 | FP ghost surface alloc per frame | fp_preview.py |
| 6.5 | P2 | PIP hardcoded 400×300 cap | app.py |
| 6.6 | P2 | Inspector dropdown overflow | inspector.py |
| 6.7 | P2 | Inspector widget y-offset stale on resize | inspector.py |
| 6.8 | P2 | TextInputModal hardcoded pixels | modals.py |
| 6.9 | P2 | Forge title bar rect mismatch draw/event | entity_forge.py |

---

*End of audit.*
