/*  systems/_ray_render.c  —  Full-frame C raycasting renderer.
 *
 *  Renders textured walls, floors, and ceilings in a single C call,
 *  writing directly into a pre-allocated framebuffer.
 *
 *  Features:
 *    • DDA wall raycasting with per-pixel texture mapping
 *    • Short walls (height_scale < 1.0), anchored at floor level
 *    • Thin walls (mid-cell intersection)
 *    • Tall walls (extend upward with alt-texture)
 *    • Row-sweep textured floor casting with platform tops
 *    • Row-sweep textured ceiling casting (interior) or sky gradient
 *    • Per-tile floor/ceiling height support
 *    • Per-tile spatial lighting (Doom-style sector lighting)
 *    • Distance-based fog with exponential falloff
 *    • Directional wall shading (EW faces darker)
 *    • Checkerboard floor tint for visual tile separation
 *    • AO shadows at wall bases
 *    • Entity billboard rendering with z-buffer clipping
 *
 *  Compile:  python build_ext.py build_ext --inplace
 *  Import :  from systems._ray_render import render_frame, render_entities
 */

#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

/* ═══════════════════════════════════════════════════════════════════
 *  Constants
 * ═══════════════════════════════════════════════════════════════════ */

#define MAX_STEPS   64      /* max DDA iterations per ray           */
#define MAX_DEPTH   32.0    /* max render distance (tiles)          */
#define CAM_H       0.5     /* camera height (0=floor, 1=ceiling)   */
#define FOG_LUT_LEN 256     /* entries in fog brightness LUT        */
#define FOG_SCALE   8.0     /* distance-to-LUT-index multiplier     */

#define MAX_SHORT_PER_COL 8   /* max short-wall hits per ray        */
#define MAX_DEF_PER_COL   12  /* short walls + thin walls per col   */

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
 *  Deferred wall hit (short walls, thin walls)
 *
 *  Short walls: hs_arr[tid] < 1.0 — ray passes through, drawn shorter.
 *  Thin walls:  mid-cell intersection geometry.
 * ═══════════════════════════════════════════════════════════════════ */

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

/* Sample RGB from a packed texture atlas.
 * atlas layout: [num_tiles × ts × ts × 3] row-major RGB.                 */
static inline void sample_tex(const uint8_t *atlas, int ts, int tid,
                               int u, int v,
                               int *r, int *g, int *b)
{
    int off = (tid * ts * ts + v * ts + u) * 3;
    *r = atlas[off];
    *g = atlas[off + 1];
    *b = atlas[off + 2];
}

