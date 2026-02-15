"""scenes/exhibits/vision_exhibit.py — Directional Vision exhibit.

Demonstrates that NPCs can only see targets within their vision cone.
A guard faces right — a target in front is detected immediately, a
target behind is invisible.  Peripheral range gives close-range
omnidirectional awareness.

Testable outcomes:
    * Target in front (A) → detected, guard chases.
    * Target behind (B) → NOT detected, guard ignores.
    * Target within peripheral range (C) → always detected.
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
from logic.ai.perception import in_vision_cone, facing_to_angle
from scenes.exhibits.base import Exhibit
from scenes.exhibits.drawing import draw_cone_alpha, draw_circle_alpha


class VisionExhibit(Exhibit):
    """Tab 5 — Directional vision cone demo."""

    name = "Vision"
    category = "AI & Perception"
    description = (
        "Directional Vision Cones\n"
        "\n"
        "A guard faces right with a 90° FOV cone and\n"
        "5 km view distance (human eyesight, clear day).\n"
        "Three targets test detection:\n"
        "\n"
        " Target A (green)  — in front: detected immediately\n"
        " Target B (red)    — behind:  invisible to the cone\n"
        " Target C (yellow) — within 10 m peripheral range:\n"
        "                     always detected regardless of\n"
        "                     facing direction\n"
        "\n"
        "What to observe:\n"
        " - Yellow wedge = full vision cone (extends beyond arena)\n"
        " - Small circle = peripheral range (close-range 360°)\n"
        " - Status labels show DETECTED vs hidden in real time\n"
        " - Guard chases Target A when simulation starts\n"
        " - Target B stays undetected unless guard turns around\n"
        "\n"
        "Systems:  in_vision_cone  VisionCone  facing_to_angle\n"
        "Controls: [Space] start / pause / reset"
    )
    arena_w = 60
    arena_h = 40
    default_debug = {"vision": True, "ranges": True, "brain": True}

    def __init__(self):
        self.running = False
        self._guard_eid: int | None = None
        self._target_a: int | None = None   # in front
        self._target_b: int | None = None   # behind
        self._target_c: int | None = None   # peripheral
        self.detected_a = False
        self.detected_b = False
        self.detected_c = False
        self._ticks = 0

    def setup(self, app: App, zone: str, tiles: list[list[int]]) -> list[int]:
        self.running = False
        self.detected_a = False
        self.detected_b = False
        self.detected_c = False
        self._ticks = 0

        w = app.world
        eids: list[int] = []

        # EventBus for combat
        w.set_res(EventBus())
        bus = w.res(EventBus)
        bus.subscribe("EntityDied", lambda ev: handle_death(w, ev.eid))
        bus.subscribe("AttackIntent", lambda ev: (
            npc_ranged_attack(w, ev.attacker_eid, ev.target_eid)
            if ev.attack_type == "ranged"
            else npc_melee_attack(w, ev.attacker_eid, ev.target_eid)))

        # ── Guard — center, facing RIGHT ─────────────────────────────
        gid = w.spawn()
        w.add(gid, Position(x=30.0, y=20.0, zone=zone))
        w.add(gid, Velocity())
        w.add(gid, Sprite(char="G", color=(255, 200, 50)))
        w.add(gid, Identity(name="Guard", kind="npc"))
        w.add(gid, Collider())
        w.add(gid, Hurtbox())
        w.add(gid, Facing(direction="right"))
        w.add(gid, Health(current=150, maximum=150))
        w.add(gid, CombatStats(damage=10, defense=8))
        w.add(gid, Lod(level="high"))
        w.add(gid, Brain(kind="guard", active=True))
        w.add(gid, HomeRange(origin_x=30.0, origin_y=20.0,
                             radius=20.0, speed=2.2))
        w.add(gid, Faction(group="guards", disposition="hostile",
                           home_disposition="hostile"))
        w.add(gid, Threat(aggro_radius=5000.0, leash_radius=200.0,
                          flee_threshold=0.0, sensor_interval=0.0))
        w.add(gid, AttackConfig(attack_type="melee", range=1.2,
                                cooldown=0.5))
        w.add(gid, VisionCone(fov_degrees=90.0, view_distance=5000.0,
                              peripheral_range=10.0))
        w.zone_add(gid, zone)
        eids.append(gid)
        self._guard_eid = gid

        # ── Target A — to the RIGHT (in cone) ───────────────────────
        self._target_a = _spawn_target(
            w, zone, "Target A", 48.0, 20.0, (80, 255, 80), "enemies")
        eids.append(self._target_a)

        # ── Target B — to the LEFT (behind guard) ────────────────────
        self._target_b = _spawn_target(
            w, zone, "Target B", 10.0, 20.0, (255, 80, 80), "enemies")
        eids.append(self._target_b)

        # ── Target C — very close (within peripheral range) ──────────
        self._target_c = _spawn_target(
            w, zone, "Target C", 29.0, 19.0, (255, 255, 80), "enemies")
        eids.append(self._target_c)

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
        projectile_system(app.world, dt, tiles)
        bus = app.world.res(EventBus)
        if bus:
            bus.drain()
        self._check_detections(app)

    def _check_detections(self, app: App):
        w = app.world
        gid = self._guard_eid
        if gid is None or not w.alive(gid):
            return
        gpos = w.get(gid, Position)
        gface = w.get(gid, Facing)
        cone = w.get(gid, VisionCone)
        if not gpos or not gface or not cone:
            return

        for tag, tid, attr in [
            ("a", self._target_a, "detected_a"),
            ("b", self._target_b, "detected_b"),
            ("c", self._target_c, "detected_c"),
        ]:
            if tid is None or not w.alive(tid):
                continue
            tpos = w.get(tid, Position)
            if tpos and in_vision_cone(gpos, gface.direction, tpos, cone):
                setattr(self, attr, True)

    # ── Drawing ──────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, ox: int, oy: int,
             app: App, eids: list[int],
             tile_px: int = TILE_SIZE, flags=None):
        gid = self._guard_eid
        if gid is None or not app.world.alive(gid):
            return
        w = app.world
        pos = w.get(gid, Position)
        facing = w.get(gid, Facing)
        cone = w.get(gid, VisionCone)
        if not pos or not facing or not cone:
            return

        cx = ox + int(pos.x * tile_px) + tile_px // 2
        cy = oy + int(pos.y * tile_px) + tile_px // 2

        # Vision cone wedge
        if not flags or flags.vision:
            face_angle = facing_to_angle(facing.direction)
            half_fov = math.radians(cone.fov_degrees / 2.0)
            # Cap visual to arena extents (actual detection is still 5 km)
            sw_local, sh_local = surface.get_size()
            max_vis = int(math.hypot(sw_local, sh_local) * 0.5) + 50
            view_px = min(int(cone.view_distance * tile_px), max_vis)
            draw_cone_alpha(surface, (255, 200, 50, 25),
                            cx, cy, view_px, face_angle, half_fov)

            # Cone edge lines
            for sign in (-1, 1):
                a = face_angle + sign * half_fov
                ex = cx + int(math.cos(a) * view_px)
                ey = cy + int(math.sin(a) * view_px)
                pygame.draw.line(surface, (255, 200, 50), (cx, cy), (ex, ey), 1)

        # Peripheral range circle
        if not flags or flags.ranges:
            periph_px = int(cone.peripheral_range * tile_px)
            pygame.draw.circle(surface, (255, 200, 100), (cx, cy), periph_px, 1)

        # Detection status labels
        labels = [
            (self._target_a, self.detected_a, "A: IN FRONT"),
            (self._target_b, self.detected_b, "B: BEHIND"),
            (self._target_c, self.detected_c, "C: CLOSE"),
        ]
        y_off = 60
        for tid, detected, label in labels:
            color = (80, 255, 80) if detected else (255, 80, 80)
            status = "DETECTED" if detected else "hidden"
            app.draw_text(surface, f"{label} — {status}",
                          8, y_off, color, app.font_sm)
            y_off += 16

            # Ring around target
            if tid and w.alive(tid):
                tpos = w.get(tid, Position)
                if tpos:
                    tx = ox + int(tpos.x * tile_px) + tile_px // 2
                    ty_scr = oy + int(tpos.y * tile_px) + tile_px // 2
                    ring_col = (80, 255, 80) if detected else (255, 80, 80)
                    pygame.draw.circle(surface, ring_col, (tx, ty_scr),
                                       tile_px // 2 + 4, 2)

        # Guard FSM state
        brain = w.get(gid, Brain)
        if brain:
            c = brain.state.get("combat", {})
            mode = c.get("mode", "idle")
            app.draw_text(surface, f"Guard: {mode}",
                          8, y_off + 8, (220, 220, 220), app.font_sm)

    def info_text(self, app: App, eids: list[int]) -> str:
        status = "RUNNING" if self.running else "READY"
        action = "pause" if self.running else "start"
        det = sum([self.detected_a, self.detected_b, self.detected_c])
        return (f"Vision: {status}  Detected:{det}/3  "
                f"Tick:{self._ticks}  FOV:90°  Range:5 km  "
                f"Periph:10 m  [Space] {action}")


# ── Target spawner ──────────────────────────────────────────────────

def _spawn_target(w, zone: str, name: str,
                  x: float, y: float,
                  color: tuple, faction_group: str) -> int:
    """Spawn a stationary hostile target dummy."""
    eid = w.spawn()
    w.add(eid, Position(x=x, y=y, zone=zone))
    w.add(eid, Velocity())
    w.add(eid, Sprite(char=name[-1], color=color))
    w.add(eid, Identity(name=name, kind="npc"))
    w.add(eid, Collider())
    w.add(eid, Hurtbox())
    w.add(eid, Facing())
    w.add(eid, Health(current=200, maximum=200))
    w.add(eid, CombatStats(damage=0, defense=20))
    w.add(eid, Lod(level="high"))
    w.add(eid, Brain(kind="wander", active=False))
    w.add(eid, HomeRange(origin_x=x, origin_y=y, radius=0.5, speed=0.0))
    w.add(eid, Faction(group=faction_group, disposition="hostile",
                       home_disposition="hostile"))
    w.zone_add(eid, zone)
    return eid
