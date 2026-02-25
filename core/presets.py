"""core/presets.py — Cell preset ("Model") system.

A ``CellPreset`` is a **recipe** that tells the editor how to configure
a zone cell: sculpt heights, paint every surface, and lay out wall
segments.  Presets replace the old notion of "tile types as visual
models" with explicit, composable blueprints.

The cell’s tile type (wall vs open) is **derived** from its geometry:
when ``floor_height ≥ ceil_height`` the cell has no passable gap and
becomes a full-height solid column automatically.

Apply Modes
-----------
Each preset carries an ``apply_mode`` that controls how it interacts
with the cell’s existing state:

``replace``  — Overwrites the cell completely (default).
``stack_floor``  — Stacks on top of the existing floor: a floor-step
    segment is created at the old floor height, then the floor is
    raised by the preset’s ``floor_height``.
``stack_ceil``  — Hangs from the ceiling: a ceil-step segment is
    created at the old ceiling height, then the ceiling is lowered
    by the preset’s ``floor_height`` (used as thickness).
``merge``  — Only writes non-None fields; tile type is left alone.

Presets are stored as TOML files in ``data/presets/`` and loaded at
import time (like the tile registry).  The editor can also capture a
cell's current state as a new preset and persist it.

Hand-authored TOML files may omit any field (the cell keeps its
existing value).  Editor-captured presets always write every field
explicitly with range comments so the file is self-documenting.

    from core.presets import PRESET_REGISTRY, apply_preset, capture_preset
    apply_preset(zone, row, col, PRESET_REGISTRY["brick_wall"])
"""

from __future__ import annotations

import os as _os
from dataclasses import dataclass
from typing import Any

try:
    import tomllib as _tomllib
except ModuleNotFoundError:
    import tomli as _tomllib          # type: ignore[no-redef]

from core.paths import DATA_DIR

# ── Directory ────────────────────────────────────────────────────

PRESETS_DIR = str(DATA_DIR / "presets")

# ═══════════════════════════════════════════════════════════════════
#  CellPreset dataclass
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class CellPreset:
    """Immutable recipe for configuring a zone cell.

    Fields set to ``None`` are *not applied* — the cell keeps its
    existing value.  An empty string ``""`` explicitly **clears** a
    texture override.
    """
    id:       str
    name:     str
    category: str                              = "General"
    color:    tuple[int, int, int]              = (128, 128, 128)

    # ── Apply mode ───────────────────────────────────────────────
    # "replace"     — overwrite the cell completely
    # "stack_floor" — raise floor, create step segment at old height
    # "stack_ceil"  — lower ceiling, create step segment at old height
    # "merge"       — only write non-None fields, don’t touch tile type
    apply_mode: str                            = "replace"

    # ── Heights (None = leave unchanged) ─────────────────────────
    # floor_height: 0.0–10.0 m — at maximum the cell becomes a
    #               full-height solid column (wall).
    floor_height:      float | None            = None
    # ceil_height:  0.0–10.0 m
    ceil_height:       float | None            = None
    # upper_wall_height: 0.0–10.0 m
    upper_wall_height: float | None            = None

    # ── Surface textures (None = leave, "" = clear) ──────────────
    floor_texture:      str | None             = None
    ceil_texture:       str | None             = None
    wall_texture:       str | None             = None
    # Per-face overrides [N, S, E, W].  None = leave unchanged.
    face_textures:      tuple[str, ...] | None = None
    floor_step_textures: tuple[str, ...] | None = None
    ceil_step_textures:  tuple[str, ...] | None = None

    # ── Wall segments (None = leave, empty list = clear) ─────────
    # Each is a list of 4 face-lists.  Each face-list contains
    # [[tex, y_top], ...] entries sorted bottom→top.
    wall_segments:       tuple | None          = None
    floor_step_segments: tuple | None          = None
    ceil_step_segments:  tuple | None          = None


# ═══════════════════════════════════════════════════════════════════
#  Registry
# ═══════════════════════════════════════════════════════════════════

PRESET_REGISTRY: dict[str, CellPreset] = {}
PRESET_CATEGORIES: list[str] = ["General", "Walls", "Floors", "Rooms"]
APPLY_MODES: list[str] = ["replace", "stack_floor", "stack_ceil", "merge"]

