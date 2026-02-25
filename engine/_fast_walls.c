/*  systems/_fast_walls.c  —  C-accelerated wall geometry computation.
 *
 *  Compile:  python build_ext.py build_ext --inplace
 *  Import :  from systems._fast_walls import compute_wall_geometry
 *
 *  Takes the slice list from cast_walls and pre-computes all
 *  per-slice geometry (cy0, cy1, draw_h_q, tv0, tv1, col_w, fog,
 *  cache_key, etc.) in a single C-level pass.  The Python caller
 *  only needs to do cache lookups and Surface operations.
 */

#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <math.h>
#include <stdint.h>

/* ── compute_wall_geometry ───────────────────────────────────────
 *
 * Arguments (positional):
 *   slices     : list of tuples — output of cast_walls()
 *   sh         : int   — screen height (internal res)
 *   half       : int   — sh // 2
 *   tex_size   : int   — texture size in pixels (e.g. 64)
 *   fog_lut    : bytes — 256 fog brightness values
 *   step       : int   — RAY_STEP (pixels per ray column)
 *   sw         : int   — screen width (internal res)
 *
 * Returns a list of tuples, one per visible slice:
 *
 *  idx  field       type    description
 *  ───  ──────────  ──────  ──────────────────────────────────
 *   0   sx          int     screen x
 *   1   dist        double  perpendicular distance
 *   2   cy0         int     clamped top y
 *   3   cy1         int     clamped bottom y
 *   4   draw_h      int     cy1 - cy0 (raw draw height)
 *   5   draw_h_q    int     quantised draw height (8px grid)
 *   6   tv0         int     texture V start
 *   7   tv1         int     texture V end
 *   8   col_w       int     column width (pixels)
 *   9   fog         int     fog brightness 0-255
 *  10   tx_s        int     texture X snapped to 4-col grid
 *  11   cache_key   int64   packed cache key
 *  12   tid         int     tile id
 *  13   side        int     0 = NS, 1 = EW
 *  14   hs          double  height scale
 *  15   is_full     int     1 = full wall, 0 = half wall
 *  16   ao_y        int     AO shadow y (0 if none)
 *  17   ao_h        int     AO shadow height (0 if none)
 *  18   has_vp      int     1 = half-wall with visplane above
 *  19   src_idx     int     original index into slices list
 *
 * Slices with draw_h < 1 are skipped (not emitted).
 */
