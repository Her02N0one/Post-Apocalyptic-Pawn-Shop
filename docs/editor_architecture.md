# Editor Architecture — Analysis & Direction

*Living document. Updated as proposals are implemented or understanding changes. Last revised March 2026.*

## What the Editor Is

The zone editor is a standalone application (separate from the game) that manipulates `.zone` files through two views: a 3D editing view and a 2.5D raycaster preview, toggled with TAB. Zones are the atomic unit of the game world — each one a 2D grid of cells extended into 3D through height fields, face textures, wall segments, and layered collections of discrete objects (entities, boxes, quads, portals, curves, overlay walls).

The fundamental data model is a `Zone` dataclass: nested lists of scalars (heights, tile keys, texture keys) indexed by `[row][col]`, plus flat lists of dicts for discrete objects. Every editing operation mutates this object directly. The editor's job is to make those mutations safe (undo), visible (rendering), and intuitive (tools, keybinds, panels). 

---

## How it's Built — The Mixin Architecture

The editor's two main classes use **mixin composition** as their organizing principle:

**ZoneEditorApp** (the outer shell) composes ~8 mixins handling events, viewport dispatch, panels, dialogs, asset browsers, and entity creation.

**Zone3DEditor** (the inner editing engine) composes ~14 mixins — one for each tool domain: sculpting, painting, filling, selecting, segmenting, stamping, entities, boxes, quads, portals, curves, layers, overlay walls, plus rendering, drawing primitives, undo, and save.

This gives each concern its own file. Adding a new tool means writing a new mixin, dropping it into the inheritance chain, and it gains access to `self.zone`, the undo stack, and the rendering pipeline for free-ish.

### Where this works well

Isolation. A developer working on the sculpt tool never touches the paint tool's code. The file system becomes a natural map of the feature set. Each mixin can be understood in near-isolation because it reads from and writes to the same shared `Zone` object.

### Where this strains

**Discovery.** With 14 mixins and Python's MRO, figuring out where a method is defined requires tooling or memorization. `self._push_undo()` lives in UndoMixin but is called from everywhere. `self._mark_dirty()` could plausibly live in three different mixins. The namespace is flat — every method on every mixin shares the same `self`, which means naming discipline is the only barrier to collision.

**Coupling through `self`.** Each mixin accesses `self.zone`, `self.aimed_cell`, `self.current_tool`, and a dozen other attributes. But none of these are declared in a single place. You have to infer the full interface by reading all mixins. This is the classic diamond problem expressed through convention rather than interface contracts.

**Testing.** Since each mixin expects `self` to be a fully-constructed Zone3DEditor, unit testing a single mixin in isolation requires either mocking the entire class or constructing the full object. Most tests take the latter approach, which makes them slow and brittle.

---

## The Selection System

Selection is a core architectural concern that cuts across every tool. The editor has two selection tracks, managed through a `SelectionStore`:

**Cell selection** operates on `(row, col)` tuples. Click to start a rectangle, click again to finish. Shift+click for Bresenham line selection. Ctrl+click to toggle individual cells. The selection set is a collection of grid coordinates — tool-independent, used by sculpt (bulk raise/lower), paint (bulk texture), and erase (bulk clear).

**Object selection** operates on persistent UIDs. Entities, boxes, quads, portals, curves, and overlay walls all have integer UIDs that survive deletions of unrelated objects — no index fixup needed. A single primary UID determines which object the inspector panel focuses on.

### Where this interacts with tools

Each tool mode reinterprets the selection differently. In sculpt mode, a cell selection means "raise/lower these cells." In paint mode, it means "fill these faces." In entity mode, the selection tracks which entity UID is active for the inspector. This means the selection system is less "select then act" and more "the selection's meaning depends on context." That's not inherently wrong, but it means the selection system and the tool system are tightly coupled — you can't understand what a selection does without knowing which tool is active.

This is also one of the places where the mixin architecture strains hardest. `SelectMixin` owns cell selection logic but every other tool mixin checks and uses that selection state through `self`. There's no formal interface between "selection provider" and "selection consumer."

**Open question for the registry migration:** When tools move to explicit dependency injection, selection becomes one of the injected dependencies — but which direction does it flow? Does a tool receive a read-only selection snapshot (selection drives tool behavior), or does the tool also write selection changes (tool drives selection state)? Currently both directions happen freely through `self`, which hides the question. The registry will force an answer. A read-only snapshot is cleaner but insufficient for tools like entity placement that need to set the active UID. A bidirectional interface (read selection + emit selection-change commands through the bus) would preserve current behavior while making the data flow explicit.

---

## The Input System

The editor has moved from a single `mouse_captured` boolean to a **priority-ordered InputStack**. Contexts are pushed and popped; the topmost context gets first dibs on each event, and can block propagation.

