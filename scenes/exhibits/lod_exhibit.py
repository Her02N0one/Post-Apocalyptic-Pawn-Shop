"""scenes/exhibits/lod_exhibit.py — LOD Transition exhibit.

Demonstrates the full LOD lifecycle: entities start in high-LOD with
real Position + Brain, get *demoted* to low-LOD (SubzonePos, Brain
deactivated, events scheduled), then *promoted* back (Position restored,
Brain reactivated, grace period set).

Two zones are simulated: ``__museum__`` (player zone) and
``__offscreen__`` (unloaded zone).  A mini SubzoneGraph connects them.

Layout
------
Left side  — "Player Zone" with 3 NPCs (high-LOD, coloured green)
Right side — status panel showing LOD state, SubzonePos, scheduled events

Controls:
    Space — cycle: setup → demote all → promote all → reset
"""

from __future__ import annotations
from typing import TYPE_CHECKING

from scenes.exhibits.base import Exhibit
from core.constants import TILE_SIZE
from components import (
    Position, Velocity, Sprite, Identity, Collider, Hurtbox,
    Facing, Health, CombatStats, Lod, Brain, GameClock,
)
from components.ai import HomeRange
from components.social import Faction
from components.simulation import SubzonePos, Home
from simulation.subzone import SubzoneGraph, SubzoneNode
from simulation.scheduler import WorldScheduler
from simulation.lod_transition import promote_entity, demote_entity

if TYPE_CHECKING:
    import pygame
    from core.app import App

_ZONE_PLAYER = "__museum__"
_ZONE_OFFSCREEN = "__offscreen__"