static PyObject *
fast_compute_wall_geometry(PyObject *self, PyObject *args)
{
    PyObject   *slices_obj;
    int         sh, half, tex_size, step, sw;
    Py_buffer   fog_buf = {0};

    if (!PyArg_ParseTuple(args, "Oiiiy*ii",
            &slices_obj, &sh, &half, &tex_size,
            &fog_buf, &step, &sw))
        return NULL;

    if (!PyList_Check(slices_obj)) {
        PyBuffer_Release(&fog_buf);
        PyErr_SetString(PyExc_TypeError, "slices must be a list");
        return NULL;
    }

    const uint8_t *fog_lut = (const uint8_t *)fog_buf.buf;
    const int  tex_m1  = tex_size - 1;

    Py_ssize_t n = PyList_GET_SIZE(slices_obj);
    PyObject *result = PyList_New(0);
    if (!result) { PyBuffer_Release(&fog_buf); return NULL; }

    for (Py_ssize_t i = 0; i < n; i++) {
        PyObject *ws = PyList_GET_ITEM(slices_obj, i);

        int     ws_sx   = (int)PyLong_AsLong(PyTuple_GET_ITEM(ws, 0));
        double  ws_dist = PyFloat_AsDouble(PyTuple_GET_ITEM(ws, 1));
        int     ws_h    = (int)PyLong_AsLong(PyTuple_GET_ITEM(ws, 2));
        int     ws_tid  = (int)PyLong_AsLong(PyTuple_GET_ITEM(ws, 3));
        int     ws_side = (int)PyLong_AsLong(PyTuple_GET_ITEM(ws, 4));
        double  ws_tx   = PyFloat_AsDouble(PyTuple_GET_ITEM(ws, 5));
        double  ws_hs   = PyFloat_AsDouble(PyTuple_GET_ITEM(ws, 6));

        /* ── Geometry ─────────────────────────────────────── */
        double full_half_h = ws_h * 0.5;
        double full_top    = half - full_half_h;
        double full_bot    = half + full_half_h;

        double y_top, y_bot;
        int is_full;
        if (ws_hs < 0.99) {
            double scaled_h = ws_h * ws_hs;
            y_top = full_bot - scaled_h;
            y_bot = full_bot;
            is_full = 0;
        } else {
            y_top = full_top;
            y_bot = full_bot;
            is_full = 1;
        }

        int cy0 = (int)y_top;
        if (cy0 < 0) cy0 = 0;
        int cy1 = (int)y_bot;
        if (cy1 > sh) cy1 = sh;
        int draw_h = cy1 - cy0;
        if (draw_h < 1)
            continue;

        double actual_h = y_bot - y_top;
        double v0, v1;
        if (actual_h > 0) {
            v0 = (cy0 - y_top) / actual_h;
            v1 = (cy1 - y_top) / actual_h;
        } else {
            v0 = 0.0;
            v1 = 1.0;
        }

        int tv0 = (int)(v0 * tex_size);
        if (tv0 < 0) tv0 = 0;
        if (tv0 > tex_m1) tv0 = tex_m1;
        int tv1 = (int)(v1 * tex_size);
        if (tv1 < tv0 + 1) tv1 = tv0 + 1;
        if (tv1 > tex_size) tv1 = tex_size;

        int col_w = step;
        if (ws_sx + step > sw) col_w = sw - ws_sx;

        /* Fog from LUT */
        int fog_idx = (int)(ws_dist * 8.0);
        if (fog_idx < 0)   fog_idx = 0;
        if (fog_idx > 255) fog_idx = 255;
        int fog = fog_lut[fog_idx];

        /* Texture column — snap to 4-col grid */
        int tx = (int)(ws_tx * tex_size) & tex_m1;
        int tx_s = tx & ~3;

        /* Quantisation */
        int draw_h_q = (draw_h + 4) & ~7;
        if (draw_h_q < 8) draw_h_q = 8;
        int fog_q = fog >> 6;

        /* Packed cache key (matches Python packing exactly) */
        int64_t cache_key = (int64_t)ws_tid
                          | ((int64_t)tx_s << 10)
                          | ((int64_t)(tv1 - tv0) << 16)
                          | ((int64_t)draw_h_q << 23)
                          | ((int64_t)col_w << 33)
                          | ((int64_t)ws_side << 37)
                          | ((int64_t)fog_q << 38);

        /* AO rect (only for full walls close enough) */
        int ao_y = 0, ao_h = 0;
        if (is_full && ws_dist < 6.0 && cy1 < sh) {
            int ao_raw = draw_h >> 3;
            if (ao_raw < 1) ao_raw = 1;
            if (ao_raw > 6) ao_raw = 6;
            ao_h = ao_raw;
            if (ao_h > sh - cy1) ao_h = sh - cy1;
            if (ao_h > 0) ao_y = cy1;
            else ao_h = 0;
        }

        /* has_vp: half-wall with visplane platform above */
        int has_vp = 0;
        if (!is_full && cy0 > 0 && cy0 < sh) {
            double delta_h = 0.5 - ws_hs;
            if (delta_h > 0.01 && cy0 > half)
                has_vp = 1;
        }

        /* Build result tuple — 20 fields */
        PyObject *t = Py_BuildValue("(idiiiiiiiiiLiidiiiin)",
            ws_sx,        /*  0  sx          */
            ws_dist,      /*  1  dist        */
            cy0,          /*  2  cy0         */
            cy1,          /*  3  cy1         */
            draw_h,       /*  4  draw_h      */
            draw_h_q,     /*  5  draw_h_q    */
            tv0,          /*  6  tv0         */
            tv1,          /*  7  tv1         */
            col_w,        /*  8  col_w       */
            fog,          /*  9  fog         */
            tx_s,         /* 10  tx_s        */
            cache_key,    /* 11  cache_key   */
            ws_tid,       /* 12  tid         */
            ws_side,      /* 13  side        */
            ws_hs,        /* 14  hs          */
            is_full,      /* 15  is_full     */
            ao_y,         /* 16  ao_y        */
            ao_h,         /* 17  ao_h        */
            has_vp,       /* 18  has_vp      */
            i             /* 19  src_idx     */
        );
        if (!t) goto cleanup;
        if (PyList_Append(result, t) < 0) {
            Py_DECREF(t);
            goto cleanup;
        }
        Py_DECREF(t);
    }

    PyBuffer_Release(&fog_buf);
    return result;

cleanup:
    Py_DECREF(result);
    PyBuffer_Release(&fog_buf);
    return NULL;
}


/* ── Module definition ───────────────────────────────────────── */

static PyMethodDef methods[] = {
    {"compute_wall_geometry", fast_compute_wall_geometry, METH_VARARGS,
     "Batch-compute wall column geometry for all slices."},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef moduledef = {
    PyModuleDef_HEAD_INIT,
    "_fast_walls",
    "C-accelerated wall geometry for the first-person renderer.",
    -1,
    methods
};

PyMODINIT_FUNC
PyInit__fast_walls(void)
{
    return PyModule_Create(&moduledef);
}
