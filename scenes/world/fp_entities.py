"""scenes/world/fp_entities.py — Entity billboard rendering.

Defines the entity-drawing methods attached to ``Renderer``:
``draw_entities``, ``_draw_billboards``, ``_draw_one_billboard``,
and ``_get_prop_surface``.
"""

from __future__ import annotations

import math
import operator
from typing import TYPE_CHECKING

import pygame

from core.tiles import PLATFORM_IDS, tile_def
from core.types import Direction
from components import (
    Position, Sprite, Player, Facing, Identity, Health, WallSprite,
)
from engine.raycaster import project_entities
from scenes.world.fp_lighting import build_fog_lut

if TYPE_CHECKING:
    from scenes.world.fp_renderer import Renderer

# Maximum distance for rendering entity billboards
_MAX_ENT_DIST = 14.0
# Distance beyond which we skip name tags / health bars
_DETAIL_DIST = 5.0
_TWO_PI = math.pi * 2.0

# ═════════════════════════════════════════════════════════════════════
#  Entity visual constants
# ═════════════════════════════════════════════════════════════════════

# Billboard texture map — character → prop key for textured rendering
PROP_GLYPHS: dict[str, str] = {
    "\u2261": "shelf",      # ≡ Shelf
    "\u25a1": "crate",      # □ Crate
    "\u25a0": "safe",       # ■ Safe
    "\u2550": "table",      # ═ Table
    "\u2592": "bookshelf",  # ▒ Bookcase
    "O": "barrel",
}

# Per-glyph visual properties: (height_scale, width_scale, is_billboard)
ENTITY_VIS: dict[str, tuple[float, float, bool]] = {
    # NPCs — always face camera
    "D": (0.75, 0.50, True),
    "N": (0.75, 0.50, True),
    "M": (0.75, 0.50, True),
    "V": (0.75, 0.50, True),
    # Round / symmetric objects
    "O": (0.45, 0.45, True),
    "\u2606": (0.25, 0.20, True),
    "\u2698": (0.40, 0.35, True),
    "#": (0.30, 0.30, True),
    "*": (0.15, 0.20, True),
    "C": (0.45, 0.45, True),
    # Flat furniture — facing-aware
    "\u2261": (0.60, 0.70, False),
    "\u25a1": (0.40, 0.45, False),
    "\u25a0": (0.35, 0.40, False),
    "\u2550": (0.35, 0.65, False),
    "\u2592": (0.70, 0.55, False),
    "h": (0.40, 0.35, False),
    "\u2500": (0.35, 0.75, False),
}
DEFAULT_VIS: tuple[float, float, bool] = (0.60, 0.50, True)

# Facing direction → raycaster angle
FACE_ANGLES: dict[Direction, float] = {
    Direction.UP:    math.pi * 1.5,
    Direction.DOWN:  math.pi * 0.5,
    Direction.LEFT:  math.pi,
    Direction.RIGHT: 0.0,
}


def _billboard_octant(
    angle_to_player: float,
    facing_angle: float,
) -> int:
    """Compute which of 8 sprite-frames to show (Doom-style).

    ``angle_to_player`` — atan2(ey-py, ex-px): direction FROM player TO entity
    ``facing_angle``    — the direction the entity faces (radians, 0=east)

    Returns an index 0–7 corresponding to:
        0 = entity facing directly toward camera
        4 = entity facing directly away from camera
    """
    delta = (angle_to_player - facing_angle) % _TWO_PI
    return int((delta + math.pi / 8.0) / (math.pi / 4.0)) % 8


# ══════════════════════════════════════════════════════════════════
#  draw_entities — main entry point
# ══════════════════════════════════════════════════════════════════

