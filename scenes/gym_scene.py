"""scenes/gym_scene.py — Movement & Pathfinding Gym.

A flat arena with a controllable test entity and real-time metrics.
Use this to test A*, collision, and movement systems in isolation.

Controls:
    WASD         — move the test entity
    1-3          — preset tile layouts (open, maze, rooms)
    LMB          — paint / erase walls
    RMB          — set A* goal marker
    G            — toggle grid overlay
    P            — toggle A* path visualisation
    R            — reset arena
    Tab          — cycle metrics panel
    Escape / F3  — back to scene picker
"""

from __future__ import annotations
import math
import pygame
from core.scene import Scene
from core.app import App
from core.ecs import World
from core.constants import TILE_SIZE, TILE_COLORS, TILE_WALL, TILE_GRASS, TILE_STONE
from components import (
    Position, Velocity, Sprite, Identity, Player, Camera, Collider,
    Hurtbox, Health, Brain, Facing, Lod, GameClock,
)
from components.ai import Patrol
from logic.pathfinding import find_path, path_next_waypoint
from logic.systems import movement_system
from core.zone import ZONE_MAPS


# ── Arena presets ────────────────────────────────────────────────────

_W = TILE_WALL
_G = TILE_GRASS
_S = TILE_STONE

def _make_open(w: int = 30, h: int = 20) -> list[list[int]]:
    """Flat grass arena with stone border."""
    tiles = [[_G] * w for _ in range(h)]
    for r in range(h):
        tiles[r][0] = _W
        tiles[r][w - 1] = _W
    for c in range(w):
        tiles[0][c] = _W
        tiles[h - 1][c] = _W
    return tiles


def _make_maze(w: int = 30, h: int = 20) -> list[list[int]]:
    """Open arena with internal wall corridors for pathfinding tests."""
    tiles = _make_open(w, h)
    # Horizontal walls with gaps
    for c in range(2, w - 4):
        tiles[5][c] = _W
        tiles[10][c + 2] = _W
        tiles[15][c] = _W
    # Gaps
    tiles[5][10] = _G
    tiles[5][20] = _G
    tiles[10][6] = _G
    tiles[10][18] = _G
    tiles[15][12] = _G
    tiles[15][24] = _G
    # Vertical walls
    for r in range(3, 18):
        if r not in (7, 12):
            tiles[r][14] = _W
    return tiles