This is a genuine strength. Modal dialogs, viewport capture, and global shortcuts compose cleanly. Adding a new modal interaction (like stamp naming) just means pushing a new context onto the stack.

The **keybind registry** is another strength: every action has a unique ID, a default key, a scope, and an optional condition. Conflict detection is built in. User rebinds persist to JSON. The entire system is introspectable — the keybind editor panel reads from the same data it edits.

### Viewport capture model

The viewport has an explicit engaged/disengaged state. When disengaged, the mouse is visible, ImGui panels are clickable, and the viewport shows a prompt ("Click viewport or Enter to edit"). Clicking or pressing Enter pushes a `CapturedViewportContext` onto the InputStack — the cursor hides, mouse input routes to the 3D camera, and editing begins. Escape pops the context and returns to panel-interaction mode.

This is a smart design for an ImGui-based editor. Without it, mouselook and panel interaction would fight for the mouse. The capture model gives them clean turns. The tradeoff is that every editing session starts with a mode switch — you open the editor, see your zone, and must click or press Enter before you can do anything. For long sessions this is invisible. For quick adjustments ("open, change one texture, save, close") it's one extra step of friction each time.

### Keybind / InputStack gap

The weak spot is that the keybind registry and the InputStack don't fully talk to each other. Contexts make input routing decisions, but tool-specific keybinds are resolved inside the tool mixins themselves. This creates a subtle layering violation: the context system decides *who* gets the event, but the *who* then does its own ad-hoc key matching.

---

## The Panel and UI System

The editor uses **ImGui** (via `imgui` Python bindings) in immediate mode for all panels and dialogs. Every frame, the UI is rebuilt from scratch by polling editor state — no retained widgets, no event subscriptions. Panels read `self.zone`, `self.current_tool`, and `self.aimed_cell` directly.

### What exists

**Menu bar** — File (new, save, save-as, recent zones, quit), Edit (undo, redo, select all, find/replace texture), View (3D/2D toggle, visibility toggles, preview window), Zone (settings, resize, validate, export, duplicate), Data (entity defs, items, loot, presets), Window (texture browser, keybind editor, camera bookmarks, help).

**Left toolbox** — Four mode buttons (ARCH, SURFACE, PROPS, LOGIC), sub-tool selector, snap increment buttons (1/16 to 1 unit), texture/preset/entity palette, selection info.

**Right inspector** — Cell properties (heights, face textures, lighting, segments) or object properties (type, position, rotation, overrides). Sliders and direct numeric input for values.

**Dialogs** — Managed through a `DialogManager` with floating and modal categories. Modal dialogs block input; floating dialogs coexist with editing.

### How panels learn about state changes

They don't. ImGui immediate mode means panels re-read all state every frame. When a tool changes, the toolbox panel simply reads `self.current_tool` next frame and draws different buttons. When a cell is selected, the inspector reads its properties from the zone grid.

This is simple and impossible to desynchronize, which is a real strength. The tradeoff is that panels can't react to changes — they can only reflect current state. There's no "on selection changed" hook for a panel to respond to. This makes it hard to build panels that animate, transition, or show contextual information that depends on what just happened (as opposed to what is).

### The UX ceiling

ImGui provides a functional baseline: panels resize, splitters drag, dropdowns work. But it's not a full design system. There's no custom theming, no layout engine beyond ImGui's built-in column/table/window flow, and no way to make the UI feel like a polished application rather than a debug overlay. For a power-user tool this is adequate. For a tool that needs to be usable by someone unfamiliar with it, ImGui's visual language ("this is a debug UI") works against learnability.

---

## The Command System

The editor is partway through a migration from direct mutation to a command pattern. Phase 0 wraps mutations in immutable `Command` dataclasses dispatched through a `CommandBus`. Before each command executes, a snapshot of the zone is pushed to the undo stack.

**What this buys:** A single point of interception for all mutations. State-change events. A clear audit trail of what happened.

**What's not there yet:** Inverse commands (Phase 1). Currently, undo means restoring a full snapshot, not running the inverse operation. This is memory-proportional to zone size per undo step — fine for small zones, expensive for large ones.

**The real tension:** Not all tools use the command bus yet. Some still call `_push_undo()` directly and mutate the zone inline. This creates two competing patterns in the same codebase, which is fine as a migration strategy but creates confusion about which pattern to follow when writing new code.

**The deeper tension:** The command bus migration and the tool registry migration (section below) interact. If tools move to explicit dependency injection, the command bus becomes one of those injected dependencies — which creates a natural enforcement point where tools *must* go through the bus because it's the only mutation interface they receive. Right now the two-pattern problem persists partly because mixins have unmediated access to `self.zone`. A registry that hands tools a `ZoneAccessor` (read-only view) plus a `CommandBus` (write path) would close that gap structurally rather than by convention. The tool literally cannot mutate the zone without going through commands, because it never receives a mutable reference.

