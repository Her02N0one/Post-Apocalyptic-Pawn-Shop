"""logic/goals.py — Priority-based goal system (Minecraft-style).

Each Goal implements five lifecycle hooks:

    can_start(world, eid, memory)  → bool
    can_continue(world, eid, memory) → bool
    start(world, eid, memory)
    tick(world, eid, memory, dt, game_time)
    stop(world, eid, memory)

The AI orchestrator evaluates goals lowest-priority-number first.
A goal that ``can_start`` preempts the current goal if it has a
strictly lower priority number. Goals at the same priority never
preempt each other.

Built-in goals
--------------
WanderGoal          — random walk within patrol radius
IdleGoal            — stand still, face random directions
AttackTargetGoal    — acquire + chase + attack (melee or ranged)
FleeGoal            — retreat when HP is low
ReturnHomeGoal      — pathfind back to patrol origin
EatGoal             — stand still while auto_eat_system consumes food
ForageGoal          — wander looking for food items
"""

from __future__ import annotations
import random
import math
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from core.ecs import World
from core.zone import is_passable
from components import (
    Position, Velocity, Patrol, Threat, AttackConfig,
    Health, Hunger, Inventory, Needs, Facing, HitFlash, Faction,
    GameClock,
)
from components.ai import Memory
from logic.pathfinding import find_path, path_next_waypoint
from logic.brains._helpers import (
    find_player, dist_pos, hp_ratio,
    move_toward, move_away, strafe, face_toward,
    should_engage, try_dodge, try_heal,
    reset_faction_on_return,
)


# ── Goal ABC ─────────────────────────────────────────────────────────

class Goal(ABC):
    """Abstract base for a priority-evaluated AI goal."""

    @abstractmethod
    def can_start(self, world: World, eid: int, memory: Memory) -> bool:
        """Return True if the goal's preconditions are met."""
        ...

    @abstractmethod
    def can_continue(self, world: World, eid: int, memory: Memory) -> bool:
        """Return True if the goal should keep running."""
        ...

    def start(self, world: World, eid: int, memory: Memory) -> None:
        """Called once when the goal becomes active."""

    @abstractmethod
    def tick(self, world: World, eid: int, memory: Memory,
             dt: float, game_time: float) -> None:
        """Called every AI frame while active."""
        ...

    def stop(self, world: World, eid: int, memory: Memory) -> None:
        """Called once when the goal is interrupted or completed."""


# ══════════════════════════════════════════════════════════════════════
#  BUILT-IN GOALS
# ══════════════════════════════════════════════════════════════════════


# ── Wander ───────────────────────────────────────────────────────────

class WanderGoal(Goal):
    """Random walk within patrol radius.  Always available as fallback."""

    def can_start(self, world, eid, memory):
        return world.has(eid, Patrol)

    def can_continue(self, world, eid, memory):
        return True  # wander indefinitely

    def start(self, world, eid, memory):
        memory.forget("_wander_timer")
        memory.forget("_wander_dir")

    def tick(self, world, eid, memory, dt, game_time):
        pos = world.get(eid, Position)
        vel = world.get(eid, Velocity)
        patrol = world.get(eid, Patrol)
        if not pos or not vel or not patrol:
            return

        timer = memory.get("_wander_timer", 0.0) - dt
        dx, dy = memory.get("_wander_dir", (0.0, 0.0))

        if timer <= 0:
            angle = random.uniform(0, 2 * math.pi)
            speed = random.uniform(patrol.speed * 0.3, patrol.speed)
            dx = speed * math.cos(angle)
            dy = speed * math.sin(angle)
            timer = random.uniform(1.0, 3.0)
            memory.set("_wander_dir", (dx, dy))

        memory.set("_wander_timer", timer)

        # Remember origin on first tick
        ox = patrol.origin_x or pos.x
        oy = patrol.origin_y or pos.y
        if patrol.origin_x == 0 and patrol.origin_y == 0:
            patrol.origin_x, patrol.origin_y = pos.x, pos.y
            ox, oy = pos.x, pos.y

        # Stay within patrol radius
        nx = pos.x + dx * dt
        ny = pos.y + dy * dt
        if (nx - ox) ** 2 + (ny - oy) ** 2 > patrol.radius ** 2:
            to_ox = ox - pos.x
            to_oy = oy - pos.y
            length = max(0.01, math.hypot(to_ox, to_oy))
            spd = patrol.speed * 0.5
            dx = (to_ox / length) * spd
            dy = (to_oy / length) * spd
            memory.set("_wander_dir", (dx, dy))
            memory.set("_wander_timer", random.uniform(0.5, 1.5))

        # Wall check
        if is_passable(pos.zone, pos.x + dx * dt, pos.y + dy * dt):
            vel.x, vel.y = dx, dy
        else:
            vel.x, vel.y = 0.0, 0.0
            memory.set("_wander_timer", 0.1)

    def stop(self, world, eid, memory):
        vel = world.get(eid, Velocity)
        if vel:
            vel.x, vel.y = 0.0, 0.0


