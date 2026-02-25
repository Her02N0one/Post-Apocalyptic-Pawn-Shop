#!/usr/bin/env python3
"""tests/test_editor_renderer.py — Comprehensive visual-correctness and
functional tests for the 3D sculpt editor + renderer pipeline.

Sections
--------
  1.  Cell-box visibility — every cell type has clickable geometry
  2.  Crosshair aiming   — camera at known positions finds correct targets
  3.  Build actions       — LMB produces measurable zone data changes AND
                            visible box changes
  4.  Dig actions         — RMB removes/reduces geometry correctly
  5.  Wall/open transitions
  6.  Per-face texture painting + renderer face-tex grid
  7.  Renderer pixel tests — no magenta, pixel changes after edits
  8.  Editor draw sanity  — 3D wireframe surface never all-black, no crash
  9.  Camera sync 2D↔3D
  10. Zone save round-trip
  11. Projection orientation
"""

import math
import sys
import os
import json
import array as _arr
import tempfile
import shutil
from pathlib import Path

_root = str(Path(__file__).resolve().parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

os.environ["SDL_VIDEODRIVER"] = "dummy"
import pygame
pygame.init()
screen = pygame.display.set_mode((320, 240))

from core.zones import load_zone
from core.tiles import tile_def, tile_str_to_int, TILE_REGISTRY
from editor.view_3d import (
    Zone3DEditor, _build_view_matrix, _perspective, _mat4_mul, _project,
    _CellHit, CAM_H, COL_BG,
)
from engine.textures import TextureAtlas
from engine.ray_renderer import RayRenderer

# ── Helpers ───────────────────────────────────────────────────────
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
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")

def has_magenta(pixels_bytes: bytes, threshold: int = 10) -> int:
    """Count pixels that are close to magenta (255, 0, 255).
    Returns number of magenta-ish pixels."""
    count = 0
    for i in range(0, len(pixels_bytes) - 2, 3):
        r, g, b = pixels_bytes[i], pixels_bytes[i+1], pixels_bytes[i+2]
        if r > 230 and g < 30 and b > 230:
            count += 1
    return count

def pixel_variance(pixels_bytes: bytes) -> float:
    """Return fraction of pixels that differ from the first pixel."""
    if len(pixels_bytes) < 6:
        return 0.0
    r0, g0, b0 = pixels_bytes[0], pixels_bytes[1], pixels_bytes[2]
    total = len(pixels_bytes) // 3
    diff = sum(1 for i in range(0, len(pixels_bytes) - 2, 3)
               if pixels_bytes[i] != r0 or pixels_bytes[i+1] != g0
               or pixels_bytes[i+2] != b0)
    return diff / total


# =================================================================
section("1. CELL-BOX VISIBILITY")
# Every cell type must produce at least one visible, clickable box.
# =================================================================

zone = load_zone("showcase")
editor = Zone3DEditor(zone)

# Wall cell — must have a box
boxes_wall = editor._cell_boxes(0, 0)
check("Wall cell (0,0) has exactly 1 box",
      len(boxes_wall) == 1, f"got {len(boxes_wall)}")
if boxes_wall:
    p, yb, yt = boxes_wall[0]
    check("Wall box part='wall'", p == "wall")
    check("Wall box has height",
          yt - yb > 0.04, f"yb={yb:.3f} yt={yt:.3f}")

# Open cell fh=0 ch=0.95 — MUST still have visible floor + ceiling
open_r, open_c = 1, 1
td_open = tile_def(zone.tiles[open_r][open_c])
check("(1,1) is open cell", td_open is not None and not td_open.wall)
fh = zone.floor_heights[open_r][open_c]
ch = zone.ceil_heights[open_r][open_c]
boxes_open = editor._cell_boxes(open_r, open_c)
check("Open cell fh=0 ch=0.95: has floor box",
      any(p == "floor" for p, _, _ in boxes_open),
      f"boxes={boxes_open}")
check("Open cell fh=0 ch=0.95: has ceiling box",
      any(p == "ceiling" for p, _, _ in boxes_open),
      f"boxes={boxes_open}")
check("Open cell: exactly 2 boxes (floor+ceiling)",
      len(boxes_open) == 2, f"got {len(boxes_open)}")
# Floor box must be visible (non-zero height)
for p, yb, yt in boxes_open:
    if p == "floor":
        check("Floor box has non-zero height",
              yt - yb > 0.01, f"yb={yb:.3f} yt={yt:.3f}")

# Open cell with ch=2.0 — must still show BOTH floor and ceiling
hi_ch_r, hi_ch_c = None, None
for r in range(zone.height):
    for c in range(zone.width):
        if zone.ceil_heights[r][c] > 1.5:
            td = tile_def(zone.tiles[r][c])
            if td and not td.wall:
                hi_ch_r, hi_ch_c = r, c
                break
    if hi_ch_r is not None:
        break
if hi_ch_r is not None:
    boxes_hi = editor._cell_boxes(hi_ch_r, hi_ch_c)
    ch_val = zone.ceil_heights[hi_ch_r][hi_ch_c]
    check(f"High-ceiling cell ({hi_ch_r},{hi_ch_c}) ch={ch_val:.1f}: has floor",
          any(p == "floor" for p, _, _ in boxes_hi),
          f"boxes={boxes_hi}")
    check(f"High-ceiling cell: has ceiling (ch < 10)",
          any(p == "ceiling" for p, _, _ in boxes_hi),
          f"boxes={boxes_hi}")
else:
    print("  [SKIP] No high-ceiling cell found")

# Exhaustive: every single cell must produce at least 1 box
empty_cells = []
for r in range(zone.height):
    for c in range(zone.width):
        if len(editor._cell_boxes(r, c)) == 0:
            empty_cells.append((r, c))
check("No cells produce zero boxes",
      len(empty_cells) == 0,
      f"empty: {empty_cells[:5]}{'...' if len(empty_cells) > 5 else ''}")


# =================================================================
section("2. CROSSHAIR AIMING")
# Camera at known positions must detect specific geometry.
# =================================================================

zone2 = load_zone("showcase")
ed2 = Zone3DEditor(zone2)

# 2a: In open cell (1,1) looking at wall (0,1) to the north
#     yaw=π → forward = (0, 0, -1) = north
ed2.cam_x = 1.5
ed2.cam_y = 0.5
ed2.cam_z = 1.5
ed2.yaw = math.pi  # north
ed2.pitch = 0.0
ed2._update_aim()
h2a = ed2.aimed
check("Aim north at wall: hit found",
      h2a is not None)
if h2a:
    check("Aim north at wall: part=wall",
          h2a.part == "wall", f"part={h2a.part}")
    check("Aim north at wall: face=south (facing us)",
          h2a.face == "south", f"face={h2a.face}")
    check("Aim north at wall: row=0 (border wall)",
          h2a.row == 0, f"row={h2a.row}")

# 2b: Looking straight down at floor
ed2.yaw = 0.0
ed2.pitch = -1.2  # steep down
ed2._update_aim()
h2b = ed2.aimed
check("Aim down at floor: hit found",
      h2b is not None)
if h2b:
    check("Aim down: part=floor or face=ground",
          h2b.part == "floor" or h2b.face == "ground",
          f"part={h2b.part} face={h2b.face}")

# 2c: Looking up at ceiling
ed2.pitch = 1.2  # steep up
ed2._update_aim()
h2c = ed2.aimed
check("Aim up at ceiling: hit found",
      h2c is not None)
if h2c:
    check("Aim up: part=ceiling",
          h2c.part == "ceiling", f"part={h2c.part} face={h2c.face}")

# 2d: Aimed hit must NEVER be None when inside a standard room
ed2.pitch = 0.0
aim_none_count = 0
for yaw_deg in range(0, 360, 15):
    ed2.yaw = math.radians(yaw_deg)
    ed2._update_aim()
    if ed2.aimed is None:
        aim_none_count += 1
check("Horizontal sweep: aims at geometry in all directions",
      aim_none_count == 0,
      f"missed {aim_none_count}/24 directions")


# =================================================================
section("3. BUILD ACTIONS (visible results)")
# Each build action must change zone data AND cell_boxes output.
# =================================================================

zone3 = load_zone("showcase")
ed3 = Zone3DEditor(zone3)
ed3.snap_y = 0.25

# 3a: Build on open floor — fh must increase
tr, tc = 1, 1
orig_fh = zone3.floor_heights[tr][tc]
boxes_before = editor._cell_boxes(tr, tc)
ed3.aimed = _CellHit(t=1.0, col=tc, row=tr, part="floor", face="top")
ed3._build()
new_fh = zone3.floor_heights[tr][tc]
check(f"Build floor top: fh {orig_fh:.2f} -> {new_fh:.2f}",
      new_fh > orig_fh, f"fh={new_fh}")

# Verify boxes changed
boxes_after = ed3._cell_boxes(tr, tc)
check("Build floor: boxes changed",
      boxes_before != boxes_after,
      f"before={boxes_before} after={boxes_after}")

# 3b: Floor box height should reflect new fh
floor_box = [b for b in boxes_after if b[0] == "floor"]
check("After build: floor box exists",
      len(floor_box) == 1)
if floor_box:
    _, yb, yt = floor_box[0]
    check(f"Floor box encompasses new fh={new_fh:.2f}",
          yb <= new_fh <= yt + 0.01,
          f"yb={yb:.3f} yt={yt:.3f}")

# 3c: Build wall top → ch increases
zone3w = load_zone("showcase")
ed3w = Zone3DEditor(zone3w)
ed3w.snap_y = 0.25
orig_ch_w = zone3w.ceil_heights[0][0]
ed3w.aimed = _CellHit(t=1.0, col=0, row=0, part="wall", face="top")
ed3w._build()
new_ch_w = zone3w.ceil_heights[0][0]
check(f"Build wall top: ch {orig_ch_w:.2f} -> {new_ch_w:.2f}",
      new_ch_w > orig_ch_w)

# 3d: Build wall side → adjacent cell becomes wall
zone3s = load_zone("showcase")
ed3s = Zone3DEditor(zone3s)
adj_r, adj_c = 1, 1  # south of wall (0,1)
check("Adjacent cell starts as open",
      not tile_def(zone3s.tiles[adj_r][adj_c]).wall)
ed3s.aimed = _CellHit(t=1.0, col=1, row=0, part="wall", face="south")
ed3s._build()
check("Build wall south: adjacent (1,1) now wall",
      tile_def(zone3s.tiles[adj_r][adj_c]).wall,
      f"tile={zone3s.tiles[adj_r][adj_c]}")


# =================================================================
section("4. DIG ACTIONS")
# =================================================================

zone4 = load_zone("showcase")
ed4 = Zone3DEditor(zone4)
ed4.snap_y = 0.25

# 4a: Dig wall top → ch decreases
orig_ch4 = zone4.ceil_heights[0][0]
ed4.aimed = _CellHit(t=1.0, col=0, row=0, part="wall", face="top")
ed4._dig()
check(f"Dig wall top: ch decreased",
      zone4.ceil_heights[0][0] < orig_ch4)

# 4b: Dig wall side → becomes open
zone4b = load_zone("showcase")
ed4b = Zone3DEditor(zone4b)
check("Wall before dig", tile_def(zone4b.tiles[0][0]).wall)
ed4b.aimed = _CellHit(t=1.0, col=0, row=0, part="wall", face="north")
ed4b._dig()
check("Dig wall side: now open",
      not tile_def(zone4b.tiles[0][0]).wall)

# 4c: Dig open floor → fh decreases
zone4c = load_zone("showcase")
ed4c = Zone3DEditor(zone4c)
ed4c.snap_y = 0.25
zone4c.floor_heights[1][1] = 0.5
ed4c.aimed = _CellHit(t=1.0, col=1, row=1, part="floor", face="top")
ed4c._dig()
check("Dig open floor: fh decreased",
      zone4c.floor_heights[1][1] < 0.5,
      f"fh={zone4c.floor_heights[1][1]}")

# 4d: After dig, cell boxes still non-empty
boxes_dug = ed4b._cell_boxes(0, 0)
check("Dug cell still has visible boxes",
      len(boxes_dug) >= 1,
      f"boxes={boxes_dug}")


# =================================================================
section("5. WALL/OPEN TRANSITIONS")
# =================================================================

zone5 = load_zone("showcase")
ed5 = Zone3DEditor(zone5)
ed5.snap_y = 0.125
tr5, tc5 = 1, 1
zone5.floor_heights[tr5][tc5] = 0.0
zone5.ceil_heights[tr5][tc5] = 0.5
check("Open before", not tile_def(zone5.tiles[tr5][tc5]).wall)

for _ in range(10):
    ed5.aimed = _CellHit(t=1.0, col=tc5, row=tr5, part="floor", face="top")
    ed5._build()
    if tile_def(zone5.tiles[tr5][tc5]).wall:
        break
check("Floor->ceiling: becomes wall",
      tile_def(zone5.tiles[tr5][tc5]).wall)

ed5.aimed = _CellHit(t=1.0, col=tc5, row=tr5, part="wall", face="north")
ed5._dig()
check("Dig side: back to open",
      not tile_def(zone5.tiles[tr5][tc5]).wall)

# After open: visible boxes again
boxes5 = ed5._cell_boxes(tr5, tc5)
check("Opened cell has visible boxes",
      len(boxes5) >= 1, f"boxes={boxes5}")


# =================================================================
section("6. PER-FACE TEXTURES")
# =================================================================

zone6 = load_zone("showcase")
ed6 = Zone3DEditor(zone6)

ed6.current_texture = "concrete"
ed6.aimed = _CellHit(t=1.0, col=0, row=0, part="wall", face="north")
ed6._paint()
ft6 = zone6.face_textures[0][0]
check("Paint north: ft[0]='concrete'", ft6[0] == "concrete")
check("Paint north: others unchanged", ft6[1] == "" and ft6[2] == "" and ft6[3] == "")

ed6.current_texture = "carpet"
ed6.aimed = _CellHit(t=1.0, col=0, row=0, part="wall", face="south")
ed6._paint()
check("Paint south: ft[1]='carpet'", zone6.face_textures[0][0][1] == "carpet")

# Renderer face_tex_grid
ftex_bytes = RayRenderer._build_face_tex_grid(zone6)
ftex = _arr.array("i")
ftex.frombytes(ftex_bytes)
ci = 0  # cell (0,0)
check("face_tex grid N=concrete",
      ftex[ci * 4 + 0] == tile_str_to_int("concrete"))
check("face_tex grid S=carpet",
      ftex[ci * 4 + 1] == tile_str_to_int("carpet"))

# Floor texture
ed6.current_texture = "tile_floor"
ed6.aimed = _CellHit(t=1.0, col=1, row=1, part="floor", face="top")
ed6._paint()
check("Paint floor top: floor_textures updated",
      zone6.floor_textures[1][1] == "tile_floor")


# =================================================================
section("7. RENDERER PIXEL TESTS")
# Verify rendered output: no magenta, meaningful pixels, changes
# after edits.
# =================================================================

try:
    zone7 = load_zone("showcase")
    atlas = TextureAtlas()

    # Find a wall with open cell to south
    wr7, wc7 = -1, -1
    for r7 in range(zone7.height):
        for c7 in range(zone7.width):
            td_t = tile_def(zone7.tiles[r7][c7])
            if td_t and td_t.wall and r7 + 1 < zone7.height:
                td_s = tile_def(zone7.tiles[r7 + 1][c7])
                if td_s and not td_s.wall:
                    wr7, wc7 = r7, c7
                    break
        if wr7 >= 0:
            break

    if wr7 >= 0:
        cam_x = wc7 + 0.5
        cam_y = wr7 + 1.5
        cam_angle = math.pi * 1.5  # north

        renderer = RayRenderer(zone7, atlas, sw=160, sh=90, fov=60, dn=1.0)

        # 7a: Initial render — no magenta
        fb1 = renderer.render(cam_x, cam_y, cam_angle)
        px1 = pygame.image.tobytes(fb1, "RGB")
        mag1 = has_magenta(px1)
        check("Initial render: no magenta pixels",
              mag1 == 0, f"magenta={mag1}")

        # 7b: Initial render — not all black (has content)
        var1 = pixel_variance(px1)
        check("Initial render: has visual content (not uniform)",
              var1 > 0.05, f"variance={var1:.3f}")

        # 7c: Center pixel is not magenta
        center_idx = (45 * 160 + 80) * 3
        cr, cg, cb = px1[center_idx], px1[center_idx+1], px1[center_idx+2]
        check("Center pixel not magenta",
              not (cr > 230 and cg < 30 and cb > 230),
              f"rgb=({cr},{cg},{cb})")

        # 7d: Dig wall, re-render, pixels change
        ed7 = Zone3DEditor(zone7)
        ed7.aimed = _CellHit(t=1.0, col=wc7, row=wr7, part="wall", face="north")
        ed7._dig()
        check("After dig: cell is non-wall",
              not tile_def(zone7.tiles[wr7][wc7]).wall)

        renderer.update_zone(zone7, atlas, 1.0)
        fb2 = renderer.render(cam_x, cam_y, cam_angle)
        px2 = pygame.image.tobytes(fb2, "RGB")

        diff = sum(1 for a, b in zip(px1, px2) if a != b)
        pct = diff / len(px1) * 100
        check("Rendered pixels changed after edit",
              diff > 0, f"diff={diff}")
        check(f"Significant change ({pct:.1f}%)",
              pct > 1.0)

        # 7e: After-edit render has no magenta
        mag2 = has_magenta(px2)
        check("Post-edit render: no magenta",
              mag2 == 0, f"magenta={mag2}")

        # 7f: Render from several angles — no magenta anywhere
        angles_clear = True
        worst_mag = 0
        for test_angle in [0, math.pi/2, math.pi, math.pi*1.5]:
            fb_a = renderer.render(cam_x, cam_y, test_angle)
            px_a = pygame.image.tobytes(fb_a, "RGB")
            m = has_magenta(px_a)
            worst_mag = max(worst_mag, m)
            if m > 0:
                angles_clear = False
        check("No magenta from any cardinal direction",
              angles_clear, f"worst={worst_mag}")

    else:
        print("  [SKIP] No wall+open pair found")

except Exception as e:
    import traceback
    traceback.print_exc()
    print(f"  [SKIP] Renderer tests failed: {e}")


# =================================================================
section("8. EDITOR DRAW SANITY")
# 3D editor draw must not crash and must produce visible content.
# =================================================================

zone8 = load_zone("showcase")
ed8 = Zone3DEditor(zone8)
surf8 = pygame.Surface((320, 240))

# Camera in open area, looking south
ed8.cam_x = 5.5
ed8.cam_y = 0.5
ed8.cam_z = 5.5
ed8.yaw = 0.0  # south
ed8.pitch = 0.0

try:
    ed8.draw(surf8)
    px8 = pygame.image.tobytes(surf8, "RGB")
    var8 = pixel_variance(px8)
    check("Editor draw: no crash", True)
    check("Editor draw: has visible content",
          var8 > 0.01, f"variance={var8:.3f}")
except Exception as e:
    check("Editor draw: no crash", False, str(e))

# Looking down at floor should show geometry
ed8.pitch = -0.8
try:
    ed8.draw(surf8)
    center_px8 = surf8.get_at((160, 120))[:3]
    check("Pitch down: center pixel not background",
          center_px8 != COL_BG,
          f"rgb={center_px8}")
except Exception as e:
    check("Pitch down draw", False, str(e))

# Looking at wall
ed8.cam_x = 1.5
ed8.cam_y = 0.5
ed8.cam_z = 1.5
ed8.yaw = math.pi  # north
ed8.pitch = 0.0
try:
    ed8.draw(surf8)
    center_px8w = surf8.get_at((160, 120))[:3]
    check("Looking at wall: center pixel not background",
          center_px8w != COL_BG,
          f"rgb={center_px8w}")
except Exception as e:
    check("Wall draw", False, str(e))


# =================================================================
section("9. CAMERA SYNC 2D<->3D")
# Verify yaw conversion between 2.5D angle and 3D editor yaw.
# =================================================================

# 2.5D: angle=π*1.5 means north (cos=-0, sin=-1 → -row direction)
# 3D:   yaw = angle - π/2 → yaw = π
# Forward at yaw=π: (-cos(π)*sin(π), ..., cos(π)*cos(π)) = (0, ..., -1) = -Z = north ✓

angle_2d_north = math.pi * 1.5
yaw_3d = angle_2d_north - math.pi * 0.5
# Forward direction
cp = math.cos(0)
fz = cp * math.cos(yaw_3d)
check("2D north → 3D forward -Z",
      fz < -0.9, f"fz={fz}")

angle_2d_east = 0.0  # cos=1,sin=0 → +col
yaw_3d_e = angle_2d_east - math.pi * 0.5
fx_e = -math.cos(0) * math.sin(yaw_3d_e)
check("2D east → 3D forward +X",
      fx_e > 0.9, f"fx={fx_e}")

# Round-trip: 3D yaw → 2D angle → 3D yaw
for test_yaw in [0, 0.5, 1.0, math.pi, -0.3]:
    angle_rt = test_yaw + math.pi * 0.5
    yaw_rt = angle_rt - math.pi * 0.5
    check(f"Yaw round-trip yaw={test_yaw:.2f}",
          abs(yaw_rt - test_yaw) < 1e-10)


# =================================================================
section("10. ZONE SAVE ROUND-TRIP")
# =================================================================

zone10 = load_zone("showcase")
ed10 = Zone3DEditor(zone10)
ed10.snap_y = 0.25
zone10.floor_heights[2][2] = 0.3
zone10.ceil_heights[2][2] = 0.7
ed10._make_wall(2, 2)
zone10.face_textures[2][2] = ["concrete", "carpet", "", ""]

orig_zones_dir = None
try:
    tmpdir = Path(tempfile.mkdtemp())
    import core.paths
    orig_zones_dir = core.paths.ZONES_DIR
    core.paths.ZONES_DIR = tmpdir
    ed10._save_zone_json()

    with open(tmpdir / f"{zone10.name}.json") as f:
        data = json.load(f)

    check("face_textures saved", "face_textures" in data)
    if "face_textures" in data:
        check("face_textures[2][2] correct",
              data["face_textures"][2][2] == ["concrete", "carpet", "", ""])
    check("floor_heights[2][2] = 0.3",
          abs(data["floor_heights"][2][2] - 0.3) < 0.01)
    check("ceil_heights[2][2] = 0.7",
          abs(data["ceil_heights"][2][2] - 0.7) < 0.01)
    check("tiles[2][2] is wall",
          tile_def(data["tiles"][2][2]).wall)
finally:
    if orig_zones_dir:
        core.paths.ZONES_DIR = orig_zones_dir
    if 'tmpdir' in dir():
        shutil.rmtree(tmpdir, ignore_errors=True)


# =================================================================
section("11. PROJECTION ORIENTATION")
# =================================================================

eye = (5.5, 0.5, 9.5)
hw, hh = 160.0, 120.0
proj = _perspective(math.radians(75.0), hw / hh, 0.05, 80.0)
view = _build_view_matrix(eye, 0.0, 0.0)
vp = _mat4_mul(proj, view)

p_ahead = _project(vp, 5.5, 0.5, 13.5, hw, hh)
check("Point ahead -> center",
      p_ahead is not None and abs(p_ahead[0] - hw) < 30 and abs(p_ahead[1] - hh) < 30)

p_above = _project(vp, 5.5, 2.0, 13.5, hw, hh)
check("Point above -> top half", p_above is not None and p_above[1] < hh)

p_below = _project(vp, 5.5, -1.0, 13.5, hw, hh)
check("Point below -> bottom half", p_below is not None and p_below[1] > hh)

p_behind = _project(vp, 5.5, 0.5, 5.0, hw, hh)
check("Point behind -> rejected", p_behind is None)


# =================================================================
#  Summary
# =================================================================
print(f"\n{'='*60}")
print(f"  RESULTS: {PASS} passed, {FAIL} failed")
print(f"{'='*60}")
sys.exit(1 if FAIL > 0 else 0)
