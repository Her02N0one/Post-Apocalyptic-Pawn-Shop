# Editor Codebase Audit

> **Scope:** `editor/` — 16 Python files, **7,378 lines total**  
> **Generated:** Comprehensive file-by-file analysis

---

## Summary Statistics

| File | Lines | Classes | Primary Responsibility |
|------|------:|--------:|------------------------|
| [modals.py](editor/modals.py) | 1,627 | 8 | Overlay dialogs (zone picker, text input, prefab picker, portal wizard, add-component, tile editor) |
| [panels.py](editor/panels.py) | 1,688 | 12 | Menu bar, tile palette, zone/entity/texture/portal/template panels, minimap, status bar, splitter |
| [inspector.py](editor/inspector.py) | 876 | 1 | Right-side tabbed inspector (Zone + Tile tabs) |
| [app.py](editor/app.py) | 840 | 1 | Main editor application, event routing, draw loop |
| [entity_forge.py](editor/entity_forge.py) | 754 | 1 | Full-screen Entity Forge overlay |
| [templates.py](editor/templates.py) | 669 | 1* | Zone template system + full-screen template editor (*TemplateEditor class + free functions) |
| [state.py](editor/state.py) | 646 | 4 | Central mutable state, zone I/O, undo/redo, helper queries |
| [ui.py](editor/ui.py) | 625 | 10 | Widget toolkit (Button, TextField, NumberField, Checkbox, Dropdown, ColorField, ScrollPanel, etc.) |
| [fp_preview.py](editor/fp_preview.py) | 510 | 1 | First-person raycaster preview + in-viewport editing |
| [loot_editor.py](editor/loot_editor.py) | 377 | 1 | Visual loot table editor overlay |
| [canvas.py](editor/canvas.py) | 239 | 1 | Map canvas rendering, coordinate transforms, cursor preview |
| [forge_registry.py](editor/forge_registry.py) | 232 | 2 | ForgeArchetype dataclass + ForgeRegistry singleton I/O |
| [palette_format.py](editor/palette_format.py) | 175 | 0 | Palette-pattern map compression (pure data transform) |
| [msgpack_io.py](editor/msgpack_io.py) | 186 | 0 | MessagePack binary zone export/import |
| [layout.py](editor/layout.py) | 121 | 1 | Responsive layout singleton |
| [__init__.py](editor/__init__.py) | 9 | 0 | Package docstring |

---

## Deep Dive: Priority Files

### 1. `app.py` — EditorApp (840 lines, 1 class)

**Responsibility count:** EditorApp is the **God Object** of the editor. It owns:
- Pygame window lifecycle (`_init`, `run`)
- Font management (2 fonts)
- **19 sub-system instances** created in `_init`
- All event routing (`_handle_events` ~100 lines)
- All keyboard shortcuts (`_handle_shortcut` ~50 lines)
- All action dispatch (`_dispatch_action` ~100 lines)
- Canvas mouse interaction (`_handle_canvas_event` ~100 lines)
- Forge entity placement logic (`_place_forge_entity` ~60 lines — **duplicated** from `modals.py:PrefabPickerModal._place_forge_archetype`)
- FP preview toggling
- MessagePack export
- Draw orchestration (`_draw` ~70 lines)
- Toast/update tick

**Key method sizes:**
| Method | Lines | Notes |
|--------|------:|-------|
| `_handle_events` | ~100 | Nested if/elif/continue chain |
| `_dispatch_action` | ~100 | 30+ elif branches |
| `_handle_canvas_event` | ~100 | Tool-specific mouse handling |
| `_handle_shortcut` | ~50 | Key-to-action mapping |
| `_draw` | ~70 | Panel mode if/elif routing |
| `_place_forge_entity` | ~60 | **Copy-pasted** from modals.py |
| `_init` | ~50 | 19 sub-system constructors |

