"""Micro-benchmarks to validate specific optimisation approaches."""
import os, sys, time
os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"
import pygame, collections
pygame.init()

SW, SH = 960, 640
surface = pygame.Surface((SW, SH))
N_STRIPS = 240  # RAY_STEP=4 scenario
COL_W = 4

# ── blits() vs individual blit ──────────────────────────────────────
strips = [(pygame.Surface((COL_W, 200)), (i * COL_W, 100)) for i in range(N_STRIPS)]
WARMUP, ITERS = 20, 1000

for _ in range(WARMUP):
    for s, p in strips:
        surface.blit(s, p)
t0 = time.perf_counter()
for _ in range(ITERS):
    for s, p in strips:
        surface.blit(s, p)
t1 = time.perf_counter()
print(f"individual blit x{N_STRIPS}:  {(t1-t0)/ITERS*1000:.3f} ms/frame")

for _ in range(WARMUP):
    surface.blits(strips)
t0 = time.perf_counter()
for _ in range(ITERS):
    surface.blits(strips)
t1 = time.perf_counter()
print(f"blits() x{N_STRIPS}:          {(t1-t0)/ITERS*1000:.3f} ms/frame")

# ── namedtuple .attr vs tuple [idx] ─────────────────────────────────
WS = collections.namedtuple("WS", "a b c d e f g h i j")
ws = WS(1, 2.0, 3, 4, 5, 0.6, 1.0, 0.1, 0.2, 0.3)
ws_tuple = tuple(ws)

ITERS2 = 2_000_000
t0 = time.perf_counter()
for _ in range(ITERS2):
    _ = ws.a; _ = ws.b; _ = ws.c; _ = ws.d; _ = ws.e
t1 = time.perf_counter()
print(f"namedtuple .attr x5 x{ITERS2//1000}k: {(t1-t0)*1000:.1f} ms")

t0 = time.perf_counter()
for _ in range(ITERS2):
    _ = ws[0]; _ = ws[1]; _ = ws[2]; _ = ws[3]; _ = ws[4]
t1 = time.perf_counter()
print(f"namedtuple [idx] x5 x{ITERS2//1000}k: {(t1-t0)*1000:.1f} ms")

t0 = time.perf_counter()
for _ in range(ITERS2):
    _ = ws_tuple[0]; _ = ws_tuple[1]; _ = ws_tuple[2]; _ = ws_tuple[3]; _ = ws_tuple[4]
t1 = time.perf_counter()
print(f"plain tuple [idx] x5 x{ITERS2//1000}k: {(t1-t0)*1000:.1f} ms")

# ── list zbuf fill vs numpy zbuf ────────────────────────────────────
import numpy as np
ITERS3 = 10_000

t0 = time.perf_counter()
for _ in range(ITERS3):
    zbuf = [1e10] * SW
    for i in range(0, SW, COL_W):
        zbuf[i:i+COL_W] = [5.0] * COL_W
t1 = time.perf_counter()
print(f"list zbuf fill x{ITERS3}: {(t1-t0)/ITERS3*1000:.3f} ms")

t0 = time.perf_counter()
for _ in range(ITERS3):
    zbuf = np.full(SW, 1e10)
    for i in range(0, SW, COL_W):
        zbuf[i:i+COL_W] = 5.0
t1 = time.perf_counter()
print(f"numpy zbuf fill x{ITERS3}: {(t1-t0)/ITERS3*1000:.3f} ms")

# pre-allocated numpy
zbuf_np = np.full(SW, 1e10)
t0 = time.perf_counter()
for _ in range(ITERS3):
    zbuf_np[:] = 1e10
    for i in range(0, SW, COL_W):
        zbuf_np[i:i+COL_W] = 5.0
t1 = time.perf_counter()
print(f"numpy zbuf reuse x{ITERS3}: {(t1-t0)/ITERS3*1000:.3f} ms")

# ── AO fills: full set vs skip distant ──────────────────────────────
AO_COLOR = (120, 120, 115)
ITERS4 = 2000

t0 = time.perf_counter()
for _ in range(ITERS4):
    for i in range(N_STRIPS):
        surface.fill(AO_COLOR, (i * COL_W, 100, COL_W, 6), pygame.BLEND_MULT)
t1 = time.perf_counter()
print(f"AO fill all {N_STRIPS} x{ITERS4}: {(t1-t0)/ITERS4*1000:.3f} ms")

t0 = time.perf_counter()
for _ in range(ITERS4):
    for i in range(N_STRIPS // 3):  # only near walls
        surface.fill(AO_COLOR, (i * COL_W, 100, COL_W, 6), pygame.BLEND_MULT)
t1 = time.perf_counter()
print(f"AO fill 1/3 near x{ITERS4}: {(t1-t0)/ITERS4*1000:.3f} ms")

# ── floor buffer sizes ──────────────────────────────────────────────
ITERS5 = 500

for fdiv, label in [(5, "FDIV=5"), (6, "FDIV=6"), (7, "FDIV=7")]:
    fbw = SW // fdiv
    fbh = SH // (fdiv * 2)
    fb = pygame.Surface((fbw, fbh))
    arr = np.random.randint(0, 255, (fbh, fbw, 3), dtype=np.uint8)
    t0 = time.perf_counter()
    for _ in range(ITERS5):
        buf = arr.tobytes()
        img = pygame.image.frombuffer(buf, (fbw, fbh), "RGB")
        scaled = pygame.transform.scale(img, (SW, SH // 2))
        surface.blit(scaled, (0, SH // 2))
    t1 = time.perf_counter()
    print(f"floor {label} ({fbw}x{fbh}): {(t1-t0)/ITERS5*1000:.3f} ms")

pygame.quit()
print("\nDone.")
