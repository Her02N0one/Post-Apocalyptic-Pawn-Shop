"""scenes/world/firstperson.py — First-person raycasted subzone view.

Renders the same tile grid and ECS entities as TopDown, but from a
Wolfenstein / Doom-style first-person perspective using raycasting.

Controls:
    W / S          — move forward / backward
    A / D          — strafe left / right
    Left / Right   — turn camera (or hold right mouse button + drag)
    E              — interact with nearest entity
    Tab            — toggle debug overlay / minimap
    Escape         — return to overworld (pop scene)
    F5 / F9        — save / load

The scene reads tiles and entities from the shared ``Session`` and
never creates or loads data itself.
"""

from __future__ import annotations

import math

import pygame

from core.app import App
from core.constants import TILE_SIZE, TILE_COLORS, TILE_WALL
from core.scene import Scene
from core.types import Direction
from components import (
    Position, Velocity, Sprite, Player, Facing,
    Health, Identity, Camera, GameClock,
)
from systems.physics import movement_system
from systems.interaction import try_interact, nearest_interactable
from systems.raycaster import (
    cast_walls, project_entities, build_zbuffer,
)

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.session import Session

# ── Constants ────────────────────────────────────────────────────────
FOV = math.pi / 3          # 60° horizontal field of view
TURN_SPEED = 2.5           # radians / second
MOUSE_SENSITIVITY = 0.003  # radians / px of mouse movement
RAY_STEP = 2               # cast every Nth column (1 = full res)

# Ceiling / floor colours
_CEILING = (30, 30, 40)
_FLOOR = (50, 50, 45)


