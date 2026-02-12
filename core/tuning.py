"""core/tuning.py — Data-driven tuning constants.

All gameplay numbers live in ``data/tuning.toml`` and are loaded once
at startup.  Any system can read a value with::

    from core.tuning import get
    speed = get("ai.helpers", "dodge_speed_mult", 3.0)

Hot-reload: call ``reload()`` to re-read the file.  In-game, press F4.
"""

from __future__ import annotations
import os
from pathlib import Path

try:
    import tomllib                         # Python 3.11+
except ModuleNotFoundError:
    try:
        import tomli as tomllib            # pip install tomli
    except ModuleNotFoundError:
        tomllib = None                     # type: ignore[assignment]


_data: dict = {}
_path: Path | None = None


def load(path: str | Path | None = None) -> None:
    """Load (or reload) tuning constants from *path*.

    If *path* is ``None``, default to ``data/tuning.toml`` relative to
    the project root (one level above ``core/``).
    """
    global _data, _path

    if path is None:
        root = Path(__file__).resolve().parent.parent
        path = root / "data" / "tuning.toml"
    else:
        path = Path(path)

    _path = path

    if not path.exists():
        print(f"[TUNING] {path} not found — using defaults")
        _data = {}
        return

    if tomllib is None:
        print("[TUNING] No TOML parser available (need Python 3.11+ or `pip install tomli`)")
        _data = {}
        return

    with open(path, "rb") as f:
        _data = tomllib.load(f)

    count = _count_leaves(_data)
    print(f"[TUNING] Loaded {count} values from {path}")


def reload() -> None:
    """Re-read the tuning file from disk (hot-reload)."""
    load(_path)


def get(section: str, key: str, default=None):
    """Read a tuning value.

    *section* uses dot-notation to traverse nested tables, e.g.
    ``"combat.melee"`` looks up ``[combat.melee]``.

    >>> get("combat.melee", "default_knockback", 3.0)
    3.0
    """
    node = _data
    for part in section.split("."):
        if isinstance(node, dict):
            node = node.get(part)
        else:
            return default
        if node is None:
            return default
    if isinstance(node, dict):
        return node.get(key, default)
    return default


def section(section_path: str) -> dict:
    """Return an entire section dict (shallow copy), or empty dict."""
    node = _data
    for part in section_path.split("."):
        if isinstance(node, dict):
            node = node.get(part)
        else:
            return {}
        if node is None:
            return {}
    if isinstance(node, dict):
        return dict(node)
    return {}


def _count_leaves(d: dict, _n: int = 0) -> int:
    for v in d.values():
        if isinstance(v, dict):
            _n = _count_leaves(v, _n)
        else:
            _n += 1
    return _n
