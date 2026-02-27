# Zone Editor — Tool Taxonomy

## Fundamental Properties (the "forces")

Every cell in the zone grid has exactly **4 fundamental property categories**:

| # | Property | Type | What it controls |
|---|----------|------|------------------|
| 1 | **Geometry** | `floor_height`, `ceil_height` | Shape — where solid mass exists in 3D space |
| 2 | **Solidity** | `tile_id` (wall vs open) | Whether geometry blocks rays/movement entirely |
| 3 | **Surface** | `*_textures`, `*_step_textures` | What each visible face looks like |
| 4 | **Segments** | `*_segments`, `*_step_segments` | How a single face is subdivided vertically |

Everything the editor does is a mutation of one or more of these four categories.

---

## Fundamental Mutations (atomic operations)

There are exactly **7 atomic mutations** from which all tools are composed:

| # | Mutation | Target Property | Description |
|---|----------|----------------|-------------|
| 1 | `set_floor(r,c, height)` | `floor_heights` | Move floor surface to absolute Y |
| 2 | `set_ceil(r,c, height)` | `ceil_heights` | Move ceiling surface to absolute Y |
| 3 | `set_tile(r,c, tile_id)` | `tiles` | Change tile type (wall ↔ open) |
| 4 | `set_texture(r,c, face, tex)` | `*_textures` | Paint one face with a texture |
| 5 | `clear_texture(r,c, face)` | `*_textures` | Reset face to default texture |
| 6 | `split_segment(r,c, face, y)` | `*_segments` | Add a horizontal divider |
| 7 | `merge_segment(r,c, face, y)` | `*_segments` | Remove nearest horizontal divider |

The `face` parameter in mutations 4–7 is context-aware: it routes to wall faces, floor-step faces, ceil-step faces, floor-top, or ceil-bottom based on what surface the user is pointing at.

---

## Tool Layer (user-facing)

Tools combine fundamental mutations into intent-driven actions with clear visual feedback.

### Tool 1: **Sculpt** (F5)

**Intent**: Shape the 3D geometry of a cell.

All three old tools (Wall, Floor, Ceiling) manipulated the same two properties (`floor_height`, `ceil_height`). They were split across 3 tools with 2 modes, creating confusion. Unified into one tool with two **targets** (Floor / Ceiling) and clear mouse actions:

| Action | Target = Floor | Target = Ceiling |
|--------|---------------|-----------------|
| **LMB** | Raise floor by snap | Lower ceiling by snap |
| **RMB** | Lower floor by snap | Raise ceiling by snap |
| **Scroll** | Change snap increment | Change snap increment |
| **Shift+LMB** | Set floor to exact height (wall_height) | Set ceiling to exact height |
| **C** | Toggle target (Floor ↔ Ceiling) | Toggle target |
| **R** | Reset to default (0.0 / 1.0) | Reset to default |
| **MMB** | Paint aimed face | Paint aimed face |

The old "Wall tool" Floor Up / Ceil Down modes become **Shift+LMB** — "stamp to height" rather than a separate tool. When floor meets ceiling the cell becomes geometry-solid automatically.

### Tool 2: **Paint** (F6)

**Intent**: Change what a surface looks like without changing geometry.

| Action | What it does |
|--------|-------------|
| **LMB** | Apply current texture to aimed face |
| **RMB** | Erase texture override (revert to default) |
| **Ctrl+LMB** | Flood fill current texture across connected cells |
| **Ctrl+RMB** | Flood clear texture across connected cells |
| **MMB** | Eyedropper — pick texture from aimed face |
| **Scroll** | Cycle texture palette (syncs hotbar slot) |
| **Shift+LMB** | Paint all faces of aimed cell at once |

Context-aware face routing: wall N/S/E/W, floor-step N/S/E/W, ceil-step N/S/E/W, floor-top, ceil-bottom — all via the same tool, determined by what the crosshair hits.

### Tool 3: **Segment** (F7)

**Intent**: Subdivide a face vertically for multi-texture bands.

| Action | What it does |
|--------|-------------|
| **LMB** | Split face at crosshair Y |
| **RMB** | Merge nearest split boundary |
| **MMB** | Paint the specific segment band |
| **Scroll** | Cycle texture palette |