_FALLBACK = CellPreset("_empty", "Empty")


def preset_def(preset_id: str) -> CellPreset:
    """Look up a preset, returning a safe fallback for unknowns."""
    return PRESET_REGISTRY.get(preset_id, _FALLBACK)


def presets_by_category() -> dict[str, list[CellPreset]]:
    """Return presets grouped by category (ordered, non-empty only)."""
    from collections import OrderedDict
    groups: dict[str, list[CellPreset]] = OrderedDict()
    for cat in PRESET_CATEGORIES:
        groups[cat] = []
    for p in PRESET_REGISTRY.values():
        groups.setdefault(p.category, []).append(p)
    for cat in groups:
        groups[cat].sort(key=lambda p: p.name)
    return {k: v for k, v in groups.items() if v}


# ═══════════════════════════════════════════════════════════════════
#  Apply / Capture
# ═══════════════════════════════════════════════════════════════════

def apply_preset(
    zone: Any,
    r: int,
    c: int,
    preset: CellPreset,
    *,
    wall_tile: str = "void",
    open_tile: str = "grass",
    mode_override: str | None = None,
) -> None:
    """Stamp a :class:`CellPreset` recipe onto zone cell *(r, c)*.

    Only fields that are not ``None`` in the preset are touched.
    The tile type (wall vs open) is derived from the resulting gap
    between floor and ceiling: when floor_height >= ceil_height the
    cell becomes a solid wall column.

    Parameters
    ----------
    mode_override
        If given, use this apply mode instead of the preset's own.
    """
    mode = mode_override or preset.apply_mode

    if mode == "stack_floor":
        _apply_stack_floor(zone, r, c, preset, wall_tile, open_tile)
    elif mode == "stack_ceil":
        _apply_stack_ceil(zone, r, c, preset, wall_tile, open_tile)
    elif mode == "merge":
        _apply_merge(zone, r, c, preset)
    else:  # "replace"
        _apply_replace(zone, r, c, preset, wall_tile, open_tile)


def _apply_replace(
    zone: Any, r: int, c: int, preset: CellPreset,
    wall_tile: str, open_tile: str,
) -> None:
    """Mode *replace*: overwrite the cell completely."""
    if preset.floor_height is not None:
        zone.floor_heights[r][c] = preset.floor_height
    if preset.ceil_height is not None:
        zone.ceil_heights[r][c] = preset.ceil_height
    if preset.upper_wall_height is not None:
        if zone.upper_wall_height and len(zone.upper_wall_height) > r:
            zone.upper_wall_height[r][c] = preset.upper_wall_height

    _derive_tile_type(zone, r, c, wall_tile, open_tile)
    _apply_textures(zone, r, c, preset)
    _apply_segments(zone, r, c, preset)


def _apply_stack_floor(
    zone: Any, r: int, c: int, preset: CellPreset,
    wall_tile: str, open_tile: str,
) -> None:
    """Mode *stack_floor*: add preset on top of existing floor.

    Creates a floor-step segment at the old floor height, then raises
    the floor by the preset's ``floor_height`` value.
    """
    old_fh = zone.floor_heights[r][c]
    delta = preset.floor_height if preset.floor_height is not None else 0.0
    new_fh = min(old_fh + delta, 10.0)

    # Create floor-step segment at the boundary
    if zone.floor_step_segments and len(zone.floor_step_segments) > r:
        tex = preset.wall_texture or ""
        for face_idx in range(4):
            zone.floor_step_segments[r][c][face_idx].append(
                [tex, new_fh]
            )

    # Paint step risers if the preset specifies them
    if preset.floor_step_textures is not None:
        if zone.floor_step_textures and len(zone.floor_step_textures) > r:
            zone.floor_step_textures[r][c] = list(preset.floor_step_textures)

    zone.floor_heights[r][c] = new_fh
    if preset.ceil_height is not None:
        zone.ceil_heights[r][c] = preset.ceil_height

    _derive_tile_type(zone, r, c, wall_tile, open_tile)
    _apply_textures(zone, r, c, preset)


