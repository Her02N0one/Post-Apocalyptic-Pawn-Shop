"""systems/item_registry.py — Item template lookup table.

Loads ``data/items.toml`` once and provides fast lookup for:
- display names
- sprite info (char, color)
- item type / style
- numeric fields (damage, heal, etc.)

Used by the inventory UI, dev panel, and ground-item spawner.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import tomllib                          # Python 3.11+
except ModuleNotFoundError:
    import tomli as tomllib                 # type: ignore[no-redef]


from core.paths import DATA_DIR as _DATA_DIR


@dataclass
class ItemDef:
    """Parsed item template."""
    id: str
    type: str = "misc"
    style: str = ""
    name: str = ""
    kind: str = "item"
    char: str = "?"
    color: tuple[int, int, int] = (200, 200, 200)
    fields: dict[str, Any] = field(default_factory=dict)


class ItemRegistry:
    """Singleton resource: loads all items from ``data/items.toml``."""

    def __init__(self) -> None:
        self._items: dict[str, ItemDef] = {}
        self._load()

    # ── Loading ────────────────────────────────────────────────────

    def _load(self) -> None:
        path = _DATA_DIR / "items.toml"
        if not path.exists():
            return
        try:
            with open(path, "rb") as f:
                raw = tomllib.load(f)
        except Exception as exc:
            print(f"[ITEM_REGISTRY] Failed to parse items.toml: {exc}")
            return

        for item_id, data in raw.items():
            if not isinstance(data, dict):
                continue
            ident = data.get("identity", {})
            sprite = data.get("sprite", {})
            color_raw = sprite.get("color", [200, 200, 200])
            if not isinstance(color_raw, (list, tuple)) or len(color_raw) < 3:
                color_raw = [200, 200, 200]
            color = (int(color_raw[0]), int(color_raw[1]), int(color_raw[2]))

            self._items[item_id] = ItemDef(
                id=item_id,
                type=data.get("type", "misc"),
                style=data.get("style", ""),
                name=ident.get("name", item_id),
                kind=ident.get("kind", "item"),
                char=sprite.get("char", "?"),
                color=color,
                fields={k: v for k, v in data.items()
                        if k not in ("identity", "sprite")},
            )

    # ── Public API ─────────────────────────────────────────────────

    def __contains__(self, item_id: str) -> bool:
        return item_id in self._items

    def __iter__(self):
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def ids(self) -> list[str]:
        """All item IDs sorted alphabetically."""
        return sorted(self._items)

    def get(self, item_id: str) -> ItemDef | None:
        return self._items.get(item_id)

    def display_name(self, item_id: str) -> str:
        d = self._items.get(item_id)
        return d.name if d else item_id

    def sprite_info(self, item_id: str) -> tuple[str, tuple[int, int, int]]:
        """Return (char, color) for an item."""
        d = self._items.get(item_id)
        if d:
            return d.char, d.color
        return "?", (200, 200, 200)

    def item_type(self, item_id: str) -> str:
        d = self._items.get(item_id)
        return d.type if d else "misc"

    def get_field(self, item_id: str, key: str, default: Any = None) -> Any:
        """Read an arbitrary numeric/string field from the item template."""
        d = self._items.get(item_id)
        if d is None:
            return default
        return d.fields.get(key, default)

    def to_descriptor(self, item_id: str) -> dict[str, Any]:
        """Build an entity descriptor dict for spawning this item as a ground entity."""
        d = self._items.get(item_id)
        if d is None:
            return {
                "prefab": "ground_item",
                "identity": {"name": item_id, "kind": "item"},
            }
        return {
            "prefab": "ground_item",
            "identity": {"name": d.name, "kind": "item"},
            "sprite": {"char": d.char, "color": list(d.color), "layer": 2},
            "tile_entity": {"tile_type": "ground_item", "item_id": item_id},
        }