**Code smells:**
- **God object**: One class does everything — routing, rendering, entity creation, export, state management helpers.
- **Duplicated forge placement**: `_place_forge_entity` (lines 641-710) is nearly identical to `PrefabPickerModal._place_forge_archetype` in modals.py (lines 440-490). Both build the same entity dict with the same kind-specific component logic.
- **Inline imports**: `from core.tiles import TILE_NAMES` inside `_handle_shortcut` (L321), `from core.tiles import TILE_REGISTRY as _reg` inside `_dispatch_action` (L370), `from editor.forge_registry import ForgeRegistry` inside `_place_forge_entity` (L642).
- **String-based dispatch**: `_dispatch_action` is a 30+ elif chain on action strings like `"save"`, `"load"`, `"panel:tiles"`, `"tool:brush"`. No enum, no command pattern, no registry.
- **Magic numbers**: `brush_size` clamped to `9` in multiple places (also in `state.py` and `panels.py`). `FPS = 60` is fine.

---

### 2. `panels.py` — 12 classes (1,688 lines)

**Class inventory:**
| Class | Lines | Purpose |
|-------|------:|---------|
| `MenuBar` | ~330 | Dropdown menu bar (File/Edit/View/Tools/Editors/Export) |
| `ZoneNav` | ~100 | Back/forward zone navigation bar |
| `TilePalette` | ~310 | Left-panel tile grid with search filter, type headers, thumbnails |
| `ZonePanel` | ~80 | Left-panel zone list browser |
| `EntityPanel` | ~200 | Left-panel entity browser (Prefabs + Forge tabs) |
| `TextureBrowserPanel` | ~130 | Left-panel texture grid |
| `PortalPanel` | ~100 | Left-panel portal list |
| `RoomTemplatePanel` | ~100 | Left-panel template list |
| `Minimap` | ~70 | Overlay minimap |
| `StatusBar` | ~50 | Bottom status bar with hover info + toast |
| `PanelSplitter` | ~100 | Draggable panel dividers |
| Aliases: `Sidebar`, `Toolbar` | 2 | Backward-compat = `MenuBar` |

**Separation quality: MIXED**
- Each panel class is self-contained (own `draw` + `handle_event`) — **good**.
- All 12 classes are in **one 1,688-line file** — this is the biggest file and should be split.
- `MenuBar._resolve_action` handles toggle/tool state changes itself, duplicating logic that `EditorApp._dispatch_action` also handles (e.g., `toggle_grid`, `brush_inc`, `brush_dec`).

**Code smells:**
- **File is too large**: 1,688 lines with 12 classes. Should be split into at least `menu_bar.py`, `palette.py`, `left_panels.py`, `minimap.py`, `status_bar.py`, `splitter.py`.
- **Module-level `_MENU_DEFS`** data structure (70 lines) could live in a separate `menu_defs.py` or in `layout.py`.
- **Bottom `import os`** at line 1441: `import os  # needed by RoomTemplatePanel` — import at bottom of module, after class definitions that need it. Should be at the top.
- **Duplicated toggle logic**: `MenuBar._resolve_action` toggles `show_grid`, `show_minimap`, `brush_size` internally and returns `None` — but `EditorApp._dispatch_action` also handles these same actions. If the menu resolves them, the app never sees them; if a shortcut sends `"toggle_grid"` to `_dispatch_action`, the toggle happens there. This dual path is fragile.
- **Backward-compat aliases**: `Sidebar = MenuBar` and `Toolbar = MenuBar` are confusing dead code.
- **`getattr(self, '_hit_areas', [])` / `getattr(self, '_header_areas', [])` / `getattr(self, '_total_h', 0)`**: Several attributes are conditionally created in `draw()` and Read via `getattr` fallback in `handle_event()`. These should be initialized in `__init__`.

---

### 3. `inspector.py` — Inspector (876 lines, 1 class)

**Size & tangling:**
- 876 lines, **single class** `Inspector`.
- `_rebuild_widgets` and `_build_entity_widgets` together are ~250 lines of raw widget construction — building tuples like `("labeled_widget", "ID:", id_field, px, y)`.
- Widget drawing loop (`draw`) is ~120 lines of `if kind == "label"... elif kind == "kv"...` matching.
- Event handling (`_handle_zone_events`) similarly loops over widget tuples by kind.

