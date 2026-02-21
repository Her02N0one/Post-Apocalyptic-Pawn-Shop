"""scenes/world/firstperson.py — First-person raycasted scene controller.

Thin orchestrator that owns player input, lifecycle, interaction, and
update logic.  All rendering is delegated to ``fp_renderer.Renderer``
and ``fp_hud.HUD``.  Entity-interaction / inventory methods live in
``fp_interact``.

Controls:
    W / S          — move forward / backward
    A / D          — strafe left / right
    Left / Right   — turn camera (or hold right mouse button + drag)
    Space          — dash in current movement direction
    E              — interact with nearest entity
    I              — open inventory
    Tab            — toggle debug overlay / minimap
    Escape         — pause menu
    Backspace      — return to top-down view
    F5 / F9        — save / load

The scene reads tiles and entities from the shared ``Session`` and
never creates or loads data itself.
"""

from __future__ import annotations

import gc
import math
import time

import pygame

from core.app import App
from core.scene import Scene
from core.types import Direction
from components import (
    Position, Velocity, Player, Facing,
    Health, Camera, GameClock, WorldClock,
)
from systems.physics import movement_system
from systems.interaction import set_camera_angle
from systems.item_registry import ItemRegistry
from ui.modal import ModalStack
from ui.commands import CloseModal, HealPlayer

from scenes.world.fp_renderer import (
    Renderer, FOV, day_night_factor, compute_fog_params,
)
from scenes.world.fp_hud import HUD
from scenes.world.fp_perflog import PerfLogger

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.session import Session

# ── Constants (player control) ───────────────────────────────────
TURN_SPEED = 3.5
TURN_ACCEL = 18.0
TURN_FRICTION = 12.0
MOUSE_SENSITIVITY = 0.004
HEAD_BOB_SPEED = 8.0
HEAD_BOB_AMP = 4.0
MOVE_ACCEL = 18.0
MOVE_FRICTION = 10.0
SPRINT_MULTIPLIER = 1.6
SPRINT_BOB_MULT = 1.4
SPRINT_FOV_BOOST = 0.08
DAMAGE_FLASH_DUR = 0.3
SWAY_AMOUNT = 2.0
SWAY_DECAY = 8.0

# Dash
DASH_SPEED = 12.0
DASH_DURATION = 0.15
DASH_COOLDOWN = 0.45
DASH_FOV_PUNCH = 0.14

# Internal render resolution — render at 1/RSCALE then upscale.
# 2 = half-res (480×320 → 960×640), huge perf win with retro look.
_RSCALE = 2


