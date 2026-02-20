"""systems/textures.py — Tile texture atlas, PNG-only loading.

Loads a 64×64 pixel texture Surface for each tile ID from individual
PNG files in ``assets/textures/tiles/{texture_key}.png``.

No procedural generation — all textures are pre-baked PNGs.
If a PNG is missing, a flat solid-colour fallback is used.

The atlas only lives in memory — no ``atlas.png`` is saved to disk.

    from systems.textures import TextureAtlas
    atlas = TextureAtlas()
    wall_surf = atlas.get("wall")  # 64×64 Surface
"""

from __future__ import annotations

import logging
from pathlib import Path

import pygame

from core.tiles import TILE_COLORS, TILE_REGISTRY, tile_def, TILE_TEX_DIR

_log = logging.getLogger(__name__)

# Texture resolution — power of two for fast bitwise modulo
TEX_SIZE = 64
_TEX_MASK = TEX_SIZE - 1  # for & instead of %

# Atlas layout constants (kept for in-memory grid packing)
_ATLAS_COLS = 8
_TEX_DIR = Path(TILE_TEX_DIR)

# Legacy path — kept so old code importing it doesn't crash,
# but atlas.png is no longer written to disk.
_ATLAS_PATH = Path(__file__).resolve().parent.parent / "assets" / "atlas.png"


class TextureAtlas:
    """Lazy-built in-memory atlas of 64×64 textures, one per tile ID.

    Textures are loaded from individual PNGs in
    ``assets/textures/tiles/``.  If a PNG is missing, a flat
    solid-colour surface is used as fallback.
    """

    def __init__(self, *, force_regen: bool = False) -> None:
        self._surfaces: dict[str, pygame.Surface] = {}
        self._pixels: dict[str, pygame.PixelArray] = {}

    # ── public API ───────────────────────────────────────────────

    def get(self, tile_id: str) -> pygame.Surface:
        """Return the 64×64 Surface for a tile.  Loads on first access."""
        if tile_id not in self._surfaces:
            surf = _load_texture(tile_id)
            try:
                surf = surf.convert()
            except pygame.error:
                pass  # display not initialised yet
            self._surfaces[tile_id] = surf
        return self._surfaces[tile_id]

    def get_by_key(self, key: str) -> pygame.Surface:
        """Return the 64×64 Surface for an arbitrary texture *key*.

        Looks up ``assets/textures/tiles/{key}.png`` directly, without
        going through the tile registry.  Falls back to solid grey.
        """
        cache_key = f"_key:{key}"
        if cache_key not in self._surfaces:
            surf = _load_texture_by_key(key)
            try:
                surf = surf.convert()
            except pygame.error:
                pass
            self._surfaces[cache_key] = surf
        return self._surfaces[cache_key]

    def invalidate(self, tile_id: str) -> None:
        """Drop the cached surface for *tile_id* so it is re-loaded."""
        self._surfaces.pop(tile_id, None)
        self._pixels.pop(tile_id, None)

    def sample(self, tile_id: str, u: float, v: float) -> tuple[int, int, int]:
        """Sample colour at normalised (u, v) coords ∈ [0, 1)."""
        surf = self.get(tile_id)
        tx = int(u * TEX_SIZE) & _TEX_MASK
        ty = int(v * TEX_SIZE) & _TEX_MASK
        return surf.get_at((tx, ty))[:3]  # type: ignore[return-value]

    def save_atlas(self) -> Path:
        """Legacy no-op.  Atlas is memory-only now."""
        return _ATLAS_PATH

    def ensure_all(self) -> None:
        """Make sure every tile in the registry has a loaded texture."""
        for tid in TILE_REGISTRY:
            self.get(tid)

    def _try_load_atlas(self) -> None:
        """Legacy no-op."""


def _save_atlas(surfaces: dict[str, pygame.Surface]) -> Path:
    """Legacy no-op.  Returns _ATLAS_PATH for compat."""
    return _ATLAS_PATH


# ═════════════════════════════════════════════════════════════════════
#  Texture loading  (PNG-only, no procedural generation)
# ═════════════════════════════════════════════════════════════════════

def _load_texture(tile_id: str) -> pygame.Surface:
    """Load a tile's texture from its PNG file.

    Falls back to a solid-colour surface if the PNG is missing.
    """
    td = tile_def(tile_id)
    key = (td.texture_key or td.id) if td else None
    if key:
        png_path = _TEX_DIR / f"{key}.png"
        if png_path.exists():
            try:
                surf = pygame.image.load(str(png_path))
                if surf.get_size() != (TEX_SIZE, TEX_SIZE):
                    surf = pygame.transform.scale(surf, (TEX_SIZE, TEX_SIZE))
                return surf
            except pygame.error as exc:
                _log.warning("Failed to load %s: %s", png_path, exc)

    # Solid-colour fallback
    color = TILE_COLORS.get(tile_id, (80, 80, 80))
    surf = pygame.Surface((TEX_SIZE, TEX_SIZE))
    surf.fill(color)
    return surf


