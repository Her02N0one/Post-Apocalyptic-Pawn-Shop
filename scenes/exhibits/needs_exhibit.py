"""scenes/exhibits/needs_exhibit.py — Needs / Hunger exhibit.

NPCs with hunger that drains at accelerated speed.
They carry food and eat when hungry.
"""

from __future__ import annotations
import pygame
from core.app import App
from core.constants import TILE_SIZE
from components import (
    Position, Velocity, Sprite, Identity, Collider, Facing,
    Health, Hunger, Lod, Brain, Needs, Inventory,
)
from components.ai import Patrol
from logic.systems import movement_system
from logic.brains import run_brains
from scenes.exhibits.base import Exhibit


class NeedsExhibit(Exhibit):
    """Tab 7 — Needs / Hunger demo."""

    name = "Needs"

    def __init__(self):
        self.running = False
        self._time_scale = 10.0

    def setup(self, app: App, zone: str, tiles: list[list[int]]) -> list[int]:
        self.running = False
        eids: list[int] = []

        npc_data = [
            ("Well-Fed Farmer",  8.0,  6.0,  (100, 200, 80),  80.0),
            ("Hungry Scavenger", 15.0, 6.0,  (200, 180, 80),  30.0),
            ("Starving Nomad",   22.0, 6.0,  (200, 100, 80),  10.0),
            ("Village Cook",     8.0,  14.0, (120, 200, 120), 60.0),
            ("Trader",           15.0, 14.0, (180, 160, 220), 50.0),
        ]

        w = app.world
        for name, x, y, color, start_hunger in npc_data:
            eid = w.spawn()
            w.add(eid, Position(x=x, y=y, zone=zone))
            w.add(eid, Velocity())
            w.add(eid, Sprite(char=name[0], color=color))
            w.add(eid, Identity(name=name, kind="npc"))
            w.add(eid, Collider())
            w.add(eid, Facing())
            w.add(eid, Health(current=100, maximum=100))
            w.add(eid, Lod(level="high"))
            w.add(eid, Brain(kind="wander", active=True))
            w.add(eid, Patrol(origin_x=x, origin_y=y, radius=3.0, speed=1.5))
            w.add(eid, Hunger(current=start_hunger, maximum=100.0,
                              rate=0.5, starve_dps=2.0))
            w.add(eid, Needs())
            inv = Inventory()
            inv.items = {"ration": 3, "stew": 1}
            w.add(eid, inv)
            w.zone_add(eid, zone)
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
        from logic.needs_system import hunger_system
        hunger_system(app.world, dt * self._time_scale)
        run_brains(app.world, dt)
        movement_system(app.world, dt, tiles)

    def draw(self, surface: pygame.Surface, ox: int, oy: int,
             app: App, eids: list[int]):
        for eid in eids:
            if not app.world.alive(eid):
                continue
            pos = app.world.get(eid, Position)
            hunger = app.world.get(eid, Hunger)
            needs = app.world.get(eid, Needs)
            if not pos or not hunger:
                continue

            sx = ox + int(pos.x * TILE_SIZE)
            sy = oy + int(pos.y * TILE_SIZE)

            # Hunger bar
            bar_w = TILE_SIZE - 4
            bar_x = sx + 2
            bar_y = sy + TILE_SIZE + 2
            ratio = max(0.0, hunger.current / max(hunger.maximum, 1.0))
            pygame.draw.rect(surface, (40, 40, 40), (bar_x, bar_y, bar_w, 4))
            if ratio > 0.5:
                bc = (80, 200, 80)
            elif ratio > 0.25:
                bc = (220, 180, 50)
            else:
                bc = (220, 80, 50)
            pygame.draw.rect(surface, bc,
                             (bar_x, bar_y, max(1, int(bar_w * ratio)), 4))

            # Label
            pct = int(ratio * 100)
            label = f"{pct}%"
            if needs and needs.priority == "eat":
                label += " HUNGRY"
            app.draw_text(surface, label, sx - 4, sy + TILE_SIZE + 8,
                          color=bc, font=app.font_sm)

            # Inventory
            inv = app.world.get(eid, Inventory)
            if inv:
                total_food = sum(inv.items.values())
                app.draw_text(surface, f"Food:{total_food}",
                              sx - 4, sy + TILE_SIZE + 20,
                              color=(180, 180, 180), font=app.font_sm)

    def info_text(self, app: App, eids: list[int]) -> str:
        status = "RUNNING" if self.running else "READY"
        action = "pause" if self.running else "start"
        return (f"Needs: {status}  Speed: {self._time_scale:.0f}x  "
                f"[Space] {action}")