# ── Idle ─────────────────────────────────────────────────────────────

class IdleGoal(Goal):
    """Stand still and occasionally change facing.  Lowest-priority."""

    def can_start(self, world, eid, memory):
        return True

    def can_continue(self, world, eid, memory):
        return True

    def tick(self, world, eid, memory, dt, game_time):
        vel = world.get(eid, Velocity)
        if vel:
            vel.x, vel.y = 0.0, 0.0

        # Random facing change every few seconds
        look_timer = memory.get("_look_timer", 0.0) - dt
        if look_timer <= 0:
            look_timer = random.uniform(2.0, 5.0)
            facing = world.get(eid, Facing)
            if facing:
                facing.direction = random.choice(["up", "down", "left", "right"])
        memory.set("_look_timer", look_timer)


# ── Attack Target ────────────────────────────────────────────────────

class AttackTargetGoal(Goal):
    """Acquire, chase, and attack a hostile target.

    Combines target acquisition from sensor data with chase and attack
    behaviour, driven by ``AttackConfig`` (melee vs ranged) and
    ``Threat`` (aggro/leash/flee thresholds).

    Memory keys read:
        ``nearest_hostile`` — (eid, x, y, dist) from NearestHostileSensor
        ``attacker``        — eid from HurtSensor

    Memory keys written:
        ``attack_target``   — eid of current target
        ``_atk_path``       — pathfinding waypoints
        ``_atk_mode``       — sub-state (chase / attack)
    """

    def can_start(self, world, eid, memory):
        if not should_engage(world, eid):
            return False
        if not world.has(eid, Threat) or not world.has(eid, AttackConfig):
            return False
        return memory.has("nearest_hostile") or memory.has("attacker")

    def can_continue(self, world, eid, memory):
        target_eid = memory.get("attack_target")
        if target_eid is None:
            return False
        if not world.alive(target_eid):
            return False
        # Leash check
        pos = world.get(eid, Position)
        patrol = world.get(eid, Patrol)
        if pos and patrol:
            ox = patrol.origin_x or pos.x
            oy = patrol.origin_y or pos.y
            if math.hypot(pos.x - ox, pos.y - oy) > (world.get(eid, Threat) or Threat()).leash_radius:
                return False
        return True

    def start(self, world, eid, memory):
        # Prefer attacker over nearest hostile
        attacker = memory.get("attacker")
        if attacker is not None and world.alive(attacker):
            memory.set("attack_target", attacker)
        else:
            nh = memory.get("nearest_hostile")
            if nh:
                memory.set("attack_target", nh[0])
        memory.set("_atk_mode", "chase")
        memory.forget("_atk_path")

    def tick(self, world, eid, memory, dt, game_time):
        from logic import combat_movement as cmove

        pos = world.get(eid, Position)
        vel = world.get(eid, Velocity)
        atk_cfg = world.get(eid, AttackConfig)
        threat = world.get(eid, Threat)
        patrol = world.get(eid, Patrol)
        if not pos or not vel or not atk_cfg:
            return

        target_eid = memory.get("attack_target")
        if target_eid is None:
            vel.x, vel.y = 0.0, 0.0
            return

        t_pos = world.get(target_eid, Position)
        if t_pos is None or t_pos.zone != pos.zone:
            memory.forget("attack_target")
            vel.x, vel.y = 0.0, 0.0
            return

        dist = dist_pos(pos, t_pos)
        is_ranged = atk_cfg.attack_type == "ranged"
        p_speed = patrol.speed if patrol else 2.0
        mode = memory.get("_atk_mode", "chase")

        # Movement state dict — shared with combat_movement functions
        if not memory.has("_mov"):
            memory.set("_mov", {})
        mov = memory.get("_mov")

        # ── Reactive defence (dodge / heal) ──────────────────────────
        from components import Brain
        brain = world.get(eid, Brain)
        if brain and mode in ("chase", "attack"):
            if try_dodge(world, eid, brain, pos, vel,
                         brain.state, dt, game_time):
                return
            try_heal(world, eid, brain, brain.state, game_time)

        # ── Sub-state transitions ────────────────────────────────────
        if mode == "chase":
            in_range = (dist <= atk_cfg.range if not is_ranged
                        else dist <= atk_cfg.range * 1.1)
            if in_range:
                mode = "attack"
                memory.set("_atk_mode", "attack")
                mov["melee_sub"] = "approach"
        elif mode == "attack":
            out_of_range = (dist > atk_cfg.range * 1.6 if not is_ranged
                            else dist > atk_cfg.range * 1.8)
            if out_of_range:
                mode = "chase"
                memory.set("_atk_mode", "chase")

        # ── Chase movement ───────────────────────────────────────────
        if mode == "chase":
            chase_mult = 1.2 if is_ranged else 1.4
            cmove.chase(pos, vel, t_pos.x, t_pos.y,
                        p_speed * chase_mult, mov, game_time)
            face_toward(world, eid, t_pos)

        # ── Attack behaviour ─────────────────────────────────────────
        elif mode == "attack":
            face_toward(world, eid, t_pos)

            # Fire / strike when cooldown elapsed
            if memory.get("_atk_cooldown", 0.0) <= game_time:
                if is_ranged:
                    from logic.combat import npc_ranged_attack
                    npc_ranged_attack(world, eid, target_eid)
                else:
                    from logic.combat import npc_melee_attack
                    npc_melee_attack(world, eid, target_eid)
                    mov["_melee_just_hit"] = True
                memory.set("_atk_cooldown", game_time + atk_cfg.cooldown)

            # Movement during attack (shared with combat_engagement)
            if is_ranged:
                cmove.ranged_attack(pos, vel, t_pos.x, t_pos.y, dist,
                                    atk_cfg.range, p_speed, mov, dt)
            else:
                cmove.melee_attack(pos, vel, t_pos.x, t_pos.y, dist,
                                   atk_cfg.range, p_speed, mov, dt)

    def stop(self, world, eid, memory):
        memory.forget("attack_target")
        memory.forget("_atk_mode")
        memory.forget("_atk_cooldown")
        memory.forget("_mov")
        vel = world.get(eid, Velocity)
        if vel:
            vel.x, vel.y = 0.0, 0.0
        reset_faction_on_return(world, eid)


