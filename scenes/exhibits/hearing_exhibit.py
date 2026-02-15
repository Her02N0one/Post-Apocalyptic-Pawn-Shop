"""scenes/exhibits/hearing_exhibit.py — Hearing & Searching exhibit.

A raider fires a gunshot.  The report carries ~1.6 km (1 mile) — far
beyond this arena — so **every** guard hears it immediately.

Guards enter **searching** mode, walk toward the noise, and scan with
their vision cone until they spot the target (→ chase) or time out
(→ idle).  The guards start facing AWAY from the raider so they must
physically turn around via the search-scan rotation.

Closer guards reach the sound source first and engage sooner.

Testable outcomes:
    * After gunshot, all guards enter ``searching``.
    * Searching guards walk toward the sound source.
    * Guards spot the raider via vision cone → transition to ``chase``.
    * Nearer guards reach and engage the raider before farther ones.
"""

from __future__ import annotations
import math
import pygame
from core.app import App
from core.constants import TILE_SIZE
from core.events import EventBus
from components import (
    Position, Velocity, Sprite, Identity, Collider, Hurtbox,
    Facing, Health, Lod, Brain, GameClock,
)
from components.ai import HomeRange, Threat, AttackConfig, VisionCone
from components.combat import CombatStats
from components.social import Faction
from logic.movement import movement_system
from logic.ai.brains import tick_ai
from logic.combat.projectiles import projectile_system
from logic.combat import handle_death, npc_melee_attack, npc_ranged_attack
from logic.combat.attacks import emit_combat_sound
from scenes.exhibits.base import Exhibit
from scenes.exhibits.drawing import draw_circle_alpha  # kept for potential future use


