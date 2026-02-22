"""editor/canvas.py — Map canvas: tile rendering, coordinate transforms,
painting, entity markers, cursor preview.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pygame

# Add project root so imports work when running standalone
_root = str(Path(__file__).resolve().parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

from core.tiles import TILE_COLORS, TILE_NAMES, TILE_REGISTRY, tile_def, TF
from core.constants import TILE_SIZE, DIR_ARROWS
from editor.ui import Theme, draw_text
from editor.state import EditorState, Tool
from editor.layout import Layout


# ── Surface overlay mode ─────────────────────────────────────────────

class SurfaceOverlay:
    """Controls what surface data the canvas overlays on top of tiles."""
    NONE = "none"
    FLOOR_HEIGHT = "floor_height"
    CEIL_HEIGHT = "ceil_height"
    FLOOR_TEXTURE = "floor_texture"
    CEIL_TEXTURE = "ceil_texture"


class Canvas:
    """Handles the main tile map area — rendering and interaction."""

    def __init__(self, state: EditorState):
        self.state = state
        self.surface_overlay: str = SurfaceOverlay.NONE

    # ── Coordinate transforms ────────────────────────────────────

    def viewport_rect(self, surface: pygame.Surface) -> pygame.Rect:
        """Return the pixel rect of the map viewport."""
        L = Layout
        return pygame.Rect(L.canvas_x, L.canvas_y,
                           L.canvas_w, L.canvas_h)

    def screen_to_world(self, sx: int, sy: int,
                        surface: pygame.Surface) -> tuple[float, float]:
        vp = self.viewport_rect(surface)
        cx = vp.x + vp.w / 2
        cy = vp.y + vp.h / 2
        st = self.state
        wx = (sx - cx) / st.zoom - st.cam_x
        wy = (sy - cy) / st.zoom - st.cam_y
        return wx, wy

    def world_to_screen(self, wx: float, wy: float,
                        surface: pygame.Surface) -> tuple[int, int]:
        vp = self.viewport_rect(surface)
        cx = vp.x + vp.w / 2
        cy = vp.y + vp.h / 2
        st = self.state
        sx = int((wx + st.cam_x) * st.zoom + cx)
        sy = int((wy + st.cam_y) * st.zoom + cy)
        return sx, sy

    def screen_to_tile(self, sx: int, sy: int,
                       surface: pygame.Surface) -> tuple[int, int] | None:
        wx, wy = self.screen_to_world(sx, sy, surface)
        c = int(wx / TILE_SIZE)
        r = int(wy / TILE_SIZE)
        st = self.state
        if 0 <= r < st.map_h and 0 <= c < st.map_w:
            return r, c
        return None

    # ── Drawing ──────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, font: pygame.font.Font,
             font_sm: pygame.font.Font):
        vp = self.viewport_rect(surface)
        # Clip to viewport
        surface.set_clip(vp)
        try:
            # Background
            pygame.draw.rect(surface, Theme.BG, vp)

            st = self.state
            ts = int(TILE_SIZE * st.zoom)
            if ts < 1:
                return

            sw, sh = surface.get_size()

            # Draw tiles with enriched detail
            _ROT_ARROW = ("\u25B2", "\u25B6", "\u25BC", "\u25C0")  # N E S W
            _height_overlay = pygame.Surface((ts, ts), pygame.SRCALPHA) if ts >= 1 else None
            for r in range(st.map_h):
                for c in range(st.map_w):
                    sx, sy = self.world_to_screen(c * TILE_SIZE, r * TILE_SIZE,
                                                  surface)
                    if sx + ts < vp.x or sy + ts < vp.y or sx > vp.right or sy > vp.bottom:
                        continue
                    tid = st.tiles[r][c]
                    color = TILE_COLORS.get(tid, (120, 120, 120))
                    rect = pygame.Rect(sx, sy, ts, ts)
                    pygame.draw.rect(surface, color, rect)

                    # Subtle floor-height shading (darkens raised floors)
                    if (st.floor_heights and r < len(st.floor_heights)
                            and c < len(st.floor_heights[0])):
                        fh = st.floor_heights[r][c]
                        if fh > 0.001 and _height_overlay is not None:
                            alpha = min(80, int(fh * 120))
                            _height_overlay.fill((0, 0, 0, alpha))
                            surface.blit(_height_overlay, (sx, sy))

                    # Wall indicator: thick inner border
                    td = tile_def(tid)
                    if td and (td.flags & (TF.WALL | TF.SOLID)):
                        bw = max(2, ts // 8)
                        wall_col = tuple(max(0, ch - 50) for ch in color)
                        pygame.draw.rect(surface, wall_col, rect, bw)
                    elif st.show_grid and ts >= 8:
                        pygame.draw.rect(surface, Theme.GRID, rect, 1)

                    # Rotation arrow on non-zero-rotation tiles at zoom
                    if (ts >= 18 and st.rotations
                            and r < len(st.rotations)
                            and c < len(st.rotations[0])):
                        rot = st.rotations[r][c]
                        if rot != 0 and font_sm:
                            arrow = _ROT_ARROW[rot % 4]
                            glyph = font_sm.render(
                                arrow, True, (220, 220, 220))
                            gx = sx + (ts - glyph.get_width()) // 2
                            gy = sy + (ts - glyph.get_height()) // 2
                            surface.blit(glyph, (gx, gy))

            # Surface overlay (floor/ceiling height or texture visualization)
            if self.surface_overlay != SurfaceOverlay.NONE:
                self._draw_surface_overlay(surface, vp, ts, font_sm)

            # Draw entities (portals are entities with a portal component)
            self._draw_entities(surface, font, font_sm, ts)

            # Draw cursor
            self._draw_cursor(surface, ts, font_sm)
        finally:
            surface.set_clip(None)

    def _draw_entities(self, surface: pygame.Surface,
                       font: pygame.font.Font,
                       font_sm: pygame.font.Font,
                       ts: int):
        st = self.state
        for i, ent in enumerate(st.entities):
            is_sel = (i == st.selected_entity)

            # Portal entities — draw per-tile with portal styling
            if ent.portal is not None:
                ptl = ent.portal
                for tile in ptl.tiles:
                    if len(tile) < 2:
                        continue
                    r, c = tile[0], tile[1]
                    sx, sy = self.world_to_screen(
                        c * TILE_SIZE, r * TILE_SIZE, surface)
                    center = (sx + ts // 2, sy + ts // 2)
                    radius = max(4, ts // 3)
                    ring_col = Theme.ACCENT if is_sel else Theme.PORTAL
                    pygame.draw.circle(surface, ring_col, center, radius)
                    pygame.draw.circle(surface, (255, 255, 255),
                                       center, radius, 1)
                    if is_sel:
                        pygame.draw.circle(surface, Theme.ACCENT,
                                           center, radius + 2, 2)
                    if ts >= 16:
                        draw_text(surface, ptl.target_zone[:8],
                                  sx + 2, sy + ts + 1,
                                  Theme.TEXT_DIM, font_sm)
                        arrow = DIR_ARROWS.get(ptl.exit_direction, "?")
                        draw_text(surface, arrow,
                                  center[0] - 4, center[1] - 6,
                                  (255, 255, 255), font_sm)
                continue

            # Regular entities
            ex, ey = ent.position.x, ent.position.y
            sx, sy = self.world_to_screen(ex * TILE_SIZE, ey * TILE_SIZE,
                                          surface)

            sprite = ent.sprite
            if sprite is None:
                # Try prefab defaults
                if PREFAB_DEFAULTS:
                    defaults = PREFAB_DEFAULTS.get(ent.prefab, {})
                    sprite_d = defaults.get("sprite", {})
                    char = sprite_d.get("char", "?")
                    color = tuple(sprite_d.get("color", [200, 200, 200]))
                else:
                    char = "?"
                    color = (200, 200, 200)
            else:
                char = sprite.char
                color = tuple(sprite.color)

            name = ent.display_name

            radius = max(Layout.s(6), ts // 3)
            is_sel = (i == st.selected_entity)

            if ent.tile_entity is not None:
                ring_col = Theme.ACCENT if is_sel else Theme.ACCENT2
                half = radius
                pygame.draw.rect(surface, ring_col,
                                 (sx - half, sy - half,
                                  half * 2, half * 2), 2)
            else:
                ring_col = Theme.ACCENT if is_sel else Theme.ENTITY
                pygame.draw.circle(surface, ring_col, (sx, sy), radius, 2)

            if ts >= 12:
                glyph = font.render(char, True, color)
                surface.blit(glyph, (sx - glyph.get_width() // 2,
                                     sy - glyph.get_height() // 2))
            if ts >= 16 and name:
                label = name[:14]
                draw_text(surface, label,
                          sx - len(label) * 3, sy + radius + 2,
                          Theme.TEXT_DIM, font_sm)

    def _draw_cursor(self, surface: pygame.Surface, ts: int,
                     font_sm: pygame.font.Font | None = None):
        st = self.state
        if st.hover_tile is None:
            return
        r, c = st.hover_tile
        half = st.brush_size // 2

        # Surface editing mode: draw a distinct cursor
        if self.surface_overlay != SurfaceOverlay.NONE:
            for rr in range(r - half, r - half + st.brush_size):
                for cc in range(c - half, c - half + st.brush_size):
                    if 0 <= rr < st.map_h and 0 <= cc < st.map_w:
                        sx, sy = self.world_to_screen(
                            cc * TILE_SIZE, rr * TILE_SIZE, surface)
                        rect = pygame.Rect(sx, sy, ts, ts)
                        cursor_surf = pygame.Surface((ts, ts), pygame.SRCALPHA)
                        cursor_surf.fill((255, 255, 255, 40))
                        surface.blit(cursor_surf, (sx, sy))
                        pygame.draw.rect(surface, (255, 220, 80), rect, 2)
            return

        if st.tool in (Tool.BRUSH, Tool.ERASER, Tool.FILL):
            for rr in range(r - half, r - half + st.brush_size):
                for cc in range(c - half, c - half + st.brush_size):
                    if 0 <= rr < st.map_h and 0 <= cc < st.map_w:
                        sx, sy = self.world_to_screen(
                            cc * TILE_SIZE, rr * TILE_SIZE, surface)
                        rect = pygame.Rect(sx, sy, ts, ts)
                        cursor_surf = pygame.Surface((ts, ts), pygame.SRCALPHA)
                        if st.tool == Tool.ERASER:
                            cursor_surf.fill((255, 80, 80, 60))
                        else:
                            color = TILE_COLORS.get(st.selected_tile,
                                                    (200, 200, 200))
                            cursor_surf.fill((*color, 80))
                        surface.blit(cursor_surf, (sx, sy))
                        pygame.draw.rect(surface, (255, 255, 255), rect, 1)

            # Rotation direction arrow on centre cell
            if st.tool != Tool.ERASER and ts >= 14:
                cx_s, cy_s = self.world_to_screen(
                    c * TILE_SIZE, r * TILE_SIZE, surface)
                _ROT_ARROW = ("\u25B2", "\u25B6", "\u25BC", "\u25C0")  # N E S W
                arrow = _ROT_ARROW[st.pending_rotation % 4]
                if font_sm:
                    glyph = font_sm.render(arrow, True, (255, 255, 255))
                    gx = cx_s + (ts - glyph.get_width()) // 2
                    gy = cy_s + (ts - glyph.get_height()) // 2
                    surface.blit(glyph, (gx, gy))
        elif st.tool == Tool.SELECT:
            sx, sy = self.world_to_screen(c * TILE_SIZE, r * TILE_SIZE,
                                          surface)
            rect = pygame.Rect(sx, sy, ts, ts)
            pygame.draw.rect(surface, (255, 255, 255), rect, 1)
            # Pending entity placement ghost label
            if st.pending_prefab and ts >= 12:
                name = st.pending_prefab
                if name.startswith("forge:"):
                    name = name[6:]
                from editor.ui import draw_text as _dt
                _dt(surface, name[:12], sx + 2, sy - 12,
                    Theme.SUCCESS, font_sm)

    # ── Surface overlay drawing ──────────────────────────────────

    def _draw_surface_overlay(self, surface: pygame.Surface,
                              vp: pygame.Rect, ts: int,
                              font_sm: pygame.font.Font | None):
        """Draw a colored overlay showing floor/ceiling heights or textures."""
        st = self.state
        mode = self.surface_overlay
        overlay = pygame.Surface((ts, ts), pygame.SRCALPHA)

        for r in range(st.map_h):
            for c in range(st.map_w):
                sx, sy = self.world_to_screen(
                    c * TILE_SIZE, r * TILE_SIZE, surface)
                if (sx + ts < vp.x or sy + ts < vp.y
                        or sx > vp.right or sy > vp.bottom):
                    continue

                if mode == SurfaceOverlay.FLOOR_HEIGHT:
                    grid = st.floor_heights
                    if not grid or r >= len(grid) or c >= len(grid[0]):
                        continue
                    val = grid[r][c]
                    # Color: blue(0.0) → green(0.5) → yellow(1.0)
                    t = max(0.0, min(1.0, val))
                    if t < 0.5:
                        f = t * 2.0
                        cr = int(40 * (1 - f))
                        cg = int(40 + 160 * f)
                        cb = int(200 * (1 - f))
                    else:
                        f = (t - 0.5) * 2.0
                        cr = int(40 + 200 * f)
                        cg = int(200 - 40 * f)
                        cb = 0
                    alpha = 100 if val > 0.001 else 30
                    overlay.fill((cr, cg, cb, alpha))
                    surface.blit(overlay, (sx, sy))
                    # Label if zoomed in enough
                    if ts >= 24 and font_sm and val > 0.001:
                        lbl = f"{val:.2f}"
                        draw_text(surface, lbl, sx + 2, sy + 2,
                                  (255, 255, 255), font_sm)

                elif mode == SurfaceOverlay.CEIL_HEIGHT:
                    grid = st.ceil_heights
                    if not grid or r >= len(grid) or c >= len(grid[0]):
                        continue
                    val = grid[r][c]
                    # Color: red(low) → purple(1.0) → cyan(2.0)
                    t = max(0.0, min(1.0, val / 2.0))
                    cr = int(200 * (1 - t))
                    cg = int(50 + 150 * t)
                    cb = int(80 + 170 * t)
                    alpha = 100 if abs(val - 1.0) > 0.01 else 30
                    overlay.fill((cr, cg, cb, alpha))
                    surface.blit(overlay, (sx, sy))
                    if ts >= 24 and font_sm and abs(val - 1.0) > 0.01:
                        lbl = f"{val:.2f}"
                        draw_text(surface, lbl, sx + 2, sy + 2,
                                  (255, 255, 255), font_sm)

                elif mode == SurfaceOverlay.FLOOR_TEXTURE:
                    grid = st.floor_textures
                    if not grid or r >= len(grid) or c >= len(grid[0]):
                        continue
                    tex = grid[r][c]
                    if tex:
                        overlay.fill((60, 180, 60, 80))
                        surface.blit(overlay, (sx, sy))
                        if ts >= 20 and font_sm:
                            lbl = tex[:6]
                            draw_text(surface, lbl, sx + 1, sy + 1,
                                      (200, 255, 200), font_sm)

                elif mode == SurfaceOverlay.CEIL_TEXTURE:
                    grid = st.ceil_textures
                    if not grid or r >= len(grid) or c >= len(grid[0]):
                        continue
                    tex = grid[r][c]
                    if tex:
                        overlay.fill((60, 60, 180, 80))
                        surface.blit(overlay, (sx, sy))
                        if ts >= 20 and font_sm:
                            lbl = tex[:6]
                            draw_text(surface, lbl, sx + 1, sy + 1,
                                      (200, 200, 255), font_sm)


# ── Public import of prefab defaults ─────────────────────────────────

from systems.spawner import PREFAB_DEFAULTS, get_prefab_defaults  # noqa: F401
