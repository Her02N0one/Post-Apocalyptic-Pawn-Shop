/*  systems/_fast_cast.c  —  C-accelerated DDA wall raycaster.
 *
 *  Compile:  python build_ext.py build_ext --inplace
 *  Import :  from systems._fast_cast import cast_walls
 *
 *  Accepts pre-built numpy/array buffers so that no Python object
 *  creation happens inside the hot DDA loop.
 *
 *  Returns 13-element tuples matching WallSlice namedtuple:
 *    (screen_x, distance, height, tile_id, side, tex_x, height_scale,
 *     ray_dir_x, ray_dir_y, wall_x, map_x, map_y, face)
 */

#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <math.h>
#include <stdint.h>
#include <string.h>

#define MAX_STEPS 32
#define MAX_HALF  8
#define MAX_TRANS 4

/* Face constants — must match core/types.py */
#define FACE_NORTH 0
#define FACE_SOUTH 1
#define FACE_EAST  2
#define FACE_WEST  3

typedef struct {
    int    sx;
    double dist;
    int    h;
    int    tid;
    int    side;
    double tx;
    double hs;
    double rx, ry, wx;
    int    map_x, map_y, face;
} Hit;

static inline int face_from_side(int side, double rdx, double rdy) {
    if (side == 0) return rdx > 0 ? FACE_WEST : FACE_EAST;
    else           return rdy > 0 ? FACE_NORTH : FACE_SOUTH;
}