class HearingExhibit(Exhibit):
    """Tab 2 — Hearing / searching demo."""

    name = "Hearing"
    category = "AI & Perception"
    description = (
        "Hearing & Searching\n"
        "\n"
        "A raider fires a gunshot.  The sound carries ~1.6 km\n"
        "(1 mile) — far beyond this 100 m arena — so ALL guards\n"
        "hear it and enter SEARCHING mode.  They walk toward\n"
        "the noise and scan with their vision cone until they\n"
        "spot the raider (→ chase) or time out (→ idle).\n"
        "\n"
        "Guards start facing AWAY from the raider so they\n"
        "must physically turn around via search-scan rotation.\n"
        "\n"
        "What to observe:\n"
        " - ALL guards hear the shot (1.6 km >> 100 m arena)\n"
        " - Near guard (~25 m) reaches the raider first\n"
        " - Mid guard (~50 m) arrives second\n"
        " - Far guard (~85 m) takes the longest to engage\n"
        " - Vision cone rotation while scanning\n"
        " - Transition: idle → searching → chase → attack\n"
        "\n"
        "Systems:  emit_combat_sound  tick_ai  VisionCone\n"
        "Controls: [Space] fire gunshot / reset"
    )
    arena_w = 100
    arena_h = 60
    default_debug = {"brain": True, "ranges": True}

    def __init__(self):
        self.running = False
        self._fired = False
        self._raider_eid: int | None = None
        self._guard_eids: list[int] = []
        self._far_guard_eid: int | None = None
        self._ticks = 0
        self._state_log: list[str] = []

    def setup(self, app: App, zone: str, tiles: list[list[int]]) -> list[int]:
        self.running = False
        self._fired = False
        self._ticks = 0
        self._state_log.clear()
        self._guard_eids = []
        self._zone = zone

        w = app.world
        eids: list[int] = []

        # EventBus
        w.set_res(EventBus())
        bus = w.res(EventBus)
        bus.subscribe("EntityDied", lambda ev: handle_death(w, ev.eid))
        bus.subscribe("AttackIntent", lambda ev: (
            npc_ranged_attack(w, ev.attacker_eid, ev.target_eid)
            if ev.attack_type == "ranged"
            else npc_melee_attack(w, ev.attacker_eid, ev.target_eid)))

        # ── Raider — left side with a gun ────────────────────────────
        rid = w.spawn()
        w.add(rid, Position(x=5.0, y=30.0, zone=zone))
        w.add(rid, Velocity())
        w.add(rid, Sprite(char="R", color=(255, 60, 60)))
        w.add(rid, Identity(name="Raider", kind="npc"))
        w.add(rid, Collider())
        w.add(rid, Hurtbox())
        w.add(rid, Facing(direction="right"))
        w.add(rid, Health(current=100, maximum=100))
        w.add(rid, CombatStats(damage=15, defense=5))
        w.add(rid, Lod(level="high"))
        w.add(rid, Brain(kind="wander", active=False))
        w.add(rid, HomeRange(origin_x=5.0, origin_y=30.0,
                             radius=1.0, speed=0.0))
        w.add(rid, Faction(group="raiders", disposition="hostile",
                           home_disposition="hostile"))
        w.add(rid, Threat(aggro_radius=5000.0, leash_radius=200.0))
        w.add(rid, AttackConfig(attack_type="ranged", range=10.0,
                                cooldown=0.8))
        w.zone_add(rid, zone)
        eids.append(rid)
        self._raider_eid = rid

        # ── Guards — right side, facing DOWN (away from raider) ──────
        guard_data = [
            ("Guard Near",  30.0, 30.0),   # ~25 m from raider
            ("Guard Mid",   55.0, 25.0),   # ~50 m from raider
            ("Guard Far",   90.0, 30.0),   # ~85 m — still well within 1.6 km
        ]
        for name, gx, gy in guard_data:
            gid = _spawn_guard(w, zone, name, gx, gy, facing="down")
            eids.append(gid)
            self._guard_eids.append(gid)

        return eids

    def on_space(self, app: App) -> str | None:
        if not self.running and not self._fired:
            # First press: start simulation and fire gunshot
            self.running = True
            self._fire_gunshot(app)
            return None
        elif self.running:
            # Second press: reset
            self.running = False
            self._fired = False
            return "reset"
        return "reset"

    def _fire_gunshot(self, app: App):
        """Emit a gunshot sound from the raider's position."""
        self._fired = True
        w = app.world
        rid = self._raider_eid
        if rid is None or not w.alive(rid):
            return
        rpos = w.get(rid, Position)
        if rpos:
            emit_combat_sound(w, rid, rpos, "gunshot")
            self._state_log.append("Raider fired!")

    def update(self, app: App, dt: float, tiles: list[list[int]],
               eids: list[int]):
        if not self.running:
            return
        self._ticks += 1
        tick_ai(app.world, dt)
        movement_system(app.world, dt, tiles)
        projectile_system(app.world, dt, tiles)
        bus = app.world.res(EventBus)
        if bus:
            bus.drain()
        self._update_log(app)

    def _update_log(self, app: App):
        w = app.world
        for gid in self._guard_eids:
            if not w.alive(gid):
                continue
            brain = w.get(gid, Brain)
            ident = w.get(gid, Identity)
            if not brain or not ident:
                continue
            c = brain.state.get("combat", {})
            mode = c.get("mode", "idle")
            tag = f"{ident.name}:{mode}"
            if not self._state_log or self._state_log[-1] != tag:
                # Only log transitions
                prev = None
                for entry in reversed(self._state_log):
                    if entry.startswith(ident.name + ":"):
                        prev = entry
                        break
                if prev != tag:
                    self._state_log.append(tag)

    # ── Drawing ──────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, ox: int, oy: int,
             app: App, eids: list[int],
             tile_px: int = TILE_SIZE, flags=None):
        w = app.world

        # Hearing range annotation (raider position)
        if not flags or flags.ranges:
            rid = self._raider_eid
            if rid and w.alive(rid):
                rpos = w.get(rid, Position)
                if rpos:
                    cx = ox + int(rpos.x * tile_px) + tile_px // 2
                    cy = oy + int(rpos.y * tile_px) + tile_px // 2
                    app.draw_text(surface, "gunshot: 1.6 km range",
                                  cx - 40, cy - tile_px - 14,
                                  (255, 100, 50), app.font_sm)
                    app.draw_text(surface, "(all guards hear this)",
                                  cx - 45, cy - tile_px,
                                  (255, 150, 80), app.font_sm)

        # Search-source arrows (always shown when searching)
        for eid in eids:
            if not w.alive(eid):
                continue
            brain = w.get(eid, Brain)
            if not brain:
                continue
            pos = w.get(eid, Position)
            if not pos:
                continue
            c = brain.state.get("combat", {})
            mode = c.get("mode")
            if mode == "searching":
                src = c.get("search_source")
                if src:
                    pcx = ox + int(pos.x * tile_px) + tile_px // 2
                    pcy = oy + int(pos.y * tile_px) + tile_px // 2
                    angle = math.atan2(src[1] - pos.y, src[0] - pos.x)
                    arrow_len = tile_px
                    ex = pcx + int(math.cos(angle) * arrow_len)
                    ey = pcy + int(math.sin(angle) * arrow_len)
                    pygame.draw.line(surface, (255, 180, 50),
                                     (pcx, pcy), (ex, ey), 2)

        # State log (right side, below HUD bars)
        sw = surface.get_width()
        y_off = 60
        app.draw_text(surface, "Event Log:", sw - 160, y_off,
                      (200, 200, 200), app.font_sm)
        y_off += 16
        for entry in self._state_log[-12:]:
            color = (255, 80, 80) if "fired" in entry.lower() else \
                    (255, 180, 50) if "searching" in entry else \
                    (80, 255, 80) if "chase" in entry else \
                    (180, 180, 180)
            app.draw_text(surface, entry, sw - 160, y_off,
                          color, app.font_sm)
            y_off += 14

    def info_text(self, app: App, eids: list[int]) -> str:
        if not self._fired:
            return "Hearing: READY  [Space] fire gunshot"
        status = "RUNNING" if self.running else "DONE"
        # Count modes
        modes: dict[str, int] = {}
        w = app.world
        for gid in self._guard_eids:
            if not w.alive(gid):
                continue
            brain = w.get(gid, Brain)
            if brain:
                c = brain.state.get("combat", {})
                m = c.get("mode", "idle")
                modes[m] = modes.get(m, 0) + 1
        mode_str = " ".join(f"{k}:{v}" for k, v in sorted(modes.items()))
        return (f"Hearing: {status}  Tick:{self._ticks}  "
                f"Guards: {mode_str}  [Space] reset")


