"""editor/entity_factory.py — Centralised entity creation.

All entity placement logic lives here so that PrefabPickerModal,
EditorApp (forge placement), and any future placement code use
the same validated builder instead of duplicating construction.
"""

from __future__ import annotations

import copy
from typing import Any

from editor.entity_defs import (
    EntityDef, EDPosition, EDIdentity, EDSprite, EDFacing,
    EDCollider, EDTileEntity, EDWallSprite, EDInventory,
    EDDialogue, EDHealth,
)


# ── Unique-ID generator ─────────────────────────────────────────────

def generate_unique_id(base: str, existing_ids: set[str]) -> str:
    """Return *base* if unused, otherwise append ``_N``."""
    if base not in existing_ids:
        return base
    n = 1
    while f"{base}_{n}" in existing_ids:
        n += 1
    return f"{base}_{n}"


def _existing_ids(entities: list) -> set[str]:
    """Extract IDs from a list of EntityDef or dict."""
    ids: set[str] = set()
    for e in entities:
        if isinstance(e, EntityDef):
            ids.add(e.id)
        elif isinstance(e, dict):
            ids.add(e.get("id", ""))
    return ids


# ── Prefab entity builder ───────────────────────────────────────────

_COMPONENT_KEYS = (
    "identity", "sprite", "tile_entity", "collider",
    "health", "facing", "inventory", "dialogue", "wall_sprite",
)


def create_prefab_entity(
    prefab_name: str,
    prefab_defaults: dict[str, dict],
    row: int,
    col: int,
    entities: list,
) -> EntityDef:
    """Build an EntityDef from a system prefab definition.

    Parameters
    ----------
    prefab_name:
        Key into *prefab_defaults*.
    prefab_defaults:
        Mapping of prefab name → default component dict.
    row, col:
        Map tile to place the entity at.
    entities:
        Existing entity list (used only for unique-ID generation;
        **not** mutated — caller must append).

    Returns
    -------
    A fully-constructed EntityDef ready to be appended.
    """
    pdef = prefab_defaults.get(prefab_name, {})
    uid = generate_unique_id(
        f"{prefab_name}_{len(entities)}",
        _existing_ids(entities),
    )

    ent = EntityDef(
        id=uid,
        prefab=prefab_name,
        position=EDPosition(x=float(col) + 0.5, y=float(row) + 0.5),
    )

    # Copy component data from prefab defaults
    if "identity" in pdef:
        i = pdef["identity"]
        ent.identity = EDIdentity(
            name=f"{prefab_name.replace('_', ' ').title()} ({uid})",
            kind=i.get("kind", "npc"),
        )
    if "sprite" in pdef:
        s = pdef["sprite"]
        ent.sprite = EDSprite(
            char=s.get("char", "?"),
            color=list(s.get("color", [200, 200, 200])),
            layer=int(s.get("layer", 5)),
        )
    if "facing" in pdef:
        ent.facing = EDFacing(direction=pdef["facing"].get("direction", "down"))
    if "collider" in pdef:
        c = pdef["collider"]
        ent.collider = EDCollider(
            w=float(c.get("w", 0.6)),
            h=float(c.get("h", 0.6)),
            solid=bool(c.get("solid", True)),
        )
    if "health" in pdef:
        h = pdef["health"]
        ent.health = EDHealth(
            current=float(h.get("current", 100)),
            maximum=float(h.get("maximum", 100)),
        )
    if "tile_entity" in pdef:
        te = pdef["tile_entity"]
        ent.tile_entity = EDTileEntity(
            tile_type=te.get("tile_type", "container"),
            loot_table=te.get("loot_table", ""),
        )
    if "wall_sprite" in pdef:
        ws = pdef["wall_sprite"]
        ent.wall_sprite = EDWallSprite(
            texture_key=ws.get("texture_key", ""),
            width=float(ws.get("width", 1.0)),
            height=float(ws.get("height", 1.0)),
            elevation=float(ws.get("elevation", 0.0)),
        )
    if "inventory" in pdef:
        ent.inventory = EDInventory(
            items=dict(pdef["inventory"].get("items", {})))
    if "dialogue" in pdef:
        ent.dialogue = EDDialogue(bark=pdef["dialogue"].get("bark", ""))

    return ent


# ── Forge archetype entity builder ──────────────────────────────────

def create_forge_entity(
    arch,                        # ForgeArchetype from forge_registry
    row: int,
    col: int,
    entities: list,
) -> EntityDef:
    """Build an EntityDef from a Forge archetype.

    Parameters
    ----------
    arch:
        A ``ForgeArchetype`` instance (from :mod:`editor.forge_registry`).
    row, col:
        Map tile to place the entity at.
    entities:
        Existing entity list (not mutated).

    Returns
    -------
    A fully-constructed EntityDef.
    """
    uid = generate_unique_id(
        f"{arch.id}_{len(entities)}",
        _existing_ids(entities),
    )

    ent = EntityDef(
        id=uid,
        forge_archetype=arch.id,
        position=EDPosition(x=float(col) + 0.5, y=float(row) + 0.5),
        identity=EDIdentity(
            name=arch.display_name or arch.id.replace("_", " ").title(),
            kind=arch.kind,
        ),
        sprite=EDSprite(
            char=(
                arch.sprite_char if arch.kind == "billboard"
                else ("\u25A3" if arch.kind == "tile" else "\u25A1")
            ),
            color=list(
                arch.sprite_color if arch.kind == "billboard"
                else arch.color
            ),
            layer=5,
        ),
    )

    if arch.dev_notes:
        ent.dev_notes = arch.dev_notes
    if arch.tags:
        ent.tags = list(arch.tags)

    # Kind-specific components
    if arch.kind == "tile":
        ent.tile_entity = EDTileEntity(tile_type="container")
        if arch.texture_key:
            ent.wall_sprite = EDWallSprite(
                texture_key=arch.texture_key,
                width=1.0,
                height=arch.ceiling_z - arch.floor_z,
                elevation=arch.floor_z,
            )
    elif arch.kind == "box":
        if arch.solid:
            ent.collider = EDCollider(w=arch.width, h=arch.depth,
                                      solid=True)
        if arch.texture_key:
            ent.wall_sprite = EDWallSprite(
                texture_key=arch.texture_key,
                width=arch.width,
                height=arch.height,
                elevation=arch.z_offset,
            )
    elif arch.kind == "billboard":
        if arch.solid:
            ent.collider = EDCollider(w=0.4, h=0.4, solid=True)

    return ent