class FirstPerson(Scene):
    """First-person raycasted view — renders the same world as TopDown."""

    def __init__(self, session: "Session") -> None:
        self.session = session
        self.player_angle: float = math.pi * 1.5  # facing "up" (north)
        self.show_debug = False
        self._mouse_captured = False

    # ── Lifecycle ─────────────────────────────────────────────────

    def on_enter(self, app: App) -> None:
        # Sync angle from current Facing direction
        result = app.world.query_one(Player, Facing)
        if result:
            _, _, facing = result
            self.player_angle = _direction_to_angle(facing.direction)

        if not app.world.resources.has(Camera):
            app.world.resources.set(Camera())
        if not app.world.resources.has(GameClock):
            app.world.resources.set(GameClock())

    def on_exit(self, app: App) -> None:
        # Sync facing direction back to the Facing component
        result = app.world.query_one(Player, Facing)
        if result:
            _, _, facing = result
            facing.direction = _angle_to_direction(self.player_angle)

        # Release mouse if captured
        if self._mouse_captured:
            pygame.event.set_grab(False)
            pygame.mouse.set_visible(True)
            self._mouse_captured = False

    # ── Events ────────────────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event, app: App) -> None:
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                app.pop_scene()  # return to overworld
            elif event.key == pygame.K_TAB:
                self.show_debug = not self.show_debug
            elif event.key == pygame.K_e:
                self._do_interact(app)
            elif event.key == pygame.K_F5:
                self.session.save()
            elif event.key == pygame.K_F9:
                self.session.load()
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
            pygame.event.set_grab(True)
            pygame.mouse.set_visible(False)
            self._mouse_captured = True
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 3:
            pygame.event.set_grab(False)
            pygame.mouse.set_visible(True)
            self._mouse_captured = False
        elif event.type == pygame.MOUSEMOTION and self._mouse_captured:
            self.player_angle += event.rel[0] * MOUSE_SENSITIVITY

    def _do_interact(self, app: App) -> None:
        if try_interact(app.world, app.world.events):
            found = nearest_interactable(app.world)
            if found:
                ident = app.world.get(found[0], Identity)
                name = ident.name if ident else "???"
                self.session.status = f"Interacted with {name}"
                self.session.status_timer = 1.5
        else:
            self.session.status = "Nothing nearby"
            self.session.status_timer = 1.0

    # ── Update ────────────────────────────────────────────────────

    def update(self, dt: float, app: App) -> None:
        if self.session.status_timer > 0:
            self.session.status_timer -= dt

        keys = pygame.key.get_pressed()

        # ── Turn (keyboard) ──────────────────────────────────────
        if keys[pygame.K_LEFT]:
            self.player_angle -= TURN_SPEED * dt
        if keys[pygame.K_RIGHT]:
            self.player_angle += TURN_SPEED * dt

        # ── Movement ─────────────────────────────────────────────
        fwd = 0.0
        strafe = 0.0
        if keys[pygame.K_w] or keys[pygame.K_UP]:    fwd += 1
        if keys[pygame.K_s] or keys[pygame.K_DOWN]:  fwd -= 1
        if keys[pygame.K_a]:  strafe -= 1
        if keys[pygame.K_d]:  strafe += 1

        # Normalise
        mag = math.sqrt(fwd * fwd + strafe * strafe)
        if mag > 0.01:
            fwd /= mag
            strafe /= mag

        cos_a = math.cos(self.player_angle)
        sin_a = math.sin(self.player_angle)

        # Forward along angle, strafe is perpendicular
        dx = fwd * cos_a + strafe * (-sin_a)
        dy = fwd * sin_a + strafe * cos_a

        for eid, player, vel in app.world.query(Player, Velocity):
            vel.x = dx * player.speed
            vel.y = dy * player.speed

        # ── Game clock ───────────────────────────────────────────
        clock = app.world.resources.try_get(GameClock)
        if clock:
            clock.time += dt

        # ── Physics (same collision system) ──────────────────────
        movement_system(app.world, dt, self.session.tiles)

        # ── Events ───────────────────────────────────────────────
        app.world.events.flush()

        # ── Camera ───────────────────────────────────────────────
        cam = app.world.resources.try_get(Camera)
        result = app.world.query_one(Player, Position)
        if cam and result:
            _, _, pos = result
            cam.x = pos.x
            cam.y = pos.y

        app.world.purge()

    # ── Draw ──────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, app: App) -> None:
        sw, sh = surface.get_size()

        # Player position
        result = app.world.query_one(Player, Position)
        if not result:
            surface.fill((0, 0, 0))
            app.draw_text(surface, "No player entity", 10, 10, (255, 0, 0))
            return
        _, _, pos = result
        px, py = pos.x, pos.y

        # ── Ceiling / floor ──────────────────────────────────────
        surface.fill(_CEILING)
        pygame.draw.rect(surface, _FLOOR, (0, sh // 2, sw, sh // 2))

        # ── Walls ────────────────────────────────────────────────
        slices = cast_walls(
            px, py, self.player_angle, FOV,
            sw, sh, self.session.tiles,
            step=RAY_STEP,
        )

        for ws in slices:
            # Wall colour from tile palette, darkened on one side
            base = TILE_COLORS.get(ws.tile_id, (90, 90, 90))
            if ws.side == 1:
                color = (base[0] * 2 // 3, base[1] * 2 // 3, base[2] * 2 // 3)
            else:
                color = base

            half_h = ws.height // 2
            y_start = max(0, sh // 2 - half_h)
            y_end = min(sh, sh // 2 + half_h)

            for c in range(ws.screen_x, min(ws.screen_x + RAY_STEP, sw)):
                pygame.draw.line(surface, color, (c, y_start), (c, y_end))

        # ── Entity billboards ────────────────────────────────────
        zone = self.session.zone_name
        ent_data: list[tuple[int, float, float, str, tuple[int, int, int]]] = []
        for eid, epos, sprite in app.world.query(Position, Sprite):
            if epos.zone != zone:
                continue
            if app.world.has(eid, Player):
                continue  # don't render self
            ent_data.append((eid, epos.x, epos.y, sprite.char, sprite.color))

        if ent_data:
            zbuf = build_zbuffer(slices, sw, step=RAY_STEP)
            billboards = project_entities(
                px, py, self.player_angle, FOV, sw, sh, ent_data,
            )
            self._draw_billboards(surface, app, billboards, zbuf, sw, sh)

        # ── HUD ──────────────────────────────────────────────────
        self._draw_hud(surface, app, sw, sh)

        # ── Minimap / debug ──────────────────────────────────────
        if self.show_debug:
            self._draw_minimap(surface, app, px, py, sw, sh)
            self._draw_debug(surface, app, px, py)

    # ── Billboard rendering ──────────────────────────────────────

    def _draw_billboards(
        self, surface: pygame.Surface, app: App,
        billboards: list, zbuf: list[float],
        sw: int, sh: int,
    ) -> None:
        for bb in billboards:
            if bb.height < 2:
                continue
            # Character rendered at a size proportional to distance
            font_size = max(8, min(72, bb.height // 2))
            # Use cached font closest to the size we need
            font = pygame.font.SysFont("monospace", font_size)
            img = font.render(bb.char, True, bb.color)
            img_w, img_h = img.get_size()

            dx = int(bb.screen_x - img_w // 2)
            dy = int(bb.screen_y + (bb.height - img_h) // 2)

            # Simple per-column z-occlusion (clip against zbuffer)
            left = max(0, dx)
            right = min(sw, dx + img_w)
            if left >= right:
                continue

            # Check if majority of the sprite is behind walls
            visible_cols = 0
            for c in range(left, right):
                if bb.distance < zbuf[c]:
                    visible_cols += 1
            if visible_cols < (right - left) * 0.3:
                continue

            surface.blit(img, (dx, dy))

            # Health bar
            hp = app.world.get(bb.eid, Health)
            if hp and hp.current < hp.maximum:
                bar_w = min(img_w, 40)
                ratio = max(0.0, hp.current / hp.maximum)
                bx = int(bb.screen_x - bar_w // 2)
                by = dy - 4
                pygame.draw.rect(surface, (60, 0, 0), (bx, by, bar_w, 3))
                pygame.draw.rect(surface, (0, 200, 0),
                                 (bx, by, int(bar_w * ratio), 3))

    # ── HUD ───────────────────────────────────────────────────────

    def _draw_hud(self, surface: pygame.Surface, app: App,
                  sw: int, sh: int) -> None:
        # Health bar
        result = app.world.query_one(Player, Health)
        if result:
            _, _, hp = result
            bar_x, bar_y = 10, sh - 30
            bar_w, bar_h = 120, 12
            ratio = max(0.0, hp.current / hp.maximum)
            pygame.draw.rect(surface, (60, 0, 0), (bar_x, bar_y, bar_w, bar_h))
            pygame.draw.rect(surface, (0, 200, 0),
                             (bar_x, bar_y, int(bar_w * ratio), bar_h))
            app.draw_text(surface, f"{int(hp.current)}/{int(hp.maximum)} HP",
                          bar_x + bar_w + 6, bar_y - 1, (200, 200, 200),
                          app.font_sm)

        # Crosshair
        cx, cy = sw // 2, sh // 2
        pygame.draw.line(surface, (200, 200, 200), (cx - 6, cy), (cx + 6, cy))
        pygame.draw.line(surface, (200, 200, 200), (cx, cy - 6), (cx, cy + 6))

        # Zone name
        app.draw_text(surface, self.session.zone_name, sw - 100, 10,
                      (120, 140, 130), app.font_sm)

        # Interaction prompt
        target = nearest_interactable(app.world)
        if target:
            t_eid, _ = target
            ident = app.world.get(t_eid, Identity)
            name = ident.name if ident else f"Entity #{t_eid}"
            app.draw_text(surface, f"[E] {name}",
                          sw // 2 - 40, sh - 50,
                          (255, 230, 150), app.font_sm)

        # Status label
        if self.session.status_timer > 0 and self.session.status:
            alpha = min(1.0, self.session.status_timer / 0.5)
            c = int(220 * alpha)
            app.draw_text_bg(surface, self.session.status,
                             sw // 2 - 80, 40, (c, c, c))

        # Controls
        app.draw_text(surface,
                      "WASD=move  Arrows=turn  RMB+drag=look  E=interact  Esc=back",
                      10, sh - 14, (80, 100, 90), app.font_sm)

    # ── Minimap ──────────────────────────────────────────────────

    def _draw_minimap(self, surface: pygame.Surface, app: App,
                      px: float, py: float,
                      sw: int, sh: int) -> None:
        """Small top-down minimap in the corner."""
        tiles = self.session.tiles
        mw = self.session.map_w
        mh = self.session.map_h
        if not tiles:
            return

        cell = 4  # pixels per tile on minimap
        mm_w = mw * cell
        mm_h = mh * cell
        mm_x = sw - mm_w - 8
        mm_y = 24

        # Background
        bg = pygame.Surface((mm_w, mm_h), pygame.SRCALPHA)
        bg.fill((0, 0, 0, 140))
        surface.blit(bg, (mm_x, mm_y))

        # Tiles
        for row in range(mh):
            for col in range(mw):
                tid = tiles[row][col]
                if tid == TILE_WALL:
                    color = (150, 150, 160)
                else:
                    color = (40, 45, 35)
                pygame.draw.rect(surface, color,
                                 (mm_x + col * cell, mm_y + row * cell,
                                  cell, cell))

        # Entities
        zone = self.session.zone_name
        for _, epos, sprite in app.world.query(Position, Sprite):
            if epos.zone != zone:
                continue
            ex = mm_x + int(epos.x * cell)
            ey = mm_y + int(epos.y * cell)
            pygame.draw.circle(surface, sprite.color, (ex, ey), max(1, cell // 2))

        # Player dot + direction line
        ppx = mm_x + int(px * cell)
        ppy = mm_y + int(py * cell)
        pygame.draw.circle(surface, (255, 255, 100), (ppx, ppy), cell)
        end_x = ppx + int(math.cos(self.player_angle) * cell * 3)
        end_y = ppy + int(math.sin(self.player_angle) * cell * 3)
        pygame.draw.line(surface, (255, 255, 100), (ppx, ppy), (end_x, end_y), 1)

    def _draw_debug(self, surface: pygame.Surface, app: App,
                    px: float, py: float) -> None:
        y = 30
        fps = app.clock.get_fps()
        app.draw_text_bg(surface, f"FPS: {fps:.0f}", 10, y, (0, 255, 200))
        y += 16
        app.draw_text_bg(surface,
                         f"Pos: ({px:.1f}, {py:.1f})  Ang: {math.degrees(self.player_angle):.0f}°",
                         10, y, (0, 255, 200))
        y += 16
        n = len(app.world.zone_entities(self.session.zone_name))
        app.draw_text_bg(surface, f"Entities: {n}", 10, y, (0, 255, 200))
        y += 16
        clock = app.world.resources.try_get(GameClock)
        if clock:
            app.draw_text_bg(surface, f"Time: {clock.time:.1f}s",
                             10, y, (0, 255, 200))


# ── Angle  ↔  Direction helpers ──────────────────────────────────────

_DIR_ANGLES: dict[Direction, float] = {
    Direction.RIGHT: 0.0,
    Direction.DOWN:  math.pi * 0.5,
    Direction.LEFT:  math.pi,
    Direction.UP:    math.pi * 1.5,
}


def _direction_to_angle(d: Direction) -> float:
    return _DIR_ANGLES.get(d, math.pi * 1.5)


def _angle_to_direction(a: float) -> Direction:
    """Snap a continuous angle to the nearest cardinal direction."""
    a = a % (2 * math.pi)
    if a < math.pi * 0.25 or a >= math.pi * 1.75:
        return Direction.RIGHT
    if a < math.pi * 0.75:
        return Direction.DOWN
    if a < math.pi * 1.25:
        return Direction.LEFT
    return Direction.UP
