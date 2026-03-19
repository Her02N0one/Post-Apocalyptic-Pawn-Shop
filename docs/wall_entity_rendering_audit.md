# Wall-Mounted Entity Rendering — Post-Mortem Audit

## The Problem (As Stated)

> "Entities now render properly on raised floors, however they still don't render on walls if applicable when in the 2.5D mode... something like the vent cover probably needs something like side facing textures which are a different size than the face, and just function to kinda make the wall look like it have a vent slightly protruding from the wall. but the way its set up if you look at a wall at 90 degrees, the vent face will also rotate 90 degrees"

In short: wall-mounted billboard entities (vent grates, wall lamps) always rotated to face the camera like any other billboard sprite. Looking at a wall at a 90° angle meant the vent face also turned 90° — physically impossible for something bolted to a wall.

## Why This Was Hard

The difficulty was not any single complex algorithm. It was the **number of parallel rendering paths that all had to agree on a single new concept** — "this billboard is fixed to a wall surface" — while that concept existed nowhere in the original architecture.

Here is an honest accounting of every factor that made this take as long as it did.

---

### 1. Three Completely Independent Rendering Pipelines

The engine has three distinct paths that all render entities:

| Path | Where | Language | Used By |
|------|-------|----------|---------|
| **C raycaster** | `_ray_entities.c` + `ray_renderer.py` | C + Python packer | Editor 2.5D viewport |
| **Python FP renderer** | `fp_entities.py` + `raycaster.py` | Pure Python | In-game first-person mode |
| **3D editor** | `view_3d/` OpenGL | Python/OpenGL | 3D editor viewport |

A fix in one path is invisible to the other two. The C renderer projects entities using an inv_det matrix with `(plane_x, plane_y, dir_x, dir_y)`. The Python FP renderer uses `cos(angle)/sin(angle)` rotation math. The 3D editor uses OpenGL projection. They share no projection code. Every new rendering concept has to be implemented **three separate times** in three separate mathematical frameworks, and tested against each one.

The wall-anchored entity change touched:
- `_ray_entities.c` (~80 lines of new C)
- `ray_renderer.py` (packer wall_face detection)
- `fp_entities.py` (~100 lines of new Python projection)
- `fp_wall_entities.py` (reference for projection math, not modified)
- `raycaster.py` (untouched — it only does camera-facing billboard projection, which is the exact problem)

### 2. The "Billboard" Assumption Was Baked Into Every Layer

The original entity system was designed around a single assumption: **all sprite entities are camera-facing billboards.** This assumption was embedded at every level:

- **`raycaster.py`'s `project_entities()`** returns `BillboardSprite` objects. The entire function computes a single screen-space point and a scale — there's no concept of a flat quad with two projected endpoints. You can't make a billboard "not face the camera" by tweaking parameters. The function's mathematical foundation is wrong for wall-mounted entities.

- **The C renderer's entity loop** computes `dx/dy` from camera to entity, transforms it to a single `(tx, ty)` camera-space point, then draws a camera-centered rectangle. Same fundamental assumption.

- **The entity data tuple** `(eid, x, y, char, color, h_scale, w_scale, elev, bb_mode, bb_key, octant)` has no field for orientation relative to a wall. The packed C buffer (12 doubles per entity) uses `facing_angle` and `n_facings` for multi-facing sprite selection — not for wall alignment.

- **`fp_entities.py`'s `draw_entities`** collects all billboard entities into one list and feeds them all through `project_entities()`, which returns camera-facing projections. There's no branch point to say "these ones should project differently."

You can't transform a billboard into a wall-aligned quad by changing a flag. The entire projection math is different:

| | Billboard | Wall-Anchored |
|---|---|---|
| Screen space | Single center point + symmetric width | Two independently projected endpoints |
| Depth | Uniform across sprite | Varies per-column (perspective-correct `1/z` interpolation) |
| Width on screen | Constant for a given distance | Shrinks to zero when viewed edge-on |
| Texture U | Linear across sprite width | Perspective-correct across wall surface |
| Near-plane clipping | Skip if center behind camera | Must clip individual quad corners |

### 3. No Existing "Wall-Aligned Flat Quad" Primitive

The codebase already has:
- **Billboards** (camera-facing sprites) — `_ray_entities.c`, `fp_entities.py`
- **3D solid boxes** (six-faced prisms) — `fp_wall_entities.py`, `_ray_render.c` box pipeline

