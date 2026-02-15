"""scenes/exhibits/crime_exhibit.py — Crime & Witness exhibit.

Demonstrates the witness-based crime system: a "player" steals an
item near NPCs.  Witnesses within detection radius record the crime
in WorldMemory.  Armed witnesses (guards) turn hostile.  Unarmed
civilians remember the crime and flee.

Layout
------
Centre   — a container (chest) with items
Left     — 2 armed guards (close, far)
Right    — 2 civilians (close, far)
Bottom   — event log

Controls:
    Space — simulate a theft → witnesses react → reset
"""

from __future__ import annotations
import math
from typing import TYPE_CHECKING

from scenes.exhibits.base import Exhibit
from core.constants import TILE_SIZE
from components import (
    Position, Velocity, Sprite, Identity, Collider, Hurtbox,
    Facing, Health, CombatStats, Lod, Brain, GameClock,
    Player, Inventory,
)
from components.ai import HomeRange, Threat, AttackConfig, VisionCone
from components.social import Faction, CrimeRecord
from components.simulation import WorldMemory
from logic.crime import find_witnesses, report_theft

if TYPE_CHECKING:
    import pygame
    from core.app import App

_WITNESS_RADIUS = 30.0  # m  (close enough to identify actions as criminal)


class CrimeExhibit(Exhibit):
    """Crime & Witness — theft detection and guard reaction."""

    name = "Crime"
    category = "Social"
    description = (
        "Crime & Witness System\n"
        "\n"
        "A player steals an item from a chest.  NPCs within\n"
        "the witness detection radius (30 m, red ring) observe\n"
        "the crime and react based on their role:\n"
        "\n"
        " Guards (armed)   — turn hostile, record crime\n"
        " Civilians (unarmed) — remember crime, may flee\n"
        " NPCs outside radius — unaware\n"
        "\n"
        "What to observe:\n"
        " - Guard Near (7 m away) detects the theft\n"
        " - Civilian Near (8 m away) witnesses the crime\n"
        " - Guard Far (35 m away) is outside detection radius\n"
        " - Civilian Far (35 m away) is unaware\n"
        " - WorldMemory records 'crime:player_theft' on witnesses\n"
        "\n"
        "Systems:  find_witnesses  report_theft  WorldMemory\n"
        "Controls: [Space] steal / reset"
    )
    arena_w = 80
    arena_h = 40
    default_debug = {"faction": True, "ranges": True}

    def __init__(self):
        self._player_eid: int = 0
        self._chest_pos: tuple[float, float] = (40.0, 20.0)
        self._log: list[str] = []
        self._stolen = False

    def setup(self, app, zone, tiles):
        self._log = ["Press [Space] to steal from the chest"]
        self._stolen = False
        w = app.world
        eids: list[int] = []

        # Spawn "player" entity near chest
        p = w.spawn()
        w.add(p, Position(x=39.0, y=20.0, zone=zone))
        w.add(p, Velocity())
        w.add(p, Sprite(char="@", color=(0, 255, 200)))
        w.add(p, Identity(name="Player", kind="player"))
        w.add(p, Health(current=100, maximum=100))
        w.add(p, Player(speed=3.0))
        w.add(p, CrimeRecord())
        w.zone_add(p, zone)
        self._player_eid = p
        eids.append(p)

        # Spawn chest
        chest = w.spawn()
        w.add(chest, Position(x=40.0, y=20.0, zone=zone))
        w.add(chest, Sprite(char="C", color=(200, 170, 60)))
        w.add(chest, Identity(name="Chest", kind="container"))
        w.add(chest, Inventory(items={"gold_watch": 1, "ammo_9mm": 5}))
        w.zone_add(chest, zone)
        eids.append(chest)

        # Guard close (within 30 m radius, d≈7)
        g1 = self._spawn_npc(app, zone, "Guard Near", 33.0, 20.0,
                             color=(80, 160, 255), armed=True)
        eids.append(g1)

        # Guard far (outside 30 m radius, d≈35)
        g2 = self._spawn_npc(app, zone, "Guard Far", 5.0, 20.0,
                             color=(60, 120, 200), armed=True)
        eids.append(g2)

        # Civilian close (within 30 m, d≈8)
        c1 = self._spawn_npc(app, zone, "Civilian Near", 48.0, 20.0,
                             color=(80, 200, 80), armed=False)
        eids.append(c1)

        # Civilian far (outside 30 m, d≈35)
        c2 = self._spawn_npc(app, zone, "Civilian Far", 75.0, 20.0,
                             color=(60, 160, 60), armed=False)
        eids.append(c2)

        return eids

    def _spawn_npc(self, app, zone, name, x, y, *, color, armed):
        w = app.world
        eid = w.spawn()
        w.add(eid, Position(x=x, y=y, zone=zone))
        w.add(eid, Velocity())
        w.add(eid, Sprite(char=name[0], color=color))
        w.add(eid, Identity(name=name, kind="npc"))
        w.add(eid, Collider())
        w.add(eid, Facing())
        w.add(eid, Health(current=100, maximum=100))
        w.add(eid, CombatStats(damage=8, defense=3))
        w.add(eid, Lod(level="high"))
        w.add(eid, Brain(kind="guard" if armed else "wander", active=True))
        w.add(eid, HomeRange(origin_x=x, origin_y=y, radius=4.0, speed=2.0))
        w.add(eid, Faction(group="settlers", disposition="friendly",
                           home_disposition="friendly"))
        w.add(eid, WorldMemory())
        if armed:
            w.add(eid, Threat(aggro_radius=5000.0, leash_radius=200.0))
            w.add(eid, AttackConfig(attack_type="melee", range=1.2, cooldown=0.5))
            w.add(eid, VisionCone(fov_degrees=120.0, view_distance=5000.0,
                                  peripheral_range=10.0))
        w.zone_add(eid, zone)
        return eid

    def on_space(self, app):
        if self._stolen:
            return "reset"
        self._do_theft(app)
        return None

    def _do_theft(self, app):
        w = app.world
        clock = w.res(GameClock)
        gt = clock.time if clock else 0.0
        px, py_pos = 39.0, 20.0  # player position

        # Find witnesses
        witnesses = find_witnesses(w, "__museum__", px, py_pos,
                                   radius=_WITNESS_RADIUS)
        self._log = [
            f"Theft at ({px:.0f},{py_pos:.0f})  radius={_WITNESS_RADIUS:.0f} m",
            f"Witnesses found: {len(witnesses)}",
        ]

        for weid in witnesses:
            ident = w.get(weid, Identity)
            pos = w.get(weid, Position)
            if ident and pos:
                d = math.hypot(pos.x - px, pos.y - py_pos)
                self._log.append(f"  {ident.name} (d={d:.1f} m)")

        # Report the theft
        msg = report_theft(w, witnesses, "gold_watch", "settlers", gt)
        if msg:
            self._log.append(f"Report: {msg}")

        # Show aftermath
        self._log.append("")
        for weid in witnesses:
            ident = w.get(weid, Identity)
            faction = w.get(weid, Faction)
            wmem = w.get(weid, WorldMemory)
            name = ident.name if ident else "?"
            disp = faction.disposition if faction else "?"
            has_mem = bool(wmem and wmem.entries.get("crime:player_theft"))
            self._log.append(f"{name}: disp={disp} crime_mem={has_mem}")

        self._stolen = True

    def update(self, app, dt, tiles, eids):
        pass

    def draw(self, surface, ox, oy, app, eids, tile_px=TILE_SIZE, flags=None):
        import pygame
        w = app.world

        # Draw witness radius circle around theft position
        if not flags or flags.ranges:
            cx = ox + int(self._chest_pos[0] * tile_px) + tile_px // 2
            cy = oy + int(self._chest_pos[1] * tile_px) + tile_px // 2
            r = int(_WITNESS_RADIUS * tile_px)
            pygame.draw.circle(surface, (200, 100, 100), (cx, cy), r, 1)
            app.draw_text(surface, f"witness radius {_WITNESS_RADIUS:.0f} m",
                          cx - 50, cy - r - 14,
                          (200, 100, 100), app.font_sm)

        # Log panel
        panel_x = ox + 2 * tile_px
        py = oy + 22 * tile_px
        for line in self._log[-10:]:
            app.draw_text(surface, line, panel_x, py,
                          (180, 180, 180), app.font_sm)
            py += 14

    def info_text(self, app, eids):
        if self._stolen:
            return "[Space] Reset  |  Witnesses recorded crime; guards turned hostile"
        return "[Space] Steal  |  Crime witness detection + guard reaction"