---

## Undo, Redo, and Snapshots

Undo and redo are both implemented, backed by snapshot stacks. Before any mutation, `_push_undo()` captures a type-aware copy of the full zone state using fast shallow copiers (list slices for 2D grids, nested slices for 3D/4D grids, shallow dict copies for object lists). `copy.deepcopy` is avoided for performance.

Ctrl+Z undoes; Ctrl+Y or Ctrl+Shift+Z redoes. The redo stack is cleared whenever a new mutation occurs after an undo, which is standard behavior.

The snapshot approach is simple and correct. It's also O(zone-size) per undo step in both time and memory. For current zone sizes this works. The open question is at what zone size it stops working — a 128×128 zone with dense segments and hundreds of entities would snapshot significantly more data per operation than a sparse 32×32 zone. Phase 1 inverse commands would make this O(mutation-size) instead, but that requires the ZoneModel abstraction (see below) to provide semantic operations that know their own inverses.

---

## The Zone Data Model

The Zone is a thick dataclass with ~25 fields: 2D grids for heights and textures, 3D grids for per-face textures, 4D grids for wall segments, and flat lists for every kind of discrete object. All accessed by `[row][col]` indexing.

### The good

The Zone is the single source of truth. Everything derives from it. The renderer reads it, the tools write it, serialization round-trips it, validation checks it. There's no hidden parallel state.

### The uncomfortable

The dimensionality of the segment grids (`[row][col][face][segment_list]`) creates complexity that compounds through every operation. Copying for undo is a custom recursive process. Serialization is a custom binary format. Migration requires understanding the nesting. Any new segment feature (like segment-level textures or metadata) multiplies the complexity further.

The entity list is a `list[dict]` with no schema enforcement at edit time. An entity missing a `type` key or pointing to a nonexistent definition is only caught on save/load validation (or crashes at render time). There's a gap between the strongly-typed `EntityDef` dataclasses used for definitions and the weakly-typed dicts used for instances.

---

## Serialization and Zone I/O

Zones are stored as binary `.zone` files using a chunked format:

- **Header** (12 bytes): magic number, version, flags, width, height.
- **NAVI chunk**: pathability bitmasks (uint16 per cell).
- **ELEV chunk**: floor and ceiling heights (float32 arrays).
- **RNDR chunk**: face textures and lighting (uint16 + float32 per cell).
- **ENTY chunk**: everything else — entities, portals, overlay walls, all editor grids, segments, metadata — packed as a msgpack blob.

Schema versioning is tracked via `ZONE_SCHEMA_VERSION`. On load, `apply_migrations()` upgrades old formats forward. This works as a linear migration chain, similar to database migrations.

### Where this interacts with proposed changes

The binary format is not self-describing — the reader must know the schema to parse it. This means every structural change to the Zone (new field, changed nesting, typed entities) requires a corresponding migration. If a ZoneModel abstraction is introduced, the serialization layer is one of the first things that needs to adapt — either the model serializes itself (encapsulating the format) or the serializer adapts to the model's interface (separating the concerns). The current design leans toward the latter, but the ENTY chunk's msgpack blob already acts as a catch-all that absorbs structural changes without requiring binary format revisions, which provides some flexibility.

---

## The Asset Pipeline

Assets enter the editor through three paths:

**Tile textures**: PNG files in `assets/textures/tiles/`. The texture manager loads them lazily into an in-memory atlas (one 128×128 surface per tile). Missing PNGs fall back to a solid-color placeholder. The atlas is cached and can be invalidated for hot-reload.

**Entity definitions**: TOML files in `data/entity_defs.toml`. Parsed at startup into frozen `EntityDef` dataclasses. Entity sprite textures are generated (or loaded) into the same atlas by key lookup.

**Tile definitions**: The `TILE_REGISTRY` maps tile keys to `TileDef` objects describing wall/floor/liquid type, default color, texture path. Immutable at runtime.

### What's missing

There's no formal asset validation at load time beyond "does the file exist." An entity referencing a texture key that doesn't map to any atlas entry will silently render as the fallback tile. A TOML definition with a typo in a face name will produce a defaulted texture slot with no warning. The gap between "asset exists on disk" and "asset is correctly wired into the rendering pipeline" is unguarded.

Hot-reload is partial — textures can be invalidated, but entity definitions are frozen at startup. Changing a TOML file requires restarting the editor.

---

## Rendering — Two Views, One Toggle

### The 3D Editing View

