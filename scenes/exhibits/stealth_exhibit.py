"""scenes/exhibits/stealth_exhibit.py — Stealth / Vision Cone exhibit.

A guard patrols with a visible cone. An intruder wanders nearby.
Watch for detection.
"""

from __future__ import annotations
import math
import pygame
from core.app import App
from core.constants import TILE_SIZE
from components import (
    Position, Velocity, Sprite, Identity, Collider, Hurtbox,
    Facing, Health, Lod, Brain,
)
from components.ai import HomeRange, Threat, AttackConfig, VisionCone
from components.combat import CombatStats
from components.social import Faction
from logic.movement import movement_system
from logic.ai.brains import tick_ai
from scenes.exhibits.base import Exhibit
from scenes.exhibits.drawing import draw_cone_alpha


class StealthExhibit(Exhibit):
    """Tab 5 — Stealth / vision cone demo."""

    name = "Stealth"

    def __init__(self):
        self.running = False
        self.detected = False
        self.timer = 0.0
        self._guard_eid: int | None = None
        self._intruder_eid: int | None = None

    def setup(self, app: App, zone: str, tiles: list[list[int]]) -> list[int]:
        self.running = False
        self.detected = False
        self.timer = 0.0
        eids: list[int] = []
        w = app.world

        # Guard
        eid = w.spawn()
        w.add(eid, Position(x=15.0, y=10.0, zone=zone))
        w.add(eid, Velocity())
        w.add(eid, Sprite(char="G", color=(255, 200, 50)))
        w.add(eid, Identity(name="Guard", kind="npc"))
        w.add(eid, Collider())
        w.add(eid, Hurtbox())
        w.add(eid, Facing(direction="right"))
        w.add(eid, Health(current=100, maximum=100))
        w.add(eid, CombatStats(damage=10, defense=5))
        w.add(eid, Lod(level="high"))
        w.add(eid, Brain(kind="wander", active=True))
        w.add(eid, HomeRange(origin_x=15.0, origin_y=10.0, radius=8.0, speed=1.8))
        w.add(eid, Faction(group="guards", disposition="neutral",
                           home_disposition="neutral"))
        w.add(eid, Threat(aggro_radius=12.0, leash_radius=20.0,
                          flee_threshold=0.0))
        w.add(eid, AttackConfig(attack_type="melee", range=1.2, cooldown=0.5))
        w.add(eid, VisionCone(fov_degrees=90.0, view_distance=10.0,
                              peripheral_range=2.5))
        w.zone_add(eid, zone)
        eids.append(eid)
        self._guard_eid = eid

        # Intruder
        eid2 = w.spawn()
        w.add(eid2, Position(x=25.0, y=15.0, zone=zone))
        w.add(eid2, Velocity())
        w.add(eid2, Sprite(char="I", color=(255, 80, 80)))
        w.add(eid2, Identity(name="Intruder", kind="npc"))
        w.add(eid2, Collider())
        w.add(eid2, Hurtbox())
        w.add(eid2, Facing())
        w.add(eid2, Health(current=60, maximum=60))
        w.add(eid2, CombatStats(damage=5, defense=2))
        w.add(eid2, Lod(level="high"))
        w.add(eid2, Brain(kind="wander", active=True))
        w.add(eid2, HomeRange(origin_x=20.0, origin_y=12.0, radius=7.0, speed=1.2))
        w.add(eid2, Faction(group="intruders", disposition="neutral",
                           home_disposition="neutral"))
        w.zone_add(eid2, zone)
        eids.append(eid2)
        self._intruder_eid = eid2

        return eids

    def on_space(self, app: App) -> str | None:
        self.running = not self.running
        self.detected = False
        self.timer = 0.0
        if not self.running:
            return "reset"
        return None

    def update(self, app: App, dt: float, tiles: list[list[int]],
               eids: list[int]):
        if not self.running:
            return
        self.timer += dt
        tick_ai(app.world, dt)
        movement_system(app.world, dt, tiles)
        self._check_detection(app)

    def _check_detection(self, app: App):
        if self.detected:
            return
        w = app.world
        gid, iid = self._guard_eid, self._intruder_eid
        if gid is None or iid is None:
            return
        if not w.alive(gid) or not w.alive(iid):
            return
        gpos = w.get(gid, Position)
        ipos = w.get(iid, Position)
        gface = w.get(gid, Facing)
        cone = w.get(gid, VisionCone)
        if not gpos or not ipos or not gface or not cone:
            return
        from logic.ai.perception import in_vision_cone
        if in_vision_cone(gpos, gface.direction, ipos, cone):
            self.detected = True
            gfac = w.get(gid, Faction)
            if gfac:
                gfac.disposition = "hostile"
            ifac = w.get(iid, Faction)
            if ifac:
                ifac.disposition = "hostile"
            gbrain = w.get(gid, Brain)
            if gbrain:
                gbrain.kind = "hostile_melee"
                c = gbrain.state.setdefault("combat", {})
                c["mode"] = "chase"
                c["p_eid"] = iid
                c["p_pos"] = (ipos.x, ipos.y)

    # ── Drawing ──────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, ox: int, oy: int,
             app: App, eids: list[int]):
        gid = self._guard_eid
        if gid and app.world.alive(gid):
            pos = app.world.get(gid, Position)
            facing = app.world.get(gid, Facing)
            cone = app.world.get(gid, VisionCone)
            vel = app.world.get(gid, Velocity)
            if pos and facing and cone:
                cx = ox + int(pos.x * TILE_SIZE) + TILE_SIZE // 2
                cy = oy + int(pos.y * TILE_SIZE) + TILE_SIZE // 2

                if vel and (abs(vel.x) > 0.01 or abs(vel.y) > 0.01):
                    face_angle = math.atan2(vel.y, vel.x)
                else:
                    from logic.ai.perception import facing_to_angle
                    face_angle = facing_to_angle(facing.direction)

                half_fov = math.radians(cone.fov_degrees / 2.0)
                view_px = int(cone.view_distance * TILE_SIZE)

                cone_color = (255, 60, 60, 30) if self.detected else (255, 200, 50, 30)
                draw_cone_alpha(surface, cone_color, cx, cy, view_px,
                                face_angle, half_fov)

                line_color = (255, 60, 60) if self.detected else (255, 200, 50)
                for sign in (-1, 1):
                    a = face_angle + sign * half_fov
                    ex = cx + int(math.cos(a) * view_px)
                    ey = cy + int(math.sin(a) * view_px)
                    pygame.draw.line(surface, line_color, (cx, cy), (ex, ey), 1)

                periph_px = int(cone.peripheral_range * TILE_SIZE)
                pygame.draw.circle(surface, line_color, (cx, cy), periph_px, 1)

        # Detection banner
        if self.detected:
            sw = surface.get_width()
            app.draw_text(surface, "!! DETECTED !!", sw // 2 - 50, 40,
                          (255, 60, 60), app.font_lg)
            app.draw_text(surface, f"Time: {self.timer:.1f}s",
                          sw // 2 - 30, 60, (255, 200, 50), app.font_sm)

    def info_text(self, app: App, eids: list[int]) -> str:
        status = ("DETECTED!" if self.detected
                  else "PATROLLING" if self.running else "READY")
        action = "reset" if self.running else "start"
        return (f"Stealth: {status}  Time: {self.timer:.1f}s  "
                f"[Space] {action}")
