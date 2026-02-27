"""build_ext.py — Build C-accelerated extensions.

Usage
-----
    python build_ext.py build_ext --inplace

This compiles ``engine/_fast_cast.c`` and ``engine/_fast_walls.c``
into ``.pyd`` (Windows) or ``.so`` (Linux/macOS) modules that the
renderer imports at runtime.  If compilation fails (no C compiler),
the pure-Python fallback is used automatically.

Requirements
------------
* **Windows**: Microsoft C++ Build Tools (``cl.exe``).
  Install via https://visualstudio.microsoft.com/visual-cpp-build-tools/
* **Linux / macOS**: ``gcc`` or ``clang`` (usually pre-installed).
"""

import platform
from setuptools import setup, Extension

# Optimisation flags for the C extensions
_extra_compile = []
if platform.system() != "Windows":
    _extra_compile = ["-O2", "-ffast-math"]

ext_cast = Extension(
    "engine._fast_cast",
    sources=["engine/_fast_cast.c"],
    language="c",
    extra_compile_args=_extra_compile,
)

ext_walls = Extension(
    "engine._fast_walls",
    sources=["engine/_fast_walls.c"],
    language="c",
    extra_compile_args=_extra_compile,
)

ext_ray_render = Extension(
    "engine._ray_render",
    sources=[
        "engine/_ray_render.c",
        "engine/_ray_entities.c",
        "engine/_ray_debug.c",
    ],
    language="c",
    extra_compile_args=_extra_compile,
)

setup(
    name="fast_extensions",
    ext_modules=[ext_cast, ext_walls, ext_ray_render],
)
