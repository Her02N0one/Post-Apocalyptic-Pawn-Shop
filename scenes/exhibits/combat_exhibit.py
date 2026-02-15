"""scenes/exhibits/combat_exhibit.py — CombatStats exhibit.

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
from components.combat import CombatStats, Projectile
from components.social import Faction
from logic.movement import movement_system
from logic.ai.brains import tick_ai
from logic.combat.projectiles import projectile_system
from logic.combat import handle_death, npc_melee_attack, npc_ranged_attack
from scenes.exhibits.base import Exhibit
from scenes.exhibits.drawing import spawn_combat_npc


class CombatExhibit(Exhibit):
    """Tab 1 — CombatStats demo."""

    name = "Combat"
    category = "Combat"
    description = (
        "Team Combat Arena\n"
        "\n"
        "Two factions (Blue vs Red, 5 per side) battle across\n"
        "an 80 × 50 m arena with scattered cover blocks.\n"
        "All units have realistic 5 km vision — in this open\n"
        "arena everyone sees everyone instantly.  Ranged units\n"
        "open fire immediately while melee close the ~50 m gap.\n"
        "\n"
        "What to observe:\n"
        " - Ranged units detect and fire before melee engages\n"
        " - Melee units advance through cover toward the enemy\n"
        " - Staggered speeds create a natural battle front\n"
        " - NPCs flee when HP drops below their flee threshold\n"
        " - Vision cones (F5) and LOS lines show targeting\n"
        "\n"
        "Systems:  tick_ai  movement  projectiles  VisionCone\n"
        "          CombatStats  Threat  AttackConfig  EventBus\n"
        "Controls: [Space] start / pause / reset"
    )
    arena_w = 80
    arena_h = 50
    default_debug = {"brain": True, "vision": True}

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

        # Cover blocks — scattered across the battlefield
        cover_positions = [
            # Left approach (cols 22-30)
            (15, 24), (16, 24),
            (24, 27), (25, 27), (26, 27),
            (34, 24), (35, 24),
            # Mid-left (cols 32-38)
            (10, 35), (11, 35),
            (20, 33), (20, 34), (21, 33), (21, 34),
            (30, 33), (30, 34), (31, 33), (31, 34),
            (40, 35), (41, 35),
            # Mid-right (cols 42-48)
            (10, 45), (11, 45),
            (20, 46), (20, 47), (21, 46), (21, 47),
            (30, 46), (30, 47), (31, 46), (31, 47),
            (40, 45), (41, 45),
            # Right approach (cols 52-58)
            (15, 55), (16, 55),
            (24, 53), (25, 53), (26, 53),
            (34, 55), (35, 55),
        ]
        for r, c in cover_positions:
            if 0 < r < len(tiles) - 1 and 0 < c < len(tiles[0]) - 1:
                tiles[r][c] = TILE_WALL
        ZONE_MAPS[zone] = tiles

        eids: list[int] = []

        # ── Blue team (left side) ────────────────────────────────────
        for name, x, y, hp, defense, speed in [
            ("Blue Vanguard",  15.0, 12.0, 120, 20, 3.2),
            ("Blue Tank",      12.0, 25.0, 180, 40, 2.5),
            ("Blue Skirmisher", 15.0, 38.0, 100, 15, 3.0),
        ]:
            eid = spawn_combat_npc(
                app, zone, name, "hostile_melee", x, y, (80, 140, 255),
                "blue_team", hp=hp, defense=defense,
                damage=15, aggro=5000.0, atk_range=1.2, cooldown=0.6,
                flee_threshold=0.15, speed=speed,
                fov_degrees=120.0, view_distance=5000.0, peripheral_range=10.0,
                initial_facing="right")
            eids.append(eid)

        for name, x, y, hp, defense, speed, acc, pspd in [
            ("Blue Sniper", 8.0, 18.0, 70, 5, 2.0, 0.90, 18.0),
            ("Blue Gunner", 8.0, 32.0, 80, 8, 2.2, 0.80, 16.0),
        ]:
            eid = spawn_combat_npc(
                app, zone, name, "hostile_ranged", x, y,
                (100, 160, 255), "blue_team", hp=hp, defense=defense,
                damage=20, aggro=5000.0, atk_range=12.0, cooldown=0.8,
                attack_type="ranged", flee_threshold=0.3, speed=speed,
                accuracy=acc, proj_speed=pspd,
                fov_degrees=90.0, view_distance=5000.0, peripheral_range=10.0,
                initial_facing="right")
            eids.append(eid)

        # ── Red team (right side) ────────────────────────────────────
        for name, x, y, hp, defense, speed in [
            ("Red Berserker", 65.0, 12.0, 110, 15, 3.3),
            ("Red Brute",     68.0, 25.0, 160, 35, 2.6),
            ("Red Brawler",   65.0, 38.0, 100, 20, 3.0),
        ]:
            eid = spawn_combat_npc(
                app, zone, name, "hostile_melee", x, y, (255, 80, 80),
                "red_team", hp=hp, defense=defense,
                damage=18, aggro=5000.0, atk_range=1.2, cooldown=0.5,
                flee_threshold=0.15, speed=speed,
                fov_degrees=120.0, view_distance=5000.0, peripheral_range=10.0,
                initial_facing="left")
            eids.append(eid)

        for name, x, y, hp, defense, speed, acc, pspd in [
            ("Red Archer",   72.0, 18.0, 60, 5, 2.2, 0.85, 14.0),
            ("Red Marksman", 72.0, 32.0, 75, 8, 2.0, 0.88, 16.0),
        ]:
            eid = spawn_combat_npc(
                app, zone, name, "hostile_ranged", x, y,
                (255, 120, 100), "red_team", hp=hp, defense=defense,
                damage=15, aggro=5000.0, atk_range=11.0, cooldown=0.7,
                attack_type="ranged", flee_threshold=0.35, speed=speed,
                accuracy=acc, proj_speed=pspd,
                fov_degrees=90.0, view_distance=5000.0, peripheral_range=10.0,
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
        tick_ai(app.world, dt)
        movement_system(app.world, dt, tiles)
        projectile_system(app.world, dt, tiles)
        bus = app.world.res(EventBus)
        if bus:
            bus.drain()

    # ── Drawing ──────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, ox: int, oy: int,
             app: App, eids: list[int],
             tile_px: int = TILE_SIZE, flags=None):
        if not flags or flags.vision:
            self._draw_vision_cones(surface, ox, oy, app, eids, tile_px)
        self._draw_projectiles(surface, ox, oy, app, tile_px)

    def _draw_projectiles(self, surface: pygame.Surface, ox: int, oy: int,
                          app: App, tile_px: int = TILE_SIZE):
        for _p_eid, p_pos, proj in app.world.query(Position, Projectile):
            if p_pos.zone != self._zone:
                continue
            px = ox + int(p_pos.x * tile_px)
            py = oy + int(p_pos.y * tile_px)
            app.draw_text(surface, proj.char, px - 2, py - 4,
                          color=proj.color, font=app.font_lg)

    def _draw_vision_cones(self, surface: pygame.Surface, ox: int, oy: int,
                           app: App, eids: list[int],
                           tile_px: int = TILE_SIZE):
        for eid in eids:
            if not app.world.alive(eid):
                continue
            pos = app.world.get(eid, Position)
            facing = app.world.get(eid, Facing)
            cone = app.world.get(eid, VisionCone)
            if not pos or not facing or not cone:
                continue

            cx = ox + int(pos.x * tile_px) + tile_px // 2
            cy = oy + int(pos.y * tile_px) + tile_px // 2

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
                    from logic.ai.perception import facing_to_angle
                    face_angle = facing_to_angle(facing.direction)

            half_fov = math.radians(cone.fov_degrees / 2.0)
            ind_len = tile_px + 6

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

            # Peripheral ring (10 m = 320 px — fine as an outline)
            periph_px = min(int(cone.peripheral_range * tile_px), 500)
            if periph_px > 2:
                pygame.draw.circle(surface, line_color, (cx, cy), periph_px, 1)

            # LOS line to target
            if brain:
                cs2 = brain.state.get("combat", {})
                tp2 = cs2.get("p_pos")
                if tp2 and cs2.get("mode") in ("chase", "attack"):
                    tpx = ox + int(tp2[0] * tile_px) + tile_px // 2
                    tpy = oy + int(tp2[1] * tile_px) + tile_px // 2
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
