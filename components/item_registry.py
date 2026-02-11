"""components.item_registry — Item data lookup table.

This is the only component with real business logic (field access,
cooldown defaults, etc.) so it lives in its own module.
"""

from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class ItemRegistry:
    """Lookup table mapping item IDs → full item data.

    Populated automatically by DataLoader when items.toml is loaded.
    Systems and UI can do::

        registry = world.res(ItemRegistry)
        name = registry.display_name("canned_beans")
        stats = registry.get_item("knife")
    """
    _entries: dict = field(default_factory=dict)

    # ── core helpers ─────────────────────────────────────────────────

    def register(self, item_id: str, name: str, char: str = "?",
                 color: tuple = (200, 200, 200), **extra):
        self._entries[item_id] = {
            "name": name, "char": char, "color": color,
            **extra,
        }

    def get_item(self, item_id: str) -> dict | None:
        """Full data dict for an item, or None."""
        return self._entries.get(item_id)

    def get_field(self, item_id: str, key: str, default=0.0):
        """Generic field accessor.

        Returns the value cast to the same type as *default*, or *default*
        itself when the item or key is missing.  For tuple fields (like
        ``proj_color``) pass a tuple default.
        """
        entry = self._entries.get(item_id)
        if not entry:
            return default
        raw = entry.get(key, default)
        # Match the type of *default* so callers always get a consistent type.
        if isinstance(default, float):
            return float(raw)
        if isinstance(default, int):
            return int(raw)
        if isinstance(default, tuple):
            return tuple(raw)
        return raw

    # ── semantic helpers (non-trivial logic) ─────────────────────────

    def display_name(self, item_id: str) -> str:
        """Human-readable name for an item ID, falling back to the ID itself."""
        entry = self._entries.get(item_id)
        return entry["name"] if entry else item_id

    def item_type(self, item_id: str) -> str:
        """Return the type string ('weapon', 'consumable', 'misc', …)."""
        entry = self._entries.get(item_id)
        return entry.get("type", "misc") if entry else "misc"

    def weapon_cooldown(self, item_id: str) -> float:
        """Attack cooldown in seconds. Falls back to style default."""
        entry = self._entries.get(item_id)
        if entry and "cooldown" in entry:
            return float(entry["cooldown"])
        style = self.get_field(item_id, "style", "melee")
        return 0.4 if style == "ranged" else 0.25

    def sprite_info(self, item_id: str) -> tuple[str, tuple]:
        """Return (char, color) for an item, with sensible defaults."""
        entry = self._entries.get(item_id)
        if entry:
            return entry["char"], tuple(entry["color"])
        return "?", (200, 200, 200)
