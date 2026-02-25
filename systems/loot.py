"""systems.loot — Loot table rolling.

Pure function that reads ``data/loot_tables.toml`` and returns a
random item selection.

Usage::

    from systems.loot import roll_loot
    items = roll_loot("crate_common")  # {"scrap": 3, "bandage": 1}
"""

from __future__ import annotations

import logging
import random
from typing import Any

_log = logging.getLogger(__name__)

# Loot table data — cached after first load
_loot_data: dict[str, Any] | None = None


def _get_loot_data() -> dict[str, Any]:
    """Return cached loot-table data, loading from disk on first call."""
    global _loot_data
    if _loot_data is not None:
        return _loot_data
    try:
        try:
            import tomllib
        except ModuleNotFoundError:
            import tomli as tomllib  # type: ignore[no-redef]
        from core.paths import LOOT_TABLES_PATH
        path = LOOT_TABLES_PATH
        with open(path, "rb") as f:
            _loot_data = tomllib.load(f)
    except Exception as exc:
        _log.warning("Failed to load loot_tables.toml: %s", exc)
        _loot_data = {}
    return _loot_data


def roll_loot(table_id: str) -> dict[str, int]:
    """Roll a loot table and return ``{item_id: count}``."""
    try:
        data = _get_loot_data()
        table = data.get("tables", {}).get(table_id)
        if not table:
            return {}
        items: dict[str, int] = {}
        for pool in table.get("pools", []):
            rolls = int(pool.get("rolls", 1))
            bonus = pool.get("bonus_rolls", 0)
            if bonus:
                rolls += int(random.random() * bonus)
            entries = pool.get("entries", [])
            if not entries:
                continue
            weights = [e.get("weight", 1) for e in entries]
            for _ in range(rolls):
                chosen = random.choices(entries, weights=weights, k=1)[0]
                item = chosen.get("item", "")
                lo = chosen.get("min_count", 1)
                hi = chosen.get("max_count", 1)
                count = random.randint(lo, hi)
                items[item] = items.get(item, 0) + count
        return items
    except Exception as exc:
        _log.warning("roll_loot(%s) failed: %s", table_id, exc)
        return {}
