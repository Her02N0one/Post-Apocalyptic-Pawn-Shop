"""scenes/world/fp_surfaces.py — Floor, ceiling, visplane & tint rendering.

Defines methods attached to ``Renderer``: ``draw_floor_ceiling``,
``draw_visplane_tops``, and ``draw_day_night``.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pygame
import numpy as np

from core.tiles import SOLID_IDS, PLATFORM_IDS, TILE_COLORS, color_lut, solid_int_set, grid_to_ints, platform_lut
from scenes.world.fp_lighting import (
    lerp_color,
    CEILING_DAY, CEILING_NIGHT,
    FLOOR_DAY, FLOOR_NIGHT,
    GRAD_BANDS,
)

if TYPE_CHECKING:
    from scenes.world.fp_renderer import Renderer


# ══════════════════════════════════════════════════════════════════
#  Floor / Ceiling
# ══════════════════════════════════════════════════════════════════

def draw_floor_ceiling(
    self: "Renderer",
    surface: pygame.Surface,
    sw: int, sh: int, half: int,
    px: float, py: float, angle: float,
    fog_lut: list[int], dn: float,
    fov: float,
    tiles: list[list[str]], map_w: int, map_h: int,
    is_interior: bool,
) -> None:
    """Per-row textured floor with checkerboard + gradient ceiling."""
    _fill = surface.fill

    # ── Ceiling ──────────────────────────────────────────────
    if is_interior:
        _cc = lerp_color((25, 28, 32), (65, 68, 72), dn)
        half_sh = sh * 0.5
        _CDIV = 4
        cbw = max(1, sw // _CDIV)
        cbh = max(1, half // _CDIV)

        # Vectorised ceiling — replaces Python row-loop
        _cy = np.arange(cbh, dtype=np.float64)
        dy = (cbh - _cy) * _CDIV
        p = dy + 0.5
        row_dist = half_sh / p
        fi = np.clip((row_dist * 8.0).astype(np.int32), 0, 255)
        fog_arr = np.asarray(fog_lut, dtype=np.float64)
        ff = fog_arr[fi] * 0.003921568627451  # 1/255
        cr = np.clip((_cc[0] * ff).astype(np.int32), 0, 255).astype(np.uint8)
        cg = np.clip((_cc[1] * ff).astype(np.int32), 0, 255).astype(np.uint8)
        cb_ = np.clip((_cc[2] * ff).astype(np.int32), 0, 255).astype(np.uint8)
        rgb = np.empty((cbh, cbw, 3), dtype=np.uint8)
        rgb[:, :, 0] = cr[:, None]
        rgb[:, :, 1] = cg[:, None]
        rgb[:, :, 2] = cb_[:, None]
        ceil_fb = pygame.image.frombuffer(rgb.tobytes(), (cbw, cbh), 'RGB').convert()
        surface.blit(pygame.transform.scale(ceil_fb, (sw, half)), (0, 0))
    else:
        ceil = lerp_color(CEILING_NIGHT, CEILING_DAY, dn)
        band_h = max(1, half // GRAD_BANDS + 1)
        for i in range(GRAD_BANDS):
            t = i / GRAD_BANDS
            cr = int(ceil[0] * (0.3 + 0.7 * t))
            cg = int(ceil[1] * (0.3 + 0.7 * t))
            cb = int(ceil[2] * (0.3 + 0.7 * t))
            y = int(t * half)
            _fill((cr, cg, cb), (0, y, sw, band_h))

    # ── Floor ────────────────────────────────────────────────
    if not tiles or map_w < 1 or map_h < 1:
        fc = lerp_color(FLOOR_NIGHT, FLOOR_DAY, dn)
        _fill(fc, (0, half, sw, sh - half))
        return

    _cos_a = math.cos(angle)
    _sin_a = math.sin(angle)
    _tan_h = math.tan(fov * 0.5)
    plane_x = -_sin_a * _tan_h
    plane_y = _cos_a * _tan_h
    half_sh = sh * 0.5

    _dflt = (50, 50, 45)
    _solid_ints = solid_int_set()
    _clut = color_lut()
    _pal: list[tuple[int, int, int]] = []
    for i, c in enumerate(_clut):
        _pal.append(_dflt if i in _solid_ints else c)
    _pal_len = len(_pal)

    floor_h = sh - half
    if floor_h < 1:
        return

    _FDIV = 5
    fbw = max(1, sw // _FDIV)
    fbh = max(1, floor_h // _FDIV)

    np_tiles = self._get_np_tiles(grid_to_ints(tiles), map_h, map_w)
    ct = self._get_floor_ct(fog_lut, _pal, _pal_len)

    # Row geometry — vectorised over all rows at once.
    # Cache _by and _bx arrays (only depend on fbh/fbw).
    _floor_key = (fbh, fbw, _FDIV)
    if getattr(self, '_floor_arr_key', None) != _floor_key:
        self._floor_arr_key = _floor_key
        self._floor_by = np.arange(fbh, dtype=np.float64)
        self._floor_bx = np.arange(fbw, dtype=np.float64)
        self._floor_by_scaled = self._floor_by * _FDIV + _FDIV * 0.5 + 0.5
    _by_sc = self._floor_by_scaled
    _bx = self._floor_bx

    row_dist = half_sh / _by_sc
    fi = np.clip((row_dist * 8.0).astype(np.int32), 0, 255)

    # World-coordinate grid — (fbh, fbw)
    _inv = 1.0 / fbw
    sx = row_dist * (2.0 * plane_x * _inv)
    sy = row_dist * (2.0 * plane_y * _inv)
    fx0 = px + row_dist * (_cos_a - plane_x) + sx * 0.5
    fy0 = py + row_dist * (_sin_a - plane_y) + sy * 0.5

    fx = fx0[:, None] + _bx[None, :] * sx[:, None]
    fy = fy0[:, None] + _bx[None, :] * sy[:, None]

    ifx = fx.astype(np.int32)
    ify = fy.astype(np.int32)
    tid_grid = np.clip(
        np_tiles[ify % map_h, ifx % map_w], 0, _pal_len - 1)
    checker = (ifx ^ ify) & 1

    rgb = ct[fi[:, None], tid_grid, checker]
    fb = pygame.image.frombuffer(rgb.tobytes(), (fbw, fbh), 'RGB').convert()
    surface.blit(pygame.transform.scale(fb, (sw, floor_h)), (0, half))


# ══════════════════════════════════════════════════════════════════
#  Visplane platform tops  (Doom-style horizontal spans)
# ══════════════════════════════════════════════════════════════════

def draw_visplane_tops(
    self: "Renderer",
    surface: pygame.Surface,
    sw: int, sh: int, half: int,
    px: float, py: float,
    angle: float, fov: float,
    plat_col: dict[int, tuple[int, int, float, int]],
    fog_lut: list[int],
    tiles: list[list[str]], map_w: int, map_h: int,
    *, offscreen: bool = False,
) -> tuple[pygame.Surface, int] | None:
    """Draw platform top surfaces at reduced resolution.

    When *offscreen* is True, renders to a transparent surface
    and returns ``(vp_surface, vp_top)`` instead of blitting
    directly.
    """
    if not plat_col:
        return None

    _cos_a = math.cos(angle)
    _sin_a = math.sin(angle)
    _tan_h = math.tan(fov * 0.5)
    vp_plane_x = -_sin_a * _tan_h
    vp_plane_y = _cos_a * _tan_h
    _inv_sw = 1.0 / sw

    _VP_DIV = 3

    max_cy0 = max(v[0] for v in plat_col.values())
    vp_top = half + 1
    vp_h = min(sh, max_cy0 + 1) - vp_top
    if vp_h < 1:
        return None

    buf_w = max(1, sw // _VP_DIV)
    buf_h = max(1, vp_h // _VP_DIV)

    # ── Palette + colour table ───────────────────────────────
    _dflt = (100, 95, 85)
    _clut = color_lut()
    _pal: list[tuple[int, int, int]] = [_dflt if not c else c for c in _clut] if _clut else [_dflt]
    _pal_len = len(_pal)

    vp_ct = self._get_vp_ct(fog_lut, _pal, _pal_len)

    # ── Gather platform columns into flat arrays ─────────────
    n_alloc = len(plat_col)
    _col_bx = np.empty(n_alloc, dtype=np.int32)
    _col_cy = np.empty(n_alloc, dtype=np.int32)
    _col_dx = np.empty(n_alloc, dtype=np.float64)
    _col_dy = np.empty(n_alloc, dtype=np.float64)
    _col_dh = np.empty(n_alloc, dtype=np.float64)
    _i = 0
    for scr_x, (cy0, _tid, hs_val, cw) in plat_col.items():
        dh = 0.5 - hs_val
        if dh < 0.01:
            continue
        cam_x = (2.0 * scr_x + 1.0) * _inv_sw - 1.0
        _col_bx[_i] = scr_x // _VP_DIV
        _col_cy[_i] = (cy0 - vp_top) // _VP_DIV
        _col_dx[_i] = _cos_a + cam_x * vp_plane_x
        _col_dy[_i] = _sin_a + cam_x * vp_plane_y
        _col_dh[_i] = dh
        _i += 1
    if _i == 0:
        return None
    col_bx = _col_bx[:_i]
    col_cy = _col_cy[:_i]
    col_dx = _col_dx[:_i]
    col_dy = _col_dy[:_i]
    col_dh = _col_dh[:_i]

    np_tiles = self._get_np_tiles(grid_to_ints(tiles), map_h, map_w)

    # ── Vectorised row / column sweep ────────────────────────
    by_arr = np.arange(buf_h, dtype=np.float64)
    p = by_arr * _VP_DIV + (_VP_DIV >> 1) + 1.0
    delta_sh = col_dh * sh
    row_dist = delta_sh[None, :] / p[:, None]

    fi = np.clip((row_dist * 8.0).astype(np.int32), 0, 255)

    wx = (px + row_dist * col_dx[None, :]).astype(np.int32)
    wy = (py + row_dist * col_dy[None, :]).astype(np.int32)

    # Validity mask
    valid = np.arange(buf_h, dtype=np.int32)[:, None] < col_cy[None, :]
    valid &= (wx >= 0) & (wx < map_w) & (wy >= 0) & (wy < map_h)

    swx = np.clip(wx, 0, max(0, map_w - 1))
    swy = np.clip(wy, 0, max(0, map_h - 1))
    grid_tid = np_tiles[swy, swx]

    # Platform-ID check via boolean LUT (compact int space)
    _plut = platform_lut()
    plat_lut_len = max(
        int(grid_tid.max()) + 1 if grid_tid.size else 0,
        len(_plut),
    )
    plat_lut = np.zeros(plat_lut_len, dtype=bool)
    for i in range(min(len(_plut), plat_lut_len)):
        if _plut[i]:
            plat_lut[i] = True
    valid &= plat_lut[np.clip(grid_tid, 0, plat_lut_len - 1)]
    valid &= grid_tid < _pal_len

    checker = (wx ^ wy) & 1
    colors = vp_ct[
        fi, np.clip(grid_tid, 0, _pal_len - 1), checker
    ]

    # ── Scatter into output buffer (colour-keyed) ────────────
    buf_np = np.empty((buf_h, buf_w, 3), dtype=np.uint8)
    buf_np[:, :, 0] = 0
    buf_np[:, :, 1] = 0
    buf_np[:, :, 2] = 1  # colour key

    vr, vc = np.where(valid)
    vbx = col_bx[vc]
    ok = (vbx >= 0) & (vbx < buf_w)
    buf_np[vr[ok], vbx[ok]] = colors[vr[ok], vc[ok]]

    # Fill 1-column gaps caused by RAY_STEP > _VP_DIV
    vbx1 = np.minimum(vbx[ok] + 1, buf_w - 1)
    buf_np[vr[ok], vbx1] = colors[vr[ok], vc[ok]]

    vp_surf = pygame.image.frombuffer(
        buf_np.tobytes(), (buf_w, buf_h), 'RGB').convert()
    vp_surf.set_colorkey((0, 0, 1))
    scaled_vp = pygame.transform.scale(vp_surf, (sw, vp_h))

    if offscreen:
        return scaled_vp, vp_top
    surface.blit(scaled_vp, (0, vp_top))
    return None


# ══════════════════════════════════════════════════════════════════
#  Day / night tint overlay
# ══════════════════════════════════════════════════════════════════

def draw_day_night(
    self: "Renderer",
    surface: pygame.Surface,
    wc,  # WorldClock | None
) -> None:
    """Apply a subtle colour overlay based on time of day."""
    if wc is None:
        return
    phase = wc.day_phase
    if 0.30 <= phase < 0.70:
        return

    if phase < 0.20 or phase >= 0.85:
        color = (10, 10, 50)
        alpha = 60
    elif 0.20 <= phase < 0.30:
        t = (phase - 0.20) / 0.10
        alpha = int(60 * (1.0 - t))
        r = int(10 + 40 * t)
        g = int(10 + 20 * t)
        b = int(50 - 20 * t)
        color = (r, g, b)
    elif 0.70 <= phase < 0.80:
        t = (phase - 0.70) / 0.10
        alpha = int(50 * t)
        color = (50 - int(30 * t), 20 - int(10 * t),
                 10 + int(30 * t))
    else:
        t = (phase - 0.80) / 0.05
        alpha = int(50 + 10 * t)
        color = (20 - int(10 * t), 10, 40 + int(10 * t))

    sz = surface.get_size()
    if (self._tint_surf is None
            or self._tint_surf.get_size() != sz):
        self._tint_surf = pygame.Surface(sz, pygame.SRCALPHA)
    self._tint_surf.fill((*color, alpha))
    surface.blit(self._tint_surf, (0, 0))
