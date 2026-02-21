"""scenes/world/fp_renderer.py — First-person rendering coordinator.

Owns GPU-side caches and assembles the ``Renderer`` class from
focused sub-modules:

*  ``fp_lighting``  — day/night + fog helpers
*  ``fp_walls``     — wall column casting & blitting
*  ``fp_surfaces``  — floor, ceiling, visplane, tint
*  ``fp_entities``  — billboard projection & drawing

Previously a single 1100+ line file; split for maintainability while
keeping all rendering behind the same ``Renderer`` interface.
"""

from __future__ import annotations

import math

import pygame
import numpy as np

from core.fonts import get_font
from systems.textures import TextureAtlas

# ── Re-exports (public API consumed by firstperson.py, fp_hud.py) ─
from scenes.world.fp_lighting import (          # noqa: F401
    day_night_factor,
    compute_fog_params,
    build_fog_lut,
    lerp_color,
)
from scenes.world.fp_walls import RAY_STEP      # noqa: F401

# ═════════════════════════════════════════════════════════════════════
#  Constants
# ═════════════════════════════════════════════════════════════════════

FOV = math.pi / 3  # 60° horizontal field of view


# ═════════════════════════════════════════════════════════════════════
#  Renderer
# ═════════════════════════════════════════════════════════════════════


