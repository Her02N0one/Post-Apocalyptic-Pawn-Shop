"""scenes/exhibits/helpers.py — Shared drawing and spawn utilities.

Used by multiple museum exhibits so they live here instead of being
duplicated across exhibit files.
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


# ── Drawing helpers ──────────────────────────────────────────────────

# Max pixel radius for FILLED alpha overlays (circles / cones).
# Kept small to avoid giant Surface allocations.  Wireframe outlines
# (used by draw_entity_vision_cones) are not capped by this.
_MAX_RENDER_PX = 500


def draw_circle_alpha(surface: pygame.Surface, color: tuple,
                      cx: int, cy: int, radius: int):
    """Draw a semi-transparent filled circle.

    Automatically downgrades to an outline if the radius is too large
    for a filled alpha Surface.
    """
    if radius < 2:
        return
    r, g, b, a = color
    if radius > _MAX_RENDER_PX:
        # Outline only — no giant Surface allocation
        pygame.draw.circle(surface, (r, g, b), (cx, cy), radius, 1)
        return
    d = radius * 2 + 2
    cs = pygame.Surface((d, d), pygame.SRCALPHA)
    pygame.draw.circle(cs, (r, g, b, a), (d // 2, d // 2), radius)
    surface.blit(cs, (cx - d // 2, cy - d // 2))


def draw_cone_alpha(surface: pygame.Surface, color: tuple,
                    cx: int, cy: int, radius: int,
                    face_angle: float, half_fov: float,
                    steps: int = 24):
    """Draw a semi-transparent filled arc (vision cone wedge).

    Falls back to a wireframe arc when the radius is too large.
    """
    if radius < 2:
        return
    r, g, b = color[:3]
    a = color[3] if len(color) > 3 else 40
    if radius > _MAX_RENDER_PX:
        # Wireframe fallback — arcs + edge lines, zero allocation
        _draw_cone_wireframe(surface, (r, g, b), cx, cy, radius,
                             face_angle, half_fov, steps)
        return
    pts = [(cx, cy)]
    for i in range(steps + 1):
        ang = face_angle - half_fov + (2 * half_fov) * i / steps
        pts.append((cx + int(math.cos(ang) * radius),
                     cy + int(math.sin(ang) * radius)))
    if len(pts) < 3:
        return
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    w = max_x - min_x + 2
    h = max_y - min_y + 2
    if w < 1 or h < 1:
        return
    s = pygame.Surface((w, h), pygame.SRCALPHA)
    local_pts = [(px - min_x + 1, py - min_y + 1) for px, py in pts]
    pygame.draw.polygon(s, (r, g, b, a), local_pts)
    surface.blit(s, (min_x - 1, min_y - 1))


def _draw_cone_wireframe(surface: pygame.Surface, color: tuple,
                         cx: int, cy: int, radius: int,
                         face_angle: float, half_fov: float,
                         steps: int = 24):
    """Draw a cone as edge lines + arc outline (no Surface allocation)."""
    # Edge lines
    for sign in (-1, 1):
        ang = face_angle + sign * half_fov
        ex = cx + int(math.cos(ang) * radius)
        ey = cy + int(math.sin(ang) * radius)
        pygame.draw.line(surface, color, (cx, cy), (ex, ey), 1)
    # Arc
    arc_pts: list[tuple[int, int]] = []
    for i in range(steps + 1):
        ang = face_angle - half_fov + (2 * half_fov) * i / steps
        arc_pts.append((cx + int(math.cos(ang) * radius),
                        cy + int(math.sin(ang) * radius)))
    if len(arc_pts) > 1:
        pygame.draw.lines(surface, color, False, arc_pts, 1)


def draw_diamond(surface: pygame.Surface, color: tuple,
                 cx: int, cy: int, size: int):
    """Draw a small diamond marker."""
    points = [(cx, cy - size), (cx + size, cy),
              (cx, cy + size), (cx - size, cy)]
    pygame.draw.polygon(surface, color, points, 2)


def draw_entity_vision_cones(surface: pygame.Surface, ox: int, oy: int,
                             app: App, eids: list[int], tile_px: int,
                             color: tuple = (255, 200, 50, 20)):
    """Draw lightweight vision cone indicators for all entities.

    Uses wireframe (arc + edge lines) instead of filled alpha surfaces
    so it stays fast even with realistic 5 km view distances.
    """
    from logic.ai.perception import facing_to_angle

    sw, sh = surface.get_size()
    r, g, b = color[:3]
    # Cap visual radius to half the screen diagonal — plenty to show direction
    max_vis = int(math.hypot(sw, sh) * 0.5) + 50

    for eid in eids:
        if not app.world.alive(eid):
            continue
        pos = app.world.get(eid, Position)
        facing = app.world.get(eid, Facing)
        cone = app.world.get(eid, VisionCone)
        if not pos or not facing or not cone:
            continue
        cx = ox + int(pos.x * tile_px) + tile_px // 2
        cy = oy + int(pos.y * tile_px) + tile_px // 2

        # Viewport cull — skip entities far off-screen
        if cx < -max_vis or cx > sw + max_vis or cy < -max_vis or cy > sh + max_vis:
            continue

        vel = app.world.get(eid, Velocity)
        if vel and (abs(vel.x) > 0.01 or abs(vel.y) > 0.01):
            face_angle = math.atan2(vel.y, vel.x)
        else:
            face_angle = facing_to_angle(facing.direction)

        half_fov = math.radians(cone.fov_degrees / 2.0)
        view_px = min(int(cone.view_distance * tile_px), max_vis)

        # Wireframe cone: edge lines + arc (no Surface allocation)
        for sign in (-1, 1):
            a = face_angle + sign * half_fov
            ex = cx + int(math.cos(a) * view_px)
            ey = cy + int(math.sin(a) * view_px)
            pygame.draw.line(surface, (r, g, b), (cx, cy), (ex, ey), 1)

        arc_pts: list[tuple[int, int]] = []
        for i in range(25):
            a = face_angle - half_fov + (2 * half_fov) * i / 24
            arc_pts.append((cx + int(math.cos(a) * view_px),
                            cy + int(math.sin(a) * view_px)))
        if len(arc_pts) > 1:
            pygame.draw.lines(surface, (r, g, b), False, arc_pts, 1)


# ── Spawn helpers ────────────────────────────────────────────────────

def spawn_npc(app: App, zone: str, name: str, brain_kind: str,
              x: float, y: float, color: tuple,
              faction_group: str = "neutral",
              disposition: str = "neutral") -> int:
    """Spawn a basic NPC with standard components."""
    w = app.world
    eid = w.spawn()
    w.add(eid, Position(x=x, y=y, zone=zone))
    w.add(eid, Velocity())
    w.add(eid, Sprite(char=name[0], color=color))
    w.add(eid, Identity(name=name, kind="npc"))
    w.add(eid, Collider())
    w.add(eid, Hurtbox())
    w.add(eid, Facing())
    w.add(eid, Health(current=100, maximum=100))
    w.add(eid, CombatStats(damage=10, defense=2))
    w.add(eid, Lod(level="high"))
    w.add(eid, Brain(kind=brain_kind, active=True))
    w.add(eid, HomeRange(origin_x=x, origin_y=y, radius=6.0, speed=2.0))
    w.add(eid, Faction(group=faction_group, disposition=disposition,
                       home_disposition=disposition))
    if brain_kind in ("guard", "hostile_melee"):
        w.add(eid, Threat(aggro_radius=5000.0, leash_radius=200.0))
        w.add(eid, AttackConfig(attack_type="melee", range=1.2, cooldown=0.5))
    elif brain_kind == "hostile_ranged":
        w.add(eid, Threat(aggro_radius=5000.0, leash_radius=200.0))
        w.add(eid, AttackConfig(attack_type="ranged", range=8.0, cooldown=0.6))
    w.zone_add(eid, zone)
    return eid


def spawn_combat_npc(app: App, zone: str, name: str, brain_kind: str,
                     x: float, y: float, color: tuple,
                     faction_group: str, *,
                     hp: int = 100, damage: int = 10, defense: int = 5,
                     aggro: float = 5000.0,
                     atk_range: float = 1.2, cooldown: float = 0.5,
                     attack_type: str = "melee",
                     flee_threshold: float = 0.2,
                     speed: float = 2.0,
                     accuracy: float = 0.85,
                     proj_speed: float = 14.0,
                     fov_degrees: float = 120.0,
                     view_distance: float = 5000.0,
                     peripheral_range: float = 10.0,
                     initial_facing: str = "down") -> int:
    """Spawn a combat-ready NPC with full stats and VisionCone."""
    w = app.world
    eid = w.spawn()
    w.add(eid, Position(x=x, y=y, zone=zone))
    w.add(eid, Velocity())
    w.add(eid, Sprite(char=name[0], color=color))
    w.add(eid, Identity(name=name, kind="npc"))
    w.add(eid, Collider())
    w.add(eid, Hurtbox())
    w.add(eid, Facing(direction=initial_facing))
    w.add(eid, Health(current=hp, maximum=hp))
    w.add(eid, CombatStats(damage=damage, defense=defense))
    w.add(eid, Lod(level="high"))
    w.add(eid, Brain(kind=brain_kind, active=True))
    w.add(eid, HomeRange(origin_x=x, origin_y=y, radius=12.0, speed=speed))
    w.add(eid, Faction(group=faction_group, disposition="hostile",
                       home_disposition="hostile"))
    w.add(eid, Threat(aggro_radius=aggro, leash_radius=200.0,
                      flee_threshold=flee_threshold))
    w.add(eid, AttackConfig(attack_type=attack_type, range=atk_range,
                            cooldown=cooldown, accuracy=accuracy,
                            proj_speed=proj_speed))
    w.add(eid, VisionCone(fov_degrees=fov_degrees,
                          view_distance=view_distance,
                          peripheral_range=peripheral_range))
    w.zone_add(eid, zone)
    return eid
