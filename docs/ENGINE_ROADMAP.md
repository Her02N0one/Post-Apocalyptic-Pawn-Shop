# Engine & Editor Roadmap

> Living document — 25 features spanning rendering, editor tooling, and
> architecture.  Organised into phases by dependency and risk.

---

## Phase 1 — Transparency & Two-Sided Quads

### 1. RGBA Atlas + Alpha Compositing

**What:** The texture atlas is currently RGB (3 bytes per texel).  Add a
fourth alpha channel so textures can contain transparent regions — glass
panes, chain-link fences, grate floors, foliage cutouts.

**C impact:** `sample_tex` grows from 3-byte to 4-byte reads.  Every
`put_px` call on a transparent surface must blend:

```
dst = src * alpha + dst * (1 - alpha)
```

instead of overwriting.  This touches wall columns, floor sweeps, ceiling
sweeps, and entity billboards.  A fast path (`alpha == 255 → overwrite`)
keeps opaque geometry at current speed.

**Data:** `atlas` buffer changes from `uint8[num_tiles * ts * ts * 3]` to
`uint8[num_tiles * ts * ts * 4]`.  Python-side `textures.py` must pack the
extra channel from PNG source images.

---

### 2. Ray-Continues-After-Hit for Transparent Walls

**What:** The DDA loop (`PHASE 1`) currently breaks on the first solid
wall.  For glass, fences, and other see-through materials the ray must
**continue through** transparent cells, collect all hits into the deferred
list, and composite them back-to-front per column.

**C impact:** The `trans_lt` buffer already exists and is used for short
walls, but full-height transparent walls still trigger `hit = 1; break`.
Add a check: if `trans_lt[tid]` is set, push the hit onto the deferred
list (like short walls) and keep marching.  After the DDA finishes, sort
all deferred hits far-to-near and draw them with alpha blending.

**Edge cases:**
- Multiple transparent walls stacking (3+ layers) — cap at
  `MAX_DEF_PER_COL` (currently 12, may need bumping).
- Transparent wall + floor/ceiling behind it: the floor/ceiling sweep
  already runs after walls, so it composites naturally.

---

### 3. Two-Sided Quad Intersection (Thin Decals & Fences)

**What:** A new geometry type: arbitrary-angle line segments within cells.
Not axis-aligned like thin walls — free rotation for fences, barricades,
window shutters, hanging tarps.

**Data model (per quad):**
```
{
    cell:       (row, col),
    pos:        (x_offset, z_offset),   // within-cell float
    angle:      float,                  // radians
    height:     float,                  // world units
    base_y:     float,                  // bottom of quad
    texture:    int,                    // atlas tile ID
    collision:  bool,
    two_sided:  bool
}
```

**C impact:** New buffer `quad_data` passed to `render_frame`.  During the
DDA walk, when a ray enters a cell flagged as containing quads, test each
quad as a 2D line-segment intersection.  Push hits onto the deferred list
with proper distance, texture UV (derived from intersection point along the
segment), and face direction.

**Editor impact:** New "Quad" placement tool — click a floor surface to
anchor, drag to set angle and width.  Renders as a thin filled polygon pair
in the 3D editor.

---

## Phase 2 — Entity Billboards

### 4. Complete Per-Pixel Depth Buffer Writes

**What:** `depth_px[sw * sh]` exists but floors and ceilings only write
depth in the step-wall paths.  Every rendered floor pixel, ceiling pixel,
and deferred-wall pixel must write its depth.

**Why:** Foundational for correct sprite clipping, quad clipping, and
future post-processing effects (DOF, SSAO).

**C impact:** Add `put_depth(depth_px, sw, x, y, dist)` to the floor sweep
(Phase 2) and ceiling sweep (Phase 3) inner loops — currently missing from
the standard flat-floor path.

---

### 5. Multi-Facing Sprite Support in `render_entities`

**What:** Currently each entity has one `tex_id`.  Radial billboards need
the renderer to select from N textures based on the angle between camera
direction and entity facing direction.

**Sprite tiers:**

| Tier | Examples | Facing logic | Data per entity |
|------|----------|-------------|-----------------|
| Static billboard | Tree, rock, signpost | Always faces camera (1 tex) | `pos, tex_id, scale` |
| Radial billboard | NPC idle, barrel | 5 or 8 textures | `pos, base_tex, n_facings, facing_angle, scale` |
| Functional prop | Light, TV, keypad | Fixed orientation + interact | `pos, angle, tex_id, on_interact_id` |
| Actor | Enemy, NPC | Radial + animation states | `pos, angle, state, anim_frame, base_tex, n_facings` |

