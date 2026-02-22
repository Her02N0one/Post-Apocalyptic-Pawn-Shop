#!/usr/bin/env python3
"""debug_render.py — Generate annotated diagnostic PNGs from the renderer.

Produces a set of reference screenshots in debug_renders/ with:
  • Full-color renders from multiple viewpoints
  • Z-buffer heatmap visualisation
  • Column-by-column depth chart (ASCII)
  • Per-pixel analysis summary

Usage:
    .venv/bin/python debug_render.py [zone_name]

Default zone: showcase
"""

from __future__ import annotations

import math
import os
import struct
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

pygame.init()
pygame.display.set_mode((100, 100))

from core.zones import load_zone
from systems.textures import TextureAtlas
from systems.ray_renderer import RayRenderer

SW, SH = 640, 360
HALF = SH // 2
OUT_DIR = "debug_renders"


def _make(zone_name: str) -> tuple[RayRenderer, object]:
    atlas = TextureAtlas()
    atlas.ensure_all()
    z = load_zone(zone_name)
    r = RayRenderer(z, atlas, sw=SW, sh=SH)
    return r, z


def _save_png(fb: bytes, path: str) -> None:
    surf = pygame.Surface((SW, SH))
    for y in range(SH):
        for x in range(SW):
            off = (y * SW + x) * 3
            surf.set_at((x, y), (fb[off], fb[off + 1], fb[off + 2]))
    pygame.image.save(surf, path)
    print(f"  saved {path}")


def _zbuf_heatmap(zbuf: list[float], path: str) -> None:
    """Render z-buffer as a colour heatmap (close=red, far=blue)."""
    valid = [z for z in zbuf if z > 0 and z == z]
    if not valid:
        return
    zmin, zmax = min(valid), max(valid)
    rng = max(zmax - zmin, 0.01)

    surf = pygame.Surface((SW, 40))
    for x, z in enumerate(zbuf):
        t = max(0.0, min(1.0, (z - zmin) / rng))
        r = int(255 * (1.0 - t))
        g = int(255 * max(0, 1.0 - abs(t - 0.5) * 2))
        b = int(255 * t)
        for y in range(40):
            surf.set_at((x, y), (r, g, b))
    pygame.image.save(surf, path)
    print(f"  saved {path} (z: {zmin:.2f}–{zmax:.2f})")


def _annotate(
    renderer: RayRenderer,
    px: float,
    py: float,
    angle: float,
    label: str,
) -> None:
    """Render a viewpoint, save colour PNG + zbuf heatmap + analysis."""
    renderer.render(px, py, angle)
    fb = bytes(renderer._fb)
    zbuf = list(struct.unpack(f"{SW}d", renderer._zbuf))

    base = os.path.join(OUT_DIR, label)
    _save_png(fb, f"{base}.png")
    _zbuf_heatmap(zbuf, f"{base}_zbuf.png")

    # Per-pixel depth image
    from systems._ray_render import depth_to_grayscale
    depth_fb = bytearray(renderer._fb)  # copy to avoid clobbering
    depth_to_grayscale(depth_fb, renderer._depth_px, SW, SH, 24.0)
    _save_png(bytes(depth_fb), f"{base}_depth.png")

    # Quick stats
    valid_z = [z for z in zbuf if z > 0 and z == z]
    zmin = min(valid_z) if valid_z else 0
    zmax = max(valid_z) if valid_z else 0
    maxlum = max(
        fb[i * 3] + fb[i * 3 + 1] + fb[i * 3 + 2]
        for i in range(SW * SH)
    )

    # Column analysis at center
    center = SW // 2
    transitions = []
    prev_lum = 0
    for y in range(SH):
        off = (y * SW + center) * 3
        lum = fb[off] + fb[off + 1] + fb[off + 2]
        if abs(lum - prev_lum) > 30:
            transitions.append(y)
        prev_lum = lum

    print(
        f"  {label}: z=[{zmin:.2f},{zmax:.2f}] "
        f"maxlum={maxlum} transitions={len(transitions)}"
    )


def main() -> None:
    zone_name = sys.argv[1] if len(sys.argv) > 1 else "showcase"
    os.makedirs(OUT_DIR, exist_ok=True)

    print(f"Rendering {zone_name} at {SW}×{SH} …")
    r, z = _make(zone_name)

    ax, ay = z.anchor
    views = [
        (ax + 0.5, ay + 0.5, math.pi * 1.5, "spawn_north"),
        (ax + 0.5, ay + 0.5, 0.0, "spawn_east"),
        (ax + 0.5, ay + 0.5, math.pi * 0.5, "spawn_south"),
        (ax + 0.5, ay + 0.5, math.pi, "spawn_west"),
        (ax + 0.5, ay - 0.5, math.pi * 1.5, "close_north"),
        (4.5, 7.5, math.pi * 1.5, "inside_counter"),
        (2.5, 7.5, 0.0, "counter_side"),
    ]

    for px, py, angle, label in views:
        _annotate(r, px, py, angle, label)

    # Summary of all zones
    print("\nAll-zone smoke test:")
    atlas = TextureAtlas()
    atlas.ensure_all()
    import time

    for zn in [
        "campsite", "crossroads", "generated", "house_interior",
        "outskirts", "pawn_shop", "playground", "showcase", "test",
        "untitled",
    ]:
        z2 = load_zone(zn)
        r.update_zone(z2, atlas)
        r._is_interior = int(z2.first_person)
        ax2, ay2 = z2.anchor
        t0 = time.perf_counter()
        r.render(ax2 + 0.5, ay2 + 0.5, 0.0)
        dt = (time.perf_counter() - t0) * 1000
        zb = struct.unpack(f"{SW}d", r._zbuf)
        nans = sum(1 for z in zb if z != z)
        print(f"  {zn:20s}: {dt:5.1f}ms NaN={nans}")

    print(f"\nDone — images in {OUT_DIR}/")


if __name__ == "__main__":
    main()
