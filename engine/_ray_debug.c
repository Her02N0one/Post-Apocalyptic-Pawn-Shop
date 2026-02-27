/*  engine/_ray_debug.c  —  Debug visualization helpers.
 *
 *  Depth-buffer-to-grayscale conversion for debugging.
 *
 *  Separated from _ray_render.c for maintainability.
 *  Shares types and helpers via _ray_render.h.
 */

#include "_ray_render.h"

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
PyObject *
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
