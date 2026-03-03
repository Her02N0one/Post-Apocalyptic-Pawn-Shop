# Zone Editor Redesign — Radical Rethink

**Date:** 2026-03-02  
**Scope:** Full workflow redesign of `editor/view_3d/` and `editor/app/`  
**Problem:** The editor grew tool-by-tool. Each tool is a silo with its own selection model, keybinds, inspector UI, and batch semantics. The result: batch operations are difficult or impossible, common properties are edited through tool-specific interfaces instead of common ones, and the keybind space is overloaded with per-tool meanings.

### Implementation Status

| Phase | Status | Files |
|-------|--------|-------|
| **1. Selection Layer + Batch** | ✅ Done | `editor/view_3d/selection.py` (new), `editor/view_3d/editor.py` (modified), `editor/view_3d/tools_select.py` (modified) |
| **2. Editable Inspector** | ✅ Done | `editor/app/panels.py` (modified — `_draw_cell_inspector` rewrite + `_batch_set_cell_prop`) |
| **3. Keybind System** | ✅ Done | `editor/view_3d/editor.py` (`_on_keydown` rewrite), `editor/view_3d/constants.py` (new docs + hints) |
| **4. Unified Object Tool** | ✅ Done | `editor/view_3d/objects.py` (new — ObjectLayer), `editor/view_3d/editor.py` (multi-select wiring), `editor/app/panels.py` (cross-tool inspectors, prism inspector) |
| **5. Polish** | ✅ Done | Line selection (Shift+click), selection info panel, help overlay (?), display/tool label fixes |

**Key changes:**
- **1-5** = tool selection (Sculpt/Paint/Detail/Entity/Prism)
- **Ctrl+1-5** = display toggles (walls/floors/ceilings/entities/wireframe)
- **Alt+1-0** = hotbar texture slots (all 10)
- **6-0** = hotbar slots 6-10 (bare keys still work)
- **Ctrl+A** = select all cells
- **Ctrl+D** = duplicate selection (placeholder)
- **Escape** clears universal selection, then legacy selection, then aimed
- Old F5-F9 tool keys still work as aliases
- Old V/F/J/N/\ display toggles still work as aliases

---

## §1 — The 8 Concrete Problems

### 1.1 Selection is a Tool, Not a Layer

**Current:** Selection is a dedicated tool mode (`B` key). Entering select mode leaves your current tool. Selection is 2-click rectangle only. Selection is cleared when you switch to another tool. Selection only works on cells — not entities, prisms, quads, curves, or portals.

**Impact:** You can't "select 6 cells, then sculpt them all" — you have to be in select mode to define the area, then use the limited batch operations available *within* select mode (scroll to adjust, T/H/L keys). Switching to sculpt tool to use its full capabilities drops the selection.

### 1.2 Batch Operations Barely Exist

**Current:** With a selection active, you can: raise/lower floors (scroll), raise/lower ceilings (Shift+scroll), add/remove ceilings (T), make wall/open (H), flatten to aimed cell (L), fill/clear textures (LMB/RMB in select tool), reset cells (Delete). That's it.

**Missing:** Set absolute height values. Paint specific faces (N/S/E/W) across selection. Set upper wall height across selection. Batch-set light levels, reflectivity, fog density. Duplicate selection. Mirror/rotate selection. Copy selection to stamp. Select and transform multiple objects. Line-select or lasso-select.

### 1.3 No Numeric/Absolute Value Input

**Current:** Sculpting only supports relative raise/lower by the snap increment. To set a floor to exactly 2.75, you click dozens of times. The inspector shows floor/ceil heights as **read-only text** — you can't type a value.

**Impact:** Precision work is miserable. Making multiple rooms at exactly the same height requires the flatten shortcut (which requires aim + selection) rather than just typing "0.5" into a field.

### 1.4 Objects Are 5 Copies of the Same Pattern

**Current:** Entity, Prism, Quad, Portal, and Curve tools each independently implement:
- `_XXX_find_aimed()` — raycast to pick
- `_XXX_select(idx)` — set selection index
- `_XXX_deselect()` — clear selection
- `_XXX_delete(idx)` — remove from list
- `_XXX_move_to_aimed()` — reposition
- Per-type inspector panel in `panels.py`

Each tool has its own scroll behavior, its own keybinds, its own click interpretation. They're semantically identical but coded as 5 separate mixin files with separate inspector drawing functions.

**Impact:** You can only interact with ONE object type at a time. You can't select a prism and an entity together. You can't select-all objects in a region and move them. Each tool requires learning its own subtle differences.

### 1.5 Inspector is Display-Only for Critical Properties