**C impact:** Extend `ent_data` from 8 doubles to 12:
```
[x, y, r, g, b, h_scale, w_scale, base_tex, facing_angle, n_facings, anim_offset, flags]
```

Compute: `relative_angle = atan2(ey - cam_y, ex - cam_x) - facing_angle`,
normalise to `[0, 2π)`, then `tex_id = base_tex + anim_offset + (int)(relative_angle / (2*PI) * n_facings)`.

---

### 6. Static Billboard Entity Placement in Editor

**What:** Entities need a world-space position (not grid-locked), rendered
as camera-facing quads in the 3D editor view.  

**Editor tool:** Click on any floor surface → entity spawns at that exact
world point.  Drag to rotate.  Scroll to cycle entity prefab.

**Panel:** Entity palette (like the texture palette but for prefabs).
Each prefab shows its billboard texture, name, and tier.

**Integration:** The editor writes spawn points into the zone data.  The
game session instantiates them with full ECS components via `spawner.py`.

---

## Phase 3 — Lighting

### 7. Point Light Accumulation Buffer

**What:** The current `light_grid` is per-cell (Doom-style sector
lighting).  Point lights need per-pixel contributions.

**Data:** Light array passed to `render_frame`:
```
[x, y, intensity, r, g, b, radius]   // per light
```

**C impact:** During floor/ceiling sweeps, for each pixel's world
coordinate, sum contributions from nearby lights:
```
contribution = intensity * max(0, 1 - dist/radius)
```

Use a spatial grid (hash by cell) so each pixel only tests lights whose
radius overlaps the current cell.  Accumulate into a per-pixel brightness
multiplier, then apply after texture sampling.

---

### 8. Shadow Casting from Lights

**What:** After computing light contributions, determine visibility between
each lit pixel and its light sources.

**Approach (efficient):** For each light, pre-compute a 2D **visibility
bitmap** — which cells are visible from the light (simplified 2D
raycasting from the light position against the wall grid).  During the
floor sweep, look up the bitmap for each contributing light.  If the
current cell is shadowed, zero out that light's contribution.

**Cost:** One 2D ray-march per light per frame (or cache and invalidate
only when geometry changes).  The per-pixel lookup is a single bit test.

---

## Phase 4 — Freeform Geometry

### 9. Freeform Box Ray Intersection

**What:** Sub-grid rotatable boxes — furniture, crates, counters, shelves
that aren't confined to the tile grid.

**Data model:**
```
{
    pos:        (x, y, z),      // world-space float
    size:       (w, h, d),      // dimensions
    yaw:        float,          // Y-axis rotation only
    textures:   {top, bot, N, S, E, W},
    collision:  bool,
    anchored:   "floor" | "ceiling"
}
```

**Constraint:** Boxes snap to floor or ceiling and stack on each other —
no floating geometry.

**C impact:** After the DDA walk, test each ray against nearby OBBs
(oriented bounding boxes) using ray-slab intersection with a 2D rotation
transform.  Collect hits into the deferred list.

**Performance:** Spatial hashing by cell — each ray only tests boxes whose
AABB overlaps cells along its path.

---

### 10. Box Placement & Rotation Tool in Editor

**What:** 3D editor tool for placing, sizing, and rotating freeform boxes.

**Interaction:**
- Click floor/ceiling surface to place.
- Drag handles to resize.
- R + mouse to rotate (yaw only).
- Scroll while holding Shift to stack on top of existing boxes.
- Per-face texture painting (reuse the existing paint tool logic).

**Rendering:** `_filled_rotated_box` primitive — applies a yaw rotation
matrix before projection.

---

## Phase 5 — Architecture & Performance

### 11. Argument Struct Refactor

**What:** `py_render_frame` currently takes **40+ positional arguments**
through `PyArg_ParseTuple` — one of the longest format strings in any
Python C extension.  This is brittle, impossible to extend, and already at
practical limits.

**Solution:** Define a `RenderContext` struct:
```c
typedef struct {
    double cam_x, cam_y, cam_angle, cam_fov, cam_h;
    int    horizon_shift, sw, sh, map_w, map_h;
    int    tex_size, num_tiles, is_interior;
    // ... pointers to all buffers
} RenderContext;
```

