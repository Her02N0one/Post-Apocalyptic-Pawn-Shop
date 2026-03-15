"""core.zones.validation — Structured zone validation pass.

Takes a loaded :class:`Zone` and produces a list of :class:`ZoneIssue`
objects describing every error and warning *before* the zone reaches the
renderer or the game simulation.  This replaces the "load and pray" model
with a concrete gate between authoring and runtime.

Usage::

    from core.zones.validation import validate_zone

    issues = validate_zone(zone)
    errors = [i for i in issues if i.severity == "error"]
    if errors:
        raise RuntimeError(f"{len(errors)} validation errors")

Each check is an independent generator function so new checks can be added
without touching existing ones.

Optional keyword arguments control which expensive checks run (texture
asset existence needs the filesystem, entity-type resolution needs the
registry, etc.).  With no arguments, all purely-structural checks still run.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator
import math

_log = logging.getLogger(__name__)

# ── Issue dataclass ───────────────────────────────────────────────


@dataclass(frozen=True)
class ZoneIssue:
    """A single validation finding.

    Attributes
    ----------
    severity : ``"error"`` | ``"warning"``
        Errors indicate data that *will* cause crashes or incorrect
        behaviour.  Warnings indicate suspicious values that are technically
        representable but almost certainly unintended.
    category : str
        Machine-friendly tag for filtering (e.g. ``"geometry"``,
        ``"entity"``, ``"portal"``, ``"texture"``, ``"uid"``).
    message : str
        Human-readable description, specific enough to act on.
    location : str
        Optional cell/object locator, e.g. ``"cell (3, 7)"`` or
        ``"entity uid=42"``.
    """
    severity: str
    category: str
    message: str
    location: str = ""


# ── Public entry point ────────────────────────────────────────────


def validate_zone(
    zone: Any,
    *,
    entity_registry: dict[str, Any] | None = None,
    tile_registry: dict[str, Any] | None = None,
    texture_dir: Path | None = None,
) -> list[ZoneIssue]:
    """Run all validation checks on *zone* and return a list of issues.

    Parameters
    ----------
    zone
        A :class:`~core.zones.zone.Zone` instance.
    entity_registry
        If provided, entity ``type`` strings are checked against this
        mapping.  Pass ``entity_registry()`` from ``core.entity_defs``.
    tile_registry
        If provided, tile ID strings are checked against this mapping.
        Pass ``TILE_REGISTRY`` from ``core.tiles``.
    texture_dir
        If provided, texture key strings are checked for a corresponding
        ``.png`` file under this directory.  Pass ``core.paths.TILE_TEX_DIR``.

    Returns
    -------
    list[ZoneIssue]
        All findings, errors first, then warnings.  Empty list = clean.
    """
    issues: list[ZoneIssue] = []
    w, h = zone.width, zone.height

    for check in _ALL_CHECKS:
        issues.extend(check(zone, w, h,
                            entity_registry=entity_registry,
                            tile_registry=tile_registry,
                            texture_dir=texture_dir))

    # Stable sort: errors before warnings, then by category.
    issues.sort(key=lambda i: (0 if i.severity == "error" else 1, i.category))
    return issues


# ── Individual check functions ────────────────────────────────────
# Each yields ZoneIssue instances.  Signature:
#   (zone, w, h, *, entity_registry, tile_registry, texture_dir) → Iterator


def _check_grid_dimensions(
    zone: Any, w: int, h: int, **_kw: Any
) -> Iterator[ZoneIssue]:
    """Verify all 2D/3D grids match (width, height)."""
    _2d_fields = [
        "tiles", "rotations",
        "floor_heights", "ceil_heights",
        "floor_textures", "ceil_textures", "wall_textures",
        "light_levels", "reflect_map",
        "floor_slope_dx", "floor_slope_dy", "floor_slope_div",
        "floor2_heights", "ceil2_heights",
        "floor2_textures", "ceil2_textures",
        "upper_wall_height", "upper_wall_height2",
        "fog_density",
    ]
    for fname in _2d_fields:
        grid = getattr(zone, fname, None)
        if grid is None:
            continue
        rows = len(grid)
        if rows != h:
            yield ZoneIssue(
                "error", "grid",
                f"{fname} has {rows} rows, expected {h}",
            )
            continue
        for r, row in enumerate(grid):
            if len(row) != w:
                yield ZoneIssue(
                    "error", "grid",
                    f"{fname} row {r} has {len(row)} cols, expected {w}",
                    f"row {r}",
                )

    # 3D grids: [H][W][4]
    _3d_fields = [
        "face_textures",
        "floor_step_textures", "ceil_step_textures",
    ]
    for fname in _3d_fields:
        grid = getattr(zone, fname, None)
        if grid is None:
            continue
        rows = len(grid)
        if rows != h:
            yield ZoneIssue(
                "error", "grid",
                f"{fname} has {rows} rows, expected {h}",
            )
            continue
        for r, row in enumerate(grid):
            if len(row) != w:
                yield ZoneIssue(
                    "error", "grid",
                    f"{fname} row {r} has {len(row)} cols, expected {w}",
                    f"row {r}",
                )
                continue
            for c, cell in enumerate(row):
                if not isinstance(cell, (list, tuple)) or len(cell) != 4:
                    yield ZoneIssue(
                        "error", "grid",
                        f"{fname}[{r}][{c}] has {len(cell) if isinstance(cell, (list, tuple)) else 'non-list'} faces, expected 4",
                        f"cell ({r}, {c})",
                    )


def _check_geometry(
    zone: Any, w: int, h: int, **_kw: Any
) -> Iterator[ZoneIssue]:
    """Floor-above-ceiling, degenerate secondary layers."""
    _SENTINEL = -1000.0
    fh_grid = getattr(zone, "floor_heights", [])
    ch_grid = getattr(zone, "ceil_heights", [])
    f2_grid = getattr(zone, "floor2_heights", [])
    c2_grid = getattr(zone, "ceil2_heights", [])

    for r in range(h):
        if r >= len(fh_grid) or r >= len(ch_grid):
            break  # grid dimension errors caught by _check_grid_dimensions
        fh_row = fh_grid[r]
        ch_row = ch_grid[r]
        for c in range(w):
            if c >= len(fh_row) or c >= len(ch_row):
                break
            # Primary layer: floor above ceiling
            fh = fh_row[c]
            ch = ch_row[c]
            if fh > ch:
                yield ZoneIssue(
                    "warning", "geometry",
                    f"floor ({fh:.2f}) > ceiling ({ch:.2f})",
                    f"cell ({r}, {c})",
                )

            # Secondary layer consistency
            f2 = f2_grid[r][c] if r < len(f2_grid) and c < len(f2_grid[r]) else _SENTINEL
            c2 = c2_grid[r][c] if r < len(c2_grid) and c < len(c2_grid[r]) else _SENTINEL
            f2_active = f2 > _SENTINEL
            c2_active = c2 > _SENTINEL

            if f2_active and not c2_active:
                yield ZoneIssue(
                    "warning", "geometry",
                    f"secondary floor set ({f2:.2f}) but ceiling is sentinel",
                    f"cell ({r}, {c})",
                )
            elif c2_active and not f2_active:
                yield ZoneIssue(
                    "warning", "geometry",
                    f"secondary ceiling set ({c2:.2f}) but floor is sentinel",
                    f"cell ({r}, {c})",
                )
            elif f2_active and c2_active and f2 > c2:
                yield ZoneIssue(
                    "warning", "geometry",
                    f"secondary floor ({f2:.2f}) > secondary ceiling ({c2:.2f})",
                    f"cell ({r}, {c})",
                )


def _check_uid_uniqueness(
    zone: Any, w: int, h: int, **_kw: Any
) -> Iterator[ZoneIssue]:
    """All UIDs across all object lists must be unique and non-zero."""
    seen: dict[int, str] = {}  # uid → "kind #index"

    _LISTS = [
        ("entities", "entity"),
        ("boxes", "box"),
        ("quads", "quad"),
        ("curves", "curve"),
        ("render_portals", "portal"),
    ]

    for list_name, kind in _LISTS:
        objs = getattr(zone, list_name, [])
        for i, obj in enumerate(objs):
            uid = obj.get("uid", 0) if isinstance(obj, dict) else getattr(obj, "uid", 0)
            if uid == 0:
                yield ZoneIssue(
                    "warning", "uid",
                    f"{kind} #{i} has uid=0 (unassigned)",
                    f"{kind} #{i}",
                )
                continue
            label = f"{kind} #{i}"
            if uid in seen:
                yield ZoneIssue(
                    "error", "uid",
                    f"duplicate uid={uid}: {seen[uid]} and {label}",
                    label,
                )
            else:
                seen[uid] = label

    # Also check overlay walls
    for i, ow in enumerate(getattr(zone, "overlay_walls", [])):
        uid = getattr(ow, "uid", 0)
        if uid == 0:
            yield ZoneIssue("warning", "uid",
                            f"overlay_wall #{i} has uid=0", f"overlay_wall #{i}")
            continue
        label = f"overlay_wall #{i}"
        if uid in seen:
            yield ZoneIssue(
                "error", "uid",
                f"duplicate uid={uid}: {seen[uid]} and {label}",
                label,
            )
        else:
            seen[uid] = label


def _check_entities(
    zone: Any, w: int, h: int, *,
    entity_registry: dict[str, Any] | None = None,
    **_kw: Any,
) -> Iterator[ZoneIssue]:
    """Entity type validity, position bounds, required fields."""
    for i, ent in enumerate(getattr(zone, "entities", [])):
        _get = (lambda k, d=None: ent.get(k, d)) if hasattr(ent, "get") else (
            lambda k, d=None: getattr(ent, k, d))
        uid = _get("uid", 0)
        loc = f"entity uid={uid}" if uid else f"entity #{i}"
        etype = _get("type", "")

        # Missing type
        if not etype:
            yield ZoneIssue("error", "entity",
                            "entity has no type", loc)

        # Unknown type (only if registry provided)
        elif entity_registry is not None and etype not in entity_registry:
            yield ZoneIssue("warning", "entity",
                            f"unknown entity type '{etype}'", loc)

        # Position out of bounds (warning — entities can technically be
        # placed outside the grid for spawn-in effects)
        ex = float(_get("x", 0.0))
        ey = float(_get("y", 0.0))
        if ex < 0 or ex >= w or ey < 0 or ey >= h:
            yield ZoneIssue("warning", "entity",
                            f"position ({ex:.1f}, {ey:.1f}) outside grid "
                            f"[0, {w}) × [0, {h})",
                            loc)


def _check_render_portals(
    zone: Any, w: int, h: int, **_kw: Any
) -> Iterator[ZoneIssue]:
    """Render-portal cell bounds, face range, destination bounds."""
    for i, p in enumerate(getattr(zone, "render_portals", [])):
        _get = (lambda k, d=None, _p=p: _p.get(k, d)) if hasattr(p, "get") else (
            lambda k, d=None, _p=p: getattr(_p, k, d))
        uid = _get("uid", 0)
        loc = f"render_portal uid={uid}" if uid else f"render_portal #{i}"

        cell = _get("cell", [0, 0])
        if isinstance(cell, (list, tuple)) and len(cell) >= 2:
            r, c = int(cell[0]), int(cell[1])
            if r < 0 or r >= h or c < 0 or c >= w:
                yield ZoneIssue("error", "portal",
                                f"cell ({r}, {c}) outside grid "
                                f"[0, {h}) × [0, {w})",
                                loc)
        else:
            yield ZoneIssue("error", "portal",
                            f"malformed cell value: {cell!r}", loc)

        face = int(_get("face", -1))
        if face not in (0, 1, 2, 3):
            yield ZoneIssue("error", "portal",
                            f"face={face}, expected 0..3", loc)

        dx = float(_get("dest_x", 0.0))
        dy = float(_get("dest_y", 0.0))
        if dx < 0 or dx >= w or dy < 0 or dy >= h:
            yield ZoneIssue("warning", "portal",
                            f"destination ({dx:.1f}, {dy:.1f}) outside grid "
                            f"[0, {w}) × [0, {h})",
                            loc)


def _check_zone_portals(
    zone: Any, w: int, h: int, **_kw: Any
) -> Iterator[ZoneIssue]:
    """Zone-transition portals: tiles in bounds, target_zone non-empty."""
    portals = getattr(zone, "portals", [])
    if isinstance(portals, dict):
        portals = list(portals.values())
    for i, portal in enumerate(portals):
        loc = f"portal #{i}"
        target = getattr(portal, "target_zone", "")
        if not target:
            yield ZoneIssue("error", "portal",
                            "zone portal has empty target_zone", loc)

        tiles = getattr(portal, "tiles", [])
        for t in tiles:
            if isinstance(t, (list, tuple)) and len(t) >= 2:
                r, c = int(t[0]), int(t[1])
                if r < 0 or r >= h or c < 0 or c >= w:
                    yield ZoneIssue("error", "portal",
                                    f"portal tile ({r}, {c}) outside grid",
                                    loc)


def _check_boxes(
    zone: Any, w: int, h: int, **_kw: Any
) -> Iterator[ZoneIssue]:
    """Zero-dimension boxes."""
    for i, box in enumerate(getattr(zone, "boxes", [])):
        _get = (lambda k, d=None, _b=box: _b.get(k, d)) if hasattr(box, "get") else (
            lambda k, d=None, _b=box: getattr(_b, k, d))
        uid = _get("uid", 0)
        loc = f"box uid={uid}" if uid else f"box #{i}"

        bw = float(_get("w", 1.0))
        bh = float(_get("h", 1.0))
        bd = float(_get("d", 1.0))
        if bw <= 0 or bh <= 0 or bd <= 0:
            yield ZoneIssue("error", "geometry",
                            f"degenerate dimensions w={bw}, h={bh}, d={bd}",
                            loc)


def _check_quads(
    zone: Any, w: int, h: int, **_kw: Any
) -> Iterator[ZoneIssue]:
    """Zero-dimension quads."""
    for i, quad in enumerate(getattr(zone, "quads", [])):
        _get = (lambda k, d=None, _q=quad: _q.get(k, d)) if hasattr(quad, "get") else (
            lambda k, d=None, _q=quad: getattr(_q, k, d))
        uid = _get("uid", 0)
        loc = f"quad uid={uid}" if uid else f"quad #{i}"

        qw = float(_get("width", 1.0))
        qh = float(_get("height", 1.0))
        if qw <= 0 or qh <= 0:
            yield ZoneIssue("warning", "geometry",
                            f"degenerate dimensions width={qw}, height={qh}",
                            loc)


def _check_textures(
    zone: Any, w: int, h: int, *,
    texture_dir: Path | None = None,
    **_kw: Any,
) -> Iterator[ZoneIssue]:
    """Texture key references with no corresponding asset on disk.

    Only runs when *texture_dir* is provided.  Collects all texture keys
    first, then does a single bulk existence check.
    """
    if texture_dir is None:
        return

    keys: set[str] = set()

    # 2D texture grids
    for fname in ("floor_textures", "ceil_textures", "wall_textures",
                  "floor2_textures", "ceil2_textures"):
        grid = getattr(zone, fname, None)
        if grid is None:
            continue
        for row in grid:
            for val in row:
                if val:
                    keys.add(val)

    # 3D texture grids
    for fname in ("face_textures", "floor_step_textures", "ceil_step_textures"):
        grid = getattr(zone, fname, None)
        if grid is None:
            continue
        for row in grid:
            for cell in row:
                for val in cell:
                    if val:
                        keys.add(val)

    # Wall segments
    for fname in ("wall_segments", "floor_step_segments", "ceil_step_segments"):
        grid = getattr(zone, fname, None)
        if grid is None:
            continue
        for row in grid:
            for cell in row:
                for face_segs in cell:
                    for seg in face_segs:
                        if isinstance(seg, (list, tuple)) and seg:
                            keys.add(str(seg[0]))

    # Object textures
    for quad in getattr(zone, "quads", []):
        tex = quad.get("texture", "") if hasattr(quad, "get") else getattr(quad, "texture", "")
        if tex:
            keys.add(tex)

    for curve in getattr(zone, "curves", []):
        tex = curve.get("texture", "") if hasattr(curve, "get") else getattr(curve, "texture", "")
        if tex:
            keys.add(tex)

    for box in getattr(zone, "boxes", []):
        texmap = box.get("textures", {}) if hasattr(box, "get") else getattr(box, "textures", {})
        if isinstance(texmap, dict):
            for tex in texmap.values():
                if tex:
                    keys.add(str(tex))

    for ow in getattr(zone, "overlay_walls", []):
        tex = getattr(ow, "texture", "")
        if tex:
            keys.add(tex)

    # Bulk existence check
    missing = sorted(k for k in keys if not (texture_dir / f"{k}.png").exists())
    for k in missing:
        yield ZoneIssue("warning", "texture",
                        f"texture '{k}' has no asset at {texture_dir / f'{k}.png'}")


def _check_tiles(
    zone: Any, w: int, h: int, *,
    tile_registry: dict[str, Any] | None = None,
    **_kw: Any,
) -> Iterator[ZoneIssue]:
    """Tile IDs not in the tile registry."""
    if tile_registry is None:
        return

    unknown: set[str] = set()
    for r, row in enumerate(getattr(zone, "tiles", [])):
        for c, tid in enumerate(row):
            if tid and tid not in tile_registry and tid not in unknown:
                unknown.add(tid)
                yield ZoneIssue("warning", "tile",
                                f"unknown tile id '{tid}'",
                                f"cell ({r}, {c})")


def _check_anchor(
    zone: Any, w: int, h: int, **_kw: Any
) -> Iterator[ZoneIssue]:
    """Player spawn anchor within grid bounds."""
    anchor = getattr(zone, "anchor", None)
    if anchor is None:
        yield ZoneIssue("warning", "anchor",
                        "zone has no anchor (player spawn point)")
        return
    if isinstance(anchor, (list, tuple)) and len(anchor) >= 2:
        ax, ay = float(anchor[0]), float(anchor[1])
        if ax < 0 or ax >= w or ay < 0 or ay >= h:
            yield ZoneIssue("warning", "anchor",
                            f"anchor ({ax:.1f}, {ay:.1f}) outside grid "
                            f"[0, {w}) × [0, {h})")


def _check_overlay_walls(
    zone: Any, w: int, h: int, **_kw: Any
) -> Iterator[ZoneIssue]:
    """Overlay walls with zero length."""
    for i, ow in enumerate(getattr(zone, "overlay_walls", [])):
        x1 = getattr(ow, "x1", 0.0)
        y1 = getattr(ow, "y1", 0.0)
        x2 = getattr(ow, "x2", 0.0)
        y2 = getattr(ow, "y2", 0.0)
        if x1 == x2 and y1 == y2:
            uid = getattr(ow, "uid", 0)
            loc = f"overlay_wall uid={uid}" if uid else f"overlay_wall #{i}"
            yield ZoneIssue("warning", "geometry",
                            f"zero-length overlay wall ({x1}, {y1})-({x2}, {y2})",
                            loc)


# ── Deferred-hit budget ───────────────────────────────────────────

MAX_DEF_PER_COL = 16  # must match _ray_render.h


def _cells_on_segment(x1: float, y1: float, x2: float, y2: float,
                      w: int, h: int) -> set[tuple[int, int]]:
    """Return the set of (row, col) grid cells a line segment crosses.

    Uses a simple parametric walk — conservative but cheap.
    """
    cells: set[tuple[int, int]] = set()
    dx = x2 - x1
    dy = y2 - y1
    length = math.hypot(dx, dy)
    if length < 1e-9:
        c, r = int(x1), int(y1)
        if 0 <= r < h and 0 <= c < w:
            cells.add((r, c))
        return cells
    # Step along the segment at half-cell resolution
    steps = max(int(length * 2) + 1, 2)
    for i in range(steps + 1):
        t = i / steps
        x = x1 + dx * t
        y = y1 + dy * t
        c, r = int(x), int(y)
        # Clamp to grid boundary (objects can extend outside)
        if 0 <= r < h and 0 <= c < w:
            cells.add((r, c))
    return cells


def _cells_in_aabb(cx: float, cy: float, half_w: float, half_h: float,
                   yaw: float, w: int, h: int) -> set[tuple[int, int]]:
    """Return cells overlapping an OBB's axis-aligned bounding box."""
    cos_a = abs(math.cos(yaw))
    sin_a = abs(math.sin(yaw))
    # AABB half-extents of rotated box
    ex = half_w * cos_a + half_h * sin_a
    ey = half_w * sin_a + half_h * cos_a
    c_min = max(0, int(cx - ex))
    c_max = min(w - 1, int(cx + ex))
    r_min = max(0, int(cy - ey))
    r_max = min(h - 1, int(cy + ey))
    cells: set[tuple[int, int]] = set()
    for r in range(r_min, r_max + 1):
        for c in range(c_min, c_max + 1):
            cells.add((r, c))
    return cells


