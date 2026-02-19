"""scenes/world/fp_hud.py — First-person HUD / overlay drawing.

Health bar, crosshair, minimap, compass, toast notifications,
debug overlay.  Split from firstperson.py for maintainability.
"""

from __future__ import annotations

import math

import pygame

from core.tiles import SOLID_IDS, HALF_WALL_IDS, DOOR_IDS
from core.types import EntityKind
from components import (
    Position, Sprite, Player, Inventory, Identity,
    TileEntity, Health, GameClock, WorldClock, WorldEventLog,
)
from systems.interaction import nearest_interactable
from scenes.world.fp_renderer import FOV

# ═════════════════════════════════════════════════════════════════════
#  Compass data
# ═════════════════════════════════════════════════════════════════════

_COMPASS_POINTS = [
    (0.0, "E"), (math.pi * 0.25, "SE"), (math.pi * 0.5, "S"),
    (math.pi * 0.75, "SW"), (math.pi, "W"), (math.pi * 1.25, "NW"),
    (math.pi * 1.5, "N"), (math.pi * 1.75, "NE"),
]

_NOTIFICATION_COLORS = {
    "combat": (255, 100, 100),
    "travel": (100, 200, 255),
    "loot":   (255, 220, 100),
    "info":   (180, 180, 180),
}


# ═════════════════════════════════════════════════════════════════════
#  HUD
# ═════════════════════════════════════════════════════════════════════


