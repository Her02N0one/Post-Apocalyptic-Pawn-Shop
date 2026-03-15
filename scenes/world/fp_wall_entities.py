"""scenes/world/fp_wall_entities.py — Wall-entity rendering (3D cubes).

Renders entities tagged with ``WallSprite`` or ``PrismShape`` as textured
3D rectangular solids in first-person mode.  Each solid has 4 vertical
faces that are back-face culled and perspective-projected column-by-column.

This gives crates, shelves, TVs, vending machines etc. true depth and
parallax — they look like real walls, not paper billboards.

Attached to ``Renderer`` as ``draw_wall_entities``.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pygame

from components import Position, Sprite, Player, Facing, WallSprite, PrismShape
from core.tiles import PLATFORM_IDS, tile_def
from core.types import Direction
from scenes.world.fp_lighting import build_fog_lut

if TYPE_CHECKING:
    from scenes.world.fp_renderer import Renderer

# Maximum render distance for wall entities
_MAX_DIST = 14.0

# Facing direction → angle in radians (same as fp_entities.py)
_FACE_ANGLES: dict[Direction, float] = {
    Direction.UP:    math.pi * 1.5,
    Direction.DOWN:  math.pi * 0.5,
    Direction.LEFT:  math.pi,
    Direction.RIGHT: 0.0,
}


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
    """Draw WallSprite and PrismShape entities as perspective-correct 3D solids.

    For each entity we define 4 vertical faces (front/back/left/right)
    based on the entity's rotation.  Each face is projected into screen
    space and drawn column-by-column with z-testing.  Back-facing faces
    are culled.
    """
    half_fov = fov * 0.5
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    _max_d2 = _MAX_DIST * _MAX_DIST
    fog_lut = build_fog_lut(255, dn)
    _tan_half = math.tan(half_fov)
    x_scale = (sw * 0.5) / _tan_half
    horizon = sh * 0.5 + bob_offset
    _BLEND = pygame.BLEND_MULT
    _get_by_key = self._atlas.get_by_key

    # ── Collect all solid-body entities into a uniform list ─────
    # Each item: (ex, ey, hw, hd, ent_height, elev, ent_angle,
    #             face_textures, base_color)
    # face_textures: (front_surf, right_surf, back_surf, left_surf) or None
    solid_bodies: list[tuple] = []

    # 1. WallSprite entities (legacy path)
    for eid, epos, ws in app.world.query_zone(zone, Position, WallSprite):
        if app.world.has(eid, Player):
            continue
        ex, ey = epos.x, epos.y
        dx = ex - px
        dy = ey - py
        if dx * dx + dy * dy > _max_d2:
            continue

        fc = app.world.get(eid, Facing)
        ent_angle = _FACE_ANGLES.get(fc.direction, 0.0) if fc else 0.0

        hw = ws.width * 0.5
        hd = ws.width * 0.5  # cube: depth == width

        elev = ws.elevation
        if elev == 0.0:
            col_i = int(ex)
            row_i = int(ey)
            if 0 <= row_i < map_h and 0 <= col_i < map_w:
                under_tid = tiles[row_i][col_i]
                if under_tid in PLATFORM_IDS:
                    td = tile_def(under_tid)
                    elev = td.height_scale

        # Resolve single texture for all faces
        tex_surf = None
        if ws.texture_key:
            tex_surf = self._prop_surfaces.get(ws.texture_key)
            if tex_surf is None:
                from core.tiles import TILE_REGISTRY
                src = None
                for tid, td_r in TILE_REGISTRY.items():
                    if td_r.texture_key == ws.texture_key:
                        src = self._atlas.get(tid)
                        break
                if src is None:
                    src = self._atlas.get("void")
                self._prop_surfaces[ws.texture_key] = src
                tex_surf = src
        face_textures = (tex_surf, tex_surf, tex_surf, tex_surf)

        sprite = app.world.get(eid, Sprite)
        base_color = sprite.color if sprite else (180, 140, 100)

        solid_bodies.append((
            ex, ey, hw, hd, ws.height, elev, ent_angle,
            face_textures, base_color,
        ))

    # 2. PrismShape entities
    for eid, epos, prism in app.world.query_zone(zone, Position, PrismShape):
        if app.world.has(eid, Player):
            continue
        ex, ey = epos.x, epos.y
        dx = ex - px
        dy = ey - py
        if dx * dx + dy * dy > _max_d2:
            continue

        hw = prism.width * 0.5
        hd = prism.depth * 0.5
        ent_angle = prism.yaw

        elev = prism.elevation
        if elev == 0.0:
            col_i = int(ex)
            row_i = int(ey)
            if 0 <= row_i < map_h and 0 <= col_i < map_w:
                under_tid = tiles[row_i][col_i]
                if under_tid in PLATFORM_IDS:
                    td = tile_def(under_tid)
                    elev = td.height_scale

        # Per-face textures from the prism
        tex = prism.textures
        def _surf(face_key: str) -> pygame.Surface | None:
            k = tex.get(face_key, "")
            return _get_by_key(k) if k else None
        # Face order: front(0), right(1), back(2), left(3)
        # Corner layout:  3---2  back
        #                 |   |  left=3→0  right=1→2
        #                 0---1  front
        # Front = -Y local = south in editor = "north" texture (N↔S swap)
        # Back  = +Y local = north in editor = "south" texture
        face_textures = (
            _surf("north"),   # front face (-Y local)
            _surf("east"),    # right face (+X local)
            _surf("south"),   # back face  (+Y local)
            _surf("west"),    # left face  (-X local)
        )

        sprite = app.world.get(eid, Sprite)
        base_color = sprite.color if sprite else (120, 120, 140)

        solid_bodies.append((
            ex, ey, hw, hd, prism.height, elev, ent_angle,
            face_textures, base_color,
        ))

    # ── Render all solid bodies ────────────────────────────────
    for (ex, ey, hw, hd, ent_height, elev, ent_angle,
         face_textures, base_color) in solid_bodies:
        cos_e = math.cos(ent_angle)
        sin_e = math.sin(ent_angle)

        # Define 4 corners of the entity's base rectangle in world space
        # relative to entity center, rotated by ent_angle.
        #  3 --- 2   (back face: 3→2)
        #  |     |   (left: 0→3, right: 2→1)
        #  0 --- 1   (front face: 0→1)
        corners_local = [
            (-hw, -hd),  # 0: front-left
            ( hw, -hd),  # 1: front-right
            ( hw,  hd),  # 2: back-right
            (-hw,  hd),  # 3: back-left
        ]
        corners_world = []
        for cx, cy in corners_local:
            wx = ex + cx * cos_e - cy * sin_e
            wy = ey + cx * sin_e + cy * cos_e
            corners_world.append((wx, wy))

        faces = [
            (0, 1),  # front
            (1, 2),  # right side
            (2, 3),  # back
            (3, 0),  # left side
        ]

        for fi, (ci_a, ci_b) in enumerate(faces):
            ax, ay = corners_world[ci_a]
            bx, by = corners_world[ci_b]
            face_surf = face_textures[fi] if face_textures else None

            # Back-face culling: face normal should point toward camera
            # edge vector
            edge_x = bx - ax
            edge_y = by - ay
            # Normal = perpendicular, pointing outward (-90°)
            normal_x = edge_y
            normal_y = -edge_x
            # Midpoint of edge
            mid_x = (ax + bx) * 0.5
            mid_y = (ay + by) * 0.5
            # Vector from midpoint to camera
            to_cam_x = px - mid_x
            to_cam_y = py - mid_y
            # Dot product — negative means facing away
            dot = normal_x * to_cam_x + normal_y * to_cam_y
            if dot <= 0:
                continue

            # Transform both corners to camera space
            dax = ax - px
            day = ay - py
            dbx = bx - px
            dby = by - py

            # Along view direction (depth)
            za = dax * cos_a + day * sin_a
            zb = dbx * cos_a + dby * sin_a

            # Both behind camera
            if za < 0.05 and zb < 0.05:
                continue

            # Lateral (perpendicular to view)
            la = dax * (-sin_a) + day * cos_a
            lb = dbx * (-sin_a) + dby * cos_a

            # Clip to near plane if needed
            if za < 0.05:
                t = (0.05 - za) / (zb - za + 1e-10)
                za = 0.05
                la = la + t * (lb - la)
            elif zb < 0.05:
                t = (0.05 - zb) / (za - zb + 1e-10)
                zb = 0.05
                lb = lb + t * (la - lb)

            # Project to screen x
            scx = sw * 0.5
            sxa = int(scx + la * x_scale / za)
            sxb = int(scx + lb * x_scale / zb)

            # Ensure left-to-right
            if sxa > sxb:
                sxa, sxb = sxb, sxa
                za, zb = zb, za
                flip_u = True
            else:
                flip_u = False

            if sxb <= 0 or sxa >= sw:
                continue

            col_count = sxb - sxa
            if col_count < 1:
                continue

            # For each screen column, interpolate depth and draw
            for c in range(max(0, sxa), min(sw, sxb)):
                t_col = (c - sxa) / (col_count) if col_count > 0 else 0.0
                # Perspective-correct interpolation
                inv_za = 1.0 / za
                inv_zb = 1.0 / zb
                inv_z = inv_za + t_col * (inv_zb - inv_za)
                col_depth = 1.0 / inv_z if inv_z > 1e-10 else 1e10

                if col_depth >= zbuf[c]:
                    continue

                # Wall column height at this depth
                # proj = half-wall in pixels; full wall = 2*proj
                proj = sh / (2.0 * col_depth)
                draw_h = int(2.0 * proj * ent_height)
                if draw_h < 1:
                    continue

                bottom_y = int(horizon + proj * (1.0 - elev))
                top_y = bottom_y - draw_h

                _top = max(0, top_y)
                _bot = min(sh, bottom_y)
                _dh = _bot - _top
                if _dh < 1:
                    continue

                # Texture U coordinate
                u = t_col if flip_u else (1.0 - t_col)

                if face_surf is not None:
                    tw = face_surf.get_width()
                    th = face_surf.get_height()
                    tx = int(u * tw) % tw

                    # V coords (same as wall rendering)
                    v_top = (top_y - _top) / draw_h if draw_h > 0 else 0.0
                    v0 = max(0, int(((_top - top_y) / draw_h) * th))
                    v1 = min(th, max(v0 + 1, int(((_bot - top_y) / draw_h) * th)))

                    try:
                        strip = face_surf.subsurface((tx, v0, 1, v1 - v0))
                        scaled = pygame.transform.scale(strip, (1, _dh))
                        surface.blit(scaled, (c, _top))
                    except (pygame.error, ValueError):
                        pygame.draw.line(surface, base_color,
                                         (c, _top), (c, _bot - 1))
                else:
                    # Darken side faces slightly for depth cue
                    if fi == 1 or fi == 3:
                        col = (max(0, base_color[0] - 30),
                               max(0, base_color[1] - 30),
                               max(0, base_color[2] - 30))
                    else:
                        col = base_color
                    pygame.draw.line(surface, col, (c, _top), (c, _bot - 1))

                zbuf[c] = col_depth

            # Fog for this face span
            sxa_c = max(0, sxa)
            sxb_c = min(sw, sxb)
            if sxa_c < sxb_c:
                mid_depth = (za + zb) * 0.5
                fog_idx = min(255, int(mid_depth * 8.0))
                fog = fog_lut[fog_idx]
                if fog < 250:
                    # Also darken side faces
                    if fi == 1 or fi == 3:
                        fog = max(0, fog - 20)
                    fog_col = (fog, fog, fog)
                    # Find the actual drawn extent
                    proj_mid = sh / (2.0 * mid_depth) if mid_depth > 0.05 else 200
                    draw_h_mid = int(2.0 * proj_mid * ent_height)
                    _bot_fog = int(horizon + proj_mid * (1.0 - elev))
                    _top_fog = max(0, _bot_fog - draw_h_mid)
                    _bot_fog = min(sh, _bot_fog)
                    _dh_fog = _bot_fog - _top_fog
                    if _dh_fog > 0:
                        surface.fill(
                            fog_col,
                            (sxa_c, _top_fog, sxb_c - sxa_c, _dh_fog),
                            special_flags=_BLEND,
                        )
