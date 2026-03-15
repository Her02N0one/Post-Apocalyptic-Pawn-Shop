"""editor/app/entity_writer.py — Read/write entity_defs.toml.

Provides functions to:

1. Load the raw TOML data as a mutable ``{entity_id: {field: value}}`` dict
2. Add / update / remove entity entries
3. Re-serialize the entire file back to well-formatted TOML

No external TOML writer library is required — all serialization is done
with a lightweight hand-written formatter that mirrors the style of the
existing file.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]


_DEFS_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "entity_defs.toml"

_BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")

# ── Field ordering ────────────────────────────────────────────────

_TOP_LEVEL_ORDER: list[str] = [
    "display_name", "category", "render_type", "color", "scale",
    "directional", "sprite_key", "states",
    "width", "depth", "height", "elevation",
    "movable",
]

_COMPONENT_ORDER: list[str] = [
    "textures", "identity", "sprite", "health", "collider",
    "facing", "player", "inventory", "tile_entity", "wall_sprite",
    "combat", "dialogue",
]

_CATEGORY_ORDER: list[str] = ["characters", "props", "gameplay"]

_CATEGORY_HEADERS: dict[str, str] = {
    "characters": "Characters — billboard entities with directional sprites",
    "props":      "Props — textured prism entities",
    "gameplay":   "Gameplay — system entities",
}

_FILE_HEADER = """\
# Entity Definitions — unified type registry.
#
# Each entry defines a placeable entity type.  Everything about an
# entity lives here: visual/placement data (editor + renderer) AND
# default ECS component values (spawner).
#
# ── Top-level fields ──────────────────────────────────────────────
#   display_name  — Human-readable label
#   category      — Editor palette grouping
#   render_type   — "billboard" | "prism" (default: "billboard")
#   color         — [R, G, B] flat-colour fallback (0-255)
#   scale         — Billboard height in world units (default 1.0)
#   directional   — Whether the entity has facing-dependent visuals
#   states        — Visual state keys (texture/animation variants)
#   sprite_key    — Base texture key for billboard sprites
#   width/depth/height/elevation — Prism geometry (render_type = "prism")
#   movable       — Player can push this object (default false)
#
# ── Component sub-tables ─────────────────────────────────────────
#   [id.identity]    — name, kind
#   [id.sprite]      — char, color, layer, billboard_mode, sprite_key
#   [id.health]      — current, maximum
#   [id.collider]    — w, h, solid
#   [id.facing]      — direction
#   [id.player]      — speed
#   [id.inventory]   — items
#   [id.tile_entity] — tile_type, loot_table, item_id, item_qty
#   [id.wall_sprite] — texture_key, width, height, elevation
#   [id.combat]      — damage, attack_range, attack_cooldown, hostile
#   [id.dialogue]    — bark
#   [id.textures]    — north, south, east, west, top, bottom (prism faces)
"""


# ── Public API ────────────────────────────────────────────────────

def load_raw() -> dict[str, dict[str, Any]]:
    """Load entity_defs.toml and return the raw dict of entity dicts."""
    if not _DEFS_PATH.exists():
        return {}
    with open(_DEFS_PATH, "rb") as f:
        data = tomllib.load(f)
    return {k: v for k, v in data.items() if isinstance(v, dict)}


def save_all(data: dict[str, dict[str, Any]]) -> None:
    """Serialize *data* and write it to ``entity_defs.toml``."""
    _DEFS_PATH.write_text(serialize_all(data))


def add_or_update(entity_id: str, fields: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Add or update one entity, preserving all other entries.

    When updating an existing entity, only the keys present in *fields*
    are overwritten — component sub-tables that aren't in *fields* are
    kept intact.

    Returns the full (modified) data dict.
    """
    data = load_raw()
    if entity_id in data:
        existing = data[entity_id]
        for k, v in fields.items():
            existing[k] = v
    else:
        data[entity_id] = dict(fields)
    save_all(data)
    return data