class LODExhibit(Exhibit):
    """LOD Transition — promote / demote lifecycle."""

    name = "LOD"
    category = "Simulation"
    description = (
        "LOD Transition Lifecycle\n"
        "\n"
        "Demonstrates the Level-of-Detail system:\n"
        "\n"
        " HIGH LOD  — real Position + active Brain (green)\n"
        " LOW  LOD  — SubzonePos only, Brain off (red)\n"
        "             scheduled events replace simulation\n"
        "\n"
        "A tiny SubzoneGraph (plaza -> market -> ruins_east)\n"
        "connects two zones.  Press Space to cycle through\n"
        "the full promote / demote lifecycle:\n"
        "\n"
        " 1. All NPCs spawn in HIGH LOD (green, active)\n"
        " 2. DEMOTE: Position removed, SubzonePos assigned,\n"
        "    Brain.active = False, scheduler events queued\n"
        " 3. PROMOTE: Position restored, Brain reactivated,\n"
        "    grace period of 0.5 s before next demotion\n"
        "\n"
        "Systems:  promote_entity  demote_entity  WorldScheduler\n"
        "Controls: [Space] cycle phases / reset"
    )
    default_debug = {"positions": True, "brain": True}

    def __init__(self):
        self._graph: SubzoneGraph | None = None
        self._scheduler: WorldScheduler | None = None
        self._phase = "high"   # high → demoted → promoted
        self._log: list[str] = []

    # ── setup ────────────────────────────────────────────────────────

    def setup(self, app, zone, tiles):
        eids: list[int] = []
        self._phase = "high"
        self._log = ["All NPCs spawned in HIGH LOD"]

        # Build a tiny subzone graph
        graph = SubzoneGraph()
        graph.add_node(SubzoneNode(
            id="plaza", zone=_ZONE_PLAYER,
            anchor=(8, 8), shelter=True,
        ))
        graph.add_node(SubzoneNode(
            id="market", zone=_ZONE_PLAYER,
            anchor=(20, 10), shelter=False,
        ))
        graph.add_node(SubzoneNode(
            id="ruins_east", zone=_ZONE_OFFSCREEN,
            anchor=(10, 10), shelter=False, threat_level=0.5,
        ))
        graph.add_edge("plaza", "market", 3.0)
        graph.add_edge("market", "ruins_east", 8.0)
        self._graph = graph
        app.world.set_res(graph)

        sched = WorldScheduler()
        self._scheduler = sched
        app.world.set_res(sched)

        for name, x, y, kind in [
            ("Guard",      8.0,  8.0, "guard"),
            ("Trader",    14.0, 10.0, "villager"),
            ("Scavenger", 20.0, 10.0, "wander"),
        ]:
            eid = self._spawn_npc(app, zone, name, x, y, kind)
            eids.append(eid)

        return eids

    def _spawn_npc(self, app, zone, name, x, y, kind):
        w = app.world
        eid = w.spawn()
        w.add(eid, Position(x=x, y=y, zone=zone))
        w.add(eid, Velocity())
        w.add(eid, Sprite(char=name[0], color=(100, 220, 100)))
        w.add(eid, Identity(name=name, kind="npc"))
        w.add(eid, Collider())
        w.add(eid, Hurtbox())
        w.add(eid, Facing())
        w.add(eid, Health(current=80, maximum=100))
        w.add(eid, CombatStats(damage=8, defense=3))
        w.add(eid, Lod(level="high"))
        w.add(eid, Brain(kind=kind, active=True))
        w.add(eid, HomeRange(origin_x=x, origin_y=y, radius=6.0, speed=2.0))
        w.add(eid, Faction(group="settlers", disposition="neutral",
                           home_disposition="neutral"))
        w.add(eid, Home(zone=zone, subzone="plaza"))
        w.zone_add(eid, zone)
        return eid

    # ── controls ─────────────────────────────────────────────────────

    def on_space(self, app):
        if self._phase == "high":
            self._do_demote(app)
            return None
        elif self._phase == "demoted":
            self._do_promote(app)
            return None
        else:
            return "reset"

    def _do_demote(self, app):
        w = app.world
        clock = w.res(GameClock)
        gt = clock.time if clock else 0.0
        demoted = 0
        for eid, _pos in list(w.all_of(Position)):
            if w.get(eid, Identity) and w.get(eid, Brain):
                if demote_entity(w, eid, self._graph, self._scheduler, gt):
                    demoted += 1
        self._phase = "demoted"
        pending = self._scheduler.pending_count()
        self._log.append(f"Demoted {demoted} NPCs → low LOD")
        self._log.append(f"  Brain.active = False")
        self._log.append(f"  Position → SubzonePos")
        self._log.append(f"  {pending} scheduler events queued")

    def _do_promote(self, app):
        w = app.world
        clock = w.res(GameClock)
        gt = clock.time if clock else 0.0
        promoted = 0
        for eid, szp in list(w.all_of(SubzonePos)):
            ident = w.get(eid, Identity)
            if ident and ident.kind == "npc":
                if promote_entity(w, eid, self._graph, self._scheduler, gt):
                    promoted += 1
        self._phase = "promoted"
        self._log.append(f"Promoted {promoted} NPCs → high LOD")
        self._log.append(f"  Brain.active = True")
        self._log.append(f"  SubzonePos → Position")
        self._log.append(f"  Grace period: 0.5 s")

    # ── update ───────────────────────────────────────────────────────

    def update(self, app, dt, tiles, eids):
        if self._phase == "demoted" and self._scheduler:
            clock = app.world.res(GameClock)
            if clock:
                self._scheduler.tick(app.world, clock.time)

    # ── draw ─────────────────────────────────────────────────────────

    def draw(self, surface, ox, oy, app, eids, tile_px=TILE_SIZE, flags=None):
        import pygame

        app.draw_text(surface, "PLAYER ZONE", ox + 4 * tile_px, oy + 1 * tile_px,
                      (0, 200, 160), app.font_sm)

        if self._graph:
            for node in self._graph.nodes.values():
                if node.zone != _ZONE_PLAYER:
                    continue
                ax, ay = node.anchor
                cx = ox + ax * tile_px + tile_px // 2
                cy = oy + ay * tile_px + tile_px // 2
                pygame.draw.circle(surface, (60, 120, 100), (cx, cy), 12, 1)
                app.draw_text(surface, node.id, cx - 14, cy + 14,
                              (80, 160, 130), app.font_sm)

        # Status panel
        w = app.world
        panel_x = ox + 22 * tile_px
        py = oy + 2 * tile_px

        app.draw_text(surface, f"Phase: {self._phase.upper()}", panel_x, py,
                      (255, 255, 255), app.font_sm)
        py += 16

        for eid in eids:
            if not w.alive(eid):
                continue
            ident = w.get(eid, Identity)
            name = ident.name if ident else "?"
            lod = w.get(eid, Lod)
            brain = w.get(eid, Brain)
            pos = w.get(eid, Position)
            szp = w.get(eid, SubzonePos)

            level = lod.level if lod else "?"
            active = brain.active if brain else False
            loc = (f"({pos.x:.0f},{pos.y:.0f}) m" if pos
                   else f"sz:{szp.subzone}" if szp else "?")

            color = ((100, 220, 100) if level == "high"
                     else (220, 180, 60) if level == "medium"
                     else (220, 80, 80))

            py += 4
            app.draw_text(surface, name, panel_x, py, color, app.font_sm)
            py += 14
            app.draw_text(surface, f"  LOD:{level} brain:{'ON' if active else 'OFF'}",
                          panel_x, py, (160, 160, 160), app.font_sm)
            py += 14
            app.draw_text(surface, f"  loc:{loc}", panel_x, py,
                          (130, 130, 130), app.font_sm)
            py += 14

        if self._scheduler:
            py += 8
            pending = self._scheduler.pending_count()
            app.draw_text(surface, f"Scheduler: {pending} events",
                          panel_x, py, (180, 180, 100), app.font_sm)
            py += 14

        py += 8
        app.draw_text(surface, "--- Log ---", panel_x, py,
                      (120, 120, 120), app.font_sm)
        py += 14
        for line in self._log[-8:]:
            app.draw_text(surface, line, panel_x, py,
                          (160, 160, 160), app.font_sm)
            py += 13

    def draw_entity_overlay(self, surface, sx, sy, eid, app):
        lod = app.world.get(eid, Lod)
        if not lod:
            return None
        if lod.level == "high":
            return (100, 220, 100)
        elif lod.level == "medium":
            return (220, 180, 60)
        return (220, 80, 80)

    def info_text(self, app, eids):
        return f"[Space] {self._phase} -> next  |  LOD lifecycle: high -> demote -> promote"