Python packs this into a single `bytearray` or passes a dict that the C
side unpacks with `PyDict_GetItemString`.  Adding new parameters becomes a
one-line struct field + one-line dict lookup instead of modifying the 40+
item format string.

---

### 12. Threaded Column Rendering

**What:** Each column's DDA walk and floor/ceiling sweep is independent.
Split columns across N worker threads.

**Implementation:** `#pragma omp parallel for` (OpenMP) on the main column
loop, or manual pthreads with column ranges.  The framebuffer and depth
buffer have no cross-column dependencies.

**Expected gain:** 3–4× on modern 4+ core machines.  Essential as per-pixel
lighting, quad intersections, and box tests increase per-column cost.

**Caveat:** The deferred hit array becomes per-thread.  Sort + draw each
thread's deferred hits independently (they don't overlap in screen space).

---

## Phase 6 — Visual Quality

### 13. Skybox / Environment Map Rendering

**What:** Replace the hardcoded linear gradient in `fill_background` with a
cylindrical panoramic texture.  For each pixel above the horizon not
covered by ceiling, compute the view angle and sample from a wide texture
strip.

**UV mapping:**
- U = `(cam_angle + column_angle) / (2 * PI)` — wraps horizontally.
- V = `(pixel_y - horizon) / sky_height` — vertical position.

**Data:** One additional texture (or a range of atlas tiles concatenated
into a panorama strip).  Zone metadata specifies which skybox to use.

**Use cases:** Ruined cityscapes, mushroom clouds, night skies, indoor
ceilings with painted murals.

---

### 14. Animated Texture Support (Texture Ticking)

**What:** Every texture is currently static.  Add a frame-offset mechanism.

**Data:** `tex_anim` LUT per tile:
```
(base_id, n_frames, frame_stride, ticks_per_frame)
```

Python passes a global `anim_tick` integer that increments each game tick.

**C impact:** In `sample_tex`, resolve:
```c
int frame = (anim_tick / ticks_per_frame) % n_frames;
int effective_tid = base_id + frame * frame_stride;
```

**Use cases:** Flickering monitors, flowing water, pulsing warning lights,
burning fires, conveyor belts.  No per-pixel branching beyond one LUT
lookup.

---

### 15. Floor/Ceiling Bump Mapping (Fake Normal via Offset Sampling)

**What:** Flat floors look flat.  Fake bump lighting by sampling a
grayscale height-map and computing a pseudo-normal.

**Technique:** Store a second "bump" atlas (grayscale, same layout).
Sample at `(u, v)`, `(u+1, v)`, and `(u, v+1)`.  Compute gradient:
```
dx = bump(u+1, v) - bump(u, v)
dy = bump(u, v+1) - bump(u, v)
brightness = dot(normalize(-dx, -dy, 1), light_dir)
```

Modulate the base texture color by this brightness.  ~6 extra texture
reads per floor pixel; gate behind a quality setting.

**Use cases:** Concrete cracks, tile grout, dirt road ruts, wooden plank
grain.

---

### 16. Mirrored / Reflective Surfaces

**What:** Puddles, polished floors, glass.  After the primary render, for
floor pixels marked as reflective, cast a second upward ray through the
wall DDA to get reflected wall color.

**Data:** Per-cell `reflect_flag` + `reflect_opacity` in a new LUT.

**C impact:** After floor sweep, iterate reflective cells.  For each
pixel, invert the pitch to get reflected camera angle, re-run a simplified
DDA (walls only, no recursion), sample the hit wall texture, blend:
```
final = floor_color * (1 - opacity) + reflected_color * opacity
```

**Cost:** Doubles ray count for reflective cells.  Mitigate by limiting
reflective cells and using half-resolution sampling.

---

### 17. Decal Overlay Pass (Projected Textures)

**What:** Blood splatters, cracks, footprints, graffiti — non-grid-aligned
detail on existing surfaces.

**Data (per decal):**
```
(world_x, world_y, world_z, width, height, angle, tex_id, surface_type)
```

**C impact:** During floor/ceiling sweeps, check if the current world
position falls within any nearby decal's bounding box (spatial hash
lookup).  Transform into decal-local UV, sample the decal texture, alpha-
blend over the existing pixel.  Wall decals work the same during wall
column rendering.