**Code smells:**
- **Primitive obsession / tuple-soup**: Widgets are stored as raw tuples `("kind", ...)` with positional fields. No dataclass, no named fields. Every draw/event loop must pattern-match on `entry[0]`.  This is fragile: adding a new field means touching every consumer.
- **Mixed rendering + data binding**: `_build_entity_widgets` creates UI widgets AND sets up `on_change` lambdas that mutate entity dicts directly via `_d.__setitem__("key", v)`. Mixing UI construction with direct entity mutation makes testing impossible.
- **Long chain of `if component is not None`**: Each ECS component (collider, health, tile_entity, wall_sprite, inventory, facing, dialogue) has a handcrafted widget section. Adding a component means adding ~30 lines of widget code.
- **Fragile `_last_tile_id` sentinel**: `self._last_tile_id` is set to `-999` (an int) in `force_rebuild()` but compared to `st.selected_tile` (a string). Works because `-999 != "grass"` but is a type mismatch smell.

---

### 4. `state.py` — EditorState (646 lines, 4 classes)

**Classes:** `Tool` (constants), `Snapshot`, `History`, `EditorState`.

**EditorState attributes (27+):**
| Category | Attributes |
|----------|------------|
| Zone data | `zone_name`, `tiles`, `map_w`, `map_h`, `anchor`, `portals`, `entities`, `first_person` |
| View | `cam_x`, `cam_y`, `zoom`, `show_grid`, `show_minimap` |
| Tool | `tool`, `selected_tile`, `brush_size`, `selected_entity`, `entity_dragging`, `pending_prefab` |
| Pan | `_panning`, `_pan_start`, `_cam_start` |
| Hover | `hover_tile` |
| Toast | `toast_msg`, `toast_timer` |
| History | `history`, `dirty` |
| Navigation | `zone_history`, `zone_history_idx` |

**Code smells:**
- **God data object**: 27+ attributes spanning zone data, view state, tool state, panning state, hover, toast, history. Should separate into `ZoneData`, `ViewState`, `ToolState`.
- **Panning state is UI concern**: `_panning`, `_pan_start`, `_cam_start` should live in the canvas, not in state. Currently `app.py` reads/writes these directly on `state`.
- **History does full `deepcopy` on every undo/redo**: For large zones this is expensive. A command pattern or delta-based approach would be better.
- **Free functions at module level**: `list_zones`, `list_loot_tables`, `load_loot_tables`, `save_loot_tables`, `load_item_ids` (170+ lines) are all in state.py. These are data-access functions that should live in their own `data_io.py` or `data_queries.py`.
- **`Tool` is a namespace, not an enum**: `Tool.BRUSH = "brush"` — just string constants. Should be `enum.StrEnum` for type safety.
- **`save_loot_tables` hand-serializes TOML line-by-line** (50 lines) instead of using `tomli-w` or `tomlkit`. Same for `ForgeRegistry.save()`.

---

### 5. `modals.py` — 8 modal classes (1,627 lines)

**Class inventory:**
| Class | Lines | Purpose |
|-------|------:|---------|
| `ModalManager` | ~30 | Only-one-at-a-time modal stack |
| `_BaseModal` | ~30 | Shared overlay dimming + panel drawing |
| `TextInputModal` | ~40 | Single text field + Enter/Esc |
| `ZonePickerModal` | ~80 | Scrollable zone list |
| `PrefabPickerModal` | ~200 | Tabbed entity picker (Prefabs + Forge) with entity creation logic |
| `AddComponentModal` | ~60 | Add missing ECS component |
| `PortalWizardModal` | ~350 | 3-step portal creation wizard with full minimap rendering |
| `TileEditorModal` | ~500+ | Full tile definition editor (create/edit/delete tiles, import textures, face textures, categories) |

**Code smells:**
- **`TileEditorModal` is massive** (~500 lines): It's a full-featured no-op-code tile editor within a single class. The `draw` method alone is ~250 lines of manual Pygame drawing. The `handle_event` is ~200 lines of nested field/slider/dropdown handling.  It implements its own text-field focus system (`_name_active`, `_tex_active`, `_face_active`, `_cat_active`) **instead of using the `TextField` widget** from `ui.py`.
- **Duplicated entity creation**: `PrefabPickerModal._place_prefab` and `_place_forge_archetype` duplicate the entity-building logic from `EditorApp._place_forge_entity`. Three places build entity dicts with the same structure.
- **`_BaseModal._draw_panel` creates a new font every call**: Line 94: `font = pygame.font.SysFont("monospace", 14)` — font creation in a per-frame draw method. Should be cached.
- **PortalWizardModal renders a full tilemap**: `_draw_tile_step` (lines 730-815) implements its own tile rendering loop with camera/zoom/panning — duplicating `Canvas.draw()` logic.
- **Mixed `import` placements**: `import json` at line 19 (fine), `import os as _os` at line 978, `from pathlib import Path as _Path` at line 979 — imports midway through the file to avoid top-level import overhead, but it's just style inconsistency.