def _load_texture_by_key(key: str) -> pygame.Surface:
    """Load a texture PNG by raw key name (no tile registry lookup).

    Falls back to a solid grey surface if the PNG is missing.
    """
    if key:
        png_path = _TEX_DIR / f"{key}.png"
        if png_path.exists():
            try:
                surf = pygame.image.load(str(png_path))
                if surf.get_size() != (TEX_SIZE, TEX_SIZE):
                    surf = pygame.transform.scale(surf, (TEX_SIZE, TEX_SIZE))
                return surf
            except pygame.error as exc:
                _log.warning("Failed to load %s: %s", png_path, exc)
    surf = pygame.Surface((TEX_SIZE, TEX_SIZE))
    surf.fill((80, 80, 80))
    return surf


# Alias kept so old call-sites still work
_load_or_generate = _load_texture
_generate = _load_texture


# export_texture and export_all_textures removed — the editor
# only imports textures, never exports them.


# ═════════════════════════════════════════════════════════════════════
#  Texture importing (copy external image → assets/textures/tiles/)
# ═════════════════════════════════════════════════════════════════════

_SUPPORTED_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tga"}


def import_texture(source_path: str | Path,
                   tile_id: str | None = None,
                   *,
                   key: str | None = None) -> Path:
    """Import an image file as a tile texture.

    *source_path* — path to the image on disk.
    *tile_id*     — if given, resolves the destination key from the
                    tile definition (texture_key or id).
    *key*         — explicit destination filename stem.  Takes
                    precedence over *tile_id* if both are supplied.

    The image is loaded via Pygame, scaled to 64×64, and saved as PNG
    into ``assets/textures/tiles/{key}.png``.

    Returns the destination Path on success.
    Raises ``ValueError`` for unsupported formats and ``FileNotFoundError``
    if *source_path* doesn't exist.
    """
    src = Path(source_path)
    if not src.exists():
        raise FileNotFoundError(f"Source image not found: {src}")
    if src.suffix.lower() not in _SUPPORTED_EXTS:
        raise ValueError(
            f"Unsupported image format '{src.suffix}'. "
            f"Supported: {', '.join(sorted(_SUPPORTED_EXTS))}")

    # Determine destination key
    import re
    if key:
        dest_key = key
    elif tile_id:
        td = tile_def(tile_id)
        dest_key = (td.texture_key or td.id) if td else tile_id
    else:
        dest_key = src.stem  # use filename without extension

    # Sanitize dest_key — strip path traversal and shell-unsafe chars
    dest_key = dest_key.replace("..", "").replace("/", "").replace("\\", "")
    dest_key = re.sub(r"[^\w\s-]", "", dest_key).strip()
    if not dest_key:
        raise ValueError("Cannot determine a safe destination filename")

    _TEX_DIR.mkdir(parents=True, exist_ok=True)
    dest = (_TEX_DIR / f"{dest_key}.png").resolve()
    # Ensure destination stays inside the texture directory
    if not str(dest).startswith(str(_TEX_DIR.resolve())):
        raise ValueError(f"Destination escapes texture directory: {dest_key}")

    # Load, scale to 64×64, save as PNG
    try:
        surf = pygame.image.load(str(src))
    except pygame.error as exc:
        raise ValueError(f"Failed to load image: {exc}") from exc

    if surf.get_size() != (TEX_SIZE, TEX_SIZE):
        surf = pygame.transform.smoothscale(surf, (TEX_SIZE, TEX_SIZE))

    pygame.image.save(surf, str(dest))
    _log.info("Imported texture %s → %s", src.name, dest)
    return dest


def browse_and_import(tile_id: str | None = None,
                      *,
                      key: str | None = None) -> Path | None:
    """Open a file dialog to pick an image, then import it.

    Uses tkinter file dialog (works alongside Pygame).
    Returns the destination Path, or None if the user cancelled.
    """
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        _log.warning("tkinter not available — cannot open file dialog")
        return None

    # Hide the tk root window
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)

    path = filedialog.askopenfilename(
        title="Import Tile Texture",
        filetypes=[
            ("Image files", "*.png *.jpg *.jpeg *.bmp *.gif *.tga"),
            ("PNG", "*.png"),
            ("All files", "*.*"),
        ],
    )
    root.destroy()

    if not path:
        return None
    return import_texture(path, tile_id=tile_id, key=key)
