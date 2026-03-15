"""engine/render_schema.py — Schema validation for C renderer dicts.

The C extension functions (``render_frame``, ``render_entities``,
``render_particles``, ``ssao_pass``) accept Python dicts with dozens
of buffer/scalar keys.  A missing key, wrong dtype, or shape mismatch
produces a C-level crash or silent corruption.

This module defines the expected schema for each C entry point and
provides a ``validate()`` function that raises a descriptive
``RenderSchemaError`` before any data reaches C code.

Usage::

    from engine.render_schema import validate_render_frame

    ctx = { ... }
    validate_render_frame(ctx)     # raises RenderSchemaError on mismatch
    _c_render_frame(ctx)           # safe to call

Validation is **opt-in** — call it in debug/development builds.
In production, skip it for zero overhead.
"""

from __future__ import annotations

import struct
from typing import Any


class RenderSchemaError(Exception):
    """Raised when a render context dict violates the expected schema."""


# ── Field descriptors ─────────────────────────────────────────────

# Type tags used in the schema tables below.
INT = "int"
FLOAT = "float"
BUF_R = "buf_r"     # readonly buffer (bytes)
BUF_W = "buf_w"     # writable buffer (bytearray)
OPT_INT = "opt_int"
OPT_FLOAT = "opt_float"
OPT_BUF = "opt_buf"   # optional buffer (bytes | bytearray | None)
OPT_TUPLE = "opt_tuple"  # optional tuple (e.g. sky_color)

# Each entry: (key, type_tag, size_expr_or_None)
# size_expr is a string evaluated against the ctx dict to compute
# expected byte length.  None means no size check.

# ── render_frame schema ───────────────────────────────────────────

RENDER_FRAME_REQUIRED: list[tuple[str, str, str | None]] = [
    # Writable outputs
    ("fb",       BUF_W, "sw * sh * 3"),
    ("zbuf",     BUF_W, "sw * 8"),
    ("depth_px", BUF_W, "sw * sh * 4"),
    # Camera
    ("cam_x",    FLOAT, None),
    ("cam_y",    FLOAT, None),
    ("cam_angle", FLOAT, None),
    ("cam_fov",  FLOAT, None),
    ("cam_h",    FLOAT, None),
    ("horizon_shift", INT, None),
    # Dimensions
    ("sw",      INT, None),
    ("sh",      INT, None),
    ("map_w",   INT, None),
    ("map_h",   INT, None),
    ("tex_size", INT, None),
    ("num_tiles", INT, None),
    ("is_interior", INT, None),
    # Core grids (all flat, map_h * map_w)
    ("tiles",     BUF_R, "map_h * map_w * 4"),
    ("walls",     BUF_R, "map_h * map_w"),
    ("floor_h",   BUF_R, "map_h * map_w * 8"),
    ("ceil_h",    BUF_R, "map_h * map_w * 8"),
    ("floor_tex", BUF_R, "map_h * map_w * 4"),
    ("ceil_tex",  BUF_R, "map_h * map_w * 4"),
    ("light",     BUF_R, "map_h * map_w * 8"),
    # Atlas
    ("atlas",    BUF_R, "num_tiles * tex_size * tex_size * 4"),
    ("fog_lut",  BUF_R, "256"),
    # LUTs (per tile-type — sized by num_tiles)
    ("thin_lut", BUF_R, None),
    ("tall_lut", BUF_R, None),
    ("hs_lut",   BUF_R, None),
    ("trans_lut", BUF_R, None),
    ("alt_tex",  BUF_R, None),
    ("vscale",   BUF_R, None),
    ("anim_lut", BUF_R, None),
    # Per-cell face textures
    ("face_tex", BUF_R, "map_h * map_w * 4 * 4"),
    # Overlay walls
    ("overlay",   BUF_R, None),
    ("n_overlay", INT, None),
    # Wall segments
    ("seg_off",  BUF_R, None),
    ("seg_cnt",  BUF_R, None),
    ("seg_tex",  BUF_R, None),
    ("seg_ytop", BUF_R, None),
    ("n_total_segs", INT, None),
    # Step-wall textures
    ("fstep_tex", BUF_R, "map_h * map_w * 4 * 4"),
    ("cstep_tex", BUF_R, "map_h * map_w * 4 * 4"),
    ("uwh",       BUF_R, "map_h * map_w * 8"),
    # Step-wall segments (floor)
    ("fstep_seg_off",  BUF_R, None),
    ("fstep_seg_cnt",  BUF_R, None),
    ("fstep_seg_tex",  BUF_R, None),
    ("fstep_seg_ytop", BUF_R, None),
    ("n_fstep_segs",   INT, None),
    # Step-wall segments (ceiling)
    ("cstep_seg_off",  BUF_R, None),
    ("cstep_seg_cnt",  BUF_R, None),
    ("cstep_seg_tex",  BUF_R, None),
    ("cstep_seg_ytop", BUF_R, None),
    ("n_cstep_segs",   INT, None),
    # Animation
    ("anim_tick", INT, None),
]

