# Select Tool & Editor Performance Audit

**Date:** 2025  
**Scope:** 3D zone editor (`editor/view_3d/`) — select tool design, mixin architecture, rendering performance  
**Files audited:** editor.py (1093 lines), rendering.py (1733 lines), tools_select.py (216 lines), primitives.py (260 lines), geometry.py (100 lines), constants.py, 12 tool mixins

---

## Table of Contents

- [§1 — Executive Summary](#1--executive-summary)
- [§2 — Select Tool: Current State](#2--select-tool-current-state)
- [§3 — Select Tool: What's Missing](#3--select-tool-whats-missing)
- [§4 — Architecture Problem: Why Batch Ops Are Hard](#4--architecture-problem-why-batch-ops-are-hard)
- [§5 — Performance Audit: Why 30×30+ Maps Lag](#5--performance-audit-why-3030-maps-lag)
- [§6 — Proposed Changes: Select-as-Mode](#6--proposed-changes-select-as-mode)
- [§7 — Proposed Changes: Performance Fixes](#7--proposed-changes-performance-fixes)
- [§8 — Execution Plan](#8--execution-plan)

---

## §1 — Executive Summary

Three interconnected problems:

1. **Select is too limited.** It can fill textures, clear textures, reset cells, and scroll-adjust heights. It can't do what most tools can do (add ceilings, place walls, layer2 ops, paint per-face, segment, etc.). Every new batch operation requires manually adding another method to `SelectMixin`.

2. **Mixin architecture fights batch operations.** Each tool mixin (`SculptMixin`, `PaintMixin`, `Layer2Mixin`, etc.) is written to operate on `self.aimed` — a single cell. None of them have a "do this to a rectangle" variant. Duplicating every single-cell method as a batch method would double the tool code.

3. **Rendering is O(W×H) per frame with no culling.** A 30×30 map = 900 cells × up to 3 geometry parts each × 6 faces per filled box × projection + polygon fill per face. That's ~16,200 polygon fills per frame before overlays. At 40×40 it's ~28,800. The Python-side software renderer can't sustain this.

---

## §2 — Select Tool: Current State

**File:** `editor/view_3d/tools_select.py` (216 lines)

### State
- `_sel_start: (row, col) | None` — first corner of rectangle
- `_sel_end: (row, col) | None` — second corner
- `_sel_ceiling_mode: bool` — whether scroll adjusts ceilings instead of floors

### Operations
| Trigger | Operation | Lines |
|---------|-----------|-------|
| LMB (1st click) | Set `_sel_start` to aimed cell | ~30 |
| LMB (2nd click) | Set `_sel_end` to aimed cell | ~6 |
| RMB (with selection) | Clear textures in rectangle | ~20 |
| LMB (with selection) | Fill textures in rectangle | ~25 |
| Delete | Reset cells to defaults | ~15 |
| Scroll | Raise/lower floors (or ceilings if ceiling\_mode) | ~50 |
| X | Toggle `_sel_ceiling_mode` | 2 |
| Escape | Cancel selection | 4 |

### Limitations
- **No batch ceiling add/remove** — Can't add ceilings to sky-cells or remove ceilings to make cells open-sky.
- **No batch wall place/remove** — Can't convert open cells to walls or vice versa.
- **No batch layer2** — Can't add/remove secondary floors/ceilings.
- **No per-face texture fill** — Always fills floor surface or all wall faces. Can't target specific faces.
- **No batch segment operations** — Can't split/merge segments across selection.
- **No batch entity/box scatter** — Can't stamp entities across selection.
- Only operates on its own dispatch — completely disconnected from what other tools can do.

---

## §3 — Select Tool: What's Missing

Operations that should work on selections but don't:

| Category | Operation | Currently Possible? |
|----------|-----------|:-------------------:|
| Sculpt | Set all floors to specific height | ❌ (scroll only, no absolute set) |
| Sculpt | Set all ceilings to specific height | ❌ |
| Sculpt | Add ceilings (cap open-sky cells) | ❌ |
| Sculpt | Remove ceilings (make cells open-sky) | ❌ |
| Sculpt | Flatten all floors to same height | ❌ |
| Sculpt | Convert all to wall / open | ❌ |
| Paint | Fill specific face (N/S/E/W) | ❌ |
| Paint | Fill floor texture | ✅ (LMB) |
| Paint | Fill ceiling texture | ❌ |
| Paint | Clear textures | ✅ (RMB) |
| Layer2 | Add floor2/ceil2 to selection | ❌ |
| Layer2 | Remove floor2/ceil2 from selection | ❌ |
| Layer2 | Set floor2/ceil2 height | ❌ |
| Segment | Auto-split all selected faces | ❌ |
| Entity | Scatter entities in selection | ❌ |
| General | Copy selection to stamp | ❌ |
| General | Reset to defaults | ✅ (Delete) |

---

## §4 — Architecture Problem: Why Batch Ops Are Hard

### Current Tool Dispatch Model

```
_on_click(event)
  ├─ if tool == "sculpt":
  │     if _sculpt_layer2: _layer2_raise() / _layer2_lower()
  │     else: _tool_floor_raise() / _tool_floor_lower()
  ├─ if tool == "paint":
  │     _paint() / _erase_texture() / _pick_texture()
  ├─ if tool == "select":
  │     _sel_click() / _sel_rclick()          ← completely separate
  └─ ...
```

Every tool method reads `self.aimed` — a single `_CellHit` — and operates on that one cell. There's no abstraction for "operate on a set of cells."

### Why This Fight Batch Ops

1. **No `apply_to_region(r_min, c_min, r_max, c_max)` pattern.** Each tool method (`_tool_floor_raise`, `_paint`, `_layer2_raise`) hard-codes `hit = self.aimed; r, c = hit.row, hit.col`. To batch them, you'd need to either:
   - Wrap each call in a loop that temporarily overrides `self.aimed` — hacky and fragile.
   - Duplicate every method with a `(r, c)` parameter variant — massive code duplication.
   - Refactor every tool to accept `(r, c)` instead of reading `self.aimed` — correct but large refactor.

2. **Select is a "tool" competing with other tools.** You can't use sculpt+select simultaneously because the tool system only allows one active tool at a time. This is the fundamental design mismatch: selection should be a *cross-cutting mode*, not a tool.

3. **Undo granularity.** Batch operations need a single undo snapshot. Currently `_push_undo()` is called per-click in individual tool methods. A batch op would need to push once, iterate, then mark dirty — the existing methods don't support this call pattern.

### The Core Insight

> Select shouldn't be a tool. It should be a **modifier layer** that any tool can read: "here are the cells to operate on." When you raise the floor in sculpt mode with an active selection, it should raise all selected cells.

---

## §5 — Performance Audit: Why 30×30+ Maps Lag

### Cost Breakdown

The `draw()` method calls these sub-methods per frame:

| Method | Complexity | Cost at 30×30 |
|--------|-----------|---------------|
| `_draw_cell_boxes` | O(W×H × parts × 6 faces) | 900 cells × ~2.5 parts × 6 faces = **~13,500 polygon fills** |
| `_draw_surface_markers` | O(W×H × 8 lines) | 900 × 8 = **7,200 line draws** |
| `_draw_seg_boundary_rings` | O(W×H × 4 faces × segs) | Up to **14,400 line draws** |
| `_draw_layer2_slabs` | O(W×H) | Up to 1,800 box draws |
| `_draw_selection_highlight` | O(selection_area) | Usually small |
| `_draw_entities` | O(n_entities) | Usually small |
| `_draw_boxes` | O(n_boxes) | Usually small |
| `_update_aim` (raycasting) | O(search_range² × parts) | 48×48 search = **~5,760 AABB tests** |

**Total per frame at 30×30: ~35,000+ draw calls in pure Python/pygame.**

At 40×40: ~62,000 draw calls. At 50×50: ~97,000.

### Root Causes

#### 1. No View Frustum Culling
`_draw_cell_boxes` iterates every cell in the map, computes distance, sorts, then draws. Cells behind the camera or outside the field of view still get processed up to the projection step. The sort itself is O(n log n) on thousands of items.

```python
# rendering.py line ~385
for r in range(H):
    for c in range(W):
        for part, yb, yt in self._cell_boxes(r, c):  # called for ALL cells
            d = ((cam[0]-mx)**2 + ...)
            box_list.append((d, r, c, part, yb, yt))
box_list.sort(reverse=True)  # sorting 2000+ items
```

#### 2. No Dirty-Region Tracking
Every frame redraws the entire scene from scratch. Moving the camera 0 pixels still triggers a full re-render. There's no concept of "only redraw if something changed."

#### 3. Pure Python Projection
Every 3D→2D projection is done in Python (`_project`, `_project_poly`, `_project_line` in `math3d.py`). Each `_filled_box` call does 8 corner projections + 6 face back-face tests + up to 6 polygon projection+clip operations. This is the hot inner loop and it's all interpreted Python.

#### 4. Per-Cell `_cell_boxes` Is Expensive
`_cell_boxes` calls `tile_def()` (dict lookup), reads floor/ceil heights, does neighbour lookups for floor-mass bottom, builds a list of tuples. Called once per cell per frame in rendering + again per cell in raycasting.

#### 5. Surface Markers Draw 4 Lines Per Cell
`_draw_surface_markers` draws 4 `_line3d` calls for floor markers and 4 for ceiling markers for every non-wall cell. That's 8 × `_project_line` calls per cell even when the cell is behind the camera.

#### 6. Alpha-Blended Box Faces Create Temporary Surfaces
`_filled_box` with `alpha < 255` creates a new `pygame.Surface` per face, draws a polygon to it, then blits it. This hits the allocator hard in selection highlights and layer2 overlays.

#### 7. Raycasting Search Window Is 48×48
`_update_aim()` searches `min(FAR_CLIP+1, 24)` cells in each direction from the camera — a 48×48 grid. For each cell it calls `_cell_boxes` and `_ray_vs_aabb` for each part. That's up to 2,304 cells × 3 parts = 6,912 AABB intersection tests per frame.

---

## §6 — Proposed Changes: Select-as-Mode

### Design: Selection as a Persistent Cross-Tool Layer

Instead of select being tool index 4 that fights with sculpt/paint/erase, make it an **orthogonal modifier**:

```
┌─────────────────────────────────────────┐
│  Active Tool:  sculpt | paint | erase   │
│  Selection:    None | (r1,c1)→(r2,c2)   │  ← independent
│  Layer2 mode:  off | on                  │
│  Ceiling mode: off | on                  │
└─────────────────────────────────────────┘
```

**Key binding:**
- **B** (current select toggle): Enter/exit **selection mode** as an overlay  
- While in selection mode, LMB sets corners (same as now)  
- Once a selection exists, it **persists across tool switches**  
- Using any tool with an active selection → batch-applies to all selected cells  
- **Escape** clears selection (same as now)

### Tool Integration Pattern

Refactor each tool's core operation to accept explicit `(r, c)`:

```python
# Before (reads self.aimed)
def _tool_floor_raise(self):
    hit = self.aimed
    if not hit: return
    r, c = hit.row, hit.col
    self._push_undo()
    # ... modify zone.floor_heights[r][c] ...

# After (accepts explicit cell)
def _tool_floor_raise_at(self, r: int, c: int) -> bool:
    """Raise floor at (r,c). Returns True if changed."""
    # ... modify zone.floor_heights[r][c] ...
    return True

def _tool_floor_raise(self):
    """Click handler: apply to aimed cell or selection."""
    if self._has_selection():
        self._push_undo()
        self._apply_to_selection(self._tool_floor_raise_at)
        self.dirty = True
    elif self.aimed:
        self._push_undo()
        self._tool_floor_raise_at(self.aimed.row, self.aimed.col)
        self.dirty = True
```

### Selection Helper Methods (added to SelectMixin)

```python
def _has_selection(self) -> bool:
    return self._sel_start is not None and self._sel_end is not None

def _apply_to_selection(self, fn: Callable[[int, int], bool]) -> bool:
    """Apply fn(r, c) to every cell in the selection rectangle."""
    bounds = self._sel_bounds()
    if bounds is None:
        return False
    r_min, c_min, r_max, c_max = bounds
    changed = False
    for r in range(r_min, r_max + 1):
        for c in range(c_min, c_max + 1):
            if fn(r, c):
                changed = True
    return changed
```

### New Batch Operations (via selection + existing tool)

| Tool Active | Action | Batch Behavior |
|-------------|--------|----------------|
| Sculpt | LMB | Raise all selected floors by snap_y |
| Sculpt | RMB | Lower all selected floors by snap_y |
| Sculpt | T | Toggle ceiling on all selected cells |
| Sculpt+L2 | LMB | Add floor2 to all selected cells |
| Paint | LMB | Paint aimed face direction on all selected cells |
| Paint | RMB | Clear textures on all selected cells |
| Erase | LMB | Reset all selected cells |
| Scroll | Up/Down | Same as current select scroll (already works) |

### Migration Path

1. Keep `_sel_start` / `_sel_end` / `_sel_ceiling_mode` / `_sel_bounds()` as-is
2. Remove "select" from `UTIL_TOOLS` — it's no longer a tool
3. B key toggles `_selection_active: bool` — this just controls whether clicks set selection corners vs. perform tool ops
4. Selection rectangle persists when switching tools  
5. Each tool checks `_has_selection()` and branches to batch path
6. Existing select-only operations (texture fill, clear, reset) become normal batch ops for their respective tools

---

## §7 — Proposed Changes: Performance Fixes

Ordered by impact-to-effort ratio:

### P0: View Frustum Culling (High Impact, Medium Effort)

Add a frustum test before processing each cell:

```python
def _visible_cells(self, W, H):
    """Yield (r, c) for cells potentially visible from current camera."""
    # Compute frustum planes from VP matrix
    # For each cell, test AABB against frustum
    # Only yield cells that pass
    ...
```

**Expected improvement:** 60–80% reduction in draw calls. Most maps have the camera looking at maybe 20–30% of cells at any time.

**Simpler alternative:** Use camera yaw to compute a forward-facing sector and only iterate cells in a wedge shape + near radius:

```python
cam_c, cam_r = int(self.cam_x), int(self.cam_z)
fwd_x, fwd_z = math.cos(self.yaw), -math.sin(self.yaw)
for r in range(max(0, cam_r - R), min(H, cam_r + R)):
    for c in range(max(0, cam_c - R), min(W, cam_c + R)):
        # Reject cells behind camera
        dx, dz = c + 0.5 - self.cam_x, r + 0.5 - self.cam_z
        if dx * fwd_x + dz * fwd_z < -1.0:
            continue  # behind camera
        yield r, c
```

### P1: Cache `_cell_boxes` Results (High Impact, Low Effort)

`_cell_boxes(r, c)` is called twice per frame per cell (once in rendering, once in raycasting). It does `tile_def()` lookups, height reads, and neighbour checks every time.

**Fix:** Cache results in a dict, invalidate on `self.dirty = True`:

```python
def _cell_boxes_cached(self, r: int, c: int):
    key = (r, c)
    if key in self._cell_box_cache:
        return self._cell_box_cache[key]
    result = self._cell_boxes(r, c)
    self._cell_box_cache[key] = result
    return result

# In draw():
if self.dirty:
    self._cell_box_cache.clear()
    self.dirty = False
```

### P2: Skip Surface Markers for Distant Cells (Medium Impact, Low Effort)

`_draw_surface_markers` draws 8 lines per cell regardless of distance. Add a distance check:

```python
def _draw_surface_markers(self, ...):
    cam_c, cam_r = int(self.cam_x), int(self.cam_z)
    max_dist_sq = 12.0 ** 2  # only draw markers within 12 cells
    for r in range(H):
        for c in range(W):
            if (r - cam_r)**2 + (c - cam_c)**2 > max_dist_sq:
                continue
            ...
```

### P3: Reduce Raycasting Search Window (Medium Impact, Low Effort)

The current 48×48 search window (24 in each direction) is far larger than needed for a first-person editor view. Reduce to 16:

```python
search = min(int(FAR_CLIP) + 1, 16)  # was 24
```

For typical FOV and interaction distance, 16 cells is more than enough.

### P4: Batch Segment Boundary Drawing (Low Impact, Low Effort)

`_draw_seg_boundary_rings` iterates W×H×4 faces even when most cells have no segments. Pre-compute a dirty set of cells that actually have segments > 1.

### P5: Avoid Per-Face Surface Allocation for Alpha (Medium Impact, Medium Effort)

`_filled_box` allocates a new `pygame.Surface` for every alpha-blended face. For selection highlights covering 100+ cells, this creates hundreds of temp surfaces per frame.

**Fix:** Pre-allocate a reusable scratch surface:

```python
# In __init__:
self._alpha_scratch = pygame.Surface((800, 600), pygame.SRCALPHA)

# In _filled_box:
scratch = self._alpha_scratch
if tw > scratch.get_width() or th > scratch.get_height():
    self._alpha_scratch = pygame.Surface(
        (max(tw, scratch.get_width()), max(th, scratch.get_height())),
        pygame.SRCALPHA)
    scratch = self._alpha_scratch
sub = scratch.subsurface((0, 0, tw, th))
sub.fill((0, 0, 0, 0))
pygame.draw.polygon(sub, (r, g, b, alpha), off)
surface.blit(sub, (min_x, min_y))
```

### P6: Long-Term — Move Projection to C Extension (High Impact, High Effort)

The project already has C extensions (`_fast_cast.c`, `_ray_render.c`). The projection math in `math3d.py` is the hottest loop and would benefit enormously from C. A `_project_cells(vp, cells, cam)` function that takes the VP matrix and returns screen-space polygons would cut frame time by 5–10×.

---

## §8 — Execution Plan

### Phase 1: Quick Wins (Performance)
- [x] P1: Add `_cell_box_cache` with dirty invalidation
- [x] P2: Distance-gate surface markers at 12 cells
- [x] P3: Reduce raycasting search from 24→16
- [x] P0 (simple): Add behind-camera rejection to `_draw_cell_boxes`

### Phase 2: Select-as-Mode Foundation
- [x] Move selection state (`_sel_start`, `_sel_end`, `_sel_ceiling_mode`) to persist across tool switches
- [x] Add `_has_selection()` and `_apply_to_selection(fn)` helpers
- [x] B key tri-state behaviour (in select→exit preserving; has selection→clear; no selection→enter)
- [x] Selection rendering (`_draw_selection_highlight`) always draws regardless of active tool

### Phase 3: Tool Refactoring for Batch
- [x] Extract `_floor_raise_at(r, c)` / `_floor_lower_at(r, c)` from sculpt
- [x] Extract `_toggle_ceiling_at(r, c)` from sculpt
- [x] Extract `_ceiling_lower_at(r, c)` / `_ceiling_raise_at(r, c)` from sculpt
- [x] Extract `_layer2_raise_at(r, c)` / `_layer2_lower_at(r, c)` from layer2
- [x] Wire each tool's click handler to check `_has_selection()` first
- [x] Paint: LMB/RMB batch fill/clear when selection active

### Phase 4: Full Frustum Culling
- [x] Implement frustum plane extraction from VP matrix (`_extract_frustum_planes`)
- [x] Add AABB-vs-frustum test (`_aabb_in_frustum`)
- [x] Replace full W×H iteration with frustum-culled cell set in all draw methods
- [x] Merge 3 segment-boundary passes into single pass over visible cells

### Phase 5: New Batch Operations
- [x] Batch ceiling toggle (T with selection in sculpt)
- [x] Batch wall conversion (H = make wall, Shift+H = make open)
- [x] Batch floor flatten (L with selection — aimed cell height)
- [x] Batch ceiling flatten (Shift+L with selection — aimed cell height)
- [x] Batch layer2 raise/lower (selection-aware)
- [x] Inspector panel: "Apply to Selection" button for cell properties
- [x] `_apply_cell_to_selection`: copy tile, heights, textures, light from aimed cell

### Additional Performance
- [x] P5: Reusable alpha scratch surface (`_alpha_scratch`) in `_filled_box` / `_filled_rotated_box`
- [ ] P6: Long-term — Move projection to C extension

---

## Appendix A: Call Graph (Hot Path)

```
draw()
 ├─ _draw_cell_boxes()          ← O(W×H), HOTTEST
 │   ├─ _cell_boxes(r, c)      ← per cell, called 2x/frame
 │   ├─ sort by distance        ← O(n log n)
 │   ├─ _filled_box() × n      ← 6 faces × projection × polygon fill
 │   └─ _draw_cell_segments()   ← per cell, per face, per segment
 ├─ _draw_surface_markers()     ← O(W×H), 8 lines per cell
 ├─ _draw_seg_boundary_rings()  ← O(W×H×4)
 ├─ _draw_layer2_slabs()        ← O(W×H)
 ├─ _draw_selection_highlight() ← O(selection_area)
 ├─ _draw_entities()            ← O(n_entities)
 ├─ _draw_boxes()               ← O(n_boxes)
 ├─ _draw_quads()               ← O(n_quads)
 ├─ _draw_portals()             ← O(n_portals)
 ├─ _draw_curves()              ← O(n_curves)
 ├─ _draw_face_hl_and_preview() ← O(1)
 ├─ _draw_crosshair()           ← O(1)
 ├─ _draw_action_context()      ← O(1)
 ├─ _draw_hotbar()              ← O(10)
 └─ _draw_hud()                 ← O(1)

update()  [per frame]
 └─ _update_aim()               ← O(search²×parts), 2nd hottest
     ├─ _cell_boxes(r, c)       ← per cell in search window
     └─ _ray_vs_aabb()          ← per part per cell
```

## Appendix B: Mixin Dependency Map

```
Zone3DEditor
 ├─ RenderingMixin     ← reads ALL state, 1733 lines
 ├─ DrawPrimitivesMixin ← stateless projection helpers
 ├─ GeometryMixin      ← _cell_boxes (shared by rendering + picking)
 ├─ SculptMixin        ← reads self.aimed, writes zone heights
 ├─ PaintMixin         ← reads self.aimed, writes zone textures
 ├─ FillMixin          ← flood-fill variant of paint
 ├─ EraseMixin         ← reset single cells
 ├─ SelectMixin        ← rectangle selection + batch ops (ISLAND)
 ├─ SegmentMixin       ← wall segment split/merge
 ├─ StampMixin         ← preset capture/apply
 ├─ EntityMixin        ← entity CRUD
 ├─ BoxMixin           ← freeform box CRUD
 ├─ Layer2Mixin        ← secondary floor/ceil layer
 ├─ QuadMixin          ← flat quad CRUD
 ├─ PortalMixin        ← portal CRUD
 ├─ CurveMixin         ← arc curve CRUD
 ├─ UndoMixin          ← snapshot-based undo/redo
 └─ SaveMixin          ← zone file I/O
```

`SelectMixin` is an **island** — it has its own click dispatch, its own batch iteration, and duplicates patterns from other tools (texture fill ≈ PaintMixin, height scroll ≈ SculptMixin, reset ≈ EraseMixin). The refactor should dissolve SelectMixin's duplicate logic back into the source tools and make selection a shared input layer.
