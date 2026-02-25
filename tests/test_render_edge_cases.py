#!/usr/bin/env python3
"""tests/test_render_edge_cases.py — Edge-case pixel tests for the C renderer.

Validates that extruded floors/ceilings render consistently, that floor/ceiling
step walls appear at height transitions, and that no magenta (or background
bleed) shows through at any camera angle or zone configuration.

Configurations tested:
  1.  Uniform flat zone — no edge artefacts
  2.  Single raised-floor cell — floor step walls visible
  3.  Single lowered-ceiling cell — ceiling step walls visible
  4.  Adjacent cells with many height tiers — no magenta gaps
  5.  Sky-hole (ch >= SKY_THRESHOLD) in interior zone
  6.  Extreme heights (fh near max, ch near min)
  7.  Cardinal + diagonal angle sweep — no magenta in any direction
  8.  Exterior zone (no ceiling) — sky gradient only, no magenta
  9.  Tiny zone (3×3) — boundary handling
  10. Floor + ceiling step in same zone — combined edges
"""

import math
import sys
import os
from pathlib import Path

_root = str(Path(__file__).resolve().parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

os.environ["SDL_VIDEODRIVER"] = "dummy"
import pygame
pygame.init()
pygame.display.set_mode((320, 240))

from core.zones import Zone
from core.tiles import (
    TILE_REGISTRY,
    tile_str_to_int, tile_def, wall_lut,
    rebuild_derived,
)
from engine.textures import TextureAtlas
from engine.ray_renderer import RayRenderer


# ── Harness ───────────────────────────────────────────────────────
PASS = 0
FAIL = 0


def check(label: str, condition: bool, detail: str = ""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        msg = f"  [FAIL] {label}"
        if detail:
            msg += f"  -- {detail}"
        print(msg)


def section(name: str):
    print(f"\n{'=' * 60}")
    print(f"  {name}")
    print(f"{'=' * 60}")


# ── Pixel helpers ─────────────────────────────────────────────────

def has_magenta(px: bytes, threshold: int = 10) -> int:
    """Count near-magenta pixels (R>230, G<30, B>230)."""
    count = 0
    for i in range(0, len(px) - 2, 3):
        r, g, b = px[i], px[i + 1], px[i + 2]
        if r > 230 and g < 30 and b > 230:
            count += 1
    return count


def pixel_variance(px: bytes) -> float:
    """Fraction of pixels that differ from pixel 0."""
    if len(px) < 6:
        return 0.0
    r0, g0, b0 = px[0], px[1], px[2]
    total = len(px) // 3
    diff = sum(
        1 for i in range(0, len(px) - 2, 3)
        if px[i] != r0 or px[i + 1] != g0 or px[i + 2] != b0
    )
    return diff / total


def count_pixel_color(px: bytes, r0: int, g0: int, b0: int, tol: int = 5) -> int:
    """Count pixels close to the given RGB."""
    count = 0
    for i in range(0, len(px) - 2, 3):
        if (abs(px[i] - r0) <= tol
                and abs(px[i + 1] - g0) <= tol
                and abs(px[i + 2] - b0) <= tol):
            count += 1
    return count


def render_snapshot(zone: Zone, cam_x: float, cam_y: float, angle: float,
                    sw: int = 160, sh: int = 90) -> bytes:
    """Create a renderer, render one frame, return raw RGB bytes."""
    atlas = TextureAtlas()
    renderer = RayRenderer(zone, atlas, sw=sw, sh=sh, fov=math.pi / 3.0, dn=1.0)
    surf = renderer.render(cam_x, cam_y, angle)
    return pygame.image.tobytes(surf, "RGB")


def sweep_angles(zone: Zone, cam_x: float, cam_y: float,
                 n_angles: int = 16, sw: int = 160, sh: int = 90) -> int:
    """Render from many angles, return worst magenta count."""
    atlas = TextureAtlas()
    renderer = RayRenderer(zone, atlas, sw=sw, sh=sh, fov=math.pi / 3.0, dn=1.0)
    worst = 0
    for i in range(n_angles):
        angle = (2.0 * math.pi * i) / n_angles
        surf = renderer.render(cam_x, cam_y, angle)
        px = pygame.image.tobytes(surf, "RGB")
        worst = max(worst, has_magenta(px))
    return worst


# ── Zone builder ──────────────────────────────────────────────────

def make_zone(w: int, h: int, *,
              interior: bool = True,
              default_fh: float = 0.0,
              default_ch: float = 1.0,
              floor_tile: str = "floor",
              wall_tile: str = "wall") -> Zone:
    """Build a simple zone with border walls and open interior."""
    # Tiles are auto-bootstrapped on import; just rebuild derived LUTs
    rebuild_derived()

    # Fall back to first available wall / floor tile
    if wall_tile not in TILE_REGISTRY:
        for k, td in TILE_REGISTRY.items():
            if td.wall:
                wall_tile = k
                break
    if floor_tile not in TILE_REGISTRY:
        for k, td in TILE_REGISTRY.items():
            if not td.wall and not td.solid:
                floor_tile = k
                break

    tiles = []
    fh = []
    ch = []
    ll = []
    ft = []
    ct = []
    ftex = []
    rots = []
    for r in range(h):
        t_row, fh_row, ch_row, ll_row = [], [], [], []
        ft_row, ct_row, ftex_row, rot_row = [], [], [], []
        for c in range(w):
            is_wall = (r == 0 or r == h - 1 or c == 0 or c == w - 1)
            t_row.append(wall_tile if is_wall else floor_tile)
            fh_row.append(default_fh)
            ch_row.append(default_ch)
            ll_row.append(1.0)
            ft_row.append("")
            ct_row.append("")
            ftex_row.append(["", "", "", ""])
            rot_row.append(0)
        tiles.append(t_row)
        fh.append(fh_row)
        ch.append(ch_row)
        ll.append(ll_row)
        ft.append(ft_row)
        ct.append(ct_row)
        ftex.append(ftex_row)
        rots.append(rot_row)

    z = Zone(
        name="test_zone",
        width=w,
        height=h,
        anchor=(w / 2.0, h / 2.0),
        tiles=tiles,
        floor_heights=fh,
        ceil_heights=ch,
        light_levels=ll,
        floor_textures=ft,
        ceil_textures=ct,
        face_textures=ftex,
        first_person=interior,
        rotations=rots,
        entities=[],
        portals=[],
    )
    return z


# ══════════════════════════════════════════════════════════════════
# Tiles are auto-loaded by core.tiles._bootstrap()
atlas_global = TextureAtlas()

# =================================================================
section("1. Uniform flat zone — no artefacts")
# =================================================================
z1 = make_zone(8, 8, interior=True, default_fh=0.0, default_ch=1.0)
# Camera in center
px1 = render_snapshot(z1, 4.0, 4.0, 0.0)
check("Flat zone: no magenta", has_magenta(px1) == 0)
check("Flat zone: has content", pixel_variance(px1) > 0.05, f"var={pixel_variance(px1):.3f}")

worst1 = sweep_angles(z1, 4.0, 4.0, n_angles=32)
check("Flat zone: 32-angle sweep no magenta", worst1 == 0, f"worst={worst1}")


# =================================================================
section("2. Single raised-floor cell — step walls visible")
# =================================================================
z2 = make_zone(8, 8, interior=True, default_fh=0.0, default_ch=1.0)
# Raise the floor of cell (4,4) to 0.3
z2.floor_heights[4][4] = 0.3

# Camera next to the raised cell, looking toward it
px2a = render_snapshot(z2, 3.5, 4.5, 0.0)   # looking east toward col 4
check("Raised floor: no magenta (east view)", has_magenta(px2a) == 0)

px2b = render_snapshot(z2, 4.5, 3.5, math.pi / 2)  # looking south toward row 4
check("Raised floor: no magenta (south view)", has_magenta(px2b) == 0)

# The raised floor should change pixels compared to a flat zone
px2_flat = render_snapshot(z1, 3.5, 4.5, 0.0)
diff2 = sum(1 for a, b in zip(px2a, px2_flat) if a != b)
check("Raised floor: pixels differ from flat zone",
      diff2 > 100, f"diff_bytes={diff2}")

worst2 = sweep_angles(z2, 3.5, 4.5, n_angles=16)
check("Raised floor: 16-angle sweep no magenta", worst2 == 0, f"worst={worst2}")


# =================================================================
section("3. Single lowered-ceiling cell — step walls visible")
# =================================================================
z3 = make_zone(8, 8, interior=True, default_fh=0.0, default_ch=1.0)
# Lower ceiling of cell (4,4) to 0.7
z3.ceil_heights[4][4] = 0.7

px3a = render_snapshot(z3, 3.5, 4.5, 0.0)
check("Lowered ceiling: no magenta (east view)", has_magenta(px3a) == 0)

# Verify pixels change compared to uniform
diff3 = sum(1 for a, b in zip(px3a, px2_flat) if a != b)
check("Lowered ceiling: pixels differ from flat",
      diff3 > 50, f"diff_bytes={diff3}")

worst3 = sweep_angles(z3, 4.0, 4.0, n_angles=16)
check("Lowered ceiling: 16-angle sweep no magenta", worst3 == 0, f"worst={worst3}")


# =================================================================
section("4. Many height tiers — no gaps")
# =================================================================
z4 = make_zone(10, 10, interior=True, default_fh=0.0, default_ch=1.0)
# Create a staircase of floor heights
for i in range(1, 7):
    z4.floor_heights[5][i + 1] = i * 0.05  # 0.05, 0.10, ... 0.30

# Also staircase of ceiling heights
for i in range(1, 7):
    z4.ceil_heights[3][i + 1] = 1.0 - i * 0.04  # 0.96, 0.92, ... 0.76

# Camera at the start of the staircase
px4a = render_snapshot(z4, 2.5, 5.5, 0.0)  # looking east along floor stairs
check("Height tiers: no magenta (floor stairs)", has_magenta(px4a) == 0)
check("Height tiers: has variance", pixel_variance(px4a) > 0.05)

px4b = render_snapshot(z4, 2.5, 3.5, 0.0)  # looking east along ceiling stairs
check("Height tiers: no magenta (ceiling stairs)", has_magenta(px4b) == 0)

worst4 = sweep_angles(z4, 5.0, 5.0, n_angles=16)
check("Height tiers: 16-angle sweep no magenta", worst4 == 0, f"worst={worst4}")


# =================================================================
section("5. Sky-hole in interior zone")
# =================================================================
z5 = make_zone(8, 8, interior=True, default_fh=0.0, default_ch=1.0)
# Set cell (4,4) ceiling to sky threshold → open sky
z5.ceil_heights[4][4] = 10.0  # SKY_THRESHOLD

px5a = render_snapshot(z5, 3.5, 4.5, 0.0)  # looking east at sky-hole cell
check("Sky-hole: no magenta", has_magenta(px5a) == 0)

# The sky-hole cell should be visually different from uniform ceiling
px5_ref = render_snapshot(z1, 3.5, 4.5, 0.0)
diff5 = sum(1 for a, b in zip(px5a, px5_ref) if a != b)
check("Sky-hole: pixels differ from closed ceiling",
      diff5 > 50, f"diff_bytes={diff5}")

# Look straight up from inside the sky-hole cell
# Camera in sky-hole cell, very low FOV to see mostly ceiling
px5b = render_snapshot(z5, 4.5, 4.5, 0.0, sw=80, sh=80)
check("Sky-hole from inside: no magenta", has_magenta(px5b) == 0)

worst5 = sweep_angles(z5, 4.5, 4.5, n_angles=16)
check("Sky-hole: 16-angle sweep no magenta", worst5 == 0, f"worst={worst5}")


# =================================================================
section("6. Extreme heights")
# =================================================================
z6 = make_zone(8, 8, interior=True, default_fh=0.0, default_ch=1.0)
# Very high floor
z6.floor_heights[3][4] = 0.45  # close to camera height (0.5)
# Very low ceiling
z6.ceil_heights[5][4] = 0.55   # just above camera height

px6a = render_snapshot(z6, 3.5, 3.5, 0.0)  # looking east at high floor
check("Extreme fh=0.45: no magenta", has_magenta(px6a) == 0)

px6b = render_snapshot(z6, 3.5, 5.5, 0.0)  # looking at low ceiling
check("Extreme ch=0.55: no magenta", has_magenta(px6b) == 0)

worst6 = sweep_angles(z6, 4.0, 4.0, n_angles=16)
check("Extreme heights: 16-angle sweep no magenta", worst6 == 0, f"worst={worst6}")


# =================================================================
section("7. Full 360° angle sweep — flat + varied")
# =================================================================
# Flat
worst7a = sweep_angles(z1, 4.0, 4.0, n_angles=64)
check("Flat zone 64-angle sweep: no magenta", worst7a == 0, f"worst={worst7a}")

# Mixed heights
z7 = make_zone(10, 10, interior=True, default_fh=0.0, default_ch=1.0)
z7.floor_heights[3][3] = 0.2
z7.floor_heights[3][4] = 0.1
z7.ceil_heights[6][3] = 0.8
z7.ceil_heights[6][4] = 0.6
z7.ceil_heights[5][5] = 10.0  # sky hole
worst7b = sweep_angles(z7, 5.0, 5.0, n_angles=64)
check("Mixed heights 64-angle sweep: no magenta", worst7b == 0, f"worst={worst7b}")


# =================================================================
section("8. Exterior zone — sky gradient, no ceiling")
# =================================================================
z8 = make_zone(8, 8, interior=False, default_fh=0.0, default_ch=1.0)
px8 = render_snapshot(z8, 4.0, 4.0, 0.0)
check("Exterior zone: no magenta", has_magenta(px8) == 0)
check("Exterior zone: has sky content", pixel_variance(px8) > 0.05)

worst8 = sweep_angles(z8, 4.0, 4.0, n_angles=32)
check("Exterior zone: 32-angle sweep no magenta", worst8 == 0, f"worst={worst8}")

# Exterior with floor height variation
z8b = make_zone(8, 8, interior=False, default_fh=0.0, default_ch=1.0)
z8b.floor_heights[4][4] = 0.2
worst8b = sweep_angles(z8b, 3.5, 4.5, n_angles=16)
check("Exterior + raised floor: no magenta", worst8b == 0, f"worst={worst8b}")


# =================================================================
section("9. Tiny zone (3×3)")
# =================================================================
z9 = make_zone(3, 3, interior=True, default_fh=0.0, default_ch=1.0)
# Only 1 interior cell
px9 = render_snapshot(z9, 1.5, 1.5, 0.0)
check("3×3 zone: no magenta", has_magenta(px9) == 0)
check("3×3 zone: has content", pixel_variance(px9) > 0.01)

worst9 = sweep_angles(z9, 1.5, 1.5, n_angles=16)
check("3×3 zone: 16-angle sweep no magenta", worst9 == 0, f"worst={worst9}")


# =================================================================
section("10. Combined floor + ceiling steps")
# =================================================================
z10 = make_zone(10, 10, interior=True, default_fh=0.0, default_ch=1.0)
# Floor ramp
z10.floor_heights[5][3] = 0.1
z10.floor_heights[5][4] = 0.2
z10.floor_heights[5][5] = 0.3
# Ceiling ramp (descending)
z10.ceil_heights[5][3] = 0.9
z10.ceil_heights[5][4] = 0.8
z10.ceil_heights[5][5] = 0.7

px10 = render_snapshot(z10, 2.5, 5.5, 0.0)  # looking east along combined ramp
check("Combined steps: no magenta", has_magenta(px10) == 0)
check("Combined steps: has variance", pixel_variance(px10) > 0.05)

# From above the ramp
px10b = render_snapshot(z10, 5.5, 4.5, math.pi / 2)  # looking south
check("Combined steps (south view): no magenta", has_magenta(px10b) == 0)

worst10 = sweep_angles(z10, 5.0, 5.0, n_angles=32)
check("Combined steps: 32-angle sweep no magenta", worst10 == 0, f"worst={worst10}")


# =================================================================
section("11. Background bleed prevention")
# Ensure no dark-grey interior background pixels show through
# in areas that should be floor or ceiling.
# =================================================================
z11 = make_zone(8, 8, interior=True, default_fh=0.0, default_ch=1.0)
# All cells uniform → no gaps in floor or ceiling

# Interior background top is ~(20-35, 22-37, 25-43)
# If ceiling gaps exist, those dark pixels would show through
px11 = render_snapshot(z11, 4.0, 4.0, 0.0, sw=320, sh=180)
dark_count = 0
total = len(px11) // 3
for i in range(0, len(px11) - 2, 3):
    r, g, b = px11[i], px11[i + 1], px11[i + 2]
    # Very dark interior-background-like pixel (excluding legitimate dark tones)
    if r < 30 and g < 30 and b < 30:
        dark_count += 1

# Some dark pixels are expected (fogged distant walls), but they
# shouldn't be more than ~15% for a well-lit uniform interior
dark_pct = dark_count / total * 100
check(f"Background bleed: dark pixels {dark_pct:.1f}% <= 25%",
      dark_pct <= 25.0, f"dark={dark_count}/{total}")


# =================================================================
section("12. Floor step wall visibility")
# Verify that the floor step wall between two adjacent cells with
# different floor heights actually changes rendered pixels.
# =================================================================
z12a = make_zone(8, 8, interior=True, default_fh=0.0, default_ch=1.0)
z12b = make_zone(8, 8, interior=True, default_fh=0.0, default_ch=1.0)
# b has a raised floor section
z12b.floor_heights[4][3] = 0.2
z12b.floor_heights[4][4] = 0.2
z12b.floor_heights[4][5] = 0.2

# Camera looking at the step
cam_x12, cam_y12 = 4.0, 3.0
angle12 = math.pi / 2  # looking south (toward row 4)

px12a = render_snapshot(z12a, cam_x12, cam_y12, angle12)
px12b = render_snapshot(z12b, cam_x12, cam_y12, angle12)

diff12 = sum(1 for a, b in zip(px12a, px12b) if a != b)
diff12_pct = diff12 / len(px12a) * 100
check(f"Floor step visible: {diff12_pct:.1f}% pixel change",
      diff12 > 200, f"diff_bytes={diff12}")
check("Floor step: no magenta", has_magenta(px12b) == 0)


# =================================================================
section("13. Ceiling step wall visibility")
# =================================================================
z13a = make_zone(8, 8, interior=True, default_fh=0.0, default_ch=1.0)
z13b = make_zone(8, 8, interior=True, default_fh=0.0, default_ch=1.0)
# b has a lowered ceiling section
z13b.ceil_heights[4][3] = 0.7
z13b.ceil_heights[4][4] = 0.7
z13b.ceil_heights[4][5] = 0.7

cam_x13, cam_y13 = 4.0, 3.0
angle13 = math.pi / 2  # looking south

px13a = render_snapshot(z13a, cam_x13, cam_y13, angle13)
px13b = render_snapshot(z13b, cam_x13, cam_y13, angle13)

diff13 = sum(1 for a, b in zip(px13a, px13b) if a != b)
diff13_pct = diff13 / len(px13a) * 100
check(f"Ceiling step visible: {diff13_pct:.1f}% pixel change",
      diff13 > 200, f"diff_bytes={diff13}")
check("Ceiling step: no magenta", has_magenta(px13b) == 0)


# =================================================================
section("14. Elevated floor top surface")
# Camera above an elevated cell — the top surface should render.
# =================================================================
z14 = make_zone(8, 8, interior=True, default_fh=0.0, default_ch=1.5)
z14.floor_heights[4][4] = 0.3
z14.floor_heights[4][5] = 0.3

# Standing adjacent, looking down at the elevated cells
px14a = render_snapshot(z14, 3.5, 4.5, 0.0)  # east view
px14_ref = render_snapshot(
    make_zone(8, 8, interior=True, default_fh=0.0, default_ch=1.5),
    3.5, 4.5, 0.0,
)
diff14 = sum(1 for a, b in zip(px14a, px14_ref) if a != b)
check("Elevated floor top: pixels differ from flat",
      diff14 > 50, f"diff_bytes={diff14}")
check("Elevated floor top: no magenta", has_magenta(px14a) == 0)


# ── Depth-buffer helper ──────────────────────────────────────────

import struct as _struct

def get_depth(renderer, x: int, y: int) -> float:
    """Read per-pixel depth (float32) from the renderer's depth buffer."""
    off = (y * renderer.sw + x) * 4
    return _struct.unpack_from('f', renderer._depth_px, off)[0]


def render_with_depth(zone: Zone, cam_x: float, cam_y: float, angle: float,
                      sw: int = 160, sh: int = 90):
    """Render and return (renderer, pixels)."""
    atlas = TextureAtlas()
    renderer = RayRenderer(zone, atlas, sw=sw, sh=sh, fov=math.pi / 3.0, dn=1.0)
    surf = renderer.render(cam_x, cam_y, angle)
    px = pygame.image.tobytes(surf, "RGB")
    return renderer, px


# =================================================================
section("15. Ceiling occlusion — 2-high wall behind 1-high ceiling")
# Stand under ch=1.0, look at a wall whose cell has ch=5.0.
# At pixels ABOVE the ceiling projection line, the depth must NOT
# equal the wall distance — the ceiling must occlude the wall.
# =================================================================

SW15, SH15 = 160, 90
HALF15 = SH15 // 2

z15 = make_zone(10, 10, interior=True, default_fh=0.0, default_ch=1.0)
# East border wall cells: insanely tall ceiling
for r in range(10):
    z15.ceil_heights[r][9] = 5.0

cam15x, cam15y = 5.5, 5.5
angle15 = 0.0   # east

rnd15, px15 = render_with_depth(z15, cam15x, cam15y, angle15, sw=SW15, sh=SH15)

check("Occlusion ch=5: no magenta", has_magenta(px15) == 0)

# The east wall is at x=9.0.  For the center column (straight ahead),
# perp_dist ~ 9.0 - 5.5 = 3.5 tiles.
center_col = SW15 // 2
wall_dist = 9.0 - cam15x   # ~3.5

# Ceiling at ch=1.0 clips: line_h = sh / wall_dist
# clip_y = half - line_h * (1.0 - 0.5) = half - 0.5 * sh / wall_dist
line_h_15 = SH15 / wall_dist
clip_y_15 = int(HALF15 - line_h_15 * (1.0 - 0.5))

# Test pixels well ABOVE the clip line (ceiling territory).
# Their depth should be LESS than the wall distance.
wall_depth_violations = 0
test_rows_above = max(1, clip_y_15 - 5)
for y in range(0, test_rows_above):
    d = get_depth(rnd15, center_col, y)
    if abs(d - wall_dist) < 0.5:
        wall_depth_violations += 1

check(f"Ceiling occlusion: no wall depth above clip line (y<{test_rows_above})",
      wall_depth_violations == 0,
      f"violations={wall_depth_violations}")

# Also check a range of columns, not just center
wide_violations = 0
for x in range(SW15 // 4, 3 * SW15 // 4):
    for y in range(0, max(1, clip_y_15 - 3)):
        d = get_depth(rnd15, x, y)
        if abs(d - wall_dist) < 0.8:
            wide_violations += 1

check("Ceiling occlusion: no wall depth in top band (wide check)",
      wide_violations == 0,
      f"violations={wide_violations}")

worst15 = sweep_angles(z15, cam15x, cam15y, n_angles=32)
check("Ceiling occlusion: 32-angle sweep no magenta",
      worst15 == 0, f"worst={worst15}")


# =================================================================
section("16. Floor occlusion — elevated floor blocks low wall")
# Camera on elevated floor (fh=0.3).  The raised floor between
# camera and the far wall should prevent wall pixels below the
# floor projection line.
# =================================================================

z16 = make_zone(10, 10, interior=True, default_fh=0.0, default_ch=1.0)
for c in range(1, 9):
    z16.floor_heights[5][c] = 0.3   # raised corridor

cam16x, cam16y = 2.5, 5.5
angle16 = 0.0  # east

rnd16, px16 = render_with_depth(z16, cam16x, cam16y, angle16, sw=SW15, sh=SH15)

check("Floor occlusion: no magenta", has_magenta(px16) == 0)

floor_wall_dist16 = 9.0 - cam16x   # ~6.5
line_h_16 = SH15 / floor_wall_dist16
# Floor at 0.3 clips: clip_bot = half + line_h * (0.5 - 0.3) = half + 0.2 * line_h
clip_bot_16 = int(HALF15 + line_h_16 * (0.5 - 0.3))

# Below the clip line: depth should NOT be the wall distance
floor_violations = 0
for y in range(min(SH15 - 1, clip_bot_16 + 5), SH15):
    d = get_depth(rnd16, center_col, y)
    if abs(d - floor_wall_dist16) < 0.8:
        floor_violations += 1

check(f"Floor occlusion: no wall depth below clip line (y>{clip_bot_16 + 5})",
      floor_violations == 0,
      f"violations={floor_violations}")

worst16 = sweep_angles(z16, cam16x, cam16y, n_angles=16)
check("Floor occlusion: 16-angle sweep no magenta",
      worst16 == 0, f"worst={worst16}")


# =================================================================
section("17. Mixed ceil heights — low ceiling corridor into tall room")
# Corridor with ch=0.7 leads to tall room with ch=2.0.
# The 0.7 ceiling clips the tall room's wall.
# =================================================================

z17 = make_zone(12, 12, interior=True, default_fh=0.0, default_ch=2.0)
for c in range(1, 6):
    z17.ceil_heights[6][c] = 0.7

cam17x, cam17y = 2.5, 6.5
angle17 = 0.0

rnd17, px17 = render_with_depth(z17, cam17x, cam17y, angle17, sw=SW15, sh=SH15)
check("Mixed ceiling corridor: no magenta", has_magenta(px17) == 0)

# The east border wall is at x=11.0, distance ~ 8.5
wall_dist_17 = 11.0 - cam17x
line_h_17 = SH15 / wall_dist_17
# Corridor ceiling at 0.7 clips: clip_y = half - lh * (0.7 - 0.5)
clip_y_17 = int(HALF15 - line_h_17 * (0.7 - 0.5))

violations_17 = 0
for y in range(0, max(1, clip_y_17 - 3)):
    d = get_depth(rnd17, center_col, y)
    if abs(d - wall_dist_17) < 1.0:
        violations_17 += 1

check(f"Mixed corridor: no wall depth above ceil clip (y<{max(1, clip_y_17 - 3)})",
      violations_17 == 0,
      f"violations={violations_17}")

worst17 = sweep_angles(z17, cam17x, cam17y, n_angles=16)
check("Mixed ceiling corridor: 16-angle sweep no magenta",
      worst17 == 0, f"worst={worst17}")


# =================================================================
section("18. Raised-floor corridor blocks distant wall bottom")
# =================================================================

z18 = make_zone(12, 12, interior=True, default_fh=0.0, default_ch=1.0)
for c in range(1, 6):
    z18.floor_heights[6][c] = 0.25

cam18x, cam18y = 2.5, 6.5
angle18 = 0.0

rnd18, px18 = render_with_depth(z18, cam18x, cam18y, angle18, sw=SW15, sh=SH15)
check("Raised floor corridor: no magenta", has_magenta(px18) == 0)

wall_dist_18 = 11.0 - cam18x
line_h_18 = SH15 / wall_dist_18
clip_bot_18 = int(HALF15 + line_h_18 * (0.5 - 0.25))

floor_viol_18 = 0
for y in range(min(SH15 - 1, clip_bot_18 + 5), SH15):
    d = get_depth(rnd18, center_col, y)
    if abs(d - wall_dist_18) < 1.0:
        floor_viol_18 += 1

check(f"Floor corridor clip: no wall depth below floor clip",
      floor_viol_18 == 0,
      f"violations={floor_viol_18}")

worst18 = sweep_angles(z18, cam18x, cam18y, n_angles=16)
check("Raised floor corridor: 16-angle sweep no magenta",
      worst18 == 0, f"worst={worst18}")


# =================================================================
section("19. Extreme occlusion — very low ceiling + very tall wall")
# Camera under ch=0.6, wall with ch=5.0.
# Wall MUST NOT render above the 0.6 ceiling line.
# =================================================================

z19 = make_zone(10, 10, interior=True, default_fh=0.0, default_ch=0.6)
for r in range(10):
    z19.ceil_heights[r][9] = 5.0

cam19x, cam19y = 5.5, 5.5
angle19 = 0.0

rnd19, px19 = render_with_depth(z19, cam19x, cam19y, angle19, sw=SW15, sh=SH15)
check("Extreme occlusion: no magenta", has_magenta(px19) == 0)

wall_dist_19 = 9.0 - cam19x
line_h_19 = SH15 / wall_dist_19
# ch=0.6 clips: clip_y = half - lh * (0.6 - 0.5)
clip_y_19 = int(HALF15 - line_h_19 * (0.6 - 0.5))

violations_19 = 0
for x in range(SW15 // 4, 3 * SW15 // 4):
    for y in range(0, max(1, clip_y_19 - 3)):
        d = get_depth(rnd19, x, y)
        if abs(d - wall_dist_19) < 0.8:
            violations_19 += 1

check(f"Extreme occlusion: no wall depth above ceil clip (wide)",
      violations_19 == 0,
      f"violations={violations_19}")

worst19 = sweep_angles(z19, cam19x, cam19y, n_angles=32)
check("Extreme occlusion: 32-angle sweep no magenta",
      worst19 == 0, f"worst={worst19}")


# =================================================================
section("20. Bidirectional — camera in tall room looking into low room")
# =================================================================

z20 = make_zone(12, 12, interior=True, default_fh=0.0, default_ch=2.0)
for r in range(4, 9):
    for c in range(7, 11):
        z20.ceil_heights[r][c] = 0.7

cam20x, cam20y = 5.5, 6.5
angle20 = 0.0

rnd20, px20 = render_with_depth(z20, cam20x, cam20y, angle20, sw=SW15, sh=SH15)
check("Tall->low room: no magenta", has_magenta(px20) == 0)
check("Tall->low room: has content", pixel_variance(px20) > 0.05)

worst20 = sweep_angles(z20, cam20x, cam20y, n_angles=16)
check("Tall->low room: 16-angle sweep no magenta",
      worst20 == 0, f"worst={worst20}")


# =================================================================
#  Summary
# =================================================================
print(f"\n{'=' * 60}")
print(f"  RESULTS: {PASS} passed, {FAIL} failed")
print(f"{'=' * 60}")
sys.exit(1 if FAIL > 0 else 0)
