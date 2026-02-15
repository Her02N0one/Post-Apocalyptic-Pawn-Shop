"""core package initialization.

Making `core` an explicit package so imports like `import core.ecs`
work reliably when running `main.py` from the project root.

Submodules
----------
app, ecs, scene, data, events, save, nbt, constants, tuning, zone, subzone
"""

__all__ = ["app", "ecs", "scene", "data", "subzone"]