The primary editing view renders solid, face-shaded polygons using pygame — not wireframe. Each visible cell is drawn as a box with six filled faces, each face tinted by the tile's color and multiplied by a per-face brightness value (top = 1.0, south = 0.8, east = 0.7, north = 0.65, bottom = 0.55, west = 0.5). Back-face culling hides rear faces. Entities are drawn as solid colored shapes — prisms for prism-type entities, flat rectangles for billboards — with floating text labels for identification. Alpha blending distinguishes ghosts, selections, and normal objects.

This is a genuinely readable spatial editor, not a placeholder wireframe. The per-face brightness differences let you immediately read depth, wall orientation, and room structure — darker west/north faces recede, brighter top/south faces advance. You can distinguish a hallway from a room, a raised platform from a pit, without any textures. Untextured faces render as magenta, which is obvious and useful — you can spot assignment gaps at a glance. Entity labels floating above their colored shapes provide identification without needing to select anything.

There are no textures on faces. The visual information is "where things are and what type they are," not "what things look like." That's a real limitation for texture assignment work, but for geometry editing — which is the majority of the editor's operations — the face-shaded view communicates everything needed.

Draw order: skybox → cell boxes → surface markers → segment boundaries → layer-2 slabs → entities → boxes → quads → portals → curves → overlay walls → selection highlight → face highlight → crosshair → HUD.

### The 2.5D Raycaster Preview

The production C raycaster, used directly. TAB switches to it; the camera position syncs (with a yaw offset for the coordinate convention difference). WASD movement with collision, noclip mode (G), interior/exterior toggle (I). This is the actual game renderer showing the zone as the player would see it — textured, lit, with depth fog and sky.

A standalone preview can also be launched as a subprocess from View → Preview Window, which opens `zone_preview.py` in a separate window.

### The gap — and why it matters

These two views are not two projections of the same renderer. They're two separate rendering pipelines that read the same data. The 3D editor renders everything the Zone data model can express. The raycaster renders the subset that the C renderer implements. Layer 2 geometry, overlay walls, and some discrete object types exist only in the 3D view.

The gap is real but specific. Spatial structure reads identically between views — the same room, the same walls, the same entity positions. What's invisible in the 3D view is aesthetic information: floor materials, wall textures, how a carpet area reads, what a face assignment actually looks like. This isn't a bug. For geometry editing the 3D view provides everything needed. But texture assignment — choosing which face gets which material, checking coverage, spotting gaps — requires seeing the textured result, and the only way to see it is a full context switch via TAB.

The build-check-fix loop for texture work is: paint a face in 3D → TAB to raycaster to see the textured result → TAB back → paint another face → TAB again. For magenta-gap hunting this is especially tedious — you see untextured faces in 3D, switch to check whether they matter in the raycaster view, switch back to paint them, switch again to verify.

### The raycaster inset — a concrete proposal

The 3D view doesn't need to become a textured renderer. It's good at what it does. The real question is whether the C raycaster could run simultaneously in a smaller viewport — a quarter-resolution buffer in a corner of the 3D view, or rendered into an ImGui image panel alongside the inspector. The C raycaster is fast (already hitting 60 FPS at full resolution); rendering to a reduced buffer for a live inset would cost a fraction of a frame.

This would give "edit here, see the textured result there" without the two renderers needing to agree on feature support. The 3D view remains the editing surface. The raycaster becomes a live texture monitor. The camera positions sync continuously (they already sync on TAB toggle), so the inset shows approximately what you're looking at. You paint a face, the inset updates, you see the texture immediately without switching.

Architecturally this is straightforward: the `RayRenderer` already renders to a pygame Surface that gets scaled and blitted. Rendering it at half or quarter resolution into a smaller rect — and doing so every frame alongside the 3D draw — is a matter of calling `renderer.render()` with the synced camera and blitting the result into the corner, or uploading it as an ImGui texture for a floating panel. The main cost is the per-frame raycaster call, which at quarter resolution should be well under a millisecond.

The feature-support gap (objects visible in 3D but absent in the raycaster) becomes less painful with this layout. You'd see both views simultaneously — if something appears in the 3D view but not the inset, the discrepancy is immediately visible rather than discovered after a TAB switch. A "raycaster: not rendered" badge on unsupported objects (nearly free to implement) would make the gap fully explicit.

The inset does not replace the full-screen TAB toggle. They serve different purposes. The inset answers "what does this texture look like?" — a quick visual check during editing, no interaction needed. The full-screen raycaster preview answers "what does this room feel like to walk through?" — collision-based WASD movement, step-up rules, depth fog, the actual game camera. You can't test doorway navigation, sightline pacing, or spatial flow from a quarter-resolution panel in the corner. The inset is a texture monitor; the TAB preview is a playtesting tool. Both remain useful.

### Coordinate Convention Mismatch

