/*  engine/_ray_render.h  —  Shared constants, structs, and inline helpers
 *                           for the C raycasting renderer.
 *
 *  Included by _ray_render.c, _ray_entities.c, and _ray_debug.c.
 *  All helpers are static inline so each translation unit gets its own
 *  copy — zero overhead, no cross-TU linking required.
 */

#ifndef _RAY_RENDER_H
#define _RAY_RENDER_H

#define PY_SSIZE_T_CLEAN
#include <Python.h>
#define _USE_MATH_DEFINES   /* M_PI on MSVC */
#include <math.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

/* ═══════════════════════════════════════════════════════════════════
 *  Constants
 * ═══════════════════════════════════════════════════════════════════ */

#define MAX_STEPS   64      /* max DDA iterations per ray           */
#define MAX_DEPTH   32.0    /* max render distance (tiles)          */
#define CAM_H_DEFAULT 0.5   /* default camera height (fallback)     */
#define FOG_LUT_LEN 256     /* entries in fog brightness LUT        */
#define FOG_SCALE   8.0     /* distance-to-LUT-index multiplier     */

#define MAX_SHORT_PER_COL 8   /* max short-wall hits per ray        */
#define MAX_DEF_PER_COL   16  /* short + thin + transparent per col  */

/* Height-tier constants for multi-tier floor/ceiling rendering */
#define TIER_TOL       0.05   /* height tolerance for tier matching  */
#define MAX_FLOOR_TIERS 32    /* max unique floor heights            */
#define LAYER_NONE     -1000.0 /* sentinel: no secondary layer       */

/* Portal rendering constants */
#define MAX_PORTAL_DEPTH 2    /* max portal hops per ray             */
#define PRT_DST_X  0          /* portal data: destination X          */
#define PRT_DST_Y  1          /* portal data: destination Y          */
#define PRT_D_ANGX 2          /* portal data: cos(angle_offset)      */
#define PRT_D_ANGY 3          /* portal data: sin(angle_offset)      */
#define PRT_STRIDE 4          /* doubles per portal entry            */

/* Sky gradient colours (exterior zones) */
#define SKY_TOP_R 50
#define SKY_TOP_G 70
#define SKY_TOP_B 160
#define SKY_BOT_R 140
#define SKY_BOT_G 170
#define SKY_BOT_B 220

/* Ground default (visible before floor texture is drawn) */
#define GND_R 25
#define GND_G 25
#define GND_B 22

/* EW wall side-shading tint (warm shadow) */
#define SIDE_R 175
#define SIDE_G 168
#define SIDE_B 155

/* Ceiling heights >= this are treated as open sky (no ceiling) */
#define SKY_THRESHOLD 10.0

/* Face constants (matches core/types.py) */
#define FACE_NORTH 0
#define FACE_SOUTH 1
#define FACE_EAST  2
#define FACE_WEST  3

/* ═══════════════════════════════════════════════════════════════════
 *  Structs
 * ═══════════════════════════════════════════════════════════════════ */

/* Deferred wall hit (short walls, thin walls, transparent walls).
 *
 * Short walls: hs_arr[tid] < 1.0 — ray passes through, drawn shorter.
 * Thin walls:  mid-cell intersection geometry.                         */
typedef struct {
    int    col;        /* screen column                              */
    double dist;       /* perpendicular distance                     */
    int    tid;        /* tile ID for texture lookup                 */
    int    ci;         /* cell index (my * map_w + mx)               */
    int    side;       /* 0=NS face, 1=EW face                      */
    int    face;       /* FACE_NORTH/SOUTH/EAST/WEST                */
    double wall_frac;  /* fractional wall-X for texture U coordinate */
    double hs;         /* height_scale (< 1 for short, 1 for full)  */
    double base_y;     /* Z anchor override; < -1e8 → use cell fh   */
} DeferredHit;

/* qsort comparator: sort deferred hits far-to-near (descending dist) */
static int cmp_deferred_desc(const void *a, const void *b) {
    double da = ((const DeferredHit *)a)->dist;
    double db = ((const DeferredHit *)b)->dist;
    if (da > db) return -1;
    if (da < db) return  1;
    return 0;
}

/* Per-column step-wall hit collected during Phase 1 DDA walk.
 * Eliminates the need for redundant DDA re-traces in Phase 2A/3A. */
