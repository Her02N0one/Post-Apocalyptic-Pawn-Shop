"""scenes/exhibits/patrol_exhibit.py — Patrol & Settlement exhibit.

Shows NPCs going about daily life around a pawn shop.  Guards walk
the building perimeter while civilians wander in the open.  Every
NPC stays within its patrol radius — a basic building block of
settlement life.

Testable outcomes:
    * After N ticks, each NPC has moved from its spawn.
    * No NPC drifts beyond its ``HomeRange.radius`` from origin.
"""

from __future__ import annotations
import pygame
from core.app import App
from core.constants import TILE_SIZE, TILE_WALL
from core.zone import ZONE_MAPS
from components import (
    Position, Velocity, Sprite, Identity, Collider, Hurtbox,
    Facing, Health, Lod, Brain,
)
from components.ai import HomeRange, VisionCone
from components.combat import CombatStats
from components.social import Faction
from logic.movement import movement_system
from logic.ai.brains import tick_ai
from scenes.exhibits.base import Exhibit
from scenes.exhibits.drawing import (
    draw_circle_alpha, draw_entity_vision_cones,
)


# ── Shop layout (tiles relative to arena) ────────────────────────────

_SHOP_WALLS: list[tuple[int, int]] = []

def _build_shop(tiles: list[list[int]]):
    """Place a small 6×4 'pawn shop' building in the center of the arena."""
    _SHOP_WALLS.clear()
    # Shop bounds: rows 14-17, cols 22-27  (centred in 50×35 arena)
    for c in range(22, 28):
        for r in (14, 17):
            tiles[r][c] = TILE_WALL
            _SHOP_WALLS.append((r, c))
    for r in range(14, 18):
        for c in (22, 27):
            tiles[r][c] = TILE_WALL
            _SHOP_WALLS.append((r, c))
    # Door on left wall
    tiles[15][22] = 0
    tiles[16][22] = 0


class PatrolExhibit(Exhibit):
    """Tab 0 — Patrol / settlement demo."""

    name = "Patrol"
    category = "AI & Behaviour"
    description = (
        "Settlement Patrol\n"
        "\n"
        "NPCs follow HomeRange-based patrol loops around a\n"
        "pawn shop building.  Guards walk the perimeter while\n"
        "civilians wander nearby.  Each NPC stays within its\n"
        "patrol radius (blue rings) from its spawn origin (dots).\n"
        "\n"
        "What to observe:\n"
        " - Guards have a 10 m patrol radius at 2.0 m/s\n"
        " - Vision cones (F5) show 5 km directional sight\n"
        " - Shopkeeper barely moves (1.5 m radius, 0.8 m/s)\n"
        " - Civilians wander 4-5 m from their origin\n"
        " - No NPC ever drifts outside its blue ring\n"
        "\n"
        "Systems:  tick_ai  movement  HomeRange  Brain(wander)\n"
        "Controls: [Space] start / pause / reset"
    )
    arena_w = 50
    arena_h = 35
    default_debug = {"ranges": True}

    def __init__(self):
        self.running = False
        self._ticks = 0

    def setup(self, app: App, zone: str, tiles: list[list[int]]) -> list[int]:
        self.running = False
        self._ticks = 0
        self._zone = zone

        _build_shop(tiles)
        ZONE_MAPS[zone] = tiles

        w = app.world
        eids: list[int] = []

        # ── Shopkeeper — barely moves, stays inside ─────────────────
        eids.append(_spawn_settler(
            w, zone, "Shopkeeper", "S", (180, 220, 140),
            x=24.0, y=15.5, radius=1.5, speed=0.8))

        # ── Guards — big patrol loop around the building ─────────────
        eids.append(_spawn_settler(
            w, zone, "Guard A", "G", (255, 200, 50),
            x=18.0, y=12.0, radius=10.0, speed=2.0, is_guard=True))
        eids.append(_spawn_settler(
            w, zone, "Guard B", "G", (255, 200, 50),
            x=32.0, y=22.0, radius=10.0, speed=2.0, is_guard=True))

        # ── Civilians — wander near the shop ─────────────────────────
        eids.append(_spawn_settler(
            w, zone, "Trader", "T", (120, 180, 220),
            x=10.0, y=8.0, radius=4.0, speed=1.4))
        eids.append(_spawn_settler(
            w, zone, "Scavenger", "C", (200, 160, 100),
            x=40.0, y=28.0, radius=5.0, speed=1.6))

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
        self._ticks += 1
        tick_ai(app.world, dt)
        movement_system(app.world, dt, tiles)

    # ── Drawing ──────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, ox: int, oy: int,
             app: App, eids: list[int],
             tile_px: int = TILE_SIZE, flags=None):
        # Patrol radius circles
        if not flags or flags.ranges:
            for eid in eids:
                if not app.world.alive(eid):
                    continue
                pos = app.world.get(eid, Position)
                patrol = app.world.get(eid, HomeRange)
                if not pos or not patrol:
                    continue
                cx = ox + int(pos.x * tile_px) + tile_px // 2
                cy = oy + int(pos.y * tile_px) + tile_px // 2
                r_px = int(patrol.radius * tile_px)

                # Patrol radius (faint circle)
                draw_circle_alpha(surface, (100, 200, 255, 20), cx, cy, r_px)
                pygame.draw.circle(surface, (100, 200, 255, 60),
                                   (cx, cy), r_px, 1)

                # Origin dot
                origin_sx = ox + int(patrol.origin_x * tile_px) + tile_px // 2
                origin_sy = oy + int(patrol.origin_y * tile_px) + tile_px // 2
                pygame.draw.circle(surface, (100, 200, 255),
                                   (origin_sx, origin_sy), 3)

        # Vision cones for guards
        if not flags or flags.vision:
            draw_entity_vision_cones(surface, ox, oy, app, eids, tile_px)

    def info_text(self, app: App, eids: list[int]) -> str:
        status = "RUNNING" if self.running else "READY"
        action = "pause" if self.running else "start"
        return (f"Patrol: {status}  Tick:{self._ticks}  "
                f"NPCs:{len(eids)}  Speed:2.0 m/s  [Space] {action}")


# ── Settler spawner ─────────────────────────────────────────────────

def _spawn_settler(w, zone: str, name: str, char: str,
                   color: tuple, *, x: float, y: float,
                   radius: float, speed: float,
                   is_guard: bool = False) -> int:
    eid = w.spawn()
    w.add(eid, Position(x=x, y=y, zone=zone))
    w.add(eid, Velocity())
    w.add(eid, Sprite(char=char, color=color))
    w.add(eid, Identity(name=name, kind="npc"))
    w.add(eid, Collider())
    w.add(eid, Facing())
    w.add(eid, Health(current=100, maximum=100))
    w.add(eid, CombatStats(damage=5, defense=2))
    w.add(eid, Lod(level="high"))
    w.add(eid, Brain(kind="wander", active=True))
    w.add(eid, HomeRange(origin_x=x, origin_y=y,
                         radius=radius, speed=speed))
    w.add(eid, Faction(group="settlers", disposition="neutral",
                       home_disposition="neutral"))
    if is_guard:
        w.add(eid, VisionCone(fov_degrees=120.0, view_distance=5000.0,
                              peripheral_range=10.0))
    w.zone_add(eid, zone)
    return eid
