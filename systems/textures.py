"""systems/textures.py — Procedural tile texture atlas with disk persistence.

Generates a 64×64 pixel texture Surface for each tile ID.  These are
used by the first-person renderer for wall columns and floor spans.

On first run the textures are procedurally generated; afterwards they
are packed into a single PNG atlas image and saved to
``assets/atlas.png``.  On subsequent runs the atlas is loaded from
disk instead of regenerating (~50× faster startup).

To force a regeneration (e.g. after editing a generator), delete
``assets/atlas.png`` or call ``TextureAtlas(force_regen=True)``.

    from systems.textures import TextureAtlas
    atlas = TextureAtlas()          # loads from disk or generates
    wall_surf = atlas.get(TILE_WALL)  # 64×64 Surface
    pixel = atlas.sample(TILE_WALL, tx, ty)  # (r,g,b) at 0..1 coords
"""

from __future__ import annotations

import logging
import random
from pathlib import Path

import pygame

from core.tiles import TILE_COLORS, TILE_REGISTRY, tile_def

_log = logging.getLogger(__name__)

# Texture resolution — power of two for fast bitwise modulo
TEX_SIZE = 64
_TEX_MASK = TEX_SIZE - 1  # for & instead of %

# Atlas layout: pack tile textures in a grid.
# Columns in the atlas image.
_ATLAS_COLS = 8
_ATLAS_PATH = Path(__file__).resolve().parent.parent / "assets" / "atlas.png"


