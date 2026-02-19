/*  systems/_fast_cast.c  —  C-accelerated DDA wall raycaster.
 *
 *  Compile:  python build_ext.py build_ext --inplace
 *  Import :  from systems._fast_cast import cast_walls
 *
 *  Accepts pre-built numpy/array buffers so that no Python object
 *  creation happens inside the hot DDA loop.
 */

#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <math.h>
#include <stdint.h>
#include <string.h>

#define MAX_STEPS 32
#define MAX_HALF  8

typedef struct {
    int    sx;
    double dist;
    int    h;
    int    tid;
    int    side;
    double tx;
    double hs;
    double rx, ry, wx;
} Hit;

/* ── fast_cast_walls ─────────────────────────────────────────────
 *
 * Arguments (positional):
 *   px, py          : float   — player position
 *   angle, fov      : float   — look direction and field of view
 *   sw, sh          : int     — screen width / height (internal res)
 *   map_h, map_w    : int     — tile grid dimensions
 *   tiles_buf       : buffer  — int32[map_h * map_w], row-major
 *   wall_buf        : buffer  — uint8[lut_len], 1 = wall
 *   half_buf        : buffer  — uint8[lut_len], 1 = half-wall
 *   hs_buf          : buffer  — float64[lut_len], height_scale per tid
 *   step            : int     — ray step (cast every Nth column)
 *
 * Returns a list of plain tuples, each with 10 elements matching
 * the WallSlice namedtuple fields.
 */