**Use cases:** Environmental storytelling — bloodstains, blast marks,
painted arrows, warning signs, tire tracks.

---

### 18. Curved / Cylindrical Wall Segments

**What:** Arc-shaped walls defined by `(center_x, center_y, radius,
angle_start, angle_end, height, texture)`.

**C impact:** During DDA walk, when a ray enters a cell flagged as
containing a curve, solve ray-circle intersection analytically:
```
t = (-b ± sqrt(b² - 4ac)) / 2a
```
Clamp to the arc's angular range.  Render the wall column at the
intersection distance with UV derived from the arc angle.

**Use cases:** Pillars, rounded corners, tunnel entrances, silos, curved
barricades.  Currently these require stairstepping dozens of wall tiles.

---

### 19. Per-Column Vertical FOV / Lens Distortion

**What:** A per-column vertical scale modifier `v_scale[x]` that stretches
or compresses wall height for that column.

**Applications:**
- **Weapon scope zoom:** center columns get `v_scale > 1`, edges get
  `v_scale < 1`.
- **Security camera fisheye:** barrel distortion LUT.
- **Drunk/poison effect:** sinusoidal wobble over time.
- **Underwater refraction:** slight sine offset per column.

**C impact:** One extra multiply per column projection during wall, floor,
and ceiling rendering.  The LUT is computed Python-side and passed as a
`double[sw]` buffer.

---

### 20. Multi-Layer Floor/Ceiling (Catwalks, Bridges, Pits)

**What:** Each cell currently has exactly one floor height and one ceiling
height.  For multi-story structures — catwalks over pits, bridges over
rivers, mezzanines — support N floor/ceiling pairs per cell.

**Data model:**
```
floor_layers[cell] = [
    (fh0, ch0, ftex0, ctex0),
    (fh1, ch1, ftex1, ctex1),
    ...
]
```

**C impact:**
- Floor/ceiling sweeps iterate layers bottom-to-top.  For each screen row,
  determine which layer the cast point falls between and sample that
  layer's texture.
- Wall DDA renders wall columns for each layer boundary (a step-wall
  between layer 0's ceiling and layer 1's floor).
- Camera height determines which layer the player is "in" for clipping.

**Architectural significance:** This is the single biggest structural
change possible.  It transforms the engine from single-story Wolfenstein
into multi-story Build/Duke3D territory.

---

## Phase 7 — Additional Features

### 21. Particle System (C-side Billboard Batch)

**What:** Dust, sparks, smoke, rain, shell casings, blood mist.  Hundreds
of tiny billboards that spawn, move, fade, and die each frame.

**Data:** Particle buffer:
```
[x, y, z, vx, vy, vz, life, max_life, r, g, b, size, tex_id, flags]
```

**C impact:** New `render_particles` function called after
`render_entities`.  Tick all particles (apply velocity, gravity, lifetime
decay), depth-sort, then render as small textured quads clipped against
`depth_px`.  Particles below a size threshold render as single coloured
dots (no texture sample).

**Why C, not Python:** Hundreds of particles at 60fps requires tight inner
loops.  Python overhead per particle would kill framerate.

---

### 22. Fog Volumes (Per-Cell Fog Density & Color)

**What:** Currently fog is global — one exponential curve via `fog_lut`.
Add per-cell fog density and color so you can have thick smoke in one room,
coloured gas in a hallway, and clear air outside.

**Data:** `fog_density[map_h * map_w]` (double, 0.0 = clear, 1.0 =
opaque) and `fog_color[map_h * map_w * 3]` (RGB per cell).

**C impact:** During the DDA walk, accumulate fog as the ray passes
through cells:
```c
accumulated_fog += fog_density[ci] * step_length;
```
At the hit point, blend the wall/floor color toward the accumulated fog
color by `1 - exp(-accumulated_fog)`.  This replaces the single global
`fog_val()` call with a per-cell integral.

**Use cases:** Smoke-filled rooms, toxic green gas, misty swamps, dust
clouds after explosions.

---

### 23. Slope / Ramp Floors

**What:** Floors currently step between discrete heights — there's no
continuous slope.  Add per-cell slope data:
```
slope_dir:    (dx, dz) — normalised direction of slope
slope_delta:  float    — height change across the cell
```