# ── Guard spawner ────────────────────────────────────────────────────

def _spawn_guard(w, zone: str, name: str,
                 x: float, y: float, *,
                 facing: str = "down") -> int:
    """Spawn a neutral armed guard that can enter searching/combat."""
    eid = w.spawn()
    w.add(eid, Position(x=x, y=y, zone=zone))
    w.add(eid, Velocity())
    w.add(eid, Sprite(char="G", color=(100, 200, 255)))
    w.add(eid, Identity(name=name, kind="npc"))
    w.add(eid, Collider())
    w.add(eid, Hurtbox())
    w.add(eid, Facing(direction=facing))
    w.add(eid, Health(current=100, maximum=100))
    w.add(eid, CombatStats(damage=12, defense=6))
    w.add(eid, Lod(level="high"))
    w.add(eid, Brain(kind="guard", active=True))
    w.add(eid, HomeRange(origin_x=x, origin_y=y,
                         radius=15.0, speed=2.0))
    w.add(eid, Faction(group="guards", disposition="neutral",
                       home_disposition="neutral"))
    w.add(eid, Threat(aggro_radius=5000.0, leash_radius=200.0,
                      flee_threshold=0.0, sensor_interval=0.0))
    w.add(eid, AttackConfig(attack_type="melee", range=1.2,
                            cooldown=0.5))
    w.add(eid, VisionCone(fov_degrees=120.0, view_distance=5000.0,
                          peripheral_range=10.0))
    w.zone_add(eid, zone)
    return eid
