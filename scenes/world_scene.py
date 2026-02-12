"""
scenes/world_scene.py — Top-down tile view

Renders a tile grid and entities on top of it.
Camera follows the player. WASD to move.
Tab toggles debug overlay.

Tiles are just colored rectangles for now.
Entities render as colored characters at their float positions.
"""

from __future__ import annotations
import pygame
from core.scene import Scene
from core.app import App
from core.constants import TILE_SIZE
from components import (
    Position, Player, Camera, Identity, ItemRegistry,
    Health, Inventory, HitFlash, Lod, Facing, Equipment, Projectile,
    GameClock,
)
from logic.systems import movement_system, input_system, item_pickup_system
from logic.brains import run_brains
from logic.lod_system import lod_system
from logic.needs_system import hunger_system, auto_eat_system, settlement_food_production
from logic.actions import mouse_world_pos
from logic.projectiles import projectile_system
from logic.particles import ParticleManager
from logic.input_manager import InputManager, InputContext
from logic.entity_factory import spawn_zone_entities, spawn_test_entities
from ui import ModalStack
from scenes.editor_controller import EditorController
from scenes.world_draw import (
    draw_tiles, draw_entities, draw_debug_colliders, draw_weapon_hitbox,
    draw_muzzle_flash, draw_particles, draw_projectiles, draw_crosshair,
    draw_range_ring, draw_tooltip, draw_hud, draw_debug_overlay,
)
from core.zone import ZONE_MAPS, ZONE_TELEPORTERS, ZONE_ANCHORS
from core.save import save_game_state
from scenes.zone_manager import load_zone, check_player_teleport
from scenes.world_helpers import (
    update_input_context, route_ui_event, process_gameplay_intents,
    update_tooltips, tick_timers,
)
from simulation.world_sim import WorldSim