typedef struct {
    double perp;       /* boundary perpendicular distance           */
    double wall_frac;  /* texture U coordinate (pre-computed)       */
    double pfh, cfh;   /* previous / current height at transition   */
    int    pci, ci;    /* previous / current cell indices           */
    int    sd;         /* side (0 = X-boundary, 1 = Y-boundary)    */
    int    ssx, ssy;   /* DDA step directions                      */
} StepWallHit;

#define MAX_STEP_HITS 32

/* ═══════════════════════════════════════════════════════════════════
 *  Inline helpers
 * ═══════════════════════════════════════════════════════════════════ */

static inline int clampi(int v, int lo, int hi) {
    return v < lo ? lo : (v > hi ? hi : v);
}

static inline double clampd(double v, double lo, double hi) {
    return v < lo ? lo : (v > hi ? hi : v);
}

static inline int mini(int a, int b) { return a < b ? a : b; }
static inline int maxi(int a, int b) { return a > b ? a : b; }

/* Write one RGB pixel to the framebuffer. */
static inline void put_px(uint8_t *fb, int sw, int x, int y,
                           int r, int g, int b)
{
    int off = (y * sw + x) * 3;
    fb[off]   = (uint8_t)r;
    fb[off+1] = (uint8_t)g;
    fb[off+2] = (uint8_t)b;
}

/* Write per-pixel depth value (float32). */
static inline void put_depth(float *dp, int sw, int x, int y, float d) {
    dp[y * sw + x] = d;
}

/* ═══════════════════════════════════════════════════════════════════
 *  Bump mapping — fake per-pixel normals from texture luminance
 * ═══════════════════════════════════════════════════════════════════ */

/* Apply fake bump lighting to a floor/ceiling pixel.
 * Derives a height-map from texture luminance, computes a pseudo-normal
 * from the gradient, and modulates brightness via dot(N, L).
 * strength: 0 = off, 2–4 = subtle, 8+ = dramatic. */
static inline void apply_bump(
    const uint8_t *atlas, int ts, int tid,
    int u, int v, double strength,
    int *r, int *g, int *b)
{
    int ts_mask = ts - 1;
    int base    = tid * ts * ts;
    /* Sample luminance at (u,v), (u+1,v), (u,v+1) */
    int off0 = (base + v * ts + u) * 4;
    int off1 = (base + v * ts + ((u + 1) & ts_mask)) * 4;
    int off2 = (base + ((v + 1) & ts_mask) * ts + u) * 4;

    double h0 = atlas[off0] * 0.299 + atlas[off0+1] * 0.587 + atlas[off0+2] * 0.114;
    double h1 = atlas[off1] * 0.299 + atlas[off1+1] * 0.587 + atlas[off1+2] * 0.114;
    double h2 = atlas[off2] * 0.299 + atlas[off2+1] * 0.587 + atlas[off2+2] * 0.114;

    double dx = (h1 - h0) * strength / 255.0;
    double dy = (h2 - h0) * strength / 255.0;

    /* Pseudo-normal (-dx, -dy, 1), dot with fixed light from upper-left */
    /* Light dir ≈ (0.408, 0.408, 0.816), pre-normalised */
    double ndotl = -dx * 0.408 + -dy * 0.408 + 0.816;
    double len2  = dx * dx + dy * dy + 1.0;
    ndotl /= sqrt(len2);      /* normalise the pseudo-normal */
    if (ndotl < 0.15) ndotl = 0.15;   /* ambient floor */

    *r = clampi((int)(*r * ndotl), 0, 255);
    *g = clampi((int)(*g * ndotl), 0, 255);
    *b = clampi((int)(*b * ndotl), 0, 255);
}

/* Sample RGBA from a packed texture atlas.
 * atlas layout: [num_tiles × ts × ts × 4] row-major RGBA.                */
static inline void sample_tex(const uint8_t *atlas, int ts, int tid,
                               int u, int v,
                               int *r, int *g, int *b, int *a)
{
    int off = (tid * ts * ts + v * ts + u) * 4;
    *r = atlas[off];
    *g = atlas[off + 1];
    *b = atlas[off + 2];
    *a = atlas[off + 3];
}

/* Alpha-blend (src over dst) a single pixel in the framebuffer.
 * alpha is 0–255; 255 = fully opaque. */
