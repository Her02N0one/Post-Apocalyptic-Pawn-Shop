"""scenes/world/scene.py — Top-down tile scene.

Renders a tile grid and entities.  Camera follows the player.
WASD/arrows to move.  Escape to quit.  Tab toggles debug HUD.
"""

from __future__ import annotations

import pygame

from core.app import App
from core.constants import TILE_SIZE, TILE_COLORS
from core.scene import Scene
from core.types import Direction
from core.zones import load_zone as load_zone_data, Zone
from components import (
    Position, Velocity, Sprite, Player, Facing, Collider,
    Health, Identity, Camera, GameClock,
)
from systems.physics import movement_system
from systems.spawner import spawn_zone_entities
from systems.interaction import try_interact, nearest_interactable
from core.save import save_game, load_game, restore_entity, has_save
from core.events import InteractionEvent


class WorldScene(Scene):
    """Top-down tile-based game scene."""

    def __init__(self, zone_name: str = "playground") -> None:
        self.zone_name = zone_name
        self.show_debug = False
        self._interact_label: str = ""
        self._interact_timer: float = 0.0

        # Try to load from disk; fall back to blank grass field
        try:
            zd = load_zone_data(zone_name)
            self.tiles = zd.tiles
            self.anchor = zd.anchor
            self._entity_descriptors = zd.entities
        except FileNotFoundError:
            self.tiles = [[1] * 30 for _ in range(30)]
            self.anchor = (15.0, 15.0)
            self._entity_descriptors = []

        self.map_h = len(self.tiles)
        self.map_w = len(self.tiles[0]) if self.tiles else 0

    # ── Lifecycle ─────────────────────────────────────────────────

    def on_enter(self, app: App) -> None:
        if not app.world.resources.has(Camera):
            app.world.resources.set(Camera())
        if not app.world.resources.has(GameClock):
            app.world.resources.set(GameClock())

        # Move player to zone anchor if this is the first zone load
        result = app.world.query_one(Player, Position)
        if result:
            _, _, pos = result
            if pos.zone == self.zone_name:
                pass  # Already in this zone
            else:
                pos.x, pos.y = self.anchor
                app.world.set_zone(result[0], self.zone_name)

        # Spawn zone entities (NPCs, dummies, objects)
        if self._entity_descriptors:
            spawned = spawn_zone_entities(
                app.world, self._entity_descriptors, self.zone_name,
            )
            print(f"[ZONE] Spawned {len(spawned)} entities in '{self.zone_name}'")
            self._entity_descriptors = []  # Don't re-spawn on re-enter

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
                path = save_game(app.world, self.zone_name)
                self._interact_label = f"Saved to {path.name}"
                self._interact_timer = 2.0
            elif event.key == pygame.K_F9:
                self._do_load(app)

    def _do_interact(self, app: App) -> None:
        """Handle E key — interact with nearest entity."""
        if try_interact(app.world, app.world.events):
            # The event will be flushed during update(); show feedback now
            found = nearest_interactable(app.world)
            if found:
                ident = app.world.get(found[0], Identity)
                name = ident.name if ident else "???"
                self._interact_label = f"Interacted with {name}"
                self._interact_timer = 1.5
        else:
            self._interact_label = "Nothing nearby"
            self._interact_timer = 1.0

    def _do_load(self, app: App) -> None:
        """Handle F9 — load game from slot 0."""
        data = load_game(slot=0)
        if data is None:
            self._interact_label = "No save found"
            self._interact_timer = 1.5
            return

        # Clear all non-player entities in current zone
        player_result = app.world.query_one(Player, Position)
        player_eid = player_result[0] if player_result else -1

        for eid in list(app.world.zone_entities(self.zone_name)):
            if eid != player_eid:
                app.world.kill(eid)
        app.world.purge()

        # Restore persistent components onto existing entities
        for entry in data.get("entities", []):
            restored = restore_entity(app.world, entry)
            # If this was the player, merge onto existing player entity
            pos = app.world.get(restored, Position)
            if pos and player_eid > 0:
                from components import Health, Inventory
                p_pos = app.world.get(player_eid, Position)
                if p_pos:
                    p_pos.x, p_pos.y, p_pos.zone = pos.x, pos.y, pos.zone
                p_hp = app.world.get(player_eid, Health)
                r_hp = app.world.get(restored, Health)
                if p_hp and r_hp:
                    p_hp.current = r_hp.current
                    p_hp.maximum = r_hp.maximum
                # Remove the duplicate
                app.world.kill(restored)

        # Restore clock
        from components import GameClock
        clock = app.world.resources.try_get(GameClock)
        if clock:
            clock.time = data.get("clock", 0.0)

        app.world.purge()

        # Reload zone if it changed
        saved_zone = data.get("zone", self.zone_name)
        if saved_zone != self.zone_name:
            self.zone_name = saved_zone
            try:
                zd = load_zone_data(saved_zone)
                self.tiles = zd.tiles
                self.map_h = len(self.tiles)
                self.map_w = len(self.tiles[0]) if self.tiles else 0
                self._entity_descriptors = zd.entities
            except FileNotFoundError:
                pass

        # Re-spawn zone NPCs
        if self._entity_descriptors:
            spawn_zone_entities(app.world, self._entity_descriptors, self.zone_name)
            self._entity_descriptors = []

        self._interact_label = "Game loaded"
        self._interact_timer = 2.0

    # ── Update ────────────────────────────────────────────────────

    def update(self, dt: float, app: App) -> None:
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

        # ── Interaction label fade ─────────────────────────────
        if self._interact_timer > 0:
            self._interact_timer -= dt

        # ── Game clock ───────────────────────────────────────────
        clock = app.world.resources.try_get(GameClock)
        if clock:
            clock.time += dt

        # ── Physics ──────────────────────────────────────────────
        movement_system(app.world, dt, self.tiles)

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

        ox = sw // 2 - int(cam.x * TILE_SIZE)
        oy = sh // 2 - int(cam.y * TILE_SIZE)

        # Visible tile range (culling)
        c0 = max(0, -ox // TILE_SIZE)
        r0 = max(0, -oy // TILE_SIZE)
        c1 = min(self.map_w, (sw - ox) // TILE_SIZE + 1)
        r1 = min(self.map_h, (sh - oy) // TILE_SIZE + 1)

        # ── Tiles ────────────────────────────────────────────────
        for row in range(r0, r1):
            for col in range(c0, c1):
                tid = self.tiles[row][col]
                color = TILE_COLORS.get(tid, (40, 40, 40))
                rect = (ox + col * TILE_SIZE, oy + row * TILE_SIZE,
                        TILE_SIZE, TILE_SIZE)
                pygame.draw.rect(surface, color, rect)

        # ── Entities ─────────────────────────────────────────────
        for eid, pos, sprite in app.world.query(Position, Sprite):
            if pos.zone != self.zone_name:
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
        sw, _ = surface.get_size()

        result = app.world.query_one(Player, Health)
        if result:
            _, _, hp = result
            # Health bar
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
        app.draw_text(surface, self.zone_name, sw - 100, 10,
                      (120, 140, 130), app.font_sm)

        # Interaction prompt
        target = nearest_interactable(app.world)
        if target:
            t_eid, _ = target
            ident = app.world.get(t_eid, Identity)
            name = ident.name if ident else f"Entity #{t_eid}"
            app.draw_text(surface, f"[E] {name}",
                          sw // 2 - 40, surface.get_height() - 36,
                          (255, 230, 150), app.font_sm)

        # Status label (save/load/interaction feedback)
        if self._interact_timer > 0 and self._interact_label:
            alpha = min(1.0, self._interact_timer / 0.5)
            c = int(220 * alpha)
            app.draw_text_bg(surface, self._interact_label,
                             sw // 2 - 80, 40, (c, c, c))

        # Controls
        app.draw_text(surface, "WASD=move  E=interact  Tab=debug  F5=save  F9=load",
                      10, surface.get_height() - 18,
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
        n = len(app.world.zone_entities(self.zone_name))
        app.draw_text_bg(surface, f"Entities: {n}", 10, y, (0, 255, 200))
        y += 16

        clock = app.world.resources.try_get(GameClock)
        if clock:
            app.draw_text_bg(surface, f"Time: {clock.time:.1f}s",
                             10, y, (0, 255, 200))

