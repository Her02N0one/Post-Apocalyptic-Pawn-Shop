"""editor2/atlas.py — GL texture array built from tile PNGs.

Loads every tile PNG from ``assets/textures/tiles/`` into a
GL_TEXTURE_2D_ARRAY.  Each 128×128 tile occupies one layer.

Usage::

    atlas = TileAtlas()          # before GL context
    atlas.upload()               # after GL context init
    atlas.bind(texture_unit=0)   # before draw
    layer = atlas.layer("wall")  # integer layer for UVs
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
from OpenGL import GL as gl
from PIL import Image

from core.tiles import TILE_REGISTRY, tile_def, TILE_TEX_DIR
from core.tiles.registry import TILE_COLORS

_log = logging.getLogger(__name__)

TEX_SIZE = 128

_MISSING_KEY = "__missing__"


def _make_checkerboard() -> np.ndarray:
    """8×8 magenta/black checkerboard — unmistakable missing-texture signal."""
    tile = np.zeros((TEX_SIZE, TEX_SIZE, 4), dtype=np.uint8)
    cell = TEX_SIZE // 8
    for row in range(8):
        for col in range(8):
            if (row + col) % 2 == 0:
                r0, r1 = row * cell, (row + 1) * cell
                c0, c1 = col * cell, (col + 1) * cell
                tile[r0:r1, c0:c1] = (255, 0, 255, 255)
            else:
                r0, r1 = row * cell, (row + 1) * cell
                c0, c1 = col * cell, (col + 1) * cell
                tile[r0:r1, c0:c1] = (0, 0, 0, 255)
    return tile


class TileAtlas:
    """Manages a GL_TEXTURE_2D_ARRAY containing all tile textures."""

    def __init__(self) -> None:
        self._tex_dir = Path(TILE_TEX_DIR)
        # Stable key → layer mapping (built once, never changes)
        self._key_to_layer: dict[str, int] = {}
        self._layers: list[str] = []  # layer index → key
        self._pixel_data: np.ndarray | None = None
        self._gl_tex: int = 0

        self._build_layers()

    def _build_layers(self) -> None:
        """Assign a layer index to every tile key and load pixels.

        Layer 0 is always the magenta checkerboard (missing texture).
        Real tiles start at layer 1.
        """
        keys = sorted(TILE_REGISTRY.keys())

        # Also scan the texture directory for PNGs not in the registry
        # (e.g. vending_front, vending_side — used by face_textures)
        on_disk = set()
        if self._tex_dir.exists():
            on_disk = {p.stem for p in self._tex_dir.glob("*.png")}
        extra = sorted(on_disk - set(keys))
        keys.extend(extra)

        # Layer 0 = missing texture checkerboard, real tiles start at 1
        self._layers = [_MISSING_KEY] + keys
        self._key_to_layer = {_MISSING_KEY: 0}
        for i, k in enumerate(keys):
            self._key_to_layer[k] = i + 1

        n = len(self._layers)
        buf = np.zeros((n, TEX_SIZE, TEX_SIZE, 4), dtype=np.uint8)
        buf[0] = _make_checkerboard()

        for i, key in enumerate(keys):
            buf[i + 1] = self._load_tile(key)

        self._pixel_data = buf
        _log.info("TileAtlas: %d layers (1 missing + %d registry + %d extra)",
                  n, len(TILE_REGISTRY), len(extra))

    def _load_tile(self, key: str) -> np.ndarray:
        """Load a single tile PNG as RGBA uint8 array [H, W, 4]."""
        # Try texture_key from registry first
        td = tile_def(key)
        tex_key = (td.texture_key or td.id) if td else key

        png_path = self._tex_dir / f"{tex_key}.png"
        if png_path.exists():
            try:
                img = Image.open(png_path).convert("RGBA")
                if img.size != (TEX_SIZE, TEX_SIZE):
                    img = img.resize((TEX_SIZE, TEX_SIZE), Image.LANCZOS)
                return np.array(img, dtype=np.uint8)
            except Exception as exc:
                _log.warning("Failed to load %s: %s", png_path, exc)

        # Solid-colour fallback
        color = TILE_COLORS.get(key, (80, 80, 80))
        tile = np.zeros((TEX_SIZE, TEX_SIZE, 4), dtype=np.uint8)
        tile[:, :, 0] = color[0]
        tile[:, :, 1] = color[1]
        tile[:, :, 2] = color[2]
        tile[:, :, 3] = 255
        return tile

    @property
    def num_layers(self) -> int:
        return len(self._layers)

    @property
    def keys(self) -> list[str]:
        """All texture keys in layer order (excludes the missing-texture sentinel)."""
        return self._layers[1:]

    @property
    def tile_keys(self) -> list[str]:
        """Only tile-registry texture keys (no entity/extra textures)."""
        return [k for k in self._layers[1:] if k in TILE_REGISTRY]

    def layer(self, key: str) -> int:
        """Return the layer index for a texture key.

        Returns 0 (magenta checkerboard) for unknown keys.
        """
        return self._key_to_layer.get(key, 0)

    def upload(self) -> None:
        """Upload the pixel data to a GL_TEXTURE_2D_ARRAY.

        Must be called after the GL context is current.
        """
        if self._pixel_data is None:
            return

        self._gl_tex = int(gl.glGenTextures(1))
        gl.glBindTexture(gl.GL_TEXTURE_2D_ARRAY, self._gl_tex)

        n = self.num_layers
        gl.glTexImage3D(
            gl.GL_TEXTURE_2D_ARRAY, 0, gl.GL_RGBA8,
            TEX_SIZE, TEX_SIZE, n, 0,
            gl.GL_RGBA, gl.GL_UNSIGNED_BYTE,
            self._pixel_data,
        )

        gl.glTexParameteri(gl.GL_TEXTURE_2D_ARRAY,
                           gl.GL_TEXTURE_MIN_FILTER, gl.GL_NEAREST)
        gl.glTexParameteri(gl.GL_TEXTURE_2D_ARRAY,
                           gl.GL_TEXTURE_MAG_FILTER, gl.GL_NEAREST)
        gl.glTexParameteri(gl.GL_TEXTURE_2D_ARRAY,
                           gl.GL_TEXTURE_WRAP_S, gl.GL_REPEAT)
        gl.glTexParameteri(gl.GL_TEXTURE_2D_ARRAY,
                           gl.GL_TEXTURE_WRAP_T, gl.GL_REPEAT)

        gl.glBindTexture(gl.GL_TEXTURE_2D_ARRAY, 0)

        # Free CPU-side copy
        self._pixel_data = None
        print(f"  Atlas: {n} layers uploaded to GL ({TEX_SIZE}×{TEX_SIZE})")

    def bind(self, unit: int = 0) -> None:
        """Bind the texture array to a texture unit."""
        gl.glActiveTexture(gl.GL_TEXTURE0 + unit)
        gl.glBindTexture(gl.GL_TEXTURE_2D_ARRAY, self._gl_tex)
