"""scenes/museum_scene.py — Interactive Exhibit Museum.

Tabbed exhibits that demo individual game systems in isolation:

  [1] AI Brains  — spawn NPCs with different brains, watch them act
  [2] Combat     — pit two factions against each other
  [3] LOD Demo   — visualise promote / demote transitions
  [4] Pathfinding — click to place start/goal, paint walls, watch A*

Controls:
    1-4         — switch exhibit tab
    Space       — start / reset the active demo
    LMB         — interact (paint walls / place markers)
    RMB         — secondary interact
    Escape / F3 — back to scene picker
"""

from __future__ import annotations
import math
import random
import time as _time
import pygame
from core.scene import Scene
from core.app import App
from core.constants import TILE_SIZE, TILE_COLORS, TILE_WALL, TILE_GRASS, TILE_STONE
from core.zone import ZONE_MAPS
from components import (
    Position, Velocity, Sprite, Identity, Camera, Collider,
    Health, Hunger, Brain, Facing, Lod, GameClock, Hurtbox,
)
from components.ai import Patrol, Threat, AttackConfig
from components.combat import Combat
from components.social import Faction
from logic.entity_factory import spawn_from_descriptor
from logic.pathfinding import find_path
from logic.systems import movement_system
from logic.brains import run_brains
from logic.projectiles import projectile_system


_TABS = ["AI Brains", "Combat", "LOD Demo", "Pathfinding"]

_ARENA_W = 30
_ARENA_H = 20


def _make_arena() -> list[list[int]]:
    tiles = [[TILE_GRASS] * _ARENA_W for _ in range(_ARENA_H)]
    for r in range(_ARENA_H):
        tiles[r][0] = TILE_WALL
        tiles[r][_ARENA_W - 1] = TILE_WALL
    for c in range(_ARENA_W):
        tiles[0][c] = TILE_WALL
        tiles[_ARENA_H - 1][c] = TILE_WALL
    return tiles