static inline PyObject *hit_to_tuple(const Hit *h) {
    return Py_BuildValue("(idiiidddddiid)",
        h->sx, h->dist, h->h, h->tid, h->side,
        h->tx, h->hs, h->rx, h->ry, h->wx,
        h->map_x, h->map_y, h->face);
}

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
 *   trans_buf       : buffer  — uint8[lut_len], 1 = transparent
 *   thin_buf        : buffer  — uint8[lut_len], 1 = thin wall
 *   step            : int     — ray step (cast every Nth column)
 *
 * Returns a list of 13-element tuples matching WallSlice.
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
    Py_buffer trans_buf = {0};
    Py_buffer thin_buf  = {0};

    if (!PyArg_ParseTuple(args, "ddddiiiiy*y*y*y*y*y*i",
            &px, &py, &angle, &fov,
            &sw, &sh, &map_h, &map_w,
            &tiles_buf, &wall_buf, &half_buf, &hs_buf,
            &trans_buf, &thin_buf,
            &step))
        goto cleanup_null;

    const int32_t  *tiles     = (const int32_t  *)tiles_buf.buf;
    const uint8_t  *wall_lut  = (const uint8_t  *)wall_buf.buf;
    const uint8_t  *half_lut  = (const uint8_t  *)half_buf.buf;
    const double   *hs_arr    = (const double   *)hs_buf.buf;
    const uint8_t  *trans_lut = (const uint8_t  *)trans_buf.buf;
    const uint8_t  *thin_lut  = (const uint8_t  *)thin_buf.buf;
    const int       lut_len   = (int)(wall_buf.len);

    const int    n_rays   = (sw + step - 1) / step;
    const double half_fov = fov * 0.5;
    const double inv_sw   = 2.0 / (double)sw;

    PyObject *result = PyList_New(0);
    if (!result) goto cleanup_null;

    Hit half_hits[MAX_HALF];
    Hit trans_hits[MAX_TRANS];

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

        int hit = 0, side = 0, n_half = 0, n_trans = 0;

        for (int s = 0; s < MAX_STEPS; s++) {
            if (sd_x < sd_y) { sd_x += dd_x; mx += sx_s; side = 0; }
            else              { sd_y += dd_y; my += sy_s; side = 1; }

            if (mx < 0 || mx >= map_w || my < 0 || my >= map_h) {
                if (!n_half && !n_trans) hit = 1;
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
                    h->map_x = mx;  h->map_y = my;
                    h->face = face_from_side(side, rx, ry);
                }
                continue;
            }

            /* ── Transparent wall: record and keep casting ── */
            if (trans_lut[tid] && n_trans < MAX_TRANS) {
                double p;
                if (side == 0)
                    p = arx > 1e-10 ? (mx - px + hsx) / rx : 1e10;
                else
                    p = ary > 1e-10 ? (my - py + hsy) / ry : 1e10;
                if (p < 0.01) p = 0.01;
                double w = side == 0 ? py + p * ry : px + p * rx;
                Hit *h = &trans_hits[n_trans++];
                h->sx = x;  h->dist = p;  h->h = (int)(sh / p);
                h->tid = tid;  h->side = side;
                h->tx = w - floor(w);
                h->hs = hs_arr[tid];
                h->rx = rx;  h->ry = ry;  h->wx = w;
                h->map_x = mx;  h->map_y = my;
                h->face = face_from_side(side, rx, ry);
                continue;
            }

            /* ── Thin wall: mid-cell intersection, keep casting ── */
            if (thin_lut[tid]) {
                double mid, p_mid;
                if (side == 0) {
                    mid = mx + 0.5;
                    p_mid = arx > 1e-10 ? (mid - px) / rx : 1e10;
                } else {
                    mid = my + 0.5;
                    p_mid = ary > 1e-10 ? (mid - py) / ry : 1e10;
                }
                if (p_mid > 0.01) {
                    double w = side == 0 ? py + p_mid * ry : px + p_mid * rx;
                    if (n_half < MAX_HALF) {
                        Hit *h = &half_hits[n_half++];
                        h->sx = x;  h->dist = p_mid;  h->h = (int)(sh / p_mid);
                        h->tid = tid;  h->side = side;
                        h->tx = w - floor(w);
                        h->hs = hs_arr[tid];
                        h->rx = rx;  h->ry = ry;  h->wx = w;
                        h->map_x = mx;  h->map_y = my;
                        h->face = face_from_side(side, rx, ry);
                    }
                }
                continue;
            }

            /* ── Full solid wall ──────────────────────────── */
            hit = 1;
            break;
        }

        if (!hit && !n_half && !n_trans) continue;

        /* Only deferred hits, no solid wall behind */
        if (!hit) {
            for (int i = n_trans - 1; i >= 0; i--) {
                PyObject *t = hit_to_tuple(&trans_hits[i]);
                if (!t) goto cleanup_list;
                if (PyList_Append(result, t) < 0)
                    { Py_DECREF(t); goto cleanup_list; }
                Py_DECREF(t);
            }
            for (int i = n_half - 1; i >= 0; i--) {
                PyObject *t = hit_to_tuple(&half_hits[i]);
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
            Hit h;
            h.sx = x;  h.dist = perp;  h.h = (int)(sh / perp);
            h.tid = tid_hit;  h.side = side;
            h.tx = wx_val - floor(wx_val);  h.hs = hs_hit;
            h.rx = rx;  h.ry = ry;  h.wx = wx_val;
            h.map_x = mx;  h.map_y = my;
            h.face = face_from_side(side, rx, ry);
            PyObject *t = hit_to_tuple(&h);
            if (!t) goto cleanup_list;
            if (PyList_Append(result, t) < 0)
                { Py_DECREF(t); goto cleanup_list; }
            Py_DECREF(t);
        }
        /* Then transparent hits far-to-near */
        for (int i = n_trans - 1; i >= 0; i--) {
            PyObject *t = hit_to_tuple(&trans_hits[i]);
            if (!t) goto cleanup_list;
            if (PyList_Append(result, t) < 0)
                { Py_DECREF(t); goto cleanup_list; }
            Py_DECREF(t);
        }
        /* Then half-walls far-to-near */
        for (int i = n_half - 1; i >= 0; i--) {
            PyObject *t = hit_to_tuple(&half_hits[i]);
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
    PyBuffer_Release(&trans_buf);
    PyBuffer_Release(&thin_buf);
    return result;

cleanup_list:
    Py_DECREF(result);
cleanup_null:
    if (tiles_buf.buf)  PyBuffer_Release(&tiles_buf);
    if (wall_buf.buf)   PyBuffer_Release(&wall_buf);
    if (half_buf.buf)   PyBuffer_Release(&half_buf);
    if (hs_buf.buf)     PyBuffer_Release(&hs_buf);
    if (trans_buf.buf)  PyBuffer_Release(&trans_buf);
    if (thin_buf.buf)   PyBuffer_Release(&thin_buf);
    return NULL;
}


/* ── Module definition ───────────────────────────────────────── */

static PyMethodDef methods[] = {
    {"cast_walls", fast_cast_walls, METH_VARARGS,
     "Fast DDA wall raycaster returning list of 13-element tuples."},
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