def draw_entities(
    self: "Renderer",
    surface: pygame.Surface,
    app,  # App
    zbuf_full: list[float],
    deferred_halves: list[tuple],
    sw: int, sh: int,
    px: float, py: float,
    angle: float, fov: float,
    dn: float, fog_rate: int,
    fog_lut: list[int],
    bob_offset: float,
    zone: str,
    tiles: list[list[int]],
    map_w: int, map_h: int,
    vp_data: tuple | None = None,
) -> None:
    """Draw entity billboards interleaved with deferred half-wall
    strips in painter's order (far → near)."""
    ent_data: list[tuple] = []
    _max_d2 = _MAX_ENT_DIST * _MAX_ENT_DIST
    for eid, epos, sprite in app.world.query_zone(zone, Position, Sprite):
        if app.world.has(eid, Player):
            continue
        # Skip entities with WallSprite — rendered by wall-entity system
        if app.world.has(eid, WallSprite):
            continue
        # Early distance cull before any other work
        _ddx = epos.x - px
        _ddy = epos.y - py
        if _ddx * _ddx + _ddy * _ddy > _max_d2:
            continue
        h_scale, w_scale, is_bb = ENTITY_VIS.get(
            sprite.char, DEFAULT_VIS
        )
        if not is_bb:
            fc = app.world.get(eid, Facing)
            if fc:
                fa = FACE_ANGLES.get(fc.direction, math.pi * 0.5)
                ca = math.atan2(epos.y - py, epos.x - px)
                w_scale *= max(0.20, abs(math.cos(fa - ca)))
        elev = 0.0
        col_i = int(epos.x)
        row_i = int(epos.y)
        if 0 <= row_i < map_h and 0 <= col_i < map_w:
            under_tid = tiles[row_i][col_i]
            if under_tid in PLATFORM_IDS:
                td = tile_def(under_tid)
                elev = td.height_scale

        # 8-way billboard: compute octant index for texture selection
        bb_mode = sprite.billboard_mode
        bb_key = sprite.sprite_key
        octant = -1
        if bb_mode == 1 and bb_key:
            fc = app.world.get(eid, Facing)
            if fc:
                fa = FACE_ANGLES.get(fc.direction, math.pi * 0.5)
                atp = math.atan2(epos.y - py, epos.x - px)
                octant = _billboard_octant(atp, fa)

        ent_data.append(
            (eid, epos.x, epos.y, sprite.char, sprite.color,
             h_scale, w_scale, elev, bb_mode, bb_key, octant)
        )

    if not ent_data and not deferred_halves:
        self._last_n_ents = 0
        self._last_n_bbs = 0
        return

    billboards = project_entities(
        px, py, angle, fov, sw, sh, ent_data,
    ) if ent_data else []
    self._last_n_ents = len(ent_data)
    self._last_n_bbs = len(billboards)
    zbuf = zbuf_full  # plain list — faster than numpy for per-entity small-span checks

    if not deferred_halves:
        _draw_billboards(
            self, surface, app, billboards, zbuf,
            sw, sh, dn, fog_rate, bob_offset,
        )
        return

    # ── Merge half-wall strips + billboards, sort far → near ──
    merged: list[tuple[float, int, object]] = []
    for hw in deferred_halves:
        merged.append((hw[0], 0, hw))
    for bb in billboards:
        merged.append((bb.distance, 1, bb))

    merged.sort(key=operator.itemgetter(0), reverse=True)

    _BLEND = pygame.BLEND_MULT
    _blit = surface.blit
    _fill = surface.fill

    bb_fog_lut = build_fog_lut(255, dn)
    _bob = bob_offset

    glyph_cache = self._glyph_cache
    if len(glyph_cache) > 400:
        for _k in list(glyph_cache)[:len(glyph_cache) // 2]:
            del glyph_cache[_k]

    if vp_data is not None:
        _vp_surf, _vp_top = vp_data
        _vp_h = _vp_surf.get_height()
        _vp_w = _vp_surf.get_width()
    else:
        _vp_surf = _vp_top = _vp_h = _vp_w = None  # type: ignore[assignment]

    for _dist, _tag, _data in merged:
        if _tag == 0:
            # ── Half-wall / transparent-wall strip ───────────
            (_, hw_surf, sx, cy0, cy1, col_w, draw_h,
             has_vp, hw_tid, hw_hs, hw_half,
             *_extra) = _data
            _is_trans = _extra[0] if _extra else False

            if has_vp and _vp_surf is not None:
                strip_h = min(_vp_h, cy0 - _vp_top)
                if strip_h > 0 and sx + col_w <= _vp_w:
                    _blit(_vp_surf, (sx, _vp_top),
                          (sx, 0, col_w, strip_h))

            if _is_trans:
                # Alpha-blended transparent wall (glass/fence)
                # Reuse shared SRCALPHA canvas from Renderer.
                _tw = hw_surf.get_width()
                _th = hw_surf.get_height()
                _tc = self._trans_canvas
                if _tw > _tc.get_width() or _th > _tc.get_height():
                    nw = max(_tw, _tc.get_width())
                    nh = max(_th, _tc.get_height())
                    self._trans_canvas = pygame.Surface(
                        (nw, nh), pygame.SRCALPHA)
                    _tc = self._trans_canvas
                _view = _tc.subsurface((0, 0, _tw, _th))
                _view.fill((0, 0, 0, 0))
                _view.blit(hw_surf, (0, 0))
                _view.fill((255, 255, 255, 140),
                           special_flags=pygame.BLEND_RGBA_MULT)
                _blit(_view, (sx, cy0))
            else:
                _blit(hw_surf, (sx, cy0))

            if not _is_trans and cy0 > 0:
                _fill(
                    (80, 78, 70),
                    (sx, cy0, col_w, 1),
                    special_flags=_BLEND,
                )
            if not _is_trans and cy1 < sh:
                _ao = min(4, max(1, draw_h >> 4))
                _ao_h = min(_ao, sh - cy1)
                if _ao_h > 0:
                    _fill(
                        (110, 110, 105),
                        (sx, cy1, col_w, _ao_h),
                        special_flags=_BLEND,
                    )
        else:
            # ── Entity billboard ─────────────────────────────
            _draw_one_billboard(
                self, surface, app, _data, zbuf,
                sw, sh, bb_fog_lut, _bob, glyph_cache,
            )


# ── internal: billboard-only fast path ───────────────────────────

def _draw_billboards(
    self: "Renderer",
    surface: pygame.Surface,
    app,
    billboards: list,
    zbuf: list[float],
    sw: int, sh: int,
    dn: float, fog_rate: int,
    bob_offset: float,
) -> None:
    """Fast path when there are no deferred half-walls."""
    bb_fog_lut = build_fog_lut(255, dn)
    _bob = bob_offset

    glyph_cache = self._glyph_cache
    if len(glyph_cache) > 400:
        for _k in list(glyph_cache)[:len(glyph_cache) // 2]:
            del glyph_cache[_k]

    for bb in billboards:
        _draw_one_billboard(
            self, surface, app, bb, zbuf,
            sw, sh, bb_fog_lut, _bob, glyph_cache,
        )


# ── single billboard rendering ───────────────────────────────────

def _draw_one_billboard(
    self: "Renderer",
    surface: pygame.Surface,
    app,
    bb,
    zbuf: list[float],
    sw: int, sh: int,
    bb_fog_lut: list[int],
    bob_offset: float,
    glyph_cache: dict,
) -> None:
    _BLEND = pygame.BLEND_MULT

    if bb.height < 2:
        return
    # Quantise to 16-px grid — coarser = far fewer cache misses
    ent_w = (bb.width if bb.width > 0 else bb.height) & ~15 or 16
    ent_h = bb.height & ~15 or 16
    if ent_w < 16:
        return

    dist = bb.distance
    fog_idx = min(255, int(dist * 8.0))
    fog = bb_fog_lut[fog_idx]

    dx = int(bb.screen_x - ent_w // 2)
    dy = int(bb.screen_y + bob_offset)

    left = max(0, dx)
    right = min(sw, dx + ent_w)
    if left >= right:
        return

    # ── Z-clip: fast-path samples 3 points ───────────────────
    _zbuf = zbuf
    mid = (left + right) >> 1
    if dist < _zbuf[left] and dist < _zbuf[right - 1] and dist < _zbuf[mid]:
        # Common case: fully visible — skip per-pixel loop
        vis_left = left
        vis_right = right
        single_span = True
    else:
        # Rare case: partially occluded — walk pixels
        vis_spans: list[tuple[int, int]] = []
        span_start = -1
        for _c in range(left, right):
            if dist < _zbuf[_c]:
                if span_start < 0:
                    span_start = _c
            else:
                if span_start >= 0:
                    vis_spans.append((span_start, _c))
                    span_start = -1
        if span_start >= 0:
            vis_spans.append((span_start, right))
        if not vis_spans:
            return
        single_span = False

    # ── Single shared canvas ─────────────────────────────────
    # We reuse ONE large Surface (created at Renderer init) for all
    # entity billboards.  subsurface() returns a zero-allocation
    # *view* into the shared pixel buffer, so there are NO runtime
    # pygame.Surface() calls — those cost ~40-50 ms on Windows
    # due to OS page-fault storms and were the root cause of every
    # entity rendering spike in the profiler logs.
    _canvas = self._ent_canvas
    if ent_w > _canvas.get_width() or ent_h > _canvas.get_height():
        # Extremely rare: entity bigger than canvas.  Grow once.
        nw = max(ent_w, _canvas.get_width())
        nh = max(ent_h, _canvas.get_height())
        self._ent_canvas = pygame.Surface((nw, nh))
        _canvas = self._ent_canvas
    ent_surf = _canvas.subsurface((0, 0, ent_w, ent_h))

    # ── Redraw entity content into the canvas every frame ────
    # 8-way billboard: use atlas texture keyed by sprite_key + octant
    if bb.bb_mode == 1 and bb.octant >= 0 and bb.bb_key:
        tex_key = f"{bb.bb_key}_{bb.octant}"
        try:
            src_surf = self._atlas.get_by_key(tex_key)
        except Exception:
            src_surf = None
        if src_surf is not None:
            pygame.transform.scale(src_surf, (ent_w, ent_h), ent_surf)
        else:
            # Fallback: tinted rect with glyph (missing texture)
            ent_surf.fill(bb.color)
            bw = 2 if min(ent_w, ent_h) > 12 else 1
            border = (max(0, bb.color[0] - 50),
                      max(0, bb.color[1] - 50),
                      max(0, bb.color[2] - 50))
            pygame.draw.rect(ent_surf, border,
                             (0, 0, ent_w, ent_h), bw)
    else:
        ent_surf.fill(bb.color)
        bw = 2 if min(ent_w, ent_h) > 12 else 1
        border = (max(0, bb.color[0] - 50),
                  max(0, bb.color[1] - 50),
                  max(0, bb.color[2] - 50))
        pygame.draw.rect(ent_surf, border,
                         (0, 0, ent_w, ent_h), bw)

        prop_key = PROP_GLYPHS.get(bb.char)
        if prop_key:
            tex_w = max(4, int(ent_w * 0.85))
            tex_h = max(4, int(ent_h * 0.85))
            prop_surf = _get_prop_surface(self, prop_key)
            _ox = (ent_w - tex_w) // 2
            _oy = (ent_h - tex_h) // 2
            if _ox >= 0 and _oy >= 0 and _ox + tex_w <= ent_w and _oy + tex_h <= ent_h:
                _dest = ent_surf.subsurface((_ox, _oy, tex_w, tex_h))
                pygame.transform.scale(prop_surf, (tex_w, tex_h), _dest)
        else:
            font_size = max(8, min(48, ent_h * 2 // 3))
            glyph_key = (bb.char, font_size)
            cached_g = glyph_cache.get(glyph_key)
            if cached_g is None:
                font = self.get_font(font_size)
                shadow = font.render(bb.char, True, (0, 0, 0))
                glyph = font.render(bb.char, True, (255, 255, 240))
                glyph_cache[glyph_key] = (shadow, glyph)
                cached_g = (shadow, glyph)
            shadow, glyph = cached_g
            gx = (ent_w - glyph.get_width()) // 2
            gy = (ent_h - glyph.get_height()) // 2
            ent_surf.blit(shadow, (gx + 1, gy + 1))
            ent_surf.blit(glyph, (gx, gy))

    # Blit visible spans, then apply fog via BLEND_MULT on destination
    _surf_blit = surface.blit
    _fog_fill = fog < 250
    _fog_col = (fog, fog, fog)
    if single_span:
        src_x = vis_left - dx
        src_w = vis_right - vis_left
        if src_w > 0 and src_x >= 0 and src_x + src_w <= ent_w:
            _surf_blit(ent_surf, (vis_left, dy),
                       (src_x, 0, src_w, ent_h))
            if _fog_fill:
                surface.fill(_fog_col,
                             (vis_left, dy, src_w, ent_h),
                             special_flags=_BLEND)
    else:
        for sp_l, sp_r in vis_spans:
            src_x = sp_l - dx
            src_w = sp_r - sp_l
            if (src_w > 0 and src_x >= 0
                    and src_x + src_w <= ent_w):
                _surf_blit(ent_surf, (sp_l, dy),
                           (src_x, 0, src_w, ent_h))
                if _fog_fill:
                    surface.fill(_fog_col,
                                 (sp_l, dy, src_w, ent_h),
                                 special_flags=_BLEND)

    # Skip health bars and name tags for distant entities
    if dist < _DETAIL_DIST:
        # Health bar
        hp = app.world.get(bb.eid, Health)
        if hp and hp.current < hp.maximum:
            bar_w = min(ent_w, 40)
            ratio = (max(0.0, hp.current / hp.maximum)
                     if hp.maximum > 0 else 0.0)
            bx = int(bb.screen_x - bar_w // 2)
            by = dy - 6
            pygame.draw.rect(surface, (60, 0, 0),
                             (bx, by, bar_w, 4))
            pygame.draw.rect(surface, (0, 200, 0),
                             (bx, by, int(bar_w * ratio), 4))

        # Name tag
        if dist < 4.0:
            ident = app.world.get(bb.eid, Identity)
            if ident:
                name_alpha = max(0.0, 1.0 - dist / 4.0)
                nc = int(200 * name_alpha)
                if nc > 30:
                    app.draw_text(
                        surface, ident.name,
                        int(bb.screen_x - len(ident.name) * 3),
                        dy - 14, (nc, nc, nc), app.font_sm,
                    )


# ── Prop texture helper ──────────────────────────────────────────

def _get_prop_surface(self: "Renderer", key: str) -> pygame.Surface:
    """Return the canonical source texture for *key*.

    Caches ONE Surface per prop type (~6 total).  The caller is
    responsible for scaling into a dest surface via
    ``pygame.transform.scale(src, (w, h), dest)`` — this avoids
    all runtime Surface allocations.
    """
    cached = self._prop_surfaces.get(key)
    if cached is not None:
        return cached
    from core.tiles import TILE_REGISTRY
    src = None
    for tid, td in TILE_REGISTRY.items():
        if td.texture_key == key:
            src = self._atlas.get(tid)
            break
    if src is None:
        src = self._atlas.get("void")
    self._prop_surfaces[key] = src
    return src