**Current:** The cell inspector shows floor height, ceiling height, tile type, textures, segments — but most are read-only labels. Only light, reflectivity, and fog have sliders. There's no editable field for floor_height, ceil_height, upper_wall_height, or tile type.

**Impact:** The inspector should be the *primary* precision editing interface. Instead it's an info panel that happens to have 3 sliders.

### 1.6 Keybinds Are Overloaded and Inconsistent

| Problem | Example |
|---------|---------|
| F-keys for tools waste prime real estate | F5-F9 are far from WASD |
| Letter keys change meaning per tool | `R` = reset height in sculpt, rotate 90° in box tool, nothing in paint |
| Display toggles consume good keys | `V` (walls), `F` (floors), `J` (ceilings), `N` (entities) |
| Utility modes use scattered keys | `B`, `P`, `I`, `O`, `;` |
| Shift means different things | Shift+LMB = ceiling op in sculpt, paint all faces in paint, nothing in box |
| No chorded shortcuts | No Ctrl+D (duplicate), no Ctrl+A (select all) |
| Scroll does completely different things per tool | Snap cycle, palette cycle, Z-shift, width adjust, radius adjust... |

### 1.7 No Multi-Object Selection

**Current:** Each object tool tracks a single `_XXX_selected: int | None`. You can select exactly one entity, or one prism, or one quad. There's no Ctrl+click to add to selection, no marquee box-select for objects, no "select all entities in this cell".

### 1.8 Tool Switching Destroys Context

**Current:** Switching from entity tool to paint tool deselects the entity. Switching from box tool to sculpt deselects the prism. Going to select mode and back preserves, but the selection's batch ops are tool-limited.

---

## §2 — Design Principles for the Redesign

### P1: Selection is a Layer, Not a Tool

Selection should be a persistent, cross-cutting layer that EVERY tool respects. When you have 12 cells selected and you're in sculpt mode, LMB raises all 12 floors. In paint mode, LMB paints all 12 cells. Selection persists across tool switches.

### P2: Common Interfaces for Common Data

Floor height, ceiling height, textures, light levels — these are cell properties. They should always be editable from the inspector regardless of which tool is active. The inspector should have inline editable fields that apply to the current cell OR the entire selection.

### P3: Objects are Objects

Entities, prisms, quads, portals, and curves should share one selection model, one inspector pattern, and one set of operations (move, delete, duplicate, multi-select). Tool-specific behavior (e.g., prism resize) layers on top of the common base.

### P4: Absolute Values Over Relative

Every numeric property should be typeable. "Set floor to 2.5" should be as easy as typing 2.5 in the inspector. Relative raise/lower (scroll, click) should supplement, not replace, absolute value input.

### P5: Keybinds Should Be Predictable

One key = one meaning everywhere (or clearly scoped). Modifiers should be consistent: Shift always means "extend/add", Ctrl always means "precision/alternate", Alt always means "option variant".

### P6: Batch = Apply Operation to Selection

Every single-cell operation should automatically become a batch operation when a selection exists. No special batch code needed — the selection layer intercepts and iterates.

---

## §3 — The New Architecture

### 3.1 Selection Layer (`editor/view_3d/selection.py`)

```
SelectionState:
    cells: set[tuple[int, int]]           # selected (row, col) pairs
    objects: set[tuple[str, int]]          # selected (type, index) pairs
                                           # type = "entity"|"prism"|"quad"|"portal"|"curve"
    mode: "none" | "cells" | "objects" | "mixed"
    anchor_cell: tuple[int, int] | None    # for rectangle drag
    
Methods:
    toggle_cell(r, c)                      # Ctrl+click
    add_cell(r, c)                         # Shift+click
    set_rect(r1, c1, r2, c2)              # rectangle drag
    select_all_cells()                     # Ctrl+A
    select_line(r1, c1, r2, c2)           # Shift+click endpoint
    clear()
    
    toggle_object(type, idx)               # Ctrl+click on object
    add_object(type, idx)
    select_objects_in_rect(bounds)          # marquee select
    
    has_cells() -> bool
    has_objects() -> bool
    iter_cells() -> Iterator[tuple[int,int]]
    iter_objects() -> Iterator[tuple[str,int]]
    cell_count() -> int
    bounds() -> tuple[int,int,int,int] | None
```

### 3.2 Unified Batch Dispatch

Every tool operation that currently checks `if self._has_selection()` manually should instead go through a standardized batch dispatch:

```python
def batch_or_single(self, cell_fn, push_undo=True):
    """Apply cell_fn to selection if active, else to aimed cell."""
    if self.selection.has_cells():
        if push_undo:
            self._push_undo()
        changed = False
        for r, c in self.selection.iter_cells():
            if cell_fn(r, c):
                changed = True
        if changed:
            self.dirty = True
        return changed
    hit = self.aimed
    if not hit:
        return False
    if push_undo:
        self._push_undo()
    if cell_fn(hit.row, hit.col):
        self.dirty = True
        return True
    return False
```

