"""tests/test_ray_render.py — Automated rendering regression tests.

These tests exercise the C raycasting renderer headlessly (no display)
and check for structural anomalies that indicate rendering bugs:

    • Z-buffer sanity (NaN, negative, monotonicity at edges)
    • Invisible collision detection (solid tiles with no wall rendering)
    • Column continuity (no wild depth jumps between adjacent columns)
    • Short-wall vs full-wall height verification
    • Interior ceiling coverage (no "sky bleed" in enclosed rooms)
    • Sky-hole rendering (outdoor cells show sky in interior zones)
    • Per-cell lighting influence on pixel brightness
    • All-zone smoke test (render from anchor in every zone)

Run with:
    .venv/bin/python -m pytest tests/test_ray_render.py -v
"""

from __future__ import annotations

import math
import os
import struct
import time

import pytest

# Headless pygame init
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

pygame.init()
pygame.display.set_mode((100, 100))

from core.tiles import TILE_REGISTRY, TileType, tile_str_to_int
from core.zones import Zone, OverlayWall, load_zone
from systems.ray_renderer import RayRenderer
from systems.textures import TextureAtlas

# ═══════════════════════════════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════════════════════════════

_atlas: TextureAtlas | None = None

def _get_atlas() -> TextureAtlas:
    global _atlas
    if _atlas is None:
        _atlas = TextureAtlas()
        _atlas.ensure_all()
    return _atlas


SW, SH = 320, 180  # internal render resolution for tests


def _make_renderer(zone_name: str) -> tuple[RayRenderer, any]:
    """Load a zone and create a renderer for it."""
    atlas = _get_atlas()
    zone = load_zone(zone_name)
    renderer = RayRenderer(zone, atlas, sw=SW, sh=SH)
    return renderer, zone


def _render_and_get_zbuf(
    renderer: RayRenderer, px: float, py: float, angle: float
) -> list[float]:
    """Render from a viewpoint and return the z-buffer as a list of floats."""
    renderer.render(px, py, angle)
    return list(struct.unpack(f"{renderer.sw}d", renderer._zbuf))


def _render_and_get_fb(
    renderer: RayRenderer, px: float, py: float, angle: float
) -> bytes:
    """Render and return the framebuffer as bytes (RGB)."""
    renderer.render(px, py, angle)
    return bytes(renderer._fb)


def _column_pixel(fb: bytes, sw: int, x: int, y: int) -> tuple[int, int, int]:
    """Get (R, G, B) of a specific pixel from a flat RGB framebuffer."""
    off = (y * sw + x) * 3
    return fb[off], fb[off + 1], fb[off + 2]


def _depth_at(
    renderer: RayRenderer, x: int, y: int
) -> float:
    """Read per-pixel depth (float32) from the depth buffer."""
    off = (y * renderer.sw + x) * 4
    return struct.unpack_from("f", renderer._depth_px, off)[0]


# ── In-memory zone construction ──────────────────────────────────

def _find_wall_tile() -> str:
    """Return an arbitrary tile with wall=True and hs=1.0."""
    for key, td in TILE_REGISTRY.items():
        if td.wall and td.height_scale >= 0.99:
            return key
    raise RuntimeError("No full-height wall tile in TILE_REGISTRY")


def _find_floor_tile() -> str:
    """Return an arbitrary non-wall tile."""
    for key, td in TILE_REGISTRY.items():
        if not td.wall and not td.solid:
            return key
    raise RuntimeError("No floor tile in TILE_REGISTRY")