The 3D editor uses (X, Y, Z) where Y is vertical. The C raycaster uses (X, Y) where Y is the map's depth axis (south = +Y). This means every boundary between the two systems requires a coordinate swap, and face-direction mappings need a north↔south inversion. This was the root cause of the vending machine face bug: the front face texture ended up 90° off from the arrow direction because the yaw convention between the arrow drawing code and the C renderer's box rotation used incompatible rotation directions.

---

## Visual Feedback During Editing

The editor provides preview feedback for several operations:

**Entity placement**: A translucent ghost shape appears at the cursor position before clicking to confirm. Respects wall-face snapping and layer detection. Shows the directional arrow for rotatable entities.

**Box/prism placement**: Translucent preview box with auto-stacking and grid snap.

**Face highlight**: The aimed cell face glows white-translucent, showing exactly which surface will be affected by the next action.

**Segment split preview**: An orange line shows where the wall will be divided.

**Height preview**: A colored indicator line shows the result of the next raise/lower operation.

**Clipboard paste**: Ghost overlay showing what will be pasted and where, respecting mask flags (heights, textures, entities, segments, lighting can be toggled independently).

### What's not there

No hover preview for paint tools — clicking a texture immediately applies it. No preview for flood fill boundaries. No visualization of what "undo" would restore. No constraint lines or snap guides beyond the grid. The feedback that exists is good; the coverage is uneven. Placement operations get previews; transformation operations mostly don't.

---

## Camera and Navigation

The 3D editing view uses a free-flying 6DOF camera: WASD to move, mouse to look (yaw and pitch), Space/Shift to ascend/descend, Shift for sprint (2.5× speed), Q/E or arrow keys for keyboard turning.

The raycaster preview uses the same WASD/mouse controls but with collision — the camera respects floor heights and step-up rules, so movement feels like the game.

**Camera bookmarks** are supported: Ctrl+Shift+1–9 saves a viewpoint, Shift+1–9 recalls it. Bookmarks persist across sessions.

There's no orbit mode, no orthographic snap, and no top-down view. The camera is always first-person. This matches the game's perspective but makes it harder to get an overview of general level layout or to precisely align things that require a top-down view to reason about.

---

## Bulk Operations and Clipboard

Cell selection supports bulk operations: select a rectangle of cells, then raise/lower all floors, fill with a texture, or clear all geometry. The stamp tool applies preset patterns (small geometry templates) at the cursor position.

**Clipboard**: Ctrl+C copies the aimed cell or selection (heights, textures, segments, lighting, entities). Ctrl+V pastes with interactive positioning. Mask flags control what gets pasted — you can paste only heights, only textures, or any combination. Ctrl+D duplicates selection at an offset.

There's no mirror, no 90° rotate for pasted regions, and no "extrude selection" operation. The building blocks for compound operations exist (selection + clipboard + masks) but the vocabulary of transformations is limited.

---

## Entity Rendering — Three Worlds

Entities exist in three representations:

1. **TOML definition** (`EntityDef`): declares geometry, textures, face mappings, component defaults.
2. **Zone instance** (`dict` in `zone.entities`): position, angle, state, overrides.
3. **Render data** (box_data for C, colored shapes for 3D): transformed geometry ready for display.

The pipeline is: TOML → EntityDef (frozen) → zone dict (mutable) → render data (per-frame).

Each transition is a lossy transform. The EntityDef's face names ("north", "south") must be mapped to C renderer face slots with a coordinate swap. The zone dict's angle must be converted to a yaw that aligns the front face with the entity's facing direction. The render data must match the entity's visual width/depth/height to the texture aspect ratio.

Each of these transforms has been a source of bugs — because the contracts between them are implicit. The TOML says "north = front", the code says "north → BX_TEX_S", and the renderer says "BX_TEX_S is the local -Y face." Whether these compose correctly depends on understanding what "north" means at each layer.

---

## Error Handling and Recovery

The editor does not autosave. All saves are manual (Ctrl+S). A dirty flag tracks unsaved changes; the unsaved guard dialog prompts on quit or zone switch. If the editor crashes mid-session, all unsaved work is lost.

Zone I/O validates magic numbers, version bytes, and chunk lengths on load. Corrupt files raise `ZoneIOError` with a descriptive message. Entity references to deleted definitions are caught by the zone validator (Zone → Validate), which reports all issues but allows continuing.

Transient status messages (`_flash()`) provide feedback for 3 seconds on save, validation, and tool actions. ImGui error dialogs handle validation failures.

Session state — window size, panel widths, recent zones, camera bookmarks — persists on clean exit only. A crash loses session state along with zone data.

### What's missing

No autosave or backup-on-save (writing to `.zone.bak` before overwriting). No crash recovery journal. No undo stack persistence across sessions. These are common in production editors and their absence is felt on any crash. An autosave that writes to a temp file every N minutes or N operations would be a low-effort, high-impact addition.

---

## Performance Characteristics