static PyObject *
fast_cast_walls(PyObject *self, PyObject *args)
{
    double px, py, angle, fov;
    int sw, sh, map_h, map_w, step;
    Py_buffer tiles_buf = {0};
    Py_buffer wall_buf  = {0};
    Py_buffer half_buf  = {0};
    Py_buffer hs_buf    = {0};

    if (!PyArg_ParseTuple(args, "ddddiiiiy*y*y*y*i",
            &px, &py, &angle, &fov,
            &sw, &sh, &map_h, &map_w,
            &tiles_buf, &wall_buf, &half_buf, &hs_buf,
            &step))
        goto cleanup_null;

    const int32_t  *tiles    = (const int32_t  *)tiles_buf.buf;
    const uint8_t  *wall_lut = (const uint8_t  *)wall_buf.buf;
    const uint8_t  *half_lut = (const uint8_t  *)half_buf.buf;
    const double   *hs_arr   = (const double   *)hs_buf.buf;
    const int       lut_len  = (int)(wall_buf.len);

    const int    n_rays   = (sw + step - 1) / step;
    const double half_fov = fov * 0.5;
    const double inv_sw   = 2.0 / (double)sw;

    PyObject *result = PyList_New(0);
    if (!result) goto cleanup_null;

    Hit half_hits[MAX_HALF];

    for (int col = 0; col < n_rays; col++) {
        const int    x  = col * step;
        const double ra = angle + ((double)x * inv_sw - 1.0) * half_fov;
        const double rx = cos(ra);
        const double ry = sin(ra);

        int mx = (int)px;
        int my = (int)py;

        const double arx  = fabs(rx);
        const double ary  = fabs(ry);
        const double dd_x = arx > 1e-10 ? 1.0 / arx : 1e10;
        const double dd_y = ary > 1e-10 ? 1.0 / ary : 1e10;

        int sx_s, sy_s;
        double sd_x, sd_y;
        if (rx < 0) { sx_s = -1; sd_x = (px - mx) * dd_x; }
        else        { sx_s =  1; sd_x = (mx + 1.0 - px) * dd_x; }
        if (ry < 0) { sy_s = -1; sd_y = (py - my) * dd_y; }
        else        { sy_s =  1; sd_y = (my + 1.0 - py) * dd_y; }

        const double hsx = (1 - sx_s) * 0.5;
        const double hsy = (1 - sy_s) * 0.5;

        int hit = 0, side = 0, n_half = 0;

        for (int s = 0; s < MAX_STEPS; s++) {
            if (sd_x < sd_y) { sd_x += dd_x; mx += sx_s; side = 0; }
            else              { sd_y += dd_y; my += sy_s; side = 1; }

            if (mx < 0 || mx >= map_w || my < 0 || my >= map_h) {
                if (!n_half) hit = 1;
                break;
            }

            const int tid = tiles[my * map_w + mx];
            if (tid < 0 || tid >= lut_len || !wall_lut[tid])
                continue;

            /* ── Half-wall: record and keep casting ──────── */
            if (half_lut[tid]) {
                double p;
                if (side == 0)
                    p = arx > 1e-10 ? (mx - px + hsx) / rx : 1e10;
                else
                    p = ary > 1e-10 ? (my - py + hsy) / ry : 1e10;
                if (p < 0.01) p = 0.01;
                double w = side == 0 ? py + p * ry : px + p * rx;
                if (n_half < MAX_HALF) {
                    Hit *h = &half_hits[n_half++];
                    h->sx = x;  h->dist = p;  h->h = (int)(sh / p);
                    h->tid = tid;  h->side = side;
                    h->tx = w - floor(w);
                    h->hs = hs_arr[tid];
                    h->rx = rx;  h->ry = ry;  h->wx = w;
                }
                continue;
            }
            /* ── Full wall ────────────────────────────────── */
            hit = 1;
            break;
        }

        if (!hit && !n_half) continue;

        /* Only half-walls, no full wall behind → far-to-near */
        if (!hit) {
            for (int i = n_half - 1; i >= 0; i--) {
                Hit *h = &half_hits[i];
                PyObject *t = Py_BuildValue("(idiiiddddd)",
                    h->sx, h->dist, h->h, h->tid, h->side,
                    h->tx, h->hs, h->rx, h->ry, h->wx);
                if (!t) goto cleanup_list;
                if (PyList_Append(result, t) < 0)
                    { Py_DECREF(t); goto cleanup_list; }
                Py_DECREF(t);
            }
            continue;
        }

        /* Full wall hit */
        double perp;
        if (side == 0)
            perp = arx > 1e-10 ? (mx - px + hsx) / rx : 1e10;
        else
            perp = ary > 1e-10 ? (my - py + hsy) / ry : 1e10;
        if (perp < 0.01) perp = 0.01;

        double wx_val = side == 0 ? py + perp * ry : px + perp * rx;
        int tid_hit = (mx >= 0 && mx < map_w && my >= 0 && my < map_h)
                    ? tiles[my * map_w + mx] : 0;
        double hs_hit = (tid_hit >= 0 && tid_hit < lut_len)
                      ? hs_arr[tid_hit] : 1.0;

        /* Emit full wall FIRST */
        {
            PyObject *t = Py_BuildValue("(idiiiddddd)",
                x, perp, (int)(sh / perp), tid_hit, side,
                wx_val - floor(wx_val), hs_hit, rx, ry, wx_val);
            if (!t) goto cleanup_list;
            if (PyList_Append(result, t) < 0)
                { Py_DECREF(t); goto cleanup_list; }
            Py_DECREF(t);
        }
        /* Then half-walls far-to-near */
        for (int i = n_half - 1; i >= 0; i--) {
            Hit *h = &half_hits[i];
            PyObject *t = Py_BuildValue("(idiiiddddd)",
                h->sx, h->dist, h->h, h->tid, h->side,
                h->tx, h->hs, h->rx, h->ry, h->wx);
            if (!t) goto cleanup_list;
            if (PyList_Append(result, t) < 0)
                { Py_DECREF(t); goto cleanup_list; }
            Py_DECREF(t);
        }
    }

    /* Success */
    PyBuffer_Release(&tiles_buf);
    PyBuffer_Release(&wall_buf);
    PyBuffer_Release(&half_buf);
    PyBuffer_Release(&hs_buf);
    return result;

cleanup_list:
    Py_DECREF(result);
cleanup_null:
    if (tiles_buf.buf) PyBuffer_Release(&tiles_buf);
    if (wall_buf.buf)  PyBuffer_Release(&wall_buf);
    if (half_buf.buf)  PyBuffer_Release(&half_buf);
    if (hs_buf.buf)    PyBuffer_Release(&hs_buf);
    return NULL;
}


/* ── Module definition ───────────────────────────────────────── */

static PyMethodDef methods[] = {
    {"cast_walls", fast_cast_walls, METH_VARARGS,
     "Fast DDA wall raycaster returning list of 10-element tuples."},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef moduledef = {
    PyModuleDef_HEAD_INIT,
    "_fast_cast",
    "C-accelerated DDA raycaster for the first-person renderer.",
    -1,
    methods
};

PyMODINIT_FUNC
PyInit__fast_cast(void)
{
    return PyModule_Create(&moduledef);
}