class WorldScene(Scene):
    def __init__(self, tile_map: list[list[int]] | None = None,
                 editor_mode: bool = False, zone_name: str | None = None):
        self.editor_active = False
        self.editor_mode = bool(editor_mode)
        self.zone = zone_name or "overworld"
        self.npcs_enabled = False

        self.editor = EditorController()

        if self.editor_mode and self.zone not in ZONE_MAPS:
            tile_map = [[1] * 30 for _ in range(30)]
            self.editor_active = True

        if tile_map is None and self.zone in ZONE_MAPS:
            src = ZONE_MAPS[self.zone]
            tile_map = [row[:] for row in src]
        elif tile_map is None:
            tile_map = [[1] * 30 for _ in range(30)]

        self.tiles = tile_map
        self.map_h = len(tile_map)
        self.map_w = len(tile_map[0]) if tile_map else 0
        if self.editor_active:
            self._orig_tiles = [row[:] for row in self.tiles]
        self.show_debug = False
        self.show_grid = False
        self.show_all_zones = False

        # Attack visualization state
        self.attack_active = False
        self.attack_timer = 0.0
        self.attack_direction = (1, 0)
        self.attack_cooldown = 0.0
        self.attack_cooldown_max = 0.3

        # Mouse aim state
        self.mouse_world_x = 0.0
        self.mouse_world_y = 0.0
        self.show_crosshair = True

        # Muzzle flash (ranged weapon visual)
        self.muzzle_flash_timer = 0.0
        self.muzzle_flash_start: tuple[float, float] = (0.0, 0.0)
        self.muzzle_flash_end: tuple[float, float] = (0.0, 0.0)

        # Entity tooltip (mouse hover)
        self.tooltip_eid: int | None = None
        self.tooltip_text: str = ""
        self.tooltip_hp: tuple[float, float] | None = None

        # UI modal stack
        self.modals = ModalStack()

        # Intent-based input system
        self.input = InputManager()

        # World simulation (off-screen persistent entities)
        self.world_sim: WorldSim | None = None

        # Time-scale for fast-forward (1.0 = normal, hold F for 10x)
        self.time_scale: float = 1.0

        if tile_map is not None and not self.editor_active:
            ZONE_MAPS[self.zone] = tile_map

        if not self.editor_active:
            load_zone(self, self.zone)
        else:
            # Editor mode: populate teleporters from portals + legacy
            from core.zone import portal_lookup_for_zone
            self.editor.teleporters = {}
            for (r, c), (tz, sr, sc, pid) in portal_lookup_for_zone(self.zone).items():
                self.editor.teleporters[(r, c)] = {
                    "zone": tz, "r": int(sr), "c": int(sc), "portal_id": pid,
                }
                if 0 <= r < self.map_h and 0 <= c < self.map_w:
                    self.tiles[r][c] = 9
            for (r, c), tgt in ZONE_TELEPORTERS.get(self.zone, {}).items():
                if (r, c) not in self.editor.teleporters:
                    self.editor.teleporters[(r, c)] = tgt
                    if 0 <= r < self.map_h and 0 <= c < self.map_w:
                        self.tiles[r][c] = 9

    def on_enter(self, app: App):
        if not app.world.res(Camera):
            app.world.set_res(Camera())
        if not app.world.res(GameClock):
            app.world.set_res(GameClock())
        from components.dev_log import DevLog
        if not app.world.res(DevLog):
            app.world.set_res(DevLog())

        from logic.quests import QuestLog
        from logic.dialogue import DialogueManager, load_builtin_trees
        if not app.world.res(QuestLog):
            app.world.set_res(QuestLog())
        if not app.world.res(DialogueManager):
            dm = DialogueManager()
            load_builtin_trees(dm)
            app.world.set_res(dm)

        if self.editor_active:
            cx = self.map_w / 2.0
            cy = self.map_h / 2.0
            res = app.world.query_one(Player, Position)
            if res:
                eid, _, pos = res
                pos.zone = self.zone
                app.world.zone_set(eid, self.zone)
                pos.x = cx
                pos.y = cy
            cam = app.world.res(Camera)
            if cam:
                cam.x = cx
                cam.y = cy

        if self.npcs_enabled:
            try:
                spawn_zone_entities(app.world, self.zone, npcs_enabled=True)
            except Exception as ex:
                print(f"[ZONE] spawn error: {ex}")

        # Initialise off-screen world simulation
        self._init_world_sim(app)

    def _init_world_sim(self, app: App):
        """Initialise the world simulation if a subzone graph exists."""
        from pathlib import Path
        from components.simulation import Stockpile
        from simulation.economy import create_settlement
        graph_path = Path("data/subzones.toml")
        if not graph_path.exists():
            return
        try:
            self.world_sim = WorldSim(app.world)
            self.world_sim.load_graph(graph_path)

            # Ensure the settlement stockpile exists for the sim layer
            has_stockpile = any(True for _ in app.world.all_of(Stockpile))
            if not has_stockpile:
                graph = self.world_sim.graph
                subzone_id = "sett_storehouse"
                if subzone_id not in graph.nodes:
                    for node in graph.nodes.values():
                        if node.zone == "settlement":
                            subzone_id = node.id
                            break
                node = graph.get_node(subzone_id)
                if node:
                    create_settlement(app.world, "Settlement", node.zone, node.id)

            # Attach container EIDs to graph nodes (set by _spawn_characters)
            cmap = app.world.res(type(None))  # placeholder
            # Look for _ContainerMap resource by scanning stores
            for cls, store in app.world._stores.items():
                if cls.__name__ == "_ContainerMap" and -1 in store:
                    cmap = store[-1]
                    break
            if cmap and hasattr(cmap, "mapping"):
                for subzone_id, eids in cmap.mapping.items():
                    node = self.world_sim.graph.get_node(subzone_id)
                    if node:
                        node.container_eids.extend(eids)
                print(f"[SIM] Attached containers to {len(cmap.mapping)} subzone nodes")

            clock = app.world.res(GameClock)
            game_time = clock.time if clock else 0.0
            # clock.time IS game-minutes (1 real sec = 1 game min)
            self.world_sim.bootstrap(app.world, game_time)

            # Promote entities in the player's starting zone to high-LOD
            self.world_sim.on_zone_change(app.world, self.zone, game_time)
        except Exception as ex:
            print(f"[SIM] Failed to initialise world sim: {ex}")
            import traceback; traceback.print_exc()
            self.world_sim = None

    # ── helpers ──────────────────────────────────────────────────────

    def _screen_to_tile(self, mx: int, my: int, app: App):
        """Convert mouse screen coords to (row, col) tile coords or None."""
        cam = app.world.res(Camera) or Camera()
        sw, sh = app._virtual_size
        ox = sw // 2 - int(cam.x * TILE_SIZE)
        oy = sh // 2 - int(cam.y * TILE_SIZE)
        col = (mx - ox) // TILE_SIZE
        row = (my - oy) // TILE_SIZE
        if 0 <= row < self.map_h and 0 <= col < self.map_w:
            return row, col
        return None

    # ── event handler ────────────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event, app: App):
        update_input_context(self)
        self.input.feed(event)

        if event.type == pygame.KEYDOWN:
            if self.editor.text_input_active:
                self.editor.handle_key(event, self)
                return
            if self.modals.is_open:
                route_ui_event(self, event, app)
                return

        elif event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEMOTION) and self.modals.is_open:
            route_ui_event(self, event, app)
            return

        elif event.type == pygame.MOUSEBUTTONDOWN and self.editor_active:
            self.editor.handle_mouse_down(event, app, self)

        elif event.type == pygame.MOUSEBUTTONUP and self.editor_active:
            if event.button == 1 and self.editor.mouse_drag_start is not None:
                rc = self._screen_to_tile(*event.pos, app)
                if rc:
                    row, col = rc
                    r0, c0 = self.editor.mouse_drag_start
                    rmin, rmax = min(r0, row), max(r0, row)
                    cmin, cmax = min(c0, col), max(c0, col)
                    for rr in range(rmin, rmax + 1):
                        for cc in range(cmin, cmax + 1):
                            self.tiles[rr][cc] = self.editor.selected_tile
                    print(f"[EDITOR] filled ({rmin},{cmin})-({rmax},{cmax})")
                self.editor.mouse_drag_start = None

    # ── update ───────────────────────────────────────────────────────

    def update(self, dt: float, app: App):
        self._last_dt = dt
        update_input_context(self)
        self.input.end_frame()

        # ── Fast-forward: hold F for 10x, Shift+F for 30x ──
        keys = pygame.key.get_pressed()
        if keys[pygame.K_f] and not self.editor_active and not self.modals.is_open:
            mods = pygame.key.get_mods()
            self.time_scale = 30.0 if (mods & pygame.KMOD_SHIFT) else 10.0
        else:
            self.time_scale = 1.0

        # Apply time scale to dt for simulation systems
        scaled_dt = dt * self.time_scale

        if self.input.context == InputContext.GAMEPLAY:
            process_gameplay_intents(self, app)
        elif self.input.context == InputContext.EDITOR:
            self.editor.update_intents(self.input, self, app)

        input_system(app.world, move=self.input.movement())
        self.input.begin_frame()
        self.modals.update(dt)
        clock = app.world.res(GameClock)
        if clock:
            clock.time += scaled_dt
        lod_system(app.world, dt)
        hunger_system(app.world, scaled_dt)
        auto_eat_system(app.world, scaled_dt)
        settlement_food_production(app.world, scaled_dt)
        run_brains(app.world, dt)
        movement_system(app.world, dt, self.tiles)
        projectile_system(app.world, dt, self.tiles)

        # Tick the off-screen world simulation
        if self.world_sim and self.world_sim.active:
            # clock.time IS game-minutes (1 real sec = 1 game min)
            game_minutes = clock.time if clock else 0.0
            # When fast-forwarding, tick multiple times to process queued events
            if self.time_scale > 1.01:
                steps = min(int(self.time_scale), 30)
                for _ in range(steps):
                    self.world_sim.tick(app.world, game_minutes)
            else:
                self.world_sim.tick(app.world, game_minutes)

        app.world.purge()

        mw = mouse_world_pos(app, self)
        if mw:
            self.mouse_world_x, self.mouse_world_y = mw

        update_tooltips(self, app, mw)
        tick_timers(self, dt, app)

        pm = app.world.res(ParticleManager)
        if pm:
            pm.update(dt)

        check_player_teleport(self, app)

        result = app.world.query_one(Player, Position)
        cam = app.world.res(Camera)
        if result and cam:
            _, _, pos = result
            cam.x = pos.x
            cam.y = pos.y

        item_pickup_system(app.world)

        if self.editor_active:
            self.editor.continuous_paint(app, self, cam)

    # ── draw ─────────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, app: App):
        surface.fill((20, 20, 25))
        cam = app.world.res(Camera) or Camera()
        sw, sh = surface.get_size()

        ox = sw // 2 - int(cam.x * TILE_SIZE)
        oy = sh // 2 - int(cam.y * TILE_SIZE)

        start_col = max(0, -ox // TILE_SIZE)
        start_row = max(0, -oy // TILE_SIZE)
        end_col = min(self.map_w, (sw - ox) // TILE_SIZE + 1)
        end_row = min(self.map_h, (sh - oy) // TILE_SIZE + 1)

        draw_tiles(surface, self.tiles, ox, oy, self.show_grid,
                   start_row, start_col, end_row, end_col)
        draw_entities(surface, app, ox, oy, self.zone, self.show_all_zones)

        if self.show_debug:
            draw_debug_colliders(surface, app, ox, oy, self.zone, self.show_all_zones)

        draw_weapon_hitbox(surface, app, self, ox, oy)
        draw_muzzle_flash(surface, self, ox, oy)

        pm = app.world.res(ParticleManager)
        if pm:
            draw_particles(pm, surface, ox, oy, TILE_SIZE)

        draw_projectiles(surface, app, ox, oy, self.zone)
        draw_crosshair(surface, app, self)
        draw_range_ring(surface, app, ox, oy, self.zone, self)
        draw_tooltip(surface, app, self)
        draw_hud(surface, app, self)

        if self.modals.is_open:
            self.modals.draw(surface, app)

        if self.show_debug:
            draw_debug_overlay(surface, app, self, cam)

        if self.editor_active:
            self.editor.draw(surface, app, self, cam, ox, oy,
                             start_row, start_col, end_row, end_col)

