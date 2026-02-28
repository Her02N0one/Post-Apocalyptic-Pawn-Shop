/*  engine/_ray_render.c  -  Full-frame C raycasting renderer.
 *
 *  Main rendering entry point: py_render_frame.
 *  Draws textured walls, floors, ceilings, short/thin/tall/transparent walls,
 *  per-tile lighting, fog, and floor/ceiling height tiers.
 *
 *  Entity billboard rendering  -> _ray_entities.c
 *  Debug visualisation helpers -> _ray_debug.c
 *  Shared types and helpers    -> _ray_render.h
 *
 *  Compile:  python build_ext.py build_ext --inplace
 */

#include "_ray_render.h"

#ifdef _OPENMP
#include <omp.h>
#endif

/* ── Segmented wall column renderer ──────────────────────────────
 * Draws a wall column using per-face texture segments (stacked textures).
 * Each segment has a texture and a top-Y in world units.
 * Segments are sorted bottom-to-top.  The first segment's bottom is
 * the wall's floor height; the last segment's top is the ceiling height.
 *
 * Parameters:
 *   fb, sw, x        — framebuffer, screen width, column index
 *   depth_px         — per-pixel depth buffer
 *   atlas, ts, ts_mask — texture atlas data
 *   half, line_h     — half screen height, pixel-height-per-world-unit
 *   y0, y1           — visible screen-Y range (already clipped)
 *   fh, ch           — world floor / ceiling height of this cell
 *   tex_x            — texture U coordinate (shared for all segments)
 *   sr, sg, sb       — side shading multipliers (0-255)
 *   fog              — fog multiplier (0-255)
 *   tile_light       — spatial light multiplier (0.0-1.0)
 *   perp             — perpendicular distance for depth-write
 *   fallback_tid     — texture to use when segment tex is invalid
 *   seg_tex, seg_ytop — segment arrays (indexed by seg_off + i)
 *   seg_off, n_segs  — offset into segment arrays, segment count
 *   num_tiles        — bounds for texture ID validation
 *   vscale           — per-tile v_scale array (may be NULL)
 */
static void draw_segmented_column_ex(
    uint8_t *fb, int sw, int x,
    float *depth_px,
    const uint8_t *atlas, int ts, int ts_mask,
    int half, int line_h,
    int y0, int y1,
    double fh, double ch,
    int tex_x,
    int sr, int sg, int sb,
    int fog, double tile_light, double perp,
    int fallback_tid,
    const int32_t *seg_tex_arr, const double *seg_ytop_arr,
    int seg_off, int n_segs,
    int num_tiles,
    const double *vscale,
    double cam_h,
    int depth_test,
    const int32_t *anim_lt,
    int anim_tick,
    double plr, double plg_v, double plb)
{
    for (int si = 0; si < n_segs; si++) {
        double seg_bot = (si == 0) ? fh : seg_ytop_arr[seg_off + si - 1];
        double seg_top = seg_ytop_arr[seg_off + si];
        if (seg_top <= seg_bot) continue;

        int stid = seg_tex_arr[seg_off + si];
        if (stid < 0 || stid >= num_tiles) stid = fallback_tid;
        stid = resolve_anim_tid(anim_lt, stid, anim_tick, num_tiles);

        /* Screen Y positions (higher world Y → lower screen Y) */
        int scr_top = (int)(half + line_h * (cam_h - seg_top));
        int scr_bot = (int)(half + line_h * (cam_h - seg_bot));

        /* Clamp to visible wall range */
        int sy0 = scr_top < y0 ? y0 : scr_top;
        int sy1 = scr_bot > y1 ? y1 : scr_bot;
        if (sy0 > sy1) continue;

        /* Texture V mapping: one full texture per world-unit, or
         * scaled by v_scale if provided. */
        double vs = (vscale && stid < num_tiles) ? vscale[stid] : 1.0;
        double seg_tex_step = (double)ts * vs / (double)line_h;
        double seg_tex_pos  = (sy0 - scr_top) * seg_tex_step;

        for (int y = sy0; y <= sy1; y++) {
            /* Per-pixel depth test: skip if existing pixel is closer */
            if (depth_test && depth_px[y * sw + x] <= (float)perp) {
                seg_tex_pos += seg_tex_step;
                continue;
            }
            double tp = fmod(seg_tex_pos, (double)ts);
            if (tp < 0.0) tp += (double)ts;
            int tex_y = clampi((int)tp, 0, ts - 1);
            seg_tex_pos += seg_tex_step;

            int r, g, b, a;
            sample_tex(atlas, ts, stid, tex_x, tex_y, &r, &g, &b, &a);
            if (a <= 0) { seg_tex_pos += seg_tex_step; continue; }

            r = (r * sr) >> 8;
            g = (g * sg) >> 8;
            b = (b * sb) >> 8;
            apply_lights(&r, &g, &b, tile_light, plr, plg_v, plb);
            r = (r * fog) >> 8;
            g = (g * fog) >> 8;
            b = (b * fog) >> 8;

            blend_px(fb, sw, x, y, r, g, b, a);
            if (a >= 255) put_depth(depth_px, sw, x, y, (float)perp);
        }
    }
}

static void draw_segmented_column(
    uint8_t *fb, int sw, int x,
    float *depth_px,
    const uint8_t *atlas, int ts, int ts_mask,
    int half, int line_h,
    int y0, int y1,
    double fh, double ch,
    int tex_x,
    int sr, int sg, int sb,
    int fog, double tile_light, double perp,
    int fallback_tid,
    const int32_t *seg_tex_arr, const double *seg_ytop_arr,
    int seg_off, int n_segs,
    int num_tiles,
    const double *vscale,
    double cam_h,
    double plr, double plg_v, double plb)
{
    draw_segmented_column_ex(
        fb, sw, x, depth_px, atlas, ts, ts_mask,
        half, line_h, y0, y1, fh, ch, tex_x,
        sr, sg, sb, fog, tile_light, perp,
        fallback_tid, seg_tex_arr, seg_ytop_arr,
        seg_off, n_segs, num_tiles, vscale, cam_h, 0,
        NULL, 0,
        plr, plg_v, plb);
}

/* ═══════════════════════════════════════════════════════════════════
 *  Background fill
 * ═══════════════════════════════════════════════════════════════════ */