# ── Flee ─────────────────────────────────────────────────────────────

class FleeGoal(Goal):
    """Run away from the threat source when HP is critically low."""

    def can_start(self, world, eid, memory):
        threat = world.get(eid, Threat)
        if not threat or threat.flee_threshold <= 0:
            return False
        return hp_ratio(world, eid) <= threat.flee_threshold

    def can_continue(self, world, eid, memory):
        threat = world.get(eid, Threat)
        if not threat:
            return False
        ratio = hp_ratio(world, eid)
        # Keep fleeing until HP recovers well past threshold
        return ratio <= threat.flee_threshold * 2.5

    def start(self, world, eid, memory):
        memory.forget("attack_target")
        memory.forget("_atk_path")

    def tick(self, world, eid, memory, dt, game_time):
        pos = world.get(eid, Position)
        vel = world.get(eid, Velocity)
        patrol = world.get(eid, Patrol)
        if not pos or not vel:
            return

        speed = (patrol.speed if patrol else 2.0) * 1.3

        # Flee from nearest hostile or attacker
        nh = memory.get("nearest_hostile")
        if nh:
            _, tx, ty, _ = nh
            move_away(pos, vel, tx, ty, speed)
        else:
            p_eid, p_pos = find_player(world)
            if p_pos and p_pos.zone == pos.zone:
                move_away(pos, vel, p_pos.x, p_pos.y, speed)
            else:
                vel.x, vel.y = 0.0, 0.0

    def stop(self, world, eid, memory):
        vel = world.get(eid, Velocity)
        if vel:
            vel.x, vel.y = 0.0, 0.0


