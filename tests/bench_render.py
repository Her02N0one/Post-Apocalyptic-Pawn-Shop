"""tests/bench_render.py — Micro-benchmark for each rendering stage.

Run:
    python tests/bench_render.py

Simulates 200 frames of camera rotation (the worst-case for cache
thrashing) and prints per-stage timings plus percentile breakdowns.
"""

from __future__ import annotations

import gc
import math
import os
import sys
import time

# ── Bootstrap ────────────────────────────────────────────────────
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame
pygame.init()
screen = pygame.display.set_mode((960, 640))

# Project root on sys.path
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)

import numpy as np
from systems.raycaster import cast_walls, project_entities, WallSlice
from systems.textures import TextureAtlas, TEX_SIZE
from scenes.world.fp_renderer import Renderer, FOV, compute_fog_params
from scenes.world.fp_walls import RAY_STEP
from scenes.world.fp_lighting import build_fog_lut

# ═════════════════════════════════════════════════════════════════════
#  Stress-test map  (20×30 with mixed full / half walls)
# ═════════════════════════════════════════════════════════════════════

_W = 6   # full wall
_F = 0   # floor
_H = 27  # half-wall (stone platform)

MAP_H, MAP_W = 20, 30
TILES: list[list[int]] = []
for r in range(MAP_H):
    row: list[int] = []
    for c in range(MAP_W):
        if r == 0 or r == MAP_H - 1 or c == 0 or c == MAP_W - 1:
            row.append(_W)
        elif (r % 5 == 0 and c % 4 == 0):
            row.append(_W)
        elif (r % 7 == 0 and c % 3 == 0):
            row.append(_H)
        else:
            row.append(_F)
    TILES.append(row)

# Player start in open area
PX, PY = 10.5, 10.5
SW, SH = 960, 640
HALF = SH // 2

