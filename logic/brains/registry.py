"""logic/brains/registry.py — Brain name → function mapping.

Keeps the registry as a separate module so brain modules can import
``register_brain`` without pulling in the full runner (avoids cycles).
"""

from __future__ import annotations
from typing import Callable


_registry: dict[str, Callable] = {}


def register_brain(name: str, fn: Callable) -> None:
    """Register *fn* as the brain tick function for *name*."""
    _registry[name] = fn


def get_brain(name: str) -> Callable | None:
    """Return the brain function for *name*, or ``None``."""
    return _registry.get(name)


def registered_names() -> list[str]:
    """Return a sorted list of all registered brain names."""
    return sorted(_registry.keys())