static inline void blend_px(uint8_t *fb, int sw, int x, int y,
                             int sr, int sg, int sb, int alpha)
{
    if (alpha >= 255) {
        put_px(fb, sw, x, y, sr, sg, sb);
        return;
    }
    if (alpha <= 0) return;
    int off = (y * sw + x) * 3;
    int inv = 255 - alpha;
    fb[off]   = (uint8_t)((sr * alpha + fb[off]   * inv) >> 8);
    fb[off+1] = (uint8_t)((sg * alpha + fb[off+1] * inv) >> 8);
    fb[off+2] = (uint8_t)((sb * alpha + fb[off+2] * inv) >> 8);
}

/* Fog brightness from distance (0–255). */
static inline int fog_val(const uint8_t *fog_lut, double dist) {
    int idx = clampi((int)(dist * FOG_SCALE), 0, FOG_LUT_LEN - 1);
    return fog_lut[idx];
}

/* Volume-fog: combine distance fog with accumulated per-cell fog.
 * accum = integral of fog_density along the ray so far.
 * Returns effective fog multiplier (0–255, 255 = clear). */
static inline int fog_vol(const uint8_t *fog_lut, double dist,
                          double accum)
{
    int df = fog_val(fog_lut, dist);           /* distance fog (0-255) */
    if (accum <= 0.0) return df;
    /* Volume contribution: exp(-accum) in [0,1].  1 = clear, 0 = opaque. */
    double vol = exp(-accum);
    if (vol < 0.0) vol = 0.0;
    if (vol > 1.0) vol = 1.0;
    int vf = (int)(vol * 255.0);               /* volume fog (0-255) */
    /* Combine: min of both (darker = more foggy) */
    return df < vf ? df : vf;
}

/* Apply per-cell fog color tint after fog darkening.
 * fog_col: RGB per cell (3 bytes), ci: cell index, accum: accumulated fog.
 * Blends (r,g,b) toward fog_col by (1-exp(-accum)).  Modifies r,g,b in place. */
static inline void fog_color_blend(int *r, int *g, int *b,
                                   const uint8_t *fog_col, int ci,
                                   double accum)
{
    if (!fog_col || accum <= 0.0) return;
    double t = 1.0 - exp(-accum);
    if (t < 0.0) t = 0.0;
    if (t > 1.0) t = 1.0;
    int off = ci * 3;
    *r = (int)(*r * (1.0 - t) + fog_col[off]     * t);
    *g = (int)(*g * (1.0 - t) + fog_col[off + 1] * t);
    *b = (int)(*b * (1.0 - t) + fog_col[off + 2] * t);
}

/* Resolve animated texture ID.
 * anim_lut layout: [num_tiles × 4] int32
 *   per tile: (base_id, n_frames, stride, ticks_per_frame).
 * For static tiles n_frames==1, so the branch exits immediately. */
static inline int resolve_anim_tid(const int32_t *anim_lt, int tid,
                                    int anim_tick, int num_tiles)
{
    if (!anim_lt || tid < 0 || tid >= num_tiles) return tid;
    int off = tid * 4;
    int n_frames = anim_lt[off + 1];
    if (n_frames <= 1) return tid;
    int base_id = anim_lt[off + 0];
    int stride  = anim_lt[off + 2];
    int tpf     = anim_lt[off + 3];
    if (tpf <= 0) tpf = 1;
    int frame = (anim_tick / tpf) % n_frames;
    int etid = base_id + frame * stride;
    if (etid < 0 || etid >= num_tiles) return tid;
    return etid;
}

/* ═══════════════════════════════════════════════════════════════════
 *  Point Light Helpers
 * ═══════════════════════════════════════════════════════════════════ */

/* Maximum lights that can contribute to a single cell */
#define MAX_LIGHTS_PER_CELL 8

/* Per-light data layout (8 doubles): x, y, z, r, g, b, intensity, radius */
#define PL_X    0
#define PL_Y    1
#define PL_Z    2
#define PL_R    3
#define PL_G    4
#define PL_B    5
#define PL_INT  6
#define PL_RAD  7
#define PL_STRIDE 8

/* Spatial index: per-cell array of light indices.
 * cell_lights[ci * MAX_LIGHTS_PER_CELL .. (ci+1) * MAX_LIGHTS_PER_CELL - 1]
 * contains indices into the light array (or -1 for unused slots).
 * n_cell_lights[ci] = count of lights for that cell (0 to MAX_LIGHTS_PER_CELL). */
typedef struct {
    int *cell_lights;       /* int[map_size * MAX_LIGHTS_PER_CELL] */
    int *n_cell_lights;     /* int[map_size] */
} LightGrid;

