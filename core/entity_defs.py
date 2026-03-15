"""core/entity_defs.py — Unified entity type definitions.

Loads ``data/entity_defs.toml`` and provides :class:`EntityDef` with
**all** entity data: visual/placement properties (for the editor and
renderer) AND default ECS component values (for the spawner).

This is the single source of truth for "what is a barrel?" — visuals,
geometry, and behaviour live in one TOML entry.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]


_DEFS_PATH = Path(__file__).resolve().parent.parent / "data" / "entity_defs.toml"

# ── Facing label constants ────────────────────────────────────────
# 8-way facing order matching the C renderer's facing arithmetic.
# Index 0 = south (facing camera), counter-clockwise.
FACING_LABELS_8: tuple[str, ...] = ("s", "sw", "w", "nw", "n", "ne", "e", "se")

# ── Known keys ────────────────────────────────────────────────────
# Top-level scalar/list fields on a TOML entry (NOT component sub-tables).
_TOP_LEVEL_FIELDS: set[str] = {
    "display_name", "category", "render_type", "color", "scale",
    "directional", "states", "sprite_key",
    # Prism geometry
    "width", "depth", "height", "elevation",
    # Flags
    "movable",
}

# Recognised component sub-table keys.  The spawner has a builder for
# each of these.  Any dict-valued key in the TOML that isn't in
# _TOP_LEVEL_FIELDS _and_ isn't in this set produces a load-time warning.
_KNOWN_COMPONENT_KEYS: set[str] = {
    "identity", "sprite", "health", "collider", "facing",
    "player", "inventory", "tile_entity", "wall_sprite",
    "combat", "dialogue",
    # Special: prism per-face textures (parsed separately, not a component)
    "textures",
}

# ── Face → BX_TEX_* offset mapping ───────────────────────────────
# The C renderer's +Y axis is the editor's south, so north↔south swap.
_FACE_TO_BX: dict[str, int] = {
    "north":  8,   # BX_TEX_S
    "south":  7,   # BX_TEX_N
    "east":   9,   # BX_TEX_E
    "west":   10,  # BX_TEX_W
    "top":    11,  # BX_TEX_T
    "bottom": 12,  # BX_TEX_B
}


def face_to_box_index(face_name: str) -> int:
    """Map a game-space face name to its ``BX_TEX_*`` buffer offset.

    Use this everywhere box_data is constructed — never hard-code the
    north↔south swap inline.
    """
    return _FACE_TO_BX[face_name]


# ── EntityDef ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class EntityDef:
    """Immutable descriptor for one entity type.

    Combines visual/placement data (for editor + renderer) with default
    ECS component values (for spawner).  Loaded from a single TOML entry.
    """

    # ── Identity ──────────────────────────────────────
    id: str
    display_name: str
    category: str

    # ── Rendering ─────────────────────────────────────
    render_type: str                                    # "billboard", "8way", "prism"
    color: tuple[int, int, int]
    scale: float
    directional: bool
    states: tuple[str, ...]
    sprite_key: str                                     # 8-way texture base (e.g. "crawler")
    frame_width: int                                    # sprite cell width in px  (default 32)
    frame_height: int                                   # sprite cell height in px (default 128)

    # ── Prism geometry (render_type == "prism") ───────
    width: float
    depth: float
    height: float
    elevation: float
    textures: tuple[tuple[str, str], ...]               # ((face, key), ...) — frozen for hashing
    movable: bool

    # ── ECS component defaults ────────────────────────
    components: tuple[tuple[str, tuple[tuple[str, Any], ...]], ...]
    # Frozen structure: (("identity", (("name", "Barrel"), ("kind", "container"))), ...)
    # Converted to mutable dicts via component_defaults() for spawner use.

    def component_defaults(self) -> dict[str, dict[str, Any]]:
        """Return a mutable ``{key: {field: value}}`` copy of component data."""
        return {k: dict(v) for k, v in self.components}

    @property
    def def_version(self) -> str:
        """Return a short hash of this definition's component structure.

        Changes whenever component keys, field names, or default values
        change.  Used to detect save-incompatible definition changes.
        """
        sig = repr(self.components) + repr(self.textures) + self.render_type
        return hashlib.sha1(sig.encode(), usedforsecurity=False).hexdigest()[:12]

    def texture_map(self) -> dict[str, str]:
        """Return a mutable ``{face: texture_key}`` copy."""
        return dict(self.textures)

    def face_dimensions(self, face: str) -> tuple[float, float]:
        """Return ``(world_width, world_height)`` of a face.

        Used to compute correct texture aspect ratios.

        - north/south: width × height  (faces perpendicular to depth axis)
        - east/west:   depth × height  (faces perpendicular to width axis)
        - top/bottom:  width × depth   (horizontal faces)
        """
        if face in ("north", "south"):
            return (self.width, self.height)
        if face in ("east", "west"):
            return (self.depth, self.height)
        if face in ("top", "bottom"):
            return (self.width, self.depth)
        return (1.0, 1.0)

    @staticmethod
    def face_tex_size(face_w: float, face_h: float,
                      base_px: int = 128,
                      ref_dim: float = 0.0) -> tuple[int, int]:
        """Compute pixel dimensions for a face texture.

        When *ref_dim* > 0 the scale factor is ``base_px / ref_dim``,
        giving **consistent pixel density** across every face of the
        same entity.  Pass ``ref_dim = max(width, depth, height)``.

        When *ref_dim* is omitted (or 0) the face's own longest side
        is used (legacy per-face behaviour).

        Result is rounded to the nearest multiple of 4 (GPU-aligned).

        >>> EntityDef.face_tex_size(0.4, 0.8, 128, ref_dim=0.8)
        (64, 128)
        >>> EntityDef.face_tex_size(0.4, 0.35, 128, ref_dim=0.8)
        (64, 56)
        """
        longest = ref_dim if ref_dim > 0 else max(face_w, face_h, 0.01)
        scale = base_px / longest
        w_px = max(4, round(face_w * scale / 4) * 4)
        h_px = max(4, round(face_h * scale / 4) * 4)
        return (w_px, h_px)


# ── Module-level cache ────────────────────────────────────────────

_REGISTRY: dict[str, EntityDef] = {}
_PALETTE: list[str] = []           # ordered list of type IDs


def _load() -> None:
    """Load (or reload) entity definitions from disk."""
    _REGISTRY.clear()
    _PALETTE.clear()
    if not _DEFS_PATH.exists():
        return
    with open(_DEFS_PATH, "rb") as f:
        data = tomllib.load(f)
    for key, raw in data.items():
        if not isinstance(raw, dict):
            continue
        _REGISTRY[key] = _parse_entry(key, raw)

    # Sort palette: category then display_name
    _PALETTE.extend(
        sorted(_REGISTRY, key=lambda k: (_REGISTRY[k].category,
                                         _REGISTRY[k].display_name))
    )


def _parse_entry(key: str, raw: dict[str, Any]) -> EntityDef:
    """Parse one TOML entry into an EntityDef."""
    # ── Validate sub-table keys ──────────────────────────────────
    for sub_key, sub_val in raw.items():
        if isinstance(sub_val, dict) and sub_key not in _KNOWN_COMPONENT_KEYS:
            if sub_key not in _TOP_LEVEL_FIELDS:
                print(f"[ENTITY_DEFS] WARNING: '{key}.{sub_key}' is not a "
                      f"recognised component — will be ignored by spawner")

    # ── Top-level fields ─────────────────────────────────────────
    color_raw = raw.get("color", [200, 200, 200])
    color = (int(color_raw[0]), int(color_raw[1]), int(color_raw[2]))

    render_type = raw.get("render_type", "billboard")

    # ── Prism geometry ───────────────────────────────────────────
    textures_raw: dict[str, str] = raw.get("textures", {})
    textures = tuple(sorted(textures_raw.items()))

    # ── Component sub-tables ─────────────────────────────────────
    components: list[tuple[str, tuple[tuple[str, Any], ...]]] = []
    for comp_key in _KNOWN_COMPONENT_KEYS:
        if comp_key == "textures":
            continue  # handled above
        sub = raw.get(comp_key)
        if isinstance(sub, dict):
            # Freeze values that are mutable (lists → tuples for hashing)
            frozen_items = tuple(
                (k, tuple(v) if isinstance(v, list) else v)
                for k, v in sorted(sub.items())
            )
            components.append((comp_key, frozen_items))

    return EntityDef(
        id=key,
        display_name=raw.get("display_name", key),
        category=raw.get("category", "misc"),
        render_type=render_type,
        color=color,
        scale=float(raw.get("scale", 1.0)),
        directional=bool(raw.get("directional", False)),
        states=tuple(raw.get("states", ["default"])),
        sprite_key=raw.get("sprite_key", ""),
        frame_width=int(raw.get("frame_width", 32)),
        frame_height=int(raw.get("frame_height", 128)),
        width=float(raw.get("width", 1.0)),
        depth=float(raw.get("depth", 1.0)),
        height=float(raw.get("height", 1.0)),
        elevation=float(raw.get("elevation", 0.0)),
        textures=textures,
        movable=bool(raw.get("movable", False)),
        components=tuple(components),
    )


def reload_registry() -> None:
    """Force a reload from disk (e.g. after editing the TOML)."""
    _REGISTRY.clear()
    _PALETTE.clear()
    _load()


def entity_registry() -> dict[str, EntityDef]:
    """Return the full ``{id: EntityDef}`` mapping.  Loads on first call."""
    if not _REGISTRY:
        _load()
    return _REGISTRY


def entity_palette() -> list[str]:
    """Ordered list of entity type IDs for the editor palette."""
    if not _PALETTE:
        _load()
    return _PALETTE


def get_entity_def(type_id: str) -> EntityDef | None:
    """Look up a single entity def by ID."""
    return entity_registry().get(type_id)


def _read_state_frames(toml_path: Path, states: list[str]) -> dict[str, int]:
    """Read per-state frame counts from a billboard TOML sidecar.

    Returns a dict mapping state name → frame count.
    If the TOML doesn't exist or has no ``[states.X]`` sections,
    every state defaults to 1 frame.
    """
    result = {s: 1 for s in states}
    if not toml_path.exists():
        return result
    try:
        with open(toml_path, "rb") as f:
            meta = tomllib.load(f)
        states_tbl = meta.get("states", {})
        for s in states:
            info = states_tbl.get(s)
            if isinstance(info, dict):
                result[s] = max(int(info.get("frames", 1)), 1)
    except Exception:
        pass
    return result


def entity_texture_keys() -> list[str]:
    """Return texture keys for every entity type, in atlas-ready order.

    Billboard entities register one key per state × frame × facing.
    Keys always include the frame index for consistency::

        dummy:idle_0_s, dummy:idle_0_sw, …, dummy:idle_0_se,
        dummy:walk_0_s, …, dummy:walk_0_se,
        dummy:walk_1_s, …, dummy:walk_1_se,  (4 rows for 4-frame walk)
        …

    Non-directional entities omit the facing::

        torch:lit_0, torch:lit_1, torch:lit_2, torch:lit_3,
        torch:off_0

    The keys **must** be consecutive in the atlas so the C renderer's
    ``base_tex + anim_offset + frame`` arithmetic works.

    Frame counts per state are read from the TOML sidecar's
    ``[states.X]`` sections.  If no sidecar exists, 1 frame is assumed.
    """
    from core.paths import BILLBOARD_TEX_DIR

    reg = entity_registry()
    keys: list[str] = []  # ordered — insertion order IS the atlas order
    for edef in sorted(reg.values(), key=lambda e: e.id):
        # Prism face textures (order doesn't matter — looked up by name)
        for _face, tex_key in edef.textures:
            if tex_key and tex_key not in keys:
                keys.append(tex_key)
        # Billboard sprite textures — consecutive block per entity
        if edef.render_type in ("billboard", "8way") and edef.sprite_key:
            n_facings = 8 if edef.directional else 1
            states = list(edef.states) or ["default"]

            # Read per-state frame counts from TOML sidecar
            state_frames = _read_state_frames(
                BILLBOARD_TEX_DIR / f"{edef.id}_sheet.toml", states)

            for state in states:
                nf = state_frames.get(state, 1)
                for frame_idx in range(nf):
                    if n_facings == 1:
                        k = f"{edef.sprite_key}:{state}_{frame_idx}"
                        if k not in keys:
                            keys.append(k)
                    else:
                        for fi in range(n_facings):
                            k = f"{edef.sprite_key}:{state}_{frame_idx}_{FACING_LABELS_8[fi]}"
                            if k not in keys:
                                keys.append(k)
    return keys


# ── Angle helpers ─────────────────────────────────────────────────

def snap_angle_8dir(angle: float) -> float:
    """Snap *angle* (radians) to the nearest 45° increment.

    Returns a value in ``[0, 2π)``.
    """
    step = math.pi / 4.0
    snapped = round(angle / step) * step
    return snapped % (2.0 * math.pi)


def angle_to_label(angle: float) -> str:
    """Return a human-readable compass label for an angle (radians, 0 = east).

    Returns one of: E, NE, N, NW, W, SW, S, SE.
    """
    idx = round(angle / (math.pi / 4.0)) % 8
    return ("E", "NE", "N", "NW", "W", "SW", "S", "SE")[idx]