The 3D editing view does frustum culling per cell, drawing only visible geometry. For small-to-medium zones this is fast enough for interactive frame rates. The C raycaster preview is inherently fast (column-based, C-compiled).

The snapshot undo system is O(zone-size) per step. For current zone sizes this is adequate. The practical ceiling depends on zone dimensions × segment density × entity count. A 128×128 zone with dense 4D segment grids and hundreds of entities would produce large snapshots that could cause visible pauses on each edit operation and consume significant memory over a long editing session.

No profiling data exists in the codebase. The performance ceiling is wherever the first bottleneck appears, and it hasn't been systematically characterized. For a project in active development this is fine — optimize when slow.

But if zones are expected to grow, the two likely bottlenecks are on different timescales and would be profiled and addressed differently:

**Per-operation latency: snapshot undo.** O(zone-size) copying before each edit. The user feels this as a hitch — a brief pause after clicking. It scales with zone dimensions × grid dimensionality, not with what's visible. Mitigation is Phase 1 inverse commands (O(mutation-size) instead of O(zone-size)), which depends on the ZoneModel.

**Per-frame throughput: Python polygon rendering.** O(visible-cells) with per-face `pygame.draw.polygon` calls in Python. The user feels this as low FPS — sluggish camera movement and visual lag. It scales with viewport density (how many cells are in view), not with total zone size. The feasible mitigations are tighter culling (frustum + occlusion) and level-of-detail for distant cells (fewer faces, simplified geometry). These are incremental improvements to the existing renderer.

A more radical option — pushing polygon rendering to a C extension or a GPU path (OpenGL/SDL2) — would remove the Python-call-per-face bottleneck entirely, but it's a significant architectural decision, not a tuning knob. The existing C raycaster is column-based and purpose-built for 2.5D; extending it to also render 3D editor polygons would fight its architecture. A GPU path would mean introducing a third rendering backend alongside the pygame 3D view and the C raycaster, with its own projection, culling, and face-shading logic. Either route is months of work. If the 3D view hits a throughput wall that culling and LOD can't fix, this becomes the conversation — but it's a "redesign the renderer" conversation, not a "tune the renderer" conversation.

Conflating these under "performance" understates the difference. One is an interaction-time spike; the other is a sustained throughput floor. A zone could hit one bottleneck without hitting the other.

---

## The Editor as a User-Facing Tool

The architecture sections above analyze the editor as an engineering system. This section asks: is it pleasant to use?

### What works

The 3D view provides immediate spatial comprehension — face shading communicates depth and orientation without needing textures. Ghost previews for entity and box placement let you see before you commit. The camera controls are fluid. Cell selection with rectangle, line, and toggle modes is flexible. Camera bookmarks eliminate the "where was I" problem. The keybind system is well-designed and introspectable. Undo and redo work.

### What limits it

**The 3D view shows geometry but not aesthetics.** The face shading tells you everything about spatial structure — wall orientation, depth, room shape. But it can't tell you what a face looks like textured. Floor materials, wall textures, how a carpet area reads against surrounding stone — all invisible until you TAB to the raycaster. For geometry work this doesn't matter. For texture assignment it creates a build-check-fix loop: paint, TAB, check, TAB back, adjust, TAB again. A live raycaster inset (see Rendering section) would collapse this loop without requiring the 3D view itself to become a textured renderer.

**The two views diverge on feature support.** Objects placed in the 3D view may not render in the raycaster. The spatial structure matches between views — same walls, same entities, same room shapes. But layer 2 geometry, overlay walls, and some discrete object types exist only in the 3D view, with no indication that they won't appear in the raycaster.

**No top-down overview.** The camera is always first-person. There's no way to see the full zone layout from above, which makes large-scale spatial planning difficult. A minimap, an orthographic toggle, or a 2D overhead mode would help.

**Discoverability depends on prior knowledge.** The toolbox panel shows mode buttons and sub-tool selectors, which helps. But the full set of operations (clipboard masks, segment tools, layer-2 editing, overlay walls) requires knowing the keybinds or finding them in the menus. An editor with this many capabilities needs better progressive disclosure — tooltips, contextual hints, a command palette.

**No preview for destructive operations.** Undo exists, but there's no preview for flood fill, bulk erase, or height changes across a selection. You click and see what happened. If it's wrong, you undo. This is functional but not confidence-inspiring for large operations.

**Asset feedback is binary.** A texture either loads or you get a magenta fallback. There's no indication of why a texture failed (wrong path? wrong size? missing file?). Entity definitions either parse or they don't — there's no partial-load or per-field error reporting.

### The honest framing

