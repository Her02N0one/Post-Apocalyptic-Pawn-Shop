"""core/tiles/crud.py — Tile CRUD operations (editor API).

Create, update, delete tiles; manage categories; legacy compat shims.
"""

from __future__ import annotations

import os as _os
from typing import Any

from core.tiles.types import (
    TileType, TF, TileDef, _TYPE_FLAGS, _TYPE_DEFAULT_HEIGHT, _type_from_flags,
)
from core.tiles.registry import (
    TILE_REGISTRY, TILE_CATEGORIES, rebuild_derived,
)
from core.tiles.io import _tile_toml_path, _save_tile_toml


def _next_tile_key(name: str) -> str:
    key = name.lower().replace(" ", "_")
    if key not in TILE_REGISTRY:
        return key
    i = 2
    while f"{key}_{i}" in TILE_REGISTRY:
        i += 1
    return f"{key}_{i}"


def register_tile(
    name: str,
    color: tuple[int, int, int],
    tile_type: TileType = TileType.FLOOR,
    flags: TF | None = None,
    texture_key: str = "",
    texture_front: str = "",
    texture_back: str = "",
    tex_n: str = "",
    tex_s: str = "",
    tex_e: str = "",
    tex_w: str = "",
    alt_texture: str = "",
    height_scale: float | None = None,
    category: str = "Custom",
    sound: str = "stone",
    *,
    tile_key: str = "",
    face_textures: dict[str, str] | None = None,
    front_texture: str = "",
) -> TileDef:
    key = tile_key or _next_tile_key(name)
    if flags is None:
        flags = _TYPE_FLAGS.get(tile_type, TF.NONE)
    if height_scale is None:
        height_scale = _TYPE_DEFAULT_HEIGHT.get(tile_type, 1.0)

    if face_textures:
        if not texture_front:
            texture_front = face_textures.get("south", "")
        if not texture_back:
            texture_back = face_textures.get("north", "")
    if front_texture and not texture_front:
        texture_front = front_texture

    td = TileDef(
        id=key, name=name, color=color, type=tile_type,
        flags=flags, texture_key=texture_key,
        texture_front=texture_front, texture_back=texture_back,
        tex_n=tex_n, tex_s=tex_s, tex_e=tex_e, tex_w=tex_w,
        alt_texture=alt_texture,
        height_scale=height_scale,
        category=category, sound=sound,
    )
    TILE_REGISTRY[key] = td
    rebuild_derived()
    _save_tile_toml(td)
    return td


def update_tile(tile_id: str, **kwargs: Any) -> TileDef | None:
    old = TILE_REGISTRY.get(tile_id)
    if old is None:
        return None
    old_toml = _tile_toml_path(old.id)

    fields: dict[str, Any] = {
        "id": old.id, "name": old.name, "color": old.color,
        "type": old.type, "flags": old.flags,
        "texture_key": old.texture_key,
        "texture_front": old.texture_front,
        "texture_back": old.texture_back,
        "tex_n": old.tex_n, "tex_s": old.tex_s,
        "tex_e": old.tex_e, "tex_w": old.tex_w,
        "alt_texture": old.alt_texture,
        "height_scale": old.height_scale, "category": old.category,
        "sound": old.sound,
    }

    if "face_textures" in kwargs:
        ft = kwargs.pop("face_textures")
        if isinstance(ft, dict):
            if "south" in ft:
                fields["texture_front"] = ft["south"]
            if "north" in ft:
                fields["texture_back"] = ft["north"]
        elif isinstance(ft, tuple):
            d = dict(ft)
            if "south" in d:
                fields["texture_front"] = d["south"]
            if "north" in d:
                fields["texture_back"] = d["north"]
    if "front_texture" in kwargs:
        fields["texture_front"] = kwargs.pop("front_texture")
    if "floor_texture" in kwargs:
        kwargs.pop("floor_texture")

    fields.update(kwargs)

    if "type" in kwargs and "flags" not in kwargs:
        fields["flags"] = _TYPE_FLAGS.get(fields["type"], TF.NONE)

    td = TileDef(**fields)
    TILE_REGISTRY[td.id] = td
    rebuild_derived()

    new_toml = _tile_toml_path(td.id)
    if old_toml != new_toml and _os.path.exists(old_toml):
        _os.remove(old_toml)
    _save_tile_toml(td)
    return td


def delete_tile(tile_id: str) -> bool:
    td = TILE_REGISTRY.get(tile_id)
    if td is None:
        return False
    path = _tile_toml_path(td.id)
    if _os.path.exists(path):
        _os.remove(path)
    del TILE_REGISTRY[tile_id]
    rebuild_derived()
    return True


def add_category(name: str) -> None:
    if name and name not in TILE_CATEGORIES:
        TILE_CATEGORIES.append(name)


def remove_category(name: str) -> None:
    if name in TILE_CATEGORIES:
        TILE_CATEGORIES.remove(name)
        for tid, td in list(TILE_REGISTRY.items()):
            if td.category == name:
                update_tile(tid, category="Custom")


# ── Legacy compat aliases ────────────────────────────────────────

def register_custom_tile(name, color, flags=TF.NONE, texture_key="",
                         height_scale=1.0, category="Custom"):
    tile_type = _type_from_flags(flags)
    return register_tile(name, color, tile_type=tile_type, flags=flags,
                         texture_key=texture_key, height_scale=height_scale,
                         category=category)


def delete_custom_tile(tile_id):
    return delete_tile(tile_id)


def save_custom_tiles():
    from core.tiles.io import save_tiles
    save_tiles()


def load_custom_tiles():
    pass


def _next_custom_id():
    return _next_tile_key("custom")