class HUD:
    """First-person heads-up display and overlays."""

    def __init__(self) -> None:
        self._font_cache: dict[int, pygame.font.Font] = {}
        # Minimap caches
        self._mm_base: pygame.Surface | None = None
        self._mm_zone: str = ""
        self._mm_tiles_hash: int = 0
        self._mm_cone: pygame.Surface | None = None
        # Compass caches
        self._compass_bg: pygame.Surface | None = None
        self._compass_labels: dict | None = None

    # ── Font cache ───────────────────────────────────────────────

    def _get_font(self, size: int) -> pygame.font.Font:
        size = max(8, min(72, size))
        size = (size // 2) * 2
        if size not in self._font_cache:
            self._font_cache[size] = pygame.font.SysFont("monospace", size)
        return self._font_cache[size]

    # ══════════════════════════════════════════════════════════════
    #  Main HUD
    # ══════════════════════════════════════════════════════════════

    def draw_hud(
        self,
        surface: pygame.Surface,
        app,
        sw: int, sh: int,
        modals_open: bool,
        session,
    ) -> None:
        # Health bar
        result = app.world.query_one(Player, Health)
        if result:
            _, _, hp = result
            bar_x, bar_y = 10, sh - 30
            bar_w, bar_h = 120, 12
            ratio = (max(0.0, hp.current / hp.maximum)
                     if hp.maximum > 0 else 0.0)
            pygame.draw.rect(surface, (40, 0, 0),
                             (bar_x - 1, bar_y - 1,
                              bar_w + 2, bar_h + 2))
            pygame.draw.rect(surface, (60, 0, 0),
                             (bar_x, bar_y, bar_w, bar_h))
            hp_r = int(220 * (1.0 - ratio))
            hp_g = int(200 * ratio)
            pygame.draw.rect(surface, (hp_r, hp_g, 0),
                             (bar_x, bar_y,
                              int(bar_w * ratio), bar_h))
            app.draw_text(surface,
                          f"{int(hp.current)}/{int(hp.maximum)} HP",
                          bar_x + bar_w + 6, bar_y - 1,
                          (200, 200, 200), app.font_sm)

        # Inventory count
        inv_res = app.world.query_one(Player, Inventory)
        if inv_res:
            _, _, inv = inv_res
            total = sum(inv.items.values())
            if total > 0:
                app.draw_text(surface, f"\u25a0 {total}",
                              140, sh - 30, (180, 170, 140),
                              app.font_sm)

        # Crosshair
        cx, cy = sw // 2, sh // 2
        pygame.draw.line(surface, (200, 200, 200),
                         (cx - 8, cy), (cx - 3, cy))
        pygame.draw.line(surface, (200, 200, 200),
                         (cx + 3, cy), (cx + 8, cy))
        pygame.draw.line(surface, (200, 200, 200),
                         (cx, cy - 8), (cx, cy - 3))
        pygame.draw.line(surface, (200, 200, 200),
                         (cx, cy + 3), (cx, cy + 8))
        pygame.draw.circle(surface, (220, 220, 220), (cx, cy), 1)

        # Zone name
        app.draw_text(surface, session.zone_name, sw - 100, 10,
                      (120, 140, 130), app.font_sm)

        # World clock
        wc = app.world.resources.try_get(WorldClock)
        if wc:
            hour = int(wc.day_phase * 24) % 24
            minute = int((wc.day_phase * 24 * 60) % 60)
            time_str = f"Day {wc.day + 1}  {hour:02d}:{minute:02d}"
            if 0.25 <= wc.day_phase < 0.75:
                time_col = (220, 200, 140)
            elif 0.75 <= wc.day_phase < 0.85:
                time_col = (220, 140, 80)
            elif wc.day_phase >= 0.85 or wc.day_phase < 0.15:
                time_col = (100, 120, 180)
            else:
                time_col = (180, 160, 120)
            app.draw_text(surface, time_str, sw - 100, 24,
                          time_col, app.font_sm)
            if wc.time_scale > 1.0:
                app.draw_text(
                    surface,
                    f"\u25b6\u25b6{int(wc.time_scale)}\u00d7",
                    sw - 100, 38, (255, 180, 60), app.font_sm,
                )

        # Interaction prompt
        target = nearest_interactable(app.world)
        if target and not modals_open:
            t_eid, _ = target
            ident = app.world.get(t_eid, Identity)
            te = app.world.get(t_eid, TileEntity)
            name = ident.name if ident else f"Entity #{t_eid}"
            if te and te.tile_type == "ground_item":
                label = f"[E] Pick up {name}"
            elif te and te.tile_type == "container":
                label = f"[E] Open {name}"
            elif ident and ident.kind == EntityKind.NPC:
                label = f"[E] Talk to {name}"
            else:
                label = f"[E] {name}"
            tw = len(label) * 7 + 12
            pill = pygame.Surface((tw, 20), pygame.SRCALPHA)
            pill.fill((0, 0, 0, 120))
            surface.blit(pill, (sw // 2 - tw // 2, sh - 54))
            app.draw_text(surface, label,
                          sw // 2 - tw // 2 + 6, sh - 52,
                          (255, 230, 150), app.font_sm)

        # Status label
        if session.status_timer > 0 and session.status:
            alpha = min(1.0, session.status_timer / 0.5)
            c = int(220 * alpha)
            app.draw_text_bg(surface, session.status,
                             sw // 2 - 80, 40, (c, c, c))

        # Controls hint
        app.draw_text(
            surface,
            "WASD=move  Shift=sprint  Mouse=look  E=interact"
            "  I=inv  Tab=debug  Esc=cursor",
            10, sh - 14, (80, 100, 90), app.font_sm,
        )

    # ══════════════════════════════════════════════════════════════
    #  Toast notifications
    # ══════════════════════════════════════════════════════════════

    def draw_notifications(
        self,
        surface: pygame.Surface,
        app,
    ) -> None:
        event_log = app.world.resources.try_get(WorldEventLog)
        if event_log is None or not event_log.entries:
            return

        sw, sh = surface.get_size()
        clock = app.world.resources.try_get(GameClock)
        now = clock.time if clock else 0.0

        max_show = 5
        y = 50
        shown = 0

        for entry in reversed(event_log.entries):
            age = now - entry.time
            if age > 8.0:
                break
            if shown >= max_show:
                break
            if age > 5.0:
                fade = 1.0 - (age - 5.0) / 3.0
            else:
                fade = 1.0

            color = _NOTIFICATION_COLORS.get(entry.category,
                                             (180, 180, 180))
            color = tuple(int(c * fade) for c in color)

            text = entry.message
            tw = len(text) * 7
            bx = sw - tw - 20
            by = y
            bg_surf = pygame.Surface((tw + 12, 18), pygame.SRCALPHA)
            bg_surf.fill((0, 0, 0, int(120 * fade)))
            surface.blit(bg_surf, (bx - 4, by - 2))

            app.draw_text(surface, text, bx, by, color, app.font_sm)
            y += 20
            shown += 1

        event_log.unread = 0

    # ══════════════════════════════════════════════════════════════
    #  Compass bar
    # ══════════════════════════════════════════════════════════════

    def draw_compass(
        self,
        surface: pygame.Surface,
        sw: int,
        player_angle: float,
    ) -> None:
        bar_w = min(260, sw - 40)
        bar_h = 16
        bx = (sw - bar_w) // 2
        by = 4

        if (self._compass_bg is None
                or self._compass_bg.get_width() != bar_w):
            self._compass_bg = pygame.Surface((bar_w, bar_h),
                                              pygame.SRCALPHA)
            self._compass_bg.fill((0, 0, 0, 100))
        surface.blit(self._compass_bg, (bx, by))

        cx = bx + bar_w // 2
        pygame.draw.line(surface, (255, 255, 200),
                         (cx, by), (cx, by + 3))

        if self._compass_labels is None:
            font = self._get_font(10)
            self._compass_labels = {}
            for pt_ang, label in _COMPASS_POINTS:
                col = ((255, 240, 180) if len(label) == 1
                       else (140, 140, 120))
                self._compass_labels[label] = (
                    pt_ang, col, font.render(label, True, col),
                )

        ang = player_angle % (2 * math.pi)
        half_bar = bar_w * 0.5
        _pi = math.pi
        for label, (pt_ang, col, txt) in self._compass_labels.items():
            diff = (pt_ang - ang + _pi) % (2 * _pi) - _pi
            frac = diff / _pi
            px_off = int(frac * half_bar)
            lx = cx + px_off
            if lx < bx or lx > bx + bar_w:
                continue
            if len(label) == 1:
                pygame.draw.line(surface, col,
                                 (lx, by + bar_h - 4),
                                 (lx, by + bar_h))
            else:
                pygame.draw.line(surface, col,
                                 (lx, by + bar_h - 2),
                                 (lx, by + bar_h))
            surface.blit(txt,
                         (lx - txt.get_width() // 2, by + 1))

    # ══════════════════════════════════════════════════════════════
    #  Minimap
    # ══════════════════════════════════════════════════════════════

    def draw_minimap(
        self,
        surface: pygame.Surface,
        app,
        px: float, py: float,
        sw: int, sh: int,
        player_angle: float,
        session,
    ) -> None:
        tiles = session.tiles
        mw = session.map_w
        mh = session.map_h
        if not tiles:
            return

        cell = 4
        mm_w = mw * cell
        mm_h = mh * cell
        mm_x = sw - mm_w - 8
        mm_y = 24

        zone = session.zone_name
        tiles_id = id(tiles)
        if (self._mm_base is None
                or self._mm_zone != zone
                or self._mm_tiles_hash != tiles_id):
            base = pygame.Surface((mm_w + 2, mm_h + 2),
                                  pygame.SRCALPHA)
            base.fill((0, 0, 0, 160))
            for row in range(mh):
                for col in range(mw):
                    tid = tiles[row][col]
                    if tid in SOLID_IDS:
                        if tid in HALF_WALL_IDS:
                            color = (120, 110, 90)
                        else:
                            color = (150, 150, 160)
                    elif tid in DOOR_IDS:
                        color = (80, 160, 200)
                    else:
                        color = (40, 45, 35)
                    pygame.draw.rect(
                        base, color,
                        (1 + col * cell, 1 + row * cell,
                         cell, cell),
                    )
            pygame.draw.rect(base, (80, 80, 90),
                             (0, 0, mm_w + 2, mm_h + 2), 1)
            self._mm_base = base
            self._mm_zone = zone
            self._mm_tiles_hash = tiles_id

        surface.blit(self._mm_base, (mm_x - 1, mm_y - 1))

        # Entities
        for eid, epos, sprite in app.world.query(Position, Sprite):
            if epos.zone != zone:
                continue
            if app.world.has(eid, Player):
                continue
            ex = mm_x + int(epos.x * cell)
            ey = mm_y + int(epos.y * cell)
            ident = app.world.get(eid, Identity)
            if ident and ident.kind == EntityKind.NPC:
                pts = [(ex, ey - 2), (ex + 2, ey),
                       (ex, ey + 2), (ex - 2, ey)]
                pygame.draw.polygon(surface, (100, 255, 100), pts)
            else:
                pygame.draw.circle(surface, sprite.color,
                                   (ex, ey), max(1, cell // 2))

        # Player + FOV cone
        ppx = mm_x + int(px * cell)
        ppy = mm_y + int(py * cell)
        cone_len = cell * 5
        half_fov = FOV * 0.5
        left_ang = player_angle - half_fov
        right_ang = player_angle + half_fov
        cone_pts = [
            (ppx, ppy),
            (ppx + int(math.cos(left_ang) * cone_len),
             ppy + int(math.sin(left_ang) * cone_len)),
            (ppx + int(math.cos(right_ang) * cone_len),
             ppy + int(math.sin(right_ang) * cone_len)),
        ]

        mm_size = (mm_w + 2, mm_h + 2)
        if (self._mm_cone is None
                or self._mm_cone.get_size() != mm_size):
            self._mm_cone = pygame.Surface(mm_size, pygame.SRCALPHA)
        self._mm_cone.fill((0, 0, 0, 0))
        local_pts = [(x - mm_x + 1, y - mm_y + 1)
                     for x, y in cone_pts]
        pygame.draw.polygon(self._mm_cone,
                            (255, 255, 100, 40), local_pts)
        surface.blit(self._mm_cone, (mm_x - 1, mm_y - 1))

        pygame.draw.circle(surface, (255, 255, 100),
                           (ppx, ppy), max(2, cell))
        end_x = ppx + int(math.cos(player_angle) * cell * 3)
        end_y = ppy + int(math.sin(player_angle) * cell * 3)
        pygame.draw.line(surface, (255, 255, 100),
                         (ppx, ppy), (end_x, end_y), 1)

    # ══════════════════════════════════════════════════════════════
    #  Debug overlay
    # ══════════════════════════════════════════════════════════════

    def draw_debug(
        self,
        surface: pygame.Surface,
        app,
        px: float, py: float,
        player_angle: float,
        zone_name: str,
    ) -> None:
        y = 30
        fps = app.clock.get_fps()
        app.draw_text_bg(surface, f"FPS: {fps:.0f}",
                         10, y, (0, 255, 200))
        y += 16
        app.draw_text_bg(
            surface,
            f"Pos: ({px:.1f}, {py:.1f})"
            f"  Ang: {math.degrees(player_angle):.0f}\u00b0",
            10, y, (0, 255, 200),
        )
        y += 16
        n = len(app.world.zone_entities(zone_name))
        app.draw_text_bg(surface, f"Entities: {n}",
                         10, y, (0, 255, 200))
        y += 16
        clock = app.world.resources.try_get(GameClock)
        if clock:
            app.draw_text_bg(surface, f"Time: {clock.time:.1f}s",
                             10, y, (0, 255, 200))
        y += 16
        wc = app.world.resources.try_get(WorldClock)
        if wc:
            app.draw_text_bg(
                surface,
                f"Day {wc.day + 1}  Phase: {wc.day_phase:.2f}",
                10, y, (0, 255, 200),
            )