But **a 2D quad fixed in world space** — the thing between these two extremes — didn't exist as a rendering primitive. The wall-entity system (`fp_wall_entities.py`) renders 4-face 3D boxes with back-face culling. We needed something much simpler: a single textured face on a wall, but with proper perspective projection.

This meant writing a new renderer from scratch — one that:
1. Computes two world-space quad corners from entity position ± wall tangent × half_width
2. Transforms both corners into camera space
3. Clips to the near plane when one corner goes behind the camera
4. Projects both to screen X
5. Iterates column-by-column with perspective-correct depth interpolation (`1/z` lerp)
6. Samples texture with perspective-correct U coordinates
7. Does per-pixel depth testing against the existing z-buffer
8. Applies fog

And this had to be done **twice** — once in C for the editor viewport, once in Python for the in-game FP mode.

### 4. The Data Pipeline Has No "Wall Orientation" Concept

Getting `wall_face` from the editor to the renderer required threading it through:

1. **Editor placement** (`tools_entity.py`) — already computes `wall_face` and stores it in the zone entity descriptor dict. ✅ already existed.

2. **Zone save/load** — the descriptor dict is serialized to the `.zone` file. `wall_face` is just a string field in the dict, so this works automatically. ✅ no change needed.

3. **ECS spawner** (`spawner.py`) — reads the descriptor dict and creates ECS components. Had to **add propagation** of `wall_face` from the descriptor into the `Sprite` component.

4. **Sprite component** (`components/__init__.py`) — had no `wall_face` field. Had to **add** `wall_face: str = ""`.

5. **C renderer packer** (`ray_renderer.py`) — packs entities into a flat `double[n*12]` buffer for the C extension. Had to **detect** `wall_face` in the entity dict and encode it as `n_facings = -1` + `facing_angle = tangent_angle`.

6. **C renderer** (`_ray_entities.c`) — had to **add** an entire wall-anchored rendering branch before the billboard path.

7. **Python FP entity collector** (`fp_entities.py`) — had to **detect** `sprite.wall_face` and divert those entities into a separate collection list.

8. **Python FP wall renderer** (`fp_entities.py`) — had to **write** `_draw_wall_billboards()` as an entirely new function.

That's **6 files modified** across **4 architectural layers** (editor → data → ECS → renderer). Missing any one link in the chain means the feature silently doesn't work — wall entities just render as regular billboards with no error message.

### 5. The Packed Entity Format Couldn't Be Extended

The C renderer receives entities as a flat `double[n * 12]` buffer:
```
[x, y, r, g, b, h_scale, w_scale, base_tex, facing_angle, n_facings, anim_offset, elevation]
```

Adding a 13th field would require changing:
- The struct stride in `_ray_entities.c`
- Every `ent[ei * 12 + N]` index in C
- The packing loop in `ray_renderer.py`
- The buffer size allocation