def _apply_stack_ceil(
    zone: Any, r: int, c: int, preset: CellPreset,
    wall_tile: str, open_tile: str,
) -> None:
    """Mode *stack_ceil*: hang preset from existing ceiling.

    Creates a ceil-step segment at the old ceiling height, then lowers
    the ceiling by the preset's ``floor_height`` (used as thickness).
    """
    old_ch = zone.ceil_heights[r][c]
    thickness = preset.floor_height if preset.floor_height is not None else 0.0
    new_ch = max(old_ch - thickness, 0.0)

    # Create ceil-step segment at the boundary
    if zone.ceil_step_segments and len(zone.ceil_step_segments) > r:
        tex = preset.wall_texture or ""
        for face_idx in range(4):
            zone.ceil_step_segments[r][c][face_idx].append(
                [tex, old_ch]
            )

    # Paint step risers if the preset specifies them
    if preset.ceil_step_textures is not None:
        if zone.ceil_step_textures and len(zone.ceil_step_textures) > r:
            zone.ceil_step_textures[r][c] = list(preset.ceil_step_textures)

    zone.ceil_heights[r][c] = new_ch

    _derive_tile_type(zone, r, c, wall_tile, open_tile)
    _apply_textures(zone, r, c, preset)


def _apply_merge(
    zone: Any, r: int, c: int, preset: CellPreset,
) -> None:
    """Mode *merge*: write only non-None fields, leave tile type alone."""
    if preset.floor_height is not None:
        zone.floor_heights[r][c] = preset.floor_height
    if preset.ceil_height is not None:
        zone.ceil_heights[r][c] = preset.ceil_height
    if preset.upper_wall_height is not None:
        if zone.upper_wall_height and len(zone.upper_wall_height) > r:
            zone.upper_wall_height[r][c] = preset.upper_wall_height
    # Don't touch tile type — that's the point of merge
    _apply_textures(zone, r, c, preset)
    _apply_segments(zone, r, c, preset)


# ── Apply helpers ─────────────────────────────────────────────────

def _derive_tile_type(
    zone: Any, r: int, c: int,
    wall_tile: str, open_tile: str,
) -> None:
    """Set the cell's tile type based on floor/ceil gap."""
    fh = zone.floor_heights[r][c]
    ch = zone.ceil_heights[r][c]
    if ch - fh < 0.1:
        zone.tiles[r][c] = wall_tile
    else:
        zone.tiles[r][c] = open_tile


def _apply_textures(zone: Any, r: int, c: int, preset: CellPreset) -> None:
    """Write preset texture fields onto a cell."""
    if preset.floor_texture is not None and zone.floor_textures:
        zone.floor_textures[r][c] = preset.floor_texture
    if preset.ceil_texture is not None and zone.ceil_textures:
        zone.ceil_textures[r][c] = preset.ceil_texture
    if preset.wall_texture is not None and zone.wall_textures:
        zone.wall_textures[r][c] = preset.wall_texture
    if preset.face_textures is not None:
        if zone.face_textures and len(zone.face_textures) > r:
            zone.face_textures[r][c] = list(preset.face_textures)
    if preset.floor_step_textures is not None:
        if zone.floor_step_textures and len(zone.floor_step_textures) > r:
            zone.floor_step_textures[r][c] = list(preset.floor_step_textures)
    if preset.ceil_step_textures is not None:
        if zone.ceil_step_textures and len(zone.ceil_step_textures) > r:
            zone.ceil_step_textures[r][c] = list(preset.ceil_step_textures)


def _apply_segments(zone: Any, r: int, c: int, preset: CellPreset) -> None:
    """Write preset segment fields onto a cell."""
    if preset.wall_segments is not None:
        if zone.wall_segments and len(zone.wall_segments) > r:
            zone.wall_segments[r][c] = _deep_copy_seg(preset.wall_segments)
    if preset.floor_step_segments is not None:
        if zone.floor_step_segments and len(zone.floor_step_segments) > r:
            zone.floor_step_segments[r][c] = _deep_copy_seg(
                preset.floor_step_segments)
    if preset.ceil_step_segments is not None:
        if zone.ceil_step_segments and len(zone.ceil_step_segments) > r:
            zone.ceil_step_segments[r][c] = _deep_copy_seg(
                preset.ceil_step_segments)


