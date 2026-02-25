"""core.transition — Screen-fade + portal transition logic.

Extracted from ``core.session`` to keep the Session class focused on
data-pipeline lifecycle (zone loading, save/load).

Classes
-------
TransitionMixin
    Mixed into Session.  Provides ``check_portals()``,
    ``update_transition()``, and ``_execute_teleport()``.
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from core.types import Direction
from components import (
    Player, Position, Velocity, Facing,
)
from systems.spawner import spawn_zone_entities
from systems.lod import sync_zone_lod

if TYPE_CHECKING:
    from core.ecs import World


class TransitionMixin:
    """Portal checking, screen-fade, and auto-walk logic.

    Expects the host class to provide:
    - ``world: World``
    - ``zone_name: str``
    - ``auto_walk_*`` attributes
    - ``fade_alpha``, ``_fade_direction``, ``_fade_speed``
    - ``_pending_teleport``
    - ``_portal_map``, ``_portal_arrival``
    - ``_load_zone_template(name) -> Zone``
    - ``visited_zones: set[str]``
    - ``status``, ``status_timer``
    """

    # ── Direction helpers ────────────────────────────────────────

    _DIR_DELTA: dict[str, tuple[float, float]] = {
        "up":    ( 0.0, -1.0),
        "down":  ( 0.0,  1.0),
        "left":  (-1.0,  0.0),
        "right": ( 1.0,  0.0),
    }

    _DIR_ENUM: dict[str, Direction] = {
        "up":    Direction.UP,
        "down":  Direction.DOWN,
        "left":  Direction.LEFT,
        "right": Direction.RIGHT,
    }

    _OPPOSITE_DIR: dict[str, str] = {
        "up":    "down",
        "down":  "up",
        "left":  "right",
        "right": "left",
    }

    # ── Portal checking ──────────────────────────────────────────

    def check_portals(self, dt: float = 0.0) -> bool:
        """If the player is standing on a portal tile, begin transition.

        Returns True if a zone-change sequence was *started* (fade-out).
        The actual teleport happens when the fade completes.
        """
        if self.auto_walk_active or self._fade_direction != 0:
            return False

        result = self.world.query_one(Player, Position)
        if not result:
            return False
        eid, _, pos = result
        r = int(pos.y)
        c = int(pos.x)
        key = (r, c)

        if self._portal_arrival is not None and key != self._portal_arrival:
            self._portal_arrival = None

        if key == self._portal_arrival:
            return False

        if key not in self._portal_map:
            return False

        target_zone, target_r, target_c, exit_dir = self._portal_map[key]

        self._pending_teleport = (target_zone, target_r, target_c, exit_dir)
        self._fade_direction = 1
        return True

    def update_transition(self, dt: float) -> None:
        """Tick the fade and auto-walk state.  Call from scene.update()."""
        # ── Screen fade ──────────────────────────────────────────
        if self._fade_direction != 0:
            self.fade_alpha += self._fade_direction * self._fade_speed * dt
            if self._fade_direction == 1 and self.fade_alpha >= 1.0:
                self.fade_alpha = 1.0
                if self._pending_teleport:
                    self._execute_teleport(*self._pending_teleport)
                    self._pending_teleport = None
                self._fade_direction = -1
            elif self._fade_direction == -1 and self.fade_alpha <= 0.0:
                self.fade_alpha = 0.0
                self._fade_direction = 0

        # ── Auto-walk ────────────────────────────────────────────
        if self.auto_walk_active:
            self.auto_walk_timer -= dt
            if self.auto_walk_timer <= 0:
                self.auto_walk_active = False
                self.auto_walk_timer = 0.0
                for _, _, vel in self.world.query(Player, Velocity):
                    vel.x = 0.0
                    vel.y = 0.0
            else:
                result = self.world.query_one(Player, Velocity)
                if result:
                    _, _, vel = result
                    speed = 4.0
                    vel.x = self.auto_walk_dx * speed
                    vel.y = self.auto_walk_dy * speed

    def _execute_teleport(self, target_zone: str, target_r: float,
                          target_c: float, exit_dir: str) -> None:
        """Move the player to the destination zone + start auto-walk."""
        try:
            zd = self._load_zone_template(target_zone)
        except (FileNotFoundError, ValueError) as exc:
            print(f"[SESSION] Teleport failed — cannot load '{target_zone}': {exc}")
            self._fade_direction = -1
            return

        if target_zone not in self.visited_zones:
            spawned = spawn_zone_entities(self.world, zd.entities, target_zone)
            print(f"[SESSION] First visit to '{target_zone}' — "
                  f"spawned {len(spawned)} entities")
        self.visited_zones.add(target_zone)

        sync_zone_lod(self.world, target_zone)

        result = self.world.query_one(Player, Position)
        if not result:
            return
        _, _, pos = result
        pos.x = target_c + 0.5
        pos.y = target_r + 0.5
        pos.zone = target_zone

        dest_r = int(pos.y)
        dest_c = int(pos.x)
        self._portal_arrival = (dest_r, dest_c)

        dest_key = (dest_r, dest_c)
        if dest_key in self._portal_map:
            arrival_dir = self._portal_map[dest_key][3]
        else:
            arrival_dir = exit_dir

        direction = self._DIR_ENUM.get(arrival_dir, Direction.UP)
        for _, _, facing in self.world.query(Player, Facing):
            facing.direction = direction

        dx, dy = self._DIR_DELTA.get(arrival_dir, (0.0, -1.0))
        self.auto_walk_active = True
        self.auto_walk_duration = 0.6
        self.auto_walk_timer = self.auto_walk_duration
        self.auto_walk_dx = dx
        self.auto_walk_dy = dy

        self.status = f"Entered {target_zone}"
        self.status_timer = 1.5
