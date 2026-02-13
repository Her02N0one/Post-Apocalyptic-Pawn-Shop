"""scenes/exhibits/combat_exhibit.py — Combat exhibit.

Two factions fight in an arena with cover blocks.
"""

from __future__ import annotations
import math
import pygame
from core.app import App
from core.constants import TILE_SIZE, TILE_WALL
from core.events import EventBus
from core.zone import ZONE_MAPS
from components import Position, Velocity, Facing, Health, Brain, Lod
from components.ai import VisionCone
from components.combat import Combat, Projectile
from components.social import Faction
from logic.systems import movement_system
from logic.brains import run_brains
from logic.projectiles import projectile_system
from logic.combat import handle_death, npc_melee_attack, npc_ranged_attack
from scenes.exhibits.base import Exhibit
from scenes.exhibits.helpers import spawn_combat_npc

_ARENA_W = 30
_ARENA_H = 20


class CombatExhibit(Exhibit):
    """Tab 1 — Combat demo."""

    name = "Combat"

    def __init__(self):
        self.running = False

    def setup(self, app: App, zone: str, tiles: list[list[int]]) -> list[int]:
        self.running = False
        self._zone = zone

        # Fresh EventBus
        app.world.set_res(EventBus())
        bus = app.world.res(EventBus)
        _wr = app.world

        def _on_entity_died(ev):
            handle_death(_wr, ev.eid)

        def _on_attack_intent(ev):
            if ev.attack_type == "ranged":
                npc_ranged_attack(_wr, ev.attacker_eid, ev.target_eid)
            else:
                npc_melee_attack(_wr, ev.attacker_eid, ev.target_eid)

        bus.subscribe("EntityDied", _on_entity_died)
        bus.subscribe("AttackIntent", _on_attack_intent)

        # Cover blocks
        cover_positions = [
            (6, 14), (6, 15),
            (9, 12), (9, 13), (9, 16), (9, 17),
            (13, 14), (13, 15),
        ]
        for r, c in cover_positions:
            if 0 < r < _ARENA_H - 1 and 0 < c < _ARENA_W - 1:
                tiles[r][c] = TILE_WALL
        ZONE_MAPS[zone] = tiles

        eids: list[int] = []

        # Blue team
        for name, x, y, hp, defense in [
            ("Blue Tank",    4.0,  5.0, 150, 40),
            ("Blue Fighter", 4.0, 14.0, 100, 20),
        ]:
            eid = spawn_combat_npc(
                app, zone, name, "hostile_melee", x, y, (80, 140, 255),
                "blue_team", hp=hp, defense=defense,
                damage=15, aggro=24.0, atk_range=1.2, cooldown=0.6,
                flee_threshold=0.15, speed=2.5,
                fov_degrees=120.0, view_distance=22.0, peripheral_range=5.0,
                initial_facing="right")
            eids.append(eid)

        eid = spawn_combat_npc(
            app, zone, "Blue Sniper", "hostile_ranged", 3.0, 10.0,
            (100, 160, 255), "blue_team", hp=70, defense=5,
            damage=20, aggro=28.0, atk_range=10.0, cooldown=0.8,
            attack_type="ranged", flee_threshold=0.3, speed=2.0,
            accuracy=0.95, proj_speed=18.0,
            fov_degrees=90.0, view_distance=26.0, peripheral_range=5.0,
            initial_facing="right")
        eids.append(eid)

        # Red team
        for name, x, y, hp, defense in [
            ("Red Brute",   25.0,  5.0, 130, 30),
            ("Red Brawler", 25.0, 14.0, 100, 25),
        ]:
            eid = spawn_combat_npc(
                app, zone, name, "hostile_melee", x, y, (255, 80, 80),
                "red_team", hp=hp, defense=defense,
                damage=18, aggro=24.0, atk_range=1.2, cooldown=0.5,
                flee_threshold=0.15, speed=2.8,
                fov_degrees=120.0, view_distance=22.0, peripheral_range=5.0,
                initial_facing="left")
            eids.append(eid)

        eid = spawn_combat_npc(
            app, zone, "Red Archer", "hostile_ranged", 26.0, 10.0,
            (255, 120, 100), "red_team", hp=60, defense=5,
            damage=15, aggro=28.0, atk_range=9.0, cooldown=0.7,
            attack_type="ranged", flee_threshold=0.35, speed=2.2,
            accuracy=0.88, proj_speed=14.0,
            fov_degrees=90.0, view_distance=26.0, peripheral_range=5.0,
            initial_facing="left")
        eids.append(eid)

        return eids

    def on_space(self, app: App) -> str | None:
        self.running = not self.running
        if not self.running:
            return "reset"
        return None

    def update(self, app: App, dt: float, tiles: list[list[int]],
               eids: list[int]):
        if not self.running:
            return
        run_brains(app.world, dt)
        movement_system(app.world, dt, tiles)
        projectile_system(app.world, dt, tiles)
        bus = app.world.res(EventBus)
        if bus:
            bus.drain()

    # ── Drawing ──────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, ox: int, oy: int,
             app: App, eids: list[int]):
        self._draw_vision_cones(surface, ox, oy, app, eids)
        self._draw_projectiles(surface, ox, oy, app)

    def _draw_projectiles(self, surface: pygame.Surface, ox: int, oy: int,
                          app: App):
        for _p_eid, p_pos, proj in app.world.query(Position, Projectile):
            if p_pos.zone != self._zone:
                continue
            px = ox + int(p_pos.x * TILE_SIZE)
            py = oy + int(p_pos.y * TILE_SIZE)
            app.draw_text(surface, proj.char, px - 2, py - 4,
                          color=proj.color, font=app.font_lg)

    def _draw_vision_cones(self, surface: pygame.Surface, ox: int, oy: int,
                           app: App, eids: list[int]):
        for eid in eids:
            if not app.world.alive(eid):
                continue
            pos = app.world.get(eid, Position)
            facing = app.world.get(eid, Facing)
            cone = app.world.get(eid, VisionCone)
            if not pos or not facing or not cone:
                continue

            cx = ox + int(pos.x * TILE_SIZE) + TILE_SIZE // 2
            cy = oy + int(pos.y * TILE_SIZE) + TILE_SIZE // 2

            fac = app.world.get(eid, Faction)
            if fac and fac.group == "blue_team":
                line_color = (80, 140, 255)
            elif fac and fac.group == "red_team":
                line_color = (255, 80, 80)
            else:
                line_color = (180, 180, 180)

            brain = app.world.get(eid, Brain)
            cs = brain.state.get("combat", {}) if brain else {}
            tp = cs.get("p_pos")
            mode = cs.get("mode", "idle")

            if mode in ("chase", "attack") and tp:
                face_angle = math.atan2(tp[1] - pos.y, tp[0] - pos.x)
            else:
                vel = app.world.get(eid, Velocity)
                if vel and (abs(vel.x) > 0.01 or abs(vel.y) > 0.01):
                    face_angle = math.atan2(vel.y, vel.x)
                else:
                    from logic.brains._helpers import facing_to_angle
                    face_angle = facing_to_angle(facing.direction)

            half_fov = math.radians(cone.fov_degrees / 2.0)
            ind_len = TILE_SIZE + 6

            # FOV edge lines
            for sign in (-1, 1):
                a = face_angle + sign * half_fov
                ex = cx + int(math.cos(a) * ind_len)
                ey = cy + int(math.sin(a) * ind_len)
                pygame.draw.line(surface, line_color, (cx, cy), (ex, ey), 1)

            # Arc
            arc_pts = []
            for i in range(13):
                a = face_angle - half_fov + (2 * half_fov) * i / 12
                arc_pts.append((cx + int(math.cos(a) * ind_len),
                                cy + int(math.sin(a) * ind_len)))
            if len(arc_pts) > 1:
                pygame.draw.lines(surface, line_color, False, arc_pts, 1)

            # Centre facing line
            tip_len = ind_len + 4
            tx = cx + int(math.cos(face_angle) * tip_len)
            ty = cy + int(math.sin(face_angle) * tip_len)
            pygame.draw.line(surface, (255, 255, 255), (cx, cy), (tx, ty), 2)

            # Peripheral ring
            periph_px = int(cone.peripheral_range * TILE_SIZE)
            if periph_px > 2:
                pygame.draw.circle(surface, line_color, (cx, cy), periph_px, 1)

            # LOS line to target
            if brain:
                cs2 = brain.state.get("combat", {})
                tp2 = cs2.get("p_pos")
                if tp2 and cs2.get("mode") in ("chase", "attack"):
                    tpx = ox + int(tp2[0] * TILE_SIZE) + TILE_SIZE // 2
                    tpy = oy + int(tp2[1] * TILE_SIZE) + TILE_SIZE // 2
                    blocked = cs2.get("_los_blocked", False)
                    los_color = (255, 60, 60) if blocked else (60, 255, 60)
                    pygame.draw.line(surface, los_color, (cx, cy), (tpx, tpy), 1)
                    pygame.draw.circle(surface, los_color, (tpx, tpy), 3)

    def info_text(self, app: App, eids: list[int]) -> str:
        status = "FIGHTING" if self.running else "READY"
        alive = sum(1 for e in eids if app.world.alive(e))
        blue = sum(1 for e in eids
                   if app.world.alive(e) and app.world.has(e, Faction)
                   and app.world.get(e, Faction).group == "blue_team")
        red = sum(1 for e in eids
                  if app.world.alive(e) and app.world.has(e, Faction)
                  and app.world.get(e, Faction).group == "red_team")
        action = "pause" if self.running else "start"
        return (f"Combat: {status}  Blue:{blue} vs Red:{red}  "
                f"Alive:{alive}/{len(eids)}  [Space] {action}")