---

### 6. `ui.py` — Widget Toolkit (625 lines, 10 classes)

**Widget inventory:**
| Class | Lines | Purpose |
|-------|------:|---------|
| `Theme` | 20 | Color constants (20 named colors) |
| `UIContext` | 20 | Keyboard focus tracker |
| `Button` | 35 | Clickable button |
| `ToggleButton` | 25 | Toggle state button (extends Button) |
| `TextField` | 80 | Text input with cursor, selection |
| `NumberField` | 70 | Numeric input with +/- buttons |
| `Checkbox` | 25 | Boolean toggle |
| `Dropdown` | 60 | Single-select dropdown |
| `ColorField` | 40 | RGB triplet input with swatch |
| `ScrollPanel` | 70 | Scrollable container with scrollbar |

Plus free functions: `draw_text`, `draw_text_centered`, `draw_section_header`, `draw_label`, `_clamp`.

**Assessment: This is the cleanest file.** Good separation, consistent API (`draw` + `handle_event`), no god objects. Minor issues:
- **No `TextArea` / multi-line widget**: `TileEditorModal` reinvents text input rather than extending `TextField`.
- **`Dropdown` limited to 8 visible items**: `draw_dropdown` shows `self.options[:8]` — hardcoded limit with no scrolling.
- **Missing `__init__` on ScrollPanel attributes**: `_dragging_thumb` and `_drag_offset` are properly initialized, but the pattern isn't consistent across all widgets.

---

## Remaining Files

### `entity_forge.py` (754 lines, 1 class)
- `EntityForgeModal`: Full-screen entity archetype editor.
- Cleanly structured with form widget cache, `_rebuild_form`/`_apply_form` pattern.
- **Smell**: `_apply_form` reads widgets, updates archetype, but doesn't validate. Renaming an archetype ID can silently create duplicates.

### `forge_registry.py` (232 lines, 2 classes)
- `ForgeArchetype` dataclass + `ForgeRegistry` singleton.
- **Smell**: Singleton pattern via `_instance` class variable. Hand-serializes TOML (50 lines) instead of using a library.
- Clean dataclass with typed fields — one of the better files.

### `templates.py` (669 lines, 1 class + free functions)
- ~120 lines of I/O helper functions, ~50 lines of `bake_template` logic, ~500 lines of `TemplateEditor` UI class.
- `TemplateEditor` is similar in structure to `EntityForgeModal` — full-screen overlay with list + form.

### `fp_preview.py` (510 lines, 1 class)
- DDA raycaster with WASD+mouse-look + tile painting.
- Self-contained, minimal external dependencies.
- **Smell**: `_keys_held: set[int]` is a raw set — no debounce or key repeat management.

### `canvas.py` (239 lines, 1 class)
- Clean, focused: tile rendering, coordinate transforms, entity drawing, cursor preview.
- **Smell**: Lazy global `_PREFAB_DEFAULTS` / `_prefabs_loaded` at module level for caching prefab imports. Not thread-safe, but acceptable for single-threaded Pygame.

### `layout.py` (121 lines, 1 class)
- Mutable singleton with class-level attributes.
- Clean, well-documented. Proper clamping and min/max constraints.

### `palette_format.py` (175 lines, 0 classes)
- Pure data transformation, no Pygame dependency.
- Cleanest file in the package. No smells.

### `msgpack_io.py` (186 lines, 0 classes)
- Clean binary format with header/payload split.
- Graceful `msgpack` import fallback.

### `__init__.py` (9 lines)
- Package docstring only.

---

## `except Exception` Usage (13 instances)

All 13 are **silent swallowers** (catch + `pass` or minimal handling):