def _make_rooms(w: int = 30, h: int = 20) -> list[list[int]]:
    """Room layout: 4 rooms with doorways."""
    tiles = _make_open(w, h)
    mid_r, mid_c = h // 2, w // 2
    # Horizontal divider
    for c in range(1, w - 1):
        tiles[mid_r][c] = _W
    # Vertical divider
    for r in range(1, h - 1):
        tiles[r][mid_c] = _W
    # Doorways (2-tile wide)
    tiles[mid_r][mid_c // 2] = _G
    tiles[mid_r][mid_c // 2 + 1] = _G
    tiles[mid_r][mid_c + mid_c // 2] = _G
    tiles[mid_r][mid_c + mid_c // 2 + 1] = _G
    tiles[mid_r // 2][mid_c] = _G
    tiles[mid_r // 2 + 1][mid_c] = _G
    tiles[mid_r + mid_r // 2][mid_c] = _G
    tiles[mid_r + mid_r // 2 + 1][mid_c] = _G
    return tiles


_PRESETS = {
    1: ("Open Arena", _make_open),
    2: ("Maze",       _make_maze),
    3: ("Rooms",      _make_rooms),
}


class GymScene(Scene):
    """Movement & Pathfinding Gym."""

    def __init__(self):
        self.tiles = _make_open()
        self.map_h = len(self.tiles)
        self.map_w = len(self.tiles[0])
        self.show_grid = True
        self.show_path = True
        self.zone = "__gym__"
        self.preset_name = "Open Arena"

        # A* goal (RMB click)
        self.goal: tuple[float, float] | None = None
        self.astar_path: list[tuple[float, float]] | None = None

        # Walk-target NPCs
        self._npc_eids: list[int] = []

        # Metrics
        self._metric_panel = 0  # 0=movement, 1=pathfinding
        self._path_calc_ms: float = 0.0
        self._path_length: int = 0
        self._frames = 0
        self._move_dist: float = 0.0
        self._prev_pos: tuple[float, float] | None = None
        self._elapsed: float = 0.0

        # Wall painting
        self._painting: int | None = None  # None, TILE_WALL, TILE_GRASS

    # ── Lifecycle ────────────────────────────────────────────────────

    def on_enter(self, app: App):
        from core import tuning as tuning_mod
        tuning_mod.load()
        w = app.world
        if not w.res(Camera):
            w.set_res(Camera())
        if not w.res(GameClock):
            w.set_res(GameClock())

        # Register tiles so A* pathfinding can find them
        ZONE_MAPS[self.zone] = self.tiles

        # Spawn controllable test entity (like a "player" but in the gym)
        self._player_eid = w.spawn()
        w.add(self._player_eid, Position(x=5.0, y=5.0, zone=self.zone))
        w.add(self._player_eid, Velocity())
        w.add(self._player_eid, Sprite(char="@", color=(0, 255, 200)))
        w.add(self._player_eid, Identity(name="GymRunner", kind="player"))
        w.add(self._player_eid, Player(speed=5.0))
        w.add(self._player_eid, Collider())
        w.add(self._player_eid, Facing())
        w.zone_add(self._player_eid, self.zone)

        # Spawn a few A*-walking NPCs for group pathfinding tests
        npc_defs = [
            ("Walker-A", 8.0, 3.0, (255, 120, 50)),
            ("Walker-B", 12.0, 3.0, (50, 200, 255)),
            ("Walker-C", 16.0, 3.0, (200, 255, 50)),
        ]
        for name, nx, ny, color in npc_defs:
            eid = w.spawn()
            w.add(eid, Position(x=nx, y=ny, zone=self.zone))
            w.add(eid, Velocity())
            w.add(eid, Sprite(char="N", color=color))
            w.add(eid, Identity(name=name, kind="npc"))
            w.add(eid, Collider())
            w.add(eid, Facing())
            w.add(eid, Lod(level="high"))
            w.add(eid, Brain(kind="wander", active=True))
            w.add(eid, Patrol(origin_x=nx, origin_y=ny, radius=10.0, speed=2.5))
            w.zone_add(eid, self.zone)
            self._npc_eids.append(eid)

        cam = w.res(Camera)
        if cam:
            cam.x = self.map_w / 2.0
            cam.y = self.map_h / 2.0
        ZONE_MAPS[self.zone] = self.tiles

    def on_exit(self, app: App):
        # Clean up gym entities
        for eid in [self._player_eid] + self._npc_eids:
            if app.world.alive(eid):
                app.world.kill(eid)
        app.world.purge()
        self._npc_eids.clear()

    # ── Events ───────────────────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event, app: App):
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                app.pop_scene()
                return
            if event.key == pygame.K_g:
                self.show_grid = not self.show_grid
            elif event.key == pygame.K_p:
                self.show_path = not self.show_path
            elif event.key == pygame.K_r:
                self._reset_arena(app)
            elif event.key == pygame.K_TAB:
                self._metric_panel = (self._metric_panel + 1) % 2
            elif event.key in (pygame.K_1, pygame.K_2, pygame.K_3):
                idx = event.key - pygame.K_0
                if idx in _PRESETS:
                    self.preset_name, factory = _PRESETS[idx]
                    self.tiles = factory()
                    self.map_h = len(self.tiles)
                    self.map_w = len(self.tiles[0])
                    self.goal = None
                    self.astar_path = None
                    ZONE_MAPS[self.zone] = self.tiles

        elif event.type == pygame.MOUSEBUTTONDOWN:
            rc = self._mouse_to_tile(app)
            if rc:
                row, col = rc
                if event.button == 1:
                    # LMB: toggle wall
                    self._painting = _W if self.tiles[row][col] != _W else _G
                    self.tiles[row][col] = self._painting
                elif event.button == 3:
                    # RMB: set A* goal
                    self.goal = (col + 0.5, row + 0.5)
                    self._recalc_path(app)

        elif event.type == pygame.MOUSEMOTION:
            if self._painting is not None and pygame.mouse.get_pressed()[0]:
                rc = self._mouse_to_tile(app)
                if rc:
                    self.tiles[rc[0]][rc[1]] = self._painting

        elif event.type == pygame.MOUSEBUTTONUP:
            if event.button == 1:
                self._painting = None
                self._recalc_path(app)

    # ── Update ───────────────────────────────────────────────────────

    def update(self, dt: float, app: App):
        w = app.world
        self._frames += 1
        self._elapsed += dt

        # Player input
        keys = pygame.key.get_pressed()
        dx = float(keys[pygame.K_d]) - float(keys[pygame.K_a])
        dy = float(keys[pygame.K_s]) - float(keys[pygame.K_w])
        length = math.hypot(dx, dy)
        if length > 0.001:
            dx /= length
            dy /= length

        vel = w.get(self._player_eid, Velocity)
        player = w.get(self._player_eid, Player)
        if vel and player:
            vel.x = dx * player.speed
            vel.y = dy * player.speed

        # Track movement distance
        pos = w.get(self._player_eid, Position)
        if pos and self._prev_pos:
            self._move_dist += math.hypot(pos.x - self._prev_pos[0],
                                          pos.y - self._prev_pos[1])
        if pos:
            self._prev_pos = (pos.x, pos.y)

        # NPC brains (wander)
        from logic.brains import run_brains
        clock = w.res(GameClock)
        if clock:
            clock.time += dt
        run_brains(w, dt)

        # Physics
        movement_system(w, dt, self.tiles)
        w.purge()

        # Camera follows player
        cam = w.res(Camera)
        if pos and cam:
            cam.x = pos.x
            cam.y = pos.y

    # ── Draw ─────────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, app: App):
        surface.fill((20, 20, 25))
        cam = app.world.res(Camera) or Camera()
        sw, sh = surface.get_size()
        ox = sw // 2 - int(cam.x * TILE_SIZE)
        oy = sh // 2 - int(cam.y * TILE_SIZE)

        # Tiles
        for row in range(self.map_h):
            for col in range(self.map_w):
                tid = self.tiles[row][col]
                color = TILE_COLORS.get(tid, (255, 0, 255))
                rect = pygame.Rect(ox + col * TILE_SIZE, oy + row * TILE_SIZE,
                                   TILE_SIZE, TILE_SIZE)
                pygame.draw.rect(surface, color, rect)
                if self.show_grid:
                    pygame.draw.rect(surface, (50, 50, 50), rect, 1)

        # Goal marker
        if self.goal:
            gx = ox + int(self.goal[0] * TILE_SIZE)
            gy = oy + int(self.goal[1] * TILE_SIZE)
            _draw_diamond(surface, (255, 50, 50), gx, gy, 6)

        # A* path
        if self.show_path and self.astar_path:
            pos = app.world.get(self._player_eid, Position)
            if pos:
                prev = (ox + int(pos.x * TILE_SIZE) + TILE_SIZE // 2,
                        oy + int(pos.y * TILE_SIZE) + TILE_SIZE // 2)
                for wx, wy in self.astar_path:
                    wpx = ox + int(wx * TILE_SIZE) + TILE_SIZE // 2
                    wpy = oy + int(wy * TILE_SIZE) + TILE_SIZE // 2
                    pygame.draw.line(surface, (0, 255, 200), prev, (wpx, wpy), 1)
                    pygame.draw.circle(surface, (0, 255, 200), (wpx, wpy), 3)
                    prev = (wpx, wpy)

        # NPC A* paths (from brain state)
        for neid in self._npc_eids:
            if not app.world.alive(neid):
                continue
            npos = app.world.get(neid, Position)
            brain = app.world.get(neid, Brain)
            sprite = app.world.get(neid, Sprite)
            if not npos or not brain:
                continue
            path = brain.state.get("_path")
            if path and self.show_path:
                color = sprite.color if sprite else (200, 200, 200)
                prev = (ox + int(npos.x * TILE_SIZE) + TILE_SIZE // 2,
                        oy + int(npos.y * TILE_SIZE) + TILE_SIZE // 2)
                for wx, wy in path:
                    wpx = ox + int(wx * TILE_SIZE) + TILE_SIZE // 2
                    wpy = oy + int(wy * TILE_SIZE) + TILE_SIZE // 2
                    pygame.draw.line(surface, color, prev, (wpx, wpy), 1)
                    pygame.draw.circle(surface, color, (wpx, wpy), 2)
                    prev = (wpx, wpy)

        # Entities
        for eid, pos, sprite in app.world.query(Position, Sprite):
            if pos.zone != self.zone:
                continue
            sx = ox + int(pos.x * TILE_SIZE)
            sy = oy + int(pos.y * TILE_SIZE)
            app.draw_text(surface, sprite.char, sx + 8, sy + 4,
                          color=sprite.color, font=app.font_lg)
            # Name label
            ident = app.world.get(eid, Identity)
            if ident:
                app.draw_text(surface, ident.name, sx - 8, sy - 14,
                              color=(180, 180, 180), font=app.font_sm)

        # ── Metrics panel ────────────────────────────────────────────
        self._draw_metrics(surface, app)

        # ── Controls legend ──────────────────────────────────────────
        legend = [
            "WASD=move  1/2/3=preset  LMB=wall  RMB=goal",
            "G=grid  P=path  R=reset  Tab=metrics  Esc=back",
        ]
        y = sh - 30
        for line in legend:
            app.draw_text_bg(surface, line, 8, y, (180, 180, 180))
            y += 14

    # ── Internal ─────────────────────────────────────────────────────

    def _draw_metrics(self, surface: pygame.Surface, app: App):
        sw = surface.get_width()
        panel_w = 240
        bx = sw - panel_w - 8
        by = 8

        # Background
        bg = pygame.Surface((panel_w, 120), pygame.SRCALPHA)
        bg.fill((0, 0, 0, 160))
        surface.blit(bg, (bx, by))

        y = by + 6
        app.draw_text(surface, f"GYM: {self.preset_name}", bx + 6, y, (0, 255, 200), app.font_sm)
        y += 16

        if self._metric_panel == 0:
            # Movement metrics
            pos = app.world.get(self._player_eid, Position)
            vel = app.world.get(self._player_eid, Velocity)
            speed = math.hypot(vel.x, vel.y) if vel else 0.0
            app.draw_text(surface, f"Pos: ({pos.x:.1f}, {pos.y:.1f})" if pos else "Pos: ?",
                          bx + 6, y, (200, 200, 200), app.font_sm)
            y += 14
            app.draw_text(surface, f"Speed: {speed:.1f} t/s",
                          bx + 6, y, (200, 200, 200), app.font_sm)
            y += 14
            avg_speed = self._move_dist / max(0.001, self._elapsed)
            app.draw_text(surface, f"Avg: {avg_speed:.1f} t/s  Dist: {self._move_dist:.0f}",
                          bx + 6, y, (200, 200, 200), app.font_sm)
            y += 14
            app.draw_text(surface, f"FPS: {int(app.clock.get_fps())}",
                          bx + 6, y, (100, 255, 100), app.font_sm)
        else:
            # Pathfinding metrics
            app.draw_text(surface, f"A* calc: {self._path_calc_ms:.2f} ms",
                          bx + 6, y, (200, 200, 200), app.font_sm)
            y += 14
            app.draw_text(surface, f"Path len: {self._path_length} nodes",
                          bx + 6, y, (200, 200, 200), app.font_sm)
            y += 14
            goal_str = f"({self.goal[0]:.1f}, {self.goal[1]:.1f})" if self.goal else "none"
            app.draw_text(surface, f"Goal: {goal_str}",
                          bx + 6, y, (200, 200, 200), app.font_sm)
            y += 14
            app.draw_text(surface, f"NPCs pathfinding: {len(self._npc_eids)}",
                          bx + 6, y, (200, 200, 200), app.font_sm)

    def _mouse_to_tile(self, app: App) -> tuple[int, int] | None:
        cam = app.world.res(Camera) or Camera()
        mx, my = app.mouse_pos()
        sw, sh = app._virtual_size
        ox = sw // 2 - int(cam.x * TILE_SIZE)
        oy = sh // 2 - int(cam.y * TILE_SIZE)
        col = (mx - ox) // TILE_SIZE
        row = (my - oy) // TILE_SIZE
        if 0 <= row < self.map_h and 0 <= col < self.map_w:
            return row, col
        return None

    def _recalc_path(self, app: App):
        if not self.goal:
            self.astar_path = None
            return
        pos = app.world.get(self._player_eid, Position)
        if not pos:
            return
        import time
        t0 = time.perf_counter()
        # Ensure ZONE_MAPS has the latest tiles (after wall painting)
        ZONE_MAPS[self.zone] = self.tiles
        self.astar_path = find_path(
            self.zone, pos.x, pos.y, self.goal[0], self.goal[1],
        )
        self._path_calc_ms = (time.perf_counter() - t0) * 1000
        self._path_length = len(self.astar_path) if self.astar_path else 0

    def _reset_arena(self, app: App):
        self.tiles = _make_open()
        self.map_h = len(self.tiles)
        self.map_w = len(self.tiles[0])
        self.goal = None
        self.astar_path = None
        self.preset_name = "Open Arena"
        self._move_dist = 0.0
        self._elapsed = 0.0
        self._frames = 0
        ZONE_MAPS[self.zone] = self.tiles
        pos = app.world.get(self._player_eid, Position)
        if pos:
            pos.x = 5.0
            pos.y = 5.0


def _draw_diamond(surface, color, cx, cy, size):
    points = [(cx, cy - size), (cx + size, cy),
              (cx, cy + size), (cx - size, cy)]
    pygame.draw.polygon(surface, color, points, 2)
