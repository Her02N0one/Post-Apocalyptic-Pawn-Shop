"""Loot table system — Minecraft-style loot generation.

Uses real item IDs from items.toml.  Display names come from ItemRegistry.

Usage:
    # At startup (main.py):
    loot_mgr = LootTableManager.from_file("data/loot_tables.toml")
    app.world.set_res(loot_mgr)

    # At runtime:
    mgr = world.res(LootTableManager)
    items = mgr.roll("basic_chest")   # → ["canned_beans", "canned_beans", "bandages"]
"""

from __future__ import annotations
import random
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class _Entry:
    item: str
    weight: float = 1.0
    min_count: int = 1
    max_count: int = 1


@dataclass
class _Pool:
    name: str = ""
    rolls: int = 1
    bonus_rolls: float = 0.0
    entries: list[_Entry] = field(default_factory=list)

    def roll(self) -> list[str]:
        if not self.entries:
            return []
        items: list[str] = []
        count = self.rolls
        if self.bonus_rolls > 0 and random.random() < self.bonus_rolls:
            count += 1
        for _ in range(count):
            entry = self._weighted_choice()
            n = random.randint(entry.min_count, entry.max_count)
            items.extend([entry.item] * n)
        return items

    def _weighted_choice(self) -> _Entry:
        total = sum(e.weight for e in self.entries)
        r = random.uniform(0, total)
        cur = 0.0
        for e in self.entries:
            cur += e.weight
            if r <= cur:
                return e
        return self.entries[-1]


@dataclass
class _Table:
    name: str = ""
    description: str = ""
    pools: list[_Pool] = field(default_factory=list)

    def roll(self) -> list[str]:
        items: list[str] = []
        for pool in self.pools:
            items.extend(pool.roll())
        return items


class LootTableManager:
    """World resource — stores all loot tables loaded from TOML."""

    def __init__(self):
        self.tables: dict[str, _Table] = {}

    # ── public API ──────────────────────────────────────────────────

    def roll(self, table_name: str) -> list[str]:
        """Roll a table and return a list of item IDs."""
        tbl = self.tables.get(table_name)
        if tbl is None:
            print(f"[LOOT] unknown table: {table_name}")
            return []
        return tbl.roll()

    # ── loading ─────────────────────────────────────────────────────

    @classmethod
    def from_file(cls, filepath: str | Path) -> "LootTableManager":
        mgr = cls()
        filepath = Path(filepath)
        if not filepath.exists():
            alt = Path(__file__).parent.parent / "data" / "loot_tables.toml"
            filepath = alt if alt.exists() else filepath
        if not filepath.exists():
            print(f"[LOOT] file not found: {filepath}")
            return mgr

        with open(filepath, "rb") as f:
            data = tomllib.load(f)

        for tname, tdata in data.get("tables", {}).items():
            pools = []
            for pdata in tdata.get("pools", []):
                entries = [
                    _Entry(
                        item=e.get("item", "unknown"),
                        weight=float(e.get("weight", 1)),
                        min_count=int(e.get("min_count", 1)),
                        max_count=int(e.get("max_count", 1)),
                    )
                    for e in pdata.get("entries", [])
                ]
                pools.append(_Pool(
                    name=pdata.get("name", ""),
                    rolls=int(pdata.get("rolls", 1)),
                    bonus_rolls=float(pdata.get("bonus_rolls", 0)),
                    entries=entries,
                ))
            mgr.tables[tname] = _Table(name=tname, description=tdata.get("description", ""), pools=pools)

        print(f"[LOOT] loaded {len(mgr.tables)} tables")
        return mgr
