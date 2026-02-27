/*  engine/_ray_entities.c  —  Entity billboard renderer.
 *
 *  Renders entity sprites/billboards with z-buffer clipping,
 *  fog, and per-pixel depth testing.
 *
 *  Separated from _ray_render.c for maintainability.
 *  Shares all types and inline helpers via _ray_render.h.
 */

#include "_ray_render.h"

/* ═══════════════════════════════════════════════════════════════════
 *  Entity billboard rendering
 * ═══════════════════════════════════════════════════════════════════
 *
 * Dict keys:
 *   fb          : writable buffer uint8[sw*sh*3]
 *   sw, sh      : int
 *   cam_x, cam_y: double  — camera position
 *   dir_x, dir_y: double  — camera direction unit vector
 *   plane_x, plane_y : double — camera plane vector
 *   depth_px    : buffer float32[sw*sh] — per-pixel depth (from render_frame)
 *   fog_lut     : buffer uint8[256]
 *   atlas       : buffer uint8[num_tiles * ts * ts * 4] — tile atlas
 *   tex_size    : int — texture side length (e.g. 64)
 *   num_tiles   : int — number of tiles in atlas
 *   ent_data    : buffer double[n * 12] — packed entity data:
 *                   [x, y, r, g, b, h_scale, w_scale, base_tex,
 *                    facing_angle, n_facings, anim_offset, flags]
 *                   per entity
 *   n_ents      : int — number of entities
 *
 * Returns None.
 */
