"""scenes/world/fp_wall_entities.py — Wall-entity rendering.

Renders entities tagged with ``WallSprite`` as textured wall columns
in first-person mode — they look like real walls with correct perspective,
not billboards.  Supports sub-tile widths (crates, items on surfaces)
and elevation (objects sitting on top of platforms).

Attached to ``Renderer`` as ``draw_wall_entities``.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pygame

from components import Position, Sprite, Player, WallSprite
from core.tiles import PLATFORM_IDS, tile_def
from scenes.world.fp_lighting import build_fog_lut

if TYPE_CHECKING:
    from scenes.world.fp_renderer import Renderer

# Maximum render distance for wall entities
_MAX_DIST = 14.0


def draw_wall_entities(
    self: "Renderer",
    surface: pygame.Surface,
    app,
    zbuf: list[float],
    sw: int, sh: int,
    px: float, py: float,
    angle: float, fov: float,
    dn: float,
    bob_offset: float,
    zone: str,
    tiles: list[list[int]],
    map_w: int, map_h: int,
) -> None:
    """Draw all WallSprite entities as textured wall columns.

    Each wall-entity is treated as a small rectangular solid at its
    Position.  We compute the column range it covers on screen and
    render textured vertical strips — the same technique used for
    tile walls, but at the entity's width/height/elevation.
    """
    half_fov = fov * 0.5
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    _max_d2 = _MAX_DIST * _MAX_DIST
    fog_lut = build_fog_lut(255, dn)

    for eid, epos, ws in app.world.query_zone(zone, Position, WallSprite):
        if app.world.has(eid, Player):
            continue

        dx = epos.x - px
        dy = epos.y - py
        d2 = dx * dx + dy * dy
        if d2 > _max_d2:
            continue

        # Transform to camera space
        # perp_dist = component along view direction
        perp_dist = dx * cos_a + dy * sin_a
        if perp_dist < 0.15:
            continue

        # lateral offset
        lat = dx * (-sin_a) + dy * cos_a

        # Compute elevation: if entity sits on a platform, add that
        elev = ws.elevation
        if elev == 0.0:
            col_i = int(epos.x)
            row_i = int(epos.y)
            if 0 <= row_i < map_h and 0 <= col_i < map_w:
                under_tid = tiles[row_i][col_i]
                if under_tid in PLATFORM_IDS:
                    td = tile_def(under_tid)
                    elev = td.height_scale

        # Screen projection
        proj = (sh * 0.5) / perp_dist
        ent_h = ws.height
        ent_w = ws.width

        # Wall column height in pixels
        draw_h = int(proj * ent_h)
        if draw_h < 2:
            continue

        # Y position on screen (bottom of entity = floor + elevation)
        # Floor is at sh//2 + bob_offset (horizon line)
        horizon = sh * 0.5 + bob_offset
        # Bottom of the entity wall
        bottom_y = int(horizon + proj * (0.5 - elev))
        top_y = bottom_y - draw_h
        if bottom_y < 0 or top_y >= sh:
            continue

        # X range on screen
        half_w_world = ent_w * 0.5
        # Left and right edges in camera space
        x_left = lat - half_w_world
        x_right = lat + half_w_world

        # Convert to screen x using perspective
        screen_cx = sw * 0.5
        x_scale = sw / (2.0 * math.tan(half_fov))

        sx_left = int(screen_cx + x_left * x_scale / perp_dist)
        sx_right = int(screen_cx + x_right * x_scale / perp_dist)

        if sx_right <= 0 or sx_left >= sw:
            continue

        # Clamp to screen
        sx_left = max(0, sx_left)
        sx_right = min(sw, sx_right)
        col_span = sx_right - sx_left
        if col_span < 1:
            continue

        # Z-test: only draw pixels where this entity is closer
        visible = False
        for c in range(sx_left, sx_right):
            if perp_dist < zbuf[c]:
                visible = True
                break
        if not visible:
            continue

        # Get texture
        tex_surf = None
        if ws.texture_key:
            from core.tiles import TILE_REGISTRY
            if ws.texture_key not in self._prop_surfaces:
                src = None
                for tid, td in TILE_REGISTRY.items():
                    if td.texture_key == ws.texture_key:
                        src = self._atlas.get(tid)
                        break
                if src is None:
                    src = self._atlas.get("void")
                self._prop_surfaces[ws.texture_key] = src
            tex_surf = self._prop_surfaces[ws.texture_key]

        # Compute fog
        fog_idx = min(255, int(perp_dist * 8.0))
        fog = fog_lut[fog_idx]

        # Draw the entity as a solid colored/textured rectangle
        _top = max(0, top_y)
        _bot = min(sh, bottom_y)
        _draw_h = _bot - _top
        if _draw_h < 1:
            continue

        if tex_surf is not None:
            # Scale the texture to the column span
            try:
                scaled = pygame.transform.scale(tex_surf, (col_span, _draw_h))
                # Blit column by column with z-test
                for c in range(sx_left, sx_right):
                    if perp_dist < zbuf[c]:
                        src_x = c - sx_left
                        surface.blit(scaled, (c, _top), (src_x, 0, 1, _draw_h))
                        zbuf[c] = perp_dist
            except (pygame.error, ValueError):
                pass
        else:
            # Solid colour fallback
            sprite = app.world.get(eid, Sprite)
            color = sprite.color if sprite else (180, 140, 100)
            for c in range(sx_left, sx_right):
                if perp_dist < zbuf[c]:
                    pygame.draw.line(surface, color, (c, _top), (c, _bot - 1))
                    zbuf[c] = perp_dist

        # Apply fog
        if fog < 250:
            fog_col = (fog, fog, fog)
            surface.fill(
                fog_col,
                (sx_left, _top, col_span, _draw_h),
                special_flags=pygame.BLEND_MULT,
            )
