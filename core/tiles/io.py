"""core/tiles/io.py — TOML persistence for tile definitions.

One file per tile in ``assets/models/tiles/{key}.toml``.
"""

from __future__ import annotations

import os as _os

try:
    import tomllib as _tomllib
except ModuleNotFoundError:
    import tomli as _tomllib  # type: ignore[no-redef]

from core.tiles.types import TileType, TF, TileDef, _TYPE_FLAGS, _TYPE_DEFAULT_HEIGHT
from core.tiles.registry import (
    TILE_REGISTRY, TILES_TOML_DIR, rebuild_derived,
)

_TILES_TOML_DIR = TILES_TOML_DIR


def _tile_toml_path(tile_key: str) -> str:
    return _os.path.join(_TILES_TOML_DIR, f"{tile_key}.toml")


def _parse_tile_toml(path: str) -> TileDef | None:
    try:
        with open(path, "rb") as f:
            data = _tomllib.load(f)
    except Exception:
        return None

    basename = _os.path.splitext(_os.path.basename(path))[0]
    if basename.startswith("_"):
        return None

    tile_key = basename
    raw_color = data.get("color", [120, 120, 120])
    color = (int(raw_color[0]), int(raw_color[1]), int(raw_color[2]))

    type_str = data.get("type", "floor")
    try:
        tile_type = TileType(type_str)
    except ValueError:
        tile_type = TileType.FLOOR
    flags = _TYPE_FLAGS.get(tile_type, TF.NONE)

    if data.get("transparent", False):
        flags |= TF.TRANSPARENT
    if data.get("farmland", False):
        flags |= TF.FARMLAND
    if data.get("thin_wall", False):
        flags |= TF.THIN_WALL
    if data.get("tall_wall", False):
        flags |= TF.TALL_WALL

    default_h = _TYPE_DEFAULT_HEIGHT.get(tile_type, 1.0)
    height = float(data.get("height", default_h))

    texture_key = data.get("texture", "")
    texture_front = data.get("texture_front", "")
    texture_back = data.get("texture_back", "")
    tex_n = data.get("tex_n", "")
    tex_s = data.get("tex_s", "")
    tex_e = data.get("tex_e", "")
    tex_w = data.get("tex_w", "")
    alt_texture = data.get("alt_texture", "")
    v_scale = float(data.get("v_scale", 1.0))

    return TileDef(
        id=tile_key,
        name=data.get("name", tile_key),
        color=color,
        type=tile_type,
        flags=flags,
        texture_key=texture_key,
        texture_front=texture_front,
        texture_back=texture_back,
        tex_n=tex_n, tex_s=tex_s, tex_e=tex_e, tex_w=tex_w,
        alt_texture=alt_texture,
        height_scale=height,
        v_scale=v_scale,
        category=data.get("category", "Custom"),
        sound=data.get("sound", "stone"),
    )


def _load_tiles_toml() -> bool:
    if not _os.path.isdir(_TILES_TOML_DIR):
        return False
    loaded = 0
    for fname in sorted(_os.listdir(_TILES_TOML_DIR)):
        if not fname.endswith(".toml") or fname.startswith("_"):
            continue
        td = _parse_tile_toml(_os.path.join(_TILES_TOML_DIR, fname))
        if td is not None:
            TILE_REGISTRY[td.id] = td
            loaded += 1
    if loaded == 0:
        return False
    rebuild_derived()
    return True


def _save_tile_toml(td: TileDef) -> str:
    lines: list[str] = []
    lines.append(f'name = "{td.name}"')
    lines.append(f'type = "{td.type.value}"')
    lines.append(f'category = "{td.category}"')
    lines.append(f'color = [{td.color[0]}, {td.color[1]}, {td.color[2]}]')

    if td.sound != "stone":
        lines.append(f'sound = "{td.sound}"')

    if td.texture_key:
        lines.append("")
        lines.append(f'texture = "{td.texture_key}"')
    if td.texture_front:
        lines.append(f'texture_front = "{td.texture_front}"')
    if td.texture_back:
        lines.append(f'texture_back = "{td.texture_back}"')
    if td.tex_n:
        lines.append(f'tex_n = "{td.tex_n}"')
    if td.tex_s:
        lines.append(f'tex_s = "{td.tex_s}"')
    if td.tex_e:
        lines.append(f'tex_e = "{td.tex_e}"')
    if td.tex_w:
        lines.append(f'tex_w = "{td.tex_w}"')

    if td.flags & TF.TRANSPARENT:
        lines.append("transparent = true")
    if td.flags & TF.FARMLAND:
        lines.append("farmland = true")
    if td.flags & TF.THIN_WALL:
        lines.append("thin_wall = true")
    if td.flags & TF.TALL_WALL:
        lines.append("tall_wall = true")
    if td.alt_texture:
        lines.append(f'alt_texture = "{td.alt_texture}"')

    default_h = _TYPE_DEFAULT_HEIGHT.get(td.type, 1.0)
    if td.height_scale != default_h:
        lines.append(f"height = {td.height_scale}")
    if td.v_scale != 1.0:
        lines.append(f"v_scale = {td.v_scale}")

    _os.makedirs(_TILES_TOML_DIR, exist_ok=True)
    path = _tile_toml_path(td.id)
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return path


def save_tiles() -> None:
    for td in TILE_REGISTRY.values():
        _save_tile_toml(td)
    rebuild_derived()


def save_tile(tile_id: str) -> None:
    td = TILE_REGISTRY.get(tile_id)
    if td:
        _save_tile_toml(td)