def _cells_on_arc(cx: float, cy: float, radius: float,
                  w: int, h: int) -> set[tuple[int, int]]:
    """Cells overlapping a circle's bounding box (conservative)."""
    c_min = max(0, int(cx - radius))
    c_max = min(w - 1, int(cx + radius))
    r_min = max(0, int(cy - radius))
    r_max = min(h - 1, int(cy + radius))
    cells: set[tuple[int, int]] = set()
    for r in range(r_min, r_max + 1):
        for c in range(c_min, c_max + 1):
            cells.add((r, c))
    return cells


def _check_deferred_budget(
    zone: Any, w: int, h: int, *,
    tile_registry: dict[str, Any] | None = None,
    **_kw: Any,
) -> Iterator[ZoneIssue]:
    """Warn when a cell's worst-case deferred-hit count may exceed the
    C renderer's ``MAX_DEF_PER_COL`` limit.

    This is a *conservative* over-approximation: it counts every deferred-
    capable object whose bounding geometry overlaps each cell, plus one for
    the cell itself if its tile is transparent or thin-wall.  The actual
    per-column count depends on camera angle, but any cell that exceeds
    the budget in this static analysis is likely to produce silent geometry
    drops at *some* camera angle.
    """
    # Per-cell deferred count accumulator  [row][col]
    budget = [[0] * w for _ in range(h)]

    # 1. Transparent / thin-wall cells contribute 1 each (needs registry)
    if tile_registry is not None:
        tile_grid = getattr(zone, "tiles", [])
        for r in range(min(h, len(tile_grid))):
            row = tile_grid[r]
            for c in range(min(w, len(row))):
                td = tile_registry.get(row[c])
                if td is None:
                    continue
                is_trans = getattr(td, "transparent", False)
                is_thin = getattr(td, "thin_wall", False)
                if is_trans or is_thin:
                    budget[r][c] += 1

    # 2. Overlay walls — each can produce 1 deferred hit per cell it crosses
    for ow in getattr(zone, "overlay_walls", []):
        x1 = getattr(ow, "x1", 0.0)
        y1 = getattr(ow, "y1", 0.0)
        x2 = getattr(ow, "x2", 0.0)
        y2 = getattr(ow, "y2", 0.0)
        for r, c in _cells_on_segment(x1, y1, x2, y2, w, h):
            budget[r][c] += 1

    # 3. Quads — line segments in world space
    for quad in getattr(zone, "quads", []):
        _get = (lambda k, d=None, _q=quad: _q.get(k, d)) if hasattr(quad, "get") else (
            lambda k, d=None, _q=quad: getattr(_q, k, d))
        qx = float(_get("x", 0.0))
        qz = float(_get("z", 0.0))
        angle = float(_get("angle", 0.0))
        qw = float(_get("width", 1.0))
        hw = qw / 2.0
        rad = math.radians(angle)
        dx = math.cos(rad) * hw
        dy = math.sin(rad) * hw
        for r, c in _cells_on_segment(qx - dx, qz - dy, qx + dx, qz + dy, w, h):
            budget[r][c] += 1

    # 4. Boxes — OBB approximated by AABB
    for box in getattr(zone, "boxes", []):
        _get = (lambda k, d=None, _b=box: _b.get(k, d)) if hasattr(box, "get") else (
            lambda k, d=None, _b=box: getattr(_b, k, d))
        bx = float(_get("x", 0.0))
        bz = float(_get("z", 0.0))
        bw = float(_get("w", 1.0))
        bd = float(_get("d", 1.0))
        yaw = float(_get("yaw", 0.0))
        for r, c in _cells_in_aabb(bx, bz, bw / 2, bd / 2, yaw, w, h):
            budget[r][c] += 1

    # 5. Curves — circle bounding box
    for curve in getattr(zone, "curves", []):
        _get = (lambda k, d=None, _cv=curve: _cv.get(k, d)) if hasattr(curve, "get") else (
            lambda k, d=None, _cv=curve: getattr(_cv, k, d))
        cx = float(_get("x", 0.0))
        cy = float(_get("y", 0.0))
        radius = float(_get("radius", 1.0))
        for r, c in _cells_on_arc(cx, cy, radius, w, h):
            budget[r][c] += 1

    # Report cells that exceed the budget
    for r in range(h):
        for c in range(w):
            count = budget[r][c]
            if count > MAX_DEF_PER_COL:
                yield ZoneIssue(
                    "warning", "deferred",
                    f"cell has {count} potential deferred hits "
                    f"(limit is {MAX_DEF_PER_COL}); geometry may silently "
                    f"vanish from some camera angles",
                    f"cell ({r}, {c})",
                )


# ── Check registry ────────────────────────────────────────────────
# Ordered list of all check functions.  Add new checks here.

_ALL_CHECKS = [
    _check_grid_dimensions,
    _check_geometry,
    _check_uid_uniqueness,
    _check_entities,
    _check_render_portals,
    _check_zone_portals,
    _check_boxes,
    _check_quads,
    _check_overlay_walls,
    _check_anchor,
    _check_textures,
    _check_tiles,
    _check_deferred_budget,
]