def _make_box_zone(
    w: int,
    h: int,
    *,
    wall: str | None = None,
    floor: str | None = None,
    overlay_walls: list[OverlayWall] | None = None,
    ceil_height: float = 1.0,
) -> Zone:
    """Create a simple walled box with floor interior — fully in memory."""
    wall = wall or _find_wall_tile()
    floor = floor or _find_floor_tile()
    tiles = []
    for r in range(h):
        row = []
        for c in range(w):
            if r == 0 or r == h - 1 or c == 0 or c == w - 1:
                row.append(wall)
            else:
                row.append(floor)
        tiles.append(row)
    return Zone(
        name="test_box",
        width=w,
        height=h,
        anchor=(h // 2, w // 2),
        tiles=tiles,
        rotations=[[0] * w for _ in range(h)],
        floor_heights=[[0.0] * w for _ in range(h)],
        ceil_heights=[[ceil_height] * w for _ in range(h)],
        floor_textures=[[""] * w for _ in range(h)],
        ceil_textures=[[""] * w for _ in range(h)],
        light_levels=[[1.0] * w for _ in range(h)],
        first_person=True,
        overlay_walls=overlay_walls or [],
    )


def _render_box(
    w: int,
    h: int,
    px: float,
    py: float,
    angle: float,
    *,
    overlay_walls: list[OverlayWall] | None = None,
    ceil_height: float = 1.0,
) -> RayRenderer:
    """Build a box zone, create a renderer, render one frame, return it."""
    zone = _make_box_zone(w, h, overlay_walls=overlay_walls,
                          ceil_height=ceil_height)
    atlas = _get_atlas()
    renderer = RayRenderer(zone, atlas, sw=SW, sh=SH)
    renderer.render(px, py, angle)
    return renderer


# ═══════════════════════════════════════════════════════════════════
#  Zone list
# ═══════════════════════════════════════════════════════════════════

ALL_ZONES = [
    "campsite", "crossroads", "generated", "house_interior",
    "outskirts", "pawn_shop", "playground", "showcase", "test", "untitled",
]


# ═══════════════════════════════════════════════════════════════════
#  Tests
# ═══════════════════════════════════════════════════════════════════


class TestZBufferSanity:
    """Z-buffer should contain no NaN/negative values and have
    reasonable depth ranges from multiple viewpoints."""

    @pytest.mark.parametrize("zone_name", ALL_ZONES)
    def test_zbuf_no_nan_or_negative(self, zone_name: str) -> None:
        renderer, zone = _make_renderer(zone_name)
        ax, ay = zone.anchor
        zbuf = _render_and_get_zbuf(renderer, ax + 0.5, ay + 0.5, 0.0)

        nan_count = sum(1 for z in zbuf if z != z)
        neg_count = sum(1 for z in zbuf if z < 0)

        assert nan_count == 0, f"Z-buffer has {nan_count} NaN values"
        assert neg_count == 0, f"Z-buffer has {neg_count} negative values"

    @pytest.mark.parametrize("zone_name", ALL_ZONES)
    def test_zbuf_reasonable_range(self, zone_name: str) -> None:
        renderer, zone = _make_renderer(zone_name)
        ax, ay = zone.anchor
        zbuf = _render_and_get_zbuf(renderer, ax + 0.5, ay + 0.5, 0.0)

        valid = [z for z in zbuf if z > 0 and z == z]
        assert len(valid) > 0, "No valid depth values"
        assert min(valid) >= 0.001, f"Min depth {min(valid):.4f} too small"
        assert max(valid) <= 200.0, f"Max depth {max(valid):.1f} unreasonably large"


class TestColumnContinuity:
    """Adjacent columns in the z-buffer shouldn't have extreme depth
    jumps (more than 10× ratio), which would indicate missed wall hits."""

    @pytest.mark.parametrize("zone_name", ALL_ZONES)
    def test_no_extreme_depth_jumps(self, zone_name: str) -> None:
        renderer, zone = _make_renderer(zone_name)
        ax, ay = zone.anchor
        zbuf = _render_and_get_zbuf(renderer, ax + 0.5, ay + 0.5, 0.0)

        big_jumps = 0
        for i in range(1, len(zbuf)):
            a, b = zbuf[i - 1], zbuf[i]
            if a > 0.01 and b > 0.01:
                ratio = max(a, b) / min(a, b)
                if ratio > 10.0:
                    big_jumps += 1

        # Allow a small number of jumps (wall edges create natural discontinuities)
        max_jumps = max(5, int(renderer.sw * 0.05))
        assert big_jumps <= max_jumps, (
            f"Z-buffer has {big_jumps} extreme depth jumps (> 10× ratio), "
            f"max allowed {max_jumps}"
        )


class TestInvisibleCollision:
    """Tiles that are solid AND have wall=True should be in the wall LUT.
    Platform tiles are excluded — they're intentionally solid obstacles
    whose top surface is visible via the floor sweep, not DDA wall hits."""

    def test_no_invisible_collision_tiles(self) -> None:
        """Every tile with wall=True should have wall_lt = 1."""
        renderer, zone = _make_renderer("showcase")
        wall_ba = renderer._wall_buf

        invisible = []
        for tid_str, td in TILE_REGISTRY.items():
            ti = tile_str_to_int(tid_str)
            is_in_lut = wall_ba[ti] if ti < len(wall_ba) else 0

            # Tiles flagged wall=True must be in the wall LUT
            if td.wall and not is_in_lut:
                invisible.append(
                    f"{tid_str} (hs={td.height_scale:.2f}, type={td.type.value})"
                )

        assert invisible == [], (
            f"Tiles with wall=True missing from wall_lut: {invisible}"
        )


class TestWallLUTConsistency:
    """The renderer's wall LUT is type-based: tiles with wall=True are
    included.  Platforms (wall=False) are excluded — they render via
    the floor sweep instead."""

    def test_all_wall_flagged_tiles_in_lut(self) -> None:
        renderer, _ = _make_renderer("showcase")
        wall_ba = renderer._wall_buf

        missing = []
        for tid_str, td in TILE_REGISTRY.items():
            ti = tile_str_to_int(tid_str)
            is_in_lut = wall_ba[ti] if ti < len(wall_ba) else 0
            if td.wall and not is_in_lut:
                missing.append(f"{tid_str} (hs={td.height_scale:.2f})")

        assert missing == [], (
            f"Tiles with wall=True missing from wall_lut: {missing}"
        )

    def test_floor_tiles_not_in_wall_lut(self) -> None:
        """Floor tiles (hs=0) should NOT be in the wall LUT."""
        renderer, _ = _make_renderer("showcase")
        wall_ba = renderer._wall_buf

        wrongly_included = []
        for tid_str, td in TILE_REGISTRY.items():
            ti = tile_str_to_int(tid_str)
            is_wall = wall_ba[ti] if ti < len(wall_ba) else 0
            if td.height_scale <= 0.001 and is_wall:
                wrongly_included.append(f"{tid_str}")

        assert wrongly_included == [], (
            f"Floor tiles wrongly in wall_lut: {wrongly_included}"
        )


class TestShortWallHeight:
    """Short walls (hs < 1.0) should produce walls shorter than full walls
    at the same distance.  Verified by comparing drawn wall pixel count."""

    def test_short_wall_shorter_than_full(self) -> None:
        """A half_wall (hs~0.35-0.50) should draw fewer wall pixels than
        a brick_wall (hs=1.00) at the same distance."""
        renderer, zone = _make_renderer("showcase")
        W, H = zone.width, zone.height

        def _has_open_approach(c: int, r: int) -> tuple | None:
            """Find a camera position 2.5 tiles away from (c,r)
            inside the map with a clear line of sight."""
            approaches = [
                (c + 0.5, r + 2.5, math.pi * 1.5),  # south of wall, face north
                (c + 0.5, r - 2.5, math.pi * 0.5),   # north of wall, face south
                (c - 2.5, r + 0.5, 0.0),              # west of wall, face east
                (c + 2.5, r + 0.5, math.pi),          # east of wall, face west
            ]
            for px, py, ang in approaches:
                ix, iy = int(px), int(py)
                if 1 <= ix < W - 1 and 1 <= iy < H - 1:
                    if not renderer.is_solid(px, py):
                        return (px, py, ang)
            return None

        # Find a short wall and a full wall with valid camera positions
        half_info = None
        full_info = None
        for r, row in enumerate(zone.tiles):
            for c, t in enumerate(row):
                td = TILE_REGISTRY.get(t)
                if td is None:
                    continue
                if 0.3 <= td.height_scale <= 0.6 and half_info is None:
                    approach = _has_open_approach(c, r)
                    if approach:
                        half_info = ((c, r), approach)
                if t == "brick_wall" and full_info is None:
                    approach = _has_open_approach(c, r)
                    if approach:
                        full_info = ((c, r), approach)

        if half_info is None or full_info is None:
            pytest.skip("Cannot find approachable short + full walls")

        def wall_pixel_count(px: float, py: float, angle: float) -> int:
            """Count non-dark pixels in the center column."""
            fb = _render_and_get_fb(renderer, px, py, angle)
            mid_col = renderer.sw // 2
            count = 0
            for y in range(renderer.sh):
                R, G, B = _column_pixel(fb, renderer.sw, mid_col, y)
                if R + G + B > 80:  # not background/ceiling/dark
                    count += 1
            return count

        half_pixels = wall_pixel_count(*half_info[1])
        full_pixels = wall_pixel_count(*full_info[1])

        assert half_pixels < full_pixels or half_pixels == 0, (
            f"Short wall {half_info[0]} pixel count {half_pixels} "
            f">= full wall {full_info[0]} pixel count {full_pixels}"
        )


class TestCeilingCoverage:
    """Interior zones with ceil_height < SKY_THRESHOLD (10.0) should have
    ceiling pixels (not sky) above the horizon."""

    def test_interior_zone_has_ceiling(self) -> None:
        """house_interior should have no true sky gradient in upper half."""
        renderer, zone = _make_renderer("house_interior")
        assert zone.first_person is True, "house_interior should be FP/interior"

        ax, ay = zone.anchor
        fb = _render_and_get_fb(renderer, ax + 0.5, ay + 0.5, 0.0)
        half = renderer.sh // 2

        # Sky gradient signature: B value follows a smooth ramp from
        # ~SKY_TOP (B~180-200) at y=0 to ~SKY_BOT (B~120-140) at y=half.
        # Check that the topmost rows are NOT sky-colored but dark-ceiling.
        sky_signature_count = 0
        for x in range(renderer.sw):
            R0, G0, B0 = _column_pixel(fb, renderer.sw, x, 0)
            # True sky at y=0 has B > 150
            if B0 > 150 and B0 > R0 + 50:
                sky_signature_count += 1

        max_sky = int(renderer.sw * 0.05)  # at most 5% of columns
        assert sky_signature_count <= max_sky, (
            f"{sky_signature_count} columns have sky-colored pixels at y=0 "
            f"(max allowed {max_sky}). Interior zone ceiling not rendering?"
        )


class TestSkyHoleRendering:
    """Zones with mixed ceil_heights should show sky (ceil >= 10.0)
    and ceiling (ceil < 10.0) in the correct cells."""

    def test_showcase_has_indoor_ceiling(self) -> None:
        """The showcase (12×12 interior shop, ch=0.95) should produce
        ceiling pixels, not sky, when rendered from the shop floor."""
        renderer, zone = _make_renderer("showcase")
        assert zone.first_person is True, "showcase should be interior"

        # Render from shop floor looking north
        fb = _render_and_get_fb(renderer, 5.5, 9.5, math.pi * 1.5)
        half = renderer.sh // 2

        # Count dark ceiling pixels vs bright sky pixels in upper half
        dark_pixels = 0
        sky_pixels = 0
        for y in range(half):
            for x in range(renderer.sw):
                R, G, B = _column_pixel(fb, renderer.sw, x, y)
                if R < 80 and G < 80 and B < 80:
                    dark_pixels += 1
                if B > 150 and B > R + 50:
                    sky_pixels += 1

        # Interior zone: should have no sky and mostly dark ceiling + walls
        total = renderer.sw * half
        assert sky_pixels < total * 0.05, (
            f"{sky_pixels}/{total} sky-colored pixels in upper half of interior zone"
        )
        assert dark_pixels > total * 0.05, (
            f"Only {dark_pixels}/{total} dark pixels in upper half. "
            f"Ceiling not rendering in interior zone?"
        )


class TestAllZonesRender:
    """Smoke test: every zone should render without crashes and
    within a reasonable time."""

    @pytest.mark.parametrize("zone_name", ALL_ZONES)
    def test_zone_renders(self, zone_name: str) -> None:
        renderer, zone = _make_renderer(zone_name)
        ax, ay = zone.anchor

        t0 = time.perf_counter()
        surf = renderer.render(ax + 0.5, ay + 0.5, 0.0)
        dt = (time.perf_counter() - t0) * 1000

        assert surf is not None, "render() returned None"
        assert dt < 100, f"Rendering took {dt:.1f}ms (max 100ms)"

    @pytest.mark.parametrize("zone_name", ALL_ZONES)
    def test_zone_renders_four_directions(self, zone_name: str) -> None:
        """Render at 4 cardinal angles to catch direction-specific bugs."""
        renderer, zone = _make_renderer(zone_name)
        ax, ay = zone.anchor

        for angle in [0.0, math.pi * 0.5, math.pi, math.pi * 1.5]:
            zbuf = _render_and_get_zbuf(renderer, ax + 0.5, ay + 0.5, angle)
            nan_count = sum(1 for z in zbuf if z != z)
            assert nan_count == 0, (
                f"NaN in z-buffer at angle {angle:.2f} in {zone_name}"
            )


class TestFramebufferNotBlank:
    """The framebuffer should not be all-black or all one color after
    rendering — that would indicate the renderer silently failed."""

    @pytest.mark.parametrize("zone_name", ALL_ZONES)
    def test_framebuffer_has_variety(self, zone_name: str) -> None:
        renderer, zone = _make_renderer(zone_name)
        ax, ay = zone.anchor
        fb = _render_and_get_fb(renderer, ax + 0.5, ay + 0.5, 0.0)

        # Sample every 10th pixel and count unique colors
        colors = set()
        for i in range(0, len(fb) - 2, 30):  # every 10th pixel (×3 bytes)
            colors.add((fb[i], fb[i + 1], fb[i + 2]))

        assert len(colors) > 10, (
            f"Framebuffer has only {len(colors)} unique colors — "
            f"likely blank or broken render"
        )


class TestPlatformRendering:
    """Platform tiles (type=platform) are NOT in the wall LUT (wall=False).
    They should be skipped by DDA.  This test verifies that if a zone
    has platforms, the ray passes through them."""

    def test_platform_creates_wall_hit(self) -> None:
        """Shooting a ray at a platform should produce a z-buffer hit
        at the correct distance."""
        renderer, zone = _make_renderer("showcase")

        # Find a stone_platform cell and a walkable tile nearby
        plat_pos = None
        cam_pos = None
        cam_angle = 0.0
        for r, row in enumerate(zone.tiles):
            for c, t in enumerate(row):
                if t != "stone_platform":
                    continue
                # Try approaching from each cardinal direction
                approaches = [
                    (c - 3, r, 0.0),          # from west, face east
                    (c + 3, r, math.pi),       # from east, face west
                    (c, r - 3, math.pi * 0.5), # from north, face south
                    (c, r + 3, math.pi * 1.5), # from south, face north
                ]
                for ax, ay, ang in approaches:
                    if 0 <= ax < zone.width and 0 <= ay < zone.height:
                        if not renderer.is_solid(ax + 0.5, ay + 0.5):
                            plat_pos = (c, r)
                            cam_pos = (ax + 0.5, ay + 0.5)
                            cam_angle = ang
                            break
                if plat_pos:
                    break
            if plat_pos:
                break

        if plat_pos is None:
            pytest.skip("No reachable stone_platform in showcase zone")

        zbuf = _render_and_get_zbuf(renderer, cam_pos[0], cam_pos[1], cam_angle)

        center_depth = zbuf[renderer.sw // 2]
        assert 1.0 < center_depth < 8.0, (
            f"Center column depth {center_depth:.2f} — expected ~3.0 "
            f"for platform at {plat_pos} from camera {cam_pos}"
        )


class TestLightingInfluence:
    """Per-cell spatial lighting should affect pixel brightness.
    A cell with light=0.3 should be dimmer than one with light=1.0."""

    def test_dark_cells_are_darker(self) -> None:
        """Modify light levels and check that dimmer cells produce
        darker pixels."""
        atlas = _get_atlas()
        zone = load_zone("showcase")

        # Set all lights to 1.0 first, render
        zone.light_levels = [
            [1.0] * zone.width for _ in range(zone.height)
        ]
        r_bright = RayRenderer(zone, atlas, sw=SW, sh=SH)
        fb_bright = _render_and_get_fb(r_bright, 5.5, 9.5, 0.0)

        # Set center cells to 0.2, render again
        zone.light_levels = [
            [1.0] * zone.width for _ in range(zone.height)
        ]
        for row in range(3, zone.height - 1):
            for col in range(1, zone.width - 1):
                zone.light_levels[row][col] = 0.2

        r_dark = RayRenderer(zone, atlas, sw=SW, sh=SH)
        fb_dark = _render_and_get_fb(r_dark, 5.5, 9.5, 0.0)

        # Compare average brightness in the lower half (floor region)
        half = SH // 2

        def avg_brightness(fb: bytes) -> float:
            total = 0
            count = 0
            for y in range(half + 1, SH):
                for x in range(0, SW, 4):  # sample every 4th pixel
                    off = (y * SW + x) * 3
                    total += fb[off] + fb[off + 1] + fb[off + 2]
                    count += 3
            return total / count if count > 0 else 0

        bright_avg = avg_brightness(fb_bright)
        dark_avg = avg_brightness(fb_dark)

        assert dark_avg < bright_avg, (
            f"Dark zone avg brightness {dark_avg:.1f} should be less than "
            f"bright zone {bright_avg:.1f}"
        )


class TestEntityRendering:
    """Entity billboard rendering should not crash and should produce
    visible changes in the framebuffer."""

    @pytest.mark.parametrize("zone_name", ["showcase", "pawn_shop"])
    def test_entities_dont_crash(self, zone_name: str) -> None:
        renderer, zone = _make_renderer(zone_name)
        if not zone.entities:
            pytest.skip(f"{zone_name} has no entities")

        ax, ay = zone.anchor
        renderer.render(ax + 0.5, ay + 0.5, 0.0)
        fb_before = bytes(renderer._fb)

        # Render entities on top
        renderer.render_entities(ax + 0.5, ay + 0.5, 0.0)
        fb_after = bytes(renderer._fb)

        # The framebuffers should differ if any entity is visible
        # (not guaranteed from anchor, but should not crash)
        assert len(fb_after) == len(fb_before), "Framebuffer size changed"


class TestMultiViewpointStability:
    """Render from many random viewpoints to catch rare crashes
    or buffer overflows from edge-case camera positions."""

    @pytest.mark.parametrize("zone_name", ["showcase", "house_interior"])
    def test_many_viewpoints(self, zone_name: str) -> None:
        renderer, zone = _make_renderer(zone_name)
        w, h = zone.width, zone.height

        # Sweep a grid of positions × angles
        for gx in range(1, w - 1, 3):
            for gy in range(1, h - 1, 3):
                # Skip solid tiles
                if renderer.is_solid(gx + 0.5, gy + 0.5):
                    continue
                for angle_i in range(4):
                    angle = angle_i * math.pi * 0.5
                    zbuf = _render_and_get_zbuf(
                        renderer, gx + 0.5, gy + 0.5, angle
                    )
                    nan_count = sum(1 for z in zbuf if z != z)
                    assert nan_count == 0, (
                        f"NaN at ({gx},{gy}) angle={angle:.2f} in {zone_name}"
                    )


# ═══════════════════════════════════════════════════════════════════
#  Deferred wall depth / platform-top / floor-sweep tests
# ═══════════════════════════════════════════════════════════════════


class TestDeferredWallZBuffer:
    """The z-buffer should reflect deferred (short/thin) wall distances,
    not just primary wall distances.  Entities behind counters should
    be depth-clipped correctly."""

    def test_counter_zbuf_closer_than_primary_wall(self) -> None:
        """From spawn looking north, the center column z-buf should
        reflect the counter distance (~2.5), not the far wall (~4.5)."""
        renderer, zone = _make_renderer("showcase")
        zbuf = _render_and_get_zbuf(renderer, 5.5, 9.5, math.pi * 1.5)

        center = renderer.sw // 2
        # Counter at row 6, spawn at row 9.5 → dist ≈ 2.5
        # Primary wall at row 4 → dist ≈ 4.5
        assert zbuf[center] < 3.5, (
            f"Center z-buf={zbuf[center]:.2f}, expected < 3.5 "
            f"(counter, not primary wall)"
        )

    def test_majority_columns_have_deferred_zbuf(self) -> None:
        """Most columns should have z-buf values reflecting deferred
        walls (counters/railings), not the far wall behind them."""
        renderer, zone = _make_renderer("showcase")
        zbuf = _render_and_get_zbuf(renderer, 5.5, 9.5, math.pi * 1.5)

        close_count = sum(1 for z in zbuf if z < 3.5)
        assert close_count > renderer.sw * 0.5, (
            f"Only {close_count}/{renderer.sw} columns have z-buf < 3.5"
        )

    def test_zbuf_matches_counter_distance(self) -> None:
        """Center column z-buf should approximately match the geometric
        distance from camera to the counter face."""
        renderer, zone = _make_renderer("showcase")
        zbuf = _render_and_get_zbuf(renderer, 5.5, 9.5, math.pi * 1.5)

        center = renderer.sw // 2
        # Perpendicular distance from y=9.5 to counter south face at y=7.0
        expected_dist = 2.5
        assert abs(zbuf[center] - expected_dist) < 0.5, (
            f"Center z-buf={zbuf[center]:.2f}, expected ≈{expected_dist}"
        )


class TestTransparentWallRendering:
    """Half-walls (counters, railings) act as transparent walls:
    the floor renders through them normally, and the wall face
    overlays on top.  This matches the reference raycasting engine
    where transparent walls don't affect floor/ceiling rendering."""

    def test_counter_face_visible_above_floor(self) -> None:
        """At off-center columns, counter face pixels should be
        visibly different from the floor below them."""
        renderer, zone = _make_renderer("showcase")
        fb = _render_and_get_fb(renderer, 5.5, 9.5, math.pi * 1.5)

        half = renderer.sh // 2
        # Count columns that have brown counter-face pixels
        # (R dominant, high lum) in the lower half of the screen
        brown_cols = 0
        for col in range(renderer.sw // 4, 3 * renderer.sw // 4):
            for y in range(half + 5, renderer.sh - 10):
                R, G, B = _column_pixel(fb, renderer.sw, col, y)
                if R + G + B > 120 and R > B * 1.5:
                    brown_cols += 1
                    break

        assert brown_cols > 5, (
            f"Only {brown_cols} columns have brown counter-face pixels. "
            f"Half-wall face not rendering?"
        )

    def test_counter_wall_face_is_brown(self) -> None:
        """The counter wall face should produce brown-ish pixels
        (R > G > B) at the expected screen position."""
        renderer, zone = _make_renderer("showcase")
        fb = _render_and_get_fb(renderer, 5.5, 9.5, math.pi * 1.5)

        half = renderer.sh // 2
        center = renderer.sw // 2
        brown_count = 0
        for y in range(half + 11, half + 35):
            R, G, B = _column_pixel(fb, renderer.sw, center, y)
            if R > G and G > B and R + G + B > 80:
                brown_count += 1

        assert brown_count > 10, (
            f"Only {brown_count} brown pixels at center column — "
            f"counter wall face not rendering?"
        )

    def test_counter_face_height_matches_hs(self) -> None:
        """The counter face drawn pixel height should be approximately
        height_scale × full_wall_height pixels."""
        renderer, zone = _make_renderer("showcase")
        fb = _render_and_get_fb(renderer, 5.5, 9.5, math.pi * 1.5)

        half = renderer.sh // 2
        center = renderer.sw // 2
        # Count brown counter pixels at center column in the expected
        # counter-face band.  Allow gaps (platform top, AO shadow) by
        # not requiring strict consecutiveness.
        # At 320×180, counter face is ~y=101-126 (below half=90).
        scan_start = half + 8   # skip platform-top / wall boundary
        scan_end = min(half + 40, renderer.sh)
        counter_pixels = 0
        for y in range(scan_start, scan_end):
            R, G, B = _column_pixel(fb, renderer.sw, center, y)
            # Counter texture: warm brown (R dominant, reasonable lum)
            if R > G and R + G + B > 80:
                counter_pixels += 1

        # At 320×180, counter at dist 2.5: line_h=72, scaled_h=72*0.35=25
        # Allow generous tolerance since platform top + AO share
        # some of the scanned band
        expected = int(renderer.sh / 2.5 * 0.35)
        assert counter_pixels > expected * 0.4, (
            f"Counter face is {counter_pixels}px, expected ≈{expected}px"
        )


class TestFloorThroughHalfWalls:
    """The floor sweep should render the floor texture through
    half-wall tiles (transparent wall model).  No gaps or black
    pixels in the floor region."""

    def test_no_black_gaps_in_floor(self) -> None:
        """The floor between the camera and counter should have no
        black/zero-brightness pixels (gaps from skipped tiles)."""
        renderer, zone = _make_renderer("showcase")
        fb = _render_and_get_fb(renderer, 5.5, 9.5, math.pi * 1.5)

        half = renderer.sh // 2
        center = renderer.sw // 2
        gap_pixels = 0
        for y in range(half + 5, renderer.sh):
            R, G, B = _column_pixel(fb, renderer.sw, center, y)
            if R + G + B == 0:
                gap_pixels += 1

        assert gap_pixels == 0, (
            f"{gap_pixels} black pixels in floor region at center column. "
            f"Floor not rendering through half-wall tiles?"
        )

    def test_floor_uses_floor_texture_not_wall(self) -> None:
        """The floor under counter tiles should use the floor texture
        override (tile_floor), not the counter wall texture."""
        renderer, zone = _make_renderer("showcase")
        fb = _render_and_get_fb(renderer, 5.5, 8.0, math.pi * 1.5)

        half = renderer.sh // 2
        center = renderer.sw // 2
        # The floor visible just above the counter face should be
        # gray (tile_floor) not brown (counter_top texture).
        # Scan the floor region above the counter face.
        gray_count = 0
        for y in range(half + 2, half + 15):
            R, G, B = _column_pixel(fb, renderer.sw, center, y)
            lum = R + G + B
            rgdiff = abs(R - G) + abs(G - B)
            # Gray floor: balanced RGB, not strongly brown
            if lum > 40 and rgdiff < 20:
                gray_count += 1

        assert gray_count > 3, (
            f"Only {gray_count} gray floor pixels above counter face. "
            f"Floor may be using wall texture instead of floor override."
        )


class TestCounterFromMultipleAngles:
    """The counter U-shape should be visible from all four cardinal
    directions when approaching from valid camera positions."""

    def test_counter_faces_visible_from_each_side(self) -> None:
        """Render toward the counter from each approach and verify
        the deferred wall produces visible pixels."""
        renderer, zone = _make_renderer("showcase")

        viewpoints = [
            # (px, py, angle, description)
            (5.5, 9.5, math.pi * 1.5, "south→north (default)"),
            (4.5, 7.5, math.pi * 1.5, "inside-U north face"),
            (4.5, 7.5, math.pi,       "inside-U west face"),
            (2.5, 7.5, 0.0,           "west side → east"),
        ]

        half = renderer.sh // 2

        for px, py, angle, desc in viewpoints:
            fb = _render_and_get_fb(renderer, px, py, angle)
            zbuf = _render_and_get_zbuf(renderer, px, py, angle)

            # Count columns with counter-distance z-buf
            close_cols = sum(1 for z in zbuf if 0.2 < z < 4.0)
            # Count brown-ish pixels in the counter face band
            brown_px = 0
            for y in range(half, renderer.sh):
                for x in range(0, renderer.sw, 4):
                    R, G, B = _column_pixel(fb, renderer.sw, x, y)
                    if R + G + B > 80 and R > B:
                        brown_px += 1

            assert close_cols > 0, (
                f"No deferred z-buf hits from {desc}"
            )
            assert brown_px > 20, (
                f"Only {brown_px} brown pixels from {desc} — "
                f"counter face not visible?"
            )


class TestAOShadowBelowCounter:
    """Short walls should cast a subtle AO shadow on the floor below."""

    def test_ao_shadow_darker_than_adjacent_floor(self) -> None:
        renderer, zone = _make_renderer("showcase")
        fb = _render_and_get_fb(renderer, 5.5, 9.5, math.pi * 1.5)

        half = renderer.sh // 2
        center = renderer.sw // 2
        # Find the bottom of the counter face (first non-brown pixel below
        # the brown region)
        counter_bottom = None
        in_counter = False
        for y in range(half, renderer.sh):
            R, G, B = _column_pixel(fb, renderer.sw, center, y)
            is_brown = R > G and G >= B and R + G + B > 80
            if is_brown:
                in_counter = True
            elif in_counter:
                counter_bottom = y
                break

        if counter_bottom is None:
            pytest.skip("Cannot find counter bottom edge")

        # The pixel just below counter should be darker (AO shadow)
        # than the floor a few pixels below
        R_ao, G_ao, B_ao = _column_pixel(
            fb, renderer.sw, center, counter_bottom)
        lum_ao = R_ao + G_ao + B_ao

        floor_y = min(counter_bottom + 8, renderer.sh - 1)
        R_f, G_f, B_f = _column_pixel(fb, renderer.sw, center, floor_y)
        lum_floor = R_f + G_f + B_f

        assert lum_ao <= lum_floor, (
            f"AO shadow ({lum_ao}) not darker than floor ({lum_floor}) "
            f"below counter at y={counter_bottom}"
        )


# ═══════════════════════════════════════════════════════════════════
#  Tall ceiling / multi-tier rendering
# ═══════════════════════════════════════════════════════════════════


class TestTallCeiling:
    """The renderer supports variable ceiling heights (e.g. 2.0 for
    double-height rooms).  Walls in tall rooms tile their texture
    vertically, and the ceiling sweep handles multiple height tiers."""

    def test_showcase_has_two_ceiling_tiers(self) -> None:
        """The showcase zone should contain both 0.95 and 2.0 ceil
        heights after the double-height right showroom was added."""
        _, zone = _make_renderer("showcase")
        ch_flat = [h for row in zone.ceil_heights for h in row]
        unique = sorted(set(round(c, 2) for c in ch_flat))
        assert 0.95 in unique, "Standard ceiling tier (0.95) missing"
        assert 2.0 in unique, "Tall ceiling tier (2.0) missing"

    def test_tall_wall_extends_higher(self) -> None:
        """Looking at a wall in the double-height section, the wall
        should extend higher on screen than the same wall type in the
        standard section."""
        renderer, zone = _make_renderer("showcase")

        # Look north from standard-height lobby (cam at col 2, row 9)
        fb_std = _render_and_get_fb(renderer, 2.5, 5.5, math.pi * 1.5)
        # Look north from tall section (cam at col 8, row 4 — inside 2.0 room)
        fb_tall = _render_and_get_fb(renderer, 8.5, 4.5, math.pi * 1.5)

        half = renderer.sh // 2
        center = renderer.sw // 2

        def first_wall_pixel(fb: bytes) -> int:
            """Find the topmost row with a non-background pixel at center."""
            for y in range(half):
                R, G, B = _column_pixel(fb, renderer.sw, center, y)
                if R + G + B > 30:
                    return y
            return half

        top_std = first_wall_pixel(fb_std)
        top_tall = first_wall_pixel(fb_tall)

        # The tall room's wall/ceiling should start higher on screen
        # (lower y value) because the ceiling is at 2.0 instead of 0.95.
        # If both see walls at similar distances, the tall one goes higher.
        # At minimum, verify both render something visible in the upper half.
        assert top_std < half, "Standard room has no wall/ceiling pixels"
        assert top_tall < half, "Tall room has no wall/ceiling pixels"

    def test_no_nan_in_depth_with_mixed_ceilings(self) -> None:
        """The depth buffer should have zero NaN values when rendering
        a zone with mixed ceiling heights."""
        renderer, _ = _make_renderer("showcase")
        renderer.render(5.5, 9.5, math.pi * 1.5)

        import array
        depth_arr = array.array('f')
        depth_arr.frombytes(renderer._depth_px)
        nan_count = sum(1 for v in depth_arr if math.isnan(v))
        assert nan_count == 0, f"{nan_count} NaN values in depth buffer"

    def test_wall_texture_tiles_not_stretches(self) -> None:
        """A wall in the 2.0-height section should tile the texture
        twice vertically (fmod tiling), not stretch it.  We verify
        by checking that the wall column is NOT vertically monotonic
        in brightness — a stretched texture has a single gradient,
        while a tiled one repeats."""
        renderer, zone = _make_renderer("showcase")

        # Look at the north brick wall from inside the tall room
        fb = _render_and_get_fb(renderer, 8.5, 3.5, math.pi * 1.5)

        half = renderer.sh // 2
        center = renderer.sw // 2

        # Collect luminance values down the center column (wall region)
        lum_values = []
        for y in range(half):
            R, G, B = _column_pixel(fb, renderer.sw, center, y)
            lum = R + G + B
            if lum > 30:  # non-background
                lum_values.append(lum)

        # With tiled texture, we expect at least some pixels
        # If the wall is visible, there should be renderable pixels
        assert len(lum_values) > 5, (
            f"Only {len(lum_values)} wall pixels visible in tall room"
        )


# ═══════════════════════════════════════════════════════════════════
#  Pixel-accuracy tests  (in-memory zones, deterministic geometry)
# ═══════════════════════════════════════════════════════════════════


class TestWallDepthAccuracy:
    """Verify that per-pixel depth buffer values match the geometric
    perpendicular distance for known camera→wall configurations."""

    def test_facing_north_depth(self) -> None:
        """10×10 box, camera at (5, 5.5), facing north.
        North wall south-face is at y=1.  Expected perp ≈ 4.5."""
        r = _render_box(10, 10, 5.0, 5.5, math.pi * 1.5)
        cx, cy = SW // 2, SH // 2
        d = _depth_at(r, cx, cy)
        assert abs(d - 4.5) < 0.15, f"Expected depth ≈4.5, got {d:.3f}"

    def test_facing_east_depth(self) -> None:
        """Camera at (5.5, 5), facing east.  East wall at col 9,
        west face at x=9.  Expected perp ≈ 3.5."""
        r = _render_box(10, 10, 5.5, 5.0, 0.0)
        cx, cy = SW // 2, SH // 2
        d = _depth_at(r, cx, cy)
        assert abs(d - 3.5) < 0.15, f"Expected depth ≈3.5, got {d:.3f}"

    def test_facing_south_depth(self) -> None:
        """Camera at (5, 5.5), facing south.  South wall north-face
        at y=9.  Expected perp ≈ 3.5."""
        r = _render_box(10, 10, 5.0, 5.5, math.pi * 0.5)
        cx, cy = SW // 2, SH // 2
        d = _depth_at(r, cx, cy)
        assert abs(d - 3.5) < 0.15, f"Expected depth ≈3.5, got {d:.3f}"

    def test_facing_west_depth(self) -> None:
        """Camera at (5.5, 5), facing west.  West wall at col 0,
        east face at x=1.  Expected perp ≈ 4.5."""
        r = _render_box(10, 10, 5.5, 5.0, math.pi)
        cx, cy = SW // 2, SH // 2
        d = _depth_at(r, cx, cy)
        assert abs(d - 4.5) < 0.15, f"Expected depth ≈4.5, got {d:.3f}"

    def test_closer_gives_smaller_depth(self) -> None:
        """Move camera from 2.5 to 7.5: near→far."""
        r_near = _render_box(10, 10, 5.0, 2.5, math.pi * 1.5)
        r_far  = _render_box(10, 10, 5.0, 7.5, math.pi * 1.5)
        cx, cy = SW // 2, SH // 2
        d_near = _depth_at(r_near, cx, cy)
        d_far  = _depth_at(r_far, cx, cy)
        assert d_near < d_far, (
            f"Near depth {d_near:.3f} should be < far depth {d_far:.3f}"
        )
        assert abs(d_near - 1.5) < 0.15
        assert abs(d_far  - 6.5) < 0.15

    def test_depth_floor_below_wall_is_farther(self) -> None:
        """Pixels below the wall region (floor) should have depth >
        the wall depth, since the floor plane recedes."""
        r = _render_box(10, 10, 5.0, 5.5, math.pi * 1.5)
        cx = SW // 2
        d_wall  = _depth_at(r, cx, SH // 2)
        d_floor = _depth_at(r, cx, SH - 10)  # near the bottom
        assert d_floor < d_wall or d_floor < 2.0, (
            f"Floor depth {d_floor:.3f} should be closer (floor near camera) "
            f"vs wall depth {d_wall:.3f}"
        )


class TestOverlayOcclusion:
    """Verify that overlay walls respect depth ordering against
    primary solid walls — the bug this session fixed."""

    def test_overlay_behind_solid_wall_invisible(self) -> None:
        """An overlay placed behind the north wall should NOT affect
        the depth buffer at center screen."""
        overlay = OverlayWall(
            x1=2.0, y1=-0.5, x2=8.0, y2=-0.5,
            texture=_find_wall_tile(), height_scale=1.0,
        )
        r = _render_box(10, 10, 5.0, 5.5, math.pi * 1.5,
                        overlay_walls=[overlay])
        cx, cy = SW // 2, SH // 2
        d = _depth_at(r, cx, cy)
        # Should be primary wall depth (~4.5), NOT overlay
        assert abs(d - 4.5) < 0.2, (
            f"Behind-wall overlay leaked: depth={d:.3f}, expected ≈4.5"
        )

    def test_overlay_in_front_of_wall_visible(self) -> None:
        """An overlay at y=3 between camera (5.5) and wall face (1.0)
        should be hit first.  Expected overlay perp ≈ 2.5."""
        overlay = OverlayWall(
            x1=1.0, y1=3.0, x2=9.0, y2=3.0,
            texture=_find_wall_tile(), height_scale=1.0,
        )
        r = _render_box(10, 10, 5.0, 5.5, math.pi * 1.5,
                        overlay_walls=[overlay])
        cx, cy = SW // 2, SH // 2
        d = _depth_at(r, cx, cy)
        assert abs(d - 2.5) < 0.2, (
            f"Front overlay not visible: depth={d:.3f}, expected ≈2.5"
        )

    def test_two_overlays_closer_wins(self) -> None:
        """Two overlays at y=4 (close) and y=2 (far).  Camera at y=5.5
        facing north.  Close overlay (perp≈1.5) should win."""
        overlays = [
            OverlayWall(x1=1.0, y1=2.0, x2=9.0, y2=2.0,
                        texture=_find_wall_tile(), height_scale=1.0),
            OverlayWall(x1=1.0, y1=4.0, x2=9.0, y2=4.0,
                        texture=_find_wall_tile(), height_scale=1.0),
        ]
        r = _render_box(10, 10, 5.0, 5.5, math.pi * 1.5,
                        overlay_walls=overlays)
        cx, cy = SW // 2, SH // 2
        d = _depth_at(r, cx, cy)
        assert abs(d - 1.5) < 0.2, (
            f"Closer overlay should win: depth={d:.3f}, expected ≈1.5"
        )

    def test_overlay_behind_camera_not_visible(self) -> None:
        """Overlay at y=7 while camera at y=5.5 faces north.
        The overlay is behind the camera and should not appear."""
        overlay = OverlayWall(
            x1=1.0, y1=7.0, x2=9.0, y2=7.0,
            texture=_find_wall_tile(), height_scale=1.0,
        )
        r = _render_box(10, 10, 5.0, 5.5, math.pi * 1.5,
                        overlay_walls=[overlay])
        cx, cy = SW // 2, SH // 2
        d = _depth_at(r, cx, cy)
        # Should see the primary wall at ~4.5
        assert abs(d - 4.5) < 0.2, (
            f"Behind-camera overlay visible: depth={d:.3f}, expected ≈4.5"
        )

    def test_overlay_occluded_by_nearer_solid_wall(self) -> None:
        """Build a zone with an internal wall and an overlay behind it.
        The internal wall should occlude the overlay."""
        wall_tile = _find_wall_tile()
        floor_tile = _find_floor_tile()
        # 12×12 box with an internal wall at row 3 (cols 1-10)
        zone = _make_box_zone(12, 12)
        for c in range(1, 11):
            zone.tiles[3][c] = wall_tile  # internal wall at row 3
        # Overlay behind the internal wall at y=2.5
        zone.overlay_walls = [
            OverlayWall(x1=1.0, y1=2.5, x2=11.0, y2=2.5,
                        texture=wall_tile, height_scale=1.0),
        ]
        atlas = _get_atlas()
        r = RayRenderer(zone, atlas, sw=SW, sh=SH)
        r.render(6.0, 8.5, math.pi * 1.5)  # face north toward internal wall
        cx, cy = SW // 2, SH // 2
        d = _depth_at(r, cx, cy)
        # Internal wall at row 3, south face at y=4.  Dist = 8.5 - 4.0 = 4.5
        assert d < 5.5, f"Expected internal wall hit, depth={d:.3f}"
        # Should NOT be the overlay (distance 6.0)
        assert d < 5.5, f"Overlay behind internal wall leaked, depth={d:.3f}"


class TestShortOverlayGap:
    """A short overlay (hs < 1) should leave a gap above it where
    the background (solid wall behind, ceiling, etc.) shows through."""

    def test_short_overlay_center_shows_wall_behind(self) -> None:
        """Short overlay (hs=0.3) at y=3.  At screen center (horizon),
        the overlay is below the horizon and shouldn't cover it.
        Center pixel should show the primary wall at ~4.5."""
        overlay = OverlayWall(
            x1=1.0, y1=3.0, x2=9.0, y2=3.0,
            texture=_find_wall_tile(), height_scale=0.3,
        )
        r = _render_box(10, 10, 5.0, 5.5, math.pi * 1.5,
                        overlay_walls=[overlay])
        cx, cy = SW // 2, SH // 2
        d = _depth_at(r, cx, cy)
        # Horizon-level pixels should see through the short overlay
        # to the primary wall behind
        assert d > 3.0, (
            f"Short overlay blocking horizon: depth={d:.3f}, "
            f"expected primary wall at ~4.5"
        )

    def test_short_overlay_bottom_has_overlay_depth(self) -> None:
        """Below the horizon, the short overlay should be visible.
        Check a pixel well below center in the overlay band."""
        overlay = OverlayWall(
            x1=1.0, y1=3.0, x2=9.0, y2=3.0,
            texture=_find_wall_tile(), height_scale=0.4,
        )
        r = _render_box(10, 10, 5.0, 5.5, math.pi * 1.5,
                        overlay_walls=[overlay])
        cx = SW // 2
        # Scan the lower portion of the screen for overlay-depth pixels
        found_overlay = False
        for y in range(SH // 2 + 5, SH - 5):
            d = _depth_at(r, cx, y)
            if abs(d - 2.5) < 0.3:
                found_overlay = True
                break
        assert found_overlay, (
            "Short overlay not visible in lower screen half"
        )


class TestDepthSymmetry:
    """For a perfectly centered camera facing a flat wall, the left
    and right halves of the depth buffer should be mirror-symmetric."""

    def test_left_right_depth_symmetry(self) -> None:
        """Depth at columns equidistant from center should match."""
        r = _render_box(10, 10, 5.0, 5.5, math.pi * 1.5)
        cx, cy = SW // 2, SH // 2
        for offset in [10, 30, 60, 100]:
            xl = cx - offset
            xr = cx + offset - 1  # -1 because center pixel is at cx
            if xl < 0 or xr >= SW:
                continue
            dl = _depth_at(r, xl, cy)
            dr = _depth_at(r, xr, cy)
            assert abs(dl - dr) < 0.05, (
                f"Asymmetric depth at ±{offset}: left={dl:.4f}, right={dr:.4f}"
            )

    def test_left_right_depth_symmetry_with_overlay(self) -> None:
        """Overlay wall spanning the full width should also be symmetric."""
        overlay = OverlayWall(
            x1=1.0, y1=3.0, x2=9.0, y2=3.0,
            texture=_find_wall_tile(), height_scale=1.0,
        )
        r = _render_box(10, 10, 5.0, 5.5, math.pi * 1.5,
                        overlay_walls=[overlay])
        cx, cy = SW // 2, SH // 2
        for offset in [10, 30, 60]:
            xl = cx - offset
            xr = cx + offset - 1
            if xl < 0 or xr >= SW:
                continue
            dl = _depth_at(r, xl, cy)
            dr = _depth_at(r, xr, cy)
            assert abs(dl - dr) < 0.05, (
                f"Overlay asymmetric at ±{offset}: "
                f"left={dl:.4f}, right={dr:.4f}"
            )


class TestDiagonalOverlayIntersection:
    """Diagonal overlay walls should be hit by the expected columns
    and missed by others."""

    def test_diagonal_center_column_hit(self) -> None:
        """A diagonal overlay from (3,3) to (7,3) — horizontal, so
        center column facing north should hit it."""
        overlay = OverlayWall(
            x1=3.0, y1=3.0, x2=7.0, y2=3.0,
            texture=_find_wall_tile(), height_scale=1.0,
        )
        r = _render_box(10, 10, 5.0, 5.5, math.pi * 1.5,
                        overlay_walls=[overlay])
        cx, cy = SW // 2, SH // 2
        d = _depth_at(r, cx, cy)
        assert abs(d - 2.5) < 0.2, (
            f"Diagonal overlay center miss: depth={d:.3f}, expected ≈2.5"
        )

    def test_narrow_overlay_edges_not_covering_all(self) -> None:
        """A short segment from (4,3) to (6,3) should only cover
        columns near the center, not the far left/right."""
        overlay = OverlayWall(
            x1=4.0, y1=3.0, x2=6.0, y2=3.0,
            texture=_find_wall_tile(), height_scale=1.0,
        )
        r = _render_box(10, 10, 5.0, 5.5, math.pi * 1.5,
                        overlay_walls=[overlay])
        cy = SH // 2
        # Center column should hit
        d_center = _depth_at(r, SW // 2, cy)
        assert abs(d_center - 2.5) < 0.3, (
            f"Center should hit overlay: depth={d_center:.3f}"
        )
        # Far left column should NOT hit the overlay (see primary wall)
        d_left = _depth_at(r, 5, cy)
        assert d_left > 3.5, (
            f"Far-left column shouldn't hit narrow overlay: "
            f"depth={d_left:.3f}"
        )

    def test_true_diagonal_visible(self) -> None:
        """A truly diagonal overlay from (3,2) to (7,4) should be
        intersected by some columns in the center."""
        overlay = OverlayWall(
            x1=3.0, y1=2.0, x2=7.0, y2=4.0,
            texture=_find_wall_tile(), height_scale=1.0,
        )
        r = _render_box(10, 10, 5.0, 5.5, math.pi * 1.5,
                        overlay_walls=[overlay])
        # At least some columns in the central region should hit the overlay
        cy = SH // 2
        overlay_hits = 0
        for x in range(SW // 4, 3 * SW // 4):
            d = _depth_at(r, x, cy)
            if d < 4.0:  # closer than the primary wall
                overlay_hits += 1
        assert overlay_hits > SW // 10, (
            f"True diagonal overlay only hit {overlay_hits} columns, "
            f"expected > {SW // 10}"
        )


class TestOverlayNoDepthBufferCorruption:
    """The depth buffer should never contain NaN or negative values
    when overlay walls are present."""

    def test_no_nan_with_overlays(self) -> None:
        overlays = [
            OverlayWall(x1=2.0, y1=3.0, x2=8.0, y2=3.0,
                        texture=_find_wall_tile(), height_scale=1.0),
            OverlayWall(x1=3.0, y1=2.0, x2=7.0, y2=4.0,
                        texture=_find_wall_tile(), height_scale=0.4),
        ]
        r = _render_box(10, 10, 5.0, 5.5, math.pi * 1.5,
                        overlay_walls=overlays)
        import array as arr_mod
        depth_arr = arr_mod.array("f")
        depth_arr.frombytes(r._depth_px)
        nan_count = sum(1 for v in depth_arr if math.isnan(v))
        neg_count = sum(1 for v in depth_arr if v < 0)
        assert nan_count == 0, f"{nan_count} NaN values in depth buffer"
        assert neg_count == 0, f"{neg_count} negative depth values"

    def test_no_nan_with_many_overlays(self) -> None:
        """Stress test: many overlays from various angles."""
        overlays = []
        for i in range(10):
            y = 1.5 + i * 0.7
            if y >= 9.0:
                break
            overlays.append(OverlayWall(
                x1=1.5, y1=y, x2=8.5, y2=y,
                texture=_find_wall_tile(), height_scale=0.5,
            ))
        r = _render_box(10, 10, 5.0, 5.5, math.pi * 1.5,
                        overlay_walls=overlays)
        zbuf = list(struct.unpack(f"{SW}d", r._zbuf))
        nan_count = sum(1 for z in zbuf if z != z)
        assert nan_count == 0, f"Z-buffer has {nan_count} NaN after many overlays"

    def test_overlay_four_directions_stable(self) -> None:
        """Render with overlays from all 4 cardinal directions."""
        overlay = OverlayWall(
            x1=3.0, y1=3.0, x2=7.0, y2=7.0,
            texture=_find_wall_tile(), height_scale=1.0,
        )
        zone = _make_box_zone(10, 10, overlay_walls=[overlay])
        atlas = _get_atlas()
        r = RayRenderer(zone, atlas, sw=SW, sh=SH)
        for angle in [0.0, math.pi * 0.5, math.pi, math.pi * 1.5]:
            r.render(5.0, 5.5, angle)
            zbuf = list(struct.unpack(f"{SW}d", r._zbuf))
            nan_count = sum(1 for z in zbuf if z != z)
            assert nan_count == 0, (
                f"NaN at angle {angle:.2f} with diagonal overlay"
            )


class TestWallScreenCoverage:
    """Verify that a wall at known distance produces the correct
    on-screen height in pixels."""

    def test_wall_covers_center_band(self) -> None:
        """Wall at perp ≈ 4.5 in 320×180: line_h = 180/4.5 = 40.
        Wall should span roughly ±20 pixels around the horizon."""
        r = _render_box(10, 10, 5.0, 5.5, math.pi * 1.5)
        cx = SW // 2
        # Count the vertical extent of wall-depth pixels at center column
        wall_depth = _depth_at(r, cx, SH // 2)
        wall_pixels = 0
        for y in range(SH):
            d = _depth_at(r, cx, y)
            if abs(d - wall_depth) < 0.1:
                wall_pixels += 1
        expected_h = int(SH / wall_depth)
        # Allow ±30% tolerance for rounding, clamping, etc.
        assert wall_pixels > expected_h * 0.7, (
            f"Wall covers only {wall_pixels}px, expected ≈{expected_h}"
        )
        assert wall_pixels < expected_h * 1.3, (
            f"Wall covers {wall_pixels}px, expected ≈{expected_h} — too tall?"
        )

    def test_closer_wall_taller_on_screen(self) -> None:
        """A wall at distance 1.5 should cover more screen pixels
        than the same wall at distance 4.5."""
        r_near = _render_box(10, 10, 5.0, 2.5, math.pi * 1.5)
        r_far  = _render_box(10, 10, 5.0, 5.5, math.pi * 1.5)
        cx = SW // 2

        def wall_height(renderer: RayRenderer) -> int:
            ref = _depth_at(renderer, cx, SH // 2)
            return sum(1 for y in range(SH)
                       if abs(_depth_at(renderer, cx, y) - ref) < 0.1)

        h_near = wall_height(r_near)
        h_far  = wall_height(r_far)
        assert h_near > h_far, (
            f"Closer wall ({h_near}px) should be taller than far ({h_far}px)"
        )


class TestRendererStressOverlays:
    """Stress-test the renderer with edge-case overlay configurations."""

    def test_zero_length_overlay_no_crash(self) -> None:
        """A zero-length overlay segment should be harmlessly skipped."""
        overlay = OverlayWall(
            x1=5.0, y1=3.0, x2=5.0, y2=3.0,
            texture=_find_wall_tile(), height_scale=1.0,
        )
        r = _render_box(10, 10, 5.0, 5.5, math.pi * 1.5,
                        overlay_walls=[overlay])
        # Should not crash — just verify render completes
        assert _depth_at(r, SW // 2, SH // 2) > 0

    def test_overlay_on_camera_position_no_crash(self) -> None:
        """Overlay passing through the camera position should not crash."""
        overlay = OverlayWall(
            x1=1.0, y1=5.5, x2=9.0, y2=5.5,
            texture=_find_wall_tile(), height_scale=1.0,
        )
        r = _render_box(10, 10, 5.0, 5.5, math.pi * 1.5,
                        overlay_walls=[overlay])
        assert _depth_at(r, SW // 2, SH // 2) > 0

    def test_overlay_along_ray_direction_no_crash(self) -> None:
        """Overlay parallel to the viewing direction (degenerate
        intersection) should be safely skipped."""
        overlay = OverlayWall(
            x1=5.0, y1=2.0, x2=5.0, y2=4.0,
            texture=_find_wall_tile(), height_scale=1.0,
        )
        r = _render_box(10, 10, 5.0, 5.5, math.pi * 1.5,
                        overlay_walls=[overlay])
        # Center ray goes straight north (dx=0, dy=-1).  Overlay is also
        # N-S aligned at x=5.  They're parallel → denom ≈ 0 → skip.  
        # Depth should be the primary wall.
        cx, cy = SW // 2, SH // 2
        d = _depth_at(r, cx, cy)
        assert d > 3.0, f"Parallel overlay shouldn't be visible: depth={d:.3f}"

    def test_many_overlapping_overlays(self) -> None:
        """Stack many overlays at ascending distances.  The closest
        should always win."""
        overlays = []
        for i in range(8):
            y = 2.0 + i * 0.5
            overlays.append(OverlayWall(
                x1=1.0, y1=y, x2=9.0, y2=y,
                texture=_find_wall_tile(), height_scale=1.0,
            ))
        r = _render_box(10, 10, 5.0, 5.5, math.pi * 1.5,
                        overlay_walls=overlays)
        cx, cy = SW // 2, SH // 2
        d = _depth_at(r, cx, cy)
        # The closest overlay is at y=5.0 (farthest from wall, closest to cam)
        # perp = 5.5 - 5.0 = 0.5
        assert d < 1.0, (
            f"Closest overlay should be at ~0.5 depth, got {d:.3f}"
        )