/* Build the spatial index.  Caller must free cell_lights and n_cell_lights. */
static inline void build_light_grid(
    LightGrid *lg, const double *lights, int n_lights,
    int map_w, int map_h)
{
    int map_size = map_w * map_h;
    lg->cell_lights   = (int *)malloc(map_size * MAX_LIGHTS_PER_CELL * sizeof(int));
    lg->n_cell_lights = (int *)calloc(map_size, sizeof(int));
    if (!lg->cell_lights || !lg->n_cell_lights) return;

    /* Init to -1 */
    memset(lg->cell_lights, 0xff,
           map_size * MAX_LIGHTS_PER_CELL * sizeof(int));

    for (int li = 0; li < n_lights; li++) {
        double lx = lights[li * PL_STRIDE + PL_X];
        double ly = lights[li * PL_STRIDE + PL_Y];
        double lr = lights[li * PL_STRIDE + PL_RAD];

        int c0 = clampi((int)(lx - lr), 0, map_w - 1);
        int c1 = clampi((int)(lx + lr) + 1, 0, map_w - 1);
        int r0 = clampi((int)(ly - lr), 0, map_h - 1);
        int r1 = clampi((int)(ly + lr) + 1, 0, map_h - 1);

        for (int r = r0; r <= r1; r++) {
            for (int c = c0; c <= c1; c++) {
                int ci = r * map_w + c;
                int n = lg->n_cell_lights[ci];
                if (n < MAX_LIGHTS_PER_CELL) {
                    lg->cell_lights[ci * MAX_LIGHTS_PER_CELL + n] = li;
                    lg->n_cell_lights[ci] = n + 1;
                }
            }
        }
    }
}

static inline void free_light_grid(LightGrid *lg) {
    free(lg->cell_lights);
    free(lg->n_cell_lights);
    lg->cell_lights = NULL;
    lg->n_cell_lights = NULL;
}

/* ═══════════════════════════════════════════════════════════════════
 *  Shadow map — per-light 2D visibility bitmap  (forward decl here
 *  so accumulate_lights can reference it)
 * ═══════════════════════════════════════════════════════════════════ */

typedef struct {
    uint8_t *vis;           /* uint8_t[n_lights * map_size]        */
    int      n_lights;
    int      map_size;
} ShadowMap;

/* Accumulate point light contribution at a given world position.
 * Returns additive RGB each in [0.0, 1.0+] range.
 * wx, wy: world XY position of the pixel.
 * wz: world Z (height) of the pixel (for vertical falloff).
 * ci: cell index for spatial lookup.
 * sm: optional shadow map — if non-NULL, occluded lights are skipped. */
static inline void accumulate_lights(
    const double *lights, const LightGrid *lg, int ci,
    double wx, double wy, double wz,
    const ShadowMap *sm,
    double *out_r, double *out_g, double *out_b)
{
    *out_r = 0.0; *out_g = 0.0; *out_b = 0.0;
    if (!lights || !lg->cell_lights || !lg->n_cell_lights) return;

    int n = lg->n_cell_lights[ci];
    for (int i = 0; i < n; i++) {
        int li = lg->cell_lights[ci * MAX_LIGHTS_PER_CELL + i];
        if (li < 0) continue;

        /* Shadow check: skip light if this cell is occluded */
        if (sm && sm->vis && li < sm->n_lights
            && ci >= 0 && ci < sm->map_size
            && !sm->vis[li * sm->map_size + ci])
            continue;

        const double *L = lights + li * PL_STRIDE;

        double dx = wx - L[PL_X];
        double dy = wy - L[PL_Y];
        double dz = wz - L[PL_Z];
        double dist = sqrt(dx * dx + dy * dy + dz * dz);
        double radius = L[PL_RAD];
        if (dist >= radius) continue;

        double atten = (1.0 - dist / radius);
        atten *= atten;  /* quadratic falloff for softer edges */
        double inten = L[PL_INT] * atten;

        *out_r += (L[PL_R] / 255.0) * inten;
        *out_g += (L[PL_G] / 255.0) * inten;
        *out_b += (L[PL_B] / 255.0) * inten;
    }
}

/* Apply point light contributions to an RGB pixel.
 * sector = static light_grid value.
 * lr, lg, lb = accumulated point light RGB from accumulate_lights. */
