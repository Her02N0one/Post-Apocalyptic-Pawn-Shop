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

def draw_circle_alpha(surface: pygame.Surface, color: tuple,
                      cx: int, cy: int, radius: int):
    """Draw a semi-transparent filled circle."""
    if radius < 2:
        return
    r, g, b, a = color
    d = radius * 2 + 2
    cs = pygame.Surface((d, d), pygame.SRCALPHA)
    pygame.draw.circle(cs, (r, g, b, a), (d // 2, d // 2), radius)
    surface.blit(cs, (cx - d // 2, cy - d // 2))


def draw_cone_alpha(surface: pygame.Surface, color: tuple,
                    cx: int, cy: int, radius: int,
                    face_angle: float, half_fov: float,
                    steps: int = 24):
    """Draw a semi-transparent filled arc (vision cone wedge)."""
    if radius < 2:
        return
    r, g, b, a = color
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


def draw_diamond(surface: pygame.Surface, color: tuple,
                 cx: int, cy: int, size: int):
    """Draw a small diamond marker."""
    points = [(cx, cy - size), (cx + size, cy),
              (cx, cy + size), (cx - size, cy)]
    pygame.draw.polygon(surface, color, points, 2)


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
        w.add(eid, Threat(aggro_radius=8.0, leash_radius=15.0))
        w.add(eid, AttackConfig(attack_type="melee", range=1.2, cooldown=0.5))
    elif brain_kind == "hostile_ranged":
        w.add(eid, Threat(aggro_radius=12.0, leash_radius=20.0))
        w.add(eid, AttackConfig(attack_type="ranged", range=8.0, cooldown=0.6))
    w.zone_add(eid, zone)
    return eid


def spawn_combat_npc(app: App, zone: str, name: str, brain_kind: str,
                     x: float, y: float, color: tuple,
                     faction_group: str, *,
                     hp: int = 100, defense: int = 5,
                     damage: int = 10, aggro: float = 8.0,
                     atk_range: float = 1.2, cooldown: float = 0.5,
                     attack_type: str = "melee",
                     flee_threshold: float = 0.2,
                     speed: float = 2.0,
                     accuracy: float = 0.85,
                     proj_speed: float = 14.0,
                     fov_degrees: float = 120.0,
                     view_distance: float = 20.0,
                     peripheral_range: float = 5.0,
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
    w.add(eid, Threat(aggro_radius=aggro, leash_radius=30.0,
                      flee_threshold=flee_threshold))
    w.add(eid, AttackConfig(attack_type=attack_type, range=atk_range,
                            cooldown=cooldown, accuracy=accuracy,
                            proj_speed=proj_speed))
    w.add(eid, VisionCone(fov_degrees=fov_degrees,
                          view_distance=view_distance,
                          peripheral_range=peripheral_range))
    w.zone_add(eid, zone)
    return eid
