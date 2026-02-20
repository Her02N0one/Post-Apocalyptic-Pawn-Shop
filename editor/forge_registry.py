"""editor/forge_registry.py — Load / save / query custom entity archetypes.

Reads ``data/custom_entities.toml`` and provides typed lookup for the
Entity Forge UI and the runtime spawner.

    from editor.forge_registry import ForgeRegistry
    reg = ForgeRegistry.instance()
    crate = reg.get("wooden_crate")
    boxes = reg.by_kind("box")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DATA_PATH = _PROJECT_ROOT / "data" / "custom_entities.toml"


# ── Archetype dataclass ─────────────────────────────────────────────

@dataclass
class ForgeArchetype:
    """One custom entity definition from the TOML file."""
    id: str
    kind: str                                  # "tile" | "box" | "billboard"
    display_name: str = ""
    dev_notes: str = ""
    tags: list[str] = field(default_factory=list)

    # ── tile ──
    texture_key: str = ""
    floor_z: float = 0.0
    ceiling_z: float = 1.0
    solid: bool = True
    transparent: bool = False

    # ── box ──
    width: float = 0.5
    depth: float = 0.5
    height: float = 0.5
    z_offset: float = 0.0
    face_textures: dict[str, str] = field(default_factory=dict)
    color: tuple[int, int, int] = (180, 180, 180)

    # ── billboard ──
    sprite_char: str = "?"
    sprite_color: tuple[int, int, int] = (200, 200, 200)
    directional: bool = False
    sprite_sheet: str = ""
    directions: list[str] = field(default_factory=lambda: [
        "N", "NE", "E", "SE", "S", "SW", "W", "NW",
    ])
    scale: float = 1.0


# ── TOML I/O ────────────────────────────────────────────────────────

def _load_tomllib():
    """Return the best available TOML reader."""
    try:
        import tomllib          # Python 3.11+
        return tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef]
        return tomllib


def _parse_color(raw) -> tuple[int, int, int]:
    """Coerce a TOML list to an (R, G, B) tuple."""
    if isinstance(raw, (list, tuple)) and len(raw) >= 3:
        return (int(raw[0]), int(raw[1]), int(raw[2]))
    return (180, 180, 180)


def _archetype_from_dict(aid: str, d: dict[str, Any]) -> ForgeArchetype:
    """Build an archetype from a single ``[entities.<id>]`` table."""
    kind = d.get("kind", "billboard")
    ft_raw = d.get("face_textures", {})
    face_textures = {str(k): str(v) for k, v in ft_raw.items()} if ft_raw else {}
    return ForgeArchetype(
        id=aid,
        kind=kind,
        display_name=d.get("display_name", aid.replace("_", " ").title()),
        dev_notes=d.get("dev_notes", ""),
        tags=list(d.get("tags", [])),
        # tile
        texture_key=d.get("texture_key", ""),
        floor_z=float(d.get("floor_z", 0.0)),
        ceiling_z=float(d.get("ceiling_z", 1.0)),
        solid=bool(d.get("solid", True)),
        transparent=bool(d.get("transparent", False)),
        # box
        width=float(d.get("width", 0.5)),
        depth=float(d.get("depth", 0.5)),
        height=float(d.get("height", 0.5)),
        z_offset=float(d.get("z_offset", 0.0)),
        face_textures=face_textures,
        color=_parse_color(d.get("color", [180, 180, 180])),
        # billboard
        sprite_char=str(d.get("sprite_char", "?")),
        sprite_color=_parse_color(d.get("sprite_color", [200, 200, 200])),
        directional=bool(d.get("directional", False)),
        sprite_sheet=str(d.get("sprite_sheet", "")),
        directions=list(d.get("directions", ["N", "NE", "E", "SE", "S", "SW", "W", "NW"])),
        scale=float(d.get("scale", 1.0)),
    )


# ── Registry ────────────────────────────────────────────────────────

class ForgeRegistry:
    """In-memory cache of all custom entity archetypes."""

    _instance: "ForgeRegistry | None" = None

    def __init__(self) -> None:
        self._archetypes: dict[str, ForgeArchetype] = {}
        self.reload()

    @classmethod
    def instance(cls) -> "ForgeRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── I/O ──────────────────────────────────────────────────────

    def reload(self) -> None:
        """(Re)load from disk."""
        self._archetypes.clear()
        if not _DATA_PATH.exists():
            return
        try:
            tomllib = _load_tomllib()
            with open(_DATA_PATH, "rb") as f:
                data = tomllib.load(f)
            entities = data.get("entities", {})
            for aid, body in entities.items():
                if isinstance(body, dict):
                    self._archetypes[aid] = _archetype_from_dict(aid, body)
        except Exception as exc:
            print(f"[ForgeRegistry] Load error: {exc}")

    def save(self) -> bool:
        """Write all archetypes back to TOML (hand-serialised)."""
        def _q(s: str) -> str:
            """Escape a string for TOML double-quoted value."""
            return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")

        lines: list[str] = [
            "# Custom Entities \u2014 Entity Forge Output",
            "# Auto-generated by the Map Editor Entity Forge.",
            "",
        ]
        for aid, a in sorted(self._archetypes.items()):
            lines.append(f"[entities.{aid}]")
            lines.append(f'kind          = "{_q(a.kind)}"')
            lines.append(f'display_name  = "{_q(a.display_name)}"')
            lines.append(f'dev_notes     = "{_q(a.dev_notes)}"')
            tags_str = ", ".join(f'"{_q(t)}"' for t in a.tags)
            lines.append(f'tags          = [{tags_str}]')

            if a.kind == "tile":
                lines.append(f'texture_key   = "{_q(a.texture_key)}"')
                lines.append(f'floor_z       = {a.floor_z}')
                lines.append(f'ceiling_z     = {a.ceiling_z}')
                lines.append(f'solid         = {"true" if a.solid else "false"}')
                lines.append(f'transparent   = {"true" if a.transparent else "false"}')

            elif a.kind == "box":
                lines.append(f'width         = {a.width}')
                lines.append(f'depth         = {a.depth}')
                lines.append(f'height        = {a.height}')
                lines.append(f'z_offset      = {a.z_offset}')
                lines.append(f'solid         = {"true" if a.solid else "false"}')
                lines.append(f'color         = [{a.color[0]}, {a.color[1]}, {a.color[2]}]')
                if a.face_textures:
                    lines.append("")
                    lines.append(f"[entities.{aid}.face_textures]")
                    for face, tex in sorted(a.face_textures.items()):
                        lines.append(f'{face} = "{_q(tex)}"')

            elif a.kind == "billboard":
                lines.append(f'sprite_char   = "{_q(a.sprite_char)}"')
                lines.append(f'sprite_color  = [{a.sprite_color[0]}, {a.sprite_color[1]}, {a.sprite_color[2]}]')
                lines.append(f'directional   = {"true" if a.directional else "false"}')
                lines.append(f'sprite_sheet  = "{_q(a.sprite_sheet)}"')
                lines.append(f'scale         = {a.scale}')

            lines.append("")
            lines.append("")

        try:
            _DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(_DATA_PATH, "w") as f:
                f.write("\n".join(lines))
            return True
        except IOError as exc:
            print(f"[ForgeRegistry] Save error: {exc}")
            return False

    # ── Lookup ───────────────────────────────────────────────────

    def get(self, aid: str) -> ForgeArchetype | None:
        return self._archetypes.get(aid)

    def all(self) -> dict[str, ForgeArchetype]:
        return dict(self._archetypes)

    def by_kind(self, kind: str) -> list[ForgeArchetype]:
        return [a for a in self._archetypes.values() if a.kind == kind]

    def by_tag(self, tag: str) -> list[ForgeArchetype]:
        return [a for a in self._archetypes.values() if tag in a.tags]

    def ids(self) -> list[str]:
        return sorted(self._archetypes.keys())

    # ── Mutation ─────────────────────────────────────────────────

    def upsert(self, archetype: ForgeArchetype) -> None:
        self._archetypes[archetype.id] = archetype

    def delete(self, aid: str) -> bool:
        if aid in self._archetypes:
            del self._archetypes[aid]
            return True
        return False
