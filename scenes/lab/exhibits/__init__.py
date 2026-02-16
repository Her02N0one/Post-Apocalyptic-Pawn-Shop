"""scenes/lab/exhibits — Museum exhibit modules.

Each exhibit is a self-contained class that owns its setup, update,
draw, and teardown logic.  MuseumScene acts as a thin tab-bar host
that delegates to the active exhibit.

Exhibits are **auto-discovered** at runtime: any ``*_exhibit.py`` file
in this package that defines an :class:`Exhibit` subclass will be
picked up automatically.  You can delete every exhibit file from this
folder and the museum will simply show an empty picker — then drop a
new ``*_exhibit.py`` back in and it reappears.

See ``base.py`` for the Exhibit protocol.
"""

from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
from pathlib import Path

from scenes.lab.exhibits.base import Exhibit

_log = logging.getLogger(__name__)


def discover_exhibits() -> list[type[Exhibit]]:
    """Scan this package for Exhibit subclasses and return them sorted by name.

    Only considers modules whose filename matches ``*_exhibit.py``.
    Modules that fail to import are logged and silently skipped so one
    broken exhibit never takes down the whole museum.
    """
    pkg_dir = Path(__file__).resolve().parent
    found: list[type[Exhibit]] = []

    for info in pkgutil.iter_modules([str(pkg_dir)]):
        if not info.name.endswith("_exhibit"):
            continue
        module_name = f"scenes.lab.exhibits.{info.name}"
        try:
            mod = importlib.import_module(module_name)
        except Exception:
            _log.warning("Failed to import exhibit module %s", module_name,
                         exc_info=True)
            continue
        for _attr_name, obj in inspect.getmembers(mod, inspect.isclass):
            if issubclass(obj, Exhibit) and obj is not Exhibit:
                found.append(obj)

    # Stable sort by exhibit display name so picker order is predictable
    found.sort(key=lambda cls: getattr(cls, "name", cls.__name__))
    return found