The editor is a power-user tool built by and for the developer. It assumes familiarity with its mental model, keybinds, and the object types the raycaster does and doesn't support. For that user it's effective. For anyone else, the learning curve is steep and the feedback is thin. Making it usable by someone who isn't the developer would require: better progressive disclosure (tooltips, a command palette, contextual guidance), visual feedback for more operations (paint preview, fill boundary preview), and either texture display in the 3D view or a reliable side-by-side layout with the raycaster.

---

## What Would a Better Organization Look Like?

The current architecture works. The question is whether it can keep working as complexity grows. Here are the pressure points and possible responses.

### 1. Replace mixin composition with explicit delegation

The mixin approach trades interface contracts for convenience. A tool registry would reverse that trade:

```
editor.tools["sculpt"] = SculptTool(zone_accessor, undo_service, event_bus)
```

Each tool receives explicit dependencies. No `self.zone` global. No 14-deep MRO. Testing a tool means constructing it with mocks. Adding a tool means implementing a `Tool` interface and registering it.

The cost: boilerplate. Every tool needs its dependencies injected. The benefit: each tool's contract is visible in its constructor, not discoverable-only-by-reading-every-mixin.

**Assessment:** Worth doing for new tools. Migrating existing tools can be incremental — the tool registry and the mixin system can coexist during transition (like the command bus migration).

But the coexistence period is itself a feature, not just a compromise. Mixins that are stable and rarely touched — undo, save, rendering primitives — don't benefit from migration. The overhead of extracting them into registry-compatible tools exceeds the return. The tools that are still actively evolving (entities, segments) are where the registry pattern pays for itself in testability and interface clarity. The migration criterion should be "is this tool still generating bugs or design churn?" not "has this tool been migrated yet?"

### 2. Formalize the entity pipeline

The chain from TOML face names → C renderer face slots → visual output crosses three coordinate systems with two implicit swaps. This should be a single, explicit, tested pipeline:

```
TOML face → entity-local face → box-local face (accounting for yaw) → C slot
```

Each step is a named, tested function. The current `_FACE_TO_BX` mapping handles one swap; the yaw correction handles another; but neither knows about the other, and neither is tested as part of a round-trip contract.

**Assessment:** This is the highest-value structural improvement. A `PrismFaceMapper` class (or even a well-structured module) that owns the entire mapping with invariants tested at each stage would have prevented every face-direction bug.

The testing strategy matters here. The right test is not "does `_FACE_TO_BX` return 8 for 'north'" — that's testing a constant. The right test is a round-trip property test: take an arbitrary TOML face assignment and yaw, push it through the full pipeline (TOML → face slot → C renderer local space → visible face direction), and assert that the rendered face matches the expected visual direction. If that test passes for all four cardinal yaws × all six faces, you've covered the space that generated the vending machine bug. The individual mappings are implementation details; the round-trip contract is the invariant.

### 3. Type the entity instances

Zone entities are `list[dict]`. This means no autocomplete, no validation at edit time, and subtle KeyError crashes at render time. A frozen dataclass (or at minimum a TypedDict) for entity instances would catch mismatches at the edit-time boundary instead of at the render-time boundary.

**Assessment:** Low cost, high value. A TypedDict or dataclass doesn't require changing any storage format — just adding a validation layer on insert/update.

### 4. Reconcile the two renderers' feature sets

Rather than trying to make both renderers show everything (which fights their different purposes), accept that they serve different roles and make the boundary between them explicit.

The raycaster inset (described in the Rendering section) addresses the texture-feedback problem without requiring feature parity. The 3D view remains the geometry editor; the raycaster inset provides continuous texture monitoring. For the feature-support gap (objects visible in 3D but absent in the raycaster), a visual badge on unsupported objects (“raycaster: not rendered”) makes the gap explicit rather than invisible.

For future object types, a **feature-support manifest** — a declaration of which object types each renderer can handle — would prevent the current pattern where each new object type requires someone to manually remember to add placeholder rendering in both views. That's a small interface (a dict or enum set), but it matters for every future object type.

### 5. Separate the Zone model from its grid storage

The Zone dataclass is both the conceptual model ("a zone has cells with heights and textures") and the storage layout ("nested Python lists with specific indexing"). These conflate two concerns.

A `ZoneModel` could expose semantic operations (`set_floor_height(row, col, h)`, `get_face_texture(row, col, face)`) while hiding whether the underlying storage is nested lists, numpy arrays, or something else. This would let the undo system, the renderers, and the serialization each optimize independently.