static inline void apply_lights(int *r, int *g, int *b,
                                double sector,
                                double lr, double lg_v, double lb)
{
    double tr = sector + lr;
    double tg = sector + lg_v;
    double tb = sector + lb;
    *r = clampi((int)(*r * tr), 0, 255);
    *g = clampi((int)(*g * tg), 0, 255);
    *b = clampi((int)(*b * tb), 0, 255);
}

/* ═══════════════════════════════════════════════════════════════════
 *  Dict extraction helpers (for METH_O dict-based APIs)
 * ═══════════════════════════════════════════════════════════════════ */

static int dict_get_double(PyObject *dict, const char *key, double *out) {
    PyObject *o = PyDict_GetItemString(dict, key);
    if (!o) { PyErr_Format(PyExc_KeyError, "missing key: '%s'", key); return -1; }
    *out = PyFloat_AsDouble(o);
    if (*out == -1.0 && PyErr_Occurred()) return -1;
    return 0;
}

static int dict_get_int(PyObject *dict, const char *key, int *out) {
    PyObject *o = PyDict_GetItemString(dict, key);
    if (!o) { PyErr_Format(PyExc_KeyError, "missing key: '%s'", key); return -1; }
    long v = PyLong_AsLong(o);
    if (v == -1 && PyErr_Occurred()) return -1;
    *out = (int)v;
    return 0;
}

static int dict_get_buf(PyObject *dict, const char *key,
                        Py_buffer *buf, int writable) {
    PyObject *o = PyDict_GetItemString(dict, key);
    if (!o) { PyErr_Format(PyExc_KeyError, "missing key: '%s'", key); return -1; }
    if (PyObject_GetBuffer(o, buf, writable ? PyBUF_WRITABLE : 0) < 0)
        return -1;
    return 0;
}

/* Determine which compass face of a wall was hit.
 * side==0 → X-boundary (east/west), side==1 → Y-boundary (north/south).
 * step_x/step_y are the DDA step directions.                            */
static inline int detect_face(int side, int step_x, int step_y) {
    if (side == 0)
        return (step_x > 0) ? FACE_WEST : FACE_EAST;
    else
        return (step_y > 0) ? FACE_NORTH : FACE_SOUTH;
}

/* Resolve per-face texture for a cell.
 * face_tex layout: [map_h * map_w * 4], 4 ints per cell (N,S,E,W).
 * Returns the face-specific tex id, or base_tid if no override (-1). */
static inline int resolve_face_tex(const int32_t *face_tex, int ci,
                                    int face, int base_tid, int num_tiles) {
    int ftid = face_tex[ci * 4 + face];
    if (ftid >= 0 && ftid < num_tiles) return ftid;
    return base_tid;
}

/* ═══════════════════════════════════════════════════════════════════
 *  Decal overlay pass — projected textures on existing surfaces
 * ═══════════════════════════════════════════════════════════════════ */

/* Per-decal layout: 8 doubles */
#define DC_X      0   /* world X centre              */
#define DC_Y      1   /* world Y centre              */
#define DC_Z      2   /* world Z centre (height)     */
#define DC_W      3   /* width  (world units)        */
#define DC_H      4   /* height (world units)        */
#define DC_ANG    5   /* rotation angle (radians)    */
#define DC_TID    6   /* texture ID in atlas         */
#define DC_FLAGS  7   /* surface bits: 1=floor 2=ceil 4=wall */
#define DC_STRIDE 8

#define MAX_DECALS_PER_CELL 8

#define DC_FLOOR   1
#define DC_CEILING 2
#define DC_WALL    4

typedef struct {
    int *cell_decals;       /* int[map_size * MAX_DECALS_PER_CELL] */
    int *n_cell_decals;     /* int[map_size]                       */
} DecalGrid;