**C impact:** During floor sweeps, instead of testing
`floor_y == constant` per cell, interpolate:
```c
double local_fh = fh + slope_delta * dot(frac_pos, slope_dir);
```
This changes the screen-row-to-world-y mapping from piecewise-constant to
piecewise-linear per cell.  Wall step rendering at cell boundaries needs to
account for the sloped edge heights.

**Use cases:** Ramps, hillsides, drainage ditches, wheelchair-accessible
post-apocalyptic architecture.

---

### 24. Screen-Space Ambient Occlusion (SSAO) Post-Pass

**What:** After the full render, darken pixels in concave regions (corners,
wall bases, under overhangs) using the depth buffer.

**Algorithm:** For each pixel, sample `depth_px` at N random offsets in a
small radius.  If neighboring samples are closer to the camera (i.e., the
surface curves inward), darken the pixel.  Classic SSAO hemisphere
sampling:
```c
for (int i = 0; i < N_SAMPLES; i++) {
    float sample_depth = depth_px[offset_y * sw + offset_x];
    if (sample_depth < center_depth - bias)
        occlusion += 1.0;
}
brightness *= 1.0 - (occlusion / N_SAMPLES) * strength;
```

**Cost:** O(sw × sh × N_SAMPLES).  At N=8 and 640×480 this is ~2.5M
depth reads per frame — fast enough with the depth buffer already in cache.
Gate behind a quality flag.

---

### 25. Portal Rendering (Non-Euclidean Geometry)

**What:** When a ray hits a portal surface, instead of drawing a wall
texture, **teleport** the ray to the portal's destination and continue
casting in the target zone.  This enables impossible architecture: doors
that lead to rooms larger than the building, hallways that loop, and
windows that look into different zones.

**Data (per portal):**
```
{
    cell:       (row, col),
    face:       int,                // which wall face is the portal
    dest_zone:  zone_id,
    dest_cell:  (row, col),
    dest_face:  int,
    transform:  (dx, dy, angle)     // coordinate remap
}
```

**C impact:** During the DDA walk, when a ray hits a portal cell face:
1. Save current ray state (position, direction, remaining depth budget).
2. Transform ray origin/direction into the destination zone's coordinate
   space.
3. Load the destination zone's tile/height/texture buffers (passed as
   additional pointer arrays).
4. Continue DDA in the new space.
5. Cap recursion depth (e.g., max 2 portal transitions per ray).

**Performance:** Each portal transition roughly doubles the per-ray cost.
With a max depth of 2, worst case is 3× cost — acceptable if portals are
rare.  Spatial culling: only test portal cells when the ray actually enters
them.

**Use cases:** Doorways into zone interiors, shop entrances that open into
larger rooms, horror hallways, "bigger on the inside" buildings.

---

## Implementation Priority

```
 #  Feature                             Depends on   Risk    Effort
─── ─────────────────────────────────── ──────────── ─────── ──────
11  Argument struct refactor  ✅       —            Low     Medium
 4  Complete depth buffer writes  ✅    —            Low     Small
 1  RGBA atlas + alpha compositing  ✅  —            Low     Medium
 2  Continue-through transparent walls ✅ 1            Medium  Medium
 3  Two-sided quad intersection         1, 2         Medium  Large
 5  Multi-facing sprites  ✅            4            Low     Medium
 6  Entity placement in editor          5            Low     Medium
14  Animated textures                   —            Low     Small
13  Skybox                              —            Low     Medium
 7  Point light accumulation            4            Medium  Large
 8  Shadow casting                      7            High    Large
22  Fog volumes                         —            Low     Medium
12  Threaded column rendering           11           Medium  Medium
15  Bump mapping                        7            Medium  Medium
17  Decal overlay pass                  1, 4         Medium  Large
 9  Freeform box ray intersection       11, 4        High    Large
10  Box placement editor tool           9            Medium  Large
21  Particle system                     1, 4         Medium  Medium
16  Reflective surfaces                 4            High    Large
23  Slope / ramp floors                 —            High    Large
18  Curved walls                        —            High    Large
19  Lens distortion                     —            Low     Small
24  SSAO post-pass                      4            Medium  Medium
20  Multi-layer floor/ceiling           11           High    X-Large
25  Portal rendering                    11, 20       High    X-Large
```

Features are numbered in the order introduced, not priority.  The
"Depends on" column tracks hard prerequisites.  Start from the top of the
priority table and work down.
