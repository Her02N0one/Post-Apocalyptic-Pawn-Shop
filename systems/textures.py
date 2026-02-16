"""systems/textures.py — Procedural tile texture atlas.

Generates a 64×64 pixel texture Surface for each tile ID.  These are
used by the first-person renderer for wall columns and floor spans.

To swap in real art later, replace the procedural generation in
``_generate_*`` functions with ``pygame.image.load()``.

    from systems.textures import TextureAtlas
    atlas = TextureAtlas()          # builds once on first call
    wall_surf = atlas.get(TILE_WALL)  # 64×64 Surface
    pixel = atlas.sample(TILE_WALL, tx, ty)  # (r,g,b) at 0..1 coords
"""

from __future__ import annotations

import random

import pygame

from core.constants import TILE_COLORS

# Texture resolution — power of two for fast bitwise modulo
TEX_SIZE = 64
_TEX_MASK = TEX_SIZE - 1  # for & instead of %


class TextureAtlas:
    """Lazy-built atlas of 64×64 procedural textures, one per tile ID."""

    def __init__(self) -> None:
        self._surfaces: dict[int, pygame.Surface] = {}
        self._pixels: dict[int, pygame.PixelArray] = {}

    def get(self, tile_id: int) -> pygame.Surface:
        """Return the 64×64 Surface for a tile.  Builds on first access."""
        if tile_id not in self._surfaces:
            self._surfaces[tile_id] = _generate(tile_id)
        return self._surfaces[tile_id]

    def sample(self, tile_id: int, u: float, v: float) -> tuple[int, int, int]:
        """Sample colour at normalised (u, v) coords ∈ [0, 1)."""
        surf = self.get(tile_id)
        tx = int(u * TEX_SIZE) & _TEX_MASK
        ty = int(v * TEX_SIZE) & _TEX_MASK
        return surf.get_at((tx, ty))[:3]  # type: ignore[return-value]


# ═════════════════════════════════════════════════════════════════════
#  Procedural generators
# ═════════════════════════════════════════════════════════════════════

def _generate(tile_id: int) -> pygame.Surface:
    """Dispatch to the right generator for this tile type."""
    base = TILE_COLORS.get(tile_id, (80, 80, 80))
    gen = _GENERATORS.get(tile_id, _gen_noise)
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
    for y in range(TEX_SIZE):
        for x in range(TEX_SIZE):
            dist = _math.sqrt((x - 32) ** 2 + (y - 32) ** 2)
            v = int(20 * _math.sin(dist * 0.4))
            c = (_clamp(base[0] + v), _clamp(base[1] - 10),
                 _clamp(base[2] + v))
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


# ── Registry ────────────────────────────────────────────────────────

from core.constants import (
    TILE_VOID, TILE_GRASS, TILE_DIRT, TILE_STONE, TILE_WATER,
    TILE_WOOD_FLOOR, TILE_WALL, TILE_SAND, TILE_RUBBLE, TILE_TELEPORTER,
    TILE_WINDOW,
)

_GENERATORS = {
    TILE_VOID:       _gen_noise,
    TILE_GRASS:      _gen_grass,
    TILE_DIRT:       _gen_dirt,
    TILE_STONE:      _gen_stone,
    TILE_WATER:      _gen_water,
    TILE_WOOD_FLOOR: _gen_wood,
    TILE_WALL:       _gen_wall,
    TILE_SAND:       _gen_sand,
    TILE_RUBBLE:     _gen_dirt,
    TILE_TELEPORTER: _gen_teleporter,
    TILE_WINDOW:     _gen_window,
}