class FirstPerson(Scene):
    """First-person raycasted view — delegates rendering to Renderer/HUD."""

    def __init__(self, session: "Session") -> None:
        self.session = session
        self.player_angle: float = math.pi * 1.5
        self.show_debug = False
        self._mouse_captured = False
        self._renderer = Renderer()
        self._hud = HUD()
        self._registry = ItemRegistry()
        self.modals = ModalStack()
        self._perflog = PerfLogger()
        # Render profiler
        self._prof_history: dict[str, list[float]] = {}
        self._prof_order: list[str] = []
        self._PROF_LEN = 60
        # Head bob
        self._bob_timer: float = 0.0
        self._bob_offset: float = 0.0
        # Smooth movement
        self._move_vx: float = 0.0
        self._move_vy: float = 0.0
        # Smooth turning
        self._turn_vel: float = 0.0
        # Sprint state
        self._sprinting: bool = False
        self._sprint_fov: float = 0.0
        # Damage flash
        self._damage_flash: float = 0.0
        self._last_hp: float = -1.0
        # View sway
        self._sway_offset: float = 0.0
        # Footstep
        self._step_phase: float = 0.0
        self._last_step_side: int = 0
        # Dash state
        self._dash_timer: float = 0.0
        self._dash_cooldown: float = 0.0
        self._dash_dir: tuple[float, float] = (0.0, 0.0)

    # ── Attach interaction methods from fp_interact ──────────────
    from scenes.world.fp_interact import (  # type: ignore[assignment]
        _do_interact,
        _open_npc_dialogue,
        _open_inventory,
        _spawn_ground_item,
        _pickup_ground_item,
        _open_container,
        _try_platform_interact,
        _get_platform_entity,
        _roll_loot,
    )

    # ── Public query ───────────────────────────────────────────

    @property
    def is_dashing(self) -> bool:
        """True while the player is in a dash burst."""
        return self._dash_timer > 0.0

    # ── Lifecycle ─────────────────────────────────────────────────

    def on_enter(self, app: App) -> None:
        result = app.world.query_one(Player, Facing)
        if result:
            _, _, facing = result
            self.player_angle = _direction_to_angle(facing.direction)

        if not app.world.resources.has(Camera):
            app.world.resources.set(Camera())
        if not app.world.resources.has(GameClock):
            app.world.resources.set(GameClock())

        pygame.event.set_grab(True)
        pygame.mouse.set_visible(False)
        self._mouse_captured = True
        set_camera_angle(self.player_angle)

        self._move_vx = 0.0
        self._move_vy = 0.0
        self._turn_vel = 0.0
        self._sway_offset = 0.0
        self._sprint_fov = 0.0
        self._sprinting = False
        self._bob_timer = 0.0
        self._bob_offset = 0.0

        hp_res = app.world.query_one(Player, Health)
        if hp_res:
            self._last_hp = hp_res[2].current

        self._renderer.invalidate_zone(self.session.zone_name)
        self._renderer.warmup()

    def on_exit(self, app: App) -> None:
        if self._perflog.active:
            self._perflog.stop()
        result = app.world.query_one(Player, Facing)
        if result:
            _, _, facing = result
            facing.direction = _angle_to_direction(self.player_angle)

        if not self.session.auto_walk_active:
            for _, _, vel in app.world.query(Player, Velocity):
                vel.x = 0.0
                vel.y = 0.0

        set_camera_angle(None)
        pygame.event.set_grab(False)
        pygame.mouse.set_visible(True)
        self._mouse_captured = False

    def _release_mouse(self) -> None:
        """Release the mouse grab so modal UIs can use the cursor."""
        if self._mouse_captured:
            pygame.event.set_grab(False)
            pygame.mouse.set_visible(True)
            self._mouse_captured = False

    # ── Events ────────────────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event, app: App) -> None:
        if self.modals.is_open:
            cmds = self.modals.handle_event(event)
            for cmd in cmds:
                if isinstance(cmd, CloseModal):
                    self.modals.pop()
                    if not self.modals.is_open:
                        pygame.event.set_grab(True)
                        pygame.mouse.set_visible(False)
                        self._mouse_captured = True
                elif isinstance(cmd, HealPlayer):
                    res = app.world.query_one(Player, Health)
                    if res:
                        _, _, hp = res
                        hp.current = min(hp.maximum, hp.current + cmd.amount)
            return

        if self.session.auto_walk_active or self.session._fade_direction != 0:
            return
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                if self._mouse_captured:
                    pygame.event.set_grab(False)
                    pygame.mouse.set_visible(True)
                    self._mouse_captured = False
                from scenes.pause_menu import PauseMenu
                app.push_scene(PauseMenu(self.session))
            elif event.key == pygame.K_TAB:
                self.show_debug = not self.show_debug
            elif event.key == pygame.K_e:
                if not self.is_dashing:
                    self._do_interact(app)
            elif event.key == pygame.K_i:
                if not self.is_dashing:
                    self._open_inventory(app)
            elif event.key == pygame.K_F5:
                self.session.save()
            elif event.key == pygame.K_F9:
                self.session.load()
            elif event.key == pygame.K_F4:
                from scenes.editor import MapEditor
                app.push_scene(MapEditor(self.session.zone_name))
            elif event.key == pygame.K_F6:
                msg = self._perflog.toggle()
                print(msg)
            elif event.key == pygame.K_BACKSPACE:
                app.pop_scene()
            elif event.key == pygame.K_PERIOD:
                self._cycle_time_scale(app, 1)
            elif event.key == pygame.K_COMMA:
                self._cycle_time_scale(app, -1)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if not self._mouse_captured:
                pygame.event.set_grab(True)
                pygame.mouse.set_visible(False)
                self._mouse_captured = True
        elif event.type == pygame.MOUSEMOTION and self._mouse_captured:
            dx = event.rel[0] * MOUSE_SENSITIVITY
            self.player_angle += dx
            self._sway_offset += dx * 80.0

    def _cycle_time_scale(self, app: App, direction: int) -> None:
        """Cycle WorldClock.time_scale up (+1) or down (-1)."""
        wc = app.world.resources.try_get(WorldClock)
        if not wc:
            return
        scales = wc.TIME_SCALES
        try:
            idx = scales.index(wc.time_scale)
        except ValueError:
            idx = 0
        idx = max(0, min(len(scales) - 1, idx + direction))
        wc.time_scale = scales[idx]
        if wc.time_scale == 1.0:
            self.session.status = "Normal speed"
        else:
            self.session.status = f"Fast-forward {int(wc.time_scale)}×"
        self.session.status_timer = 1.5

    # ── Update ────────────────────────────────────────────────────

    def update(self, dt: float, app: App) -> None:
        if self.modals.is_open:
            self.modals.update(dt)

        if self.session.status_timer > 0:
            self.session.status_timer -= dt

        if self.modals.is_open:
            for eid, player, vel in app.world.query(Player, Velocity):
                vel.x = 0.0
                vel.y = 0.0
            return

        was_fading_in = (self.session._fade_direction == -1)
        self.session.update_transition(dt)

        if was_fading_in or self.session.auto_walk_active:
            result = app.world.query_one(Player, Facing)
            if result:
                _, _, facing = result
                self.player_angle = _direction_to_angle(facing.direction)

        # After a portal transition, stay in FP mode regardless of zone
        # (seamless view switching — both views always available).

        if not self.session.auto_walk_active and self.session._fade_direction == 0:
            keys = pygame.key.get_pressed()

            self._sprinting = bool(keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT])

            # ── Dash trigger ─────────────────────────────────
            if keys[pygame.K_SPACE] and self._dash_cooldown <= 0.0 and self._dash_timer <= 0.0:
                _fwd = 0.0
                _str = 0.0
                if keys[pygame.K_w] or keys[pygame.K_UP]:    _fwd += 1
                if keys[pygame.K_s] or keys[pygame.K_DOWN]:  _fwd -= 1
                if keys[pygame.K_a]:  _str -= 1
                if keys[pygame.K_d]:  _str += 1
                _mag = math.sqrt(_fwd * _fwd + _str * _str)
                if _mag < 0.01:
                    _fwd = 1.0
                    _mag = 1.0
                _fwd /= _mag
                _str /= _mag
                _ca = math.cos(self.player_angle)
                _sa = math.sin(self.player_angle)
                self._dash_dir = (_fwd * _ca + _str * (-_sa),
                                  _fwd * _sa + _str * _ca)
                self._dash_timer = DASH_DURATION
                self._dash_cooldown = DASH_COOLDOWN

            # ── Turn (keyboard, smoothed) ────────────────────
            turn_input = 0.0
            if keys[pygame.K_LEFT]:  turn_input -= 1.0
            if keys[pygame.K_RIGHT]: turn_input += 1.0
            if abs(turn_input) > 0.01:
                self._turn_vel += (turn_input * TURN_SPEED - self._turn_vel) * min(1.0, TURN_ACCEL * dt)
                self._sway_offset += turn_input * SWAY_AMOUNT * 4.0 * dt
            else:
                self._turn_vel *= max(0.0, 1.0 - TURN_FRICTION * dt)
                if abs(self._turn_vel) < 0.01:
                    self._turn_vel = 0.0
            self.player_angle += self._turn_vel * dt

            # ── Movement (smooth accel / decel) ──────────────
            fwd = 0.0
            strafe = 0.0
            if keys[pygame.K_w] or keys[pygame.K_UP]:    fwd += 1
            if keys[pygame.K_s] or keys[pygame.K_DOWN]:  fwd -= 1
            if keys[pygame.K_a]:  strafe -= 1
            if keys[pygame.K_d]:  strafe += 1

            mag = math.sqrt(fwd * fwd + strafe * strafe)
            if mag > 0.01:
                fwd /= mag
                strafe /= mag

            cos_a = math.cos(self.player_angle)
            sin_a = math.sin(self.player_angle)
            want_dx = fwd * cos_a + strafe * (-sin_a)
            want_dy = fwd * sin_a + strafe * cos_a
            moving = (abs(want_dx) > 0.01 or abs(want_dy) > 0.01)

            sprint_mult = SPRINT_MULTIPLIER if self._sprinting and moving else 1.0

            for eid, player, vel in app.world.query(Player, Velocity):
                spd = player.speed * sprint_mult
                if self._dash_timer > 0.0:
                    vel.x = self._dash_dir[0] * DASH_SPEED
                    vel.y = self._dash_dir[1] * DASH_SPEED
                elif moving:
                    self._move_vx += (want_dx * spd - self._move_vx) * min(1.0, MOVE_ACCEL * dt)
                    self._move_vy += (want_dy * spd - self._move_vy) * min(1.0, MOVE_ACCEL * dt)
                else:
                    decay = max(0.0, 1.0 - MOVE_FRICTION * dt)
                    self._move_vx *= decay
                    self._move_vy *= decay
                    if abs(self._move_vx) < 0.01:
                        self._move_vx = 0.0
                    if abs(self._move_vy) < 0.01:
                        self._move_vy = 0.0

                vel.x = self._move_vx
                vel.y = self._move_vy

            # ── Head bob ─────────────────────────────────────
            actual_speed = math.sqrt(self._move_vx ** 2 + self._move_vy ** 2)
            bob_speed = HEAD_BOB_SPEED * (SPRINT_BOB_MULT if self._sprinting else 1.0)
            bob_amp = HEAD_BOB_AMP * (SPRINT_BOB_MULT if self._sprinting else 1.0)
            if actual_speed > 0.3:
                self._bob_timer += dt * bob_speed
                self._bob_offset = math.sin(self._bob_timer) * bob_amp
                new_phase = int(self._bob_timer / math.pi)
                if new_phase != self._last_step_side:
                    self._last_step_side = new_phase
                    self._step_phase = 1.0
            else:
                self._bob_timer = 0.0
                self._bob_offset *= max(0.0, 1.0 - 10.0 * dt)
        else:
            self._sprinting = False

        # ── Decay view sway ──────────────────────────────────
        self._sway_offset *= max(0.0, 1.0 - SWAY_DECAY * dt)
        if abs(self._sway_offset) < 0.1:
            self._sway_offset = 0.0
        self._sway_offset = max(-12.0, min(12.0, self._sway_offset))

        # ── Sprint FOV smoothing ─────────────────────────────
        if self._dash_timer > 0.0:
            target_fov_boost = DASH_FOV_PUNCH
        elif self._sprinting:
            target_fov_boost = SPRINT_FOV_BOOST
        else:
            target_fov_boost = 0.0
        self._sprint_fov += (target_fov_boost - self._sprint_fov) * min(1.0, 6.0 * dt)

        # ── Dash timers ──────────────────────────────────────
        if self._dash_timer > 0.0:
            self._dash_timer = max(0.0, self._dash_timer - dt)
            if self._dash_timer <= 0.0:
                self._move_vx = self._dash_dir[0] * 1.5
                self._move_vy = self._dash_dir[1] * 1.5
        if self._dash_cooldown > 0.0:
            self._dash_cooldown = max(0.0, self._dash_cooldown - dt)

        # ── Damage flash detection ───────────────────────────
        hp_res = app.world.query_one(Player, Health)
        if hp_res:
            cur_hp = hp_res[2].current
            if self._last_hp >= 0 and cur_hp < self._last_hp:
                self._damage_flash = DAMAGE_FLASH_DUR
            self._last_hp = cur_hp
        if self._damage_flash > 0:
            self._damage_flash -= dt

        # ── Footstep decay ───────────────────────────────────
        if self._step_phase > 0:
            self._step_phase = max(0.0, self._step_phase - dt * 6.0)

        set_camera_angle(self.player_angle)

        clock = app.world.resources.try_get(GameClock)
        if clock:
            clock.time += dt

        _perf = time.perf_counter
        _plog = self._perflog
        _t0 = _perf()
        self.session.tick_world(dt)
        _dt_sim = _perf() - _t0
        self._prof_record('sim', _dt_sim)
        _plog.record_ms('dt_sim', _dt_sim)

        _t0 = _perf()
        movement_system(app.world, dt, self.session.tiles,
                        portal_tiles=self.session.portal_positions)
        app.world.events.flush()
        _dt_phys = _perf() - _t0
        self._prof_record('physics', _dt_phys)
        _plog.record_ms('dt_physics', _dt_phys)

        if self.session.check_portals(dt):
            pass

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
        _plog = self._perflog
        _plog.begin_frame()

        result = app.world.query_one(Player, Position)
        if not result:
            surface.fill((0, 0, 0))
            app.draw_text(surface, "No player entity", 10, 10, (255, 0, 0))
            return
        _, _, pos = result
        px, py = pos.x, pos.y

        wc = app.world.resources.try_get(WorldClock)
        dn = day_night_factor(wc)
        if self.session.first_person:
            dn = max(dn, 0.85)

        fog_rate, _ambient, fog_lut = compute_fog_params(dn)
        half = sh // 2 + int(self._bob_offset)
        sway = int(self._sway_offset)
        current_fov = FOV + self._sprint_fov

        tiles = self.session.tiles
        map_w = self.session.map_w
        map_h = self.session.map_h
        zone = self.session.zone_name
        renderer = self._renderer

        _perf = time.perf_counter

        _gc_was = gc.isenabled()
        gc.disable()
        try:
            self._draw_world(
                surface, app, sw, sh, px, py,
                half, sway, current_fov,
                tiles, map_w, map_h,
                zone, renderer, dn, fog_rate, fog_lut, wc,
                _perf,
            )
        finally:
            if _gc_was:
                gc.enable()

        # ── Damage flash ────────────────────────────────────
        if self._damage_flash > 0:
            flash_t = min(1.0, self._damage_flash / DAMAGE_FLASH_DUR)
            flash_alpha = int(90 * flash_t)
            flash_surf = getattr(self, '_dmg_flash_surf', None)
            if flash_surf is None or flash_surf.get_size() != (sw, sh):
                flash_surf = pygame.Surface((sw, sh), pygame.SRCALPHA)
                self._dmg_flash_surf = flash_surf
            flash_surf.fill((180, 0, 0, flash_alpha))
            surface.blit(flash_surf, (0, 0))

        # ── View sway shift ─────────────────────────────────
        if abs(sway) >= 1:
            s = int(sway)
            surface.scroll(s, 0)
            if s > 0:
                surface.fill((0, 0, 0), (0, 0, s, sh))
            else:
                surface.fill((0, 0, 0), (sw + s, 0, -s, sh))

        # ── HUD ──────────────────────────────────────────────
        _t0 = _perf()
        hud = self._hud
        hud.draw_hud(surface, app, sw, sh,
                     self.modals.is_open, self.session)
        hud.draw_notifications(surface, app)
        hud.draw_minimap(surface, app, px, py, sw, sh,
                         self.player_angle, self.session)
        hud.draw_compass(surface, sw, self.player_angle)
        self._prof_record('hud', _perf() - _t0)
        _plog.record_ms('dt_hud', _perf() - _t0)

        if self.show_debug:
            hud.draw_debug(surface, app, px, py,
                           self.player_angle,
                           self.session.zone_name)
            self._draw_profiler(surface, sw, sh, app)

        # ── Fade overlay ─────────────────────────────────────
        if self.session.fade_alpha > 0.01:
            a = int(min(255, self.session.fade_alpha * 255))
            if not hasattr(self, '_fade_surf') or self._fade_surf.get_size() != (sw, sh):
                self._fade_surf = pygame.Surface((sw, sh), pygame.SRCALPHA)
            self._fade_surf.fill((0, 0, 0, a))
            surface.blit(self._fade_surf, (0, 0))

        if self.modals.is_open:
            self.modals.draw(surface, app)

        # ── Perf log: end frame ──────────────────────────────
        _plog.record('fps', round(app.clock.get_fps(), 1) if hasattr(app, 'clock') else 0)
        _plog.end_frame()

    # ── Render world (GC-safe wrapper) ────────────────────────────

    def _draw_world(
        self,
        surface: pygame.Surface,
        app: App,
        sw: int, sh: int,
        px: float, py: float,
        half: int, sway: int, current_fov: float,
        tiles, map_w: int, map_h: int,
        zone: str, renderer, dn: float,
        fog_rate: int, fog_lut: list[int], wc,
        _perf,
    ) -> None:
        """Core rendering pipeline — called with GC disabled.

        Renders to a half-resolution internal surface (``_RSCALE``)
        and upscales to the display surface at the end.  This cuts
        per-pixel work ~75 % while keeping the HUD crisp.
        """
        _RS = _RSCALE
        rsw = sw // _RS
        rsh = sh // _RS
        rhalf = half // _RS
        rbob = self._bob_offset / _RS
        _plog = self._perflog

        rt = getattr(self, '_rtarget', None)
        if rt is None or rt.get_size() != (rsw, rsh):
            self._rtarget = pygame.Surface((rsw, rsh)).convert()
            rt = self._rtarget

        # ── Perf log: player state ───────────────────────────
        _plog.record('zone', zone)
        _plog.record('px', round(px, 3))
        _plog.record('py', round(py, 3))
        _plog.record('angle', round(self.player_angle, 4))
        _plog.record('fov', round(current_fov, 4))
        _plog.record('render_w', rsw)
        _plog.record('render_h', rsh)

        _t0 = _perf()
        renderer.draw_floor_ceiling(
            rt, rsw, rsh, rhalf, px, py, self.player_angle,
            fog_lut, dn, current_fov,
            tiles, map_w, map_h, self.session.first_person,
        )
        _dt_fc = _perf() - _t0
        self._prof_record('floor/ceil', _dt_fc)
        _plog.record_ms('dt_floor_ceil', _dt_fc)

        _t0 = _perf()
        slices, plat_col, zbuf_full, deferred_halves = renderer.draw_walls(
            rt, rsw, rsh, rhalf, px, py,
            self.player_angle, current_fov,
            tiles, fog_lut, dn,
            self.session.rotations,
        )
        _wall_total = _perf() - _t0
        self._prof_record('walls', _wall_total)
        self._prof_record(' ∟cast', renderer._cast_time)
        self._prof_record(' ∟blit', _wall_total - renderer._cast_time)
        _plog.record_ms('dt_walls', _wall_total)
        _plog.record_ms('dt_cast', renderer._cast_time)
        _plog.record_ms('dt_blit_walls', _wall_total - renderer._cast_time)

        _t0 = _perf()
        vp_data = renderer.draw_visplane_tops(
            rt, rsw, rsh, rhalf, px, py,
            self.player_angle, current_fov,
            plat_col, fog_lut, tiles, map_w, map_h,
            offscreen=True,
        )
        _dt_vp = _perf() - _t0
        self._prof_record('visplane', _dt_vp)
        _plog.record_ms('dt_visplane', _dt_vp)

        _t0 = _perf()
        renderer.draw_entities(
            rt, app, zbuf_full, deferred_halves, rsw, rsh, px, py,
            self.player_angle, current_fov,
            dn, fog_rate, fog_lut, rbob,
            zone, tiles, map_w, map_h,
            vp_data=vp_data,
        )
        _dt_ent = _perf() - _t0
        self._prof_record('entities', _dt_ent)
        _plog.record_ms('dt_entities', _dt_ent)

        # ── Wall-entity rendering (WallSprite components) ────
        _t0 = _perf()
        renderer.draw_wall_entities(
            rt, app, zbuf_full, rsw, rsh, px, py,
            self.player_angle, current_fov,
            dn, rbob, zone, tiles, map_w, map_h,
        )
        _dt_went = _perf() - _t0
        self._prof_record('wall_ents', _dt_went)
        _plog.record_ms('dt_wall_entities', _dt_went)

        _t0 = _perf()
        if not self.session.first_person:
            renderer.draw_day_night(rt, wc)
        _dt_tint = _perf() - _t0
        self._prof_record('tint', _dt_tint)
        _plog.record_ms('dt_tint', _dt_tint)

        # ── Upscale to display resolution ────────────────────
        _t0 = _perf()
        pygame.transform.scale(rt, (sw, sh), surface)
        _dt_up = _perf() - _t0
        self._prof_record('upscale', _dt_up)
        _plog.record_ms('dt_upscale', _dt_up)

        # ── Perf log: cache & entity stats ───────────────────
        _plog.record('strip_cache_size', len(renderer._strip_cache))
        _plog.record('strip_cache_prev_size', len(renderer._strip_cache_prev))
        _plog.record('col_cache_size', len(renderer._col_cache))
        _plog.record('ent_pool_size', len(renderer._ent_pool))
        _plog.record('bb_base_cache_size', len(renderer._bb_base_cache))
        _plog.record('glyph_cache_size', len(renderer._glyph_cache))
        _plog.record('n_slices', len(slices))
        _plog.record('n_deferred_halves', len(deferred_halves))
        _plog.record('n_entities_visible', getattr(renderer, '_last_n_ents', 0))
        _plog.record('n_entity_billboards', getattr(renderer, '_last_n_bbs', 0))
        from systems.raycaster import _USE_C_CAST
        _plog.record('c_extension_active', _USE_C_CAST)

    # ── Profiler helpers ──────────────────────────────────────────

    def _prof_record(self, name: str, elapsed: float) -> None:
        """Append *elapsed* seconds to the rolling history for *name*."""
        hist = self._prof_history
        if name not in hist:
            hist[name] = []
            self._prof_order.append(name)
        buf = hist[name]
        buf.append(elapsed)
        if len(buf) > self._PROF_LEN:
            del buf[: len(buf) - self._PROF_LEN]

    def _draw_profiler(
        self,
        surface: pygame.Surface,
        sw: int, sh: int,
        app,
    ) -> None:
        """Render a per-stage timing panel with bar chart."""
        hist = self._prof_history
        if not hist:
            return

        lines: list[tuple[str, float, float, float]] = []
        total_avg = 0.0
        for name in self._prof_order:
            buf = hist.get(name)
            if not buf:
                continue
            cur = buf[-1] * 1000.0
            avg = sum(buf) / len(buf) * 1000.0
            peak = max(buf) * 1000.0
            lines.append((name, cur, avg, peak))
            total_avg += avg

        if not lines:
            return

        row_h = 14
        bar_max_w = 100
        panel_w = 310
        panel_h = (len(lines) + 2) * row_h + 6
        px0 = sw - panel_w - 8
        py0 = 30

        bg = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        bg.fill((0, 0, 0, 160))
        surface.blit(bg, (px0, py0))

        font = app.font_sm
        y = py0 + 4

        app.draw_text(surface, "STAGE        cur   avg  peak",
                      px0 + 4, y, (160, 160, 160), font)
        y += row_h

        _BAR_COLORS = [
            (100, 200, 255), (100, 255, 150), (255, 200, 100),
            (255, 130, 130), (200, 150, 255), (150, 255, 255),
        ]

        max_ms = max(max(l[3] for l in lines), 0.01)

        for i, (name, cur, avg, peak) in enumerate(lines):
            col = _BAR_COLORS[i % len(_BAR_COLORS)]
            bar_w = int(peak / max_ms * bar_max_w)
            avg_w = int(avg / max_ms * bar_max_w)
            pygame.draw.rect(surface, (col[0] // 3, col[1] // 3, col[2] // 3),
                             (px0 + 4, y + 1, bar_w, row_h - 3))
            pygame.draw.rect(surface, col,
                             (px0 + 4, y + 1, avg_w, row_h - 3))
            label = f"{name:<12s} {cur:4.1f}  {avg:4.1f}  {peak:4.1f}"
            app.draw_text(surface, label,
                          px0 + 8, y, (255, 255, 255), font)
            y += row_h

        y += 2
        app.draw_text(surface, f"{'TOTAL':<12s}        {total_avg:4.1f}ms",
                      px0 + 8, y, (0, 255, 200), font)


# ── Angle ↔ Direction helpers ────────────────────────────────────

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