# ── Return Home ──────────────────────────────────────────────────────

class ReturnHomeGoal(Goal):
    """Path back to the patrol origin after combat or getting lost."""

    # How far from origin to trigger return
    FAR_THRESHOLD = 3.0
    # How close counts as "home"
    HOME_THRESHOLD = 1.0

    def can_start(self, world, eid, memory):
        pos = world.get(eid, Position)
        patrol = world.get(eid, Patrol)
        if not pos or not patrol:
            return False
        ox = patrol.origin_x or pos.x
        oy = patrol.origin_y or pos.y
        return math.hypot(pos.x - ox, pos.y - oy) > self.FAR_THRESHOLD

    def can_continue(self, world, eid, memory):
        pos = world.get(eid, Position)
        patrol = world.get(eid, Patrol)
        if not pos or not patrol:
            return False
        ox = patrol.origin_x or pos.x
        oy = patrol.origin_y or pos.y
        return math.hypot(pos.x - ox, pos.y - oy) > self.HOME_THRESHOLD

    def start(self, world, eid, memory):
        memory.forget("_return_path")

    def tick(self, world, eid, memory, dt, game_time):
        pos = world.get(eid, Position)
        vel = world.get(eid, Velocity)
        patrol = world.get(eid, Patrol)
        if not pos or not vel or not patrol:
            return

        ox = patrol.origin_x or pos.x
        oy = patrol.origin_y or pos.y
        speed = patrol.speed * 1.2

        # Pathfind home
        path = memory.get("_return_path")
        repath_due = (game_time - memory.get("_return_path_time", 0.0)) > 1.0
        if path is None or repath_due:
            path = find_path(pos.zone, pos.x, pos.y, ox, oy, max_dist=40)
            memory.set("_return_path", path)
            memory.set("_return_path_time", game_time)

        if path:
            wp = path_next_waypoint(path, pos.x, pos.y)
            if wp:
                move_toward(pos, vel, wp[0], wp[1], speed)
            else:
                move_toward(pos, vel, ox, oy, speed)
        else:
            move_toward(pos, vel, ox, oy, speed)

    def stop(self, world, eid, memory):
        memory.forget("_return_path")
        memory.forget("_return_path_time")
        reset_faction_on_return(world, eid)
        vel = world.get(eid, Velocity)
        if vel:
            vel.x, vel.y = 0.0, 0.0


# ── Eat ──────────────────────────────────────────────────────────────