class MuseumScene(Scene):
    """Interactive Exhibit Museum."""

    def __init__(self):
        self.zone = "__museum__"
        self.tab = 0
        self.tiles = _make_arena()
        self.map_w = _ARENA_W
        self.map_h = _ARENA_H

        self._eids: list[int] = []
        self._cam_x = _ARENA_W / 2.0
        self._cam_y = _ARENA_H / 2.0

        # Pathfinding tab state
        self._pf_start: tuple[float, float] | None = None
        self._pf_goal: tuple[float, float] | None = None
        self._pf_path: list[tuple[float, float]] | None = None
        self._pf_calc_ms: float = 0.0
        self._painting: int | None = None

        # Combat tab state
        self._combat_running = False

        # LOD tab state
        self._lod_radius = 8.0
        self._lod_center: tuple[float, float] = (_ARENA_W / 2.0, _ARENA_H / 2.0)

    def on_enter(self, app: App):
        if not app.world.res(Camera):
            app.world.set_res(Camera())
        if not app.world.res(GameClock):
            app.world.set_res(GameClock())
        ZONE_MAPS[self.zone] = self.tiles
        self._setup_tab(app)

    def on_exit(self, app: App):
        self._clear_entities(app)

    def _clear_entities(self, app: App):
        for eid in self._eids:
            if app.world.alive(eid):
                app.world.kill(eid)
        app.world.purge()
        self._eids.clear()

    def _setup_tab(self, app: App):
        """Reset arena and spawn entities for the current tab."""
        self._clear_entities(app)
        self.tiles = _make_arena()
        ZONE_MAPS[self.zone] = self.tiles
        self._combat_running = False
        self._pf_start = None
        self._pf_goal = None
        self._pf_path = None

        if self.tab == 0:
            self._setup_ai_demo(app)
        elif self.tab == 1:
            self._setup_combat_demo(app)
        elif self.tab == 2:
            self._setup_lod_demo(app)
        # Tab 3 (pathfinding) starts empty

    # ── Tab 0: AI Brains ─────────────────────────────────────────────

    def _setup_ai_demo(self, app: App):
        """Spawn NPCs with different brain types."""
        brain_types = [
            ("Wanderer",     "wander",         (150, 200, 255), 4, 4),
            ("Villager",     "villager",        (100, 255, 100), 8, 4),
            ("Guard",        "guard",           (255, 200, 50),  14, 4),
            ("Hostile Melee","hostile_melee",   (255, 80, 80),   20, 4),
            ("Hostile Range","hostile_ranged",  (255, 120, 120), 26, 4),
        ]
        for name, bkind, color, x, y in brain_types:
            eid = self._spawn_npc(app, name, bkind, x, float(y), color)
            self._eids.append(eid)

    def _spawn_npc(self, app: App, name: str, brain_kind: str,
                   x: float, y: float, color: tuple,
                   faction_group: str = "neutral",
                   disposition: str = "neutral") -> int:
        w = app.world
        eid = w.spawn()
        w.add(eid, Position(x=x, y=y, zone=self.zone))
        w.add(eid, Velocity())
        w.add(eid, Sprite(char=name[0], color=color))
        w.add(eid, Identity(name=name, kind="npc"))
        w.add(eid, Collider())
        w.add(eid, Hurtbox())
        w.add(eid, Facing())
        w.add(eid, Health(current=100, maximum=100))
        w.add(eid, Combat(damage=10, defense=2))
        w.add(eid, Lod(level="high"))
        w.add(eid, Brain(kind=brain_kind, active=True))
        w.add(eid, Patrol(origin_x=x, origin_y=y, radius=6.0, speed=2.0))
        w.add(eid, Faction(group=faction_group, disposition=disposition,
                           home_disposition=disposition))
        if brain_kind in ("guard", "hostile_melee"):
            w.add(eid, Threat(aggro_radius=8.0, leash_radius=15.0))
            w.add(eid, AttackConfig(attack_type="melee", range=1.2, cooldown=0.5))
        elif brain_kind == "hostile_ranged":
            w.add(eid, Threat(aggro_radius=12.0, leash_radius=20.0))
            w.add(eid, AttackConfig(attack_type="ranged", range=8.0, cooldown=0.6))
        w.zone_add(eid, self.zone)
        return eid

    # ── Tab 1: Combat ────────────────────────────────────────────────

    def _setup_combat_demo(self, app: App):
        """Two factions facing off."""
        # Blue team (left side)
        for i in range(3):
            eid = self._spawn_npc(app, f"Blue-{i+1}", "hostile_melee",
                                   5.0, 5.0 + i * 3, (80, 120, 255),
                                   "blue_team", "hostile")
            self._eids.append(eid)

        # Red team (right side)
        for i in range(3):
            eid = self._spawn_npc(app, f"Red-{i+1}", "hostile_melee",
                                   24.0, 5.0 + i * 3, (255, 80, 80),
                                   "red_team", "hostile")
            self._eids.append(eid)

    # ── Tab 2: LOD Demo ──────────────────────────────────────────────

    def _setup_lod_demo(self, app: App):
        """Scatter NPCs and visualise LOD tiers based on distance.

        In the demo all NPCs are in the same zone, so none can be
        low LOD (that only happens when the player leaves the zone).
        High = near the camera centre, medium = further away.
        Both tiers run brains and move.
        """
        for i in range(15):
            x = random.uniform(3, _ARENA_W - 3)
            y = random.uniform(3, _ARENA_H - 3)
            eid = self._spawn_npc(app, f"NPC-{i+1}", "wander",
                                   x, y, (150, 200, 180))
            lod = app.world.get(eid, Lod)
            if lod:
                lod.level = "medium"  # same zone, brains active
            brain = app.world.get(eid, Brain)
            if brain:
                brain.active = True
            self._eids.append(eid)

    # ── Events ───────────────────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event, app: App):
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                app.pop_scene()
                return
            if event.key in (pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4):
                self.tab = event.key - pygame.K_1
                self._setup_tab(app)
            elif event.key == pygame.K_SPACE:
                self._on_space(app)

        elif event.type == pygame.MOUSEBUTTONDOWN:
            rc = self._mouse_to_tile(app)
            if rc is None:
                return
            row, col = rc
            if self.tab == 3:  # Pathfinding
                if event.button == 1:
                    # LMB: toggle wall or set start
                    keys = pygame.key.get_mods()
                    if keys & pygame.KMOD_SHIFT:
                        self._pf_start = (col + 0.5, row + 0.5)
                        self._recalc_pf()
                    else:
                        self._painting = TILE_WALL if self.tiles[row][col] != TILE_WALL else TILE_GRASS
                        self.tiles[row][col] = self._painting
                elif event.button == 3:
                    self._pf_goal = (col + 0.5, row + 0.5)
                    self._recalc_pf()
            elif self.tab == 2:  # LOD
                self._lod_center = (col + 0.5, row + 0.5)

        elif event.type == pygame.MOUSEMOTION:
            if self._painting is not None and self.tab == 3 and pygame.mouse.get_pressed()[0]:
                rc = self._mouse_to_tile(app)
                if rc:
                    self.tiles[rc[0]][rc[1]] = self._painting
                    ZONE_MAPS[self.zone] = self.tiles

        elif event.type == pygame.MOUSEBUTTONUP:
            if event.button == 1:
                if self._painting is not None:
                    self._painting = None
                    ZONE_MAPS[self.zone] = self.tiles
                    self._recalc_pf()

    def _on_space(self, app: App):
        if self.tab == 1:
            # Toggle combat — reset or start
            self._combat_running = not self._combat_running
            if not self._combat_running:
                self._setup_tab(app)
        elif self.tab == 3:
            # Clear pathfinding
            self._pf_start = None
            self._pf_goal = None
            self._pf_path = None
            self.tiles = _make_arena()
            ZONE_MAPS[self.zone] = self.tiles
        else:
            self._setup_tab(app)

    # ── Update ───────────────────────────────────────────────────────

    def update(self, dt: float, app: App):
        clock = app.world.res(GameClock)
        if clock:
            clock.time += dt

        if self.tab == 0:
            # AI demo: run brains + movement
            run_brains(app.world, dt)
            movement_system(app.world, dt, self.tiles)
        elif self.tab == 1 and self._combat_running:
            run_brains(app.world, dt)
            movement_system(app.world, dt, self.tiles)
            projectile_system(app.world, dt, self.tiles)
        elif self.tab == 2:
            # LOD demo: all same zone → high or medium (never low).
            # Both tiers run brains and move.
            cx, cy = self._lod_center
            for eid in self._eids:
                if not app.world.alive(eid):
                    continue
                pos = app.world.get(eid, Position)
                lod = app.world.get(eid, Lod)
                brain = app.world.get(eid, Brain)
                if not pos or not lod:
                    continue
                d = math.hypot(pos.x - cx, pos.y - cy)
                if d <= self._lod_radius:
                    lod.level = "high"
                else:
                    lod.level = "medium"
                # Both high and medium run brains
                if brain and not brain.active:
                    brain.active = True
            run_brains(app.world, dt)
            movement_system(app.world, dt, self.tiles)

        app.world.purge()

    # ── Draw ─────────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, app: App):
        surface.fill((16, 20, 24))
        sw, sh = surface.get_size()
        ox = sw // 2 - int(self._cam_x * TILE_SIZE)
        oy = sh // 2 - int(self._cam_y * TILE_SIZE)

        # Tiles
        for row in range(self.map_h):
            for col in range(self.map_w):
                tid = self.tiles[row][col]
                color = TILE_COLORS.get(tid, (255, 0, 255))
                rect = pygame.Rect(ox + col * TILE_SIZE, oy + row * TILE_SIZE,
                                   TILE_SIZE, TILE_SIZE)
                pygame.draw.rect(surface, color, rect)

        # Tab-specific drawing
        if self.tab == 2:
            self._draw_lod_rings(surface, ox, oy)
        elif self.tab == 3:
            self._draw_pathfinding(surface, ox, oy, app)

        # Entities
        for eid in self._eids:
            if not app.world.alive(eid):
                continue
            pos = app.world.get(eid, Position)
            sprite = app.world.get(eid, Sprite)
            if not pos or not sprite:
                continue
            sx = ox + int(pos.x * TILE_SIZE)
            sy = oy + int(pos.y * TILE_SIZE)

            # LOD coloring in LOD tab
            lod = app.world.get(eid, Lod)
            if self.tab == 2 and lod:
                lod_color = {
                    "high": (0, 255, 100),
                    "medium": (255, 200, 50),
                    "low": (255, 80, 80),
                }.get(lod.level, (180, 180, 180))
                app.draw_text(surface, sprite.char, sx + 8, sy + 4,
                              color=lod_color, font=app.font_lg)
                app.draw_text(surface, f"{lod.level[0].upper()}", sx + 22, sy - 2,
                              color=lod_color, font=app.font_sm)
            else:
                app.draw_text(surface, sprite.char, sx + 8, sy + 4,
                              color=sprite.color, font=app.font_lg)

            # Name label
            ident = app.world.get(eid, Identity)
            if ident:
                app.draw_text(surface, ident.name, sx - 8, sy - 14,
                              color=(160, 160, 160), font=app.font_sm)

            # Brain state (for AI tab)
            if self.tab == 0:
                brain = app.world.get(eid, Brain)
                if brain:
                    cs = brain.state.get("combat", {})
                    mode = cs.get("mode") if cs else None
                    if mode:
                        mode_color = {
                            "idle": (150, 150, 150),
                            "chase": (255, 200, 80),
                            "attack": (255, 80, 80),
                            "flee": (80, 180, 255),
                        }.get(mode, (180, 180, 180))
                        app.draw_text(surface, mode, sx - 4, sy + 20,
                                      color=mode_color, font=app.font_sm)

            # Health bar
            hp = app.world.get(eid, Health)
            if hp and hp.current < hp.maximum:
                bar_w = TILE_SIZE - 4
                bar_x = sx + 2
                bar_y = sy - 5
                ratio = max(0.0, hp.current / hp.maximum)
                pygame.draw.rect(surface, (40, 40, 40), (bar_x, bar_y, bar_w, 3))
                bc = (50, 200, 50) if ratio > 0.5 else (220, 200, 50) if ratio > 0.25 else (220, 50, 50)
                pygame.draw.rect(surface, bc, (bar_x, bar_y, max(1, int(bar_w * ratio)), 3))

        # ── Tab header ───────────────────────────────────────────────
        tab_parts = []
        for i, name in enumerate(_TABS):
            marker = ">" if i == self.tab else " "
            tab_parts.append(f"[{i+1}]{marker}{name}")
        header = "MUSEUM  " + "  ".join(tab_parts) + "  [Esc] back"
        app.draw_text_bg(surface, header, 8, 8, (0, 255, 200))

        # Tab-specific info
        self._draw_tab_info(surface, app)

    def _draw_lod_rings(self, surface: pygame.Surface, ox: int, oy: int):
        cx, cy = self._lod_center
        sx = ox + int(cx * TILE_SIZE)
        sy = oy + int(cy * TILE_SIZE)

        # High-LOD ring (green)
        r_high = int(self._lod_radius * TILE_SIZE)
        _draw_circle_alpha(surface, (0, 255, 100, 25), sx, sy, r_high)
        pygame.draw.circle(surface, (0, 255, 100), (sx, sy), r_high, 1)

        # Medium-LOD ring (yellow)
        r_med = int(self._lod_radius * 2 * TILE_SIZE)
        _draw_circle_alpha(surface, (255, 200, 50, 15), sx, sy, r_med)
        pygame.draw.circle(surface, (255, 200, 50), (sx, sy), r_med, 1)

        # Center marker
        pygame.draw.circle(surface, (255, 255, 255), (sx, sy), 4)

    def _draw_pathfinding(self, surface: pygame.Surface, ox: int, oy: int, app: App):
        # Start marker
        if self._pf_start:
            sx = ox + int(self._pf_start[0] * TILE_SIZE)
            sy = oy + int(self._pf_start[1] * TILE_SIZE)
            pygame.draw.circle(surface, (0, 255, 100), (sx, sy), 5)
            app.draw_text(surface, "S", sx - 3, sy - 12, (0, 255, 100), app.font_sm)

        # Goal marker
        if self._pf_goal:
            gx = ox + int(self._pf_goal[0] * TILE_SIZE)
            gy = oy + int(self._pf_goal[1] * TILE_SIZE)
            _draw_diamond(surface, (255, 50, 50), gx, gy, 5)
            app.draw_text(surface, "G", gx - 3, gy - 12, (255, 50, 50), app.font_sm)

        # Path
        if self._pf_path:
            prev = None
            if self._pf_start:
                prev = (ox + int(self._pf_start[0] * TILE_SIZE),
                        oy + int(self._pf_start[1] * TILE_SIZE))
            for wx, wy in self._pf_path:
                wpx = ox + int(wx * TILE_SIZE)
                wpy = oy + int(wy * TILE_SIZE)
                if prev:
                    pygame.draw.line(surface, (0, 200, 255), prev, (wpx, wpy), 2)
                pygame.draw.circle(surface, (0, 200, 255), (wpx, wpy), 3)
                prev = (wpx, wpy)

    def _draw_tab_info(self, surface: pygame.Surface, app: App):
        sw, sh = surface.get_size()
        y = sh - 30

        if self.tab == 0:
            info = "AI Brains: Watch NPCs with different brain types.  [Space] reset"
        elif self.tab == 1:
            status = "FIGHTING" if self._combat_running else "PAUSED"
            alive = sum(1 for e in self._eids if app.world.alive(e))
            info = f"Combat: {status}  Alive: {alive}/{len(self._eids)}  [Space] toggle"
        elif self.tab == 2:
            info = f"LOD Demo: Click to move LOD center. Radius: {self._lod_radius:.0f}  [Space] reset"
        else:
            info = f"Pathfinding: Shift+LMB=start  RMB=goal  LMB=walls  Calc: {self._pf_calc_ms:.2f}ms  [Space] clear"
            path_len = len(self._pf_path) if self._pf_path else 0
            info += f"  Path: {path_len} nodes"

        app.draw_text_bg(surface, info, 8, y, (180, 180, 180))

    # ── Helpers ──────────────────────────────────────────────────────

    def _mouse_to_tile(self, app: App) -> tuple[int, int] | None:
        mx, my = app.mouse_pos()
        sw, sh = app._virtual_size
        ox = sw // 2 - int(self._cam_x * TILE_SIZE)
        oy = sh // 2 - int(self._cam_y * TILE_SIZE)
        col = (mx - ox) // TILE_SIZE
        row = (my - oy) // TILE_SIZE
        if 0 <= row < self.map_h and 0 <= col < self.map_w:
            return row, col
        return None

    def _recalc_pf(self):
        if not self._pf_start or not self._pf_goal:
            self._pf_path = None
            return
        ZONE_MAPS[self.zone] = self.tiles
        t0 = _time.perf_counter()
        self._pf_path = find_path(
            self.zone,
            self._pf_start[0], self._pf_start[1],
            self._pf_goal[0], self._pf_goal[1],
        )
        self._pf_calc_ms = (_time.perf_counter() - t0) * 1000


def _draw_circle_alpha(surface, color, cx, cy, radius):
    if radius < 2:
        return
    r, g, b, a = color
    d = radius * 2 + 2
    cs = pygame.Surface((d, d), pygame.SRCALPHA)
    pygame.draw.circle(cs, (r, g, b, a), (d // 2, d // 2), radius)
    surface.blit(cs, (cx - d // 2, cy - d // 2))


def _draw_diamond(surface, color, cx, cy, size):
    points = [(cx, cy - size), (cx + size, cy),
              (cx, cy + size), (cx - size, cy)]
    pygame.draw.polygon(surface, color, points, 2)
