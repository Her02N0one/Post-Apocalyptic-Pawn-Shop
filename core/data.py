"""
core/data.py — TOML → ECS loader

Reads data files and spawns entities with the right components.
The mapping from TOML keys to component constructors lives here.

You define your components in components.py.
You define your game content in .toml files.
This file connects them.

Usage:
    loader = DataLoader(world)
    loader.register("position", Position)      # maps TOML key → component class
    loader.register("health", Health)
    item_ids = loader.load("data/items.toml")   # returns {name: entity_id}
"""

from __future__ import annotations
try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    import tomli as tomllib
from pathlib import Path
from dataclasses import fields
from core.ecs import World


class DataLoader:
    def __init__(self, world: World):
        self.world = world
        self._registry: dict[str, type] = {}

    def register(self, key: str, comp_type: type):
        """Map a TOML section name to a component class.

        In the TOML file:
            [harlan.position]
            x = 5.0
            y = 3.0

        With register("position", Position), this creates
        Position(x=5.0, y=3.0) on harlan's entity.
        """
        self._registry[key] = comp_type

    def load(self, path: str | Path) -> dict[str, int]:
        """Load a TOML file. Each top-level key becomes an entity.
        Returns {name: entity_id} so you can reference them."""
        path = Path(path)
        with open(path, "rb") as f:
            data = tomllib.load(f)

        ids: dict[str, int] = {}

        for name, section in data.items():
            if not isinstance(section, dict):
                continue

            eid = self.world.spawn()
            ids[name] = eid

            for key, value in section.items():
                if key in self._registry and isinstance(value, dict):
                    # Nested table → component with kwargs
                    comp_type = self._registry[key]
                    comp = _build_component(comp_type, value)
                    self.world.add(eid, comp)
                elif key in self._registry:
                    # Bare value → component with single positional arg
                    comp_type = self._registry[key]
                    comp = comp_type(value)
                    self.world.add(eid, comp)

        return ids

    def load_items(self, path: str | Path) -> dict[str, int]:
        """Load items.toml and automatically populate the ItemRegistry resource.

        Returns {item_id: entity_id} just like load(), but also registers
        every item's display name, char, and color into the world's ItemRegistry.
        """
        from components import ItemRegistry, Identity, Sprite

        # Ensure the ItemRegistry resource exists
        registry = self.world.res(ItemRegistry)
        if registry is None:
            registry = ItemRegistry()
            self.world.set_res(registry)

        ids = self.load(path)

        # Post-process: extract display info + stats into the registry
        # Read the raw TOML again so we can grab top-level keys like type/damage
        with open(Path(path), "rb") as _f:
            raw = tomllib.load(_f)

        for item_id, eid in ids.items():
            ident = self.world.get(eid, Identity)
            sprite = self.world.get(eid, Sprite)
            name = ident.name if ident else item_id
            char = sprite.char if sprite else "?"
            color = sprite.color if sprite else (200, 200, 200)
            # Collect extra stats from raw TOML (type, damage, defense, reach, heal…)
            section = raw.get(item_id, {})
            extra: dict = {}
            for k, v in section.items():
                if not isinstance(v, dict):  # skip sub-tables like [id.identity]
                    extra[k] = v
            registry.register(item_id, name, char, color, **extra)

        return ids


def _build_component(comp_type: type, kwargs: dict):
    """Build a dataclass instance, skipping unknown fields."""
    valid = {f.name for f in fields(comp_type)} if hasattr(comp_type, '__dataclass_fields__') else set()
    if valid:
        filtered = {k: v for k, v in kwargs.items() if k in valid}
        return comp_type(**filtered)
    return comp_type(**kwargs)