static inline void build_decal_grid(
    DecalGrid *dg, const double *decals, int n_decals,
    int map_w, int map_h)
{
    int map_size = map_w * map_h;
    dg->cell_decals   = (int *)malloc(map_size * MAX_DECALS_PER_CELL * sizeof(int));
    dg->n_cell_decals = (int *)calloc(map_size, sizeof(int));
    if (!dg->cell_decals || !dg->n_cell_decals) return;

    memset(dg->cell_decals, 0xff,
           map_size * MAX_DECALS_PER_CELL * sizeof(int));

    for (int di = 0; di < n_decals; di++) {
        const double *D = decals + di * DC_STRIDE;
        double dx = D[DC_X], dy = D[DC_Y];
        double dw = D[DC_W] * 0.5, dh = D[DC_H] * 0.5;
        double a = D[DC_ANG];
        /* Bounding box of rotated rectangle */
        double ca = fabs(cos(a)), sa = fabs(sin(a));
        double bx = dw * ca + dh * sa;
        double by = dw * sa + dh * ca;

        int c0 = clampi((int)(dx - bx), 0, map_w - 1);
        int c1 = clampi((int)(dx + bx) + 1, 0, map_w - 1);
        int r0 = clampi((int)(dy - by), 0, map_h - 1);
        int r1 = clampi((int)(dy + by) + 1, 0, map_h - 1);

        for (int r = r0; r <= r1; r++) {
            for (int c = c0; c <= c1; c++) {
                int ci = r * map_w + c;
                int n = dg->n_cell_decals[ci];
                if (n < MAX_DECALS_PER_CELL) {
                    dg->cell_decals[ci * MAX_DECALS_PER_CELL + n] = di;
                    dg->n_cell_decals[ci] = n + 1;
                }
            }
        }
    }
}

static inline void free_decal_grid(DecalGrid *dg) {
    free(dg->cell_decals);
    free(dg->n_cell_decals);
    dg->cell_decals = NULL;
    dg->n_cell_decals = NULL;
}

/* ═══════════════════════════════════════════════════════════════════
 *  Two-Sided Quad constants (arbitrary-angle line segments)
 * ═══════════════════════════════════════════════════════════════════ */

/* Per-quad data layout (8 doubles) */
#define QD_X1     0   /* endpoint 1 X (world space)             */
#define QD_Y1     1   /* endpoint 1 Y (world space)             */
#define QD_X2     2   /* endpoint 2 X (world space)             */
#define QD_Y2     3   /* endpoint 2 Y (world space)             */
#define QD_HEIGHT 4   /* world-unit height                      */
#define QD_BASE_Y 5   /* Z anchor (bottom of quad)              */
#define QD_TID    6   /* texture ID in atlas                    */
#define QD_FLAGS  7   /* bit 0: collision, bit 1: two_sided     */
#define QD_STRIDE 8

#define QD_FLAG_COLLISION 1
#define QD_FLAG_TWO_SIDED 2

/* ═══════════════════════════════════════════════════════════════════
 *  Shadow map — LOS checking and bitmap construction
 * ═══════════════════════════════════════════════════════════════════ */

/* Shadow map: vis[li * map_size + ci] = 1 if cell ci is visible from
 * light li, 0 if occluded by a solid wall.  Built once per frame
 * via a simple Bresenham/DDA line-of-sight check per cell.           */

/* 2D line-of-sight check: is there an unobstructed straight line
 * from (ax,ay) to (bx,by) on the wall grid?  Uses a simplified DDA.
 * Returns 1 if visible (no solid wall between), 0 if blocked.
 * Skips the destination cell itself — we check the path, not the
 * endpoint (wall faces can be lit from the open side).              */
static inline int los_check(
    const uint8_t *cell_solid, int map_w, int map_h,
    double ax, double ay, double bx, double by)
{
    double dx = bx - ax, dy = by - ay;
    double dist = sqrt(dx * dx + dy * dy);
    if (dist < 0.01) return 1;  /* same point */

    /* March in small steps (0.3 tile) from A toward B.
     * Stop 0.5 units before B so we don't test B's own cell. */
    double inv = 1.0 / dist;
    double step = 0.3;
    double check_dist = dist - 0.5;
    if (check_dist < 0.0) return 1;  /* too close, always visible */
    int n_steps = (int)(check_dist / step) + 1;
    double sx = dx * inv * step;
    double sy = dy * inv * step;
    double cx = ax, cy = ay;

    for (int i = 0; i < n_steps; i++) {
        cx += sx;  cy += sy;
        int gx = (int)floor(cx);
        int gy = (int)floor(cy);
        if (gx < 0 || gx >= map_w || gy < 0 || gy >= map_h)
            return 0;  /* out of bounds → blocked */
        if (cell_solid[gy * map_w + gx])
            return 0;  /* hit a solid wall */
    }
    return 1;
}

