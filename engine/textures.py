"""engine/textures.py — Tile texture atlas, PNG-only loading.

Loads a 64×64 pixel texture Surface for each tile ID from individual
PNG files in ``assets/textures/tiles/{texture_key}.png``.

No procedural generation — all textures are pre-baked PNGs.
If a PNG is missing, a flat solid-colour fallback is used.

The atlas only lives in memory — no ``atlas.png`` is saved to disk.

    from engine.textures import TextureAtlas
    atlas = TextureAtlas()
    wall_surf = atlas.get("wall")  # 64×64 Surface
"""

from __future__ import annotations

import logging
from pathlib import Path

import pygame

from core.tiles import TILE_COLORS, TILE_REGISTRY, tile_def, TILE_TEX_DIR
from core.paths import BILLBOARD_TEX_DIR as _BILLBOARD_DIR
from core.paths import PRISM_TEX_DIR as _PRISM_DIR

_log = logging.getLogger(__name__)

# Texture resolution — power of two for fast bitwise modulo
TEX_SIZE = 128
_TEX_MASK = TEX_SIZE - 1  # for & instead of %

# Atlas layout constants (kept for in-memory grid packing)
_ATLAS_COLS = 8
_TEX_DIR = Path(TILE_TEX_DIR)


class TextureAtlas:
    """Lazy-built in-memory atlas of textures, one per tile ID.

    Textures are loaded from individual PNGs in
    ``assets/textures/tiles/``.  If a PNG is missing, a flat
    solid-colour surface is used as fallback.
    """

    def __init__(self, *, force_regen: bool = False) -> None:
        self._surfaces: dict[str, pygame.Surface] = {}
        self._pixels: dict[str, pygame.PixelArray] = {}

    # ── public API ───────────────────────────────────────────────

    def get(self, tile_id: str) -> pygame.Surface:
        """Return the TEX_SIZE×TEX_SIZE Surface for a tile.  Loads on first access."""
        if tile_id not in self._surfaces:
            surf = _load_texture(tile_id)
            try:
                surf = surf.convert()
            except pygame.error:
                pass  # display not initialised yet
            self._surfaces[tile_id] = surf
        return self._surfaces[tile_id]

    def get_by_key(self, key: str) -> pygame.Surface:
        """Return the Surface for an arbitrary texture *key*.

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

    def ensure_all(self) -> None:
        """Make sure every tile in the registry has a loaded texture."""
        for tid in TILE_REGISTRY:
            self.get(tid)


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


import re as _re

try:
    import tomllib as _tomllib
except ModuleNotFoundError:
    import tomli as _tomllib  # type: ignore[no-redef]

# ── Sprite-sheet cell cache ──────────────────────────────────────
# Keyed by sheet path; value is (Surface, cell_w, cell_h, n_cols, n_rows).
_SHEET_CACHE: dict[str, tuple[pygame.Surface, int, int, int, int]] = {}

# ── Prism net cache ──────────────────────────────────────────────
# Keyed by net path; value is (Surface, faces_dict_from_toml).
_NET_CACHE: dict[str, tuple[pygame.Surface, dict]] = {}

# Facing labels matching the C renderer order (same as core.entity_defs).
_FACING_LABELS_8 = ("s", "sw", "w", "nw", "n", "ne", "e", "se")


def _load_sheet_info(type_id: str) -> tuple[pygame.Surface, int, int, int, int] | None:
    """Load a billboard sprite sheet + parse its TOML sidecar.

    Returns ``(sheet_surf, cell_w, cell_h, n_cols, n_rows)`` or ``None``.
    """
    sheet_path = _BILLBOARD_DIR / f"{type_id}_sheet.png"
    toml_path = _BILLBOARD_DIR / f"{type_id}_sheet.toml"

    cache_key = str(sheet_path)
    if cache_key in _SHEET_CACHE:
        return _SHEET_CACHE[cache_key]

    if not sheet_path.exists() or not toml_path.exists():
        return None

    try:
        sheet = pygame.image.load(str(sheet_path))
        with open(toml_path, "rb") as f:
            meta = _tomllib.load(f)
        grid = meta.get("grid", meta)  # support [grid] section or flat keys
        cell_w = int(grid.get("frame_width", 32))
        cell_h = int(grid.get("frame_height", 128))
        sw, sh = sheet.get_size()
        n_cols = max(sw // cell_w, 1)
        n_rows = max(sh // cell_h, 1)
        entry = (sheet, cell_w, cell_h, n_cols, n_rows)
        _SHEET_CACHE[cache_key] = entry
        return entry
    except Exception as exc:
        _log.warning("Failed to load sprite sheet for %s: %s", type_id, exc)
        return None


def _extract_sheet_cell(
    type_id: str, state: str, frame_idx: int,
    facing: str | None,
) -> pygame.Surface | None:
    """Extract a single cell from a billboard sprite sheet.

    *state* is the animation state name (e.g. "idle").
    *frame_idx* is the animation frame (0-based within the state).
    *facing* is the compass label (e.g. "sw") or ``None`` for non-directional.

    The sheet is laid out as a grid:
      - columns = facing directions
      - rows    = animation frames, grouped by ``[states.X]`` sections

    Each ``[states.X]`` section gives ``row`` (first row) and ``frames``
    (number of consecutive rows for that state).
    """
    info = _load_sheet_info(type_id)
    if info is None:
        return None
    sheet, cell_w, cell_h, n_cols, n_rows = info

    # Parse the TOML for column labels and state layout
    toml_path = _BILLBOARD_DIR / f"{type_id}_sheet.toml"
    try:
        with open(toml_path, "rb") as f:
            meta = _tomllib.load(f)
    except Exception:
        return None

    grid = meta.get("grid", meta)
    columns = grid.get("columns", [])
    if not columns:
        n_facings = int(grid.get("facings", meta.get("facings", 1)))
        columns = list(_FACING_LABELS_8[:n_facings]) if n_facings <= 8 else list(range(n_facings))

    # Resolve row from [states.X] section
    states_tbl = meta.get("states", {})
    state_info = states_tbl.get(state)
    if isinstance(state_info, dict):
        base_row = int(state_info.get("row", 0))
        n_frames = int(state_info.get("frames", 1))
    else:
        # No [states.X] sections — shouldn't happen, but fall back
        return None

    if frame_idx < 0 or frame_idx >= n_frames:
        return None
    row = base_row + frame_idx

    # Resolve column from facing
    if facing and len(columns) > 1:
        col_labels = [str(c).lower() for c in columns]
        facing_lower = facing.lower()
        if facing_lower not in col_labels:
            return None
        col = col_labels.index(facing_lower)
    else:
        col = 0

    if row >= n_rows or col >= n_cols:
        return None

    cell = pygame.Surface((cell_w, cell_h), pygame.SRCALPHA)
    cell.blit(sheet, (0, 0), (col * cell_w, row * cell_h, cell_w, cell_h))
    return cell


def invalidate_sheet_cache(type_id: str | None = None) -> None:
    """Clear cached sprite sheets and prism nets.

    Pass *type_id* to clear one entity, or ``None`` for all.
    """
    if type_id is None:
        _SHEET_CACHE.clear()
        _NET_CACHE.clear()
    else:
        sheet_key = str(_BILLBOARD_DIR / f"{type_id}_sheet.png")
        _SHEET_CACHE.pop(sheet_key, None)
        net_key = str(_PRISM_DIR / f"{type_id}_net.png")
        _NET_CACHE.pop(net_key, None)


# ── Prism net loading ────────────────────────────────────────────

def _load_net_info(type_id: str) -> tuple[pygame.Surface, dict] | None:
    """Load a prism net image + parse its TOML sidecar.

    Returns ``(net_surface, faces_dict)`` or ``None``.
    The *faces_dict* maps face suffix → ``{"x", "y", "w", "h"}``.
    """
    net_path = _PRISM_DIR / f"{type_id}_net.png"
    toml_path = _PRISM_DIR / f"{type_id}_net.toml"

    cache_key = str(net_path)
    if cache_key in _NET_CACHE:
        return _NET_CACHE[cache_key]

    if not net_path.exists() or not toml_path.exists():
        return None

    try:
        net = pygame.image.load(str(net_path))
        with open(toml_path, "rb") as f:
            meta = _tomllib.load(f)
        faces = meta.get("faces", {})
        entry = (net, faces)
        _NET_CACHE[cache_key] = entry
        return entry
    except Exception as exc:
        _log.warning("Failed to load prism net for %s: %s", type_id, exc)
        return None


def _extract_net_face(
    type_id: str, face_suffix: str,
) -> pygame.Surface | None:
    """Extract a single face from a prism net texture.

    *face_suffix* is the key suffix, e.g. ``"front"``, ``"side"``, ``"top"``.
    """
    info = _load_net_info(type_id)
    if info is None:
        return None
    net, faces = info

    face_data = faces.get(face_suffix)
    if face_data is None:
        return None

    x = int(face_data.get("x", 0))
    y = int(face_data.get("y", 0))
    w = int(face_data.get("w", 64))
    h = int(face_data.get("h", 64))

    cell = pygame.Surface((w, h), pygame.SRCALPHA)
    cell.blit(net, (0, 0), (x, y, w, h))
    return cell


def _parse_billboard_suffix(suffix: str) -> tuple[str, int, str | None] | None:
    """Parse a billboard key suffix into ``(state, frame_idx, facing)``.

    Key formats (always includes frame index)::

        Directional:     state_frame_facing   e.g. "idle_0_s", "walk_2_ne"
        Non-directional: state_frame          e.g. "lit_3", "off_0"

    Returns ``None`` if the suffix can't be parsed.
    """
    parts = suffix.rsplit("_", 2)
    # Try 3-part: state_frame_facing
    if len(parts) == 3:
        state, frame_str, facing = parts
        if facing.lower() in _FACING_LABELS_8:
            try:
                return (state, int(frame_str), facing)
            except ValueError:
                pass
    # Try 2-part: state_frame (non-directional)
    if len(parts) >= 2:
        remainder, last = suffix.rsplit("_", 1)
        try:
            frame_idx = int(last)
            return (remainder, frame_idx, None)
        except ValueError:
            pass
    return None


def _load_texture_by_key(key: str) -> pygame.Surface:
    """Load a texture PNG by raw key name (no tile registry lookup).

    Search order:
      1. Billboard sprite sheet cell — keys like ``dummy:idle_0_s``
         (directional) or ``torch:lit_3`` (non-directional) are
         extracted from ``entities/billboard/<type_id>_sheet.png``
         using the TOML ``[states.X]`` section for row offsets.
      2. Prism net face — keys like ``vending_machine:front`` are
         extracted from ``entities/prism/<type_id>_net.png``
         using the TOML sidecar for face rects.
      3. ``assets/textures/tiles/<key>.png``
         — flat key fallback (legacy / tiles)

    Returns the surface at its **native resolution** — entity face
    textures may be non-square to preserve correct aspect ratios.
    Falls back to a solid grey surface if the PNG is missing.
    """
    if key:
        # Structured entity key:  "type_id:suffix"
        if ":" in key:
            type_id, suffix = key.split(":", 1)

            # Try billboard sheet extraction
            parsed = _parse_billboard_suffix(suffix)
            if parsed is not None:
                state, frame_idx, facing = parsed
                cell = _extract_sheet_cell(
                    type_id, state, frame_idx, facing)
                if cell is not None:
                    return cell

            # Prism net face: "vending_machine:front" → extract from net
            cell = _extract_net_face(type_id, suffix)
            if cell is not None:
                return cell

        # Flat key (legacy: tiles dir)
        png_path = _TEX_DIR / f"{key}.png"
        if png_path.exists():
            try:
                return pygame.image.load(str(png_path))
            except pygame.error as exc:
                _log.warning("Failed to load %s: %s", png_path, exc)
    surf = pygame.Surface((TEX_SIZE, TEX_SIZE))
    surf.fill((80, 80, 80))
    return surf



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

    The image is loaded via Pygame, scaled to TEX_SIZE×TEX_SIZE, and saved as PNG
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

    # Load, scale to TEX_SIZE×TEX_SIZE, save as PNG
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
