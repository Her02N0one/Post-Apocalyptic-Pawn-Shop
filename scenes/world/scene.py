"""scenes/world/scene.py — Top-down tile scene (presentation layer).

Renders tiles and entities.  Camera follows the player.
WASD to move.  E to interact.  Tab toggles debug HUD.
F5 to save.  F9 to load.  Escape to quit.

The scene reads world layout from a ``Session`` and never loads
zone data or spawns entities itself.
"""

from __future__ import annotations

import pygame

from core.app import App
from core.constants import TILE_SIZE, TILE_COLORS
from core.scene import Scene
from core.types import Direction
from components import (
    Position, Velocity, Sprite, Player, Facing,
    Health, Identity, Camera, GameClock,
)
from systems.physics import movement_system
from systems.interaction import try_interact, nearest_interactable

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.session import Session


class WorldScene(Scene):
    """Top-down tile-based game scene (presentation only).

    All zone loading, entity spawning, and save/load orchestration
    live in ``Session``.  This scene only reads data and renders.
    """

    def __init__(self, session: "Session") -> None:
        self.session = session
        self.show_debug = False

    # ── Lifecycle ─────────────────────────────────────────────────

    def on_enter(self, app: App) -> None:
        # Ensure resources exist (camera / clock set by session.new_game)
        if not app.world.resources.has(Camera):
            app.world.resources.set(Camera())
        if not app.world.resources.has(GameClock):
            app.world.resources.set(GameClock())

    # ── Events ────────────────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event, app: App) -> None:
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                app.running = False
            elif event.key == pygame.K_TAB:
                self.show_debug = not self.show_debug
            elif event.key == pygame.K_e:
                self._do_interact(app)
            elif event.key == pygame.K_F5:
                self.session.save()
            elif event.key == pygame.K_F9:
                self.session.load()
            elif event.key == pygame.K_RETURN:
                from scenes.world.doom_scene import DoomScene
                app.push_scene(DoomScene(self.session))

    def _do_interact(self, app: App) -> None:
        """Handle E key — interact with nearest entity."""
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
        # Status fade
        if self.session.status_timer > 0:
            self.session.status_timer -= dt

        keys = pygame.key.get_pressed()

        # ── Input → player velocity ──────────────────────────────
        dx = dy = 0.0
        if keys[pygame.K_w] or keys[pygame.K_UP]:    dy -= 1
        if keys[pygame.K_s] or keys[pygame.K_DOWN]:  dy += 1
        if keys[pygame.K_a] or keys[pygame.K_LEFT]:  dx -= 1
        if keys[pygame.K_d] or keys[pygame.K_RIGHT]: dx += 1

        # Normalise diagonal movement
        if dx and dy:
            dx *= 0.7071
            dy *= 0.7071

        for eid, player, vel in app.world.query(Player, Velocity):
            vel.x = dx * player.speed
            vel.y = dy * player.speed

            facing = app.world.get(eid, Facing)
            if facing and (abs(vel.x) > 0.01 or abs(vel.y) > 0.01):
                if abs(vel.x) >= abs(vel.y):
                    facing.direction = (
                        Direction.RIGHT if vel.x > 0 else Direction.LEFT
                    )
                else:
                    facing.direction = (
                        Direction.DOWN if vel.y > 0 else Direction.UP
                    )

        # ── Game clock ───────────────────────────────────────────
        clock = app.world.resources.try_get(GameClock)
        if clock:
            clock.time += dt

        # ── Physics ──────────────────────────────────────────────
        movement_system(app.world, dt, self.session.tiles)

        # ── Events ───────────────────────────────────────────────
        app.world.events.flush()

        # ── Camera follow player ─────────────────────────────────
        cam = app.world.resources.try_get(Camera)
        result = app.world.query_one(Player, Position)
        if cam and result:
            _, _, pos = result
            cam.x = pos.x
            cam.y = pos.y

        app.world.purge()

    # ── Draw ──────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, app: App) -> None:
        surface.fill((20, 20, 25))
        cam = app.world.resources.try_get(Camera) or Camera()
        sw, sh = surface.get_size()

        zone = self.session.zone_name
        tiles = self.session.tiles
        map_h = self.session.map_h
        map_w = self.session.map_w

        ox = sw // 2 - int(cam.x * TILE_SIZE)
        oy = sh // 2 - int(cam.y * TILE_SIZE)

        # Visible tile range (culling)
        c0 = max(0, -ox // TILE_SIZE)
        r0 = max(0, -oy // TILE_SIZE)
        c1 = min(map_w, (sw - ox) // TILE_SIZE + 1)
        r1 = min(map_h, (sh - oy) // TILE_SIZE + 1)

        # ── Tiles ────────────────────────────────────────────────
        for row in range(r0, r1):
            for col in range(c0, c1):
                tid = tiles[row][col]
                color = TILE_COLORS.get(tid, (40, 40, 40))
                rect = (ox + col * TILE_SIZE, oy + row * TILE_SIZE,
                        TILE_SIZE, TILE_SIZE)
                pygame.draw.rect(surface, color, rect)

        # ── Entities ─────────────────────────────────────────────
        for eid, pos, sprite in app.world.query(Position, Sprite):
            if pos.zone != zone:
                continue
            px = ox + int(pos.x * TILE_SIZE)
            py = oy + int(pos.y * TILE_SIZE)
            img = app.font.render(sprite.char, True, sprite.color)
            surface.blit(img, (px + 4, py + 2))

            # Health bar for non-player entities
            hp = app.world.get(eid, Health)
            if hp and not app.world.has(eid, Player) and hp.current < hp.maximum:
                bar_w = TILE_SIZE - 4
                ratio = max(0.0, hp.current / hp.maximum)
                pygame.draw.rect(surface, (60, 0, 0),
                                 (px + 2, py - 4, bar_w, 3))
                pygame.draw.rect(surface, (0, 200, 0),
                                 (px + 2, py - 4, int(bar_w * ratio), 3))

        # ── HUD ──────────────────────────────────────────────────
        self._draw_hud(surface, app)

        # ── Debug overlay ────────────────────────────────────────
        if self.show_debug:
            self._draw_debug(surface, app)

    # ── HUD ───────────────────────────────────────────────────────

    def _draw_hud(self, surface: pygame.Surface, app: App) -> None:
        """Minimal HUD: health bar, zone name, controls hint."""
        sw, sh = surface.get_size()

        # Health bar
        result = app.world.query_one(Player, Health)
        if result:
            _, _, hp = result
            bar_x, bar_y = 10, 10
            bar_w, bar_h = 120, 12
            ratio = max(0.0, hp.current / hp.maximum)
            pygame.draw.rect(surface, (60, 0, 0), (bar_x, bar_y, bar_w, bar_h))
            pygame.draw.rect(surface, (0, 200, 0),
                             (bar_x, bar_y, int(bar_w * ratio), bar_h))
            app.draw_text(surface, f"{int(hp.current)}/{int(hp.maximum)} HP",
                          bar_x + bar_w + 6, bar_y - 1, (200, 200, 200),
                          app.font_sm)

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
                          sw // 2 - 40, sh - 36,
                          (255, 230, 150), app.font_sm)

        # Status label (save/load/interaction feedback)
        if self.session.status_timer > 0 and self.session.status:
            alpha = min(1.0, self.session.status_timer / 0.5)
            c = int(220 * alpha)
            app.draw_text_bg(surface, self.session.status,
                             sw // 2 - 80, 40, (c, c, c))

        # Controls
        app.draw_text(surface, "WASD=move  E=interact  Enter=1st person  Tab=debug  F5=save  F9=load",
                      10, sh - 18,
                      (80, 100, 90), app.font_sm)

    def _draw_debug(self, surface: pygame.Surface, app: App) -> None:
        """Debug overlay: FPS, position, entity count."""
        y = 30
        fps = app.clock.get_fps()
        app.draw_text_bg(surface, f"FPS: {fps:.0f}", 10, y, (0, 255, 200))
        y += 16

        result = app.world.query_one(Player, Position)
        if result:
            _, _, pos = result
            app.draw_text_bg(surface, f"Pos: ({pos.x:.1f}, {pos.y:.1f})",
                             10, y, (0, 255, 200))
            y += 16

        # Count entities in current zone
        n = len(app.world.zone_entities(self.session.zone_name))
        app.draw_text_bg(surface, f"Entities: {n}", 10, y, (0, 255, 200))
        y += 16

        clock = app.world.resources.try_get(GameClock)
        if clock:
            app.draw_text_bg(surface, f"Time: {clock.time:.1f}s",
                             10, y, (0, 255, 200))