/* Build shadow maps for all lights.  Caller must free vis. */
static inline void build_shadow_maps(
    ShadowMap *sm, const double *lights, int n_lights,
    const uint8_t *cell_solid, int map_w, int map_h)
{
    int map_size = map_w * map_h;
    sm->n_lights = n_lights;
    sm->map_size = map_size;
    sm->vis = NULL;
    if (n_lights <= 0 || !lights) return;

    sm->vis = (uint8_t *)calloc(n_lights * map_size, 1);
    if (!sm->vis) return;

    for (int li = 0; li < n_lights; li++) {
        double lx = lights[li * PL_STRIDE + PL_X];
        double ly = lights[li * PL_STRIDE + PL_Y];
        double lr = lights[li * PL_STRIDE + PL_RAD];

        /* Only check cells within the light's radius */
        int c0 = clampi((int)(lx - lr), 0, map_w - 1);
        int c1 = clampi((int)(lx + lr) + 1, 0, map_w - 1);
        int r0 = clampi((int)(ly - lr), 0, map_h - 1);
        int r1 = clampi((int)(ly + lr) + 1, 0, map_h - 1);

        uint8_t *base = sm->vis + li * map_size;
        for (int r = r0; r <= r1; r++) {
            for (int c = c0; c <= c1; c++) {
                int ci = r * map_w + c;
                double cx = c + 0.5, cy = r + 0.5;
                base[ci] = (uint8_t)los_check(cell_solid, map_w, map_h,
                                               lx, ly, cx, cy);
            }
        }
    }
}

static inline void free_shadow_maps(ShadowMap *sm) {
    free(sm->vis);
    sm->vis = NULL;
}

/* ═══════════════════════════════════════════════════════════════════
 *  Freeform Box constants — OBB ray-slab intersection
 * ═══════════════════════════════════════════════════════════════════ */

/* Per-box data layout: 14 doubles */
#define BX_X       0    /* world X centre                            */
#define BX_Y       1    /* world Y centre                            */
#define BX_Z       2    /* world Z bottom (base)                     */
#define BX_W       3    /* size along local X (width)                */
#define BX_H       4    /* size along Z (height)                     */
#define BX_D       5    /* size along local Y (depth)                */
#define BX_YAW     6    /* rotation angle (radians)                  */
#define BX_TEX_N   7    /* texture: local north (+Y) face            */
#define BX_TEX_S   8    /* texture: local south (-Y) face            */
#define BX_TEX_E   9    /* texture: local east  (+X) face            */
#define BX_TEX_W  10    /* texture: local west  (-X) face            */
#define BX_TEX_T  11    /* texture: top face                         */
#define BX_TEX_B  12    /* texture: bottom face                      */
#define BX_FLAGS  13    /* bit 0: collision                          */
#define BX_STRIDE 14

#define BX_FLAG_COLLISION 1

#define MAX_BOXES_PER_CELL 8

typedef struct {
    int *cell_boxes;        /* int[map_size * MAX_BOXES_PER_CELL] */
    int *n_cell_boxes;      /* int[map_size]                      */
} BoxGrid;

/* Build spatial index for freeform boxes. */
static inline void build_box_grid(
    BoxGrid *bg, const double *boxes, int n_boxes,
    int map_w, int map_h)
{
    int map_size = map_w * map_h;
    bg->cell_boxes   = (int *)malloc(map_size * MAX_BOXES_PER_CELL * sizeof(int));
    bg->n_cell_boxes = (int *)calloc(map_size, sizeof(int));
    if (!bg->cell_boxes || !bg->n_cell_boxes) return;
    memset(bg->cell_boxes, 0xff,
           map_size * MAX_BOXES_PER_CELL * sizeof(int));

    for (int bi = 0; bi < n_boxes; bi++) {
        const double *B = boxes + bi * BX_STRIDE;
        double bx = B[BX_X], by = B[BX_Y];
        double hw = B[BX_W] * 0.5, hd = B[BX_D] * 0.5;
        double ca = fabs(cos(B[BX_YAW])), sa = fabs(sin(B[BX_YAW]));
        /* AABB of the rotated box */
        double ex = hw * ca + hd * sa;
        double ey = hw * sa + hd * ca;

        int c0 = clampi((int)(bx - ex), 0, map_w - 1);
        int c1 = clampi((int)(bx + ex) + 1, 0, map_w - 1);
        int r0 = clampi((int)(by - ey), 0, map_h - 1);
        int r1 = clampi((int)(by + ey) + 1, 0, map_h - 1);

        for (int r = r0; r <= r1; r++) {
            for (int c = c0; c <= c1; c++) {
                int ci = r * map_w + c;
                int n = bg->n_cell_boxes[ci];
                if (n < MAX_BOXES_PER_CELL) {
                    bg->cell_boxes[ci * MAX_BOXES_PER_CELL + n] = bi;
                    bg->n_cell_boxes[ci] = n + 1;
                }
            }
        }
    }
}