**Assessment:** The segment grid dimensionality (`[row][col][face][segment_list]`) is already constraining two systems: the undo system (which needs custom recursive copy logic because `copy.deepcopy` is too slow) and serialization (which needs a custom binary format because the nesting doesn't map to any standard layout). That's the threshold — two systems writing workarounds for the same structural limitation.

The timing question is whether to introduce the abstraction before or after Phase 1 inverse commands. The answer is before, or at least concurrently. Inverse commands benefit directly from semantic operations: `set_floor_height(row, col, 3.0)` knows its own inverse (restore the previous value); a raw `zone.floor_heights[row][col] = 3.0` does not. Building Phase 1 on top of raw list access would mean reimplementing the same semantic knowledge that a ZoneModel would provide. The abstraction layer and the inverse command system are complementary, not sequential.

**Convergence note:** The `ZoneAccessor` proposed in item 1 (as the read-only view handed to tools) and the `ZoneModel` proposed here are the same interface — the accessor is the model's public API, not a separate layer. If they're built independently they'll converge anyway; better to design them as one from the start.

### 6. Autosave

A background save to a temp file (`.zone.autosave`) every N operations or M minutes. On next launch, detect the autosave and offer recovery. This is the single highest-impact reliability improvement.

---

## Sequencing

The proposals above have dependencies. Here's what gates what:

**Do first: Entity pipeline formalization (#2) and typed entity instances (#3).** These are independent of each other, both low-risk, and both address active bug sources. The entity pipeline test (4 yaws × 6 faces) can be written against the current code as a regression suite before any refactoring.

**Do second: ZoneModel / ZoneAccessor (#5).** This is the foundation that enables both Phase 1 inverse commands (because semantic operations know their inverses) and the tool registry migration (because the accessor is what tools receive instead of a raw zone reference). It also unblocks serialization improvements, since the model can encapsulate format changes.

**Do third: Tool registry for actively-evolving tools (#1).** Once the ZoneModel exists, new tools can be written against the accessor + command bus interface from the start. Migrating existing tools is incremental and prioritized by churn rate.

**Do in parallel, whenever: Feature-support manifest (#4), autosave (#6).** These are independent of the core data model work and can be done at any time.

**UX improvements — two buckets.** The cheap ones — "raycaster: not rendered" badge, paint hover preview, fill boundary visualization — are parallel work with no dependencies. They can land alongside anything. The **raycaster inset** is medium-cost rendering work: it reuses the existing `RayRenderer` at reduced resolution, needs camera sync plumbing (partially exists already from TAB-toggle sync), and either a corner overlay blit or an ImGui image panel. No data model dependency — parallel bucket, but worth doing early because it collapses the texture-assignment build-check-fix loop. The expensive one — texture preview on 3D polygon faces — is real rendering work that *may* interact with the ZoneModel timeline if face texture lookups go through the model's API rather than raw grid access. It doesn't strictly depend on the model, but building it against raw `zone.face_textures[r][c][f]` and then migrating it is wasted motion if the model is coming soon. Sequence it after or concurrently with the ZoneModel. The top-down / orthographic view is independent rendering work with no data model dependency — parallel bucket.

**Not yet: Phase 1 inverse commands.** These depend on the ZoneModel being in place. Attempting them on raw list access would duplicate the semantic knowledge the model provides.

---

## Summary of Judgments

| Area | Current Approach | Verdict |
|------|-----------------|---------|
| Mixin composition | Works, strains at scale | Migrate evolving tools to registry; leave stable ones |
| Selection system | Two-track (cells + UIDs) | Works; needs formal provider/consumer interface |
| InputStack | Clean, composable | Keep; strengthen keybind integration |
| Panel/UI system | ImGui immediate mode, polls state | Functional; UX ceiling is ImGui's ceiling |
| Command bus | Partial migration | Continue; converges with tool registry |
| Zone data model | Single source of truth | Strengthen with typed entities |
| Serialization | Binary chunked + msgpack | Adequate; ZoneModel would encapsulate format changes |
| Dual rendering | Valuable but divergent | Raycaster inset for live texture feedback; badge for unsupported objects |
| Entity face pipeline | Implicit multi-system contract | Formalize and test as a single explicit pipeline |
| Zone model | Raw nested lists | Abstraction layer enables Phase 1; already constraining undo + serialization |
| Undo/redo | Snapshot-based, both work | Adequate until zones get large; Phase 1 mitigates |
| Asset pipeline | Lazy load, frozen definitions | Needs validation at load time; hot-reload is partial |
| Error recovery | Manual save only, no autosave | Autosave is the highest-impact reliability addition |
| Visual feedback | Good for placement; thin for transforms | Extend previews to paint, fill, bulk operations |
| Navigation | 6DOF fly camera, bookmarks | No top-down or orthographic view |

The editor is pragmatic software built for its developer. The architecture favors working now over architected later — the right call for a project in active development. The seams where implicit contracts cross system boundaries (coordinate swaps, face mappings, feature gaps between renderers) are where bugs live. The UX limitations (no texture preview in 3D, no top-down view, thin feedback for non-placement operations) are where workflow friction lives. The sequencing above addresses the structural issues first because they compound — but the UX gaps are what determine whether the editor is a tool you tolerate or a tool you enjoy.