Rather than change the ABI, the solution was to **repurpose existing fields**:
- `n_facings = -1` as a flag (normally 1 or 8, never negative)
- `facing_angle` reinterpreted as wall tangent angle (normally the entity's facing direction, unused when `n_facings == 1`)

This was a clever encoding but it required understanding the full lifecycle of both fields across both the Python packer and C consumer before being confident it was safe.

### 6. Two Different Camera-Space Transform Conventions

The C renderer uses the Wolfenstein-style inv_det matrix:
```c
double tx = inv_det * (dir_y * dx - dir_x * dy);
double ty = inv_det * (-plane_y * dx + plane_x * dy);
```
Where `tx` = lateral and `ty` = depth.

The Python FP renderer uses direct rotation:
```python
za = dax * cos_a + day * sin_a       # depth
la = dax * (-sin_a) + day * cos_a    # lateral
```

These are mathematically equivalent but written in different forms with different variable names and conventions. The wall-anchored projection had to be implemented correctly in **both** conventions, and a sign error in either one would cause the entity to render mirrored, inverted, or at the wrong position.

### 7. Depth Testing Works Differently Between Paths

- **C renderer**: Per-pixel depth buffer `float depth_px[sw * sh]`. Wall-anchored entities test `col_depth_biased >= depth_px[cy * sw + cx]` for every pixel.
- **Python FP renderer**: Per-column depth buffer `zbuf[sw]`. Wall-anchored entities test `col_depth * 0.995 >= zbuf[c]` per column, then **write back** `zbuf[c] = col_depth`.

The C renderer's per-pixel depth means wall-anchored entities can be partially occluded by walls at the pixel level. The Python renderer only has per-column depth, so occlusion is coarser. Both need the 0.5% depth bias to prevent z-fighting with the wall surface the entity sits on.

### 8. Texture Resolution Required Two Different Approaches

The C renderer resolves textures at **pack time** through `tile_str_to_int()` — converting a string like `"vent_grate:default_0"` into an atlas integer index, then sampling from a flat `uint8[n * ts * ts * 4]` atlas buffer.

The Python FP renderer can't use atlas indices — it works with `pygame.Surface` objects. Texture resolution happens at **entity collection time** by calling `self._atlas.get_by_key()` with the sprite key. This required looking up the entity's `PrefabRef` component to find its type ID, then constructing the atlas key (`"{sprite_key}:{state}_0"`), then caching the result as a Surface.

Two completely different texture resolution paths, both of which had to be correct.

---

## Previous Sessions — The Prerequisite Fixes

Before the wall-anchored rendering could even be attempted, multiple prerequisite issues had to be fixed first. Each of these was its own investigation and fix:

### Session 1–3: Entity Visibility on Walls
- **Crosshair alignment** — the editor's crosshair wasn't aligning with the raycaster's hit detection, causing wall entities to place at wrong positions
- **Auto-synthesize Sprite** — billboard entities placed on walls were missing the `Sprite` component because the spawner didn't synthesize one for `render_type = "billboard"` entities
- **`wall_height` on Sprite** — the Sprite component had no field for wall-mounted elevation. Entities placed on walls rendered at floor level

### Session 4: Elevation Support
- **Per-entity elevation in C renderer** — the C renderer ignored entity elevation entirely. All entities rendered at floor level regardless of `wall_height`
- **`cam_h` propagation** — `firstperson.py` and `fp_wall_entities.py` didn't pass `cam_h` through the call chain, so elevated entities were positioned wrong

### Session 5: Inset Direction Fix
- **Step-wall inset direction** — entities placed on non-solid walls (step walls) had their inset inverted, placing them inside the wall instead of outside. The fix was in `_wall_snap_from_hit` in `tools_entity.py`
- **Depth bias** — wall-mounted entities z-fought with the wall surface. Added a 0.5% depth bias (`ty * 0.995` or `col_depth * 0.995`) so entities always render slightly in front

### Session 6 (This Session): Wall-Anchored Projection
Only after all of the above were fixed could the actual billboard-rotation problem be addressed. The entity was visible, at the right height, in front of the wall, but it was still a camera-facing billboard that rotated when viewed from the side.

---

## Files Modified (Final Changeset)

| File | Change | Lines |
|------|--------|-------|
| `components/__init__.py` | Added `wall_face: str = ""` to `Sprite` | 1 line |
| `systems/spawner.py` | Propagate `wall_face` from descriptor → Sprite | ~5 lines |
| `engine/ray_renderer.py` | `_WALL_TAN_ANGLE` dict + wall_face detection in packer | ~15 lines |
| `engine/_ray_entities.c` | Full wall-anchored rendering branch | ~80 lines |
| `scenes/world/fp_entities.py` | Wall entity collection + `_draw_wall_billboards()` | ~120 lines |

**Total: ~220 lines of new code across 5 files in 4 architectural layers.**

---

## The Core Insight (What Should Have Been Obvious)

The fix boils down to one idea: **a wall-mounted sprite is not a billboard — it's a textured line segment in world space.**

A billboard is projected from a single point. A wall-mounted entity is projected from two points (the quad corners along the wall tangent). Once you have two projected screen-X values and two depths, everything else — perspective-correct interpolation, texture sampling, depth testing — follows from standard wall-rendering math that already existed in the codebase (`fp_wall_entities.py`).

The reason this wasn't obvious from the start:
1. The entity system was designed with a hard billboard-or-box dichotomy. Wall-mounted billboards fell into neither category.
2. The rendering pipeline's data formats (`BillboardSprite`, the 12-double packed buffer) had no room for orientation metadata without either extending the format or finding a clever encoding.
3. Each prerequisite fix revealed the next problem. You can't debug billboard rotation until the entity is visible, positioned correctly, and not z-fighting.
4. The three rendering pipelines meant each insight had to be translated into different math conventions and tested independently.

The actual algorithm is simple. The architecture made it hard.

---

## Encoding Summary

```
wall_face: "north" | "south" | "east" | "west" | ""

Zone descriptor → Sprite.wall_face (via spawner)
                → ray_renderer: n_facings = -1, facing_angle = tangent_angle
                → _ray_entities.c: if (n_facings < 0) → wall-anchored path
                → fp_entities.py: if sprite.wall_face → wall_ents list → _draw_wall_billboards()

Tangent angles:
  north/south walls run E-W → tangent (1, 0) → angle 0
  east/west walls run N-S   → tangent (0, 1) → angle π/2
```

---

## Architectural Remediation

Based on the post-mortem analysis, four structural problems were identified and addressed:

### Problem 1 → RenderMode Enum (Shared Taxonomy)

**Before:** Three pipelines each invented their own way to distinguish billboard vs wall-anchored.  The C renderer checked `n_facings < 0`, the Python FP renderer checked `if sprite.wall_face`, and the packer set `-1.0` as a magic number.

**After:** `core.types.RenderMode` enum defines the taxonomy once:

```python
class RenderMode(Enum):
    BILLBOARD      =  1   # camera-facing sprite
    BILLBOARD_8WAY =  8   # 8-way directional
    WALL_ANCHORED  = -1   # flat quad fixed to wall
    PRISM          = -2   # 3D box (box_data pipeline)
```

- `Sprite.render_mode` field on the component (authoritative source)
- C header mirrors: `RMODE_BILLBOARD`, `RMODE_BILLBOARD_8WAY`, `RMODE_WALL_ANCHORED`, `RMODE_PRISM`
- Every renderer dispatches on `render_mode`, not ad-hoc string/float checks
- Adding a new mode = add enum value + dispatch entry in each renderer

### Problem 2 → Extension Payload Convention

**Before:** The packed 12-double buffer had no documentation about which fields were mode-specific.  `n_facings = -1` was a clever hack with no discoverable convention.

**After:**
- `ENT_STRIDE = 12` constant replaces all hardcoded `* 12` in C code
- Field 9 is explicitly named `render_mode` (not `n_facings`) everywhere
- Field 8 (`facing_angle`) documented as mode-specific:
  - BILLBOARD/8WAY: entity facing direction (radians)
  - WALL_ANCHORED: wall tangent angle
- Both C header and Python packer carry inline documentation of the convention

### Problem 3 → Open Enum (Not Binary Taxonomy)

**Before:** Entity rendering was a binary choice: billboard (camera-facing) or box (PrismShape).  Wall-mounted entities fell into neither bucket.

**After:** `RenderMode` is an open enumeration. Adding a new projection method means adding a value and implementing dispatch — not rewriting if/else chains.  `PRISM` is already included even though it uses the `box_data` pipeline, so the taxonomy covers all existing render paths.

### Problem 4 → Debug Validation + Pipeline Integration Tests

**Before:** A broken propagation link (spawner fails to set `render_mode`) would silently render wall entities as billboards.  Nothing caught the mismatch.

**After:**
- **Debug asserts** in `fp_entities.py` and `spawner.py` that fire when `wall_face` and `render_mode` disagree (active in `__debug__` mode, stripped by `python -O`)
- **Pipeline integration test** (`tests/test_render_mode_pipeline.py`): 10 tests covering spawn → component → pack for all mode combinations.  The test caught a real bug: directional entities that already had a TOML Sprite weren't getting `BILLBOARD_8WAY` propagated.

### Files Modified

| File | Change |
|------|--------|
| `core/types.py` | Added `RenderMode` enum |
| `components/__init__.py` | Added `render_mode` field to `Sprite` |
| `systems/spawner.py` | Sets `render_mode` during spawn + debug assert |
| `engine/ray_renderer.py` | Packs `RenderMode.value` into field 9 |
| `engine/_ray_render.h` | `ENT_STRIDE`, `RMODE_*` constants |
| `engine/_ray_entities.c` | Dispatch on `render_mode`, `ENT_STRIDE` |
| `scenes/world/fp_entities.py` | Dispatch on `RenderMode.WALL_ANCHORED` + debug assert |
| `tests/test_render_mode_pipeline.py` | 10 integration tests (new file) |

### Updated Encoding Flow

```
Zone descriptor → spawn_from_descriptor()
                → Sprite.render_mode = RenderMode.WALL_ANCHORED (if wall_face)
                → ray_renderer: render_mode = RenderMode.WALL_ANCHORED.value (-1.0)
                                facing_angle = wall tangent angle
                → _ray_entities.c: if (render_mode == RMODE_WALL_ANCHORED) → wall path
                → fp_entities.py:  if sprite.render_mode == RenderMode.WALL_ANCHORED → wall path
```