def capture_preset(
    zone: Any,
    r: int,
    c: int,
    preset_id: str,
    name: str,
    category: str = "Custom",
    apply_mode: str = "replace",
) -> CellPreset:
    """Snapshot cell *(r, c)* as a new :class:`CellPreset`.

    Captures every mutable property of the cell so the preset can
    reproduce it exactly when stamped elsewhere.  The caller must
    supply an explicit *name* — there is no auto-generated default.
    """
    from core.tiles import tile_def

    td = tile_def(zone.tiles[r][c])

    fh = zone.floor_heights[r][c] if zone.floor_heights else None
    ch = zone.ceil_heights[r][c] if zone.ceil_heights else None
    uwh = (zone.upper_wall_height[r][c]
           if zone.upper_wall_height and len(zone.upper_wall_height) > r
           else None)

    ft = zone.floor_textures[r][c] if zone.floor_textures else None
    ct = zone.ceil_textures[r][c] if zone.ceil_textures else None
    wt = zone.wall_textures[r][c] if zone.wall_textures else None

    face = None
    if zone.face_textures and len(zone.face_textures) > r:
        face = tuple(zone.face_textures[r][c])

    fst = None
    if zone.floor_step_textures and len(zone.floor_step_textures) > r:
        fst = tuple(zone.floor_step_textures[r][c])

    cst = None
    if zone.ceil_step_textures and len(zone.ceil_step_textures) > r:
        cst = tuple(zone.ceil_step_textures[r][c])

    ws = None
    if zone.wall_segments and len(zone.wall_segments) > r:
        ws = _freeze_seg(zone.wall_segments[r][c])

    fss = None
    if zone.floor_step_segments and len(zone.floor_step_segments) > r:
        fss = _freeze_seg(zone.floor_step_segments[r][c])

    css = None
    if zone.ceil_step_segments and len(zone.ceil_step_segments) > r:
        css = _freeze_seg(zone.ceil_step_segments[r][c])

    # Pick a sensible swatch color
    color = td.color if td else (128, 128, 128)

    preset = CellPreset(
        id=preset_id,
        name=name,
        category=category,
        color=color,
        apply_mode=apply_mode,
        floor_height=fh,
        ceil_height=ch,
        upper_wall_height=uwh,
        floor_texture=ft,
        ceil_texture=ct,
        wall_texture=wt,
        face_textures=face,
        floor_step_textures=fst,
        ceil_step_textures=cst,
        wall_segments=ws,
        floor_step_segments=fss,
        ceil_step_segments=css,
    )
    return preset


# ═══════════════════════════════════════════════════════════════════
#  TOML I/O
# ═══════════════════════════════════════════════════════════════════

def _preset_path(preset_id: str) -> str:
    return _os.path.join(PRESETS_DIR, f"{preset_id}.toml")


def _parse_cell_type(d: dict) -> float | None:
    """Read legacy cell-type fields and convert to floor_height.

    If the TOML has ``cell_type = 1``, ``solid = true``, or
    ``is_wall = true`` *and* no explicit ``floor_height``, return
    10.0 (fills to default ceiling).  Otherwise return ``None``
    so the normal ``floor_height`` key is used instead.
    """
    # New-style files just use floor_height directly.
    if "floor_height" in d:
        return None
    # Legacy boolean / int fields
    if "cell_type" in d and int(d["cell_type"]) == 1:
        return 10.0
    legacy = d.get("solid", d.get("is_wall", False))
    if legacy:
        return 10.0
    return None