def remove_entity(entity_id: str) -> dict[str, dict[str, Any]]:
    """Remove an entity from the TOML.  Returns the modified data dict."""
    data = load_raw()
    data.pop(entity_id, None)
    save_all(data)
    return data


# ── Serialization helpers ─────────────────────────────────────────

def _toml_key(key: str) -> str:
    """Return *key* bare or quoted as needed."""
    if _BARE_KEY.match(key):
        return key
    escaped = key.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _toml_value(val: Any) -> str:  # noqa: C901 (complexity OK for serializer)
    """Format a Python value as a TOML value literal."""
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, int):
        return str(val)
    if isinstance(val, float):
        # Always emit a decimal point so TOML reads it back as float.
        if val == int(val) and abs(val) < 1e15:
            return f"{val:.1f}"
        return repr(val)
    if isinstance(val, str):
        escaped = val.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(val, (list, tuple)):
        if not val:
            return "[]"
        items = [_toml_value(v) for v in val]
        return f"[{', '.join(items)}]"
    if isinstance(val, dict):
        if not val:
            return "{}"
        items = [f"{_toml_key(k)} = {_toml_value(v)}" for k, v in val.items()]
        return "{ " + ", ".join(items) + " }"
    return repr(val)


def _serialize_entity(eid: str, data: dict[str, Any]) -> list[str]:
    """Serialize one entity entry to a list of TOML lines."""
    lines: list[str] = [f"[{eid}]"]

    # Gather top-level (non-dict) keys in preferred order
    top_keys = [k for k in _TOP_LEVEL_ORDER
                if k in data and not isinstance(data[k], dict)]
    extra_top = [k for k in data
                 if k not in _TOP_LEVEL_ORDER and not isinstance(data[k], dict)]
    all_top = top_keys + extra_top
    pad = max((len(k) for k in all_top), default=8)
    pad = max(pad, 8)

    for key in all_top:
        lines.append(f"{key:<{pad}} = {_toml_value(data[key])}")

    # Component sub-tables
    written: set[str] = set()
    for comp in _COMPONENT_ORDER:
        if comp in data and isinstance(data[comp], dict):
            _write_component(lines, eid, comp, data[comp])
            written.add(comp)
    # Any component not in _COMPONENT_ORDER
    for comp, val in data.items():
        if isinstance(val, dict) and comp not in written:
            _write_component(lines, eid, comp, val)

    return lines


def _write_component(
    lines: list[str], eid: str, comp: str, cdata: dict[str, Any],
) -> None:
    """Append a ``[eid.comp]`` sub-table to *lines*."""
    lines.append("")
    lines.append(f"[{eid}.{comp}]")
    if not cdata:
        return
    pad = max((len(k) for k in cdata), default=4)
    pad = max(pad, 4)
    for k, v in cdata.items():
        lines.append(f"{k:<{pad}} = {_toml_value(v)}")


def serialize_all(data: dict[str, dict[str, Any]]) -> str:
    """Serialize the full entity-defs data to a complete TOML string."""
    parts: list[str] = [_FILE_HEADER]

    # Group by category
    by_cat: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for eid, edata in data.items():
        cat = edata.get("category", "misc")
        by_cat.setdefault(cat, []).append((eid, edata))

    order = list(_CATEGORY_ORDER) + sorted(
        c for c in by_cat if c not in _CATEGORY_ORDER
    )

    for cat in order:
        if cat not in by_cat:
            continue
        header = _CATEGORY_HEADERS.get(cat, cat.replace("_", " ").title())
        parts.append(f"# {'═' * 65}")
        parts.append(f"#  {header}")
        parts.append(f"# {'═' * 65}")
        parts.append("")

        for eid, edata in sorted(by_cat[cat], key=lambda x: x[0]):
            parts.extend(_serialize_entity(eid, edata))
            parts.append("")

    return "\n".join(parts) + "\n"
