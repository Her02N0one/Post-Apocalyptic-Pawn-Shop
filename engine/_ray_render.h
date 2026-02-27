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
 *  Forward declarations for functions defined in companion .c files.
 *  These are needed by the module method table in _ray_render.c.
 * ═══════════════════════════════════════════════════════════════════ */

PyObject *py_render_entities(PyObject *self, PyObject *dict);
PyObject *py_depth_to_grayscale(PyObject *self, PyObject *args);

#endif /* _RAY_RENDER_H */