### Utility Mode: **Select** (B toggle)

**Intent**: Rectangle-select cells for batch operations.

| Action | What it does |
|--------|-------------|
| **LMB** | Set selection start / end corner |
| **RMB** | Clear selection |
| **Delete** | Batch delete selected cells |
| **X** | Toggle floor / ceiling mode |

### Utility Mode: **Stamp** (P toggle)

**Intent**: Place / capture preset structures.

Pressing B or P again returns to the previously active core tool.

---

## Compound Operations (convenience shortcuts)

These are multi-cell or multi-mutation actions that combine fundamentals for common workflows:

| Shortcut | What it does | Mutations used |
|----------|-------------|----------------|
| **Shift+LMB (Floor target)** | Stamp floor to `wall_height` | `set_floor` + conditionally `set_ceil` |
| **Shift+LMB (Ceiling target)** | Stamp ceiling down by `wall_height` | `set_ceil` |
| **Delete / Backspace** | Full cell reset: flat ground, open sky, clear textures | `set_floor(0)` + `set_ceil(1)` + `set_tile(open)` + `clear_texture(all)` |
| **U / Shift+U / Ctrl+U** | Adjust upper wall height override | `set_uwh` |
| **Ctrl+LMB drag** *(future)* | Line / rect fill with current action | repeated `set_floor`/`set_ceil` |
| **Ctrl+Shift+LMB** *(future)* | Flood fill to same height | pathfinding + `set_floor`/`set_ceil` |

---

## Before → After

| Old | New | Why |
|-----|-----|-----|
| 7 tools (Sculpt, Paint, Fill, Erase, Segment, Select, Stamp) | 3 core + 2 utility (Sculpt, Paint, Segment + Select, Stamp) | Fill/Erase absorbed into Paint + globals; Select/Stamp are modes |
| Number keys 1–7 select tools | F5/F6/F7 for core tools, B/P toggle utility modes | Frees 1–0 for hotbar texture slots |
| Wall tool has floor_up / ceil_down modes | Sculpt tool has Floor / Ceiling targets | Direct manipulation — "which surface am I moving?" |
| Wall tool `height` parameter (1–10 tiles) | Shift+LMB = stamp to height | Height is a parameter of the stamp action, not a mode |
| Separate Fill tool | Ctrl+LMB/RMB in Paint tool | Fill is a modifier of paint, not a separate tool |
| Separate Erase tool | Del = cell reset, R = height reset, RMB on paint = texture clear | Erase variants folded into globals and Paint |
| T = ceiling toggle | C = ceiling toggle | T freed for future tile picker; C freed from fly-down |
| F2/F3/F4 = display toggles | F8/F9/F10 = display toggles | F-keys near tool range freed |
| No hotbar | 10-slot texture hotbar (keys 1–0) | Quick texture access like Minecraft |
| Tab not used | Tab cycles core tools | Keyboard-only tool switching |

---

## Key Bindings (New)

| Key | Action |
|-----|--------|
| `F5` | Sculpt tool |
| `F6` | Paint tool |
| `F7` | Segment tool |
| `Tab` | Cycle core tools (Sculpt → Paint → Segment) |
| `B` | Toggle Select utility mode |
| `P` | Toggle Stamp utility mode |
| `1`–`0` | Select hotbar texture slot (1=slot0 … 0=slot9) |
| `C` | Toggle sculpt target (Floor ↔ Ceiling) |
| `R` | Reset height (global — works in any tool) |
| `G` | Cycle snap height |
| `U` / `Shift+U` / `Ctrl+U` | Upper wall height adjust |
| `Scroll` | Tool-specific (snap cycle / texture cycle) |
| `LMB` | Primary action |
| `RMB` | Secondary action (inverse of primary) |
| `Ctrl+LMB` | Flood fill (paint tool) |
| `Ctrl+RMB` | Flood clear (paint tool) |
| `Shift+LMB` | Stamp to height (sculpt) / Paint all faces (paint) |
| `MMB` | Paint / eyedropper / segment-paint |
| `Delete` | Full cell reset |
| `F8/F9/F10` | Toggle grid / ceiling grid / axes display |