class Renderer:
    """Owns GPU-side caches and all first-person draw methods.

    Draw methods are attached from their respective sub-modules so
    each can be maintained independently.
    """

    def __init__(self) -> None:
        self._atlas = TextureAtlas()
        # Eagerly generate all tiles in memory
        self._atlas.ensure_all()

        # ── Strip / column caches (generational) ─────────────
        self._strip_cache: dict[tuple, pygame.Surface] = {}
        self._strip_cache_prev: dict[tuple, pygame.Surface] = {}
        self._col_cache: dict[tuple, pygame.Surface] = {}
        # Free-list for recycled wall strip Surfaces, keyed by
        # (col_w, draw_h_q).  Eliminates new Surface allocations
        # during generational cache swaps.
        self._strip_free: dict[tuple[int, int], list[pygame.Surface]] = {}

        # ── Entity / prop caches ─────────────────────────────
        self._prop_surfaces: dict[str, pygame.Surface] = {}
        self._glyph_cache: dict[tuple[str, int], tuple[pygame.Surface, pygame.Surface]] = {}
        self._ent_pool: dict[tuple[int, int], pygame.Surface] = {}
        # Single shared canvas for entity billboard rendering.
        # Avoids ALL runtime pygame.Surface() allocations which
        # cost ~40-50 ms each on Windows due to page-fault storms.
        # Entities are drawn into a subsurface view of this canvas
        # and blitted to the screen immediately, then the next
        # entity reuses the same pixel buffer.
        self._ent_canvas: pygame.Surface = pygame.Surface((384, 384))
        # Shared SRCALPHA surface for transparent wall strips.
        # Reused each frame to avoid per-strip Surface allocations.
        self._trans_canvas: pygame.Surface = pygame.Surface(
            (384, 384), pygame.SRCALPHA)
        # Kept as alias so perf logger can still read len()
        self._bb_base_cache: dict = {}

        # ── Misc ─────────────────────────────────────────────
        self._cached_zone: str = ""
        self._tint_surf: pygame.Surface | None = None
        self._cast_time: float = 0.0

        # ── Visplane fogged-palette cache ────────────────────
        self._vp_fpal: dict[int, tuple[list, list]] = {}
        self._vp_fpal_key: tuple | None = None

        # ── Numpy tile / colour-table caches ─────────────────
        self._np_tiles_key: tuple | None = None
        self._np_tiles_arr: np.ndarray | None = None
        self._floor_ct: np.ndarray | None = None
        self._floor_ct_key: tuple | None = None
        self._vp_ct: np.ndarray | None = None
        self._vp_ct_key: tuple | None = None

    # ── Cache management ─────────────────────────────────────────

    def invalidate_zone(self, zone: str) -> None:
        """Clear caches when the player moves to a different zone."""
        if self._cached_zone != zone:
            self._strip_cache.clear()
            self._strip_cache_prev.clear()
            self._col_cache.clear()
            self._cached_zone = zone
            self._np_tiles_key = None
            self._floor_ct_key = None
            self._vp_ct_key = None

    def notify_tiles_changed(self) -> None:
        """Flush all tile-dependent caches after in-place grid edits.

        Call after *any* tile placement, erase, or fill so that walls
        render correctly on the very next frame.
        """
        from systems.raycaster import invalidate_caches as _inv_ray
        from scenes.world.fp_walls import invalidate_face_cache as _inv_face
        _inv_ray()
        _inv_face()
        self._strip_cache.clear()
        self._strip_cache_prev.clear()
        self._col_cache.clear()
        self._strip_free.clear()
        self._np_tiles_key = None
        self._floor_ct_key = None
        self._vp_ct_key = None

    def warmup(self) -> None:
        """Pre-allocate Surfaces and populate caches to eliminate
        first-frame lag spikes caused by OS page-fault storms.

        Called once on zone entry BEFORE the first render frame.
        Costs ~50-100 ms but prevents the ~200 ms of scattered
        spikes that would otherwise happen over the first second.
        """
        import pygame

        # ── 1. Pre-populate wall strip free-list ─────────────
        # Common strip sizes: col_w is RAY_STEP (4), draw_h_q
        # ranges from 8 to 320 in 8px steps.
        _free = self._strip_free
        for col_w in (1, 2, 3, 4):
            for draw_h_q in range(8, 328, 8):
                _sz = (col_w, draw_h_q)
                if _sz not in _free:
                    _free[_sz] = []
                # Pre-alloc 2 surfaces per size bucket
                while len(_free[_sz]) < 2:
                    _free[_sz].append(pygame.Surface(_sz))

        # ── 2. Pre-load prop textures ────────────────────────
        from scenes.world.fp_entities import PROP_GLYPHS
        for prop_key in PROP_GLYPHS.values():
            if prop_key not in self._prop_surfaces:
                self._get_prop_surface(prop_key)

        # ── 3. Pre-warm glyph cache for common entity chars ──
        from scenes.world.fp_entities import ENTITY_VIS
        common_chars = list(ENTITY_VIS.keys())
        for ch in common_chars:
            for font_size in (8, 10, 12, 14, 16, 20, 24, 32):
                gk = (ch, font_size)
                if gk not in self._glyph_cache:
                    font = self.get_font(font_size)
                    shadow = font.render(ch, True, (0, 0, 0))
                    glyph = font.render(ch, True, (255, 255, 240))
                    self._glyph_cache[gk] = (shadow, glyph)

        # ── 4. Pre-warm font cache for common sizes ──────────
        for sz in (8, 10, 11, 12, 14, 16, 18, 20, 24, 32, 48):
            self.get_font(sz)

    # ── Font cache ───────────────────────────────────────────────

    def get_font(self, size: int) -> pygame.font.Font:
        """Cached monospace font at *size* pixels."""
        return get_font(size)

    # ── Numpy cache helpers ──────────────────────────────────────

    def _get_np_tiles(
        self,
        tiles: list[list[int]],
        map_h: int, map_w: int,
    ) -> np.ndarray:
        """Return *tiles* as a cached ``(map_h, map_w)`` int32 array."""
        key = (id(tiles), map_h, map_w)
        if self._np_tiles_key == key and self._np_tiles_arr is not None:
            return self._np_tiles_arr
        self._np_tiles_arr = np.array(tiles, dtype=np.int32)
        self._np_tiles_key = key
        return self._np_tiles_arr

    def _get_floor_ct(
        self,
        fog_lut: list[int],
        pal: list[tuple[int, int, int]],
        pal_len: int,
    ) -> np.ndarray:
        """Pre-compute floor colour table ``(256, pal_len, 2, 3)``."""
        key = (id(fog_lut), pal_len, 'f')
        if self._floor_ct_key == key and self._floor_ct is not None:
            return self._floor_ct
        fog = np.array(fog_lut, dtype=np.float64) / 255.0
        pal_np = np.array(pal[:pal_len], dtype=np.float64)
        bright = np.clip(
            fog[:, None, None] * pal_np[None, :, :], 0, 255,
        ).astype(np.uint8)
        dark = np.clip(
            (fog * 0.88)[:, None, None] * pal_np[None, :, :], 0, 255,
        ).astype(np.uint8)
        ct = np.stack([bright, dark], axis=2)
        self._floor_ct = ct
        self._floor_ct_key = key
        return ct

    def _get_vp_ct(
        self,
        fog_lut: list[int],
        pal: list[tuple[int, int, int]],
        pal_len: int,
    ) -> np.ndarray:
        """Pre-compute visplane colour table ``(256, pal_len, 2, 3)``.

        Uses brighter fog multiplier (×1.2) and tighter dark-side
        ratio (0.92) compared to the floor.
        """
        key = (id(fog_lut), pal_len, 'v')
        if self._vp_ct_key == key and self._vp_ct is not None:
            return self._vp_ct
        fog = np.array(fog_lut, dtype=np.float64) * 0.00470588
        fog_d = fog * 0.92
        pal_np = np.array(pal[:pal_len], dtype=np.float64)
        bright = np.clip(
            fog[:, None, None] * pal_np[None, :, :], 0, 255,
        ).astype(np.uint8)
        dark = np.clip(
            fog_d[:, None, None] * pal_np[None, :, :], 0, 255,
        ).astype(np.uint8)
        ck = ((bright[:, :, 0] == 0) & (bright[:, :, 1] == 0)
              & (bright[:, :, 2] == 1))
        bright[ck, 2] = 2
        ck = ((dark[:, :, 0] == 0) & (dark[:, :, 1] == 0)
              & (dark[:, :, 2] == 1))
        dark[ck, 2] = 2
        ct = np.stack([bright, dark], axis=2)
        self._vp_ct = ct
        self._vp_ct_key = key
        return ct

    # ═════════════════════════════════════════════════════════════
    #  Attach methods from sub-modules
    # ═════════════════════════════════════════════════════════════

    # Wall columns (fp_walls.py)
    from scenes.world.fp_walls import draw_walls               # type: ignore[assignment]

    # Floor, ceiling, visplane, day/night tint (fp_surfaces.py)
    from scenes.world.fp_surfaces import (                     # type: ignore[assignment]
        draw_floor_ceiling,
        draw_visplane_tops,
        draw_day_night,
    )

    # Entity billboards (fp_entities.py)
    from scenes.world.fp_entities import (                     # type: ignore[assignment]
        draw_entities,
        _draw_billboards,
        _draw_one_billboard,
        _get_prop_surface,
    )

    # Wall-entity rendering (fp_wall_entities.py)
    from scenes.world.fp_wall_entities import (                # type: ignore[assignment]
        draw_wall_entities,
    )