# Fake entities spread across the map
ENTITY_DATA = [
    (i, 5.0 + (i % 5) * 3.0, 5.0 + (i // 5) * 3.0,
     "N", (180, 160, 140), 0.75, 0.50, 0.0)
    for i in range(15)
]


def percentiles(data: list[float]) -> str:
    """Return p50/p90/p99/max summary string."""
    s = sorted(data)
    n = len(s)
    if n == 0:
        return "no data"
    p50 = s[int(n * 0.50)]
    p90 = s[int(n * 0.90)]
    p99 = s[min(n - 1, int(n * 0.99))]
    mx = s[-1]
    avg = sum(s) / n
    return f"avg={avg*1000:6.2f}  p50={p50*1000:6.2f}  p90={p90*1000:6.2f}  p99={p99*1000:6.2f}  max={mx*1000:6.2f} ms"


def bench_cast_walls(n_frames: int = 200) -> list[float]:
    """Bench just the DDA raycaster (no pygame blitting)."""
    times: list[float] = []
    angle = 0.0
    for i in range(n_frames):
        angle += 0.08  # fast rotation
        t0 = time.perf_counter()
        cast_walls(PX, PY, angle, FOV, SW, SH, TILES, step=RAY_STEP)
        times.append(time.perf_counter() - t0)
    return times


def bench_wall_blit(n_frames: int = 200) -> list[float]:
    """Bench the full draw_walls (cast + cache + blit)."""
    renderer = Renderer()
    surface = pygame.Surface((SW, SH))
    dn = 1.0
    _, _, fog_lut = compute_fog_params(dn)
    times: list[float] = []
    angle = 0.0
    for i in range(n_frames):
        angle += 0.08
        t0 = time.perf_counter()
        renderer.draw_walls(surface, SW, SH, HALF, PX, PY,
                            angle, FOV, TILES, fog_lut, dn)
        times.append(time.perf_counter() - t0)
    return times


def bench_floor_ceiling(n_frames: int = 200) -> list[float]:
    """Bench floor/ceiling rendering."""
    renderer = Renderer()
    surface = pygame.Surface((SW, SH))
    dn = 1.0
    _, _, fog_lut = compute_fog_params(dn)
    times: list[float] = []
    angle = 0.0
    for i in range(n_frames):
        angle += 0.08
        t0 = time.perf_counter()
        renderer.draw_floor_ceiling(surface, SW, SH, HALF, PX, PY,
                                    angle, fog_lut, dn, FOV,
                                    TILES, MAP_W, MAP_H, True)
        times.append(time.perf_counter() - t0)
    return times


def bench_entity_billboards(n_frames: int = 200) -> list[float]:
    """Bench entity projection + billboard blitting (no half-walls)."""
    renderer = Renderer()
    surface = pygame.Surface((SW, SH))
    zbuf = [1e10] * SW
    dn = 1.0
    fog_rate, _, fog_lut = compute_fog_params(dn)
    bb_fog_lut = build_fog_lut(255, dn)
    times: list[float] = []
    angle = 0.0
    for i in range(n_frames):
        angle += 0.08
        billboards = project_entities(PX, PY, angle, FOV, SW, SH, ENTITY_DATA)
        zbuf_np = np.asarray(zbuf, dtype=np.float64)
        t0 = time.perf_counter()
        # Simulate _draw_billboards inline (we can't easily get app)
        for bb in billboards:
            if bb.height < 2:
                continue
            ent_w = (bb.width if bb.width > 0 else bb.height) & ~3 or 4
            ent_h = bb.height & ~3 or 4
            if ent_w < 4:
                continue
            fog_idx = min(255, int(bb.distance * 8.0))
            fog = bb_fog_lut[fog_idx]
            fogged = (bb.color[0] * fog // 255,
                      bb.color[1] * fog // 255,
                      bb.color[2] * fog // 255)
            dx = int(bb.screen_x - ent_w // 2)
            dy = int(bb.screen_y)
            left = max(0, dx)
            right = min(SW, dx + ent_w)
            if left >= right:
                continue
            dist = bb.distance
            zbuf_slice = zbuf_np[left:right]
            visible = dist < zbuf_slice
            if not visible.any():
                continue
            _eq = ((ent_w + 7) & ~7, (ent_h + 7) & ~7)
            ent_surf = pygame.Surface(_eq, pygame.SRCALPHA)
            ent_surf.fill((0, 0, 0, 0))
            pygame.draw.rect(ent_surf, (*fogged, 230), (0, 0, ent_w, ent_h))
            surface.blit(ent_surf, (left, dy), (left - dx, 0, right - left, ent_h))
        times.append(time.perf_counter() - t0)
    return times


def bench_zbuf_build(n_frames: int = 200) -> list[float]:
    """Bench zbuf_full construction inside draw_walls."""
    times: list[float] = []
    for i in range(n_frames):
        zbuf = [1e10] * SW
        # Simulate filling zbuf for 320 rays
        t0 = time.perf_counter()
        for col in range(0, SW, RAY_STEP):
            col_end = min(col + RAY_STEP, SW)
            zbuf[col:col_end] = [5.0] * (col_end - col)
        times.append(time.perf_counter() - t0)
    return times


def bench_cache_miss_storm(n_frames: int = 200) -> list[float]:
    """Bench worst-case: fast rotation, every frame is mostly cache misses."""
    renderer = Renderer()
    surface = pygame.Surface((SW, SH))
    dn = 1.0
    _, _, fog_lut = compute_fog_params(dn)
    times: list[float] = []
    cache_miss_counts: list[int] = []
    
    angle = 0.0
    for i in range(n_frames):
        angle += 0.15  # VERY fast rotation
        before = len(renderer._strip_cache)
        t0 = time.perf_counter()
        renderer.draw_walls(surface, SW, SH, HALF, PX, PY,
                            angle, FOV, TILES, fog_lut, dn)
        times.append(time.perf_counter() - t0)
        after = len(renderer._strip_cache)
        cache_miss_counts.append(after - before)
    
    avg_miss = sum(cache_miss_counts) / len(cache_miss_counts)
    print(f"  Cache misses/frame: avg={avg_miss:.0f}  "
          f"max={max(cache_miss_counts)}  "
          f"cache_size_final={len(renderer._strip_cache)}")
    return times


def bench_subsurface_scale(n_frames: int = 200) -> list[float]:
    """Bench the raw cost of subsurface + scale — the cache-miss penalty."""
    atlas = TextureAtlas()
    tex = atlas.get(6)  # wall tile
    _scale = pygame.transform.scale
    times: list[float] = []
    for i in range(n_frames):
        t0 = time.perf_counter()
        for _ in range(320):  # one per ray
            strip = tex.subsurface((0, 0, 1, 32))
            _scale(strip, (3, 200))
        times.append(time.perf_counter() - t0)
    return times


def bench_blit_only(n_frames: int = 200) -> list[float]:
    """Bench just the surface.blit calls (320 strips per frame)."""
    surface = pygame.Surface((SW, SH))
    strips = []
    for i in range(320):
        s = pygame.Surface((3, 200))
        s.fill((100, 80, 60))
        strips.append(s)
    times: list[float] = []
    for i in range(n_frames):
        t0 = time.perf_counter()
        for j, s in enumerate(strips):
            surface.blit(s, (j * 3, 100))
        times.append(time.perf_counter() - t0)
    return times


def bench_fill_ao(n_frames: int = 200) -> list[float]:
    """Bench the AO fill calls (one per full-wall column)."""
    surface = pygame.Surface((SW, SH))
    _fill = surface.fill
    _BLEND = pygame.BLEND_MULT
    times: list[float] = []
    for i in range(n_frames):
        t0 = time.perf_counter()
        for j in range(320):
            _fill((120, 120, 115), (j * 3, 400, 3, 4), special_flags=_BLEND)
        times.append(time.perf_counter() - t0)
    return times


def bench_full_frame(n_frames: int = 200) -> list[float]:
    """Bench complete render frame (floor + walls) under rotation."""
    renderer = Renderer()
    surface = pygame.Surface((SW, SH))
    dn = 1.0
    _, _, fog_lut = compute_fog_params(dn)
    times: list[float] = []
    angle = 0.0
    for i in range(n_frames):
        angle += 0.08
        gc_was = gc.isenabled()
        gc.disable()
        t0 = time.perf_counter()
        renderer.draw_floor_ceiling(surface, SW, SH, HALF, PX, PY,
                                    angle, fog_lut, dn, FOV,
                                    TILES, MAP_W, MAP_H, True)
        renderer.draw_walls(surface, SW, SH, HALF, PX, PY,
                            angle, FOV, TILES, fog_lut, dn)
        times.append(time.perf_counter() - t0)
        if gc_was:
            gc.enable()
    return times


# ═════════════════════════════════════════════════════════════════════
#  Main
# ═════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 72)
    print("  Render Pipeline Stress-Test Benchmark")
    print("  960×640, RAY_STEP={}, 20×30 map, 200 frames of rotation".format(RAY_STEP))
    print("=" * 72)
    print()

    benchmarks = [
        ("DDA cast_walls", bench_cast_walls),
        ("draw_walls (cast+cache+blit)", bench_wall_blit),
        ("  cache-miss storm (fast rot)", bench_cache_miss_storm),
        ("  subsurface+scale ×320", bench_subsurface_scale),
        ("  blit-only ×320 strips", bench_blit_only),
        ("  fill AO ×320", bench_fill_ao),
        ("  zbuf build", bench_zbuf_build),
        ("floor/ceiling", bench_floor_ceiling),
        ("entity billboards ×15", bench_entity_billboards),
        ("full frame (floor+walls)", bench_full_frame),
    ]

    for name, fn in benchmarks:
        # Warmup
        fn(10)
        # Measured run
        times = fn(200)
        print(f"{name:>36s}:  {percentiles(times)}")

    print()
    print("Done.")
    pygame.quit()