def _parse_preset_toml(path: str) -> CellPreset | None:
    """Parse a single preset TOML file."""
    try:
        with open(path, "rb") as f:
            d = _tomllib.load(f)
    except Exception:
        return None

    basename = _os.path.splitext(_os.path.basename(path))[0]
    if basename.startswith("_"):
        return None

    raw_color = d.get("color", [128, 128, 128])
    color = (int(raw_color[0]), int(raw_color[1]), int(raw_color[2]))

    # Parse optional face-texture / segment arrays
    face_tex = None
    if "face_textures" in d:
        ft = d["face_textures"]
        face_tex = tuple(ft) if isinstance(ft, list) else None

    fst = None
    if "floor_step_textures" in d:
        v = d["floor_step_textures"]
        fst = tuple(v) if isinstance(v, list) else None

    cst = None
    if "ceil_step_textures" in d:
        v = d["ceil_step_textures"]
        cst = tuple(v) if isinstance(v, list) else None

    ws = _parse_seg_field(d, "wall_segments")
    fss = _parse_seg_field(d, "floor_step_segments")
    css = _parse_seg_field(d, "ceil_step_segments")

    # Legacy compat: convert old is_wall / solid / cell_type
    legacy_fh = _parse_cell_type(d)

    return CellPreset(
        id=basename,
        name=d.get("name", basename),
        category=d.get("category", "General"),
        color=color,
        apply_mode=d.get("apply_mode", "replace"),
        floor_height=d.get("floor_height", legacy_fh),
        ceil_height=d.get("ceil_height"),
        upper_wall_height=d.get("upper_wall_height"),
        floor_texture=d.get("floor_texture"),
        ceil_texture=d.get("ceil_texture"),
        wall_texture=d.get("wall_texture"),
        face_textures=face_tex,
        floor_step_textures=fst,
        ceil_step_textures=cst,
        wall_segments=ws,
        floor_step_segments=fss,
        ceil_step_segments=css,
    )


def _save_preset_toml(p: CellPreset) -> str:
    """Serialize a preset to TOML and write to disk.

    Editor-generated presets write **every** field explicitly with
    inline range comments so the file is fully self-documenting.
    """
    lines: list[str] = []
    lines.append(f'name = "{p.name}"')
    lines.append(f'category = "{p.category}"')
    lines.append(f"color = [{p.color[0]}, {p.color[1]}, {p.color[2]}]")
    lines.append("")

    # ── Apply mode ───────────────────────────────────────────────
    lines.append('# apply_mode: "replace" | "stack_floor" | "stack_ceil" | "merge"')
    lines.append(f'apply_mode = "{p.apply_mode}"')
    lines.append("")

    # ── Heights ──────────────────────────────────────────────────
    lines.append("# floor_height: 0.0–10.0 (metres above base; at 10.0 the cell becomes a solid column)")
    fh = p.floor_height if p.floor_height is not None else 0.0
    lines.append(f"floor_height = {fh}")

    lines.append("# ceil_height: 0.0–10.0 (metres above base, must be >= floor_height)")
    ch = p.ceil_height if p.ceil_height is not None else 10.0
    lines.append(f"ceil_height = {ch}")

    lines.append("# upper_wall_height: 0.0–10.0 (extends wall above ceiling)")
    uwh = p.upper_wall_height if p.upper_wall_height is not None else 0.0
    lines.append(f"upper_wall_height = {uwh}")
    lines.append("")

    # ── Textures ─────────────────────────────────────────────────
    lines.append('# floor_texture: texture key or "" to clear')
    lines.append(f'floor_texture = "{p.floor_texture or ""}"')

    lines.append('# ceil_texture: texture key or "" to clear')
    lines.append(f'ceil_texture = "{p.ceil_texture or ""}"')

    lines.append('# wall_texture: texture key or "" to clear')
    lines.append(f'wall_texture = "{p.wall_texture or ""}"')
    lines.append("")

    # ── Per-face textures [N, S, E, W] ───────────────────────────
    lines.append('# face_textures: [north, south, east, west] — texture key per face')
    ft = list(p.face_textures) if p.face_textures else ["", "", "", ""]
    lines.append(f"face_textures = {ft}")

    lines.append('# floor_step_textures: [north, south, east, west] — step risers')
    fst = list(p.floor_step_textures) if p.floor_step_textures else ["", "", "", ""]
    lines.append(f"floor_step_textures = {fst}")

    lines.append('# ceil_step_textures: [north, south, east, west] — ceiling step faces')
    cst = list(p.ceil_step_textures) if p.ceil_step_textures else ["", "", "", ""]
    lines.append(f"ceil_step_textures = {cst}")
    lines.append("")

    # ── Segments ─────────────────────────────────────────────────
    ws = p.wall_segments if p.wall_segments is not None else ((), (), (), ())
    _write_seg_field(lines, "wall_segments", ws)

    fss = p.floor_step_segments if p.floor_step_segments is not None else ((), (), (), ())
    _write_seg_field(lines, "floor_step_segments", fss)

    css = p.ceil_step_segments if p.ceil_step_segments is not None else ((), (), (), ())
    _write_seg_field(lines, "ceil_step_segments", css)

    _os.makedirs(PRESETS_DIR, exist_ok=True)
    path = _preset_path(p.id)
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return path