class EatGoal(Goal):
    """Stand still while auto_eat_system handles food consumption."""

    # Hunger ratio that triggers eating
    THRESHOLD = 0.4
    # How long to pause (auto_eat_system does the actual item removal)
    PAUSE = 2.0

    def can_start(self, world, eid, memory):
        hunger = world.get(eid, Hunger)
        if not hunger:
            return False
        ratio = hunger.current / max(hunger.maximum, 0.01)
        if ratio >= self.THRESHOLD:
            return False
        inv = world.get(eid, Inventory)
        return inv is not None and len(inv.items) > 0

    def can_continue(self, world, eid, memory):
        eat_until = memory.get("_eat_until", 0.0)
        clock = world.res(GameClock)
        if clock and clock.time < eat_until:
            return True
        return False

    def start(self, world, eid, memory):
        clock = world.res(GameClock)
        gt = clock.time if clock else 0.0
        memory.set("_eat_until", gt + self.PAUSE)

    def tick(self, world, eid, memory, dt, game_time):
        vel = world.get(eid, Velocity)
        if vel:
            vel.x, vel.y = 0.0, 0.0

    def stop(self, world, eid, memory):
        memory.forget("_eat_until")


# ── Forage ───────────────────────────────────────────────────────────

class ForageGoal(Goal):
    """Wander looking for food (placeholder for a real loot-search)."""

    MAX_DURATION = 12.0

    def can_start(self, world, eid, memory):
        hunger = world.get(eid, Hunger)
        if not hunger:
            return False
        ratio = hunger.current / max(hunger.maximum, 0.01)
        if ratio >= EatGoal.THRESHOLD:
            return False
        inv = world.get(eid, Inventory)
        # Trigger forage only when inventory has no food
        return inv is None or len(inv.items) == 0

    def can_continue(self, world, eid, memory):
        forage_until = memory.get("_forage_until", 0.0)
        clock = world.res(GameClock)
        return clock is not None and clock.time < forage_until

    def start(self, world, eid, memory):
        clock = world.res(GameClock)
        gt = clock.time if clock else 0.0
        memory.set("_forage_until", gt + random.uniform(8.0, self.MAX_DURATION))
        memory.forget("_wander_timer")

    def tick(self, world, eid, memory, dt, game_time):
        # Reuse wander logic — forage is just walking around
        pos = world.get(eid, Position)
        vel = world.get(eid, Velocity)
        patrol = world.get(eid, Patrol)
        if not pos or not vel or not patrol:
            return

        timer = memory.get("_wander_timer", 0.0) - dt
        dx, dy = memory.get("_wander_dir", (0.0, 0.0))

        if timer <= 0:
            angle = random.uniform(0, 2 * math.pi)
            speed = random.uniform(patrol.speed * 0.4, patrol.speed * 0.8)
            dx = speed * math.cos(angle)
            dy = speed * math.sin(angle)
            timer = random.uniform(1.5, 3.0)
            memory.set("_wander_dir", (dx, dy))

        memory.set("_wander_timer", timer)

        ox = patrol.origin_x or pos.x
        oy = patrol.origin_y or pos.y
        nx = pos.x + dx * dt
        ny = pos.y + dy * dt
        if (nx - ox) ** 2 + (ny - oy) ** 2 > patrol.radius ** 2:
            to_ox = ox - pos.x
            to_oy = oy - pos.y
            length = max(0.01, math.hypot(to_ox, to_oy))
            spd = patrol.speed * 0.5
            dx = (to_ox / length) * spd
            dy = (to_oy / length) * spd
            memory.set("_wander_dir", (dx, dy))
            memory.set("_wander_timer", random.uniform(0.5, 1.5))

        if is_passable(pos.zone, pos.x + dx * dt, pos.y + dy * dt):
            vel.x, vel.y = dx, dy
        else:
            vel.x, vel.y = 0.0, 0.0
            memory.set("_wander_timer", 0.1)

    def stop(self, world, eid, memory):
        memory.forget("_forage_until")
        vel = world.get(eid, Velocity)
        if vel:
            vel.x, vel.y = 0.0, 0.0



