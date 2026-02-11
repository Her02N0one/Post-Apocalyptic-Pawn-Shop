"""core package initialization.

Making `core` an explicit package so imports like `import core.ecs`
work reliably when running `main.py` from the project root.
"""

__all__ = ["app", "ecs", "scene", "data"]