| File | Line | Context | Severity |
|------|-----:|---------|----------|
| [state.py](editor/state.py#L563) | 563 | `list_loot_tables` — TOML parse failure | Low (returns `[]`) |
| [state.py](editor/state.py#L583) | 583 | `load_loot_tables` — TOML parse failure | Low (returns `{}`) |
| [state.py](editor/state.py#L644) | 644 | `load_item_ids` — TOML parse failure | Low (returns `[]`) |
| [panels.py](editor/panels.py#L514) | 514 | Texture thumbnail load failure | Low (returns `None`) |
| [panels.py](editor/panels.py#L911) | 911 | EntityPanel prefab cache load | Medium — silently hides import errors |
| [panels.py](editor/panels.py#L918) | 918 | EntityPanel forge cache load | Medium |
| [panels.py](editor/panels.py#L1135) | 1135 | TextureBrowserPanel file list | Low |
| [panels.py](editor/panels.py#L1186) | 1186 | Texture thumbnail blit | Low |
| [modals.py](editor/modals.py#L229) | 229 | ForgeRegistry import in PrefabPickerModal | Medium — hides missing module |
| [modals.py](editor/modals.py#L1041) | 1041 | Atlas texture preview in TileEditorModal | Low |
| [modals.py](editor/modals.py#L1577) | 1577 | Import PNG via file dialog | OK — shows error in `_error` |
| [inspector.py](editor/inspector.py#L690) | 690 | Atlas texture preview | Low |
| [forge_registry.py](editor/forge_registry.py#L144) | 144 | TOML file parse | OK — prints error |

---

## TODO / FIXME / HACK Comments

**None found.** No TODO, FIXME, HACK, XXX, TEMP, or KLUDGE markers exist anywhere in the editor package.

---

## Prioritized Worst Offenders

### Tier 1 — Critical Separation of Concerns Issues

1. **`panels.py` (1,688 lines, 12 classes)** — Needs splitting immediately. Should be 5-6 files: `menu_bar.py`, `palette.py`, `left_panels.py` (zone/entity/texture/portal/template), `minimap.py`, `status_bar.py`, `splitter.py`.

2. **`modals.py` (1,627 lines, 8 classes)** — `TileEditorModal` alone is ~500 lines and reimplements TextField's focus system. Should extract `TileEditorModal` into its own file. `PortalWizardModal` duplicates Canvas rendering.

3. **`app.py` — God Object** — `EditorApp` has 19 sub-system fields and routes every event/action through itself. The `_dispatch_action` 30+ elif chain should become a command registry. Forge entity placement logic is duplicated from modals.py.

### Tier 2 — Design Debt

4. **Duplicated entity placement logic** — Entity dict construction with kind-specific components exists in 3 places: `app.py:_place_forge_entity`, `modals.py:PrefabPickerModal._place_prefab`, `modals.py:PrefabPickerModal._place_forge_archetype`. Should be one `entity_factory.py` function.

5. **`inspector.py` tuple-soup widget system** — Widgets stored as positional tuples with string-tag dispatch (`"label"`, `"kv"`, `"entity_row"`, etc.). Should use dataclasses or a proper widget tree.

6. **`state.py` data-access functions** — 170+ lines of TOML I/O (`list_loot_tables`, `save_loot_tables`, `load_item_ids`) don't belong in the state module. Extract to `data_io.py`.

7. **`state.py` EditorState bloat** — 27+ attributes mixing zone data, view state, tool state, panning. Should decompose into `ZoneData`, `ViewState`, `ToolState` sub-objects.

### Tier 3 — Minor Smells

8. **`Tool` is not an enum** — String constants in a plain class. Use `enum.StrEnum`.

9. **Hand-serialized TOML** — Both `state.py:save_loot_tables` and `forge_registry.py:ForgeRegistry.save` manually build TOML strings. Use `tomli-w` or `tomlkit`.

10. **`_BaseModal._draw_panel` creates font per-frame** — `pygame.font.SysFont("monospace", 14)` called every frame inside draw.

11. **Dropdown hardcoded to 8 items** — No scrolling support for long option lists.

12. **`MenuBar` duplicates toggle/brush logic** — `_resolve_action` toggles the same state that `EditorApp._dispatch_action` would, creating a dual-path for the same actions.

13. **Backward-compat aliases** — `Sidebar = MenuBar` and `Toolbar = MenuBar` at the bottom of panels.py — likely dead code.

14. **Bottom-of-file `import os`** — panels.py line 1441.

15. **`getattr(self, '_hit_areas', [])` anti-pattern** — Several panels use attributes created in `draw()` and accessed in `handle_event()` via `getattr` fallback instead of initializing in `__init__`.