class TextureAtlas:
    """Lazy-built atlas of 64×64 procedural textures, one per tile ID.

    When ``force_regen`` is False (the default) the atlas is loaded
    from ``assets/atlas.png`` if the file exists and contains entries
    for every tile in TILE_REGISTRY.  Otherwise we generate fresh
    textures and save a new atlas.
    """

    def __init__(self, *, force_regen: bool = False) -> None:
        self._surfaces: dict[int, pygame.Surface] = {}
        self._pixels: dict[int, pygame.PixelArray] = {}
        if not force_regen:
            self._try_load_atlas()

    # ── public API ───────────────────────────────────────────────

    def get(self, tile_id: int) -> pygame.Surface:
        """Return the 64×64 Surface for a tile.  Builds on first access."""
        if tile_id not in self._surfaces:
            surf = _generate(tile_id)
            try:
                surf = surf.convert()
            except pygame.error:
                pass  # display not initialised yet
            self._surfaces[tile_id] = surf
        return self._surfaces[tile_id]

    def sample(self, tile_id: int, u: float, v: float) -> tuple[int, int, int]:
        """Sample colour at normalised (u, v) coords ∈ [0, 1)."""
        surf = self.get(tile_id)
        tx = int(u * TEX_SIZE) & _TEX_MASK
        ty = int(v * TEX_SIZE) & _TEX_MASK
        return surf.get_at((tx, ty))[:3]  # type: ignore[return-value]

    def save_atlas(self) -> Path:
        """Pack all generated textures into a single PNG and save to disk.

        Returns the path to the saved atlas file.
        """
        # Ensure all tiles exist
        for tid in TILE_REGISTRY:
            self.get(tid)
        return _save_atlas(self._surfaces)

    def ensure_all(self) -> None:
        """Make sure every tile in the registry has a generated texture.

        Called at startup to eagerly build the full atlas.
        """
        for tid in TILE_REGISTRY:
            self.get(tid)

    # ── atlas persistence ────────────────────────────────────────

    def _try_load_atlas(self) -> None:
        """Load textures from the atlas PNG if it exists on disk."""
        if not _ATLAS_PATH.exists():
            return
        try:
            atlas_surf = pygame.image.load(str(_ATLAS_PATH))
        except (pygame.error, FileNotFoundError) as exc:
            _log.warning("Failed to load atlas: %s", exc)
            return

        ids = sorted(TILE_REGISTRY.keys())
        cols = _ATLAS_COLS
        expected_rows = (len(ids) + cols - 1) // cols
        expected_w = cols * TEX_SIZE
        expected_h = expected_rows * TEX_SIZE

        if atlas_surf.get_width() < expected_w or atlas_surf.get_height() < expected_h:
            _log.info("Atlas size mismatch — will regenerate")
            return

        for idx, tid in enumerate(ids):
            ax = (idx % cols) * TEX_SIZE
            ay = (idx // cols) * TEX_SIZE
            tile_surf = pygame.Surface((TEX_SIZE, TEX_SIZE))
            tile_surf.blit(atlas_surf, (0, 0), (ax, ay, TEX_SIZE, TEX_SIZE))
            try:
                tile_surf = tile_surf.convert()
            except pygame.error:
                pass
            self._surfaces[tid] = tile_surf

        _log.info("Loaded texture atlas from %s (%d tiles)", _ATLAS_PATH, len(ids))


def _save_atlas(surfaces: dict[int, pygame.Surface]) -> Path:
    """Pack tile surfaces into a grid PNG and write to disk."""
    ids = sorted(surfaces.keys())
    cols = _ATLAS_COLS
    rows = (len(ids) + cols - 1) // cols
    atlas_w = cols * TEX_SIZE
    atlas_h = rows * TEX_SIZE

    atlas_surf = pygame.Surface((atlas_w, atlas_h))
    for idx, tid in enumerate(ids):
        ax = (idx % cols) * TEX_SIZE
        ay = (idx // cols) * TEX_SIZE
        atlas_surf.blit(surfaces[tid], (ax, ay))

    _ATLAS_PATH.parent.mkdir(parents=True, exist_ok=True)
    pygame.image.save(atlas_surf, str(_ATLAS_PATH))
    _log.info("Saved texture atlas to %s (%d tiles, %dx%d)",
              _ATLAS_PATH, len(ids), atlas_w, atlas_h)
    return _ATLAS_PATH


# ═════════════════════════════════════════════════════════════════════
#  Procedural generators
# ═════════════════════════════════════════════════════════════════════

def _generate(tile_id: int) -> pygame.Surface:
    """Dispatch to the right generator for this tile type."""
    base = TILE_COLORS.get(tile_id, (80, 80, 80))
    td = tile_def(tile_id)
    if td and td.texture_key:
        gen = _KEY_GENERATORS.get(td.texture_key, _gen_noise)
    else:
        gen = _gen_noise
    return gen(base)


def _clamp(v: int) -> int:
    return max(0, min(255, v))


def _vary(base: tuple[int, int, int], amount: int,
          rng: random.Random) -> tuple[int, int, int]:
    """Slightly randomise a colour."""
    return (
        _clamp(base[0] + rng.randint(-amount, amount)),
        _clamp(base[1] + rng.randint(-amount, amount)),
        _clamp(base[2] + rng.randint(-amount, amount)),
    )


# ── Wall (brick pattern) ────────────────────────────────────────────

def _gen_wall(base: tuple[int, int, int]) -> pygame.Surface:
    surf = pygame.Surface((TEX_SIZE, TEX_SIZE))
    rng = random.Random(42)  # deterministic
    mortar = (_clamp(base[0] - 30), _clamp(base[1] - 30), _clamp(base[2] - 30))

    brick_h = 8
    brick_w = 16
    for y in range(TEX_SIZE):
        row = y // brick_h
        offset = (brick_w // 2) if row % 2 else 0
        for x in range(TEX_SIZE):
            bx = (x + offset) % (brick_w * 2)
            # Mortar lines
            if y % brick_h == 0 or bx % brick_w == 0:
                surf.set_at((x, y), mortar)
            else:
                surf.set_at((x, y), _vary(base, 8, rng))
    return surf


# ── Stone (irregular blocks) ────────────────────────────────────────

def _gen_stone(base: tuple[int, int, int]) -> pygame.Surface:
    surf = pygame.Surface((TEX_SIZE, TEX_SIZE))
    rng = random.Random(77)
    for y in range(TEX_SIZE):
        for x in range(TEX_SIZE):
            # Hash-ish variation
            v = ((x * 7 + y * 13) ^ (x * y)) % 20 - 10
            c = (_clamp(base[0] + v), _clamp(base[1] + v), _clamp(base[2] + v))
            surf.set_at((x, y), c)
    return surf


# ── Grass (dithered green) ──────────────────────────────────────────

def _gen_grass(base: tuple[int, int, int]) -> pygame.Surface:
    surf = pygame.Surface((TEX_SIZE, TEX_SIZE))
    rng = random.Random(12)
    for y in range(TEX_SIZE):
        for x in range(TEX_SIZE):
            if rng.random() < 0.15:
                # Occasional bright blade
                c = (_clamp(base[0] + 20), _clamp(base[1] + 30), _clamp(base[2] - 5))
            else:
                c = _vary(base, 10, rng)
            surf.set_at((x, y), c)
    return surf


# ── Dirt (earthy noise) ─────────────────────────────────────────────

def _gen_dirt(base: tuple[int, int, int]) -> pygame.Surface:
    surf = pygame.Surface((TEX_SIZE, TEX_SIZE))
    rng = random.Random(33)
    for y in range(TEX_SIZE):
        for x in range(TEX_SIZE):
            c = _vary(base, 12, rng)
            surf.set_at((x, y), c)
    return surf


# ── Wood floor (planks) ─────────────────────────────────────────────

def _gen_wood(base: tuple[int, int, int]) -> pygame.Surface:
    surf = pygame.Surface((TEX_SIZE, TEX_SIZE))
    rng = random.Random(55)
    plank_w = 10
    gap = (_clamp(base[0] - 25), _clamp(base[1] - 25), _clamp(base[2] - 15))
    for y in range(TEX_SIZE):
        for x in range(TEX_SIZE):
            if x % plank_w == 0:
                surf.set_at((x, y), gap)
            else:
                # Wood grain — vary along y
                grain = ((y * 3 + x) % 7) - 3
                c = (_clamp(base[0] + grain), _clamp(base[1] + grain),
                     _clamp(base[2] + grain))
                surf.set_at((x, y), c)
    return surf


# ── Water (wavy blue) ───────────────────────────────────────────────

def _gen_water(base: tuple[int, int, int]) -> pygame.Surface:
    import math as _math
    surf = pygame.Surface((TEX_SIZE, TEX_SIZE))
    for y in range(TEX_SIZE):
        for x in range(TEX_SIZE):
            wave = int(10 * _math.sin(x * 0.3 + y * 0.2))
            c = (_clamp(base[0] + wave), _clamp(base[1] + wave),
                 _clamp(base[2] + wave + 15))
            surf.set_at((x, y), c)
    return surf


# ── Sand ────────────────────────────────────────────────────────────

def _gen_sand(base: tuple[int, int, int]) -> pygame.Surface:
    surf = pygame.Surface((TEX_SIZE, TEX_SIZE))
    rng = random.Random(99)
    for y in range(TEX_SIZE):
        for x in range(TEX_SIZE):
            c = _vary(base, 8, rng)
            surf.set_at((x, y), c)
    return surf


# ── Teleporter (pulsing purple) ─────────────────────────────────────

def _gen_teleporter(base: tuple[int, int, int]) -> pygame.Surface:
    import math as _math
    surf = pygame.Surface((TEX_SIZE, TEX_SIZE))
    frame = (70, 55, 40)       # wooden door frame
    door = (45, 30, 20)        # dark wood paneling
    glow = (160, 40, 180)      # purple energy trim
    rng = random.Random(66)
    for y in range(TEX_SIZE):
        for x in range(TEX_SIZE):
            # Frame border (left, right, top)
            if x < 6 or x >= 58 or y < 6:
                surf.set_at((x, y), _vary(frame, 6, rng))
            # Glowing trim just inside the frame
            elif x < 9 or x >= 55 or y < 9:
                pulse = int(15 * _math.sin(y * 0.5 + x * 0.3))
                c = (_clamp(glow[0] + pulse), _clamp(glow[1]),
                     _clamp(glow[2] + pulse))
                surf.set_at((x, y), c)
            # Door threshold at bottom
            elif y >= 56:
                surf.set_at((x, y), _vary((60, 50, 45), 4, rng))
            else:
                # Dark interior with subtle energy swirl
                swirl = int(8 * _math.sin(x * 0.2 + y * 0.15))
                c = (_clamp(door[0] + swirl), _clamp(door[1] + swirl // 2),
                     _clamp(door[2] + abs(swirl)))
                surf.set_at((x, y), c)
    return surf


# ── Metal wall (corrugated / riveted sheet metal) ───────────────────

def _gen_metal(base: tuple[int, int, int]) -> pygame.Surface:
    surf = pygame.Surface((TEX_SIZE, TEX_SIZE))
    rng = random.Random(101)
    rivet_spacing = 16
    for y in range(TEX_SIZE):
        for x in range(TEX_SIZE):
            # Corrugation — vertical ridges
            ridge = abs((x % 8) - 4) * 3 - 4  # range ~ -4..8
            c = (_clamp(base[0] + ridge), _clamp(base[1] + ridge + 2),
                 _clamp(base[2] + ridge + 4))
            # Subtle horizontal streak
            streak = ((y * 3 + x) % 13) - 6
            c = (_clamp(c[0] + streak), _clamp(c[1] + streak), _clamp(c[2] + streak))
            # Rivet dots
            if (x % rivet_spacing == rivet_spacing // 2 and
                    y % rivet_spacing == rivet_spacing // 2):
                c = (_clamp(base[0] + 30), _clamp(base[1] + 30), _clamp(base[2] + 35))
            # Occasional rust speck
            if rng.random() < 0.02:
                c = (_clamp(base[0] + 20), _clamp(base[1] - 10), _clamp(base[2] - 15))
            surf.set_at((x, y), c)
    return surf


# ── Concrete (cracked / weathered) ──────────────────────────────────

def _gen_concrete(base: tuple[int, int, int]) -> pygame.Surface:
    surf = pygame.Surface((TEX_SIZE, TEX_SIZE))
    rng = random.Random(111)
    # Pre-compute a few crack lines
    cracks: set[tuple[int, int]] = set()
    for _ in range(3):
        cx, cy = rng.randint(10, 54), rng.randint(10, 54)
        for step in range(20):
            cracks.add((cx, cy))
            cx += rng.choice([-1, 0, 1])
            cy += rng.choice([-1, 0, 1])
            cx = max(0, min(63, cx))
            cy = max(0, min(63, cy))
    for y in range(TEX_SIZE):
        for x in range(TEX_SIZE):
            if (x, y) in cracks:
                # Dark crack
                c = (_clamp(base[0] - 40), _clamp(base[1] - 40), _clamp(base[2] - 35))
            else:
                # Smooth concrete with subtle aggregate
                v = ((x * 11 + y * 7) ^ (x + y * 3)) % 12 - 6
                c = (_clamp(base[0] + v), _clamp(base[1] + v), _clamp(base[2] + v))
            surf.set_at((x, y), c)
    return surf


# ── Tile floor (checkered ceramic) ──────────────────────────────────

def _gen_tile_floor(base: tuple[int, int, int]) -> pygame.Surface:
    surf = pygame.Surface((TEX_SIZE, TEX_SIZE))
    rng = random.Random(121)
    tile_size = 16  # each ceramic tile
    grout = (_clamp(base[0] - 30), _clamp(base[1] - 25), _clamp(base[2] - 20))
    light_tile = base
    dark_tile = (_clamp(base[0] - 25), _clamp(base[1] - 20), _clamp(base[2] - 15))
    for y in range(TEX_SIZE):
        for x in range(TEX_SIZE):
            # Grout lines
            if x % tile_size < 1 or y % tile_size < 1:
                surf.set_at((x, y), grout)
            else:
                # Checkerboard pattern
                tx = x // tile_size
                ty = y // tile_size
                if (tx + ty) % 2 == 0:
                    c = _vary(light_tile, 4, rng)
                else:
                    c = _vary(dark_tile, 4, rng)
                surf.set_at((x, y), c)
    return surf


# ── Rubble (broken debris) ──────────────────────────────────────────

def _gen_rubble(base: tuple[int, int, int]) -> pygame.Surface:
    surf = pygame.Surface((TEX_SIZE, TEX_SIZE))
    rng = random.Random(131)
    for y in range(TEX_SIZE):
        for x in range(TEX_SIZE):
            # Chunky noise – larger-scale variation
            chunk = ((x // 5 * 13 + y // 5 * 7) ^ 0xA5) % 30 - 15
            # Fine grain noise
            fine = rng.randint(-8, 8)
            c = (_clamp(base[0] + chunk + fine),
                 _clamp(base[1] + chunk + fine - 3),
                 _clamp(base[2] + chunk + fine - 5))
            surf.set_at((x, y), c)
    return surf


# ── Gateway (stone archway) ─────────────────────────────────────────

def _gen_gateway(base: tuple[int, int, int]) -> pygame.Surface:
    import math as _math
    surf = pygame.Surface((TEX_SIZE, TEX_SIZE))
    rng = random.Random(141)
    keystone = (_clamp(base[0] + 15), _clamp(base[1] + 10), _clamp(base[2] + 5))
    dark = (_clamp(base[0] - 30), _clamp(base[1] - 30), _clamp(base[2] - 25))
    for y in range(TEX_SIZE):
        for x in range(TEX_SIZE):
            # Arch shape: pillars on sides, curved top
            if x < 8 or x >= 56:
                # Stone pillar — block pattern
                v = ((x * 7 + y * 13) ^ (x * y)) % 14 - 7
                c = (_clamp(base[0] + v), _clamp(base[1] + v), _clamp(base[2] + v))
                # Mortar lines
                if y % 8 == 0:
                    c = dark
            elif y < 20:
                # Arch curve
                cx = 32
                dist = abs(x - cx)
                arch_y = int(8 + (dist * dist) / 50.0)
                if y < arch_y:
                    v = ((x * 7 + y * 13) ^ (x * y)) % 14 - 7
                    c = (_clamp(base[0] + v), _clamp(base[1] + v), _clamp(base[2] + v))
                    # Keystone at top center
                    if dist < 6 and y < 10:
                        c = _vary(keystone, 4, rng)
                else:
                    c = dark
            else:
                # Open doorway
                c = dark
            surf.set_at((x, y), c)
    return surf


# ── Bookshelf ───────────────────────────────────────────────────────

def _gen_bookshelf(base: tuple[int, int, int]) -> pygame.Surface:
    surf = pygame.Surface((TEX_SIZE, TEX_SIZE))
    rng = random.Random(151)
    shelf_color = base  # wood color
    book_colors = [
        (140, 40, 40), (40, 60, 140), (40, 120, 50), (130, 100, 40),
        (100, 40, 100), (50, 50, 50), (160, 130, 60), (80, 30, 30),
    ]
    shelf_h = 16  # height of each shelf section
    for y in range(TEX_SIZE):
        for x in range(TEX_SIZE):
            section = y // shelf_h
            local_y = y % shelf_h
            if local_y < 2:
                # Shelf plank
                c = _vary(shelf_color, 5, rng)
            else:
                # Books — vertical rectangles of varying width and color
                book_idx = (x // 4 + section * 7) % len(book_colors)
                bc = book_colors[book_idx]
                # Spine detail — slight indent at edges
                bx = x % 4
                if bx == 0:
                    c = (_clamp(bc[0] - 20), _clamp(bc[1] - 20), _clamp(bc[2] - 20))
                else:
                    c = _vary(bc, 6, rng)
            surf.set_at((x, y), c)
    return surf


# ── Crate (wooden slats with cross bracing) ─────────────────────────

def _gen_crate(base: tuple[int, int, int]) -> pygame.Surface:
    surf = pygame.Surface((TEX_SIZE, TEX_SIZE))
    rng = random.Random(161)
    slat = base
    gap = (_clamp(base[0] - 25), _clamp(base[1] - 20), _clamp(base[2] - 15))
    nail = (180, 180, 190)
    for y in range(TEX_SIZE):
        for x in range(TEX_SIZE):
            # Horizontal slats
            if y % 10 < 1:
                c = gap
            # Cross brace (X shape)
            elif abs(x - y) < 2 or abs(x - (63 - y)) < 2:
                c = (_clamp(slat[0] + 10), _clamp(slat[1] + 8), _clamp(slat[2] + 3))
            else:
                # Wood grain
                grain = ((y * 3 + x) % 7) - 3
                c = (_clamp(slat[0] + grain), _clamp(slat[1] + grain),
                     _clamp(slat[2] + grain))
            # Nail heads at intersections
            if (y % 10 == 5 and x % 16 == 8):
                c = nail
            surf.set_at((x, y), c)
    return surf


# ── Barrel (circular staves) ────────────────────────────────────────

def _gen_barrel(base: tuple[int, int, int]) -> pygame.Surface:
    import math as _math
    surf = pygame.Surface((TEX_SIZE, TEX_SIZE))
    rng = random.Random(171)
    band = (60, 60, 65)
    for y in range(TEX_SIZE):
        for x in range(TEX_SIZE):
            # Metal bands at top, bottom, and middle
            if y < 4 or y >= 60 or abs(y - 32) < 2:
                c = _vary(band, 4, rng)
            else:
                # Curved stave shading — darker at edges
                cx = 32
                dist = abs(x - cx)
                shade = int(dist * 0.8)
                grain = ((y * 3 + x) % 5) - 2
                c = (_clamp(base[0] - shade + grain),
                     _clamp(base[1] - shade + grain),
                     _clamp(base[2] - shade + grain - 2))
                # Stave gap lines
                stave_w = 8
                if x % stave_w == 0:
                    c = (_clamp(c[0] - 15), _clamp(c[1] - 15), _clamp(c[2] - 10))
            surf.set_at((x, y), c)
    return surf


# ── Fallback (simple noise) ─────────────────────────────────────────

def _gen_noise(base: tuple[int, int, int]) -> pygame.Surface:
    surf = pygame.Surface((TEX_SIZE, TEX_SIZE))
    rng = random.Random(0)
    for y in range(TEX_SIZE):
        for x in range(TEX_SIZE):
            surf.set_at((x, y), _vary(base, 6, rng))
    return surf


# ── Window (frosted pane with frame) ────────────────────────────────

def _gen_window(base: tuple[int, int, int]) -> pygame.Surface:
    import math as _math
    surf = pygame.Surface((TEX_SIZE, TEX_SIZE))
    frame = (60, 50, 40)
    rng = random.Random(88)
    for y in range(TEX_SIZE):
        for x in range(TEX_SIZE):
            # 4-pixel wooden frame around edges + cross bar in centre
            if x < 4 or x >= 60 or y < 4 or y >= 60:
                surf.set_at((x, y), frame)
            elif abs(x - 32) < 2 or abs(y - 32) < 2:
                surf.set_at((x, y), frame)
            else:
                # Frosted glass: base colour + slight noise + vertical gradient
                grad = int(20 * _math.sin(y * 0.15))
                c = (
                    _clamp(base[0] + rng.randint(-6, 6) + grad),
                    _clamp(base[1] + rng.randint(-6, 6) + grad),
                    _clamp(base[2] + rng.randint(-4, 4) + grad + 10),
                )
                surf.set_at((x, y), c)
    return surf


# ── Pillar (stone column) ───────────────────────────────────────────

def _gen_pillar(base: tuple[int, int, int]) -> pygame.Surface:
    import math as _math
    surf = pygame.Surface((TEX_SIZE, TEX_SIZE))
    rng = random.Random(181)
    cap = (_clamp(base[0] + 20), _clamp(base[1] + 15), _clamp(base[2] + 10))
    for y in range(TEX_SIZE):
        for x in range(TEX_SIZE):
            # Cap and base bands
            if y < 5 or y >= 59:
                c = _vary(cap, 4, rng)
            else:
                # Cylindrical shading — darker at edges
                cx = 32
                dist = abs(x - cx)
                shade = int(dist * 0.9)
                v = ((y * 5 + x * 3) ^ 0x55) % 10 - 5
                c = (_clamp(base[0] - shade + v),
                     _clamp(base[1] - shade + v),
                     _clamp(base[2] - shade + v))
                # Fluting lines
                if x % 8 == 0 and 8 < x < 56:
                    c = (_clamp(c[0] - 12), _clamp(c[1] - 12), _clamp(c[2] - 10))
            surf.set_at((x, y), c)
    return surf


# ── Counter top (wood with inlaid trim) ─────────────────────────────

def _gen_counter_top(base: tuple[int, int, int]) -> pygame.Surface:
    surf = pygame.Surface((TEX_SIZE, TEX_SIZE))
    rng = random.Random(191)
    trim = (_clamp(base[0] - 30), _clamp(base[1] - 25), _clamp(base[2] - 15))
    top = (_clamp(base[0] + 10), _clamp(base[1] + 5), _clamp(base[2]))
    for y in range(TEX_SIZE):
        for x in range(TEX_SIZE):
            # Top edge — polished surface
            if y < 6:
                c = _vary(top, 3, rng)
            # Front trim strip
            elif y > 56:
                c = _vary(trim, 4, rng)
            else:
                # Vertical paneling
                panel_w = 16
                if x % panel_w < 1:
                    c = trim
                else:
                    grain = ((y * 3 + x) % 7) - 3
                    c = (_clamp(base[0] + grain), _clamp(base[1] + grain),
                         _clamp(base[2] + grain))
            surf.set_at((x, y), c)
    return surf


# ── Railing (horizontal bars with posts) ────────────────────────────

def _gen_railing(base: tuple[int, int, int]) -> pygame.Surface:
    surf = pygame.Surface((TEX_SIZE, TEX_SIZE))
    rng = random.Random(201)
    post = (_clamp(base[0] + 15), _clamp(base[1] + 10), _clamp(base[2] + 5))
    bg = (30, 30, 28)  # dark "see-through" background
    rail = base
    for y in range(TEX_SIZE):
        for x in range(TEX_SIZE):
            # Vertical posts every 16px
            if x % 32 < 4:
                c = _vary(post, 3, rng)
            # Top rail
            elif y < 6:
                c = _vary(rail, 4, rng)
            # Middle rail
            elif 28 < y < 34:
                c = _vary(rail, 4, rng)
            # Bottom rail
            elif y > 58:
                c = _vary(rail, 4, rng)
            else:
                c = bg  # transparent-ish gap
            surf.set_at((x, y), c)
    return surf


# ── Table (tabletop with visible legs) ──────────────────────────────

def _gen_table(base: tuple[int, int, int]) -> pygame.Surface:
    surf = pygame.Surface((TEX_SIZE, TEX_SIZE))
    rng = random.Random(310)
    top = (_clamp(base[0] + 15), _clamp(base[1] + 10), _clamp(base[2] + 5))
    leg = (_clamp(base[0] - 15), _clamp(base[1] - 10), _clamp(base[2] - 10))
    apron = (_clamp(base[0] + 5), _clamp(base[1] + 2), _clamp(base[2] - 2))
    bg = (35, 35, 32)  # dark gap between legs (floor shows through)
    for y in range(TEX_SIZE):
        for x in range(TEX_SIZE):
            # Tabletop surface (top 12 pixels = ~19% of texture)
            if y < 8:
                # Wood grain on top
                grain = ((x * 5 + y * 2) % 9) - 4
                c = (_clamp(top[0] + grain), _clamp(top[1] + grain),
                     _clamp(top[2] + grain))
            # Apron / front trim (below tabletop)
            elif y < 14:
                n = rng.randint(-3, 3)
                c = (_clamp(apron[0] + n), _clamp(apron[1] + n),
                     _clamp(apron[2] + n))
            # Legs: left (x 4-10) and right (x 52-58)
            elif (4 <= x <= 10) or (52 <= x <= 58):
                grain = ((y * 3 + x) % 5) - 2
                c = (_clamp(leg[0] + grain), _clamp(leg[1] + grain),
                     _clamp(leg[2] + grain))
                # Highlight on inner edge of leg
                if x in (10, 52):
                    c = (_clamp(c[0] + 12), _clamp(c[1] + 10),
                         _clamp(c[2] + 8))
            else:
                # Gap between legs — dark background
                c = _vary(bg, 2, rng)
            surf.set_at((x, y), c)
    return surf


# ── Curb (low concrete edging) ──────────────────────────────────────

def _gen_curb(base: tuple[int, int, int]) -> pygame.Surface:
    surf = pygame.Surface((TEX_SIZE, TEX_SIZE))
    rng = random.Random(320)
    top = (_clamp(base[0] + 12), _clamp(base[1] + 12), _clamp(base[2] + 10))
    face = base
    for y in range(TEX_SIZE):
        for x in range(TEX_SIZE):
            if y < 10:
                # Worn top edge
                c = _vary(top, 4, rng)
            else:
                # Rough concrete face
                n = rng.randint(-6, 6)
                c = (_clamp(face[0] + n), _clamp(face[1] + n),
                     _clamp(face[2] + n))
            surf.set_at((x, y), c)
    return surf


# ── Stool (round seat on a post) ────────────────────────────────────

def _gen_stool(base: tuple[int, int, int]) -> pygame.Surface:
    surf = pygame.Surface((TEX_SIZE, TEX_SIZE))
    rng = random.Random(330)
    seat = (_clamp(base[0] + 15), _clamp(base[1] + 10), _clamp(base[2] + 5))
    post = (_clamp(base[0] - 20), _clamp(base[1] - 15), _clamp(base[2] - 15))
    bg = (35, 35, 32)
    for y in range(TEX_SIZE):
        for x in range(TEX_SIZE):
            # Seat top
            if y < 12:
                grain = ((x * 3 + y) % 7) - 3
                c = (_clamp(seat[0] + grain), _clamp(seat[1] + grain),
                     _clamp(seat[2] + grain))
            # Central post
            elif 26 <= x <= 38:
                n = rng.randint(-3, 3)
                c = (_clamp(post[0] + n), _clamp(post[1] + n),
                     _clamp(post[2] + n))
            else:
                c = _vary(bg, 2, rng)
            surf.set_at((x, y), c)
    return surf


# ── Step (single stair step) ────────────────────────────────────────

def _gen_step(base: tuple[int, int, int]) -> pygame.Surface:
    surf = pygame.Surface((TEX_SIZE, TEX_SIZE))
    rng = random.Random(340)
    tread = (_clamp(base[0] + 8), _clamp(base[1] + 8), _clamp(base[2] + 10))
    riser = (_clamp(base[0] - 10), _clamp(base[1] - 10), _clamp(base[2] - 8))
    for y in range(TEX_SIZE):
        for x in range(TEX_SIZE):
            if y < 16:
                # Tread (top surface)
                n = rng.randint(-4, 4)
                c = (_clamp(tread[0] + n), _clamp(tread[1] + n),
                     _clamp(tread[2] + n))
            elif y < 20:
                # Nosing edge
                c = (_clamp(tread[0] + 15), _clamp(tread[1] + 15),
                     _clamp(tread[2] + 12))
            else:
                # Riser face
                n = rng.randint(-5, 5)
                c = (_clamp(riser[0] + n), _clamp(riser[1] + n),
                     _clamp(riser[2] + n))
            surf.set_at((x, y), c)
    return surf


# ── Carpet (soft fibrous texture) ───────────────────────────────────

def _gen_carpet(base: tuple[int, int, int]) -> pygame.Surface:
    surf = pygame.Surface((TEX_SIZE, TEX_SIZE))
    rng = random.Random(210)
    for y in range(TEX_SIZE):
        for x in range(TEX_SIZE):
            # Fibre pattern — alternating dark/light with noise
            fibre = ((x * 3 + y * 7) ^ (x * y)) % 16 - 8
            # Subtle cross-hatch weave
            weave = 0
            if (x + y) % 4 == 0:
                weave = -6
            elif (x - y) % 6 == 0:
                weave = 4
            c = (_clamp(base[0] + fibre + weave + rng.randint(-4, 4)),
                 _clamp(base[1] + fibre + weave + rng.randint(-4, 4)),
                 _clamp(base[2] + fibre + weave + rng.randint(-3, 3)))
            surf.set_at((x, y), c)
    return surf


# ── Brick Wall (red/brown brick with mortar) ────────────────────────

def _gen_brick_wall(base: tuple[int, int, int]) -> pygame.Surface:
    surf = pygame.Surface((TEX_SIZE, TEX_SIZE))
    rng = random.Random(220)
    mortar = (_clamp(base[0] + 40), _clamp(base[1] + 40), _clamp(base[2] + 35))

    brick_h = 8
    brick_w = 16
    for y in range(TEX_SIZE):
        row = y // brick_h
        offset = (brick_w // 2) if row % 2 else 0
        for x in range(TEX_SIZE):
            bx = (x + offset) % (brick_w * 2)
            if y % brick_h == 0 or bx % brick_w == 0:
                surf.set_at((x, y), mortar)
            else:
                # Vary brick colour per-brick
                brick_seed = row * 100 + (x + offset) // brick_w
                rng2 = random.Random(brick_seed)
                variation = rng2.randint(-12, 12)
                c = (_clamp(base[0] + variation + rng.randint(-4, 4)),
                     _clamp(base[1] + variation // 2 + rng.randint(-3, 3)),
                     _clamp(base[2] + variation // 3 + rng.randint(-2, 2)))
                surf.set_at((x, y), c)
    return surf


# ── Wood Panel (vertical wood planks with grain) ────────────────────

def _gen_wood_panel(base: tuple[int, int, int]) -> pygame.Surface:
    import math as _math
    surf = pygame.Surface((TEX_SIZE, TEX_SIZE))
    rng = random.Random(230)
    groove = (_clamp(base[0] - 25), _clamp(base[1] - 20), _clamp(base[2] - 15))
    plank_w = 16

    for y in range(TEX_SIZE):
        for x in range(TEX_SIZE):
            plank = x // plank_w
            local_x = x % plank_w
            # Groove between planks
            if local_x == 0 or local_x == plank_w - 1:
                surf.set_at((x, y), groove)
                continue
            # Wood grain — horizontal with slight wave
            grain = int(6 * _math.sin((y + plank * 5) * 0.2 + plank))
            knot = 0
            # Occasional knot
            if (y - 20 * plank) % 48 < 4 and abs(local_x - 8) < 3:
                knot = -15
            c = (_clamp(base[0] + grain + knot + rng.randint(-3, 3)),
                 _clamp(base[1] + grain + knot + rng.randint(-3, 3)),
                 _clamp(base[2] + grain + knot + rng.randint(-2, 2)))
            surf.set_at((x, y), c)
    return surf


# ── Cracked Floor (damaged concrete with cracks) ────────────────────

def _gen_cracked_floor(base: tuple[int, int, int]) -> pygame.Surface:
    import math as _math
    surf = pygame.Surface((TEX_SIZE, TEX_SIZE))
    rng = random.Random(240)
    crack_color = (_clamp(base[0] - 40), _clamp(base[1] - 35), _clamp(base[2] - 30))

    # Generate a few crack lines
    cracks: set[tuple[int, int]] = set()
    for _ in range(3):
        cx, cy = rng.randint(10, 54), rng.randint(10, 54)
        for step in range(rng.randint(15, 35)):
            cracks.add((cx & 63, cy & 63))
            cx += rng.choice([-1, 0, 1])
            cy += rng.choice([-1, 0, 1, 1])

    for y in range(TEX_SIZE):
        for x in range(TEX_SIZE):
            if (x, y) in cracks:
                c = crack_color
            else:
                noise = rng.randint(-6, 6)
                c = (_clamp(base[0] + noise),
                     _clamp(base[1] + noise),
                     _clamp(base[2] + noise))
            surf.set_at((x, y), c)
    return surf


# ── Stone Floor (polished stone tiles) ──────────────────────────────

def _gen_stone_floor(base: tuple[int, int, int]) -> pygame.Surface:
    surf = pygame.Surface((TEX_SIZE, TEX_SIZE))
    rng = random.Random(250)
    grout = (_clamp(base[0] - 30), _clamp(base[1] - 28), _clamp(base[2] - 25))
    tile_size = 32  # 2x2 tiles within 64x64

    for y in range(TEX_SIZE):
        for x in range(TEX_SIZE):
            # Grout lines
            if x % tile_size < 1 or y % tile_size < 1:
                surf.set_at((x, y), grout)
            else:
                # Per-tile variation
                tx = x // tile_size
                ty = y // tile_size
                seed = tx * 10 + ty
                per_tile_shift = (seed * 7 + 3) % 15 - 7
                noise = rng.randint(-4, 4)
                c = (_clamp(base[0] + per_tile_shift + noise),
                     _clamp(base[1] + per_tile_shift + noise),
                     _clamp(base[2] + per_tile_shift + noise))
                surf.set_at((x, y), c)
    return surf


# ── Shelf Wall (wall with shelves bearing objects) ──────────────────

def _gen_shelf_wall(base: tuple[int, int, int]) -> pygame.Surface:
    surf = pygame.Surface((TEX_SIZE, TEX_SIZE))
    rng = random.Random(260)
    shelf_color = (_clamp(base[0] + 15), _clamp(base[1] + 10), _clamp(base[2] + 5))
    item_colors = [
        (_clamp(base[0] + 30), _clamp(base[1] - 10), _clamp(base[2] - 20)),
        (_clamp(base[0] - 20), _clamp(base[1] + 20), _clamp(base[2] - 10)),
        (_clamp(base[0] - 10), _clamp(base[1] - 10), _clamp(base[2] + 30)),
    ]

    shelf_rows = [0, 16, 32, 48, 62]  # horizontal shelf positions
    for y in range(TEX_SIZE):
        for x in range(TEX_SIZE):
            is_shelf = any(abs(y - sy) < 2 for sy in shelf_rows)
            if is_shelf:
                c = shelf_color
            else:
                # Items on shelves — small colored rectangles
                shelf_idx = sum(1 for sy in shelf_rows if y > sy) - 1
                item_x = x % 12
                if shelf_idx >= 0 and 3 < item_x < 10 and y % 16 > 3 and y % 16 < 14:
                    icol = item_colors[(x // 12 + shelf_idx) % len(item_colors)]
                    noise = rng.randint(-5, 5)
                    c = (_clamp(icol[0] + noise), _clamp(icol[1] + noise),
                         _clamp(icol[2] + noise))
                else:
                    # Back wall
                    noise = rng.randint(-4, 4)
                    c = (_clamp(base[0] + noise), _clamp(base[1] + noise),
                         _clamp(base[2] + noise))
            surf.set_at((x, y), c)
    return surf


# ── Stone Platform (flat stone surface with mortar lines) ───────────

def _gen_stone_platform(base: tuple[int, int, int]) -> pygame.Surface:
    surf = pygame.Surface((TEX_SIZE, TEX_SIZE))
    rng = random.Random(270)
    mortar = (_clamp(base[0] - 30), _clamp(base[1] - 28), _clamp(base[2] - 25))
    for y in range(TEX_SIZE):
        for x in range(TEX_SIZE):
            # Mortar grid every 16 px, offset every other row
            off = 8 if (y // 16) % 2 else 0
            if y % 16 == 0 or (x + off) % 16 == 0:
                c = mortar
            else:
                n = rng.randint(-6, 6)
                c = (_clamp(base[0] + n), _clamp(base[1] + n), _clamp(base[2] + n))
            surf.set_at((x, y), c)
    return surf


# ── Wood Platform (plank surface with grain) ────────────────────────

def _gen_wood_platform(base: tuple[int, int, int]) -> pygame.Surface:
    surf = pygame.Surface((TEX_SIZE, TEX_SIZE))
    rng = random.Random(280)
    gap = (_clamp(base[0] - 35), _clamp(base[1] - 30), _clamp(base[2] - 25))
    plank_w = 10
    for y in range(TEX_SIZE):
        for x in range(TEX_SIZE):
            if x % plank_w == 0:
                c = gap
            else:
                grain = rng.randint(-8, 8)
                # slight color shift per plank
                shift = ((x // plank_w) * 7) % 15 - 7
                c = (_clamp(base[0] + grain + shift),
                     _clamp(base[1] + grain + shift),
                     _clamp(base[2] + grain + shift))
            surf.set_at((x, y), c)
    return surf


# ── Metal Platform (riveted metal floor) ────────────────────────────

def _gen_metal_platform(base: tuple[int, int, int]) -> pygame.Surface:
    surf = pygame.Surface((TEX_SIZE, TEX_SIZE))
    rng = random.Random(290)
    rivet = (_clamp(base[0] + 30), _clamp(base[1] + 28), _clamp(base[2] + 25))
    for y in range(TEX_SIZE):
        for x in range(TEX_SIZE):
            # Diamond plate crosshatch
            if (x + y) % 8 == 0 or (x - y) % 8 == 0:
                n = rng.randint(-3, 3)
                c = (_clamp(base[0] + 12 + n), _clamp(base[1] + 12 + n),
                     _clamp(base[2] + 14 + n))
            else:
                n = rng.randint(-5, 5)
                c = (_clamp(base[0] + n), _clamp(base[1] + n), _clamp(base[2] + n))
            # rivets at corners of 32px grid
            dx, dy = x % 32, y % 32
            if dx < 3 and dy < 3:
                c = rivet
            surf.set_at((x, y), c)
    return surf


# ── Crate Stack (top-down view of wooden crate lids) ────────────────

def _gen_crate_stack(base: tuple[int, int, int]) -> pygame.Surface:
    surf = pygame.Surface((TEX_SIZE, TEX_SIZE))
    rng = random.Random(300)
    edge = (_clamp(base[0] - 25), _clamp(base[1] - 20), _clamp(base[2] - 15))
    cross = (_clamp(base[0] + 15), _clamp(base[1] + 10), _clamp(base[2] + 5))
    for y in range(TEX_SIZE):
        for x in range(TEX_SIZE):
            # Crate borders every 32 px
            bx, by = x % 32, y % 32
            if bx < 2 or by < 2 or bx >= 30 or by >= 30:
                c = edge
            # Cross braces on each crate lid
            elif abs(bx - by) < 2 or abs(bx - (31 - by)) < 2:
                c = cross
            else:
                n = rng.randint(-6, 6)
                c = (_clamp(base[0] + n), _clamp(base[1] + n), _clamp(base[2] + n))
            surf.set_at((x, y), c)
    return surf


# ── Registry (texture_key → generator) ──────────────────────────────
# Tiles reference a texture_key (str) in TILE_REGISTRY; the generator
# is looked up here.  Unknown keys fall back to _gen_noise.

_KEY_GENERATORS: dict[str, object] = {
    "void":       _gen_noise,
    "grass":      _gen_grass,
    "dirt":       _gen_dirt,
    "stone":      _gen_stone,
    "water":      _gen_water,
    "wood":       _gen_wood,
    "wall":       _gen_wall,
    "sand":       _gen_sand,
    "door":       _gen_teleporter,
    "gateway":    _gen_gateway,
    "window":     _gen_window,
    "metal":      _gen_metal,
    "concrete":   _gen_concrete,
    "tile_floor": _gen_tile_floor,
    "rubble":     _gen_rubble,
    "bookshelf":  _gen_bookshelf,
    "crate":      _gen_crate,
    "barrel":     _gen_barrel,
    "shelf":      _gen_bookshelf,
    "half_wall":  _gen_wall,       # reuse brick pattern
    "low_wall":   _gen_stone,      # reuse stone pattern
    "pillar":     _gen_pillar,
    "counter_top": _gen_counter_top,
    "railing":    _gen_railing,
    "carpet":     _gen_carpet,
    "brick_wall": _gen_brick_wall,
    "wood_panel": _gen_wood_panel,
    "cracked_floor": _gen_cracked_floor,
    "stone_floor": _gen_stone_floor,
    "shelf_wall": _gen_shelf_wall,
    "stone_platform": _gen_stone_platform,
    "wood_platform":  _gen_wood_platform,
    "metal_platform": _gen_metal_platform,
    "crate_stack":    _gen_crate_stack,
    "table":          _gen_table,
    "curb":           _gen_curb,
    "stool":          _gen_stool,
    "step":           _gen_step,
}
