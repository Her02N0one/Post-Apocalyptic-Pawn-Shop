"""scenes/exhibits/faction_exhibit.py — Faction Alert Cascade exhibit.

Villagers stand in a cluster. A raider approaches and attacks.
Watch alert propagation flip villager dispositions one by one.
"""

from __future__ import annotations
import pygame
from core.app import App
from core.constants import TILE_SIZE
from core.events import EventBus
from components import (
    Position, Velocity, Sprite, Identity, Collider, Hurtbox,
    Facing, Health, Lod, Brain,
)
from components.ai import Patrol, Threat, AttackConfig
from components.combat import Combat
from components.social import Faction
from logic.systems import movement_system
from logic.brains import run_brains
from logic.projectiles import projectile_system
from logic.combat import handle_death, npc_melee_attack, npc_ranged_attack
from scenes.exhibits.base import Exhibit
from scenes.exhibits.helpers import draw_circle_alpha, spawn_combat_npc


class FactionExhibit(Exhibit):
    """Tab 4 — Faction alert cascade demo."""

    name = "Faction"

    def __init__(self):
        self.running = False
        self._alert_log: list[str] = []

    def setup(self, app: App, zone: str, tiles: list[list[int]]) -> list[int]:
        self.running = False
        self._alert_log.clear()
        self._zone = zone

        # Fresh EventBus
        app.world.set_res(EventBus())
        bus = app.world.res(EventBus)
        _wr = app.world

        def _on_die(ev):
            handle_death(_wr, ev.eid)

        def _on_atk(ev):
            if ev.attack_type == "ranged":
                npc_ranged_attack(_wr, ev.attacker_eid, ev.target_eid)
            else:
                npc_melee_attack(_wr, ev.attacker_eid, ev.target_eid)

        bus.subscribe("EntityDied", _on_die)
        bus.subscribe("AttackIntent", _on_atk)

        eids: list[int] = []

        # Villager cluster
        villager_positions = [
            ("Villager A", 15.0, 8.0),
            ("Villager B", 17.0, 9.0),
            ("Villager C", 14.0, 11.0),
            ("Villager D", 16.0, 12.0),
            ("Villager E", 18.0, 10.0),
            ("Guard",      13.0, 10.0),
        ]
        w = app.world
        for name, x, y in villager_positions:
            eid = w.spawn()
            is_guard = "Guard" in name
            bkind = "guard" if is_guard else "wander"
            color = (255, 200, 50) if is_guard else (100, 220, 100)
            w.add(eid, Position(x=x, y=y, zone=zone))
            w.add(eid, Velocity())
            w.add(eid, Sprite(char=name[0], color=color))
            w.add(eid, Identity(name=name, kind="npc"))
            w.add(eid, Collider())
            w.add(eid, Hurtbox())
            w.add(eid, Facing())
            w.add(eid, Health(current=80, maximum=80))
            w.add(eid, Combat(damage=8 if not is_guard else 15, defense=5))
            w.add(eid, Lod(level="high"))
            w.add(eid, Brain(kind=bkind, active=True))
            w.add(eid, Patrol(origin_x=x, origin_y=y, radius=3.0, speed=1.5))
            w.add(eid, Faction(group="villagers", disposition="neutral",
                               home_disposition="neutral",
                               alert_radius=6.0))
            if is_guard:
                w.add(eid, Threat(aggro_radius=10.0, leash_radius=18.0,
                                  flee_threshold=0.0))
                w.add(eid, AttackConfig(attack_type="melee", range=1.2,
                                        cooldown=0.5))
            w.zone_add(eid, zone)
            eids.append(eid)

        # Hostile raider
        eid = spawn_combat_npc(
            app, zone, "Raider", "hostile_melee", 3.0, 10.0, (255, 60, 60),
            "raiders", hp=120, defense=10, damage=12,
            aggro=20.0, atk_range=1.2, cooldown=0.6,
            flee_threshold=0.1, speed=2.5,
            fov_degrees=120.0, view_distance=20.0, peripheral_range=5.0,
            initial_facing="right")
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
        self._update_alert_log(app, eids)

    def _update_alert_log(self, app: App, eids: list[int]):
        for eid in eids:
            if not app.world.alive(eid):
                continue
            fac = app.world.get(eid, Faction)
            ident = app.world.get(eid, Identity)
            if fac and ident and fac.group == "villagers":
                tag = f"{ident.name}_hostile"
                if fac.disposition == "hostile" and tag not in self._alert_log:
                    self._alert_log.append(tag)

    def draw(self, surface: pygame.Surface, ox: int, oy: int,
             app: App, eids: list[int]):
        for eid in eids:
            if not app.world.alive(eid):
                continue
            pos = app.world.get(eid, Position)
            fac = app.world.get(eid, Faction)
            if not pos or not fac:
                continue
            cx = ox + int(pos.x * TILE_SIZE) + TILE_SIZE // 2
            cy = oy + int(pos.y * TILE_SIZE) + TILE_SIZE // 2

            if fac.disposition == "hostile":
                ring_color = (255, 60, 60)
            elif fac.disposition == "neutral":
                ring_color = (200, 200, 100)
            else:
                ring_color = (100, 255, 100)
            pygame.draw.circle(surface, ring_color, (cx, cy),
                               TILE_SIZE // 2 + 2, 2)

            if fac.group == "villagers":
                ar = int(fac.alert_radius * TILE_SIZE)
                draw_circle_alpha(surface, (*ring_color, 15), cx, cy, ar)
                pygame.draw.circle(surface, ring_color, (cx, cy), ar, 1)

        # Alert cascade log
        if self._alert_log:
            sy = 60
            app.draw_text(surface, "Alert Cascade:", 700, sy,
                          (255, 200, 50), app.font_sm)
            for i, entry in enumerate(self._alert_log):
                name = entry.replace("_hostile", "")
                app.draw_text(surface, f"  ! {name} \u2192 hostile",
                              700, sy + 14 + i * 14,
                              (255, 80, 80), app.font_sm)

    def info_text(self, app: App, eids: list[int]) -> str:
        status = "RUNNING" if self.running else "READY"
        alerts = len(self._alert_log)
        alive = sum(1 for e in eids if app.world.alive(e))
        action = "pause" if self.running else "start"
        return (f"Faction Alert: {status}  Alerts:{alerts}  "
                f"Alive:{alive}  [Space] {action}")