### 3.3 Editable Inspector Properties

The inspector panel becomes the precision editing hub. Every cell property gets an inline editable field:

```
Cell (3, 7)                    [Apply to Selection] 
─────────────────────────────────
Floor Height    [___0.50___] ▲▼    <- input_float with arrows
Ceil Height     [___1.00___] ▲▼
Upper Wall      [___0.00___] ▲▼
Tile Type       [concrete    ▼]    <- dropdown
─────────────────────────────────
Floor Tex       [wood_floor  ▼]
Ceil Tex        [___________  ]
Wall N          [brick_wall  ▼]
Wall S          [___________  ]
Wall E          [___________  ]
Wall W          [___________  ]
─────────────────────────────────
Light           [====■=======] 0.75
Reflect         [====■=======] 128
Fog             [====■=======] 0.00
```

When a selection is active, the header changes to "12 Cells Selected" and fields show the common value (if all same) or "mixed". Editing a field applies to ALL selected cells.

### 3.4 Unified Object System

Replace the 5 separate tool mixins with a common object layer:

```python
class ObjectLayer:
    """Unified selection/manipulation for all placeable objects."""
    
    # Object types and their zone storage
    STORES = {
        "entity": "entities",
        "prism": "boxes",
        "quad": "quads",
        "portal": "render_portals",
        "curve": "curves",
    }
    
    selected: set[tuple[str, int]]  # shares with SelectionState
    
    def pick_nearest(self, cam, forward) -> tuple[str, int, float] | None
    def delete_selected(self)
    def duplicate_selected(self)
    def move_selected_to(self, world_x, world_z)
```

Tool-specific behavior (prism resize, curve radius, entity rotation) still lives in tool code, but the common operations (pick, select, move, delete, duplicate, inspector display) are unified.

### 3.5 New Keybind Map

**Philosophy:** Tools on easy-reach keys. Display toggles behind a prefix. Consistent modifiers.

| Key | Action | Scope |
|-----|--------|-------|
| `1` | Sculpt tool | Global |
| `2` | Paint tool | Global |
| `3` | Detail (Segment) tool | Global |
| `4` | Object tool (unified entity/prism/quad/portal/curve) | Global |
| `5` | Stamp/Preset tool | Global |
| `Tab` | Cycle tools 1→2→3→4→5 | Global |
| `~` (tilde) | Quick texure palette popup | Global |
| `Q/E` | Camera yaw (keep) | Camera |
| ── | **Selection** | ── |
| `LMB` | Tool action OR start rectangle select (if no cell hit) | Context |
| `Shift+LMB` | Add to selection (cell or object) | Always |
| `Ctrl+LMB` | Toggle in selection | Always |
| `Ctrl+A` | Select all cells / all objects (depends on tool) | Global |
| `Ctrl+D` | Duplicate selection | Global |
| `Escape` | Clear selection → release mouse (layered) | Global |
| `B` | Start rectangle select (always available) | Global |
| ── | **Sculpt** (tool 1) | ── |
| `LMB` | Raise floor (sel+batch or single) | Sculpt |
| `RMB` | Lower floor | Sculpt |
| `Shift+LMB` | Lower ceiling | Sculpt |
| `Shift+RMB` | Raise ceiling | Sculpt |
| `Scroll` | Adjust aimed surface | Sculpt |
| `R` | Reset to default height | Sculpt |
| `T` | Toggle ceiling on/off | Sculpt |
| `H` | Toggle wall/open | Sculpt |
| `L` | Flatten to aimed height | Sculpt |
| `G` | Cycle snap | Sculpt |
| `X` | Toggle Layer 2 sub-mode | Sculpt |
| ── | **Paint** (tool 2) | ── |
| `LMB` | Paint aimed face (batch if selection) | Paint |
| `RMB` | Erase texture | Paint |
| `Shift+LMB` | Paint all faces of cell | Paint |
| `Ctrl+LMB` | Flood fill | Paint |
| `MMB` | Eyedropper | Paint |
| `Scroll` | Cycle palette | Paint |
| ── | **Detail** (tool 3) | ── |
| `LMB` | Split segment | Detail |
| `RMB` | Merge segment | Detail |
| `MMB` | Paint segment | Detail |
| ── | **Object** (tool 4) | ── |
| `LMB` | Place / select object | Object |
| `RMB` | Deselect / delete targeted | Object |
| `Delete` | Delete selected | Object |
| `Ctrl+D` | Duplicate selected | Object |
| `Scroll` | Type-specific adjust | Object |
| `F` | Cycle object sub-type (entity→prism→quad→portal→curve) | Object |
| ── | **Display** (Ctrl prefix) | ── |
| `Ctrl+1` | Toggle walls visibility | Display |
| `Ctrl+2` | Toggle floors visibility | Display |
| `Ctrl+3` | Toggle ceilings visibility | Display |
| `Ctrl+4` | Toggle entities visibility | Display |
| `Ctrl+5` | Toggle wireframe | Display |
| ── | **Hotbar** (Alt prefix) | ── |
| `Alt+1` … `Alt+0` | Quick texture slot | Hotbar |
| ── | **Global** | ── |
| `Ctrl+S` | Save | Global |
| `Ctrl+Z` | Undo | Global |
| `Ctrl+Y` | Redo | Global |