RENDER_FRAME_OPTIONAL: list[tuple[str, str, str | None]] = [
    # Skybox
    ("skybox",   OPT_BUF, None),
    ("sky_w",    OPT_INT, None),
    ("sky_h",    OPT_INT, None),
    ("sky_vspan", OPT_FLOAT, None),
    ("sky_color", OPT_TUPLE, None),
    # Fog volumes
    ("fog_density", OPT_BUF, None),
    ("fog_color",   OPT_BUF, None),
    # Lens distortion
    ("lens",     OPT_BUF, None),
    # Point lights
    ("point_lights", OPT_BUF, None),
    ("n_lights",     OPT_INT, None),
    # Decals
    ("decals",   OPT_BUF, None),
    ("n_decals", OPT_INT, None),
    # Bump mapping
    ("bump_strength", OPT_FLOAT, None),
    # Quads
    ("quad_data", OPT_BUF, None),
    ("n_quads",   OPT_INT, None),
    # Boxes
    ("box_data",  OPT_BUF, None),
    ("n_boxes",   OPT_INT, None),
    # Reflective floors
    ("reflect_flags", OPT_BUF, None),
    # Curves
    ("curve_data", OPT_BUF, None),
    ("n_curves",   OPT_INT, None),
    # Slopes
    ("slope_data", OPT_BUF, None),
    ("slope_div",  OPT_BUF, None),
    # Multi-layer
    ("fheight2", OPT_BUF, None),
    ("cheight2", OPT_BUF, None),
    ("ftex2",    OPT_BUF, None),
    ("ctex2",    OPT_BUF, None),
    ("uwh2",     OPT_BUF, None),
    # Portal rendering
    ("portal_map",  OPT_BUF, None),
    ("portal_data", OPT_BUF, None),
    ("n_portals",   OPT_INT, None),
]


# ── render_entities schema ────────────────────────────────────────

RENDER_ENTITIES_REQUIRED: list[tuple[str, str, str | None]] = [
    ("fb",       BUF_W, "sw * sh * 3"),
    ("sw",       INT, None),
    ("sh",       INT, None),
    ("cam_x",    FLOAT, None),
    ("cam_y",    FLOAT, None),
    ("dir_x",    FLOAT, None),
    ("dir_y",    FLOAT, None),
    ("plane_x",  FLOAT, None),
    ("plane_y",  FLOAT, None),
    ("depth_px", BUF_W, "sw * sh * 4"),
    ("fog_lut",  BUF_R, "256"),
    ("atlas",    BUF_R, "num_tiles * tex_size * tex_size * 4"),
    ("tex_size", INT, None),
    ("num_tiles", INT, None),
    ("ent_data", BUF_R, None),
    ("n_ents",   INT, None),
]

RENDER_ENTITIES_OPTIONAL: list[tuple[str, str, str | None]] = [
    ("horizon_shift", OPT_INT, None),
    ("cam_h",         OPT_FLOAT, None),
]


# ── render_particles schema ──────────────────────────────────────

