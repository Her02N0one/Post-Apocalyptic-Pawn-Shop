"""scenes/exhibits/lod_exhibit.py — LOD Demo exhibit.

Scatter NPCs around the arena and visualise LOD tier transitions.
Click to move the LOD centre.  Entities near the centre are "high",
further away are "medium".  (Low only happens cross-zone, so it
can't be shown in a single-arena demo.)
"""

from __future__ import annotations
import math
import random
import pygame
from core.app import App
from core.constants import TILE_SIZE
from components import (
    Position, Velocity, Sprite, Identity, Collider, Facing,
    Health, Brain, Lod, GameClock,
)
from components.ai import HomeRange
from components.social import Faction
from logic.tick import tick_systems
from scenes.exhibits.base import Exhibit
from scenes.exhibits.drawing import draw_circle_alpha


_ARENA_W = 30
_ARENA_H = 20


class LODExhibit(Exhibit):
    """LOD tier visualisation demo."""

    name = "LOD Demo"

    def __init__(self):
        self._lod_radius = 8.0
        self._lod_center: tuple[float, float] = (_ARENA_W / 2.0, _ARENA_H / 2.0)

    # ── Lifecycle ────────────────────────────────────────────────────

    def setup(self, app: App, zone: str, tiles: list[list[int]]) -> list[int]:
        eids: list[int] = []
        w = app.world
        for i in range(15):
            x = random.uniform(3, _ARENA_W - 3)
            y = random.uniform(3, _ARENA_H - 3)
            eid = w.spawn()
            w.add(eid, Position(x=x, y=y, zone=zone))
            w.add(eid, Velocity())
            w.add(eid, Sprite(char="N", color=(150, 200, 180)))
            w.add(eid, Identity(name=f"NPC-{i+1}", kind="npc"))
            w.add(eid, Collider())
            w.add(eid, Facing())
            w.add(eid, Health(current=100, maximum=100))
            w.add(eid, Lod(level="medium"))
            w.add(eid, Brain(kind="wander", active=True))
            w.add(eid, HomeRange(origin_x=x, origin_y=y, radius=6.0, speed=2.0))
            w.add(eid, Faction(group="neutral", disposition="neutral",
                               home_disposition="neutral"))
            w.zone_add(eid, zone)
            eids.append(eid)
        self._lod_center = (_ARENA_W / 2.0, _ARENA_H / 2.0)
        return eids

    # ── Per-frame ────────────────────────────────────────────────────

    def update(self, app: App, dt: float, tiles: list[list[int]],
               eids: list[int]):
        cx, cy = self._lod_center
        w = app.world
        for eid in eids:
            if not w.alive(eid):
                continue
            pos = w.get(eid, Position)
            lod = w.get(eid, Lod)
            brain = w.get(eid, Brain)
            if not pos or not lod:
                continue
            d = math.hypot(pos.x - cx, pos.y - cy)
            lod.level = "high" if d <= self._lod_radius else "medium"
            if brain and not brain.active:
                brain.active = True

        tick_systems(w, dt, tiles, skip_lod=True, skip_needs=True)

    def handle_event(self, event: pygame.event.Event, app: App,
                     mouse_to_tile) -> bool:
        if event.type == pygame.MOUSEBUTTONDOWN:
            rc = mouse_to_tile()
            if rc:
                row, col = rc
                self._lod_center = (col + 0.5, row + 0.5)
                return True
        return False

    def on_space(self, app: App) -> str | None:
        return "reset"

    # ── Drawing ──────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, ox: int, oy: int,
             app: App, eids: list[int]):
        self._draw_lod_rings(surface, ox, oy)

    def _draw_lod_rings(self, surface: pygame.Surface, ox: int, oy: int):
        cx, cy = self._lod_center
        sx = ox + int(cx * TILE_SIZE)
        sy = oy + int(cy * TILE_SIZE)

        # High-LOD ring (green)
        r_high = int(self._lod_radius * TILE_SIZE)
        draw_circle_alpha(surface, (0, 255, 100, 25), sx, sy, r_high)
        pygame.draw.circle(surface, (0, 255, 100), (sx, sy), r_high, 1)

        # Medium-LOD ring (yellow)
        r_med = int(self._lod_radius * 2 * TILE_SIZE)
        draw_circle_alpha(surface, (255, 200, 50, 15), sx, sy, r_med)
        pygame.draw.circle(surface, (255, 200, 50), (sx, sy), r_med, 1)

        # Center marker
        pygame.draw.circle(surface, (255, 255, 255), (sx, sy), 4)

    def draw_entity_overlay(self, surface: pygame.Surface,
                            sx: int, sy: int, eid: int,
                            app: App) -> tuple[int, int, int] | None:
        """Override sprite colour with LOD-tier colouring."""
        lod = app.world.get(eid, Lod)
        if not lod:
            return None
        lod_color = {
            "high":   (0, 255, 100),
            "medium": (255, 200, 50),
            "low":    (255, 80, 80),
        }.get(lod.level, (180, 180, 180))
        # Tier letter next to sprite
        app.draw_text(surface, f"{lod.level[0].upper()}", sx + 22, sy - 2,
                      color=lod_color, font=app.font_sm)
        return lod_color

    def info_text(self, app: App, eids: list[int]) -> str:
        return (f"LOD Demo: Click to move LOD center. "
                f"Radius: {self._lod_radius:.0f}  [Space] reset")