PyObject *
py_render_entities(PyObject *self, PyObject *dict)
{
    int sw, sh, n_ents, tex_size, num_tiles;
    double cam_x, cam_y, dir_x, dir_y, plane_x, plane_y;

    Py_buffer fb_buf   = {0};
    Py_buffer depth_px_buf = {0};
    Py_buffer fog_buf  = {0};
    Py_buffer atlas_buf = {0};
    Py_buffer ent_buf  = {0};

    PyObject *result = NULL;

    /* Sort struct + pointer (declared here for cleanup visibility) */
    typedef struct { int idx; double dist; } EntSort;
    EntSort *sorted = NULL;

    if (!PyDict_Check(dict)) {
        PyErr_SetString(PyExc_TypeError,
            "render_entities: argument must be a dict");
        return NULL;
    }

    /* ── Extract scalars ─────────────────────────────────────────── */
    if (dict_get_int(dict, "sw",        &sw))        goto ent_cleanup;
    if (dict_get_int(dict, "sh",        &sh))        goto ent_cleanup;
    if (dict_get_int(dict, "tex_size",  &tex_size))  goto ent_cleanup;
    if (dict_get_int(dict, "num_tiles", &num_tiles)) goto ent_cleanup;
    if (dict_get_int(dict, "n_ents",    &n_ents))    goto ent_cleanup;
    if (dict_get_double(dict, "cam_x",   &cam_x))   goto ent_cleanup;
    if (dict_get_double(dict, "cam_y",   &cam_y))    goto ent_cleanup;
    if (dict_get_double(dict, "dir_x",   &dir_x))    goto ent_cleanup;
    if (dict_get_double(dict, "dir_y",   &dir_y))    goto ent_cleanup;
    if (dict_get_double(dict, "plane_x", &plane_x))  goto ent_cleanup;
    if (dict_get_double(dict, "plane_y", &plane_y))  goto ent_cleanup;

    /* ── Extract buffers ─────────────────────────────────────────── */
    if (dict_get_buf(dict, "fb",       &fb_buf,       1)) goto ent_cleanup;
    if (dict_get_buf(dict, "depth_px", &depth_px_buf, 1)) goto ent_cleanup;
    if (dict_get_buf(dict, "fog_lut",  &fog_buf,      0)) goto ent_cleanup;
    if (dict_get_buf(dict, "atlas",    &atlas_buf,    0)) goto ent_cleanup;
    if (dict_get_buf(dict, "ent_data", &ent_buf,      0)) goto ent_cleanup;

    {
    uint8_t       *fb      = (uint8_t *)fb_buf.buf;
    float         *depth_px = (float *)depth_px_buf.buf;
    const uint8_t *fog_lt  = (const uint8_t *)fog_buf.buf;
    const uint8_t *atlas   = (const uint8_t *)atlas_buf.buf;
    const double  *ent     = (const double *)ent_buf.buf;
    const int      ts      = tex_size;
    const int      ts_mask = ts - 1;

    /* Inverse determinant of the camera matrix */
    double inv_det = 1.0 / (plane_x * dir_y - dir_x * plane_y);

    /* Sort entities far-to-near using a simple index array + qsort.
     * For small entity counts this is fine. */
    sorted = (EntSort *)malloc(n_ents * sizeof(EntSort));
    if (!sorted && n_ents > 0) {
        PyErr_NoMemory();
        goto ent_cleanup;
    }

    for (int i = 0; i < n_ents; i++) {
        double ex = ent[i * 12 + 0];
        double ey = ent[i * 12 + 1];
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
        double ex = ent[ei * 12 + 0];
        double ey = ent[ei * 12 + 1];
        int    er = clampi((int)ent[ei * 12 + 2], 0, 255);
        int    eg = clampi((int)ent[ei * 12 + 3], 0, 255);
        int    eb = clampi((int)ent[ei * 12 + 4], 0, 255);
        double e_hscale = ent[ei * 12 + 5];
        double e_wscale = ent[ei * 12 + 6];
        int    base_tex = (int)ent[ei * 12 + 7];
        double facing_angle = ent[ei * 12 + 8];
        int    n_facings    = (int)ent[ei * 12 + 9];
        int    anim_offset  = (int)ent[ei * 12 + 10];
        /* int flags = (int)ent[ei * 12 + 11];  reserved */

        /* ── Multi-facing sprite selection ─────────────────────── */
        int e_tex_id;
        if (n_facings > 1 && base_tex >= 0) {
            /* Relative angle: direction from camera to entity minus
             * the entity's own facing angle.  Normalise to [0, 2π). */
            double rel = atan2(ey - cam_y, ex - cam_x) - facing_angle;
            rel = fmod(rel, 2.0 * M_PI);
            if (rel < 0.0) rel += 2.0 * M_PI;
            int frame = (int)(rel / (2.0 * M_PI) * n_facings);
            if (frame >= n_facings) frame = n_facings - 1;
            e_tex_id = base_tex + anim_offset + frame;
            /* Clamp to atlas bounds */
            if (e_tex_id < 0 || e_tex_id >= num_tiles)
                e_tex_id = base_tex;
        } else {
            e_tex_id = base_tex;
        }
        int has_tex = (e_tex_id >= 0 && e_tex_id < num_tiles);

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

                    int sr, sg, sb, sa;
                    sample_tex(atlas, ts, e_tex_id, tex_u, tex_v,
                               &sr, &sg, &sb, &sa);

                    /* Skip transparent texels (alpha or near-black) */
                    if (sa <= 0 || (sr + sg + sb < 15 && sa < 128)) continue;

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
                    put_depth(depth_px, sw, cx, cy, (float)ty);
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
                    put_depth(depth_px, sw, cx, cy, (float)ty);
                }
            }
        }
    }

    } /* end scope block */

    result = Py_None;
    Py_INCREF(Py_None);

ent_cleanup:
    if (fb_buf.buf)       PyBuffer_Release(&fb_buf);
    if (depth_px_buf.buf) PyBuffer_Release(&depth_px_buf);
    if (fog_buf.buf)      PyBuffer_Release(&fog_buf);
    if (atlas_buf.buf)    PyBuffer_Release(&atlas_buf);
    if (ent_buf.buf)      PyBuffer_Release(&ent_buf);
    free(sorted);
    return result;
}
