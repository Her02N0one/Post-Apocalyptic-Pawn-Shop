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


/* ═══════════════════════════════════════════════════════════════════
 *  Screen-Space Ambient Occlusion (SSAO) Post-Pass
 * ═══════════════════════════════════════════════════════════════════
 *
 * For each pixel, sample depth_px at a fixed kernel of offsets within a
 * screen-space radius.  If neighbouring samples are significantly closer
 * to the camera (indicating a concave corner or wall base), darken the
 * pixel.
 *
 * Dict keys:
 *   fb       : writable buffer uint8[sw*sh*3]
 *   depth_px : buffer float32[sw*sh]
 *   sw, sh   : int
 *   strength : double — occlusion darkening multiplier (0.0–1.0)
 *   radius   : int    — sample radius in pixels
 *   bias     : double — depth difference threshold to count as occluded
 *
 * Returns None.
 */
PyObject *
py_ssao_pass(PyObject *self, PyObject *dict)
{
    int sw, sh, radius;
    double strength, bias;

    Py_buffer fb_buf = {0};
    Py_buffer dp_buf = {0};

    PyObject *result = NULL;

    if (!PyDict_Check(dict)) {
        PyErr_SetString(PyExc_TypeError,
            "ssao_pass: argument must be a dict");
        return NULL;
    }

    if (dict_get_int(dict,    "sw",       &sw))       goto ssao_cleanup;
    if (dict_get_int(dict,    "sh",       &sh))       goto ssao_cleanup;
    if (dict_get_int(dict,    "radius",   &radius))   goto ssao_cleanup;
    if (dict_get_double(dict, "strength", &strength))  goto ssao_cleanup;
    if (dict_get_double(dict, "bias",     &bias))      goto ssao_cleanup;
    if (dict_get_buf(dict,    "fb",       &fb_buf, 1)) goto ssao_cleanup;
    if (dict_get_buf(dict,    "depth_px", &dp_buf, 0)) goto ssao_cleanup;

    {
    uint8_t     *fb    = (uint8_t *)fb_buf.buf;
    const float *depth = (const float *)dp_buf.buf;

    if (strength <= 0.0 || radius < 1) {
        result = Py_None;
        Py_INCREF(Py_None);
        goto ssao_cleanup;
    }

    /* Fixed 16-sample kernel — deterministic, no RNG needed.
     * Offsets are in a disc pattern at varying radii. */
    static const int N_SAMPLES = 16;
    static const double kernel[16][2] = {
        { 1.0,  0.0}, { 0.0,  1.0}, {-1.0,  0.0}, { 0.0, -1.0},
        { 0.71, 0.71}, {-0.71, 0.71}, {-0.71,-0.71}, { 0.71,-0.71},
        { 0.5,  0.0}, { 0.0,  0.5}, {-0.5,  0.0}, { 0.0, -0.5},
        { 0.38, 0.92}, {-0.92, 0.38}, { 0.92,-0.38}, {-0.38,-0.92},
    };

    /* Allocate occlusion buffer to avoid modifying fb while reading */
    double *occ = (double *)calloc(sw * sh, sizeof(double));
    if (!occ) {
        PyErr_NoMemory();
        goto ssao_cleanup;
    }

    /* Compute occlusion per pixel */
    for (int y = 0; y < sh; y++) {
        for (int x = 0; x < sw; x++) {
            float cd = depth[y * sw + x];
            if (cd >= (float)MAX_DEPTH || cd <= 0.0f) continue;

            /* Scale sample radius by inverse depth — closer pixels
             * get larger kernels for consistent world-space coverage */
            double scale = (double)radius / (1.0 + (double)cd * 0.5);
            if (scale < 1.0) scale = 1.0;

            int count = 0;
            for (int s = 0; s < N_SAMPLES; s++) {
                int sx = x + (int)(kernel[s][0] * scale);
                int sy = y + (int)(kernel[s][1] * scale);
                if (sx < 0 || sx >= sw || sy < 0 || sy >= sh) {
                    count++;  /* out-of-bounds = occluded */
                    continue;
                }
                float sd = depth[sy * sw + sx];
                if (sd < cd - (float)bias) {
                    count++;
                }
            }
            occ[y * sw + x] = (double)count / (double)N_SAMPLES;
        }
    }

    /* Apply occlusion to framebuffer */
    for (int i = 0; i < sw * sh; i++) {
        if (occ[i] <= 0.0) continue;
        double dark = 1.0 - occ[i] * strength;
        if (dark < 0.0) dark = 0.0;
        int off = i * 3;
        fb[off]   = (uint8_t)(fb[off]   * dark);
        fb[off+1] = (uint8_t)(fb[off+1] * dark);
        fb[off+2] = (uint8_t)(fb[off+2] * dark);
    }

    free(occ);

    } /* end scope block */

    result = Py_None;
    Py_INCREF(Py_None);

ssao_cleanup:
    if (fb_buf.buf) PyBuffer_Release(&fb_buf);
    if (dp_buf.buf) PyBuffer_Release(&dp_buf);
    return result;
}
