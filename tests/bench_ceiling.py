"""Benchmark: vectorised ceiling vs python-loop ceiling."""
import os, time
os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"
import pygame, numpy as np
pygame.init()

s = pygame.Surface((960, 640))
fog = [max(0, min(255, int(255 - i * 1.2))) for i in range(256)]
fa = np.asarray(fog, dtype=np.float64)
cc = (45, 48, 52)
sw, sh, half = 960, 640, 320
cbw, cbh = sw // 4, half // 4
ITERS = 2000

# ── Vectorised ceiling ──────────────────────────────────────
for _ in range(50):  # warmup
    _cy = np.arange(cbh, dtype=np.float64)
    dy = (cbh - _cy) * 4
    p = dy + 0.5
    rd = 160.0 / p
    fi = np.clip((rd * 8).astype(np.int32), 0, 255)
    ff = fa[fi] * 0.003921568627451
    cr = np.clip((cc[0] * ff).astype(np.int32), 0, 255).astype(np.uint8)
    cg = np.clip((cc[1] * ff).astype(np.int32), 0, 255).astype(np.uint8)
    cb = np.clip((cc[2] * ff).astype(np.int32), 0, 255).astype(np.uint8)
    rgb = np.empty((cbh, cbw, 3), dtype=np.uint8)
    rgb[:, :, 0] = cr[:, None]
    rgb[:, :, 1] = cg[:, None]
    rgb[:, :, 2] = cb[:, None]
    fb = pygame.image.frombuffer(rgb.tobytes(), (cbw, cbh), "RGB")
    s.blit(pygame.transform.scale(fb, (sw, half)), (0, 0))

t0 = time.perf_counter()
for _ in range(ITERS):
    _cy = np.arange(cbh, dtype=np.float64)
    dy = (cbh - _cy) * 4
    p = dy + 0.5
    rd = 160.0 / p
    fi = np.clip((rd * 8).astype(np.int32), 0, 255)
    ff = fa[fi] * 0.003921568627451
    cr = np.clip((cc[0] * ff).astype(np.int32), 0, 255).astype(np.uint8)
    cg = np.clip((cc[1] * ff).astype(np.int32), 0, 255).astype(np.uint8)
    cb = np.clip((cc[2] * ff).astype(np.int32), 0, 255).astype(np.uint8)
    rgb = np.empty((cbh, cbw, 3), dtype=np.uint8)
    rgb[:, :, 0] = cr[:, None]
    rgb[:, :, 1] = cg[:, None]
    rgb[:, :, 2] = cb[:, None]
    fb = pygame.image.frombuffer(rgb.tobytes(), (cbw, cbh), "RGB")
    s.blit(pygame.transform.scale(fb, (sw, half)), (0, 0))
t1 = time.perf_counter()
print(f"vectorised ceiling:   {(t1-t0)/ITERS*1000:.3f} ms")

# ── Python-loop ceiling ─────────────────────────────────────
for _ in range(50):
    cbuf = bytearray(cbw * cbh * 3)
    rb = cbw * 3
    for cy in range(cbh):
        dy2 = (cbh - cy) * 4
        p2 = dy2 + 0.5
        rd2 = 160.0 / p2
        fi2 = min(255, int(rd2 * 8))
        ff2 = fog[fi2] * 0.003921568627
        r2 = max(0, min(255, int(cc[0] * ff2)))
        g2 = max(0, min(255, int(cc[1] * ff2)))
        b2 = max(0, min(255, int(cc[2] * ff2)))
        ro = cy * rb
        px = bytes((r2, g2, b2))
        cbuf[ro:ro + rb] = px * cbw
    fb = pygame.image.frombuffer(bytes(cbuf), (cbw, cbh), "RGB")
    s.blit(pygame.transform.scale(fb, (sw, half)), (0, 0))

t0 = time.perf_counter()
for _ in range(ITERS):
    cbuf = bytearray(cbw * cbh * 3)
    rb = cbw * 3
    for cy in range(cbh):
        dy2 = (cbh - cy) * 4
        p2 = dy2 + 0.5
        rd2 = 160.0 / p2
        fi2 = min(255, int(rd2 * 8))
        ff2 = fog[fi2] * 0.003921568627
        r2 = max(0, min(255, int(cc[0] * ff2)))
        g2 = max(0, min(255, int(cc[1] * ff2)))
        b2 = max(0, min(255, int(cc[2] * ff2)))
        ro = cy * rb
        px = bytes((r2, g2, b2))
        cbuf[ro:ro + rb] = px * cbw
    fb = pygame.image.frombuffer(bytes(cbuf), (cbw, cbh), "RGB")
    s.blit(pygame.transform.scale(fb, (sw, half)), (0, 0))
t1 = time.perf_counter()
print(f"python-loop ceiling:  {(t1-t0)/ITERS*1000:.3f} ms")

pygame.quit()