def load_presets() -> bool:
    """Load all preset TOML files from ``data/presets/``."""
    if not _os.path.isdir(PRESETS_DIR):
        return False
    loaded = 0
    for fname in sorted(_os.listdir(PRESETS_DIR)):
        if not fname.endswith(".toml") or fname.startswith("_"):
            continue
        p = _parse_preset_toml(_os.path.join(PRESETS_DIR, fname))
        if p is not None:
            PRESET_REGISTRY[p.id] = p
            if p.category not in PRESET_CATEGORIES:
                PRESET_CATEGORIES.append(p.category)
            loaded += 1
    return loaded > 0


# ═══════════════════════════════════════════════════════════════════
#  CRUD
# ═══════════════════════════════════════════════════════════════════

def register_preset(preset: CellPreset, *, save: bool = True) -> None:
    """Add or replace a preset in the registry and optionally persist."""
    PRESET_REGISTRY[preset.id] = preset
    if preset.category not in PRESET_CATEGORIES:
        PRESET_CATEGORIES.append(preset.category)
    if save:
        _save_preset_toml(preset)


def delete_preset(preset_id: str) -> bool:
    """Remove a preset from registry and disk."""
    if preset_id not in PRESET_REGISTRY:
        return False
    path = _preset_path(preset_id)
    if _os.path.exists(path):
        _os.remove(path)
    del PRESET_REGISTRY[preset_id]
    return True


def _next_preset_id(name: str) -> str:
    """Generate a unique preset ID from a display name."""
    key = name.lower().replace(" ", "_")
    if key not in PRESET_REGISTRY:
        return key
    i = 2
    while f"{key}_{i}" in PRESET_REGISTRY:
        i += 1
    return f"{key}_{i}"


# ═══════════════════════════════════════════════════════════════════
#  Segment helpers (freeze / thaw for immutable preset storage)
# ═══════════════════════════════════════════════════════════════════

def _freeze_seg(seg4: list[list]) -> tuple:
    """Convert mutable [face0, face1, face2, face3] to nested tuples."""
    return tuple(
        tuple(tuple(entry) for entry in face)
        for face in seg4
    )


def _deep_copy_seg(seg4: tuple | list) -> list[list]:
    """Convert frozen segments back to mutable lists for zone storage."""
    return [
        [list(entry) for entry in face]
        for face in seg4
    ]


def _parse_seg_field(d: dict, key: str) -> tuple | None:
    """Parse a segment field from TOML data."""
    if key not in d:
        return None
    raw = d[key]
    if not isinstance(raw, list):
        return None
    result: list = []
    for face in raw:
        if isinstance(face, list):
            result.append(tuple(tuple(e) for e in face))
        else:
            result.append(())
    return tuple(result)


def _write_seg_field(lines: list[str], key: str, seg4: tuple) -> None:
    """Serialize a segment field to TOML lines."""
    lines.append("")
    lines.append(f"# {key}: [face0_segs, face1_segs, face2_segs, face3_segs]")
    lines.append("# Each face: [[texture, y_top], ...]  (bottom to top)")
    parts: list[str] = []
    for face in seg4:
        if not face:
            parts.append("[]")
        else:
            entries = ", ".join(
                f'["{tex}", {ytop}]' for tex, ytop in face
            )
            parts.append(f"[{entries}]")
    lines.append(f"{key} = [{', '.join(parts)}]")


# ═══════════════════════════════════════════════════════════════════
#  Bootstrap
# ═══════════════════════════════════════════════════════════════════

load_presets()