RENDER_PARTICLES_REQUIRED: list[tuple[str, str, str | None]] = [
    ("fb",          BUF_W, "sw * sh * 3"),
    ("depth_px",    BUF_W, "sw * sh * 4"),
    ("fog_lut",     BUF_R, "256"),
    ("atlas",       BUF_R, "num_tiles * tex_size * tex_size * 4"),
    ("sw",          INT, None),
    ("sh",          INT, None),
    ("tex_size",    INT, None),
    ("num_tiles",   INT, None),
    ("cam_x",       FLOAT, None),
    ("cam_y",       FLOAT, None),
    ("dir_x",       FLOAT, None),
    ("dir_y",       FLOAT, None),
    ("plane_x",     FLOAT, None),
    ("plane_y",     FLOAT, None),
    ("part_data",   BUF_W, None),
    ("n_particles", INT, None),
    ("dt",          FLOAT, None),
    ("gravity",     FLOAT, None),
]

RENDER_PARTICLES_OPTIONAL: list[tuple[str, str, str | None]] = [
    ("horizon_shift", OPT_INT, None),
    ("cam_h",         OPT_FLOAT, None),
]


# ── ssao_pass schema ─────────────────────────────────────────────

SSAO_REQUIRED: list[tuple[str, str, str | None]] = [
    ("fb",       BUF_W, "sw * sh * 3"),
    ("depth_px", BUF_R, "sw * sh * 4"),
    ("sw",       INT, None),
    ("sh",       INT, None),
    ("strength", FLOAT, None),
    ("radius",   INT, None),
    ("bias",     FLOAT, None),
]


# ── Validation engine ────────────────────────────────────────────

def _eval_size(expr: str, ctx: dict[str, Any]) -> int:
    """Evaluate a size expression against scalar values from ctx."""
    # Build a namespace of only the integer/float scalars
    ns: dict[str, int] = {}
    for k, v in ctx.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            ns[k] = int(v)
    return int(eval(expr, {"__builtins__": {}}, ns))


def _check_field(
    ctx: dict[str, Any],
    key: str,
    type_tag: str,
    size_expr: str | None,
    errors: list[str],
) -> None:
    """Validate a single field in the context dict."""
    optional = type_tag.startswith("opt_")
    val = ctx.get(key)

    if val is None:
        if not optional:
            errors.append(f"Missing required key '{key}'")
        return

    # Type checks
    if type_tag in (INT, OPT_INT):
        if not isinstance(val, int) or isinstance(val, bool):
            errors.append(
                f"Key '{key}': expected int, got {type(val).__name__}"
            )
    elif type_tag in (FLOAT, OPT_FLOAT):
        if not isinstance(val, (int, float)) or isinstance(val, bool):
            errors.append(
                f"Key '{key}': expected float, got {type(val).__name__}"
            )
    elif type_tag in (BUF_R, OPT_BUF):
        if not isinstance(val, (bytes, bytearray, memoryview)):
            errors.append(
                f"Key '{key}': expected buffer (bytes/bytearray), "
                f"got {type(val).__name__}"
            )
    elif type_tag == OPT_TUPLE:
        if not isinstance(val, tuple):
            errors.append(
                f"Key '{key}': expected tuple, "
                f"got {type(val).__name__}"
            )
    elif type_tag == BUF_W:
        if not isinstance(val, (bytearray, memoryview)):
            errors.append(
                f"Key '{key}': expected writable buffer (bytearray), "
                f"got {type(val).__name__}"
            )

    # Size check (only for buffers with an expression)
    if size_expr and isinstance(val, (bytes, bytearray, memoryview)):
        try:
            expected = _eval_size(size_expr, ctx)
            actual = len(val)
            if actual != expected:
                errors.append(
                    f"Key '{key}': buffer size mismatch — "
                    f"expected {expected} bytes ({size_expr}), got {actual}"
                )
        except Exception:
            pass  # size expression couldn't be evaluated (missing deps)


def _validate(
    ctx: dict[str, Any],
    required: list[tuple[str, str, str | None]],
    optional: list[tuple[str, str, str | None]],
    name: str,
) -> None:
    """Validate a context dict against a schema.  Raises on failure."""
    errors: list[str] = []

    for key, type_tag, size_expr in required:
        _check_field(ctx, key, type_tag, size_expr, errors)

    for key, type_tag, size_expr in optional:
        _check_field(ctx, key, type_tag, size_expr, errors)

    # Check for unknown keys (potential typos)
    known = {k for k, _, _ in required} | {k for k, _, _ in optional}
    unknown = set(ctx.keys()) - known
    if unknown:
        errors.append(f"Unknown keys: {sorted(unknown)}")

    if errors:
        msg = f"[{name}] Schema validation failed:\n  " + "\n  ".join(errors)
        raise RenderSchemaError(msg)