static void fill_background(uint8_t *fb, int sw, int sh, int half,
                             int is_interior,
                             const uint8_t *skybox, int sky_w, int sky_h,
                             double cam_angle, double cam_fov)
{
    /* Top half: sky texture (if available), gradient, or dark ceiling. */
    int sky_lim = half < sh ? half : sh;
    if (sky_lim < 0) sky_lim = 0;  /* clamp: half may be negative from extreme pitch */
    int half_ref = sh / 2;  /* stable reference for gradient */
    if (half_ref < 1) half_ref = 1;

    if (skybox && sky_w > 0 && sky_h > 0 && !is_interior) {
        /* Panoramic skybox: cylindrical UV mapping.
         * U = (cam_angle + column_angle) / (2*PI), wraps horizontally.
         * V = (y - 0) / sky_region_height, maps to texture V.          */
        double inv_2pi = 1.0 / (2.0 * M_PI);
        for (int y = 0; y < sky_lim; y++) {
            double v_norm = (double)y / (double)half_ref;
            if (v_norm > 1.0) v_norm = 1.0;
            int tv = (int)(v_norm * (sky_h - 1));
            if (tv < 0) tv = 0;
            if (tv >= sky_h) tv = sky_h - 1;
            for (int x = 0; x < sw; x++) {
                /* Column angle relative to camera centre */
                double col_frac = 2.0 * x / (double)sw - 1.0;
                double col_angle = atan2(col_frac * tan(cam_fov * 0.5), 1.0);
                double world_angle = cam_angle + col_angle;
                /* Wrap to [0, 2*PI) */
                double u_norm = world_angle * inv_2pi;
                u_norm -= floor(u_norm);
                int tu = (int)(u_norm * sky_w);
                if (tu < 0) tu = 0;
                if (tu >= sky_w) tu = sky_w - 1;
                int off = (tv * sky_w + tu) * 3;
                put_px(fb, sw, x, y, skybox[off], skybox[off+1], skybox[off+2]);
            }
        }
    } else {
        /* Fallback: procedural gradient */
        for (int y = 0; y < sky_lim; y++) {
            double t = (double)y / (double)half_ref;
            if (t > 1.0) t = 1.0;
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
    }

    /* Bottom half: dark ground default */
    int gnd_start = half < 0 ? 0 : half;  /* clamp: half may be negative */
    for (int y = gnd_start; y < sh; y++)
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
/* ═══════════════════════════════════════════════════════════════════
 *  portal_trace — lightweight secondary DDA for portal view
 *
 *  Cast a ray from (start_x, start_y) in direction (rdx, rdy) through
 *  the same zone's cell_solid grid.  Returns 1 if a solid wall is hit,
 *  populating output parameters.  Returns 0 if no hit within max_steps.
 *  Does NOT handle thin/transparent/deferred hits — walls only.
 * ═══════════════════════════════════════════════════════════════════ */
static int
portal_trace(int map_w, int map_h,
             double start_x, double start_y,
             double rdx, double rdy,
             const uint8_t *cell_solid,
             int max_steps,
             int *out_mx, int *out_my, int *out_side,
             int *out_step_x, int *out_step_y,
             double *out_perp)
{
    int mx = (int)start_x;
    int my = (int)start_y;

    double dd_x = fabs(rdx) > 1e-10 ? fabs(1.0 / rdx) : 1e10;
    double dd_y = fabs(rdy) > 1e-10 ? fabs(1.0 / rdy) : 1e10;

    int step_x, step_y;
    double sd_x, sd_y;

    if (rdx < 0) { step_x = -1; sd_x = (start_x - mx) * dd_x; }
    else          { step_x =  1; sd_x = (mx + 1.0 - start_x) * dd_x; }
    if (rdy < 0) { step_y = -1; sd_y = (start_y - my) * dd_y; }
    else          { step_y =  1; sd_y = (my + 1.0 - start_y) * dd_y; }

    int side = 0;
    for (int s = 0; s < max_steps; s++) {
        if (sd_x < sd_y) { sd_x += dd_x; mx += step_x; side = 0; }
        else              { sd_y += dd_y; my += step_y; side = 1; }

        if (mx < 0 || mx >= map_w || my < 0 || my >= map_h)
            return 0;

        int ci = my * map_w + mx;
        if (cell_solid[ci]) {
            *out_mx = mx;
            *out_my = my;
            *out_side = side;
            *out_step_x = step_x;
            *out_step_y = step_y;

            double perp;
            if (side == 0)
                perp = (mx - start_x + (1 - step_x) * 0.5) / rdx;
            else
                perp = (my - start_y + (1 - step_y) * 0.5) / rdy;
            if (perp < 0.001) perp = 0.001;
            *out_perp = perp;
            return 1;
        }
    }
    return 0;
}

static PyObject *
py_render_frame(PyObject *self, PyObject *dict)
{
    /* ── Parse arguments ─────────────────────────────────────────── */
    double cam_x, cam_y, cam_angle, cam_fov, cam_h;
    int horizon_shift;
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
    /* Wall-segment buffers (stacked textures per face) */
    Py_buffer seg_off_buf   = {0};   /* int32[map_h*map_w*4] */
    Py_buffer seg_cnt_buf   = {0};   /* int32[map_h*map_w*4] */
    Py_buffer seg_tex_buf   = {0};   /* int32[total_segs]    */
    Py_buffer seg_ytop_buf  = {0};   /* float64[total_segs]  */
    int n_total_segs = 0;
    Py_buffer vscale_buf    = {0};   /* float64[num_tiles]   */
    Py_buffer anim_buf       = {0};   /* int32[num_tiles*4]   */
    int anim_tick = 0;
    Py_buffer skybox_buf     = {0};   /* uint8[sky_h*sky_w*3] (optional) */
    int sky_w = 0, sky_h = 0;
    Py_buffer fog_den_buf    = {0};   /* float64[map_h*map_w] (optional) */
    Py_buffer fog_col_buf    = {0};   /* uint8[map_h*map_w*3] (optional) */
    Py_buffer lens_buf       = {0};   /* float64[sw] (optional)          */
    Py_buffer plight_buf     = {0};   /* float64[n_lights*8]  (optional) */
    int n_lights = 0;
    Py_buffer decal_buf      = {0};   /* float64[n_decals*8]  (optional) */
    int n_decals = 0;
    double bump_strength = 0.0;  /* 0 = disabled, 2-4 = subtle */
    Py_buffer quad_buf       = {0};   /* float64[n_quads*8]   (optional) */
    int n_quads = 0;
    Py_buffer box_buf        = {0};   /* float64[n_boxes*14]  (optional) */
    int n_boxes = 0;
    Py_buffer crv_buf        = {0};   /* float64[n_curves*9]  (optional) */
    int n_curves = 0;
    Py_buffer reflect_buf    = {0};   /* uint8[map_h*map_w]   (optional) */
    Py_buffer slope_buf      = {0};   /* float64[map_h*map_w*2] (optional) */
    /* Secondary floor/ceiling layer buffers (optional — multi-layer) */
    Py_buffer fh2_buf        = {0};   /* float64[map_h*map_w]   (optional) */
    Py_buffer ch2_buf        = {0};   /* float64[map_h*map_w]   (optional) */
    Py_buffer ftex2_buf      = {0};   /* int32[map_h*map_w]     (optional) */
    Py_buffer ctex2_buf      = {0};   /* int32[map_h*map_w]     (optional) */

    /* Portal rendering buffers */
    Py_buffer portal_map_buf = {0};   /* int32[map_h*map_w*4]   (optional) */
    Py_buffer portal_data_buf= {0};   /* float64[n_portals*PRT_STRIDE] */
    int n_portals = 0;

    /* Step-wall per-face texture buffers */
    Py_buffer fstep_tex_buf  = {0};  /* int32[map_h*map_w*4] */
    Py_buffer cstep_tex_buf  = {0};  /* int32[map_h*map_w*4] */
    Py_buffer uwh_buf        = {0};  /* float64[map_h*map_w] */
    /* Floor step segment buffers */
    Py_buffer fstep_seg_off_buf  = {0};
    Py_buffer fstep_seg_cnt_buf  = {0};
    Py_buffer fstep_seg_tex_buf  = {0};
    Py_buffer fstep_seg_ytop_buf = {0};
    int n_fstep_segs = 0;
    /* Ceiling step segment buffers */
    Py_buffer cstep_seg_off_buf  = {0};
    Py_buffer cstep_seg_cnt_buf  = {0};
    Py_buffer cstep_seg_tex_buf  = {0};
    Py_buffer cstep_seg_ytop_buf = {0};
    int n_cstep_segs = 0;

    PyObject *result = NULL;

    /* Heap allocations (need cleanup) */
    int         *w_top    = NULL;
    int         *w_bot    = NULL;
    double      *w_dist   = NULL;
    DeferredHit *deferred = NULL;
    int         *n_fstep  = NULL;   /* per-column floor step hit count */
    int         *n_cstep  = NULL;   /* per-column ceil  step hit count */
    StepWallHit *fstep_hits = NULL; /* floor step hits (sw * MAX_STEP_HITS) */
    StepWallHit *cstep_hits = NULL; /* ceil  step hits (sw * MAX_STEP_HITS) */
    double      *col_fog   = NULL;  /* per-column accumulated volume fog   */
    int         *n_def     = NULL;  /* per-column deferred hit count       */
    LightGrid    lgrid     = {0};   /* spatial index for point lights      */
    DecalGrid    dgrid     = {0};   /* spatial index for decals            */
    ShadowMap    smap      = {0};   /* per-light 2D visibility bitmap      */
    BoxGrid      bgrid     = {0};   /* spatial index for freeform boxes    */

    if (!PyDict_Check(dict)) {
        PyErr_SetString(PyExc_TypeError,
            "render_frame: argument must be a dict");
        return NULL;
    }

    /* ── Extract scalars ─────────────────────────────────────────── */
    if (dict_get_double(dict, "cam_x",     &cam_x))     goto cleanup;
    if (dict_get_double(dict, "cam_y",     &cam_y))     goto cleanup;
    if (dict_get_double(dict, "cam_angle", &cam_angle)) goto cleanup;
    if (dict_get_double(dict, "cam_fov",   &cam_fov))   goto cleanup;
    if (dict_get_double(dict, "cam_h",     &cam_h))     goto cleanup;
    if (dict_get_int(dict, "horizon_shift", &horizon_shift)) goto cleanup;
    if (dict_get_int(dict, "sw",           &sw))         goto cleanup;
    if (dict_get_int(dict, "sh",           &sh))         goto cleanup;
    if (dict_get_int(dict, "map_w",        &map_w))      goto cleanup;
    if (dict_get_int(dict, "map_h",        &map_h))      goto cleanup;
    if (dict_get_int(dict, "tex_size",     &tex_size))   goto cleanup;
    if (dict_get_int(dict, "num_tiles",    &num_tiles))  goto cleanup;
    if (dict_get_int(dict, "is_interior",  &is_interior)) goto cleanup;
    if (dict_get_int(dict, "n_overlay",    &n_overlay))  goto cleanup;
    if (dict_get_int(dict, "n_total_segs", &n_total_segs)) goto cleanup;
    if (dict_get_int(dict, "n_fstep_segs", &n_fstep_segs)) goto cleanup;
    if (dict_get_int(dict, "n_cstep_segs", &n_cstep_segs)) goto cleanup;
    if (dict_get_int(dict, "anim_tick",    &anim_tick))    goto cleanup;

    /* ── Optional skybox scalars/buffer (not required) ────────── */
    {
        PyObject *sk_o = PyDict_GetItemString(dict, "sky_w");
        if (sk_o) sky_w = (int)PyLong_AsLong(sk_o);
        sk_o = PyDict_GetItemString(dict, "sky_h");
        if (sk_o) sky_h = (int)PyLong_AsLong(sk_o);
        sk_o = PyDict_GetItemString(dict, "skybox");
        if (sk_o && sk_o != Py_None) {
            if (PyObject_GetBuffer(sk_o, &skybox_buf, 0) < 0)
                goto cleanup;
        }
    }
    /* ── Optional fog-volume buffers ──────────────────────────── */
    {
        PyObject *fd_o = PyDict_GetItemString(dict, "fog_density");
        if (fd_o && fd_o != Py_None) {
            if (PyObject_GetBuffer(fd_o, &fog_den_buf, 0) < 0)
                goto cleanup;
        }
        fd_o = PyDict_GetItemString(dict, "fog_color");
        if (fd_o && fd_o != Py_None) {
            if (PyObject_GetBuffer(fd_o, &fog_col_buf, 0) < 0)
                goto cleanup;
        }
    }
    /* ── Optional lens distortion buffer ───────────────────────── */
    {
        PyObject *ln_o = PyDict_GetItemString(dict, "lens");
        if (ln_o && ln_o != Py_None) {
            if (PyObject_GetBuffer(ln_o, &lens_buf, 0) < 0)
                goto cleanup;
        }
    }
    /* ── Optional point lights buffer ─────────────────────────── */
    {
        PyObject *pl_o = PyDict_GetItemString(dict, "n_lights");
        if (pl_o) n_lights = (int)PyLong_AsLong(pl_o);
        pl_o = PyDict_GetItemString(dict, "point_lights");
        if (pl_o && pl_o != Py_None && n_lights > 0) {
            if (PyObject_GetBuffer(pl_o, &plight_buf, 0) < 0)
                goto cleanup;
        }
    }
    /* ── Optional decal overlay buffer ────────────────────────── */
    {
        PyObject *dc_o = PyDict_GetItemString(dict, "n_decals");
        if (dc_o) n_decals = (int)PyLong_AsLong(dc_o);
        dc_o = PyDict_GetItemString(dict, "decals");
        if (dc_o && dc_o != Py_None && n_decals > 0) {
            if (PyObject_GetBuffer(dc_o, &decal_buf, 0) < 0)
                goto cleanup;
        }
    }
    /* ── Optional bump mapping strength ──────────────────────── */
    {
        PyObject *bs_o = PyDict_GetItemString(dict, "bump_strength");
        if (bs_o) bump_strength = PyFloat_AsDouble(bs_o);
    }
    /* ── Optional quad buffer (two-sided quads) ──────────────── */
    {
        PyObject *qd_o = PyDict_GetItemString(dict, "n_quads");
        if (qd_o) n_quads = (int)PyLong_AsLong(qd_o);
        qd_o = PyDict_GetItemString(dict, "quad_data");
        if (qd_o && qd_o != Py_None && n_quads > 0) {
            if (PyObject_GetBuffer(qd_o, &quad_buf, 0) < 0)
                goto cleanup;
        }
    }
    /* ── Optional freeform box buffer ────────────────────────── */
    {
        PyObject *bx_o = PyDict_GetItemString(dict, "n_boxes");
        if (bx_o) n_boxes = (int)PyLong_AsLong(bx_o);
        bx_o = PyDict_GetItemString(dict, "box_data");
        if (bx_o && bx_o != Py_None && n_boxes > 0) {
            if (PyObject_GetBuffer(bx_o, &box_buf, 0) < 0)
                goto cleanup;
        }
    }
    /* ── Optional curved wall (arc) buffer ───────────────────── */
    {
        PyObject *cv_o = PyDict_GetItemString(dict, "n_curves");
        if (cv_o) n_curves = (int)PyLong_AsLong(cv_o);
        cv_o = PyDict_GetItemString(dict, "curve_data");
        if (cv_o && cv_o != Py_None && n_curves > 0) {
            if (PyObject_GetBuffer(cv_o, &crv_buf, 0) < 0)
                goto cleanup;
        }
    }

    /* ── Optional: per-cell reflection flags (uint8[map_h*map_w]) ── */
    {
        PyObject *rf_o = PyDict_GetItemString(dict, "reflect_flags");
        if (rf_o && rf_o != Py_None) {
            if (PyObject_GetBuffer(rf_o, &reflect_buf, 0) < 0)
                goto cleanup;
        }
    }

    /* ── Optional: per-cell floor/ceiling slope (float64[map_h*map_w*2]) ── */
    {
        PyObject *sl_o = PyDict_GetItemString(dict, "slope_data");
        if (sl_o && sl_o != Py_None) {
            if (PyObject_GetBuffer(sl_o, &slope_buf, 0) < 0)
                goto cleanup;
        }
    }

    /* ── Optional: secondary floor/ceiling layer buffers ─────────── */
    {
        PyObject *o;
        o = PyDict_GetItemString(dict, "fheight2");
        if (o && o != Py_None) {
            if (PyObject_GetBuffer(o, &fh2_buf, 0) < 0) goto cleanup;
        }
        o = PyDict_GetItemString(dict, "cheight2");
        if (o && o != Py_None) {
            if (PyObject_GetBuffer(o, &ch2_buf, 0) < 0) goto cleanup;
        }
        o = PyDict_GetItemString(dict, "ftex2");
        if (o && o != Py_None) {
            if (PyObject_GetBuffer(o, &ftex2_buf, 0) < 0) goto cleanup;
        }
        o = PyDict_GetItemString(dict, "ctex2");
        if (o && o != Py_None) {
            if (PyObject_GetBuffer(o, &ctex2_buf, 0) < 0) goto cleanup;
        }
    }

    /* ── Optional: portal rendering buffers ──────────────────────── */
    {
        PyObject *o;
        o = PyDict_GetItemString(dict, "portal_map");
        if (o && o != Py_None) {
            if (PyObject_GetBuffer(o, &portal_map_buf, 0) < 0) goto cleanup;
        }
        o = PyDict_GetItemString(dict, "portal_data");
        if (o && o != Py_None) {
            if (PyObject_GetBuffer(o, &portal_data_buf, 0) < 0) goto cleanup;
        }
        o = PyDict_GetItemString(dict, "n_portals");
        if (o && o != Py_None) {
            n_portals = (int)PyLong_AsLong(o);
        }
    }

    /* ── Extract writable buffers ────────────────────────────────── */
    if (dict_get_buf(dict, "fb",       &fb_buf,       1)) goto cleanup;
    if (dict_get_buf(dict, "zbuf",     &zbuf_buf,     1)) goto cleanup;
    if (dict_get_buf(dict, "depth_px", &depth_px_buf, 1)) goto cleanup;

    /* ── Extract read-only buffers ───────────────────────────────── */
    if (dict_get_buf(dict, "tiles",     &tiles_buf,     0)) goto cleanup;
    if (dict_get_buf(dict, "walls",     &wall_buf,      0)) goto cleanup;
    if (dict_get_buf(dict, "atlas",     &atlas_buf,     0)) goto cleanup;
    if (dict_get_buf(dict, "fog_lut",   &fog_buf,       0)) goto cleanup;
    if (dict_get_buf(dict, "floor_h",   &fh_buf,        0)) goto cleanup;
    if (dict_get_buf(dict, "ceil_h",    &ch_buf,        0)) goto cleanup;
    if (dict_get_buf(dict, "floor_tex", &ft_buf,        0)) goto cleanup;
    if (dict_get_buf(dict, "ceil_tex",  &ct_buf,        0)) goto cleanup;
    if (dict_get_buf(dict, "thin_lut",  &thin_buf,      0)) goto cleanup;
    if (dict_get_buf(dict, "tall_lut",  &tall_buf,      0)) goto cleanup;
    if (dict_get_buf(dict, "hs_lut",    &hs_buf,        0)) goto cleanup;
    if (dict_get_buf(dict, "face_tex",  &ftex_grid_buf, 0)) goto cleanup;
    if (dict_get_buf(dict, "light",     &light_buf,     0)) goto cleanup;
    if (dict_get_buf(dict, "alt_tex",   &alt_tex_buf,   0)) goto cleanup;
    if (dict_get_buf(dict, "trans_lut", &trans_buf,     0)) goto cleanup;
    if (dict_get_buf(dict, "overlay",   &overlay_buf,   0)) goto cleanup;
    if (dict_get_buf(dict, "vscale",    &vscale_buf,    0)) goto cleanup;
    if (dict_get_buf(dict, "anim_lut",  &anim_buf,      0)) goto cleanup;
    /* Wall-segment buffers */
    if (dict_get_buf(dict, "seg_off",   &seg_off_buf,   0)) goto cleanup;
    if (dict_get_buf(dict, "seg_cnt",   &seg_cnt_buf,   0)) goto cleanup;
    if (dict_get_buf(dict, "seg_tex",   &seg_tex_buf,   0)) goto cleanup;
    if (dict_get_buf(dict, "seg_ytop",  &seg_ytop_buf,  0)) goto cleanup;
    /* Step-wall buffers */
    if (dict_get_buf(dict, "fstep_tex", &fstep_tex_buf, 0)) goto cleanup;
    if (dict_get_buf(dict, "cstep_tex", &cstep_tex_buf, 0)) goto cleanup;
    if (dict_get_buf(dict, "uwh",       &uwh_buf,       0)) goto cleanup;
    /* Floor step segment buffers */
    if (dict_get_buf(dict, "fstep_seg_off",  &fstep_seg_off_buf,  0)) goto cleanup;
    if (dict_get_buf(dict, "fstep_seg_cnt",  &fstep_seg_cnt_buf,  0)) goto cleanup;
    if (dict_get_buf(dict, "fstep_seg_tex",  &fstep_seg_tex_buf,  0)) goto cleanup;
    if (dict_get_buf(dict, "fstep_seg_ytop", &fstep_seg_ytop_buf, 0)) goto cleanup;
    /* Ceiling step segment buffers */
    if (dict_get_buf(dict, "cstep_seg_off",  &cstep_seg_off_buf,  0)) goto cleanup;
    if (dict_get_buf(dict, "cstep_seg_cnt",  &cstep_seg_cnt_buf,  0)) goto cleanup;
    if (dict_get_buf(dict, "cstep_seg_tex",  &cstep_seg_tex_buf,  0)) goto cleanup;
    if (dict_get_buf(dict, "cstep_seg_ytop", &cstep_seg_ytop_buf, 0)) goto cleanup;
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
    const uint8_t *cell_solid = (const uint8_t *)wall_buf.buf;
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
    const double  *fog_den    = (fog_den_buf.buf
                               && fog_den_buf.len >= (Py_ssize_t)(map_h * map_w * (int)sizeof(double)))
                             ? (const double *)fog_den_buf.buf : NULL;
    const uint8_t *fog_col    = (fog_col_buf.buf
                               && fog_col_buf.len >= (Py_ssize_t)(map_h * map_w * 3))
                             ? (const uint8_t *)fog_col_buf.buf : NULL;
    const double  *lens       = (lens_buf.buf
                               && lens_buf.len >= (Py_ssize_t)(sw * (int)sizeof(double)))
                              ? (const double *)lens_buf.buf : NULL;
    const double  *plights    = (plight_buf.buf
                               && plight_buf.len >= (Py_ssize_t)(n_lights * PL_STRIDE * (int)sizeof(double)))
                              ? (const double *)plight_buf.buf : NULL;
    const double  *decals     = (decal_buf.buf
                               && decal_buf.len >= (Py_ssize_t)(n_decals * DC_STRIDE * (int)sizeof(double)))
                              ? (const double *)decal_buf.buf : NULL;
    const double  *quad_data  = (quad_buf.buf
                               && quad_buf.len >= (Py_ssize_t)(n_quads * QD_STRIDE * (int)sizeof(double)))
                              ? (const double *)quad_buf.buf : NULL;
    const double  *box_data   = (box_buf.buf
                               && box_buf.len >= (Py_ssize_t)(n_boxes * BX_STRIDE * (int)sizeof(double)))
                              ? (const double *)box_buf.buf : NULL;
    const double  *crv_data  = (crv_buf.buf
                               && crv_buf.len >= (Py_ssize_t)(n_curves * CRV_STRIDE * (int)sizeof(double)))
                              ? (const double *)crv_buf.buf : NULL;
    const uint8_t *reflect_flags = (reflect_buf.buf
                               && reflect_buf.len >= (Py_ssize_t)(map_h * map_w))
                              ? (const uint8_t *)reflect_buf.buf : NULL;
    const double  *slope_data = (slope_buf.buf
                               && slope_buf.len >= (Py_ssize_t)(map_h * map_w * 2 * (int)sizeof(double)))
                              ? (const double *)slope_buf.buf : NULL;
    /* Secondary layer aliases (optional — multi-layer) */
    const double  *fh2 = (fh2_buf.buf
                          && fh2_buf.len >= (Py_ssize_t)(map_h * map_w * (int)sizeof(double)))
                         ? (const double *)fh2_buf.buf : NULL;
    const double  *ch2 = (ch2_buf.buf
                          && ch2_buf.len >= (Py_ssize_t)(map_h * map_w * (int)sizeof(double)))
                         ? (const double *)ch2_buf.buf : NULL;
    const int32_t *ftex2 = (ftex2_buf.buf
                            && ftex2_buf.len >= (Py_ssize_t)(map_h * map_w * (int)sizeof(int32_t)))
                           ? (const int32_t *)ftex2_buf.buf : NULL;
    const int32_t *ctex2 = (ctex2_buf.buf
                            && ctex2_buf.len >= (Py_ssize_t)(map_h * map_w * (int)sizeof(int32_t)))
                           ? (const int32_t *)ctex2_buf.buf : NULL;

    /* Portal pointer aliases */
    const int32_t *portal_map = (portal_map_buf.buf
                                 && portal_map_buf.len >= (Py_ssize_t)(map_h * map_w * 4 * (int)sizeof(int32_t)))
                                ? (const int32_t *)portal_map_buf.buf : NULL;
    const double  *portal_data = (portal_data_buf.buf
                                  && n_portals > 0
                                  && portal_data_buf.len >= (Py_ssize_t)(n_portals * PRT_STRIDE * (int)sizeof(double)))
                                 ? (const double *)portal_data_buf.buf : NULL;

    /* Wall-segment pointer aliases */
    const int32_t *seg_off   = (const int32_t *)seg_off_buf.buf;
    const int32_t *seg_cnt   = (const int32_t *)seg_cnt_buf.buf;
    const int32_t *seg_tex   = (seg_tex_buf.len >= (Py_ssize_t)sizeof(int32_t))
                             ? (const int32_t *)seg_tex_buf.buf : NULL;
    const double  *seg_ytop  = (seg_ytop_buf.len >= (Py_ssize_t)sizeof(double))
                             ? (const double *)seg_ytop_buf.buf : NULL;
    const double  *vscale    = (const double *)vscale_buf.buf;
    const int32_t *anim_lt   = (anim_buf.len >= (Py_ssize_t)(num_tiles * 4 * (int)sizeof(int32_t)))
                             ? (const int32_t *)anim_buf.buf : NULL;
    const uint8_t *skybox_data = (skybox_buf.buf && skybox_buf.len >= (Py_ssize_t)(sky_w * sky_h * 3))
                               ? (const uint8_t *)skybox_buf.buf : NULL;

    /* Step-wall pointer aliases */
    const int32_t *fstep_tex = (const int32_t *)fstep_tex_buf.buf;
    const int32_t *cstep_tex = (const int32_t *)cstep_tex_buf.buf;
    const double  *uwh       = (const double *) uwh_buf.buf;
    /* Floor step segment pointer aliases */
    const int32_t *fstep_seg_off  = (const int32_t *)fstep_seg_off_buf.buf;
    const int32_t *fstep_seg_cnt  = (const int32_t *)fstep_seg_cnt_buf.buf;
    const int32_t *fstep_seg_tex  = (fstep_seg_tex_buf.len >= (Py_ssize_t)sizeof(int32_t))
                                  ? (const int32_t *)fstep_seg_tex_buf.buf : NULL;
    const double  *fstep_seg_ytop = (fstep_seg_ytop_buf.len >= (Py_ssize_t)sizeof(double))
                                  ? (const double *)fstep_seg_ytop_buf.buf : NULL;
    /* Ceiling step segment pointer aliases */
    const int32_t *cstep_seg_off  = (const int32_t *)cstep_seg_off_buf.buf;
    const int32_t *cstep_seg_cnt  = (const int32_t *)cstep_seg_cnt_buf.buf;
    const int32_t *cstep_seg_tex  = (cstep_seg_tex_buf.len >= (Py_ssize_t)sizeof(int32_t))
                                  ? (const int32_t *)cstep_seg_tex_buf.buf : NULL;
    const double  *cstep_seg_ytop = (cstep_seg_ytop_buf.len >= (Py_ssize_t)sizeof(double))
                                  ? (const double *)cstep_seg_ytop_buf.buf : NULL;

    const int half     = sh / 2 + horizon_shift;
    const int ts       = tex_size;
    const int ts_mask  = ts - 1;           /* assumes power-of-2  */
    const int map_size = map_h * map_w;
    const int lut_len  = num_tiles;

    /* Runtime camera height (replaces the old CAM_H #define) */
    const double CAM_H = cam_h;

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
    n_fstep    = (int *)        calloc(sw, sizeof(int));
    n_cstep    = (int *)        calloc(sw, sizeof(int));
    fstep_hits = (StepWallHit *)malloc(sw * MAX_STEP_HITS * sizeof(StepWallHit));
    cstep_hits = (StepWallHit *)malloc(sw * MAX_STEP_HITS * sizeof(StepWallHit));
    col_fog    = (double *)     calloc(sw, sizeof(double));
    if (!w_top || !w_bot || !w_dist || !deferred
        || !n_fstep || !n_cstep || !fstep_hits || !cstep_hits || !col_fog) {
        PyErr_NoMemory();
        goto cleanup;
    }

    /* Build spatial index for point lights (optional) */
    if (plights && n_lights > 0) {
        build_light_grid(&lgrid, plights, n_lights, map_w, map_h);
        build_shadow_maps(&smap, plights, n_lights,
                          cell_solid, map_w, map_h);
    }
    if (decals && n_decals > 0)
        build_decal_grid(&dgrid, decals, n_decals, map_w, map_h);
    if (box_data && n_boxes > 0)
        build_box_grid(&bgrid, box_data, n_boxes, map_w, map_h);

    /* Default: no wall hit — use extremes so step walls are not
     * falsely clipped when no Phase 1 wall occludes the column.
     * Phase 2 floor sweep starts at half+1 (always > -1) and
     * Phase 3 ceiling sweep starts at half-1 (always < sh), so
     * these values have no effect on the horizontal sweeps.      */
    int *n_def = (int *)calloc(sw, sizeof(int));
    if (!n_def) { PyErr_NoMemory(); goto cleanup; }
    for (int i = 0; i < sw; i++) {
        w_top[i]  = sh;
        w_bot[i]  = -1;
        w_dist[i] = MAX_DEPTH;
    }
    int n_deferred = 0;  /* set after Phase 1 compaction */

    /* ── PHASE 0: Background fill ────────────────────────────────── */
    fill_background(fb, sw, sh, half, is_interior,
                    skybox_data, sky_w, sky_h, cam_angle, cam_fov);

    /* Initialize per-pixel depth to MAX_DEPTH */
    for (int i = 0; i < sw * sh; i++) depth_px[i] = (float)MAX_DEPTH;

    /* ── Camera cell ceiling/floor for occlusion clipping ────── */
    int cam_cell_ci = clampi((int)cam_y, 0, map_h - 1) * map_w
                    + clampi((int)cam_x, 0, map_w - 1);
    double cam_cell_ch = cheight[cam_cell_ci];
    if (cam_cell_ch >= SKY_THRESHOLD || cam_cell_ch < 0.0)
        cam_cell_ch = 1e6;
    double cam_cell_fh = fheight[cam_cell_ci];
    (void)cam_cell_ci; /* used below in per-column init */

    /* ══════════════════════════════════════════════════════════════
     *  PHASE 1 — WALLS  (DDA with half/transparent/thin/tall support)
     * ══════════════════════════════════════════════════════════════ */
#ifdef _OPENMP
    #pragma omp parallel for schedule(dynamic, 8)
#endif
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

        /* ── Per-column screen-space occlusion tracking ─────── */
        /* As the ray walks through cells, project each cell's
         * ceiling / floor at ITS OWN distance to get a screen-Y
         * clip.  This correctly handles ceiling transitions (e.g.
         * ch=0.95 → ch=2.0) without projection errors.          */
        int ray_clip_top = 0;           /* screen-Y: wall hidden above */
        int ray_clip_bot = sh - 1;      /* screen-Y: wall hidden below */
        double prev_ch = cam_cell_ch;   /* ceiling of previous cell    */
        double prev_fh = cam_cell_fh;   /* floor  of previous cell     */

        /* DDA loop — multi-type wall detection */
        int hit = 0, side = 0;
        int n_short_col = 0;
        int prev_ci = cam_cell_ci;
        double fog_accum = 0.0;   /* accumulated volume fog for this column */
        double prev_bp   = 0.0;   /* boundary dist of previous DDA step     */

        /* Portal per-column state */
        int is_portal_col = 0;
        double portal_wall_frac = 0.0;
        double portal_hit_wx = 0.0, portal_hit_wy = 0.0;

        for (int s = 0; s < MAX_STEPS; s++) {
            if (sd_x < sd_y) { sd_x += dd_x; mx += step_x; side = 0; }
            else              { sd_y += dd_y; my += step_y; side = 1; }

            if (mx < 0 || mx >= map_w || my < 0 || my >= map_h)
                break;

            /* ── Boundary perpendicular distance (used for
             *    ray-clip projection and step-wall collection). */
            double bp;
            if (side == 0)
                bp = (mx - cam_x + (1 - step_x) * 0.5) / rdx;
            else
                bp = (my - cam_y + (1 - step_y) * 0.5) / rdy;
            if (bp < 0.001) bp = 0.001;

            /* ── Project previous cell's ceiling/floor at this
             *    cell boundary (the distance where prev cell ends).
             *
             *    Ceiling clip: only when prev_ch > CAM_H (ceiling
             *    is ABOVE the camera).  When the camera is above
             *    the intervening ceiling, the ceiling surface is
             *    below us and does NOT occlude the upper portion
             *    of walls behind — we can see over it.
             *
             *    Floor clip: only when prev_fh < CAM_H (floor is
             *    BELOW the camera).  When the camera is below an
             *    elevated floor, the floor is above us and does NOT
             *    occlude the lower portion of walls behind.        */
            {
                int bl = (int)((double)sh / bp);
                if (bl < 1) bl = 1;
                if (prev_ch < SKY_THRESHOLD && prev_ch > CAM_H) {
                    int cy = (int)(half - bl * (prev_ch - CAM_H));
                    if (cy > ray_clip_top) ray_clip_top = cy;
                }
                if (prev_fh < CAM_H) {
                    int fy = (int)(half + bl * (CAM_H - prev_fh));
                    if (fy < ray_clip_bot) ray_clip_bot = fy;
                }
            }

            /* ── Geometry-based wall detection ─────────────── */
            /* cell_solid is a per-cell byte array (1 = solid,
             * 0 = passable).  Computed in Python from floor/ceil
             * heights and tile types.  Replaces the old per-tile
             * wall_lt[tid] lookup.                                */
            int cur_ci = my * map_w + mx;

            /* ── Accumulate fog volume through this cell ────── */
            if (fog_den) {
                double step_len = bp - prev_bp;
                if (step_len < 0.0) step_len = 0.0;
                fog_accum += fog_den[cur_ci] * step_len;
            }
            prev_bp = bp;

            if (!cell_solid[cur_ci]) {
                /* ── Non-solid cell ────────────────────────────── */
                /* Check for thin / transparent tiles that need
                 * deferred rendering even in passable cells.      */
                int tid = tiles[cur_ci];
                if (tid >= 0 && tid < lut_len) {
                    /* Thin wall: mid-cell intersection, defer */
                    if (thin_lt[tid] && n_def[x] < MAX_DEF_PER_COL) {
                        double perp;
                        if (side == 0)
                            perp = (mx - cam_x + (1 - step_x) * 0.5) / rdx;
                        else
                            perp = (my - cam_y + (1 - step_y) * 0.5) / rdy;
                        if (perp < 0.001) perp = 0.001;
                        int cur_face = detect_face(side, step_x, step_y);
                        double mid_p;
                        if (side == 0) mid_p = (mx + 0.5 - cam_x) / rdx;
                        else           mid_p = (my + 0.5 - cam_y) / rdy;
                        if (mid_p > 0.001) {
                            double wf;
                            if (side == 0) wf = cam_y + mid_p * rdy;
                            else           wf = cam_x + mid_p * rdx;
                            wf -= floor(wf);
                            DeferredHit *dh = &deferred[x * MAX_DEF_PER_COL + n_def[x]++];
                            dh->col       = x;
                            dh->dist      = mid_p;
                            dh->tid       = tid;
                            dh->ci        = cur_ci;
                            dh->side      = side;
                            dh->face      = cur_face;
                            dh->wall_frac = wf;
                            dh->hs        = hs_arr[tid];
                            dh->base_y    = -1e9;
                            n_short_col++;
                        }
                    }
                    /* Transparent wall: defer and continue */
                    else if (trans_lt[tid] && n_def[x] < MAX_DEF_PER_COL) {
                        double perp;
                        if (side == 0)
                            perp = (mx - cam_x + (1 - step_x) * 0.5) / rdx;
                        else
                            perp = (my - cam_y + (1 - step_y) * 0.5) / rdy;
                        if (perp < 0.001) perp = 0.001;
                        double wfrac;
                        if (side == 0) wfrac = cam_y + perp * rdy;
                        else           wfrac = cam_x + perp * rdx;
                        wfrac -= floor(wfrac);
                        int cur_face = detect_face(side, step_x, step_y);
                        DeferredHit *dh = &deferred[x * MAX_DEF_PER_COL + n_def[x]++];
                        dh->col       = x;
                        dh->dist      = perp;
                        dh->tid       = tid;
                        dh->ci        = cur_ci;
                        dh->side      = side;
                        dh->face      = cur_face;
                        dh->wall_frac = wfrac;
                        dh->hs        = hs_arr[tid];
                        dh->base_y    = -1e9;
                    }
                }
                /* Update prev ceiling/floor for next cell */
                {
                    double cfh_local = fheight[cur_ci];
                    double cch_local = cheight[cur_ci];

                    /* ── Collect step-wall transitions (single DDA) ── */
                    /* Floor height transition */
                    if (fabs(cfh_local - prev_fh) > TIER_TOL
                        && n_fstep[x] < MAX_STEP_HITS) {
                        double wf;
                        if (side == 0) wf = cam_y + bp * rdy;
                        else           wf = cam_x + bp * rdx;
                        wf -= floor(wf);
                        StepWallHit *swh = &fstep_hits[
                            x * MAX_STEP_HITS + n_fstep[x]++];
                        swh->perp      = bp;
                        swh->wall_frac = wf;
                        swh->pfh       = prev_fh;
                        swh->cfh       = cfh_local;
                        swh->pci       = prev_ci;
                        swh->ci        = cur_ci;
                        swh->sd        = side;
                        swh->ssx       = step_x;
                        swh->ssy       = step_y;
                    }
                    /* Ceiling height transition — include upper_wall_height
                     * so that two cells with the same ch but different uwh
                     * still produce a visible step face.                    */
                    if (cch_local < SKY_THRESHOLD
                        && prev_ch < SKY_THRESHOLD
                        && n_cstep[x] < MAX_STEP_HITS) {
                        double eff_prev = prev_ch;
                        double eff_cur  = cch_local;
                        {
                            double uwh_p = uwh[prev_ci];
                            if (uwh_p > prev_ch) eff_prev = uwh_p;
                        }
                        {
                            double uwh_c = uwh[cur_ci];
                            if (uwh_c > cch_local) eff_cur = uwh_c;
                        }
                        if (fabs(eff_cur - eff_prev) > TIER_TOL) {
                            double wf;
                            if (side == 0) wf = cam_y + bp * rdy;
                            else           wf = cam_x + bp * rdx;
                            wf -= floor(wf);
                            StepWallHit *swh = &cstep_hits[
                                x * MAX_STEP_HITS + n_cstep[x]++];
                            swh->perp      = bp;
                            swh->wall_frac = wf;
                            swh->pfh       = eff_prev;
                            swh->cfh       = eff_cur;
                            swh->pci       = prev_ci;
                            swh->ci        = cur_ci;
                            swh->sd        = side;
                            swh->ssx       = step_x;
                            swh->ssy       = step_y;
                        }
                    }
                    /* Sky-boundary ceiling step: one cell is sky, the
                     * other has a ceiling with upper wall.  Emit a step
                     * from ch to uwh so the upper-wall face is visible. */
                    else if (n_cstep[x] < MAX_STEP_HITS) {
                        int prev_sky = (prev_ch >= SKY_THRESHOLD);
                        int cur_sky  = (cch_local >= SKY_THRESHOLD);
                        if (prev_sky != cur_sky) {
                            int    c_ci = prev_sky ? cur_ci  : prev_ci;
                            double c_ch = prev_sky ? cch_local : prev_ch;
                            double c_uwh = uwh[c_ci];
                            if (c_uwh > c_ch + TIER_TOL) {
                                double wf;
                                if (side == 0) wf = cam_y + bp * rdy;
                                else           wf = cam_x + bp * rdx;
                                wf -= floor(wf);
                                StepWallHit *swh = &cstep_hits[
                                    x * MAX_STEP_HITS + n_cstep[x]++];
                                swh->perp      = bp;
                                swh->wall_frac = wf;
                                swh->pfh       = c_ch;
                                swh->cfh       = c_uwh;
                                swh->pci       = prev_ci;
                                swh->ci        = cur_ci;
                                swh->sd        = side;
                                swh->ssx       = step_x;
                                swh->ssy       = step_y;
                            }
                        }
                    }

                    prev_ci = cur_ci;
                    prev_ch = cch_local;
                    prev_fh = cfh_local;
                }
                continue;
            }

            /* ── Solid cell — collect step wall at boundary, then stop ── */
            /* Floor height transition into the solid cell */
            {
                double sfh = fheight[cur_ci];
                if (fabs(sfh - prev_fh) > TIER_TOL
                    && n_fstep[x] < MAX_STEP_HITS) {
                    double wf;
                    if (side == 0) wf = cam_y + bp * rdy;
                    else           wf = cam_x + bp * rdx;
                    wf -= floor(wf);
                    StepWallHit *swh = &fstep_hits[
                        x * MAX_STEP_HITS + n_fstep[x]++];
                    swh->perp      = bp;
                    swh->wall_frac = wf;
                    swh->pfh       = prev_fh;
                    swh->cfh       = sfh;
                    swh->pci       = prev_ci;
                    swh->ci        = cur_ci;
                    swh->sd        = side;
                    swh->ssx       = step_x;
                    swh->ssy       = step_y;
                }
            }
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

            /* ── Portal face check ─────────────────────────────── */
            /* If the hit wall face has a portal, cast a secondary
             * ray from the portal destination and replace the wall
             * hit with the remote geometry.                        */
            if (portal_map && portal_data) {
                int pface = detect_face(side, step_x, step_y);
                int pci   = my * map_w + mx;
                int pidx  = portal_map[pci * 4 + pface];
                if (pidx >= 0 && pidx < n_portals) {
                    double dst_x = portal_data[pidx * PRT_STRIDE + PRT_DST_X];
                    double dst_y = portal_data[pidx * PRT_STRIDE + PRT_DST_Y];
                    double cos_a = portal_data[pidx * PRT_STRIDE + PRT_D_ANGX];
                    double sin_a = portal_data[pidx * PRT_STRIDE + PRT_D_ANGY];
                    double nrdx = rdx * cos_a - rdy * sin_a;
                    double nrdy = rdx * sin_a + rdy * cos_a;

                    int pmx, pmy, pside, psx, psy;
                    double pperp;
                    if (portal_trace(map_w, map_h, dst_x, dst_y,
                                     nrdx, nrdy, cell_solid, MAX_STEPS,
                                     &pmx, &pmy, &pside, &psx, &psy,
                                     &pperp)) {
                        /* Replace hit with portal destination wall */
                        mx = pmx; my = pmy; side = pside;
                        step_x = psx; step_y = psy;
                        w_dist[x] = pre_perp + pperp;

                        /* Pre-compute wall_frac + world hit pos */
                        double wf;
                        if (pside == 0) wf = dst_y + pperp * nrdy;
                        else            wf = dst_x + pperp * nrdx;
                        portal_wall_frac = wf - floor(wf);
                        portal_hit_wx = dst_x + pperp * nrdx;
                        portal_hit_wy = dst_y + pperp * nrdy;
                        is_portal_col = 1;
                    }
                }
            }
        }

        /* ── Overlay wall intersections (non-grid-aligned segments) ── */
        /* Test each column's ray against all overlay wall segments.
         * Hits are added to the deferred list for compositing in Phase 4.
         * Uses 2D ray-segment intersection: P + t*D vs A + u*(B-A).      */
        for (int ow = 0; ow < n_overlay && n_def[x] < MAX_DEF_PER_COL; ow++) {
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

            DeferredHit *dh = &deferred[x * MAX_DEF_PER_COL + n_def[x]++];
            dh->col       = x;
            dh->dist      = ov_t;
            dh->tid       = (otid >= 0 && otid < num_tiles) ? otid : 0;
            dh->ci        = oci;
            dh->side      = ov_side;
            dh->face      = 0;
            dh->wall_frac = wfrac;
            dh->hs        = ohs;
            dh->base_y    = -1e9;
        }

        /* ── Quad intersections (two-sided thin decals / fences) ── */
        /* Each column's ray is tested against all quads.  Hits are
         * deferred like overlays, with base_y for custom Z anchor. */
        for (int qi = 0; qi < n_quads && quad_data && n_def[x] < MAX_DEF_PER_COL; qi++) {
            const double *Q = quad_data + qi * QD_STRIDE;
            double qx1 = Q[QD_X1], qy1 = Q[QD_Y1];
            double qx2 = Q[QD_X2], qy2 = Q[QD_Y2];
            int    qflags = (int)Q[QD_FLAGS];

            double sdx_q = qx2 - qx1;
            double sdy_q = qy2 - qy1;
            double denom = rdx * sdy_q - rdy * sdx_q;

            /* One-sided back-face cull: skip if ray hits the back.
             * Normal of segment points in the direction (-sdy_q, sdx_q).
             * If dot(normal, ray_dir) >= 0 the ray approaches from the
             * back side.  Two-sided quads skip this test.              */
            if (!(qflags & QD_FLAG_TWO_SIDED)) {
                double ndot = (-sdy_q) * rdx + sdx_q * rdy;
                if (ndot >= 0.0) continue;
            }

            if (fabs(denom) < 1e-10) continue;  /* parallel */

            double apx = qx1 - cam_x;
            double apy = qy1 - cam_y;
            double qt = (apx * sdy_q - apy * sdx_q) / denom;
            double qu = (apx * rdy   - apy * rdx)   / denom;

            if (qt < 0.001 || qu < 0.0 || qu > 1.0) continue;
            if (qt >= w_dist[x]) continue;  /* behind primary wall */

            /* Texture U: tile along segment length */
            double seg_len = sqrt(sdx_q * sdx_q + sdy_q * sdy_q);
            double along   = qu * seg_len;
            double wfrac_q = along - floor(along);

            /* Side shading based on segment orientation */
            int q_side = (fabs(sdx_q) >= fabs(sdy_q)) ? 1 : 0;

            /* Cell index at hit point */
            double hx  = cam_x + qt * rdx;
            double hy  = cam_y + qt * rdy;
            int    hcx = (int)floor(hx);
            int    hcy = (int)floor(hy);
            int    qci = -1;
            if (hcx >= 0 && hcx < map_w && hcy >= 0 && hcy < map_h)
                qci = hcy * map_w + hcx;

            int qtid = (int)Q[QD_TID];

            DeferredHit *qdh = &deferred[x * MAX_DEF_PER_COL + n_def[x]++];
            qdh->col       = x;
            qdh->dist      = qt;
            qdh->tid       = (qtid >= 0 && qtid < num_tiles) ? qtid : 0;
            qdh->ci        = qci;
            qdh->side      = q_side;
            qdh->face      = 0;
            qdh->wall_frac = wfrac_q;
            qdh->hs        = Q[QD_HEIGHT];
            qdh->base_y    = Q[QD_BASE_Y];
        }

        /* ── Freeform box intersections (OBB ray-slab) ────────── */
        /* Test the ray against all boxes that overlap the current
         * column's path.  Uses 2D ray-slab intersection in box-local
         * space (rotated by -yaw).  Each hit pushes a DeferredHit
         * with the struck face's texture and correct UV/base_y.     */
        if (box_data && bgrid.n_cell_boxes) {
            /* Gather unique boxes from all cells the ray has passed */
            /* For simplicity, check ALL boxes (like overlays).
             * The BoxGrid is used for per-cell lighting later.      */
            for (int bi = 0; bi < n_boxes && n_def[x] < MAX_DEF_PER_COL; bi++) {
                const double *B = box_data + bi * BX_STRIDE;
                double bx = B[BX_X],  by_b = B[BX_Y];
                double hw  = B[BX_W] * 0.5, hd = B[BX_D] * 0.5;
                double cos_y = cos(B[BX_YAW]);
                double sin_y = sin(B[BX_YAW]);

                /* Transform ray to box-local space */
                double dx_l = cam_x - bx, dy_l = cam_y - by_b;
                double lo_x =  dx_l * cos_y + dy_l * sin_y;
                double lo_y = -dx_l * sin_y + dy_l * cos_y;
                double ld_x =  rdx * cos_y + rdy * sin_y;
                double ld_y = -rdx * sin_y + rdy * cos_y;

                /* X slab */
                double t1x, t2x;
                if (fabs(ld_x) < 1e-10) {
                    if (lo_x < -hw || lo_x > hw) continue;
                    t1x = -1e20; t2x = 1e20;
                } else {
                    t1x = (-hw - lo_x) / ld_x;
                    t2x = ( hw - lo_x) / ld_x;
                    if (t1x > t2x) { double tmp = t1x; t1x = t2x; t2x = tmp; }
                }
                /* Y slab */
                double t1y, t2y;
                if (fabs(ld_y) < 1e-10) {
                    if (lo_y < -hd || lo_y > hd) continue;
                    t1y = -1e20; t2y = 1e20;
                } else {
                    t1y = (-hd - lo_y) / ld_y;
                    t2y = ( hd - lo_y) / ld_y;
                    if (t1y > t2y) { double tmp = t1y; t1y = t2y; t2y = tmp; }
                }

                double t_near = (t1x > t1y) ? t1x : t1y;
                double t_far  = (t2x < t2y) ? t2x : t2y;
                if (t_near > t_far || t_far < 0.001) continue;
                if (t_near < 0.001) t_near = 0.001;

                /* Depth culling against primary wall */
                if (t_near >= w_dist[x]) continue;

                /* Determine which face was hit and compute UV */
                int b_tid;
                double b_u;
                int b_side;

                if (t_near == t1x) {
                    /* Hit X slab face */
                    double local_hit_y = lo_y + t_near * ld_y;
                    b_u = (local_hit_y + hd) / (2.0 * hd);
                    b_side = 1;  /* EW-shading */
                    if (ld_x > 0)
                        b_tid = (int)B[BX_TEX_W];  /* entered from -X = west */
                    else
                        b_tid = (int)B[BX_TEX_E];  /* entered from +X = east */
                } else {
                    /* Hit Y slab face */
                    double local_hit_x = lo_x + t_near * ld_x;
                    b_u = (local_hit_x + hw) / (2.0 * hw);
                    b_side = 0;  /* NS-shading */
                    if (ld_y > 0)
                        b_tid = (int)B[BX_TEX_S];  /* entered from -Y = south */
                    else
                        b_tid = (int)B[BX_TEX_N];  /* entered from +Y = north */
                }

                b_u = b_u - floor(b_u);  /* wrap to [0,1) */

                /* Cell index at hit point */
                double hx = cam_x + t_near * rdx;
                double hy = cam_y + t_near * rdy;
                int hcx = clampi((int)floor(hx), 0, map_w - 1);
                int hcy = clampi((int)floor(hy), 0, map_h - 1);
                int bci = hcy * map_w + hcx;

                DeferredHit *bdh = &deferred[x * MAX_DEF_PER_COL + n_def[x]++];
                bdh->col       = x;
                bdh->dist      = t_near;
                bdh->tid       = (b_tid >= 0 && b_tid < num_tiles) ? b_tid : 0;
                bdh->ci        = bci;
                bdh->side      = b_side;
                bdh->face      = 0;
                bdh->wall_frac = b_u;
                bdh->hs        = B[BX_H];
                bdh->base_y    = B[BX_Z];
            }
        }

        /* ── Curved wall (arc) intersections ──────────────────── */
        /* For each arc, solve the quadratic ray-circle equation:
         *   a = rdx² + rdy²
         *   b = 2 * (rdx*(ox-cx) + rdy*(oy-cy))
         *   c = (ox-cx)² + (oy-cy)² - r²
         * Both roots are tested; the nearest valid one (positive t,
         * within the arc's angular range, closer than primary wall)
         * produces a DeferredHit.                                   */
        if (crv_data) {
            for (int ci_c = 0; ci_c < n_curves && n_def[x] < MAX_DEF_PER_COL; ci_c++) {
                const double *C = crv_data + ci_c * CRV_STRIDE;
                double cx_c = C[CRV_CX], cy_c = C[CRV_CY];
                double cr   = C[CRV_R];
                double a0   = C[CRV_A0], a1 = C[CRV_A1];
                if (cr < 1e-6) continue;

                double ox = cam_x - cx_c;
                double oy = cam_y - cy_c;
                double a = rdx * rdx + rdy * rdy;
                double b = 2.0 * (rdx * ox + rdy * oy);
                double c = ox * ox + oy * oy - cr * cr;
                double disc = b * b - 4.0 * a * c;
                if (disc < 0.0) continue;

                double sq = sqrt(disc);
                double inv_2a = 0.5 / a;
                /* Check both roots (the two intersections with the full circle). */
                double roots[2] = { (-b - sq) * inv_2a, (-b + sq) * inv_2a };
                for (int ri = 0; ri < 2 && n_def[x] < MAX_DEF_PER_COL; ri++) {
                    double t_c = roots[ri];
                    if (t_c < 0.001 || t_c >= w_dist[x]) continue;

                    /* Hit point in world space */
                    double hx_c = cam_x + t_c * rdx;
                    double hy_c = cam_y + t_c * rdy;
                    /* Angle of hit on the circle (0 = +X, counter-clockwise) */
                    double hit_ang = atan2(hy_c - cy_c, hx_c - cx_c);
                    /* Full-circle check: if arc span ≥ 2π, skip angle test */
                    double TWO_PI = 6.283185307179586;
                    double arc_span = a1 - a0;
                    int in_arc;
                    if (fabs(arc_span) >= TWO_PI - 1e-6) {
                        in_arc = 1;  /* full circle — any angle is valid */
                    } else {
                        /* Normalise angles to [0, 2π) for range check */
                        double na0 = a0 - floor(a0 / TWO_PI) * TWO_PI;
                        double na1 = a1 - floor(a1 / TWO_PI) * TWO_PI;
                        double nha = hit_ang - floor(hit_ang / TWO_PI) * TWO_PI;
                        if (na0 <= na1)
                            in_arc = (nha >= na0 && nha <= na1);
                        else  /* arc wraps around 0 */
                            in_arc = (nha >= na0 || nha <= na1);
                    }
                    if (!in_arc) continue;

                    /* Texture U: fraction along the arc */
                    if (fabs(arc_span) < 1e-10) continue;
                    double frac_u = (hit_ang - a0) / arc_span;
                    frac_u = frac_u - floor(frac_u);  /* wrap [0,1) */

                    /* Side shading: use normal direction at hit point */
                    double nx_c = hx_c - cx_c;
                    double ny_c = hy_c - cy_c;
                    int c_side = (fabs(nx_c) >= fabs(ny_c)) ? 1 : 0;

                    /* Cell index at hit */
                    int hcx_c = clampi((int)floor(hx_c), 0, map_w - 1);
                    int hcy_c = clampi((int)floor(hy_c), 0, map_h - 1);
                    int cci   = hcy_c * map_w + hcx_c;

                    int c_tid = (int)C[CRV_TID];
                    DeferredHit *cdh = &deferred[x * MAX_DEF_PER_COL + n_def[x]++];
                    cdh->col       = x;
                    cdh->dist      = t_c;
                    cdh->tid       = (c_tid >= 0 && c_tid < num_tiles) ? c_tid : 0;
                    cdh->ci        = cci;
                    cdh->side      = c_side;
                    cdh->face      = 0;
                    cdh->wall_frac = frac_u;
                    cdh->hs        = C[CRV_HS];
                    cdh->base_y    = C[CRV_BASE];
                    break;  /* take nearest (first) valid root */
                }
            }
        }

        if (!hit) continue;

        /* perp already computed before overlay loop */
        double perp = w_dist[x];

        /* ── Wall geometry ─────────────────────────────────────── */
        int ci = my * map_w + mx;
        double lens_m = lens ? lens[x] : 1.0;
        int line_h = (int)((double)sh / perp * lens_m);
        if (line_h < 1) line_h = 1;

        double fh = (ci < map_size) ? fheight[ci] : 0.0;
        double ch = (ci < map_size) ? cheight[ci] : 1.0;
        double orig_fh = fh, orig_ch = ch;
        /* Geometry-solid cells may have fh > ch (floor raised
         * above ceiling = filled mass).  Swap so the wall
         * column renders correctly (vis_top < vis_bot).       */
        if (fh > ch) { double tmp = fh; fh = ch; ch = tmp; }
        /* Degenerate solid (fh ≈ ch): the cell is filled mass.
         * The wall face extends from the approaching cell's floor
         * up to the top of the mass (max of original fh and ch). */
        if (ch - fh < 0.1) {
            double mass_top = orig_fh > orig_ch ? orig_fh : orig_ch;
            fh = prev_fh < fh ? prev_fh : fh;
            ch = mass_top;
            if (ch < fh + 0.1) ch = fh + 0.5;
        }
        /* Non-degenerate geometry wall (floor raised above ceiling):
         * After swap, the wall covers [orig_ch, orig_fh]. Extend
         * the bottom to the approaching cell's floor so the full
         * geometry face is visible.                                */
        else if (orig_fh > orig_ch) {
            if (prev_fh < fh) fh = prev_fh;
        }
        if (ch >= SKY_THRESHOLD) ch = SKY_THRESHOLD - 0.01;
        if (ch < fh) ch = fh + 0.1;  /* safety: ceil must be above floor */

        int vis_top = (int)(half - line_h * (ch - CAM_H));
        int vis_bot = (int)(half + line_h * (CAM_H - fh));
        /* full_top: the screen Y for the top of a unit-height column
         * from fh.  Used as the texture anchoring reference. */
        int full_top = vis_top;

        /* ── Clip wall to intervening ceiling / floor ─────────── */
        /* ray_clip_top/bot are screen-Y positions computed at
         * each intervening cell's own distance — geometrically
         * correct projection of each ceiling/floor surface.      */
        int was_ceil_clipped = 0;
        if (ray_clip_top > vis_top) {
            vis_top = ray_clip_top;
            was_ceil_clipped = 1;
        }
        if (ray_clip_bot < vis_bot)
            vis_bot = ray_clip_bot;

        int y0 = clampi(vis_top, 0, sh - 1);
        int y1 = clampi(vis_bot, 0, sh - 1);

        w_top[x] = y0;
        w_bot[x] = y1;

        /* ── Texture X coordinate ─────────────────────────────── */
        double wall_frac;
        if (is_portal_col) {
            wall_frac = portal_wall_frac;
        } else {
            if (side == 0) wall_frac = cam_y + perp * rdy;
            else           wall_frac = cam_x + perp * rdx;
            wall_frac -= floor(wall_frac);
        }
        int tex_x = (int)(wall_frac * ts) & ts_mask;

        /* ── Fog and side shading ─────────────────────────────── */
        col_fog[x] = fog_accum;
        int fog = fog_vol(fog_lt, perp, fog_accum);
        int sr = 255, sg = 255, sb = 255;
        if (side == 1) { sr = SIDE_R; sg = SIDE_G; sb = SIDE_B; }

        /* Per-tile spatial lighting */
        double tile_light = (ci < map_size) ? light_grid[ci] : 1.0;

        /* Per-column world hit position (shared by lights + decals) */
        double hit_wx, hit_wy;
        if (is_portal_col) {
            hit_wx = portal_hit_wx;
            hit_wy = portal_hit_wy;
        } else {
            hit_wx = cam_x + perp * rdx;
            hit_wy = cam_y + perp * rdy;
        }

        /* Per-column point light accumulation.
         * For primary walls, use the open cell just in front of the
         * wall face for shadow lookups (the wall cell itself is solid
         * and would always be "shadowed"). */
        double plr = 0.0, plg = 0.0, plb = 0.0;
        if (plights && ci < map_size) {
            int light_ci = ci;
            {
                double lx = hit_wx - rdx * 0.01;
                double ly = hit_wy - rdy * 0.01;
                int lcx = clampi((int)floor(lx), 0, map_w - 1);
                int lcy = clampi((int)floor(ly), 0, map_h - 1);
                light_ci = lcy * map_w + lcx;
            }
            accumulate_lights(plights, &lgrid, light_ci,
                              hit_wx, hit_wy, 0.5, &smap, &plr, &plg, &plb);
        }

        /* ── Texture mapping for the wall column ──────────────── */
        int tid = tiles[ci];
        if (tid < 0 || tid >= num_tiles) tid = 0;

        /* Per-face directional texture resolution */
        int wall_face = detect_face(side, step_x, step_y);
        int tex_tid = (ci < map_size)
            ? resolve_face_tex(face_tex, ci, wall_face, tid, num_tiles)
            : tid;
        tex_tid = resolve_anim_tid(anim_lt, tex_tid, anim_tick, num_tiles);

        /* ── Check for stacked wall segments on this face ───── */
        int face_key = ci * 4 + wall_face;
        int ns = (ci < map_size && n_total_segs > 0)
               ? seg_cnt[face_key] : 0;

        if (ns > 0 && seg_tex != NULL && seg_ytop != NULL) {
            /* Draw using per-segment textures */
            draw_segmented_column(
                fb, sw, x, depth_px,
                atlas, ts, ts_mask,
                half, line_h, y0, y1,
                fh, ch,
                tex_x, sr, sg, sb,
                fog, tile_light, perp,
                tex_tid,
                seg_tex, seg_ytop,
                seg_off[face_key], ns,
                num_tiles, vscale, CAM_H,
                plr, plg, plb);
        } else {
            /* Original single-texture path */
            double vs = (vscale && tex_tid < num_tiles) ? vscale[tex_tid] : 1.0;
            double tex_step = (double)ts * vs / (double)line_h;
            double tex_pos  = (y0 - full_top) * tex_step;

            for (int y = y0; y <= y1; y++) {
                double tp = fmod(tex_pos, (double)ts);
                if (tp < 0.0) tp += (double)ts;
                int tex_y = clampi((int)tp, 0, ts - 1);
                tex_pos += tex_step;

                int r, g, b, a;
                sample_tex(atlas, ts, tex_tid, tex_x, tex_y, &r, &g, &b, &a);
                if (a <= 0) continue;

                r = (r * sr) >> 8;
                g = (g * sg) >> 8;
                b = (b * sb) >> 8;
                apply_lights(&r, &g, &b, tile_light, plr, plg, plb);
                r = (r * fog) >> 8;
                g = (g * fog) >> 8;
                b = (b * fog) >> 8;
                fog_color_blend(&r, &g, &b, fog_col, ci, fog_accum);

                if (decals && dgrid.n_cell_decals
                    && ci < map_size && dgrid.n_cell_decals[ci] > 0) {
                    double wz = CAM_H - (double)(y - half) / (double)line_h;
                    apply_decals(decals, &dgrid, ci, hit_wx, hit_wy, wz,
                                 DC_WALL, atlas, ts, num_tiles,
                                 &r, &g, &b);
                }

                put_px(fb, sw, x, y, r, g, b);
                put_depth(depth_px, sw, x, y, (float)perp);
            }
        }

        /* ── Tall wall extension (tile upward with repeating tex) ── */
        /* Skip if the wall top was clipped by an intervening
         * ceiling — the ceiling occludes the tall extension.   */
        if (tall_lt[tid] && y0 > 0 && !was_ceil_clipped) {
            /* Use alt texture if available, else repeat main texture */
            int tall_tex = tex_tid;
            if (tid < lut_len && alt_tex_lt[tid] >= 0
                && alt_tex_lt[tid] < num_tiles) {
                tall_tex = alt_tex_lt[tid];
            }
            tall_tex = resolve_anim_tid(anim_lt, tall_tex, anim_tick, num_tiles);

            int rep_h = maxi(1, line_h);
            for (int ey = y0 - 1; ey >= 0; ey--) {
                /* Reverse-tile the texture upward from wall top */
                int rel = (y0 - 1 - ey) % rep_h;
                int tex_y_ext = ts - 1 - (int)((double)rel / rep_h * ts);
                tex_y_ext = clampi(tex_y_ext, 0, ts - 1);

                int r, g, b, a;
                sample_tex(atlas, ts, tall_tex, tex_x, tex_y_ext, &r, &g, &b, &a);
                if (a <= 0) continue;

                r = (r * sr) >> 8;
                g = (g * sg) >> 8;
                b = (b * sb) >> 8;
                apply_lights(&r, &g, &b, tile_light, plr, plg, plb);
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

    /* ── Compact per-column deferred hits into flat array for Phase 4 ─ */
    n_deferred = 0;
    for (int x = 0; x < sw; x++) {
        int nc = n_def[x];
        for (int d = 0; d < nc; d++) {
            if (n_deferred < max_deferred) {
                deferred[n_deferred++] =
                    deferred[x * MAX_DEF_PER_COL + d];
            }
        }
    }

    /* Copy depth buffer out for entity rendering */
    memcpy(zbuf_out, w_dist, sw * sizeof(double));

    /* ══════════════════════════════════════════════════════════════
     *  PHASE 2A — FLOOR STEP WALLS  (from Phase 1 collected data)
     *
     *  Uses step-wall hits collected during Phase 1's single DDA.
     *  No redundant ray trace — geometry was captured inline.
     *
     *  Per-pixel depth testing ensures floor step walls correctly
     *  render in front of farther main walls, and prevents near
     *  step walls from being falsely clipped by w_bot[x].
     * ══════════════════════════════════════════════════════════════ */
    {
        for (int x = 0; x < sw; x++) {
            if (n_fstep[x] == 0) continue;

            for (int si = 0; si < n_fstep[x]; si++) {
                StepWallHit *h = &fstep_hits[x * MAX_STEP_HITS + si];

                double fsw_lens = lens ? lens[x] : 1.0;
                int line_h = (int)((double)sh / h->perp * fsw_lens);
                if (line_h < 1) line_h = 1;

                double lo = h->pfh < h->cfh ? h->pfh : h->cfh;
                double hi = h->pfh > h->cfh ? h->pfh : h->cfh;

                int uncl_top = (int)(half + line_h * (CAM_H - hi));
                int uncl_bot = (int)(half + line_h * (CAM_H - lo));

                /* Clamp to screen bounds only — depth test handles
                 * occlusion by nearer geometry per-pixel.           */
                int s_top = clampi(uncl_top, 0, sh - 1);
                int s_bot = clampi(uncl_bot, 0, sh - 1);

                if (s_top <= s_bot) {
                    int tex_x = (int)(h->wall_frac * ts) & ts_mask;
                    int fs_face = detect_face(h->sd, h->ssx, h->ssy);

                    int hi_ci, hi_face;
                    if (h->cfh >= h->pfh) {
                        hi_ci   = h->ci;
                        hi_face = fs_face;
                    } else {
                        hi_ci   = h->pci;
                        hi_face = fs_face ^ 1;
                    }
                    int hi_tid = tiles[hi_ci];
                    if (hi_tid < 0 || hi_tid >= lut_len) hi_tid = 0;

                    int fs_key = hi_ci * 4 + hi_face;
                    int fst_ov = fstep_tex[fs_key];
                    int stex;
                    if (fst_ov >= 0 && fst_ov < num_tiles)
                        stex = fst_ov;
                    else
                        stex = resolve_face_tex(
                            face_tex, hi_ci, hi_face, hi_tid, num_tiles);
                    stex = resolve_anim_tid(anim_lt, stex, anim_tick, num_tiles);

                    int sr = 255, sg = 255, sb = 255;
                    if (h->sd == 1) { sr = SIDE_R; sg = SIDE_G; sb = SIDE_B; }
                    int fog = fog_vol(fog_lt, h->perp, col_fog[x]);
                    double tl = light_grid[h->ci];

                    /* Point light for step wall */
                    double fs_plr = 0.0, fs_plg = 0.0, fs_plb = 0.0;
                    if (plights && h->ci < map_size) {
                        double cc = 2.0 * x / (double)sw - 1.0;
                        double rx = dir_x + plane_x * cc;
                        double ry = dir_y + plane_y * cc;
                        accumulate_lights(plights, &lgrid, h->ci,
                            cam_x + h->perp * rx, cam_y + h->perp * ry,
                            0.5, &smap, &fs_plr, &fs_plg, &fs_plb);
                    }

                    int fs_nseg = fstep_seg_cnt[fs_key];
                    if (fs_nseg > 0 && fstep_seg_tex && fstep_seg_ytop) {
                        draw_segmented_column_ex(
                            fb, sw, x, depth_px,
                            atlas, ts, ts_mask,
                            half, line_h,
                            s_top, s_bot, lo, hi,
                            tex_x, sr, sg, sb,
                            fog, tl, h->perp,
                            stex,
                            fstep_seg_tex, fstep_seg_ytop,
                            fstep_seg_off[fs_key], fs_nseg,
                            num_tiles, vscale, CAM_H, 1,
                            anim_lt, anim_tick,
                            fs_plr, fs_plg, fs_plb);
                    } else {
                        double fs_vs = (vscale && stex < num_tiles)
                                     ? vscale[stex] : 1.0;
                        double tex_stp = (double)ts * fs_vs / (double)line_h;
                        double tex_pos = (s_top - uncl_top) * tex_stp;

                        for (int y = s_top; y <= s_bot; y++) {
                            /* Per-pixel depth test: skip if closer
                             * geometry already occupies this pixel. */
                            if (depth_px[y * sw + x] <= (float)h->perp) {
                                tex_pos += tex_stp;
                                continue;
                            }
                            double tp = fmod(tex_pos, (double)ts);
                            if (tp < 0.0) tp += (double)ts;
                            int tex_y = clampi((int)tp, 0, ts - 1);
                            tex_pos += tex_stp;

                            int r, g, b, a;
                            sample_tex(atlas, ts, stex, tex_x, tex_y,
                                       &r, &g, &b, &a);
                            if (a <= 0) continue;
                            r = (r * sr) >> 8;
                            g = (g * sg) >> 8;
                            b = (b * sb) >> 8;
                            apply_lights(&r, &g, &b, tl, fs_plr, fs_plg, fs_plb);
                            r = (r * fog) >> 8;
                            g = (g * fog) >> 8;
                            b = (b * fog) >> 8;

                            blend_px(fb, sw, x, y, r, g, b, a);
                            if (a >= 255)
                                put_depth(depth_px, sw, x, y, (float)h->perp);
                        }
                    }
                }
            }
        }
    }

    /* ══════════════════════════════════════════════════════════════
     *  PHASE 2B — FLOOR  (multi-tier row-sweep textured floor casting)
     *
     *  Supports variable floor heights.  Collects unique floor tiers,
     *  then for each scanline row tests from HIGHEST (closest to cam)
     *  to LOWEST.  The first tier whose projected cell matches wins.
     *  Skips pixels already claimed by step walls (Phase 2A).
     * ══════════════════════════════════════════════════════════════ */
    {
        double floor_tiers[MAX_FLOOR_TIERS];
        int n_floor_tiers = 0;

        if (0.0 < CAM_H - TIER_TOL)
            floor_tiers[n_floor_tiers++] = 0.0;

        for (int ci = 0; ci < map_size && n_floor_tiers < MAX_FLOOR_TIERS; ci++) {
            double fh = fheight[ci];
            if (fabs(fh) < 0.01) continue;
            if (fh >= CAM_H) continue;
            int found = 0;
            for (int j = 0; j < n_floor_tiers; j++) {
                if (fabs(floor_tiers[j] - fh) < TIER_TOL) { found = 1; break; }
            }
            if (!found) floor_tiers[n_floor_tiers++] = fh;
        }

        /* Secondary floor layer heights */
        if (fh2) {
            for (int ci = 0; ci < map_size && n_floor_tiers < MAX_FLOOR_TIERS; ci++) {
                double fh = fh2[ci];
                if (fh <= LAYER_NONE + 1.0) continue;
                if (fh >= CAM_H) continue;
                int found = 0;
                for (int j = 0; j < n_floor_tiers; j++) {
                    if (fabs(floor_tiers[j] - fh) < TIER_TOL) { found = 1; break; }
                }
                if (!found) floor_tiers[n_floor_tiers++] = fh;
            }
        }

        for (int i = 0; i < n_floor_tiers - 1; i++)
            for (int j = i + 1; j < n_floor_tiers; j++)
                if (floor_tiers[j] > floor_tiers[i]) {
                    double tmp = floor_tiers[i];
                    floor_tiers[i] = floor_tiers[j];
                    floor_tiers[j] = tmp;
                }

        /* Clamp loop start: half may be far off-screen from pitch */
        int floor_y_start = half + 1;
        if (floor_y_start < 0) floor_y_start = 0;
        for (int y = floor_y_start; y < sh; y++) {
            double p = (double)(y - half);
            if (p < 1.0) p = 1.0;

            double ft_fx[MAX_FLOOR_TIERS], ft_fy[MAX_FLOOR_TIERS];
            double ft_fxs[MAX_FLOOR_TIERS], ft_fys[MAX_FLOOR_TIERS];
            double ft_rd[MAX_FLOOR_TIERS];
            int    ft_fog[MAX_FLOOR_TIERS];

            for (int t = 0; t < n_floor_tiers; t++) {
                double dh = CAM_H - floor_tiers[t];
                double rd = dh * (double)sh / p;
                ft_rd[t]  = rd;
                ft_fxs[t] = rd * (ray1_x - ray0_x) / (double)sw;
                ft_fys[t] = rd * (ray1_y - ray0_y) / (double)sw;
                ft_fx[t]  = cam_x + rd * ray0_x;
                ft_fy[t]  = cam_y + rd * ray0_y;
                ft_fog[t] = fog_val(fog_lt, rd);
            }

            for (int x = 0; x < sw; x++) {
                /* Per-pixel volume fog boost for floor tiles */
                double fx_col_fog = col_fog[x];
                if (y <= w_bot[x]) {
                    for (int t = 0; t < n_floor_tiers; t++) {
                        ft_fx[t] += ft_fxs[t];
                        ft_fy[t] += ft_fys[t];
                    }
                    continue;
                }

                for (int t = 0; t < n_floor_tiers; t++) {
                    double ffx = ft_fx[t];
                    double ffy = ft_fy[t];
                    int cx = (int)floor(ffx);
                    int cy = (int)floor(ffy);

                    if (cx < 0 || cx >= map_w || cy < 0 || cy >= map_h)
                        continue;

                    int ci = cy * map_w + cx;
                    double cell_fh = fheight[ci];
                    int layer2_match = 0;

                    if (fabs(cell_fh - floor_tiers[t]) > TIER_TOL) {
                        /* Primary doesn't match — check secondary layer */
                        if (fh2 && fh2[ci] > LAYER_NONE + 1.0
                            && fabs(fh2[ci] - floor_tiers[t]) <= TIER_TOL) {
                            cell_fh = fh2[ci];
                            layer2_match = 1;
                        } else {
                            continue;
                        }
                    }

                    /* Per-cell slope: interpolate height within cell.
                     * Tier match uses base height; slope is visual only.
                     * slope_data layout: [dx0, dy0, dx1, dy1, ...]      */
                    double slope_off = 0.0;
                    if (slope_data) {
                        double sdx = slope_data[ci * 2];
                        double sdy = slope_data[ci * 2 + 1];
                        if (sdx != 0.0 || sdy != 0.0) {
                            double fx = ffx - cx - 0.5;
                            double fy = ffy - cy - 0.5;
                            slope_off = sdx * fx + sdy * fy;
                            cell_fh += slope_off;
                        }
                    }

                    /* Depth check: skip if existing pixel is closer
                     * than this floor surface (step walls win when
                     * they are nearer). */
                    if (depth_px[y * sw + x] <= (float)ft_rd[t])
                        break;

                    int tid = tiles[ci];
                    if (tid < 0 || tid >= num_tiles) tid = 0;

                    int ftid;
                    if (layer2_match && ftex2) {
                        ftid = ftex2[ci];
                        if (ftid < 0 || ftid >= num_tiles) ftid = tid;
                    } else {
                        ftid = ftex[ci];
                        if (ftid < 0 || ftid >= num_tiles) ftid = tid;
                    }
                    ftid = resolve_anim_tid(anim_lt, ftid, anim_tick, num_tiles);

                    int u = (int)(ts * (ffx - cx)) & ts_mask;
                    int v = (int)(ts * (ffy - cy)) & ts_mask;

                    int r, g, b, a;
                    sample_tex(atlas, ts, ftid, u, v, &r, &g, &b, &a);
                    if (a <= 0) continue;

                    if ((cx ^ cy) & 1) {
                        r = (r * 210) >> 8;
                        g = (g * 210) >> 8;
                        b = (b * 210) >> 8;
                    }

                    if (cell_fh > 0.01) {
                        double boost = 1.0 + 0.15 * cell_fh;
                        if (boost > 1.5) boost = 1.5;
                        r = clampi((int)(r * boost), 0, 255);
                        g = clampi((int)(g * boost), 0, 255);
                        b = clampi((int)(b * boost), 0, 255);
                    }

                    /* Bump mapping (distance-gated for performance) */
                    if (bump_strength > 0.0 && ft_rd[t] < 6.0)
                        apply_bump(atlas, ts, ftid, u, v,
                                   bump_strength, &r, &g, &b);

                    double fl = light_grid[ci];
                    {
                        double f_plr = 0.0, f_plg = 0.0, f_plb = 0.0;
                        if (plights)
                            accumulate_lights(plights, &lgrid, ci,
                                ffx, ffy, cell_fh, &smap, &f_plr, &f_plg, &f_plb);
                        apply_lights(&r, &g, &b, fl, f_plr, f_plg, f_plb);
                    }

                    int fog = ft_fog[t];
                    if (fog_den) {
                        double pf = fog_den[ci] * ft_rd[t];
                        if (pf > 0.0 || fx_col_fog > 0.0) {
                            double va = pf > fx_col_fog ? pf : fx_col_fog;
                            int vf = (int)(exp(-va) * 255.0);
                            if (vf < fog) fog = vf;
                        }
                    }
                    r = (r * fog) >> 8;
                    g = (g * fog) >> 8;
                    b = (b * fog) >> 8;
                    /* Per-cell fog colour tint (match wall behaviour) */
                    if (fog_den) {
                        double pf = fog_den[ci] * ft_rd[t];
                        double accum = pf > fx_col_fog ? pf : fx_col_fog;
                        fog_color_blend(&r, &g, &b, fog_col, ci, accum);
                    }

                    if (decals && dgrid.n_cell_decals
                        && dgrid.n_cell_decals[ci] > 0)
                        apply_decals(decals, &dgrid, ci, ffx, ffy, cell_fh,
                                     DC_FLOOR, atlas, ts, num_tiles,
                                     &r, &g, &b);

                    /* ── Reflective floor blend ─────────────────── */
                    if (reflect_flags && reflect_flags[ci] > 0) {
                        int y_ref = 2 * half - y;
                        if (y_ref >= 0 && y_ref < half) {
                            int ref_off = (y_ref * sw + x) * 3;
                            int rr = fb[ref_off];
                            int rg = fb[ref_off + 1];
                            int rb = fb[ref_off + 2];
                            double opacity = reflect_flags[ci] / 255.0;
                            double inv = 1.0 - opacity;
                            r = clampi((int)(r * inv + rr * opacity), 0, 255);
                            g = clampi((int)(g * inv + rg * opacity), 0, 255);
                            b = clampi((int)(b * inv + rb * opacity), 0, 255);
                        }
                    }

                    put_px(fb, sw, x, y, r, g, b);
                    put_depth(depth_px, sw, x, y, (float)ft_rd[t]);
                    break;
                }

                for (int t = 0; t < n_floor_tiers; t++) {
                    ft_fx[t] += ft_fxs[t];
                    ft_fy[t] += ft_fys[t];
                }
            }
        }
    }

    /* ══════════════════════════════════════════════════════════════
     *  PHASE 3A — CEILING STEP WALLS  (from Phase 1 collected data)
     *
     *  Uses step-wall hits collected during Phase 1's single DDA.
     *  No redundant ray trace — geometry was captured inline.
     *
     *  Per-pixel depth testing ensures ceiling step walls don't
     *  overdraw nearer floor step walls or solid walls, and also
     *  allows tall ceiling steps to render above/behind walls
     *  without being falsely clipped by w_top[x].
     * ══════════════════════════════════════════════════════════════ */
    if (is_interior) {
        for (int x = 0; x < sw; x++) {
            if (n_cstep[x] == 0) continue;

            for (int si = 0; si < n_cstep[x]; si++) {
                StepWallHit *h = &cstep_hits[x * MAX_STEP_HITS + si];

                double csw_lens = lens ? lens[x] : 1.0;
                int line_h = (int)((double)sh / h->perp * csw_lens);
                if (line_h < 1) line_h = 1;

                /* pfh/cfh store effective ceiling/uwh tops */
                double lo = h->pfh < h->cfh ? h->pfh : h->cfh;
                double hi = h->pfh > h->cfh ? h->pfh : h->cfh;

                /* UWH extension: upper wall may be taller */
                int lo_ci_pre, lo_face_pre;
                {
                    int cs_face_pre = detect_face(h->sd, h->ssx, h->ssy);
                    if (h->cfh >= h->pfh) {
                        lo_ci_pre   = h->pci;
                        lo_face_pre = cs_face_pre ^ 1;
                    } else {
                        lo_ci_pre   = h->ci;
                        lo_face_pre = cs_face_pre;
                    }
                }
                double uwh_val = uwh[lo_ci_pre];
                if (uwh_val > hi) {
                    hi = uwh_val;
                }

                int uncl_top = (int)(half - line_h * (hi - CAM_H));
                int uncl_bot = (int)(half - line_h * (lo - CAM_H));

                /* Clamp to screen bounds only — depth test handles
                 * occlusion by nearer geometry per-pixel.           */
                int s_top = clampi(uncl_top, 0, sh - 1);
                int s_bot = clampi(uncl_bot, 0, sh - 1);

                if (s_top <= s_bot) {
                    int tex_x = (int)(h->wall_frac * ts) & ts_mask;
                    int cs_face = detect_face(h->sd, h->ssx, h->ssy);

                    int hi_ci, hi_face;
                    if (h->cfh >= h->pfh) {
                        hi_ci   = h->ci;
                        hi_face = cs_face;
                    } else {
                        hi_ci   = h->pci;
                        hi_face = cs_face ^ 1;
                    }
                    int hi_tid = tiles[hi_ci];
                    if (hi_tid < 0 || hi_tid >= lut_len) hi_tid = 0;

                    int lo_ci = lo_ci_pre;
                    int lo_face = lo_face_pre;

                    int cs_key = lo_ci * 4 + lo_face;
                    int cst_ov = cstep_tex[cs_key];
                    int stex;
                    if (cst_ov >= 0 && cst_ov < num_tiles)
                        stex = cst_ov;
                    else
                        stex = resolve_face_tex(
                            face_tex, hi_ci, hi_face, hi_tid, num_tiles);
                    stex = resolve_anim_tid(anim_lt, stex, anim_tick, num_tiles);

                    int sr = 255, sg = 255, sb = 255;
                    if (h->sd == 1) { sr = SIDE_R; sg = SIDE_G; sb = SIDE_B; }
                    int fog = fog_vol(fog_lt, h->perp, col_fog[x]);
                    double tl = light_grid[h->ci];

                    /* Point light for ceiling step wall */
                    double cs_plr = 0.0, cs_plg = 0.0, cs_plb = 0.0;
                    if (plights && h->ci < map_size) {
                        double cc = 2.0 * x / (double)sw - 1.0;
                        double rx = dir_x + plane_x * cc;
                        double ry = dir_y + plane_y * cc;
                        accumulate_lights(plights, &lgrid, h->ci,
                            cam_x + h->perp * rx, cam_y + h->perp * ry,
                            0.5, &smap, &cs_plr, &cs_plg, &cs_plb);
                    }

                    int cs_nseg = cstep_seg_cnt[cs_key];
                    if (cs_nseg > 0 && cstep_seg_tex && cstep_seg_ytop) {
                        draw_segmented_column_ex(
                            fb, sw, x, depth_px,
                            atlas, ts, ts_mask,
                            half, line_h,
                            s_top, s_bot, lo, hi,
                            tex_x, sr, sg, sb,
                            fog, tl, h->perp,
                            stex,
                            cstep_seg_tex, cstep_seg_ytop,
                            cstep_seg_off[cs_key], cs_nseg,
                            num_tiles, vscale, CAM_H, 1,
                            anim_lt, anim_tick,
                            cs_plr, cs_plg, cs_plb);
                    } else {
                        double cs_vs = (vscale && stex < num_tiles)
                                     ? vscale[stex] : 1.0;
                        double tex_stp = (double)ts * cs_vs / (double)line_h;
                        double tex_pos = (s_top - uncl_top) * tex_stp;

                        for (int y = s_top; y <= s_bot; y++) {
                            /* Per-pixel depth test: skip if closer
                             * geometry already occupies this pixel. */
                            if (depth_px[y * sw + x] <= (float)h->perp) {
                                tex_pos += tex_stp;
                                continue;
                            }
                            double tp = fmod(tex_pos, (double)ts);
                            if (tp < 0.0) tp += (double)ts;
                            int tex_y = clampi((int)tp, 0, ts - 1);
                            tex_pos += tex_stp;

                            int r, g, b, a;
                            sample_tex(atlas, ts, stex, tex_x, tex_y,
                                       &r, &g, &b, &a);
                            if (a <= 0) continue;
                            r = (r * sr) >> 8;
                            g = (g * sg) >> 8;
                            b = (b * sb) >> 8;
                            apply_lights(&r, &g, &b, tl, cs_plr, cs_plg, cs_plb);
                            r = (r * fog) >> 8;
                            g = (g * fog) >> 8;
                            b = (b * fog) >> 8;

                            blend_px(fb, sw, x, y, r, g, b, a);
                            if (a >= 255)
                                put_depth(depth_px, sw, x, y, (float)h->perp);
                        }
                    }
                }
            }
        }
    }

    /* ══════════════════════════════════════════════════════════════
     *  PHASE 3B — CEILING  (multi-tier row-sweep, interior zones)
     *
     *  Supports variable ceiling heights (1.0, 2.0, etc.).
     *  For each pixel above the horizon, we test every known ceiling
     *  tier from LOWEST (closest) to HIGHEST (farthest).  The first
     *  tier whose projected cell actually has a matching ceil_height
     *  wins.  Skips pixels already claimed by step walls (Phase 3A).
     * ══════════════════════════════════════════════════════════════ */
    if (is_interior) {
        #define MAX_CEIL_TIERS 32
        double ceil_tiers[MAX_CEIL_TIERS];
        int n_ceil_tiers = 0;

        for (int ci = 0; ci < map_size && n_ceil_tiers < MAX_CEIL_TIERS; ci++) {
            double ch = cheight[ci];
            if (ch >= SKY_THRESHOLD) continue;
            if (ch <= CAM_H)         continue;
            int found = 0;
            for (int j = 0; j < n_ceil_tiers; j++) {
                if (fabs(ceil_tiers[j] - ch) < TIER_TOL) { found = 1; break; }
            }
            if (!found) ceil_tiers[n_ceil_tiers++] = ch;
        }

        /* Secondary ceiling layer heights */
        if (ch2) {
            for (int ci = 0; ci < map_size && n_ceil_tiers < MAX_CEIL_TIERS; ci++) {
                double ch = ch2[ci];
                if (ch <= LAYER_NONE + 1.0) continue;
                if (ch >= SKY_THRESHOLD) continue;
                if (ch <= CAM_H) continue;
                int found = 0;
                for (int j = 0; j < n_ceil_tiers; j++) {
                    if (fabs(ceil_tiers[j] - ch) < TIER_TOL) { found = 1; break; }
                }
                if (!found) ceil_tiers[n_ceil_tiers++] = ch;
            }
        }

        for (int ci = 0; ci < map_size && n_ceil_tiers < MAX_CEIL_TIERS; ci++) {
            double fh = fheight[ci];
            if (fh <= CAM_H + TIER_TOL) continue;
            if (fh >= SKY_THRESHOLD) continue;
            int found = 0;
            for (int j = 0; j < n_ceil_tiers; j++) {
                if (fabs(ceil_tiers[j] - fh) < TIER_TOL) { found = 1; break; }
            }
            if (!found) ceil_tiers[n_ceil_tiers++] = fh;
        }

        /* Secondary floor layer overhead tiers */
        if (fh2) {
            for (int ci = 0; ci < map_size && n_ceil_tiers < MAX_CEIL_TIERS; ci++) {
                double fh = fh2[ci];
                if (fh <= LAYER_NONE + 1.0) continue;
                if (fh <= CAM_H + TIER_TOL) continue;
                if (fh >= SKY_THRESHOLD) continue;
                int found = 0;
                for (int j = 0; j < n_ceil_tiers; j++) {
                    if (fabs(ceil_tiers[j] - fh) < TIER_TOL) { found = 1; break; }
                }
                if (!found) ceil_tiers[n_ceil_tiers++] = fh;
            }
        }

        for (int i = 0; i < n_ceil_tiers - 1; i++)
            for (int j = i + 1; j < n_ceil_tiers; j++)
                if (ceil_tiers[j] < ceil_tiers[i]) {
                    double tmp = ceil_tiers[i];
                    ceil_tiers[i] = ceil_tiers[j];
                    ceil_tiers[j] = tmp;
                }

        /* Clamp loop start: half may be far off-screen from pitch */
        int ceil_y_start = half - 1;
        if (ceil_y_start >= sh) ceil_y_start = sh - 1;
        for (int y = ceil_y_start; y >= 0; y--) {
            double p = (double)(half - y);
            if (p < 1.0) p = 1.0;

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
                double cx_col_fog = col_fog[x];
                if (y >= w_top[x]) {
                    for (int t = 0; t < n_ceil_tiers; t++) {
                        t_fx[t] += t_fxs[t];
                        t_fy[t] += t_fys[t];
                    }
                    continue;
                }

                for (int t = 0; t < n_ceil_tiers; t++) {
                    double cfx = t_fx[t];
                    double cfy = t_fy[t];
                    int tcx = (int)floor(cfx);
                    int tcy = (int)floor(cfy);

                    if (tcx < 0 || tcx >= map_w || tcy < 0 || tcy >= map_h)
                        continue;

                    int ci = tcy * map_w + tcx;
                    double c_h = cheight[ci];

                    if (c_h >= SKY_THRESHOLD) {
                        /* Sky cell: no physical ceiling surface at this
                         * tier height.  Skip to the next tier — farther
                         * tiers may find a real ceiling or overhead floor.
                         * Phase 0 already filled the background with sky,
                         * so sky-holes render correctly without re-drawing
                         * sky here (which would clobber nearer step walls
                         * that are already in the depth buffer).          */
                        continue;
                    }

                    int is_overhead_floor = 0;
                    int layer2_match = 0;
                    if (fabs(c_h - ceil_tiers[t]) > TIER_TOL) {
                        double f_h = fheight[ci];
                        if (fabs(f_h - ceil_tiers[t]) <= TIER_TOL) {
                            is_overhead_floor = 1;
                        } else if (ch2 && ch2[ci] > LAYER_NONE + 1.0
                                   && fabs(ch2[ci] - ceil_tiers[t]) <= TIER_TOL) {
                            layer2_match = 1;
                        } else if (fh2 && fh2[ci] > LAYER_NONE + 1.0
                                   && fabs(fh2[ci] - ceil_tiers[t]) <= TIER_TOL) {
                            is_overhead_floor = 1;
                            layer2_match = 1;
                        } else {
                            continue;
                        }
                    }

                    /* Depth check: skip if existing pixel is closer
                     * than this ceiling surface (step walls win when
                     * they are nearer). */
                    if (depth_px[y * sw + x] <= (float)t_rd[t])
                        break;

                    int tid = tiles[ci];
                    if (tid < 0 || tid >= num_tiles) tid = 0;

                    int ctid;
                    if (is_overhead_floor) {
                        if (layer2_match && ftex2) {
                            ctid = ftex2[ci];
                        } else {
                            ctid = ftex[ci];
                        }
                        if (ctid < 0 || ctid >= num_tiles) ctid = tid;
                    } else if (layer2_match && ctex2) {
                        ctid = ctex2[ci];
                        if (ctid < 0 || ctid >= num_tiles) ctid = tid;
                    } else {
                        ctid = ctex[ci];
                        if (ctid < 0 || ctid >= num_tiles) ctid = tid;
                    }
                    ctid = resolve_anim_tid(anim_lt, ctid, anim_tick, num_tiles);

                    int u = (int)(ts * (cfx - tcx)) & ts_mask;
                    int v = (int)(ts * (cfy - tcy)) & ts_mask;

                    int r, g, b, a;
                    sample_tex(atlas, ts, ctid, u, v, &r, &g, &b, &a);
                    if (a <= 0) continue;

                    double render_h = is_overhead_floor
                        ? (layer2_match ? fh2[ci] : fheight[ci])
                        : (layer2_match && ch2 ? ch2[ci] : c_h);
                    if (render_h < 0.99) {
                        double dim = 0.5 + 0.5 * render_h;
                        if (dim < 0.2) dim = 0.2;
                        r = (int)(r * dim);
                        g = (int)(g * dim);
                        b = (int)(b * dim);
                    }

                    if (is_overhead_floor) {
                        r = (r * 150) >> 8;
                        g = (g * 150) >> 8;
                        b = (b * 150) >> 8;
                    } else {
                        r = (r * 180) >> 8;
                        g = (g * 180) >> 8;
                        b = (b * 180) >> 8;
                    }

                    /* Bump mapping for ceiling (distance-gated) */
                    if (bump_strength > 0.0 && t_rd[t] < 6.0)
                        apply_bump(atlas, ts, ctid, u, v,
                                   bump_strength, &r, &g, &b);

                    double cl = light_grid[ci];
                    {
                        double c_plr = 0.0, c_plg = 0.0, c_plb = 0.0;
                        if (plights)
                            accumulate_lights(plights, &lgrid, ci,
                                cfx, cfy, c_h, &smap, &c_plr, &c_plg, &c_plb);
                        apply_lights(&r, &g, &b, cl, c_plr, c_plg, c_plb);
                    }

                    int fog = t_fog[t];
                    if (fog_den) {
                        double pf = fog_den[ci] * t_rd[t];
                        if (pf > 0.0 || cx_col_fog > 0.0) {
                            double va = pf > cx_col_fog ? pf : cx_col_fog;
                            int vf = (int)(exp(-va) * 255.0);
                            if (vf < fog) fog = vf;
                        }
                    }
                    r = (r * fog) >> 8;
                    g = (g * fog) >> 8;
                    b = (b * fog) >> 8;
                    /* Per-cell fog colour tint (match wall behaviour) */
                    if (fog_den) {
                        double pf = fog_den[ci] * t_rd[t];
                        double accum = pf > cx_col_fog ? pf : cx_col_fog;
                        fog_color_blend(&r, &g, &b, fog_col, ci, accum);
                    }

                    if (decals && dgrid.n_cell_decals
                        && dgrid.n_cell_decals[ci] > 0)
                        apply_decals(decals, &dgrid, ci, cfx, cfy, c_h,
                                     DC_CEILING, atlas, ts, num_tiles,
                                     &r, &g, &b);

                    put_px(fb, sw, x, y, r, g, b);
                    put_depth(depth_px, sw, x, y, (float)t_rd[t]);
                    break;
                }

                for (int t = 0; t < n_ceil_tiers; t++) {
                    t_fx[t] += t_fxs[t];
                    t_fy[t] += t_fys[t];
                }
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

            double d_lens = lens ? lens[dx] : 1.0;
            int d_line_h = (int)((double)sh / d_perp * d_lens);
            if (d_line_h < 1) d_line_h = 1;

            int d_fog = fog_vol(fog_lt, d_perp,
                                (dx >= 0 && dx < sw) ? col_fog[dx] : 0.0);
            int d_sr = 255, d_sg = 255, d_sb = 255;
            if (d_side == 1) { d_sr = SIDE_R; d_sg = SIDE_G; d_sb = SIDE_B; }

            /* Per-tile spatial lighting for deferred walls */
            double d_light = (d_ci >= 0 && d_ci < map_size)
                ? light_grid[d_ci] : 1.0;

            /* Point light for deferred wall */
            double d_plr = 0.0, d_plg = 0.0, d_plb = 0.0;
            if (plights && d_ci >= 0 && d_ci < map_size) {
                double dcc = 2.0 * dx / (double)sw - 1.0;
                double drx = dir_x + plane_x * dcc;
                double dry = dir_y + plane_y * dcc;
                accumulate_lights(plights, &lgrid, d_ci,
                    cam_x + d_perp * drx, cam_y + d_perp * dry,
                    0.5, &smap, &d_plr, &d_plg, &d_plb);
            }

            int d_tex_x = (int)(d_wfrac * ts) & ts_mask;

            int safe_tid = (d_tid >= 0 && d_tid < num_tiles) ? d_tid : 0;
            /* Resolve per-face texture for deferred walls */
            if (d_ci >= 0 && d_ci < map_size) {
                safe_tid = resolve_face_tex(face_tex, d_ci, d_face,
                                            safe_tid, num_tiles);
            }
            safe_tid = resolve_anim_tid(anim_lt, safe_tid, anim_tick, num_tiles);

            /* ── Short/thin wall: anchored at cell floor level ────
             *    Quads override d_fh with their own base_y anchor. ── */
            double d_fh = (dh->base_y > -1e8)
                ? dh->base_y
                : ((d_ci >= 0 && d_ci < map_size) ? fheight[d_ci] : 0.0);
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

                int r, g, b, a;
                sample_tex(atlas, ts, safe_tid, d_tex_x, tex_y,
                           &r, &g, &b, &a);

                /* Alpha transparency: skip fully transparent texels.
                 * For semi-transparent, blend over background.     */
                if (a <= 0) continue;

                /* Per-pixel depth check: skip if behind already-drawn
                 * geometry (primary walls, floors, ceilings, etc.) */
                if ((float)d_perp >= depth_px[y * sw + dx]) continue;

                r = (r * d_sr) >> 8;
                g = (g * d_sg) >> 8;
                b = (b * d_sb) >> 8;
                apply_lights(&r, &g, &b, d_light, d_plr, d_plg, d_plb);
                r = (r * d_fog) >> 8;
                g = (g * d_fog) >> 8;
                b = (b * d_fog) >> 8;
                /* Deferred wall: per-cell fog colour tint */
                if (fog_col && d_ci >= 0 && d_ci < map_size) {
                    double da = (dx >= 0 && dx < sw) ? col_fog[dx] : 0.0;
                    fog_color_blend(&r, &g, &b, fog_col, d_ci, da);
                }

                if (decals && dgrid.n_cell_decals
                    && d_ci >= 0 && d_ci < map_size
                    && dgrid.n_cell_decals[d_ci] > 0) {
                    double dcc = 2.0 * dx / (double)sw - 1.0;
                    double dwx = cam_x + d_perp * (dir_x + plane_x * dcc);
                    double dwy = cam_y + d_perp * (dir_y + plane_y * dcc);
                    double dwz = CAM_H - (double)(y - half) / (double)d_line_h;
                    apply_decals(decals, &dgrid, d_ci, dwx, dwy, dwz,
                                 DC_WALL, atlas, ts, num_tiles,
                                 &r, &g, &b);
                }

                blend_px(fb, sw, dx, y, r, g, b, a);
                if (a >= 255)
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
                    top_tid = resolve_anim_tid(anim_lt, top_tid, anim_tick, num_tiles);

                    int ct_lo = half + 1 < 0 ? 0 : half + 1;
                    int top_start = clampi(d_hw_top - 1, ct_lo, sh - 1);
                    int ct_end = half < 0 ? -1 : half;  /* loop guard */
                    for (int y = top_start; y > ct_end; y--) {
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

                        int r, g, b, a;
                        sample_tex(atlas, ts, top_tid, u, v, &r, &g, &b, &a);
                        if (a <= 0) continue;

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

                        apply_lights(&r, &g, &b, d_light, d_plr, d_plg, d_plb);

                        int tf = fog_vol(fog_lt, td,
                                         (dx >= 0 && dx < sw) ? col_fog[dx] : 0.0);
                        r = (r * tf) >> 8;
                        g = (g * tf) >> 8;
                        b = (b * tf) >> 8;
                        /* Counter-top: per-cell fog colour tint */
                        if (fog_col && d_ci >= 0 && d_ci < map_size) {
                            double ca = (dx >= 0 && dx < sw) ? col_fog[dx] : 0.0;
                            fog_color_blend(&r, &g, &b, fog_col, d_ci, ca);
                        }

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
    free_light_grid(&lgrid);
    free_decal_grid(&dgrid);
    free_shadow_maps(&smap);
    free_box_grid(&bgrid);
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
    if (seg_off_buf.buf) PyBuffer_Release(&seg_off_buf);
    if (seg_cnt_buf.buf) PyBuffer_Release(&seg_cnt_buf);
    if (seg_tex_buf.buf) PyBuffer_Release(&seg_tex_buf);
    if (seg_ytop_buf.buf) PyBuffer_Release(&seg_ytop_buf);
    if (vscale_buf.buf)  PyBuffer_Release(&vscale_buf);
    if (anim_buf.buf)    PyBuffer_Release(&anim_buf);
    if (skybox_buf.buf)  PyBuffer_Release(&skybox_buf);
    if (fog_den_buf.buf) PyBuffer_Release(&fog_den_buf);
    if (fog_col_buf.buf) PyBuffer_Release(&fog_col_buf);
    if (lens_buf.buf)    PyBuffer_Release(&lens_buf);
    if (plight_buf.buf)  PyBuffer_Release(&plight_buf);
    if (decal_buf.buf)   PyBuffer_Release(&decal_buf);
    if (quad_buf.buf)    PyBuffer_Release(&quad_buf);
    if (box_buf.buf)     PyBuffer_Release(&box_buf);
    if (crv_buf.buf)     PyBuffer_Release(&crv_buf);
    if (reflect_buf.buf) PyBuffer_Release(&reflect_buf);
    if (slope_buf.buf)   PyBuffer_Release(&slope_buf);
    if (fh2_buf.buf)     PyBuffer_Release(&fh2_buf);
    if (ch2_buf.buf)     PyBuffer_Release(&ch2_buf);
    if (ftex2_buf.buf)   PyBuffer_Release(&ftex2_buf);
    if (ctex2_buf.buf)   PyBuffer_Release(&ctex2_buf);
    if (portal_map_buf.buf)  PyBuffer_Release(&portal_map_buf);
    if (portal_data_buf.buf) PyBuffer_Release(&portal_data_buf);
    if (fstep_tex_buf.buf)  PyBuffer_Release(&fstep_tex_buf);
    if (cstep_tex_buf.buf)  PyBuffer_Release(&cstep_tex_buf);
    if (uwh_buf.buf)        PyBuffer_Release(&uwh_buf);
    if (fstep_seg_off_buf.buf)  PyBuffer_Release(&fstep_seg_off_buf);
    if (fstep_seg_cnt_buf.buf)  PyBuffer_Release(&fstep_seg_cnt_buf);
    if (fstep_seg_tex_buf.buf)  PyBuffer_Release(&fstep_seg_tex_buf);
    if (fstep_seg_ytop_buf.buf) PyBuffer_Release(&fstep_seg_ytop_buf);
    if (cstep_seg_off_buf.buf)  PyBuffer_Release(&cstep_seg_off_buf);
    if (cstep_seg_cnt_buf.buf)  PyBuffer_Release(&cstep_seg_cnt_buf);
    if (cstep_seg_tex_buf.buf)  PyBuffer_Release(&cstep_seg_tex_buf);
    if (cstep_seg_ytop_buf.buf) PyBuffer_Release(&cstep_seg_ytop_buf);
    free(w_top);
    free(w_bot);
    free(w_dist);
    free(deferred);
    free(n_fstep);
    free(n_cstep);
    free(fstep_hits);
    free(cstep_hits);
    free(col_fog);
    free(n_def);
    return result;
}


/* ═══════════════════════════════════════════════════════════════════
 *  Module definition
 * ═══════════════════════════════════════════════════════════════════ */

static PyMethodDef methods[] = {
    {"render_frame", py_render_frame, METH_O,
     "Render a complete raycaster frame into a pre-allocated buffer.\n\n"
     "render_frame(ctx_dict) -> None\n\n"
     "ctx_dict keys: fb, cam_x, cam_y, cam_angle, cam_fov, cam_h,\n"
     "  horizon_shift, sw, sh, map_w, map_h, tiles, walls, atlas,\n"
     "  tex_size, num_tiles, fog_lut, floor_h, ceil_h, floor_tex,\n"
     "  ceil_tex, is_interior, thin_lut, tall_lut, hs_lut, face_tex,\n"
     "  zbuf, light, alt_tex, depth_px, trans_lut, overlay, n_overlay,\n"
     "  seg_off, seg_cnt, seg_tex, seg_ytop, n_total_segs, vscale,\n"
     "  fstep_tex, cstep_tex, uwh, fstep_seg_off, fstep_seg_cnt,\n"
     "  fstep_seg_tex, fstep_seg_ytop, n_fstep_segs, cstep_seg_off,\n"
     "  cstep_seg_cnt, cstep_seg_tex, cstep_seg_ytop, n_cstep_segs"},
    {"render_entities", py_render_entities, METH_O,
     "Render entity billboards with z-buffer clipping and multi-facing.\n\n"
     "render_entities(ctx_dict) -> None\n\n"
     "ctx_dict keys: fb, sw, sh, cam_x, cam_y, dir_x, dir_y,\n"
     "  plane_x, plane_y, depth_px, fog_lut, atlas, tex_size,\n"
     "  num_tiles, ent_data (12 doubles/ent), n_ents"},
    {"render_particles", py_render_particles, METH_O,
     "Tick and render particle billboards with depth clipping.\n\n"
     "render_particles(ctx_dict) -> None\n\n"
     "ctx_dict keys: fb, depth_px, fog_lut, atlas, sw, sh, tex_size,\n"
     "  num_tiles, cam_x, cam_y, dir_x, dir_y, plane_x, plane_y,\n"
     "  part_data (14 doubles/particle), n_particles, dt, gravity"},
    {"depth_to_grayscale", py_depth_to_grayscale, METH_VARARGS,
     "Convert per-pixel depth buffer to grayscale visualisation.\n\n"
     "depth_to_grayscale(fb, depth_px, sw, sh, max_dist) -> None"},
    {"ssao_pass", py_ssao_pass, METH_O,
     "Apply screen-space ambient occlusion darkening to the framebuffer.\n\n"
     "ssao_pass(ctx_dict) -> None\n\n"
     "ctx_dict keys: fb, depth_px, sw, sh, strength, radius, bias"},
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