static inline void free_box_grid(BoxGrid *bg) {
    free(bg->cell_boxes);
    free(bg->n_cell_boxes);
    bg->cell_boxes = NULL;
    bg->n_cell_boxes = NULL;
}

/* Apply floor/ceiling decals at a world XY position.
 * Rotates into decal-local UV, samples the decal texture, alpha-blends. */
static inline void apply_decals(
    const double *decals, const DecalGrid *dg, int ci,
    double wx, double wy, double wz,
    int surface_mask,
    const uint8_t *atlas, int ts, int num_tiles,
    int *r, int *g, int *b)
{
    if (!decals || !dg->cell_decals || !dg->n_cell_decals) return;
    int ts_mask = ts - 1;

    int nd = dg->n_cell_decals[ci];
    for (int i = 0; i < nd; i++) {
        int di = dg->cell_decals[ci * MAX_DECALS_PER_CELL + i];
        if (di < 0) continue;
        const double *D = decals + di * DC_STRIDE;

        int flags = (int)D[DC_FLAGS];
        if (!(flags & surface_mask)) continue;

        double lx = wx - D[DC_X];
        double ly = wy - D[DC_Y];
        double ca = cos(D[DC_ANG]), sa = sin(D[DC_ANG]);
        double u = lx * ca + ly * sa;
        double v;

        double hw = D[DC_W] * 0.5, hh = D[DC_H] * 0.5;
        if (hw < 1e-6 || hh < 1e-6) continue;

        if (surface_mask & DC_WALL) {
            /* Wall decal: u = XY distance, v = height offset */
            if (u < -hw || u > hw) continue;
            v = wz - D[DC_Z];
            if (v < -hh || v > hh) continue;
        } else {
            /* Floor/ceiling: full XY rotation */
            v = -lx * sa + ly * ca;
            if (u < -hw || u > hw || v < -hh || v > hh) continue;
        }

        int tid = (int)D[DC_TID];
        if (tid < 0 || tid >= num_tiles) continue;

        int tu = (int)((u / D[DC_W] + 0.5) * ts) & ts_mask;
        int tv = (int)((v / D[DC_H] + 0.5) * ts) & ts_mask;

        int dr, dg_v, db, da;
        sample_tex(atlas, ts, tid, tu, tv, &dr, &dg_v, &db, &da);
        if (da <= 0) continue;

        if (da >= 255) {
            *r = dr; *g = dg_v; *b = db;
        } else {
            int inv = 255 - da;
            *r = clampi((*r * inv + dr * da) >> 8, 0, 255);
            *g = clampi((*g * inv + dg_v * da) >> 8, 0, 255);
            *b = clampi((*b * inv + db * da) >> 8, 0, 255);
        }
    }
}

/* ═══════════════════════════════════════════════════════════════════
 *  Curved wall (arc) constants — ray-circle intersection on arcs
 * ═══════════════════════════════════════════════════════════════════ */

/* Per-curve data layout: 9 doubles */
#define CRV_CX       0    /* arc centre X (world)                    */
#define CRV_CY       1    /* arc centre Y (world)                    */
#define CRV_R        2    /* arc radius                              */
#define CRV_A0       3    /* arc start angle (radians, 0 = +X)       */
#define CRV_A1       4    /* arc end angle   (radians)               */
#define CRV_HS       5    /* height scale (wall height multiplier)   */
#define CRV_BASE     6    /* base_y  (vertical offset)               */
#define CRV_TID      7    /* texture atlas id                        */
#define CRV_FLAGS    8    /* bit 0: transparent                      */
#define CRV_STRIDE   9

/* ═══════════════════════════════════════════════════════════════════
 *  Forward declarations for functions defined in companion .c files.
 *  These are needed by the module method table in _ray_render.c.
 * ═══════════════════════════════════════════════════════════════════ */

PyObject *py_render_entities(PyObject *self, PyObject *dict);
PyObject *py_render_particles(PyObject *self, PyObject *dict);
PyObject *py_depth_to_grayscale(PyObject *self, PyObject *args);
PyObject *py_ssao_pass(PyObject *self, PyObject *dict);

#endif /* _RAY_RENDER_H */