/* Fog brightness from distance (0–255). */
static inline int fog_val(const uint8_t *fog_lut, double dist) {
    int idx = clampi((int)(dist * FOG_SCALE), 0, FOG_LUT_LEN - 1);
    return fog_lut[idx];
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
 *  Background fill
 * ═══════════════════════════════════════════════════════════════════ */

static void fill_background(uint8_t *fb, int sw, int sh, int half,
                             int is_interior)
{
    /* Top half: sky gradient (exterior) or dark ceiling (interior) */
    for (int y = 0; y < half; y++) {
        double t = (double)y / (double)half;
        int r, g, b;
        if (is_interior) {
            r = (int)(20 + 15 * t);
            g = (int)(22 + 15 * t);
            b = (int)(25 + 18 * t);
        } else {
            r = SKY_TOP_R + (int)((SKY_BOT_R - SKY_TOP_R) * t);
            g = SKY_TOP_G + (int)((SKY_BOT_G - SKY_TOP_G) * t);
            b = SKY_TOP_B + (int)((SKY_BOT_B - SKY_TOP_B) * t);
        }
        for (int x = 0; x < sw; x++)
            put_px(fb, sw, x, y, r, g, b);
    }
    /* Bottom half: dark ground default */
    for (int y = half; y < sh; y++)
        for (int x = 0; x < sw; x++)
            put_px(fb, sw, x, y, GND_R, GND_G, GND_B);
}

/* ═══════════════════════════════════════════════════════════════════
 *  Main render function
 * ═══════════════════════════════════════════════════════════════════
 *
 * Arguments (positional):
 *
 *   fb          : writable buffer  uint8[sw * sh * 3]  —  output
 *   cam_x       : double           — camera X (tile coords)
 *   cam_y       : double           — camera Y (tile coords)
 *   cam_angle   : double           — look direction (radians)
 *   cam_fov     : double           — horizontal FOV (radians)
 *   sw, sh      : int              — framebuffer pixel size
 *   map_w       : int              — map width in tiles
 *   map_h       : int              — map height in tiles
 *   tiles       : buffer int32     — flat tile grid [map_h * map_w]
 *   wall_lut    : buffer uint8     — [num_tiles] 1=wall (blocks rays)
 *   atlas       : buffer uint8     — [num_tiles * ts * ts * 3] RGB
 *   tex_size    : int              — texture side length (e.g. 64)
 *   num_tiles   : int              — number of tiles in atlas
 *   fog_lut     : buffer uint8     — [256] dist→brightness
 *   floor_h     : buffer double    — [map_h * map_w] floor heights
 *   ceil_h      : buffer double    — [map_h * map_w] ceiling heights
 *   floor_tex   : buffer int32     — [map_h * map_w] tex override (-1=tile)
 *   ceil_tex    : buffer int32     — [map_h * map_w] tex override (-1=tile)
 *   is_interior : int              — 1=render ceiling, 0=sky
 *   thin_lut    : buffer uint8     — [num_tiles] 1=thin wall
 *   tall_lut    : buffer uint8     — [num_tiles] 1=tall wall
 *   hs_lut      : buffer double    — [num_tiles] height_scale per tile
 *                                    (< 1.0 = short wall, deferred)
 *   face_tex    : buffer int32     — [map_h*map_w*4] per-face tex override
 *   zbuf_out    : writable buffer  double[sw]  — depth output
 *   light_buf   : buffer double    — [map_h*map_w] per-cell light (0–∞)
 *   alt_tex_buf : buffer int32     — [num_tiles] alt tex for tall extension
 *
 * Returns None.  The framebuffer and zbuf are modified in-place.
 */
static PyObject *
py_render_frame(PyObject *self, PyObject *args)
{
    /* ── Parse arguments ─────────────────────────────────────────── */
    double cam_x, cam_y, cam_angle, cam_fov;
    int sw, sh, map_w, map_h;
    int tex_size, num_tiles;
    int is_interior;

    Py_buffer fb_buf    = {0};
    Py_buffer tiles_buf = {0};
    Py_buffer wall_buf  = {0};
    Py_buffer atlas_buf = {0};
    Py_buffer fog_buf   = {0};
    Py_buffer fh_buf    = {0};
    Py_buffer ch_buf    = {0};
    Py_buffer ft_buf    = {0};
    Py_buffer ct_buf    = {0};
    Py_buffer thin_buf  = {0};
    Py_buffer tall_buf  = {0};
    Py_buffer hs_buf    = {0};
    Py_buffer ftex_grid_buf = {0};
    Py_buffer zbuf_buf  = {0};
    Py_buffer light_buf = {0};
    Py_buffer alt_tex_buf = {0};
    Py_buffer depth_px_buf = {0};
    Py_buffer trans_buf = {0};
    Py_buffer overlay_buf = {0};
    int n_overlay = 0;

    PyObject *result = NULL;

    /* Heap allocations (need cleanup) */
    int         *w_top    = NULL;
    int         *w_bot    = NULL;
    double      *w_dist   = NULL;
    DeferredHit *deferred = NULL;

    if (!PyArg_ParseTuple(args,
            "y*"        /* fb           */
            "dddd"      /* cam_x .. fov */
            "ii"        /* sw, sh       */
            "ii"        /* map_w, map_h */
            "y*y*y*"    /* tiles, walls, atlas */
            "ii"        /* tex_size, num_tiles */
            "y*"        /* fog_lut      */
            "y*y*"      /* floor_h, ceil_h */
            "y*y*"      /* floor_tex, ceil_tex */
            "i"         /* is_interior  */
            "y*y*"      /* thin, tall   */
            "y*"        /* hs_lut       */
            "y*"        /* face_tex_grid */
            "y*"        /* zbuf_out     */
            "y*"        /* light_buf    */
            "y*"        /* alt_tex_buf  */
            "y*"        /* depth_px_buf */
            "y*"        /* trans_lut    */
            "y*"        /* overlay_buf  */
            "i",        /* n_overlay    */
            &fb_buf,
            &cam_x, &cam_y, &cam_angle, &cam_fov,
            &sw, &sh,
            &map_w, &map_h,
            &tiles_buf, &wall_buf, &atlas_buf,
            &tex_size, &num_tiles,
            &fog_buf,
            &fh_buf, &ch_buf,
            &ft_buf, &ct_buf,
            &is_interior,
            &thin_buf, &tall_buf,
            &hs_buf,
            &ftex_grid_buf,
            &zbuf_buf,
            &light_buf,
            &alt_tex_buf,
            &depth_px_buf,
            &trans_buf,
            &overlay_buf,
            &n_overlay))
        goto cleanup;

    /* ── Validate buffers ────────────────────────────────────────── */
    if (fb_buf.readonly || zbuf_buf.readonly || depth_px_buf.readonly) {
        PyErr_SetString(PyExc_TypeError,
            "framebuffer, zbuf, and depth_px must be writable (pass bytearrays)");
        goto cleanup;
    }
    if (fb_buf.len < (Py_ssize_t)(sw * sh * 3)) {
        PyErr_SetString(PyExc_ValueError, "framebuffer too small");
        goto cleanup;
    }
    if (zbuf_buf.len < (Py_ssize_t)(sw * (int)sizeof(double))) {
        PyErr_SetString(PyExc_ValueError, "zbuf too small");
        goto cleanup;
    }
    if (depth_px_buf.len < (Py_ssize_t)(sw * sh * (int)sizeof(float))) {
        PyErr_SetString(PyExc_ValueError, "depth_px buffer too small");
        goto cleanup;
    }
    if (sw <= 0 || sh <= 0 || map_w <= 0 || map_h <= 0 || tex_size <= 0) {
        PyErr_SetString(PyExc_ValueError, "dimensions must be positive");
        goto cleanup;
    }

    {
    /* ── Pointer aliases ─────────────────────────────────────────── */
    uint8_t       *fb       = (uint8_t *)      fb_buf.buf;
    const int32_t *tiles    = (const int32_t *)tiles_buf.buf;
    const uint8_t *wall_lt  = (const uint8_t *)wall_buf.buf;
    const uint8_t *atlas    = (const uint8_t *)atlas_buf.buf;
    const uint8_t *fog_lt   = (const uint8_t *)fog_buf.buf;
    const double  *fheight  = (const double *) fh_buf.buf;
    const double  *cheight  = (const double *) ch_buf.buf;
    const int32_t *ftex     = (const int32_t *)ft_buf.buf;
    const int32_t *ctex     = (const int32_t *)ct_buf.buf;
    const uint8_t *thin_lt  = (const uint8_t *)thin_buf.buf;
    const uint8_t *tall_lt  = (const uint8_t *)tall_buf.buf;
    const double  *hs_arr   = (const double *) hs_buf.buf;
    const int32_t *face_tex = (const int32_t *)ftex_grid_buf.buf;
    double        *zbuf_out = (double *)       zbuf_buf.buf;
    const double  *light_grid = (const double *) light_buf.buf;
    const int32_t *alt_tex_lt = (const int32_t *)alt_tex_buf.buf;
    float         *depth_px  = (float *)       depth_px_buf.buf;
    const uint8_t *trans_lt   = (const uint8_t *)trans_buf.buf;
    const double  *ov_data    = (const double *) overlay_buf.buf;

    const int half     = sh / 2;
    const int ts       = tex_size;
    const int ts_mask  = ts - 1;           /* assumes power-of-2  */
    const int map_size = map_h * map_w;
    const int lut_len  = num_tiles;

    /* ── Camera vectors ──────────────────────────────────────────── */
    const double dir_x   = cos(cam_angle);
    const double dir_y   = sin(cam_angle);
    const double tan_hf  = tan(cam_fov * 0.5);
    const double plane_x = -dir_y * tan_hf;
    const double plane_y =  dir_x * tan_hf;

    /* Edge ray directions for floor/ceiling sweep */
    const double ray0_x = dir_x - plane_x;
    const double ray0_y = dir_y - plane_y;
    const double ray1_x = dir_x + plane_x;
    const double ray1_y = dir_y + plane_y;

    /* ── Allocate per-column + deferred buffers ──────────────────── */
    int max_deferred = sw * MAX_DEF_PER_COL;
    w_top    = (int *)        malloc(sw * sizeof(int));
    w_bot    = (int *)        malloc(sw * sizeof(int));
    w_dist   = (double *)     malloc(sw * sizeof(double));
    deferred = (DeferredHit *)malloc(max_deferred * sizeof(DeferredHit));
    if (!w_top || !w_bot || !w_dist || !deferred) {
        PyErr_NoMemory();
        goto cleanup;
    }

    /* Default: no wall hit */
    for (int i = 0; i < sw; i++) {
        w_top[i]  = half;
        w_bot[i]  = half;
        w_dist[i] = MAX_DEPTH;
    }
    int n_deferred = 0;

    /* ── PHASE 0: Background fill ────────────────────────────────── */
    fill_background(fb, sw, sh, half, is_interior);

    /* Initialize per-pixel depth to MAX_DEPTH */
    for (int i = 0; i < sw * sh; i++) depth_px[i] = (float)MAX_DEPTH;

    /* ══════════════════════════════════════════════════════════════
     *  PHASE 1 — WALLS  (DDA with half/transparent/thin/tall support)
     * ══════════════════════════════════════════════════════════════ */
    for (int x = 0; x < sw; x++) {
        double cam_coord = 2.0 * x / (double)sw - 1.0;
        double rdx = dir_x + plane_x * cam_coord;
        double rdy = dir_y + plane_y * cam_coord;

        /* DDA setup */
        int mx = (int)cam_x;
        int my = (int)cam_y;

        double dd_x = fabs(rdx) > 1e-10 ? fabs(1.0 / rdx) : 1e10;
        double dd_y = fabs(rdy) > 1e-10 ? fabs(1.0 / rdy) : 1e10;

        int step_x, step_y;
        double sd_x, sd_y;

        if (rdx < 0) { step_x = -1; sd_x = (cam_x - mx) * dd_x; }
        else          { step_x =  1; sd_x = (mx + 1.0 - cam_x) * dd_x; }
        if (rdy < 0) { step_y = -1; sd_y = (cam_y - my) * dd_y; }
        else          { step_y =  1; sd_y = (my + 1.0 - cam_y) * dd_y; }

        /* DDA loop — multi-type wall detection */
        int hit = 0, side = 0;
        int n_short_col = 0;

        for (int s = 0; s < MAX_STEPS; s++) {
            if (sd_x < sd_y) { sd_x += dd_x; mx += step_x; side = 0; }
            else              { sd_y += dd_y; my += step_y; side = 1; }

            if (mx < 0 || mx >= map_w || my < 0 || my >= map_h)
                break;

            int tid = tiles[my * map_w + mx];
            if (tid < 0 || tid >= lut_len || !wall_lt[tid])
                continue;

            /* Compute perpendicular distance for this hit */
            double perp;
            if (side == 0)
                perp = (mx - cam_x + (1 - step_x) * 0.5) / rdx;
            else
                perp = (my - cam_y + (1 - step_y) * 0.5) / rdy;
            if (perp < 0.001) perp = 0.001;

            /* Wall fraction for texture X */
            double wfrac;
            if (side == 0) wfrac = cam_y + perp * rdy;
            else           wfrac = cam_x + perp * rdx;
            wfrac -= floor(wfrac);

            int cur_face = detect_face(side, step_x, step_y);
            int cur_ci   = my * map_w + mx;

            /* ── Short wall (hs < 1): defer and continue ray ──── */
            if (hs_arr[tid] < 0.999
                && n_short_col < MAX_SHORT_PER_COL
                && n_deferred < max_deferred) {
                DeferredHit *dh = &deferred[n_deferred++];
                dh->col       = x;
                dh->dist      = perp;
                dh->tid       = tid;
                dh->ci        = cur_ci;
                dh->side      = side;
                dh->face      = cur_face;
                dh->wall_frac = wfrac;
                dh->hs        = hs_arr[tid];
                n_short_col++;
                continue;
            }

            /* ── Thin wall: mid-cell intersection, continue ────── */
            if (thin_lt[tid] && n_deferred < max_deferred) {
                double mid_p;
                if (side == 0) mid_p = (mx + 0.5 - cam_x) / rdx;
                else           mid_p = (my + 0.5 - cam_y) / rdy;
                if (mid_p > 0.001) {
                    double wf;
                    if (side == 0) wf = cam_y + mid_p * rdy;
                    else           wf = cam_x + mid_p * rdx;
                    wf -= floor(wf);
                    DeferredHit *dh = &deferred[n_deferred++];
                    dh->col       = x;
                    dh->dist      = mid_p;
                    dh->tid       = tid;
                    dh->ci        = cur_ci;
                    dh->side      = side;
                    dh->face      = cur_face;
                    dh->wall_frac = wf;
                    dh->hs        = hs_arr[tid];
                    n_short_col++;
                }
                continue;
            }

            /* ── Transparent wall: defer and continue ray ──────── */
            if (trans_lt[tid] && n_deferred < max_deferred) {
                DeferredHit *dh = &deferred[n_deferred++];
                dh->col       = x;
                dh->dist      = perp;
                dh->tid       = tid;
                dh->ci        = cur_ci;
                dh->side      = side;
                dh->face      = cur_face;
                dh->wall_frac = wfrac;
                dh->hs        = hs_arr[tid];
                continue;
            }

            /* ── Full solid wall — stop the ray ────────────────── */
            hit = 1;
            break;
        }

        /* ── Pre-compute primary wall distance for overlay culling ── */
        if (hit) {
            double pre_perp;
            if (side == 0)
                pre_perp = (mx - cam_x + (1 - step_x) * 0.5) / rdx;
            else
                pre_perp = (my - cam_y + (1 - step_y) * 0.5) / rdy;
            if (pre_perp < 0.001) pre_perp = 0.001;
            w_dist[x] = pre_perp;
        }

        /* ── Overlay wall intersections (non-grid-aligned segments) ── */
        /* Test each column's ray against all overlay wall segments.
         * Hits are added to the deferred list for compositing in Phase 4.
         * Uses 2D ray-segment intersection: P + t*D vs A + u*(B-A).      */
        for (int ow = 0; ow < n_overlay && n_deferred < max_deferred; ow++) {
            double ox1    = ov_data[ow * 7 + 0];
            double oy1    = ov_data[ow * 7 + 1];
            double ox2    = ov_data[ow * 7 + 2];
            double oy2    = ov_data[ow * 7 + 3];
            double ohs    = ov_data[ow * 7 + 4];
            int    otid   = (int)ov_data[ow * 7 + 5];
            int    oflags = (int)ov_data[ow * 7 + 6];
            (void)oflags;

            double sdx_ov = ox2 - ox1;
            double sdy_ov = oy2 - oy1;
            double denom = rdx * sdy_ov - rdy * sdx_ov;
            if (fabs(denom) < 1e-10) continue;  /* parallel */

            double apx = ox1 - cam_x;
            double apy = oy1 - cam_y;

            double ov_t = (apx * sdy_ov - apy * sdx_ov) / denom;
            double ov_u = (apx * rdy    - apy * rdx)     / denom;

            if (ov_t < 0.001 || ov_u < 0.0 || ov_u > 1.0) continue;
            if (ov_t >= w_dist[x]) continue;  /* behind primary wall */

            /* Texture U: tile along segment length */
            double seg_len = sqrt(sdx_ov * sdx_ov + sdy_ov * sdy_ov);
            double along   = ov_u * seg_len;
            double wfrac   = along - floor(along);

            /* Side shading: vertical-running walls get EW dimming */
            int ov_side = (fabs(sdx_ov) >= fabs(sdy_ov)) ? 1 : 0;

            /* Cell index at hit point (for spatial lighting) */
            double hx  = cam_x + ov_t * rdx;
            double hy  = cam_y + ov_t * rdy;
            int    hcx = (int)floor(hx);
            int    hcy = (int)floor(hy);
            int    oci = -1;
            if (hcx >= 0 && hcx < map_w && hcy >= 0 && hcy < map_h)
                oci = hcy * map_w + hcx;

            DeferredHit *dh = &deferred[n_deferred++];
            dh->col       = x;
            dh->dist      = ov_t;
            dh->tid       = (otid >= 0 && otid < num_tiles) ? otid : 0;
            dh->ci        = oci;
            dh->side      = ov_side;
            dh->face      = 0;
            dh->wall_frac = wfrac;
            dh->hs        = ohs;
        }

        if (!hit) continue;

        /* perp already computed before overlay loop */
        double perp = w_dist[x];

        /* ── Wall geometry ─────────────────────────────────────── */
        int ci = my * map_w + mx;
        int line_h = (int)((double)sh / perp);
        if (line_h < 1) line_h = 1;

        double fh = (ci < map_size) ? clampd(fheight[ci], 0.0, 1.0) : 0.0;
        double ch = (ci < map_size) ? cheight[ci] : 1.0;
        if (ch >= SKY_THRESHOLD || ch < 0.0) ch = 1.0;

        int vis_top = (int)(half - line_h * (ch - CAM_H));
        int vis_bot = (int)(half + line_h * (CAM_H - fh));
        int full_top = half - line_h / 2;

        int y0 = clampi(vis_top, 0, sh - 1);
        int y1 = clampi(vis_bot, 0, sh - 1);

        w_top[x] = y0;
        w_bot[x] = y1;

        /* ── Texture X coordinate ─────────────────────────────── */
        double wall_frac;
        if (side == 0) wall_frac = cam_y + perp * rdy;
        else           wall_frac = cam_x + perp * rdx;
        wall_frac -= floor(wall_frac);
        int tex_x = (int)(wall_frac * ts) & ts_mask;

        /* ── Fog and side shading ─────────────────────────────── */
        int fog = fog_val(fog_lt, perp);
        int sr = 255, sg = 255, sb = 255;
        if (side == 1) { sr = SIDE_R; sg = SIDE_G; sb = SIDE_B; }

        /* Per-tile spatial lighting */
        double tile_light = (ci < map_size) ? light_grid[ci] : 1.0;

        /* ── Texture mapping for the wall column ──────────────── */
        int tid = tiles[ci];
        if (tid < 0 || tid >= num_tiles) tid = 0;

        /* Per-face directional texture resolution */
        int wall_face = detect_face(side, step_x, step_y);
        int tex_tid = (ci < map_size)
            ? resolve_face_tex(face_tex, ci, wall_face, tid, num_tiles)
            : tid;

        double tex_step = (double)ts / (double)line_h;
        double tex_pos  = (y0 - full_top) * tex_step;

        for (int y = y0; y <= y1; y++) {
            /* Tile texture vertically for walls taller than 1 unit */
            double tp = fmod(tex_pos, (double)ts);
            if (tp < 0.0) tp += (double)ts;
            int tex_y = clampi((int)tp, 0, ts - 1);
            tex_pos += tex_step;

            int r, g, b;
            sample_tex(atlas, ts, tex_tid, tex_x, tex_y, &r, &g, &b);

            r = (r * sr) >> 8;
            g = (g * sg) >> 8;
            b = (b * sb) >> 8;

            /* Spatial lighting */
            r = (int)(r * tile_light);
            g = (int)(g * tile_light);
            b = (int)(b * tile_light);

            r = (r * fog) >> 8;
            g = (g * fog) >> 8;
            b = (b * fog) >> 8;

            put_px(fb, sw, x, y, r, g, b);
            put_depth(depth_px, sw, x, y, (float)perp);
        }

        /* ── Tall wall extension (tile upward with repeating tex) ── */
        if (tall_lt[tid] && y0 > 0) {
            /* Use alt texture if available, else repeat main texture */
            int tall_tex = tex_tid;
            if (tid < lut_len && alt_tex_lt[tid] >= 0
                && alt_tex_lt[tid] < num_tiles) {
                tall_tex = alt_tex_lt[tid];
            }

            int rep_h = maxi(1, line_h);
            for (int ey = y0 - 1; ey >= 0; ey--) {
                /* Reverse-tile the texture upward from wall top */
                int rel = (y0 - 1 - ey) % rep_h;
                int tex_y_ext = ts - 1 - (int)((double)rel / rep_h * ts);
                tex_y_ext = clampi(tex_y_ext, 0, ts - 1);

                int r, g, b;
                sample_tex(atlas, ts, tall_tex, tex_x, tex_y_ext, &r, &g, &b);

                r = (r * sr) >> 8;
                g = (g * sg) >> 8;
                b = (b * sb) >> 8;
                r = (int)(r * tile_light);
                g = (int)(g * tile_light);
                b = (int)(b * tile_light);
                r = (r * fog) >> 8;
                g = (g * fog) >> 8;
                b = (b * fog) >> 8;

                put_px(fb, sw, x, ey, r, g, b);
                put_depth(depth_px, sw, x, ey, (float)perp);
            }
            w_top[x] = 0;   /* wall extends to screen top */
        }

        /* ── AO shadow below wall ────────────────────────────── */
        if (perp < 6.0 && y1 + 1 < sh) {
            int ao_h = clampi(line_h >> 3, 1, 6);
            int ao_end = mini(y1 + ao_h, sh - 1);
            for (int y = y1 + 1; y <= ao_end; y++) {
                double alpha = 0.35 * (1.0 - (double)(y - y1) / (double)ao_h);
                int off = (y * sw + x) * 3;
                fb[off]   = (uint8_t)(fb[off]   * (1.0 - alpha));
                fb[off+1] = (uint8_t)(fb[off+1] * (1.0 - alpha));
                fb[off+2] = (uint8_t)(fb[off+2] * (1.0 - alpha));
            }
        }
    }

    /* Copy depth buffer out for entity rendering */
    memcpy(zbuf_out, w_dist, sw * sizeof(double));

    /* ══════════════════════════════════════════════════════════════
     *  PHASE 2 — FLOOR  (row-sweep textured floor casting)
     * ══════════════════════════════════════════════════════════════ */
    for (int y = half + 1; y < sh; y++) {
        double p = (double)(y - half);
        if (p < 1.0) p = 1.0;

        double row_dist = CAM_H * (double)sh / p;

        double fx_step = row_dist * (ray1_x - ray0_x) / (double)sw;
        double fy_step = row_dist * (ray1_y - ray0_y) / (double)sw;

        double fx = cam_x + row_dist * ray0_x;
        double fy = cam_y + row_dist * ray0_y;

        int fog = fog_val(fog_lt, row_dist);

        for (int x = 0; x < sw; x++) {
            if (y <= w_bot[x]) {
                fx += fx_step;
                fy += fy_step;
                continue;
            }

            int cx = (int)floor(fx);
            int cy = (int)floor(fy);

            if (cx >= 0 && cx < map_w && cy >= 0 && cy < map_h) {
                int ci = cy * map_w + cx;
                int tid = tiles[ci];
                if (tid < 0 || tid >= num_tiles) tid = 0;

                int ftid = ftex[ci];
                if (ftid < 0 || ftid >= num_tiles) ftid = tid;

                /* Half-walls (counters, railings) are transparent:
                 * floor renders through them normally.  The wall
                 * face itself is drawn later in Phase 4 (deferred). */

                int u = (int)(ts * (fx - cx)) & ts_mask;
                int v = (int)(ts * (fy - cy)) & ts_mask;

                int r, g, b;
                sample_tex(atlas, ts, ftid, u, v, &r, &g, &b);

                if ((cx ^ cy) & 1) {
                    r = (r * 210) >> 8;
                    g = (g * 210) >> 8;
                    b = (b * 210) >> 8;
                }

                double fhv = fheight[ci];
                if (fhv > 0.01) {
                    double boost = 1.0 + 1.6 * fhv;
                    r = clampi((int)(r * boost), 0, 255);
                    g = clampi((int)(g * boost), 0, 255);
                    b = clampi((int)(b * boost), 0, 255);
                }

                /* Spatial lighting */
                double fl = light_grid[ci];
                r = (int)(r * fl);
                g = (int)(g * fl);
                b = (int)(b * fl);

                r = (r * fog) >> 8;
                g = (g * fog) >> 8;
                b = (b * fog) >> 8;

                put_px(fb, sw, x, y, r, g, b);
                put_depth(depth_px, sw, x, y, (float)row_dist);
            }

            fx += fx_step;
            fy += fy_step;
        }
    }

    /* ══════════════════════════════════════════════════════════════
     *  PHASE 3 — CEILING  (multi-tier row-sweep, interior zones)
     *
     *  Supports variable ceiling heights (1.0, 2.0, etc.).
     *  For each pixel above the horizon, we test every known ceiling
     *  tier from LOWEST (closest) to HIGHEST (farthest).  The first
     *  tier whose projected cell actually has a matching ceil_height
     *  wins — this guarantees no gaps at height transitions.
     * ══════════════════════════════════════════════════════════════ */
    if (is_interior) {
        /* ── Collect unique ceiling height tiers ──────────────── */
        #define MAX_CEIL_TIERS 16
        double ceil_tiers[MAX_CEIL_TIERS];
        int n_ceil_tiers = 0;

        for (int ci = 0; ci < map_size && n_ceil_tiers < MAX_CEIL_TIERS; ci++) {
            double ch = cheight[ci];
            if (ch >= SKY_THRESHOLD) continue;          /* skip sky  */
            if (ch <= CAM_H)         continue;          /* at/below camera */
            int found = 0;
            for (int j = 0; j < n_ceil_tiers; j++) {
                if (fabs(ceil_tiers[j] - ch) < 0.15) { found = 1; break; }
            }
            if (!found) ceil_tiers[n_ceil_tiers++] = ch;
        }

        /* Sort ASCENDING — try lowest (closest) ceilings first.
         * The first tier whose projected cell matches wins, so
         * closer surfaces naturally occlude farther ones.          */
        for (int i = 0; i < n_ceil_tiers - 1; i++)
            for (int j = i + 1; j < n_ceil_tiers; j++)
                if (ceil_tiers[j] < ceil_tiers[i]) {
                    double tmp = ceil_tiers[i];
                    ceil_tiers[i] = ceil_tiers[j];
                    ceil_tiers[j] = tmp;
                }

        /* ── Single unified sweep ────────────────────────────── */
        for (int y = half - 1; y >= 0; y--) {
            double p = (double)(half - y);
            if (p < 1.0) p = 1.0;

            /* Pre-compute per-tier ray origin + step for this row */
            double t_fx[MAX_CEIL_TIERS], t_fy[MAX_CEIL_TIERS];
            double t_fxs[MAX_CEIL_TIERS], t_fys[MAX_CEIL_TIERS];
            double t_rd[MAX_CEIL_TIERS];
            int    t_fog[MAX_CEIL_TIERS];

            for (int t = 0; t < n_ceil_tiers; t++) {
                double dh = ceil_tiers[t] - CAM_H;
                double rd = dh * (double)sh / p;
                t_rd[t]  = rd;
                t_fxs[t] = rd * (ray1_x - ray0_x) / (double)sw;
                t_fys[t] = rd * (ray1_y - ray0_y) / (double)sw;
                t_fx[t]  = cam_x + rd * ray0_x;
                t_fy[t]  = cam_y + rd * ray0_y;
                t_fog[t] = fog_val(fog_lt, rd);
            }

            for (int x = 0; x < sw; x++) {
                if (y >= w_top[x]) {
                    for (int t = 0; t < n_ceil_tiers; t++) {
                        t_fx[t] += t_fxs[t];
                        t_fy[t] += t_fys[t];
                    }
                    continue;
                }

                /* Try tiers lowest → highest; first match wins */
                for (int t = 0; t < n_ceil_tiers; t++) {
                    double cfx = t_fx[t];
                    double cfy = t_fy[t];
                    int tcx = (int)floor(cfx);
                    int tcy = (int)floor(cfy);

                    if (tcx < 0 || tcx >= map_w || tcy < 0 || tcy >= map_h)
                        continue;

                    int ci = tcy * map_w + tcx;
                    double c_h = cheight[ci];

                    /* Cell must match this tier's height */
                    if (fabs(c_h - ceil_tiers[t]) > 0.15)
                        continue;

                    /* Sky hole — paint sky gradient */
                    if (c_h >= SKY_THRESHOLD) {
                        double st = (double)y / (double)half;
                        int sr = SKY_TOP_R + (int)((SKY_BOT_R - SKY_TOP_R) * st);
                        int sg = SKY_TOP_G + (int)((SKY_BOT_G - SKY_TOP_G) * st);
                        int sb = SKY_TOP_B + (int)((SKY_BOT_B - SKY_TOP_B) * st);
                        put_px(fb, sw, x, y, sr, sg, sb);
                        put_depth(depth_px, sw, x, y, (float)t_rd[t]);
                        break;
                    }

                    int tid = tiles[ci];
                    if (tid < 0 || tid >= num_tiles) tid = 0;

                    int ctid = ctex[ci];
                    if (ctid < 0 || ctid >= num_tiles) ctid = tid;

                    int u = (int)(ts * (cfx - tcx)) & ts_mask;
                    int v = (int)(ts * (cfy - tcy)) & ts_mask;

                    int r, g, b;
                    sample_tex(atlas, ts, ctid, u, v, &r, &g, &b);

                    /* Dim low ceilings (claustrophobic feel) */
                    if (c_h < 0.99) {
                        double dim = 0.5 + 0.5 * c_h;
                        r = (int)(r * dim);
                        g = (int)(g * dim);
                        b = (int)(b * dim);
                    }

                    r = (r * 180) >> 8;
                    g = (g * 180) >> 8;
                    b = (b * 180) >> 8;

                    /* Spatial lighting */
                    double cl = light_grid[ci];
                    r = (int)(r * cl);
                    g = (int)(g * cl);
                    b = (int)(b * cl);

                    int fog = t_fog[t];
                    r = (r * fog) >> 8;
                    g = (g * fog) >> 8;
                    b = (b * fog) >> 8;

                    put_px(fb, sw, x, y, r, g, b);
                    put_depth(depth_px, sw, x, y, (float)t_rd[t]);
                    break;  /* first match wins — closest ceiling */
                }

                /* Advance ALL tier positions regardless */
                for (int t = 0; t < n_ceil_tiers; t++) {
                    t_fx[t] += t_fxs[t];
                    t_fy[t] += t_fys[t];
                }
            }
        }
    }

    /* ══════════════════════════════════════════════════════════════
     *  PHASE 3.5 — CEILING STEP WALLS
     *
     *  Where adjacent cells have different ceiling heights, draw a
     *  textured vertical face at the boundary (Doom-style "upper
     *  texture").  Uses a per-column mini-DDA that walks until it
     *  hits a full-height solid wall, recording every height change.
     * ══════════════════════════════════════════════════════════════ */
    if (is_interior) {
        for (int x = 0; x < sw; x++) {
            /* Column already filled to top — nothing above the wall */
            if (w_top[x] <= 0) continue;

            /* Ray direction (same geometry as Phase 1) */
            double cfrac = 2.0 * x / (double)sw - 1.0;
            double rdx = dir_x + plane_x * cfrac;
            double rdy = dir_y + plane_y * cfrac;

            int mx = (int)cam_x;
            int my = (int)cam_y;

            double ddx = fabs(rdx) > 1e-10 ? fabs(1.0 / rdx) : 1e10;
            double ddy = fabs(rdy) > 1e-10 ? fabs(1.0 / rdy) : 1e10;

            int ssx, ssy;
            double sdx, sdy;

            if (rdx < 0) { ssx = -1; sdx = (cam_x - mx) * ddx; }
            else          { ssx =  1; sdx = (mx + 1.0 - cam_x) * ddx; }
            if (rdy < 0) { ssy = -1; sdy = (cam_y - my) * ddy; }
            else          { ssy =  1; sdy = (my + 1.0 - cam_y) * ddy; }

            /* Camera cell ceiling height */
            int pci = clampi(my, 0, map_h - 1) * map_w
                    + clampi(mx, 0, map_w - 1);
            double pch = cheight[pci];
            if (pch >= SKY_THRESHOLD || pch < 0.0) pch = 1.0;

            /* Local ceiling top for inter-step occlusion */
            int col_top = w_top[x];

            int sd;
            for (int stp = 0; stp < MAX_STEPS; stp++) {
                if (sdx < sdy) { sdx += ddx; mx += ssx; sd = 0; }
                else            { sdy += ddy; my += ssy; sd = 1; }

                if (mx < 0 || mx >= map_w || my < 0 || my >= map_h)
                    break;

                int ci  = my * map_w + mx;
                int tid = tiles[ci];
                if (tid < 0 || tid >= lut_len) tid = 0;

                double cch = cheight[ci];
                if (cch >= SKY_THRESHOLD || cch < 0.0) cch = 1.0;

                /* ── Ceiling height transition ──────────────────── */
                if (fabs(cch - pch) > 0.15) {
                    double perp;
                    if (sd == 0)
                        perp = (mx - cam_x + (1 - ssx) * 0.5) / rdx;
                    else
                        perp = (my - cam_y + (1 - ssy) * 0.5) / rdy;
                    if (perp < 0.001) perp = 0.001;

                    int line_h = (int)((double)sh / perp);
                    if (line_h < 1) line_h = 1;

                    double lo = pch < cch ? pch : cch;
                    double hi = pch > cch ? pch : cch;

                    /* Screen band for the step face */
                    int uncl_top = (int)(half - line_h * (hi - CAM_H));
                    int uncl_bot = (int)(half - line_h * (lo - CAM_H));

                    int s_top = clampi(uncl_top, 0, sh - 1);
                    int s_bot = clampi(uncl_bot, 0, sh - 1);

                    /* Clip below existing wall / earlier step */
                    if (s_bot >= col_top) s_bot = col_top - 1;

                    if (s_top <= s_bot) {
                        /* Texture X from wall fraction */
                        double wf;
                        if (sd == 0) wf = cam_y + perp * rdy;
                        else         wf = cam_x + perp * rdx;
                        wf -= floor(wf);
                        int tex_x = (int)(wf * ts) & ts_mask;

                        /* Face of the entered cell facing the camera */
                        int cs_face = detect_face(sd, ssx, ssy);

                        /* Texture from the higher-ceiling cell */
                        int hi_ci, hi_face;
                        if (cch >= pch) {
                            hi_ci   = ci;
                            hi_face = cs_face;
                        } else {
                            hi_ci   = pci;
                            hi_face = cs_face ^ 1;  /* opposite face */
                        }
                        int hi_tid = tiles[hi_ci];
                        if (hi_tid < 0 || hi_tid >= lut_len) hi_tid = 0;

                        int stex = resolve_face_tex(
                            face_tex, hi_ci, hi_face, hi_tid, num_tiles);

                        /* Texture Y mapping */
                        double tex_stp = (double)ts / (double)line_h;
                        double tex_pos = (s_top - uncl_top) * tex_stp;

                        /* Shading */
                        int sr = 255, sg = 255, sb = 255;
                        if (sd == 1) { sr = SIDE_R; sg = SIDE_G; sb = SIDE_B; }
                        int fog = fog_val(fog_lt, perp);
                        double tl = light_grid[ci];

                        for (int y = s_top; y <= s_bot; y++) {
                            double tp = fmod(tex_pos, (double)ts);
                            if (tp < 0.0) tp += (double)ts;
                            int tex_y = clampi((int)tp, 0, ts - 1);
                            tex_pos += tex_stp;

                            int r, g, b;
                            sample_tex(atlas, ts, stex, tex_x, tex_y,
                                       &r, &g, &b);

                            r = (r * sr) >> 8;
                            g = (g * sg) >> 8;
                            b = (b * sb) >> 8;

                            r = (int)(r * tl);
                            g = (int)(g * tl);
                            b = (int)(b * tl);

                            r = (r * fog) >> 8;
                            g = (g * fog) >> 8;
                            b = (b * fog) >> 8;

                            put_px(fb, sw, x, y, r, g, b);
                            put_depth(depth_px, sw, x, y, (float)perp);
                        }

                        /* Update local top for inter-step occlusion */
                        if (s_top < col_top) col_top = s_top;
                    }
                }

                pch = cch;
                pci = ci;

                /* Stop at full-height solid wall (not short, not thin) */
                if (wall_lt[tid] && hs_arr[tid] >= 0.999
                    && !thin_lt[tid]) break;
            }
        }
    }

    /* ══════════════════════════════════════════════════════════════
     *  PHASE 4 — DEFERRED WALLS  (short walls + thin, far→near)
     * ══════════════════════════════════════════════════════════════ */
    if (n_deferred > 0) {
        qsort(deferred, n_deferred, sizeof(DeferredHit), cmp_deferred_desc);

        for (int di = 0; di < n_deferred; di++) {
            const DeferredHit *dh = &deferred[di];
            const int    dx      = dh->col;
            const double d_perp  = dh->dist;
            const int    d_tid   = dh->tid;
            const int    d_ci    = dh->ci;
            const int    d_side  = dh->side;
            const int    d_face  = dh->face;
            const double d_wfrac = dh->wall_frac;
            const double d_hs    = dh->hs;

            int d_line_h = (int)((double)sh / d_perp);
            if (d_line_h < 1) d_line_h = 1;

            int d_fog = fog_val(fog_lt, d_perp);
            int d_sr = 255, d_sg = 255, d_sb = 255;
            if (d_side == 1) { d_sr = SIDE_R; d_sg = SIDE_G; d_sb = SIDE_B; }

            /* Per-tile spatial lighting for deferred walls */
            double d_light = (d_ci >= 0 && d_ci < map_size)
                ? light_grid[d_ci] : 1.0;

            int d_tex_x = (int)(d_wfrac * ts) & ts_mask;

            int safe_tid = (d_tid >= 0 && d_tid < num_tiles) ? d_tid : 0;
            /* Resolve per-face texture for deferred walls */
            if (d_ci >= 0 && d_ci < map_size) {
                safe_tid = resolve_face_tex(face_tex, d_ci, d_face,
                                            safe_tid, num_tiles);
            }

            /* ── Short/thin wall: anchored at cell floor level ──── */
            double d_fh = (d_ci >= 0 && d_ci < map_size)
                ? clampd(fheight[d_ci], 0.0, 1.0) : 0.0;
            int d_vis_bot = (int)(half + d_line_h * (CAM_H - d_fh));
            int d_scaled_h = (int)(d_line_h * d_hs);
            int d_hw_top   = d_vis_bot - d_scaled_h;
            int d_hw_bot   = d_vis_bot;

            int d_y0 = clampi(d_hw_top, 0, sh - 1);
            int d_y1 = clampi(d_hw_bot, 0, sh - 1);

            /* Texture: scale full texture to fit the visible height.
             * This avoids cropping — the whole texture maps onto the
             * short wall, regardless of height_scale. */
            int d_hw_h = d_hw_bot - d_hw_top;
            double d_tex_step = (d_hw_h > 0)
                ? (double)ts / (double)d_hw_h : 0.0;
            double d_tex_pos = (d_y0 - d_hw_top) * d_tex_step;
            if (d_tex_pos < 0.0) d_tex_pos = 0.0;

            for (int y = d_y0; y <= d_y1; y++) {
                int tex_y = clampi((int)d_tex_pos, 0, ts - 1);
                d_tex_pos += d_tex_step;

                int r, g, b;
                sample_tex(atlas, ts, safe_tid, d_tex_x, tex_y,
                           &r, &g, &b);

                /* Color-key transparency: skip magenta (255,0,255)
                 * pixels so the surface behind shows through.
                 * Used for fences, bars, lattices, etc.          */
                if (r >= 250 && g <= 5 && b >= 250) continue;

                /* Per-pixel depth check: skip if behind already-drawn
                 * geometry (primary walls, floors, ceilings, etc.) */
                if ((float)d_perp >= depth_px[y * sw + dx]) continue;

                r = (r * d_sr) >> 8;
                g = (g * d_sg) >> 8;
                b = (b * d_sb) >> 8;
                r = (int)(r * d_light);
                g = (int)(g * d_light);
                b = (int)(b * d_light);
                r = (r * d_fog) >> 8;
                g = (g * d_fog) >> 8;
                b = (b * d_fog) >> 8;

                put_px(fb, sw, dx, y, r, g, b);
                put_depth(depth_px, sw, dx, y, (float)d_perp);
            }

            /* AO shadow below short wall */
            if (d_perp < 6.0 && d_y1 + 1 < sh) {
                int ao_h = clampi(d_scaled_h >> 3, 1, 4);
                int ao_end = mini(d_y1 + ao_h, sh - 1);
                for (int y = d_y1 + 1; y <= ao_end; y++) {
                    double al = 0.25 * (1.0 - (double)(y - d_y1)
                                        / (double)ao_h);
                    int off = (y * sw + dx) * 3;
                    fb[off]   = (uint8_t)(fb[off]   * (1.0 - al));
                    fb[off+1] = (uint8_t)(fb[off+1] * (1.0 - al));
                    fb[off+2] = (uint8_t)(fb[off+2] * (1.0 - al));
                }
            }

            /* ── Counter-top horizontal surface ──────────────────── */
            /* Renders the visible top of short walls when the camera
             * is above the counter height.  Uses floor-cast technique
             * at counter-top height, constrained to the counter tile. */
            {
                double counter_h = d_fh + d_hs;
                if (d_hs < 0.999 && CAM_H > counter_h && d_hw_top > half) {
                    double dh_cam = CAM_H - counter_h;  /* height above top */
                    /* Ray direction for this column */
                    double cc  = 2.0 * dx / (double)sw - 1.0;
                    double rx  = dir_x + plane_x * cc;
                    double ry  = dir_y + plane_y * cc;
                    int tile_x = d_ci % map_w;
                    int tile_y = d_ci / map_w;

                    /* Base tile texture for horizontal surface */
                    int top_tid = (d_tid >= 0 && d_tid < num_tiles)
                        ? d_tid : 0;

                    int top_start = clampi(d_hw_top - 1, half + 1, sh - 1);
                    for (int y = top_start; y > half; y--) {
                        double p = (double)(y - half);
                        /* Distance at which this ray hits counter_h */
                        double td = (double)sh * dh_cam / p;

                        /* World coordinates on the counter-top plane */
                        double wx = cam_x + td * rx;
                        double wy = cam_y + td * ry;
                        int wxi = (int)floor(wx);
                        int wyi = (int)floor(wy);

                        /* Only render while on the counter tile */
                        if (wxi != tile_x || wyi != tile_y) break;

                        int u = (int)(ts * (wx - wxi)) & ts_mask;
                        int v = (int)(ts * (wy - wyi)) & ts_mask;

                        int r, g, b;
                        sample_tex(atlas, ts, top_tid, u, v, &r, &g, &b);

                        /* Checkerboard dimming (matches floor style) */
                        if ((wxi ^ wyi) & 1) {
                            r = (r * 210) >> 8;
                            g = (g * 210) >> 8;
                            b = (b * 210) >> 8;
                        }

                        /* Brighten top surface (faces upward, well-lit) */
                        r = mini(255, (r * 280) >> 8);
                        g = mini(255, (g * 280) >> 8);
                        b = mini(255, (b * 280) >> 8);

                        r = (int)(r * d_light);
                        g = (int)(g * d_light);
                        b = (int)(b * d_light);

                        int tf = fog_val(fog_lt, td);
                        r = (r * tf) >> 8;
                        g = (g * tf) >> 8;
                        b = (b * tf) >> 8;

                        put_px(fb, sw, dx, y, r, g, b);
                        put_depth(depth_px, sw, dx, y, (float)td);
                    }
                }
            }

            /* ── Update z-buffer for deferred walls ──────────────── */
            if (d_perp < zbuf_out[dx]) {
                zbuf_out[dx] = d_perp;
            }
        }
    }

    } /* end scope block */

    result = Py_None;
    Py_INCREF(Py_None);

cleanup:
    if (fb_buf.buf)    PyBuffer_Release(&fb_buf);
    if (tiles_buf.buf) PyBuffer_Release(&tiles_buf);
    if (wall_buf.buf)  PyBuffer_Release(&wall_buf);
    if (atlas_buf.buf) PyBuffer_Release(&atlas_buf);
    if (fog_buf.buf)   PyBuffer_Release(&fog_buf);
    if (fh_buf.buf)    PyBuffer_Release(&fh_buf);
    if (ch_buf.buf)    PyBuffer_Release(&ch_buf);
    if (ft_buf.buf)    PyBuffer_Release(&ft_buf);
    if (ct_buf.buf)    PyBuffer_Release(&ct_buf);
    if (thin_buf.buf)  PyBuffer_Release(&thin_buf);
    if (tall_buf.buf)  PyBuffer_Release(&tall_buf);
    if (hs_buf.buf)    PyBuffer_Release(&hs_buf);
    if (ftex_grid_buf.buf) PyBuffer_Release(&ftex_grid_buf);
    if (zbuf_buf.buf)  PyBuffer_Release(&zbuf_buf);
    if (light_buf.buf) PyBuffer_Release(&light_buf);
    if (alt_tex_buf.buf) PyBuffer_Release(&alt_tex_buf);
    if (depth_px_buf.buf) PyBuffer_Release(&depth_px_buf);
    if (trans_buf.buf) PyBuffer_Release(&trans_buf);
    if (overlay_buf.buf) PyBuffer_Release(&overlay_buf);
    free(w_top);
    free(w_bot);
    free(w_dist);
    free(deferred);
    return result;
}


/* ═══════════════════════════════════════════════════════════════════
 *  Entity billboard renderer
 * ═══════════════════════════════════════════════════════════════════
 *
 * Arguments (positional):
 *
 *   fb          : writable buffer uint8[sw * sh * 3]
 *   sw, sh      : int
 *   cam_x, cam_y: double
 *   dir_x, dir_y: double  — camera direction unit vector
 *   plane_x, plane_y : double — camera plane vector
 *   depth_px    : buffer float32[sw*sh] — per-pixel depth (from render_frame)
 *   fog_lut     : buffer uint8[256]
 *   atlas       : buffer uint8[num_tiles * ts * ts * 3] — tile atlas
 *   tex_size    : int — texture side length (e.g. 64)
 *   num_tiles   : int — number of tiles in atlas
 *   ent_data    : buffer double[n * 8] — packed entity data:
 *                   [x, y, r, g, b, h_scale, w_scale, tex_id] per entity
 *   n_ents      : int — number of entities
 *
 * Returns None.
 */
static PyObject *
py_render_entities(PyObject *self, PyObject *args)
{
    int sw, sh, n_ents, tex_size, num_tiles;
    double cam_x, cam_y, dir_x, dir_y, plane_x, plane_y;

    Py_buffer fb_buf   = {0};
    Py_buffer depth_px_buf = {0};
    Py_buffer fog_buf  = {0};
    Py_buffer atlas_buf = {0};
    Py_buffer ent_buf  = {0};

    if (!PyArg_ParseTuple(args,
            "y*ii"           /* fb, sw, sh             */
            "dd"             /* cam_x, cam_y           */
            "dd"             /* dir_x, dir_y           */
            "dd"             /* plane_x, plane_y       */
            "y*y*"           /* depth_px, fog          */
            "y*ii"           /* atlas, tex_size, ntile */
            "y*i",           /* ents, n                */
            &fb_buf, &sw, &sh,
            &cam_x, &cam_y,
            &dir_x, &dir_y,
            &plane_x, &plane_y,
            &depth_px_buf, &fog_buf,
            &atlas_buf, &tex_size, &num_tiles,
            &ent_buf, &n_ents))
        return NULL;

    if (fb_buf.readonly) {
        PyErr_SetString(PyExc_TypeError, "fb must be writable");
        PyBuffer_Release(&fb_buf);
        PyBuffer_Release(&depth_px_buf);
        PyBuffer_Release(&fog_buf);
        PyBuffer_Release(&atlas_buf);
        PyBuffer_Release(&ent_buf);
        return NULL;
    }

    uint8_t       *fb      = (uint8_t *)fb_buf.buf;
    const float   *depth_px = (const float *)depth_px_buf.buf;
    const uint8_t *fog_lt  = (const uint8_t *)fog_buf.buf;
    const uint8_t *atlas   = (const uint8_t *)atlas_buf.buf;
    const double  *ent     = (const double *)ent_buf.buf;
    const int      ts      = tex_size;
    const int      ts_mask = ts - 1;

    /* Inverse determinant of the camera matrix */
    double inv_det = 1.0 / (plane_x * dir_y - dir_x * plane_y);

    /* Sort entities far-to-near using a simple index array + qsort.
     * For small entity counts this is fine. */
    typedef struct { int idx; double dist; } EntSort;
    EntSort *sorted = (EntSort *)malloc(n_ents * sizeof(EntSort));
    if (!sorted && n_ents > 0) {
        PyErr_NoMemory();
        PyBuffer_Release(&fb_buf);
        PyBuffer_Release(&depth_px_buf);
        PyBuffer_Release(&fog_buf);
        PyBuffer_Release(&ent_buf);
        return NULL;
    }

    for (int i = 0; i < n_ents; i++) {
        double ex = ent[i * 8 + 0];
        double ey = ent[i * 8 + 1];
        double dx = ex - cam_x;
        double dy = ey - cam_y;
        sorted[i].idx  = i;
        sorted[i].dist = dx * dx + dy * dy;  /* squared for sorting */
    }

    /* Sort far-to-near (descending distance) */
    for (int i = 0; i < n_ents - 1; i++) {
        for (int j = i + 1; j < n_ents; j++) {
            if (sorted[j].dist > sorted[i].dist) {
                EntSort tmp = sorted[i];
                sorted[i] = sorted[j];
                sorted[j] = tmp;
            }
        }
    }

    /* Render each entity */
    for (int si = 0; si < n_ents; si++) {
        int ei = sorted[si].idx;
        double ex = ent[ei * 8 + 0];
        double ey = ent[ei * 8 + 1];
        int    er = clampi((int)ent[ei * 8 + 2], 0, 255);
        int    eg = clampi((int)ent[ei * 8 + 3], 0, 255);
        int    eb = clampi((int)ent[ei * 8 + 4], 0, 255);
        double e_hscale = ent[ei * 8 + 5];
        double e_wscale = ent[ei * 8 + 6];
        int    e_tex_id = (int)ent[ei * 8 + 7];
        int    has_tex  = (e_tex_id >= 0 && e_tex_id < num_tiles);

        /* Camera-relative transform */
        double dx = ex - cam_x;
        double dy = ey - cam_y;
        double tx = inv_det * (dir_y * dx - dir_x * dy);
        double ty = inv_det * (-plane_y * dx + plane_x * dy);

        if (ty <= 0.1) continue;   /* behind camera */

        /* Screen projection */
        int scr_x = (int)((sw / 2.0) * (1.0 + tx / ty));
        double wall_h = (double)sh / ty;

        int spr_h = (int)(wall_h * e_hscale);
        int spr_w = (int)(wall_h * e_wscale);
        if (spr_h < 1 || spr_w < 1) continue;

        /* Vertical positioning: base at floor level */
        int floor_y = (int)((sh + wall_h) / 2.0);
        int spr_y0 = floor_y - spr_h;
        int spr_x0 = scr_x - spr_w / 2;

        /* Clamp to screen */
        int x0 = clampi(spr_x0, 0, sw - 1);
        int x1 = clampi(spr_x0 + spr_w - 1, 0, sw - 1);
        int y0 = clampi(spr_y0, 0, sh - 1);
        int y1 = clampi(spr_y0 + spr_h - 1, 0, sh - 1);

        int fog = fog_val(fog_lt, ty);

        /* Apply fog to entity colour */
        int fr = (er * fog) >> 8;
        int fg = (eg * fog) >> 8;
        int fb_c = (eb * fog) >> 8;

        /* Draw with per-pixel depth clipping */
        for (int cx = x0; cx <= x1; cx++) {
            /* Compute texture U for this column (0..ts-1) */
            double u_frac = (double)(cx - spr_x0) / (double)spr_w;
            int tex_u = clampi((int)(u_frac * ts), 0, ts_mask);

            for (int cy = y0; cy <= y1; cy++) {
                /* Per-pixel depth test: skip if something closer */
                if (ty >= (double)depth_px[cy * sw + cx]) continue;
                if (has_tex) {
                    /* Textured billboard: sample from atlas */
                    double v_frac = (double)(cy - spr_y0) / (double)spr_h;
                    int tex_v = clampi((int)(v_frac * ts), 0, ts_mask);

                    int sr, sg, sb;
                    sample_tex(atlas, ts, e_tex_id, tex_u, tex_v,
                               &sr, &sg, &sb);

                    /* Skip near-black pixels (transparency) */
                    if (sr + sg + sb < 15) continue;

                    /* Tint with entity colour */
                    sr = (sr * (128 + er / 2)) >> 8;
                    sg = (sg * (128 + eg / 2)) >> 8;
                    sb = (sb * (128 + eb / 2)) >> 8;
                    sr = clampi(sr, 0, 255);
                    sg = clampi(sg, 0, 255);
                    sb = clampi(sb, 0, 255);

                    sr = (sr * fog) >> 8;
                    sg = (sg * fog) >> 8;
                    sb = (sb * fog) >> 8;

                    put_px(fb, sw, cx, cy, sr, sg, sb);
                } else {
                    /* Coloured block with body/head shading */
                    double v_frac = (double)(cy - spr_y0) / (double)spr_h;
                    int is_head = (v_frac < 0.3) ? 1 : 0;
                    int edge_x = (cx == x0 || cx == x1) ? 1 : 0;
                    int edge_y = (cy == y0 || cy == y1) ? 1 : 0;

                    int pr = fr, pg = fg, pb = fb_c;
                    if (is_head) {
                        /* Head slightly brighter */
                        pr = mini(255, (pr * 280) >> 8);
                        pg = mini(255, (pg * 280) >> 8);
                        pb = mini(255, (pb * 280) >> 8);
                    }
                    if (edge_x || edge_y) {
                        pr >>= 1; pg >>= 1; pb >>= 1;
                    }
                    put_px(fb, sw, cx, cy, pr, pg, pb);
                }
            }
        }
    }

    free(sorted);
    PyBuffer_Release(&fb_buf);
    PyBuffer_Release(&depth_px_buf);
    PyBuffer_Release(&fog_buf);
    PyBuffer_Release(&atlas_buf);
    PyBuffer_Release(&ent_buf);
    Py_RETURN_NONE;
}


/* ═══════════════════════════════════════════════════════════════════
 *  Depth buffer → grayscale visualisation helper
 * ═══════════════════════════════════════════════════════════════════
 *
 * Arguments (positional):
 *   fb        : writable buffer uint8[sw * sh * 3]
 *   depth_px  : buffer float32[sw * sh] (per-pixel depth from render_frame)
 *   sw, sh    : int
 *   max_dist  : double — clamp distance for mapping
 *
 * Writes grayscale RGB into fb (close = bright, far = dark, log scale).
 */
static PyObject *
py_depth_to_grayscale(PyObject *self, PyObject *args)
{
    Py_buffer fb_buf = {0};
    Py_buffer dp_buf = {0};
    int sw, sh;
    double max_d;

    if (!PyArg_ParseTuple(args, "y*y*iid",
            &fb_buf, &dp_buf, &sw, &sh, &max_d))
        return NULL;

    if (fb_buf.readonly) {
        PyErr_SetString(PyExc_TypeError, "fb must be writable");
        PyBuffer_Release(&fb_buf);
        PyBuffer_Release(&dp_buf);
        return NULL;
    }

    uint8_t     *fb    = (uint8_t *)fb_buf.buf;
    const float *depth = (const float *)dp_buf.buf;
    double log_max = log(1.0 + max_d);
    int n = sw * sh;

    for (int i = 0; i < n; i++) {
        double d = (double)depth[i];
        int bri;
        if (d <= 0.0 || d >= max_d) {
            bri = 0;
        } else {
            double t = log(1.0 + d) / log_max;
            bri = (int)(255.0 * (1.0 - t));
            if (bri < 0) bri = 0;
            if (bri > 255) bri = 255;
        }
        fb[i * 3]     = (uint8_t)bri;
        fb[i * 3 + 1] = (uint8_t)bri;
        fb[i * 3 + 2] = (uint8_t)bri;
    }

    PyBuffer_Release(&fb_buf);
    PyBuffer_Release(&dp_buf);
    Py_RETURN_NONE;
}


/* ═══════════════════════════════════════════════════════════════════
 *  Module definition
 * ═══════════════════════════════════════════════════════════════════ */

static PyMethodDef methods[] = {
    {"render_frame", py_render_frame, METH_VARARGS,
     "Render a complete raycaster frame into a pre-allocated buffer.\n\n"
     "render_frame(fb, cam_x, cam_y, angle, fov, sw, sh, map_w, map_h,\n"
     "             tiles, wall_lut, atlas, tex_size, num_tiles,\n"
     "             fog_lut, floor_h, ceil_h, floor_tex, ceil_tex,\n"
     "             is_interior, thin_lut, tall_lut,\n"
     "             hs_lut, face_tex, zbuf_out, light_buf, alt_tex,\n"
     "             depth_px, trans_lut, overlay_buf, n_overlay) -> None"},
    {"render_entities", py_render_entities, METH_VARARGS,
     "Render entity billboards with z-buffer clipping.\n\n"
     "render_entities(fb, sw, sh, cam_x, cam_y, dir_x, dir_y,\n"
     "                plane_x, plane_y, depth_px, fog_lut,\n"
     "                atlas, tex_size, num_tiles,\n"
     "                ent_data, n_ents) -> None"},
    {"depth_to_grayscale", py_depth_to_grayscale, METH_VARARGS,
     "Convert per-pixel depth buffer to grayscale visualisation.\n\n"
     "depth_to_grayscale(fb, depth_px, sw, sh, max_dist) -> None"},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef moduledef = {
    PyModuleDef_HEAD_INIT,
    "_ray_render",
    "Full-frame C raycasting renderer with textured walls, floors, "
    "ceilings, short walls, per-tile lighting, and entity billboards.",
    -1,
    methods
};

PyMODINIT_FUNC
PyInit__ray_render(void)
{
    return PyModule_Create(&moduledef);
}
