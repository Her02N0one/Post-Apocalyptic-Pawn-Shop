"""scenes/exhibits/ai_exhibit.py — AI Brains exhibit.

Spawns NPCs with different brain types so you can watch them act.
"""

from __future__ import annotations
from core.app import App
from logic.systems import movement_system
from logic.brains import run_brains
from scenes.exhibits.base import Exhibit
from scenes.exhibits.helpers import spawn_npc


class AIExhibit(Exhibit):
    """Tab 0 — AI Brains demo."""

    name = "AI Brains"

    def setup(self, app: App, zone: str, tiles: list[list[int]]) -> list[int]:
        eids: list[int] = []
        brain_types = [
            ("Wanderer",      "wander",        (150, 200, 255), 4, 4),
            ("Villager",      "villager",       (100, 255, 100), 8, 4),
            ("Guard",         "guard",          (255, 200, 50),  14, 4),
            ("Hostile Melee", "hostile_melee",  (255, 80, 80),   20, 4),
            ("Hostile Range", "hostile_ranged", (255, 120, 120), 26, 4),
        ]
        for name, bkind, color, x, y in brain_types:
            eid = spawn_npc(app, zone, name, bkind, float(x), float(y), color)
            eids.append(eid)
        return eids

    def update(self, app: App, dt: float, tiles: list[list[int]],
               eids: list[int]):
        run_brains(app.world, dt)
        movement_system(app.world, dt, tiles)

    def info_text(self, app: App, eids: list[int]) -> str:
        return "AI Brains: Watch NPCs with different brain types.  [Space] reset"