# ── Public API ────────────────────────────────────────────────────

def validate_render_frame(ctx: dict[str, Any]) -> None:
    """Validate a render_frame context dict."""
    _validate(ctx, RENDER_FRAME_REQUIRED, RENDER_FRAME_OPTIONAL,
              "render_frame")


def validate_render_entities(ctx: dict[str, Any]) -> None:
    """Validate a render_entities context dict."""
    _validate(ctx, RENDER_ENTITIES_REQUIRED, RENDER_ENTITIES_OPTIONAL,
              "render_entities")


def validate_render_particles(ctx: dict[str, Any]) -> None:
    """Validate a render_particles context dict."""
    _validate(ctx, RENDER_PARTICLES_REQUIRED, RENDER_PARTICLES_OPTIONAL,
              "render_particles")


def validate_ssao(ctx: dict[str, Any]) -> None:
    """Validate an ssao_pass context dict."""
    _validate(ctx, SSAO_REQUIRED, [], "ssao_pass")


# ── Introspection helpers ─────────────────────────────────────────

_ENTRY_POINTS: dict[str, tuple[list, list]] = {
    "render_frame": (RENDER_FRAME_REQUIRED, RENDER_FRAME_OPTIONAL),
    "render_entities": (RENDER_ENTITIES_REQUIRED, RENDER_ENTITIES_OPTIONAL),
    "render_particles": (RENDER_PARTICLES_REQUIRED, RENDER_PARTICLES_OPTIONAL),
    "ssao_pass": (SSAO_REQUIRED, []),
}


def schema_keys_for(entry_point: str) -> set[str]:
    """Return the full set of known keys (required + optional) for an entry point.

    Raises :class:`KeyError` if *entry_point* is not recognised.

    >>> "cam_x" in schema_keys_for("render_frame")
    True
    """
    req, opt = _ENTRY_POINTS[entry_point]
    return {k for k, _, _ in req} | {k for k, _, _ in opt}


def all_schema_keys() -> set[str]:
    """Return the union of all known keys across every entry point."""
    out: set[str] = set()
    for req, opt in _ENTRY_POINTS.values():
        out |= {k for k, _, _ in req}
        out |= {k for k, _, _ in opt}
    return out


def check_context_completeness(
    ctx: dict[str, Any],
    entry_point: str,
) -> list[str]:
    """Return a list of required keys missing from *ctx* (empty = ok).

    Unlike :func:`validate_render_frame` this does **not** raise; it
    returns a plain list so callers can decide how to handle it.
    """
    req, _ = _ENTRY_POINTS[entry_point]
    return [k for k, _, _ in req if k not in ctx]


# ── Always-on fast required-key checks ───────────────────────────
# These are cheap (frozenset membership) and run even in production.
# They prevent C-level crashes from missing keys.

_RF_KEYS = frozenset(k for k, _, _ in RENDER_FRAME_REQUIRED)
_RE_KEYS = frozenset(k for k, _, _ in RENDER_ENTITIES_REQUIRED)
_RP_KEYS = frozenset(k for k, _, _ in RENDER_PARTICLES_REQUIRED)
_SSAO_KEYS = frozenset(k for k, _, _ in SSAO_REQUIRED)

_FAST_CHECK: dict[str, frozenset[str]] = {
    "render_frame": _RF_KEYS,
    "render_entities": _RE_KEYS,
    "render_particles": _RP_KEYS,
    "ssao_pass": _SSAO_KEYS,
}


def assert_required_keys(ctx: dict[str, Any], entry_point: str) -> None:
    """Raise :class:`RenderSchemaError` if any required key is missing.

    This is a **fast** check (frozenset difference) intended to run
    unconditionally — even in production builds.  It does NOT check
    types or buffer sizes; that's what the full validators are for.
    """
    required = _FAST_CHECK[entry_point]
    missing = required - ctx.keys()
    if missing:
        raise RenderSchemaError(
            f"[{entry_point}] Missing required keys: {sorted(missing)}"
        )
