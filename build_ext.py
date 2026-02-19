"""build_ext.py — Build C-accelerated extensions.

Usage
-----
    python build_ext.py build_ext --inplace

This compiles ``systems/_fast_cast.c`` and ``systems/_fast_walls.c``
into ``.pyd`` (Windows) or ``.so`` (Linux/macOS) modules that the
renderer imports at runtime.  If compilation fails (no C compiler),
the pure-Python fallback is used automatically.

Requirements
------------
* **Windows**: Microsoft C++ Build Tools (``cl.exe``).
  Install via https://visualstudio.microsoft.com/visual-cpp-build-tools/
* **Linux / macOS**: ``gcc`` or ``clang`` (usually pre-installed).
"""

from setuptools import setup, Extension

ext_cast = Extension(
    "systems._fast_cast",
    sources=["systems/_fast_cast.c"],
    language="c",
)

ext_walls = Extension(
    "systems._fast_walls",
    sources=["systems/_fast_walls.c"],
    language="c",
)

setup(
    name="fast_extensions",
    ext_modules=[ext_cast, ext_walls],
)