**Key differences from current:**
- Tools on 1-5 (close to WASD) instead of F5-F9 (far away)
- Display toggles moved behind Ctrl+ prefix (frees V, F, J, N)
- Hotbar behind Alt+ prefix (frees number keys for tools)
- Selection always available (Shift+click, Ctrl+click, B for rectangle)
- Object tool is unified — sub-type cycled with F, not 5 separate tools
- Consistent Shift = ceiling/extend, Ctrl = precision/flood meanings

---

## §4 — Implementation Phases

### Phase 1: Selection Layer + Batch Foundation (core)

1. Create `editor/view_3d/selection.py` with `SelectionState`
2. Replace `_sel_start/_sel_end` with the new system
3. Add rectangle-drag selection (click + drag)
4. Add Shift+click to add, Ctrl+click to toggle
5. Make selection persist across tool switches
6. Implement `batch_or_single()` dispatch
7. Migrate all `_has_selection()` checks to use new system

### Phase 2: Editable Inspector  

1. Convert floor_height from read-only text to `imgui.input_float`
2. Convert ceil_height to `imgui.input_float`
3. Add upper_wall_height editable field
4. Add tile type dropdown (wall/open)
5. Add texture dropdowns for each face
6. When selection active: show "N cells selected", editable fields apply to all
7. Add "Set Floor Height" / "Set Ceil Height" batch fields

### Phase 3: New Keybind System

1. Extract keybind definitions to a data-driven map
2. Implement tool switching on 1-5
3. Move display toggles to Ctrl+1-5
4. Move hotbar to Alt+1-0
5. Add Ctrl+A, Ctrl+D global shortcuts
6. Ensure modifier consistency (Shift = extend, Ctrl = alt)

### Phase 4: Unified Object Tool

1. Create `editor/view_3d/objects.py` with `ObjectLayer`
2. Unify `_XXX_find_aimed` into one raycaster that checks all types
3. Merge selection into `SelectionState.objects`
4. Single inspector panel that adapts per type
5. Multi-object selection with Ctrl+click
6. Batch move/delete for object selection
7. Object sub-type cycling with `F` key

### Phase 5: Polish

1. Line selection mode (Shift+click two cells = select line between)
2. Copy/paste selection (stamps from selection)
3. Selection info overlay (count, bounds, avg height)
4. Keyboard shortcut help overlay (? key)

---

## §5 — Migration Strategy

Each phase should be **backward-compatible** — old keybinds continue working until fully replaced. The approach:

1. **Phase 1** adds the new selection system alongside the old one. Old selection code (`_sel_start/_sel_end`) is wrapped to delegate to the new system. All existing tests pass.

2. **Phase 2** adds editable fields to the inspector. Read-only display still works. Fields are additive.

3. **Phase 3** adds new keybinds as aliases first (both old and new work). Then deprecate old binds in a later commit.

4. **Phase 4** is the biggest change — unifying 5 object tools. This can be done by having the unified object tool call into the existing mixin methods initially, then gradually collapsing duplicated code.

---

## §6 — What This Enables

After the redesign, the following workflows become possible:

| Workflow | Before | After |
|----------|--------|-------|
| Select 20 cells, set all floors to 0.5 | Impossible (only relative) | Select → type 0.5 in inspector |
| Select a line of cells for a corridor wall | Click each cell individually | Shift+click two endpoints |
| Paint N wall face on 10 selected cells | Impossible | Select 10 cells in paint mode → LMB (paints aimed face type on all) |
| Select 3 entities + 2 prisms, move together | Impossible | Ctrl+click each → LMB to move |
| Set ceiling height on 30 cells to exact value | Switch to select, rectangle, scroll 60+ times | Select → type value in inspector |
| Duplicate a room (cells + objects) | Impossible | Select → Ctrl+D → move duplicate |
| See all keybinds for current tool | Read docs or HUD hints | `?` key shows overlay |
| Adjust prism height from panel | Must be in box tool, use Ctrl+scroll | Select prism, type height in inspector (any tool) |
