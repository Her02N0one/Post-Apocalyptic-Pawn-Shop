"""scenes/world/firstperson.py — First-person raycasted subzone view.

Renders the same tile grid and ECS entities as TopDown, but from a
Wolfenstein / Doom-style first-person perspective using raycasting.

Controls:
    W / S          — move forward / backward
    A / D          — strafe left / right
    Left / Right   — turn camera (or hold right mouse button + drag)
    E              — interact with nearest entity
    I              — open inventory
    Tab            — toggle debug overlay / minimap
    Escape         — pause menu
    Backspace      — return to top-down view
    F5 / F9        — save / load

The scene reads tiles and entities from the shared ``Session`` and
never creates or loads data itself.
"""

from __future__ import annotations

import math

import pygame

from core.app import App
from core.tiles import SOLID_IDS, HALF_WALL_IDS, PLATFORM_IDS, DOOR_IDS, TILE_COLORS
from core.scene import Scene
from core.types import Direction, EntityKind
from components import (
    Position, Velocity, Sprite, Player, Facing,
    Health, Identity, Inventory, Camera, GameClock,
    WorldClock, TileEntity, WorldEventLog,
)
from systems.physics import movement_system
from systems.interaction import try_interact, nearest_interactable, set_camera_angle
from systems.raycaster import (
    cast_walls, project_entities, build_zbuffer,
)
from systems.textures import TextureAtlas, TEX_SIZE
from systems.item_registry import ItemRegistry
from ui.modal import ModalStack
from ui.commands import CloseModal, HealPlayer
from ui.inventory_modal import InventoryModal
from ui.transfer_modal import TransferModal

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.session import Session

# ── Constants ────────────────────────────────────────────────────────
FOV = math.pi / 3          # 60° horizontal field of view
TURN_SPEED = 3.5           # radians / second (target)
TURN_ACCEL = 18.0          # how fast keyboard turn ramps up
TURN_FRICTION = 12.0       # how fast keyboard turn decays
MOUSE_SENSITIVITY = 0.004  # radians / px of mouse movement
RAY_STEP = 2               # cast every Nth column (1 = full res)
HEAD_BOB_SPEED = 8.0       # bob cycles per second when walking
HEAD_BOB_AMP = 4.0         # pixels of vertical bob
MOVE_ACCEL = 18.0          # acceleration (tiles/s²)
MOVE_FRICTION = 10.0       # deceleration when no input
SPRINT_MULTIPLIER = 1.6    # speed boost while sprinting
SPRINT_BOB_MULT = 1.4      # head bob speed/amp boost while sprinting
SPRINT_FOV_BOOST = 0.08    # radians added to FOV when sprinting
DAMAGE_FLASH_DUR = 0.3     # seconds for red damage flash
SWAY_AMOUNT = 2.0          # pixels of horizontal sway when turning
SWAY_DECAY = 8.0           # how fast sway returns to center

# Ceiling / floor colours (base — tinted by day/night)
_CEILING_DAY = (60, 70, 100)
_CEILING_NIGHT = (10, 10, 25)
_FLOOR_DAY = (50, 50, 45)
_FLOOR_NIGHT = (20, 20, 18)
_FOG_RATE = 14             # higher = fog kicks in sooner
_FOG_RATE_NIGHT = 20       # denser fog at night
_GRAD_BANDS = 24           # bands for ceiling/floor gradient

# Billboard texture map — character → color offset for shape rendering
_PROP_GLYPHS: dict[str, str] = {
    "\u2261": "shelf",      # ≡ Shelf
    "\u25a1": "crate",      # □ Crate
    "\u25a0": "safe",       # ■ Safe
    "\u2550": "table",      # ═ Table
    "\u2592": "bookshelf",  # ▒ Bookcase
    "O": "barrel",
}

# Per-glyph visual properties: (height_scale, width_scale, is_billboard)
# height/width are proportions of full wall height at distance (1.0 = wall).
# is_billboard True  → always faces the camera (NPCs / round objects).
# is_billboard False → width narrows when viewed from the side (flat furniture).
_ENTITY_VIS: dict[str, tuple[float, float, bool]] = {
    # NPCs — billboard (always face camera)
    "D": (0.75, 0.50, True),       # Dummy / Mannequin
    "N": (0.75, 0.50, True),       # NPC
    "M": (0.75, 0.50, True),       # Merchant
    "V": (0.75, 0.50, True),       # Villager
    # Round / symmetric objects — billboard
    "O": (0.45, 0.45, True),       # Barrel
    "\u2606": (0.25, 0.20, True),  # ☆ Lantern
    "\u2698": (0.40, 0.35, True),  # ⚘ Potted Plant
    "#": (0.30, 0.30, True),       # Crop
    "*": (0.15, 0.20, True),       # Ground item
    "C": (0.45, 0.45, True),       # Generic container
    # Flat furniture — facing-aware
    "\u2261": (0.60, 0.70, False), # ≡ Shelf
    "\u25a1": (0.40, 0.45, False), # □ Crate
    "\u25a0": (0.35, 0.40, False), # ■ Safe
    "\u2550": (0.35, 0.65, False), # ═ Table
    "\u2592": (0.70, 0.55, False), # ▒ Bookcase
    "h": (0.40, 0.35, False),      # Chair
    "\u2500": (0.35, 0.75, False), # ─ Counter
}
_DEFAULT_VIS: tuple[float, float, bool] = (0.60, 0.50, True)

# Facing direction → raycaster angle (radians)
_FACE_ANGLES: dict[Direction, float] = {
    Direction.UP:    math.pi * 1.5,  # north
    Direction.DOWN:  math.pi * 0.5,  # south
    Direction.LEFT:  math.pi,        # west
    Direction.RIGHT: 0.0,            # east
}


def _lerp_color(a: tuple[int, int, int], b: tuple[int, int, int],
                t: float) -> tuple[int, int, int]:
    """Interpolate between two colors."""
    return (
        int(a[0] + (b[0] - a[0]) * t),
        int(a[1] + (b[1] - a[1]) * t),
        int(a[2] + (b[2] - a[2]) * t),
    )


def _day_night_factor(wc) -> float:  # type: ignore[type-arg]
    """Return 0.0 (full night) to 1.0 (full day) based on WorldClock."""
    if wc is None:
        return 1.0
    p = wc.day_phase
    if 0.30 <= p < 0.70:
        return 1.0
    if p < 0.20 or p >= 0.85:
        return 0.0
    if 0.20 <= p < 0.30:
        return (p - 0.20) / 0.10
    if 0.70 <= p < 0.85:
        return 1.0 - (p - 0.70) / 0.15
    return 1.0


# Gradient surface cache — keyed on (sw, sh, dn_quantized)
_gradient_cache: dict[tuple[int, int, int], pygame.Surface] = {}


def _draw_gradient(surface: pygame.Surface, sw: int, sh: int,
                   dn_factor: float = 1.0) -> None:
    """Gradient ceiling/floor — cached when dn doesn't change much."""
    dn_q = int(dn_factor * 20)  # quantise to 5% steps
    key = (sw, sh, dn_q)
    cached = _gradient_cache.get(key)
    if cached is None:
        cached = pygame.Surface((sw, sh))
        ceiling = _lerp_color(_CEILING_NIGHT, _CEILING_DAY, dn_factor)
        floor = _lerp_color(_FLOOR_NIGHT, _FLOOR_DAY, dn_factor)
        half = sh // 2
        band_h = max(1, half // _GRAD_BANDS + 1)
        for i in range(_GRAD_BANDS):
            t = i / _GRAD_BANDS
            cr = int(ceiling[0] * (0.3 + 0.7 * t))
            cg = int(ceiling[1] * (0.3 + 0.7 * t))
            cb = int(ceiling[2] * (0.3 + 0.7 * t))
            y = int(t * half)
            pygame.draw.rect(cached, (cr, cg, cb), (0, y, sw, band_h))
            fr = int(floor[0] * (1.0 - 0.5 * t))
            fg = int(floor[1] * (1.0 - 0.5 * t))
            fb = int(floor[2] * (1.0 - 0.5 * t))
            y = half + int(t * half)
            pygame.draw.rect(cached, (fr, fg, fb), (0, y, sw, band_h))
        # Keep cache small — only last 4 entries
        if len(_gradient_cache) > 4:
            _gradient_cache.clear()
        _gradient_cache[key] = cached
    surface.blit(cached, (0, 0))


# Fog brightness LUT — indexed by quantized distance (0..255)
_FOG_LUT_SIZE = 256
_fog_lut_cache: dict[tuple[int, float], list[int]] = {}


def _build_fog_lut(ambient: int, dn: float) -> list[int]:
    """Pre-compute fog brightness for 256 distance steps."""
    key = (ambient, round(dn, 2))
    lut = _fog_lut_cache.get(key)
    if lut is not None:
        return lut
    lut = [0] * _FOG_LUT_SIZE
    _exp = math.exp
    for i in range(_FOG_LUT_SIZE):
        dist = i * 0.125  # maps 0..255 → 0..32 tile distance
        dist_norm = dist / 16.0
        fog_exp = max(40, min(ambient, int(ambient * _exp(-dist_norm * 1.8))))
        fog = int(fog_exp * (0.4 + 0.6 * dn))
        lut[i] = max(20, min(255, fog))
    if len(_fog_lut_cache) > 8:
        _fog_lut_cache.clear()
    _fog_lut_cache[key] = lut
    return lut


class FirstPerson(Scene):
    """First-person raycasted view — renders the same world as TopDown."""

    def __init__(self, session: "Session") -> None:
        self.session = session
        self.player_angle: float = math.pi * 1.5  # facing "up" (north)
        self.show_debug = False
        self._mouse_captured = False
        self._atlas = TextureAtlas()
        self._font_cache: dict[int, pygame.font.Font] = {}
        self._registry = ItemRegistry()
        self.modals = ModalStack()
        # Prop texture atlas for billboard rendering
        self._prop_surfaces: dict[str, pygame.Surface] = {}
        # Head bob
        self._bob_timer: float = 0.0
        self._bob_offset: float = 0.0
        # Smooth movement
        self._move_vx: float = 0.0
        self._move_vy: float = 0.0
        # Smooth turning
        self._turn_vel: float = 0.0
        # Sprint state
        self._sprinting: bool = False
        self._sprint_fov: float = 0.0  # smoothed FOV boost
        # Damage flash
        self._damage_flash: float = 0.0
        self._last_hp: float = -1.0
        # View sway (parallax when turning)
        self._sway_offset: float = 0.0
        # Step counter for footstep visual
        self._step_phase: float = 0.0
        self._last_step_side: int = 0  # alternates 0/1
        # Zone tracking for cache invalidation
        self._cached_zone: str = ""
        # Rendering caches
        self._strip_cache: dict[tuple, pygame.Surface] = {}
        self._mm_base: pygame.Surface | None = None
        self._mm_zone: str = ""
        self._mm_tiles_hash: int = 0

    # ── Lifecycle ─────────────────────────────────────────────────

    def on_enter(self, app: App) -> None:
        # Sync angle from current Facing direction
        result = app.world.query_one(Player, Facing)
        if result:
            _, _, facing = result
            self.player_angle = _direction_to_angle(facing.direction)

        if not app.world.resources.has(Camera):
            app.world.resources.set(Camera())
        if not app.world.resources.has(GameClock):
            app.world.resources.set(GameClock())

        # Capture mouse for free-look by default in FP mode
        pygame.event.set_grab(True)
        pygame.mouse.set_visible(False)
        self._mouse_captured = True

        # Register camera angle for interaction system
        set_camera_angle(self.player_angle)

        # Reset motion / visual state to avoid stale momentum on re-entry
        self._move_vx = 0.0
        self._move_vy = 0.0
        self._turn_vel = 0.0
        self._sway_offset = 0.0
        self._sprint_fov = 0.0
        self._sprinting = False
        self._bob_timer = 0.0
        self._bob_offset = 0.0

        # Snapshot HP for damage flash detection
        hp_res = app.world.query_one(Player, Health)
        if hp_res:
            self._last_hp = hp_res[2].current

        # Clear strip cache on zone change
        if self._cached_zone != self.session.zone_name:
            self._strip_cache.clear()
            self._cached_zone = self.session.zone_name

    def on_exit(self, app: App) -> None:
        # Sync facing direction back to the Facing component
        result = app.world.query_one(Player, Facing)
        if result:
            _, _, facing = result
            facing.direction = _angle_to_direction(self.player_angle)

        # Zero out velocity so TopDown doesn't inherit angle-based momentum
        # (but skip if auto-walk is running — TopDown will continue it)
        if not self.session.auto_walk_active:
            for _, _, vel in app.world.query(Player, Velocity):
                vel.x = 0.0
                vel.y = 0.0

        # Clear camera angle so TopDown uses Facing again
        set_camera_angle(None)

        # Always release mouse on exit
        pygame.event.set_grab(False)
        pygame.mouse.set_visible(True)
        self._mouse_captured = False

    # ── Events ────────────────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event, app: App) -> None:
        # Modal events first
        if self.modals.is_open:
            cmds = self.modals.handle_event(event)
            for cmd in cmds:
                if isinstance(cmd, CloseModal):
                    self.modals.pop()
                elif isinstance(cmd, HealPlayer):
                    res = app.world.query_one(Player, Health)
                    if res:
                        _, _, hp = res
                        hp.current = min(hp.maximum, hp.current + cmd.amount)
            return

        # Block input during transitions
        if self.session.auto_walk_active or self.session._fade_direction != 0:
            return
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                # Always release mouse + open pause in one press
                if self._mouse_captured:
                    pygame.event.set_grab(False)
                    pygame.mouse.set_visible(True)
                    self._mouse_captured = False
                from scenes.pause_menu import PauseMenu
                app.push_scene(PauseMenu(self.session))
            elif event.key == pygame.K_TAB:
                self.show_debug = not self.show_debug
            elif event.key == pygame.K_e:
                self._do_interact(app)
            elif event.key == pygame.K_i:
                self._open_inventory(app)
            elif event.key == pygame.K_F5:
                self.session.save()
            elif event.key == pygame.K_F9:
                self.session.load()
            elif event.key == pygame.K_F4:
                from scenes.editor import MapEditor
                app.push_scene(MapEditor(self.session.zone_name))
            elif event.key == pygame.K_BACKSPACE:
                app.pop_scene()  # return to top-down view
            elif event.key == pygame.K_PERIOD:
                self._cycle_time_scale(app, 1)
            elif event.key == pygame.K_COMMA:
                self._cycle_time_scale(app, -1)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            # Click to re-capture mouse for free-look
            if not self._mouse_captured:
                pygame.event.set_grab(True)
                pygame.mouse.set_visible(False)
                self._mouse_captured = True
        elif event.type == pygame.MOUSEMOTION and self._mouse_captured:
            dx = event.rel[0] * MOUSE_SENSITIVITY
            self.player_angle += dx
            # View sway — turning creates a brief parallax lean
            self._sway_offset += dx * 80.0

    def _cycle_time_scale(self, app: App, direction: int) -> None:
        """Cycle WorldClock.time_scale up (+1) or down (-1)."""
        wc = app.world.resources.try_get(WorldClock)
        if not wc:
            return
        scales = wc.TIME_SCALES
        try:
            idx = scales.index(wc.time_scale)
        except ValueError:
            idx = 0
        idx = max(0, min(len(scales) - 1, idx + direction))
        wc.time_scale = scales[idx]
        if wc.time_scale == 1.0:
            self.session.status = "Normal speed"
        else:
            self.session.status = f"Fast-forward {int(wc.time_scale)}×"
        self.session.status_timer = 1.5

    def _do_interact(self, app: App) -> None:
        """Handle E key — interact with the nearest entity.

        Priority: tile entities (containers → pickup ground items),
        then NPC dialogue, then generic interaction.
        """
        found = nearest_interactable(app.world)
        if found:
            t_eid, _ = found
            te = app.world.get(t_eid, TileEntity)
            if te:
                if te.tile_type == "container":
                    self._open_container(app, t_eid, te)
                    return
                elif te.tile_type == "ground_item":
                    self._pickup_ground_item(app, t_eid, te)
                    return

            # NPC dialogue
            ident = app.world.get(t_eid, Identity)
            if ident and ident.kind == EntityKind.NPC:
                self._open_npc_dialogue(app, t_eid)
            elif try_interact(app.world, app.world.events):
                name = ident.name if ident else "???"
                self.session.status = f"Interacted with {name}"
                self.session.status_timer = 1.5
        else:
            # No entity — check if looking at a PLATFORM tile
            if self._try_platform_interact(app):
                return
            self.session.status = "Nothing nearby"
            self.session.status_timer = 1.0

    def _open_npc_dialogue(self, app: App, npc_eid: int) -> None:
        """Open a contextual dialogue modal for an NPC."""
        from systems.dialogue_gen import build_npc_dialogue
        from ui.dialogue_modal import DialogueModal

        ident = app.world.get(npc_eid, Identity)
        npc_name = ident.name if ident else "???"
        tree = build_npc_dialogue(app.world, npc_eid)
        self.modals.push(DialogueModal(tree, npc_name=npc_name, npc_eid=npc_eid))

    # ── Inventory ─────────────────────────────────────────────────

    def _open_inventory(self, app: App) -> None:
        """Open the player inventory modal."""
        res = app.world.query_one(Player, Inventory)
        if not res:
            p_res = app.world.query_one(Player, Position)
            if not p_res:
                return
            p_eid = p_res[0]
            inv = Inventory(items={})
            app.world.add(p_eid, inv)
        else:
            p_eid, _, inv = res

        def on_drop(item_id: str, qty: int) -> None:
            self._spawn_ground_item(app, item_id, qty)

        self.modals.push(InventoryModal(
            player_inv=inv.items,
            registry=self._registry,
            on_drop=on_drop,
        ))

    def _spawn_ground_item(self, app: App, item_id: str, qty: int) -> None:
        """Spawn a ground item entity near the player."""
        from systems.spawner import spawn_from_descriptor
        res = app.world.query_one(Player, Position)
        if not res:
            return
        _, _, p_pos = res
        desc = self._registry.to_descriptor(item_id)
        col = int(p_pos.x)
        row = int(p_pos.y)
        desc["position"] = {"x": float(col) + 0.5, "y": float(row) + 0.5}
        desc["id"] = f"ground_{item_id}_{id(desc)}"
        desc.setdefault("tile_entity", {})
        desc["tile_entity"]["item_id"] = item_id
        desc["tile_entity"]["item_qty"] = qty
        desc["tile_entity"]["tile_type"] = "ground_item"
        desc["tile_entity"]["tiles"] = [[row, col]]
        spawn_from_descriptor(app.world, desc, self.session.zone_name)

    def _pickup_ground_item(self, app: App, eid: int, te: TileEntity) -> None:
        """Pick up a ground item entity, adding it to player inventory."""
        res = app.world.query_one(Player, Inventory)
        if not res:
            return
        _, _, inv = res
        item_id = te.item_id
        qty = max(1, te.item_qty)
        if item_id:
            inv.items[item_id] = inv.items.get(item_id, 0) + qty
        ident = app.world.get(eid, Identity)
        name = ident.name if ident else item_id
        self.session.status = f"Picked up {name}" + (f" x{qty}" if qty > 1 else "")
        self.session.status_timer = 1.5
        app.world.kill(eid)

    # ── Container interaction ─────────────────────────────────────

    def _open_container(self, app: App, eid: int, te: TileEntity) -> None:
        """Open a container tile entity for transfer."""
        res = app.world.query_one(Player, Inventory)
        if not res:
            return
        _, _, p_inv = res
        container_inv = app.world.get(eid, Inventory)
        if container_inv is None:
            container_inv = Inventory(items={})
            app.world.add(eid, container_inv)
        if te.loot_table and not te.looted:
            container_inv.items.update(self._roll_loot(te.loot_table))
            te.looted = True
        ident = app.world.get(eid, Identity)
        title = ident.name if ident else "Container"
        self.modals.push(TransferModal(
            player_inv=p_inv.items,
            container_inv=container_inv.items,
            registry=self._registry,
            container_title=title,
        ))

    def _try_platform_interact(self, app: App) -> bool:
        """Check if the player is facing a PLATFORM tile and open it
        as a surface container (table, counter, etc.)."""
        result = app.world.query_one(Player, Position)
        if not result:
            return False
        _, _, p_pos = result
        # Step forward in look direction to find the tile
        cos_a = math.cos(self.player_angle)
        sin_a = math.sin(self.player_angle)
        for dist in (0.8, 1.2, 1.6):
            tx = int(p_pos.x + cos_a * dist)
            ty = int(p_pos.y + sin_a * dist)
            tiles = self.session.tiles
            if not tiles:
                return False
            mh = len(tiles)
            mw = len(tiles[0]) if mh else 0
            if 0 <= ty < mh and 0 <= tx < mw:
                tid = tiles[ty][tx]
                if tid in PLATFORM_IDS:
                    eid = self._get_platform_entity(app, tx, ty, tid)
                    te = app.world.get(eid, TileEntity)
                    self._open_container(app, eid, te)
                    return True
        return False

    def _get_platform_entity(self, app: App, col: int, row: int,
                             tid: int) -> int:
        """Find or create an entity for a platform tile at (col, row).

        The same tile always maps to the same entity so its inventory
        persists.
        """
        from core.tiles import tile_def as _tile_def
        zone = self.session.zone_name
        # Check existing entities for one at this tile
        for eid, pos, te in app.world.query(Position, TileEntity):
            if (pos.zone == zone
                    and te.tile_type == "platform_surface"
                    and te.tiles == [[row, col]]):
                return eid
        # Create a new platform surface entity
        td = _tile_def(tid)
        name = td.name if td else "Surface"
        eid = app.world.spawn()
        app.world.add(eid, Position(x=col + 0.5, y=row + 0.5, zone=zone))
        app.world.add(eid, Identity(name=name, kind=EntityKind.OBJECT))
        app.world.add(eid, TileEntity(
            tile_type="platform_surface",
            tiles=[[row, col]],
        ))
        app.world.add(eid, Inventory(items={}))
        return eid

    def _roll_loot(self, table_id: str) -> dict[str, int]:
        """Roll a loot table and return item dict."""
        import random as _rnd
        try:
            try:
                import tomllib
            except ModuleNotFoundError:
                import tomli as tomllib  # type: ignore[no-redef]
            from pathlib import Path
            path = Path(__file__).resolve().parent.parent.parent / "data" / "loot_tables.toml"
            with open(path, "rb") as f:
                data = tomllib.load(f)
            table = data.get("tables", {}).get(table_id)
            if not table:
                return {}
            items: dict[str, int] = {}
            for pool in table.get("pools", []):
                rolls = int(pool.get("rolls", 1))
                bonus = pool.get("bonus_rolls", 0)
                if bonus:
                    rolls += int(_rnd.random() * bonus)
                entries = pool.get("entries", [])
                if not entries:
                    continue
                weights = [e.get("weight", 1) for e in entries]
                for _ in range(rolls):
                    chosen = _rnd.choices(entries, weights=weights, k=1)[0]
                    item = chosen.get("item", "")
                    lo = chosen.get("min_count", 1)
                    hi = chosen.get("max_count", 1)
                    count = _rnd.randint(lo, hi)
                    items[item] = items.get(item, 0) + count
            return items
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("_roll_loot(%s) failed: %s", table_id, exc)
            return {}

    # ── Update ────────────────────────────────────────────────────

    def update(self, dt: float, app: App) -> None:
        # Modal ticking
        if self.modals.is_open:
            self.modals.update(dt)

        if self.session.status_timer > 0:
            self.session.status_timer -= dt

        # Don't run game logic while modal is open
        if self.modals.is_open:
            for eid, player, vel in app.world.query(Player, Velocity):
                vel.x = 0.0
                vel.y = 0.0
            return

        # Tick fade / auto-walk state machine
        was_fading_in = (self.session._fade_direction == -1)
        self.session.update_transition(dt)

        # After teleport completes and we're fading in, sync angle to new facing
        if was_fading_in or self.session.auto_walk_active:
            result = app.world.query_one(Player, Facing)
            if result:
                _, _, facing = result
                self.player_angle = _direction_to_angle(facing.direction)

        # If we just teleported into a non-FP zone, pop back to TopDown
        if self.session._fade_direction == -1 and not self.session.first_person:
            app.pop_scene()
            return

        # Player input (skipped during auto-walk / fade)
        if not self.session.auto_walk_active and self.session._fade_direction == 0:
            keys = pygame.key.get_pressed()

            # ── Sprint ───────────────────────────────────────────
            self._sprinting = bool(keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT])

            # ── Turn (keyboard, smoothed) ────────────────────────
            turn_input = 0.0
            if keys[pygame.K_LEFT]:  turn_input -= 1.0
            if keys[pygame.K_RIGHT]: turn_input += 1.0
            if abs(turn_input) > 0.01:
                self._turn_vel += (turn_input * TURN_SPEED - self._turn_vel) * min(1.0, TURN_ACCEL * dt)
                # Keyboard turn also generates sway
                self._sway_offset += turn_input * SWAY_AMOUNT * 4.0 * dt
            else:
                self._turn_vel *= max(0.0, 1.0 - TURN_FRICTION * dt)
                if abs(self._turn_vel) < 0.01:
                    self._turn_vel = 0.0
            self.player_angle += self._turn_vel * dt

            # ── Movement (smooth accel / decel) ──────────────────
            fwd = 0.0
            strafe = 0.0
            if keys[pygame.K_w] or keys[pygame.K_UP]:    fwd += 1
            if keys[pygame.K_s] or keys[pygame.K_DOWN]:  fwd -= 1
            if keys[pygame.K_a]:  strafe -= 1
            if keys[pygame.K_d]:  strafe += 1

            # Normalise input
            mag = math.sqrt(fwd * fwd + strafe * strafe)
            if mag > 0.01:
                fwd /= mag
                strafe /= mag

            cos_a = math.cos(self.player_angle)
            sin_a = math.sin(self.player_angle)

            # Desired direction in world space
            want_dx = fwd * cos_a + strafe * (-sin_a)
            want_dy = fwd * sin_a + strafe * cos_a
            moving = (abs(want_dx) > 0.01 or abs(want_dy) > 0.01)

            sprint_mult = SPRINT_MULTIPLIER if self._sprinting and moving else 1.0

            for eid, player, vel in app.world.query(Player, Velocity):
                spd = player.speed * sprint_mult
                if moving:
                    # Accelerate toward desired direction
                    self._move_vx += (want_dx * spd - self._move_vx) * min(1.0, MOVE_ACCEL * dt)
                    self._move_vy += (want_dy * spd - self._move_vy) * min(1.0, MOVE_ACCEL * dt)
                else:
                    # Friction deceleration
                    decay = max(0.0, 1.0 - MOVE_FRICTION * dt)
                    self._move_vx *= decay
                    self._move_vy *= decay
                    if abs(self._move_vx) < 0.01:
                        self._move_vx = 0.0
                    if abs(self._move_vy) < 0.01:
                        self._move_vy = 0.0

                vel.x = self._move_vx
                vel.y = self._move_vy

            # ── Head bob ─────────────────────────────────────────
            actual_speed = math.sqrt(self._move_vx ** 2 + self._move_vy ** 2)
            bob_speed = HEAD_BOB_SPEED * (SPRINT_BOB_MULT if self._sprinting else 1.0)
            bob_amp = HEAD_BOB_AMP * (SPRINT_BOB_MULT if self._sprinting else 1.0)
            if actual_speed > 0.3:
                self._bob_timer += dt * bob_speed
                self._bob_offset = math.sin(self._bob_timer) * bob_amp
                # ── Footstep pulse ────────────────────────────────
                # Track half-cycles of the bob sine for footstep events
                new_phase = int(self._bob_timer / math.pi)
                if new_phase != self._last_step_side:
                    self._last_step_side = new_phase
                    self._step_phase = 1.0  # trigger visual footstep
            else:
                # Smoothly settle back to zero
                self._bob_timer = 0.0
                self._bob_offset *= max(0.0, 1.0 - 10.0 * dt)
        else:
            self._sprinting = False

        # ── Decay view sway ──────────────────────────────────────
        self._sway_offset *= max(0.0, 1.0 - SWAY_DECAY * dt)
        if abs(self._sway_offset) < 0.1:
            self._sway_offset = 0.0
        # Clamp sway
        self._sway_offset = max(-12.0, min(12.0, self._sway_offset))

        # ── Sprint FOV smoothing ─────────────────────────────────
        target_fov_boost = SPRINT_FOV_BOOST if self._sprinting else 0.0
        self._sprint_fov += (target_fov_boost - self._sprint_fov) * min(1.0, 6.0 * dt)

        # ── Damage flash detection ───────────────────────────────
        hp_res = app.world.query_one(Player, Health)
        if hp_res:
            cur_hp = hp_res[2].current
            if self._last_hp >= 0 and cur_hp < self._last_hp:
                self._damage_flash = DAMAGE_FLASH_DUR
            self._last_hp = cur_hp
        if self._damage_flash > 0:
            self._damage_flash -= dt

        # ── Footstep decay ───────────────────────────────────────
        if self._step_phase > 0:
            self._step_phase = max(0.0, self._step_phase - dt * 6.0)

        # ── Update interaction system camera angle ───────────────
        set_camera_angle(self.player_angle)

        # ── Game clock ───────────────────────────────────────────
        clock = app.world.resources.try_get(GameClock)
        if clock:
            clock.time += dt

        # ── Background simulation (WorldClock, ZoneSim, beasts) ──
        self.session.tick_world(dt)

        # ── Physics (same collision system) ──────────────────────
        movement_system(app.world, dt, self.session.tiles,
                        portal_tiles=self.session.portal_positions)

        # ── Events ───────────────────────────────────────────────
        app.world.events.flush()

        # ── Portal check (only when not transitioning) ───────────
        if self.session.check_portals(dt):
            pass  # fade-out started; scene keeps rendering

        # ── Camera ───────────────────────────────────────────────
        cam = app.world.resources.try_get(Camera)
        result = app.world.query_one(Player, Position)
        if cam and result:
            _, _, pos = result
            cam.x = pos.x
            cam.y = pos.y

        app.world.purge()

    # ── Draw ──────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, app: App) -> None:
        sw, sh = surface.get_size()

        # Player position
        result = app.world.query_one(Player, Position)
        if not result:
            surface.fill((0, 0, 0))
            app.draw_text(surface, "No player entity", 10, 10, (255, 0, 0))
            return
        _, _, pos = result
        px, py = pos.x, pos.y

        # Day/night factor for lighting
        wc = app.world.resources.try_get(WorldClock)
        dn = _day_night_factor(wc)

        # Interior zones (first_person) have artificial lighting —
        # guarantee a minimum brightness so indoors are always visible.
        if self.session.first_person:
            dn = max(dn, 0.85)

        fog_rate = _FOG_RATE + int((_FOG_RATE_NIGHT - _FOG_RATE) * (1.0 - dn))

        half = sh // 2 + int(self._bob_offset)
        sway = int(self._sway_offset)
        ambient = int(200 + 55 * dn)  # 200 at night, 255 at day
        fog_lut = _build_fog_lut(ambient, dn)

        # Dynamic FOV including sprint boost
        current_fov = FOV + self._sprint_fov

        # ── Textured floor + gradient ceiling ────────────────────
        self._draw_floor_ceiling(surface, sw, sh, half, px, py, fog_lut, dn,
                                current_fov)

        # ── Walls (textured) ─────────────────────────────────────
        slices = cast_walls(
            px, py, self.player_angle, current_fov,
            sw, sh, self.session.tiles,
            step=RAY_STEP,
        )

        atlas = self._atlas
        night_blue = dn < 0.5
        if night_blue:
            blue_boost = int(15 * (1.0 - dn * 2))
            night_tint = (255, 255, min(255, 255 + blue_boost))

        # Local aliases for hot loop
        _atlas_get = atlas.get
        _scale = pygame.transform.scale
        _blit = surface.blit
        _TEX = TEX_SIZE
        _TEX_M1 = TEX_SIZE - 1
        _step = RAY_STEP
        _BLEND = pygame.BLEND_MULT
        _sh = sh
        _half = half
        # Strip cache — avoids redundant scale + tint for same params
        strip_cache = self._strip_cache
        if len(strip_cache) > 4000:
            strip_cache.clear()
        _cache_get = strip_cache.get

        for ws in slices:
            tid = ws.tile_id
            tx = int(ws.tex_x * _TEX) & _TEX_M1

            full_half_h = ws.height * 0.5
            full_top = _half - full_half_h
            full_bot = _half + full_half_h

            hs = ws.height_scale
            if hs < 0.99:
                scaled_h = ws.height * hs
                y_top = full_bot - scaled_h
                y_bot = full_bot
            else:
                y_top = full_top
                y_bot = full_bot

            cy0 = max(0, int(y_top))
            cy1 = min(_sh, int(y_bot))
            draw_h = cy1 - cy0
            if draw_h < 1:
                continue

            actual_h = y_bot - y_top
            if actual_h > 0:
                v0 = (cy0 - y_top) / actual_h
                v1 = (cy1 - y_top) / actual_h
            else:
                v0, v1 = 0.0, 1.0

            tv0 = max(0, min(_TEX_M1, int(v0 * _TEX)))
            tv1 = max(tv0 + 1, min(_TEX, int(v1 * _TEX)))

            col_w = min(_step, sw - ws.screen_x)

            # Fog from LUT (distance quantised to 0..255)
            fog_idx = min(255, int(ws.distance * 8.0))
            fog = fog_lut[fog_idx]

            fog_q = fog >> 3
            cache_key = (tid, tx, tv1 - tv0, draw_h, col_w, ws.side, fog_q)
            cached = _cache_get(cache_key)
            if cached is not None:
                _blit(cached, (ws.screen_x, cy0))
            else:
                tex_surf = _atlas_get(tid)
                strip = tex_surf.subsurface((tx, tv0, 1, tv1 - tv0))
                scaled = _scale(strip, (col_w, draw_h))

                # Directional shading — warm shadow on N/S faces
                if ws.side == 1:
                    scaled.fill((175, 168, 155), special_flags=_BLEND)

                # Fog
                if fog < 250:
                    scaled.fill((fog, fog, fog), special_flags=_BLEND)

                # Night tint
                if night_blue:
                    scaled.fill(night_tint, special_flags=_BLEND)

                strip_cache[cache_key] = scaled
                _blit(scaled, (ws.screen_x, cy0))

            # Ambient occlusion — darken floor just below wall base
            if cy1 < _sh and hs > 0.99:
                _ao = min(6, max(1, draw_h >> 3))
                _ao_h = min(_ao, _sh - cy1)
                if _ao_h > 0:
                    surface.fill((120, 120, 115),
                                 (ws.screen_x, cy1, col_w, _ao_h),
                                 special_flags=_BLEND)

            # Half-wall: top surface + edge highlight + AO
            if hs < 0.99 and cy0 > 0 and cy0 < _sh:
                # ── Top surface ───────────────────────────────
                # For half-walls below eye level (hs < 0.49) the
                # player can look down onto the flat top.  Render
                # a geometrically-sized strip using the tile
                # colour — height equals one tile of depth in
                # screen pixels.
                if hs < 0.49:
                    _dist = ws.distance
                    strip_h = int(
                        (0.5 - hs) * ws.height / (_dist + 1.0)
                    )
                    strip_h = max(2, min(strip_h,
                                         cy0 - max(0, int(_half) + 1)))
                    if strip_h > 0:
                        strip_top = cy0 - strip_h
                        top_color = TILE_COLORS.get(tid, (100, 95, 85))
                        # Near band (brighter, close to camera)
                        fog_near = fog
                        nr = max(20, min(255,
                            int(top_color[0] * 1.2 * fog_near / 255)))
                        ng = max(20, min(255,
                            int(top_color[1] * 1.2 * fog_near / 255)))
                        nb = max(20, min(255,
                            int(top_color[2] * 1.2 * fog_near / 255)))
                        if strip_h <= 4:
                            # Tiny strip — single fill suffices
                            surface.fill((nr, ng, nb),
                                         (ws.screen_x, strip_top,
                                          col_w, strip_h))
                        else:
                            # Two-band gradient: far half darker
                            near_h = strip_h // 2
                            far_h = strip_h - near_h
                            fog_far_idx = min(
                                255, int((_dist + 1.0) * 8.0))
                            fog_far = fog_lut[fog_far_idx]
                            fr = max(20, min(255,
                                int(top_color[0] * 1.1 * fog_far / 255)))
                            fg = max(20, min(255,
                                int(top_color[1] * 1.1 * fog_far / 255)))
                            fb = max(20, min(255,
                                int(top_color[2] * 1.1 * fog_far / 255)))
                            # Far band (top)
                            surface.fill((fr, fg, fb),
                                         (ws.screen_x, strip_top,
                                          col_w, far_h))
                            # Near band (bottom, adjacent to wall)
                            surface.fill((nr, ng, nb),
                                         (ws.screen_x, strip_top + far_h,
                                          col_w, near_h))

                # Edge highlight at the wall-top boundary
                edge_bright = max(60, min(200, fog))
                surface.fill((edge_bright, edge_bright, edge_bright - 10),
                             (ws.screen_x, cy0, col_w, 1),
                             special_flags=_BLEND)
                # AO shadow just below the half-wall base
                if cy1 < _sh:
                    _ao = min(4, max(1, draw_h >> 4))
                    _ao_h = min(_ao, _sh - cy1)
                    if _ao_h > 0:
                        surface.fill((110, 110, 105),
                                     (ws.screen_x, cy1, col_w, _ao_h),
                                     special_flags=_BLEND)

        # ── Entity billboards ────────────────────────────────────
        zone = self.session.zone_name
        ent_data: list[tuple[int, float, float, str, tuple[int, int, int], float, float]] = []
        for eid, epos, sprite in app.world.query(Position, Sprite):
            if epos.zone != zone:
                continue
            if app.world.has(eid, Player):
                continue  # don't render self
            h_scale, w_scale, is_bb = _ENTITY_VIS.get(sprite.char, _DEFAULT_VIS)
            # Narrow flat furniture when viewed from the side
            if not is_bb:
                fc = app.world.get(eid, Facing)
                if fc:
                    fa = _FACE_ANGLES.get(fc.direction, math.pi * 0.5)
                    ca = math.atan2(epos.y - py, epos.x - px)
                    w_scale *= max(0.20, abs(math.cos(fa - ca)))
            ent_data.append((eid, epos.x, epos.y, sprite.char, sprite.color,
                             h_scale, w_scale))

        if ent_data:
            zbuf = build_zbuffer(slices, sw, step=RAY_STEP)
            billboards = project_entities(
                px, py, self.player_angle, current_fov, sw, sh, ent_data,
            )
            self._draw_billboards(surface, app, billboards, zbuf, sw, sh,
                                  dn, fog_rate)

        # ── Day/night tint overlay (skip for interiors) ─────────
        if not self.session.first_person:
            self._draw_day_night(surface, wc)

        # ── Damage flash ────────────────────────────────────────
        if self._damage_flash > 0:
            flash_t = min(1.0, self._damage_flash / DAMAGE_FLASH_DUR)
            flash_alpha = int(90 * flash_t)
            flash_surf = getattr(self, '_dmg_flash_surf', None)
            if flash_surf is None or flash_surf.get_size() != (sw, sh):
                flash_surf = pygame.Surface((sw, sh), pygame.SRCALPHA)
                self._dmg_flash_surf = flash_surf
            # Red vignette — stronger at edges
            flash_surf.fill((180, 0, 0, flash_alpha))
            surface.blit(flash_surf, (0, 0))

        # ── View sway shift ─────────────────────────────────────
        # Apply a subtle horizontal pixel-shift to the rendered frame.
        # This gives a parallax / inertia feel when turning.
        if abs(sway) >= 1:
            # In-place scroll is ~100x faster than copy+blit
            s = int(sway)
            surface.scroll(s, 0)
            if s > 0:
                surface.fill((0, 0, 0), (0, 0, s, sh))
            else:
                surface.fill((0, 0, 0), (sw + s, 0, -s, sh))

        # ── HUD ──────────────────────────────────────────────────
        self._draw_hud(surface, app, sw, sh)

        # ── Notifications / toasts ───────────────────────────────
        self._draw_notifications(surface, app)

        # ── Minimap (always visible) ─────────────────────────────
        self._draw_minimap(surface, app, px, py, sw, sh)

        # ── Compass bar ──────────────────────────────────────────
        self._draw_compass(surface, sw)

        # ── Debug overlay (Tab toggle) ───────────────────────────
        if self.show_debug:
            self._draw_debug(surface, app, px, py)

        # ── Fade overlay ─────────────────────────────────────────
        if self.session.fade_alpha > 0.01:
            a = int(min(255, self.session.fade_alpha * 255))
            if not hasattr(self, '_fade_surf') or self._fade_surf.get_size() != (sw, sh):
                self._fade_surf = pygame.Surface((sw, sh), pygame.SRCALPHA)
            self._fade_surf.fill((0, 0, 0, a))
            surface.blit(self._fade_surf, (0, 0))

        # ── Modals ───────────────────────────────────────────────
        if self.modals.is_open:
            self.modals.draw(surface, app)

    # ── Prop texture billboard ───────────────────────────────────

    def _get_prop_surface(self, key: str, size: int) -> pygame.Surface:
        """Get a scaled prop texture for billboard rendering."""
        cache_key = f"{key}_{size}"
        if cache_key not in self._prop_surfaces:
            from systems.textures import _KEY_GENERATORS
            from core.tiles import TILE_REGISTRY
            # Find tile ID that maps to this key
            src = None
            for tid, td in TILE_REGISTRY.items():
                if td.texture_key == key:
                    src = self._atlas.get(tid)
                    break
            if src is None:
                # Generate standalone from key
                gen = _KEY_GENERATORS.get(key)
                if gen:
                    src = gen((120, 100, 80))
                else:
                    src = self._atlas.get(0)  # fallback to void
            self._prop_surfaces[cache_key] = pygame.transform.scale(
                src, (size, size))
        return self._prop_surfaces[cache_key]

    # ── Billboard rendering ──────────────────────────────────────

    def _get_font(self, size: int) -> pygame.font.Font:
        """Cached monospace font at *size* pixels."""
        size = max(8, min(72, size))
        size = (size // 2) * 2  # round to even -> fewer cache entries
        if size not in self._font_cache:
            self._font_cache[size] = pygame.font.SysFont("monospace", size)
        return self._font_cache[size]

    def _draw_billboards(
        self, surface: pygame.Surface, app: App,
        billboards: list, zbuf: list[float],
        sw: int, sh: int, dn: float = 1.0, fog_rate: int = _FOG_RATE,
    ) -> None:
        # Pre-build fog LUT for billboard use
        bb_fog_lut = _build_fog_lut(255, dn)
        _bob = self._bob_offset
        _BLEND = pygame.BLEND_MULT
        # Glyph render cache: (char, font_size) -> (shadow_surf, glyph_surf)
        if not hasattr(self, '_glyph_cache'):
            self._glyph_cache: dict[tuple[str, int], tuple[pygame.Surface, pygame.Surface]] = {}
        glyph_cache = self._glyph_cache
        if len(glyph_cache) > 200:
            glyph_cache.clear()

        for bb in billboards:
            if bb.height < 2:
                continue

            ent_w = bb.width if bb.width > 0 else bb.height
            ent_h = bb.height
            if ent_w < 2:
                continue

            # Distance-fogged colour (LUT)
            fog_idx = min(255, int(bb.distance * 8.0))
            fog = bb_fog_lut[fog_idx]
            fogged = (
                bb.color[0] * fog // 255,
                bb.color[1] * fog // 255,
                bb.color[2] * fog // 255,
            )

            # Position on screen
            dx = int(bb.screen_x - ent_w // 2)
            dy = int(bb.screen_y + _bob)

            left = max(0, dx)
            right = min(sw, dx + ent_w)
            if left >= right:
                continue

            # Z-clip: find visible span (min/max visible columns)
            dist = bb.distance
            vis_l, vis_r = right, left
            for c in range(left, right):
                if dist < zbuf[c]:
                    if c < vis_l:
                        vis_l = c
                    vis_r = c + 1
            if vis_l >= vis_r:
                continue

            # Build entity surface: reuse pooled SRCALPHA surface
            _eq = ((ent_w + 7) & ~7, (ent_h + 7) & ~7)  # quantize to 8px
            if not hasattr(self, '_ent_pool'):
                self._ent_pool: dict[tuple[int, int], pygame.Surface] = {}
            ent_surf = self._ent_pool.get(_eq)
            if ent_surf is None:
                ent_surf = pygame.Surface(_eq, pygame.SRCALPHA)
                self._ent_pool[_eq] = ent_surf
            ent_surf.fill((0, 0, 0, 0))  # clear alpha
            # Draw body within actual (non-quantized) bounds
            pygame.draw.rect(ent_surf, (*fogged, 230), (0, 0, ent_w, ent_h))

            # Border
            bw = 2 if min(ent_w, ent_h) > 12 else 1
            border = (max(0, fogged[0] - 50),
                      max(0, fogged[1] - 50),
                      max(0, fogged[2] - 50), 255)
            pygame.draw.rect(ent_surf, border, (0, 0, ent_w, ent_h), bw)

            # Overlay: textured prop or glyph
            prop_key = _PROP_GLYPHS.get(bb.char)
            if prop_key:
                tex_w = max(4, int(ent_w * 0.85))
                tex_h = max(4, int(ent_h * 0.85))
                prop_surf = self._get_prop_surface(prop_key, max(tex_w, tex_h))
                scaled = pygame.transform.scale(prop_surf, (tex_w, tex_h))
                if fog < 250:
                    scaled.fill((fog, fog, fog), special_flags=_BLEND)
                ent_surf.blit(scaled, ((ent_w - tex_w) // 2,
                                       (ent_h - tex_h) // 2))
            else:
                # Cached glyph rendering
                font_size = max(8, min(48, ent_h * 2 // 3))
                glyph_key = (bb.char, font_size)
                cached_g = glyph_cache.get(glyph_key)
                if cached_g is None:
                    font = self._get_font(font_size)
                    shadow = font.render(bb.char, True, (0, 0, 0))
                    glyph = font.render(bb.char, True, (255, 255, 240))
                    glyph_cache[glyph_key] = (shadow, glyph)
                    cached_g = (shadow, glyph)
                shadow, glyph = cached_g
                gx = (ent_w - glyph.get_width()) // 2
                gy = (ent_h - glyph.get_height()) // 2
                ent_surf.blit(shadow, (gx + 1, gy + 1))
                ent_surf.blit(glyph, (gx, gy))

            # Blit visible slice
            src_x = vis_l - dx
            src_w = vis_r - vis_l
            if src_w > 0 and src_x >= 0 and src_x + src_w <= ent_w:
                clipped = ent_surf.subsurface((src_x, 0, src_w, ent_h))
                surface.blit(clipped, (vis_l, dy))

            # Health bar
            hp = app.world.get(bb.eid, Health)
            if hp and hp.current < hp.maximum:
                bar_w = min(ent_w, 40)
                ratio = max(0.0, hp.current / hp.maximum) if hp.maximum > 0 else 0.0
                bx = int(bb.screen_x - bar_w // 2)
                by = dy - 6
                pygame.draw.rect(surface, (60, 0, 0), (bx, by, bar_w, 4))
                pygame.draw.rect(surface, (0, 200, 0),
                                 (bx, by, int(bar_w * ratio), 4))

            # Entity name tag (visible when close)
            if bb.distance < 4.0:
                ident = app.world.get(bb.eid, Identity)
                if ident:
                    name_alpha = max(0.0, 1.0 - bb.distance / 4.0)
                    nc = int(200 * name_alpha)
                    if nc > 30:
                        app.draw_text(surface, ident.name,
                                      int(bb.screen_x - len(ident.name) * 3),
                                      dy - 14, (nc, nc, nc), app.font_sm)

    # ── Day/night tint overlay ───────────────────────────────────

    def _draw_day_night(self, surface: pygame.Surface, wc) -> None:  # type: ignore[type-arg]
        """Apply a subtle color overlay based on time of day."""
        if wc is None:
            return
        phase = wc.day_phase
        if 0.30 <= phase < 0.70:
            return  # full daylight, no tint

        if phase < 0.20 or phase >= 0.85:
            color = (10, 10, 50)
            alpha = 60
        elif 0.20 <= phase < 0.30:
            t = (phase - 0.20) / 0.10
            alpha = int(60 * (1.0 - t))
            r = int(10 + 40 * t)
            g = int(10 + 20 * t)
            b = int(50 - 20 * t)
            color = (r, g, b)
        elif 0.70 <= phase < 0.80:
            t = (phase - 0.70) / 0.10
            alpha = int(50 * t)
            color = (50 - int(30 * t), 20 - int(10 * t), 10 + int(30 * t))
        else:
            t = (phase - 0.80) / 0.05
            alpha = int(50 + 10 * t)
            color = (20 - int(10 * t), 10, 40 + int(10 * t))

        tint_surf = getattr(self, '_tint_surf', None)
        sz = surface.get_size()
        if tint_surf is None or tint_surf.get_size() != sz:
            tint_surf = pygame.Surface(sz, pygame.SRCALPHA)
            self._tint_surf = tint_surf
        tint_surf.fill((*color, alpha))
        surface.blit(tint_surf, (0, 0))

    # ── Textured floor / ceiling ─────────────────────────────────

    def _draw_floor_ceiling(self, surface: pygame.Surface, sw: int, sh: int,
                            half: int, px: float, py: float,
                            fog_lut: list[int], dn: float,
                            fov: float = FOV) -> None:
        """Per-row textured floor with checkerboard + gradient ceiling."""
        tiles = self.session.tiles
        mw = self.session.map_w
        mh = self.session.map_h
        is_interior = self.session.first_person
        angle = self.player_angle
        _fill = surface.fill

        # ── Ceiling ──────────────────────────────────────────────
        if is_interior:
            # Concrete ceiling — each row is a single colour (distance-fogged).
            # Fill rows directly without per-pixel inner loop.
            _cc = _lerp_color((25, 28, 32), (65, 68, 72), dn)
            half_sh = sh * 0.5
            _CDIV = 4
            cbw = max(1, sw // _CDIV)
            cbh = max(1, half // _CDIV)
            cbuf = bytearray(cbw * cbh * 3)
            _min2 = min
            _int2 = int
            row_bytes = cbw * 3
            for cy in range(cbh):
                dy = (cbh - cy) * _CDIV
                p = dy + 0.5
                row_dist = half_sh / p
                fi = _min2(255, _int2(row_dist * 8.0))
                ff = fog_lut[fi] * 0.003921568627
                cr = max(0, _min2(255, _int2(_cc[0] * ff)))
                cg = max(0, _min2(255, _int2(_cc[1] * ff)))
                cb_ = max(0, _min2(255, _int2(_cc[2] * ff)))
                # Build one row and tile it across the full width
                row_off = cy * row_bytes
                pixel = bytes((cr, cg, cb_))
                cbuf[row_off:row_off + row_bytes] = pixel * cbw
            ceil_fb = pygame.image.frombuffer(bytes(cbuf), (cbw, cbh), 'RGB')
            surface.blit(pygame.transform.scale(ceil_fb, (sw, half)), (0, 0))
        else:
            # Outdoor sky gradient
            ceil = _lerp_color(_CEILING_NIGHT, _CEILING_DAY, dn)
            band_h = max(1, half // _GRAD_BANDS + 1)
            for i in range(_GRAD_BANDS):
                t = i / _GRAD_BANDS
                cr = int(ceil[0] * (0.3 + 0.7 * t))
                cg = int(ceil[1] * (0.3 + 0.7 * t))
                cb = int(ceil[2] * (0.3 + 0.7 * t))
                y = int(t * half)
                _fill((cr, cg, cb), (0, y, sw, band_h))

        # ── Floor ────────────────────────────────────────────────
        if not tiles or mw < 1 or mh < 1:
            fc = _lerp_color(_FLOOR_NIGHT, _FLOOR_DAY, dn)
            _fill(fc, (0, half, sw, sh - half))
            return

        _cos_a = math.cos(angle)
        _sin_a = math.sin(angle)
        _tan_h = math.tan(fov * 0.5)
        plane_x = -_sin_a * _tan_h
        plane_y = _cos_a * _tan_h
        half_sh = sh * 0.5

        # Pre-build flat colour palette: list indexed by tile_id → (r,g,b)
        # Replaces per-pixel dict lookups with fast list indexing.
        _dflt = (50, 50, 45)
        _solid = SOLID_IDS
        max_tid = max(TILE_COLORS.keys()) if TILE_COLORS else 0
        _pal: list[tuple[int, int, int]] = [_dflt] * (max_tid + 1)
        for tid_p, col_p in TILE_COLORS.items():
            _pal[tid_p] = _dflt if tid_p in _solid else col_p
        _pal_len = len(_pal)

        floor_h = sh - half
        if floor_h < 1:
            return

        # Render to small off-screen buffer, scale up once.
        _FDIV = 5  # 1/5 resolution — balance quality vs speed
        fbw = max(1, sw // _FDIV)
        fbh = max(1, floor_h // _FDIV)

        buf = bytearray(fbw * fbh * 3)
        inv_fbw = 1.0 / fbw
        _min = min
        _int = int

        # Pre-computed fogged palette cache — indexed by fog LUT index.
        # Avoids per-pixel colour math: just look up pre-multiplied bytes.
        _rpal_b: dict[int, list] = {}
        _rpal_d: dict[int, list] = {}

        for by in range(fbh):
            dy = by * _FDIV + _FDIV * 0.5
            p = dy + 0.5
            row_dist = half_sh / p
            fi = _min(255, _int(row_dist * 8.0))

            # Get or build fogged palette for this fog level
            cached_pals = _rpal_b.get(fi)
            if cached_pals is None:
                ff = fog_lut[fi] * 0.003921568627  # 1/255
                fd = ff * 0.88  # dark checker
                pal_b = [None] * _pal_len
                pal_d = [None] * _pal_len
                for _i in range(_pal_len):
                    _c = _pal[_i]
                    pal_b[_i] = bytes((_min(255, _int(_c[0] * ff)),
                                       _min(255, _int(_c[1] * ff)),
                                       _min(255, _int(_c[2] * ff))))
                    pal_d[_i] = bytes((_min(255, _int(_c[0] * fd)),
                                       _min(255, _int(_c[1] * fd)),
                                       _min(255, _int(_c[2] * fd))))
                _rpal_b[fi] = (pal_b, pal_d)
            else:
                pal_b, pal_d = cached_pals

            # Ray endpoints for this row
            fx = px + row_dist * (_cos_a - plane_x)
            fy = py + row_dist * (_sin_a - plane_y)
            sx = row_dist * 2.0 * plane_x * inv_fbw
            sy = row_dist * 2.0 * plane_y * inv_fbw
            fx += sx * 0.5
            fy += sy * 0.5

            row_off = by * fbw * 3
            for bx in range(fbw):
                ifx = _int(fx)
                ify = _int(fy)
                tid = tiles[ify % mh][ifx % mw]
                if tid >= _pal_len:
                    tid = 0
                off = row_off + bx * 3
                buf[off:off + 3] = pal_d[tid] if ((ifx ^ ify) & 1) else pal_b[tid]
                fx += sx
                fy += sy

        fb = pygame.image.frombuffer(bytes(buf), (fbw, fbh), 'RGB')
        scaled_floor = pygame.transform.scale(fb, (sw, floor_h))
        surface.blit(scaled_floor, (0, half))

    # ── HUD ───────────────────────────────────────────────────────

    def _draw_hud(self, surface: pygame.Surface, app: App,
                  sw: int, sh: int) -> None:
        # Health bar
        result = app.world.query_one(Player, Health)
        if result:
            _, _, hp = result
            bar_x, bar_y = 10, sh - 30
            bar_w, bar_h = 120, 12
            ratio = max(0.0, hp.current / hp.maximum) if hp.maximum > 0 else 0.0
            # Bar background
            pygame.draw.rect(surface, (40, 0, 0), (bar_x - 1, bar_y - 1,
                                                     bar_w + 2, bar_h + 2))
            pygame.draw.rect(surface, (60, 0, 0), (bar_x, bar_y, bar_w, bar_h))
            # Health fill — color shifts red→green
            hp_r = int(220 * (1.0 - ratio))
            hp_g = int(200 * ratio)
            pygame.draw.rect(surface, (hp_r, hp_g, 0),
                             (bar_x, bar_y, int(bar_w * ratio), bar_h))
            app.draw_text(surface, f"{int(hp.current)}/{int(hp.maximum)} HP",
                          bar_x + bar_w + 6, bar_y - 1, (200, 200, 200),
                          app.font_sm)

        # Inventory count
        inv_res = app.world.query_one(Player, Inventory)
        if inv_res:
            _, _, inv = inv_res
            total = sum(inv.items.values())
            if total > 0:
                app.draw_text(surface, f"\u25a0 {total}",
                              140, sh - 30, (180, 170, 140), app.font_sm)

        # Crosshair — small dot + thin lines
        cx, cy = sw // 2, sh // 2
        pygame.draw.line(surface, (200, 200, 200), (cx - 8, cy), (cx - 3, cy))
        pygame.draw.line(surface, (200, 200, 200), (cx + 3, cy), (cx + 8, cy))
        pygame.draw.line(surface, (200, 200, 200), (cx, cy - 8), (cx, cy - 3))
        pygame.draw.line(surface, (200, 200, 200), (cx, cy + 3), (cx, cy + 8))
        pygame.draw.circle(surface, (220, 220, 220), (cx, cy), 1)

        # Zone name
        app.draw_text(surface, self.session.zone_name, sw - 100, 10,
                      (120, 140, 130), app.font_sm)

        # World clock
        wc = app.world.resources.try_get(WorldClock)
        if wc:
            hour = int(wc.day_phase * 24) % 24
            minute = int((wc.day_phase * 24 * 60) % 60)
            time_str = f"Day {wc.day + 1}  {hour:02d}:{minute:02d}"
            if 0.25 <= wc.day_phase < 0.75:
                time_col = (220, 200, 140)
            elif 0.75 <= wc.day_phase < 0.85:
                time_col = (220, 140, 80)
            elif wc.day_phase >= 0.85 or wc.day_phase < 0.15:
                time_col = (100, 120, 180)
            else:
                time_col = (180, 160, 120)
            app.draw_text(surface, time_str, sw - 100, 24,
                          time_col, app.font_sm)
            if wc.time_scale > 1.0:
                app.draw_text(surface, f"\u25b6\u25b6{int(wc.time_scale)}\u00d7",
                              sw - 100, 38, (255, 180, 60), app.font_sm)

        # Interaction prompt — tile entity aware
        target = nearest_interactable(app.world)
        if target and not self.modals.is_open:
            t_eid, _ = target
            ident = app.world.get(t_eid, Identity)
            te = app.world.get(t_eid, TileEntity)
            name = ident.name if ident else f"Entity #{t_eid}"
            if te and te.tile_type == "ground_item":
                label = f"[E] Pick up {name}"
            elif te and te.tile_type == "container":
                label = f"[E] Open {name}"
            elif ident and ident.kind == EntityKind.NPC:
                label = f"[E] Talk to {name}"
            else:
                label = f"[E] {name}"
            # Background pill for readability
            tw = len(label) * 7 + 12
            pill = pygame.Surface((tw, 20), pygame.SRCALPHA)
            pill.fill((0, 0, 0, 120))
            surface.blit(pill, (sw // 2 - tw // 2, sh - 54))
            app.draw_text(surface, label,
                          sw // 2 - tw // 2 + 6, sh - 52,
                          (255, 230, 150), app.font_sm)

        # Status label
        if self.session.status_timer > 0 and self.session.status:
            alpha = min(1.0, self.session.status_timer / 0.5)
            c = int(220 * alpha)
            app.draw_text_bg(surface, self.session.status,
                             sw // 2 - 80, 40, (c, c, c))

        # Controls
        sprint_hint = "Shift=sprint  " if True else ""
        app.draw_text(surface,
                      f"WASD=move  {sprint_hint}Mouse=look  E=interact  I=inv  Tab=debug  Esc=cursor",
                      10, sh - 14, (80, 100, 90), app.font_sm)

    # ── Toast notifications ──────────────────────────────────────

    _NOTIFICATION_COLORS = {
        "combat": (255, 100, 100),
        "travel": (100, 200, 255),
        "loot":   (255, 220, 100),
        "info":   (180, 180, 180),
    }

    def _draw_notifications(self, surface: pygame.Surface, app: App) -> None:
        """Draw recent world events as toast notifications."""
        event_log = app.world.resources.try_get(WorldEventLog)
        if event_log is None or not event_log.entries:
            return

        sw, sh = surface.get_size()
        clock = app.world.resources.try_get(GameClock)
        now = clock.time if clock else 0.0

        max_show = 5
        y = 50
        shown = 0

        for entry in reversed(event_log.entries):
            age = now - entry.time
            if age > 8.0:
                break
            if shown >= max_show:
                break
            if age > 5.0:
                fade = 1.0 - (age - 5.0) / 3.0
            else:
                fade = 1.0

            color = self._NOTIFICATION_COLORS.get(entry.category, (180, 180, 180))
            color = tuple(int(c * fade) for c in color)

            text = entry.message
            tw = len(text) * 7
            bx = sw - tw - 20
            by = y
            bg_surf = pygame.Surface((tw + 12, 18), pygame.SRCALPHA)
            bg_surf.fill((0, 0, 0, int(120 * fade)))
            surface.blit(bg_surf, (bx - 4, by - 2))

            app.draw_text(surface, text, bx, by, color, app.font_sm)
            y += 20
            shown += 1

        event_log.unread = 0

    # ── Compass bar ────────────────────────────────────────────

    _COMPASS_POINTS = [
        (0.0, "E"), (math.pi * 0.25, "SE"), (math.pi * 0.5, "S"),
        (math.pi * 0.75, "SW"), (math.pi, "W"), (math.pi * 1.25, "NW"),
        (math.pi * 1.5, "N"), (math.pi * 1.75, "NE"),
    ]

    def _draw_compass(self, surface: pygame.Surface, sw: int) -> None:
        """Draw a horizontal compass bar at the top of the screen."""
        bar_w = min(260, sw - 40)
        bar_h = 16
        bx = (sw - bar_w) // 2
        by = 4

        # Cached semi-transparent background
        if not hasattr(self, '_compass_bg') or self._compass_bg.get_width() != bar_w:
            self._compass_bg = pygame.Surface((bar_w, bar_h), pygame.SRCALPHA)
            self._compass_bg.fill((0, 0, 0, 100))
        surface.blit(self._compass_bg, (bx, by))

        # Centre tick
        cx = bx + bar_w // 2
        pygame.draw.line(surface, (255, 255, 200), (cx, by), (cx, by + 3))

        # Draw compass labels scrolled by player angle
        # Cache rendered label surfaces
        if not hasattr(self, '_compass_labels'):
            font = self._get_font(10)
            self._compass_labels = {}
            for pt_ang, label in self._COMPASS_POINTS:
                if len(label) == 1:
                    col = (255, 240, 180)
                else:
                    col = (140, 140, 120)
                self._compass_labels[label] = (pt_ang, col,
                                               font.render(label, True, col))

        ang = self.player_angle % (2 * math.pi)
        half_bar = bar_w * 0.5
        _pi = math.pi
        for label, (pt_ang, col, txt) in self._compass_labels.items():
            diff = (pt_ang - ang + _pi) % (2 * _pi) - _pi
            frac = diff / _pi
            px_off = int(frac * half_bar)
            lx = cx + px_off
            if lx < bx or lx > bx + bar_w:
                continue
            if len(label) == 1:
                pygame.draw.line(surface, col, (lx, by + bar_h - 4),
                                 (lx, by + bar_h))
            else:
                pygame.draw.line(surface, col, (lx, by + bar_h - 2),
                                 (lx, by + bar_h))
            surface.blit(txt, (lx - txt.get_width() // 2, by + 1))

    # ── Minimap ──────────────────────────────────────────────────

    def _draw_minimap(self, surface: pygame.Surface, app: App,
                      px: float, py: float,
                      sw: int, sh: int) -> None:
        """Small top-down minimap in the corner with FOV cone."""
        tiles = self.session.tiles
        mw = self.session.map_w
        mh = self.session.map_h
        if not tiles:
            return

        cell = 4  # pixels per tile on minimap
        mm_w = mw * cell
        mm_h = mh * cell
        mm_x = sw - mm_w - 8
        mm_y = 24

        # Build/cache the static base tile surface
        zone = self.session.zone_name
        tiles_id = id(tiles)  # fast identity check
        if (self._mm_base is None or self._mm_zone != zone
                or self._mm_tiles_hash != tiles_id):
            base = pygame.Surface((mm_w + 2, mm_h + 2), pygame.SRCALPHA)
            base.fill((0, 0, 0, 160))
            for row in range(mh):
                for col in range(mw):
                    tid = tiles[row][col]
                    if tid in SOLID_IDS:
                        if tid in HALF_WALL_IDS:
                            color = (120, 110, 90)
                        else:
                            color = (150, 150, 160)
                    elif tid in DOOR_IDS:
                        color = (80, 160, 200)
                    else:
                        color = (40, 45, 35)
                    pygame.draw.rect(base, color,
                                     (1 + col * cell, 1 + row * cell,
                                      cell, cell))
            # Border
            pygame.draw.rect(base, (80, 80, 90),
                             (0, 0, mm_w + 2, mm_h + 2), 1)
            self._mm_base = base
            self._mm_zone = zone
            self._mm_tiles_hash = tiles_id

        # Blit cached base
        surface.blit(self._mm_base, (mm_x - 1, mm_y - 1))

        # Dynamic overlay: entities, player, FOV cone
        # Entities
        for eid, epos, sprite in app.world.query(Position, Sprite):
            if epos.zone != zone:
                continue
            if app.world.has(eid, Player):
                continue
            ex = mm_x + int(epos.x * cell)
            ey = mm_y + int(epos.y * cell)
            ident = app.world.get(eid, Identity)
            if ident and ident.kind == EntityKind.NPC:
                pts = [(ex, ey - 2), (ex + 2, ey), (ex, ey + 2), (ex - 2, ey)]
                pygame.draw.polygon(surface, (100, 255, 100), pts)
            else:
                pygame.draw.circle(surface, sprite.color, (ex, ey),
                                   max(1, cell // 2))

        # Player + FOV cone
        ppx = mm_x + int(px * cell)
        ppy = mm_y + int(py * cell)

        cone_len = cell * 5
        half_fov = FOV * 0.5
        left_ang = self.player_angle - half_fov
        right_ang = self.player_angle + half_fov
        cone_pts = [
            (ppx, ppy),
            (ppx + int(math.cos(left_ang) * cone_len),
             ppy + int(math.sin(left_ang) * cone_len)),
            (ppx + int(math.cos(right_ang) * cone_len),
             ppy + int(math.sin(right_ang) * cone_len)),
        ]
        # Reuse a small overlay surface for cone
        if not hasattr(self, '_mm_cone') or self._mm_cone.get_size() != (mm_w + 2, mm_h + 2):
            self._mm_cone = pygame.Surface((mm_w + 2, mm_h + 2), pygame.SRCALPHA)
        self._mm_cone.fill((0, 0, 0, 0))
        local_pts = [(x - mm_x + 1, y - mm_y + 1) for x, y in cone_pts]
        pygame.draw.polygon(self._mm_cone, (255, 255, 100, 40), local_pts)
        surface.blit(self._mm_cone, (mm_x - 1, mm_y - 1))

        # Player dot + direction
        pygame.draw.circle(surface, (255, 255, 100), (ppx, ppy), max(2, cell))
        end_x = ppx + int(math.cos(self.player_angle) * cell * 3)
        end_y = ppy + int(math.sin(self.player_angle) * cell * 3)
        pygame.draw.line(surface, (255, 255, 100), (ppx, ppy),
                         (end_x, end_y), 1)

    def _draw_debug(self, surface: pygame.Surface, app: App,
                    px: float, py: float) -> None:
        y = 30
        fps = app.clock.get_fps()
        app.draw_text_bg(surface, f"FPS: {fps:.0f}", 10, y, (0, 255, 200))
        y += 16
        app.draw_text_bg(surface,
                         f"Pos: ({px:.1f}, {py:.1f})  Ang: {math.degrees(self.player_angle):.0f}\u00b0",
                         10, y, (0, 255, 200))
        y += 16
        n = len(app.world.zone_entities(self.session.zone_name))
        app.draw_text_bg(surface, f"Entities: {n}", 10, y, (0, 255, 200))
        y += 16
        clock = app.world.resources.try_get(GameClock)
        if clock:
            app.draw_text_bg(surface, f"Time: {clock.time:.1f}s",
                             10, y, (0, 255, 200))
        y += 16
        wc = app.world.resources.try_get(WorldClock)
        if wc:
            app.draw_text_bg(surface,
                             f"Day {wc.day + 1}  Phase: {wc.day_phase:.2f}",
                             10, y, (0, 255, 200))


# ── Angle  \u2194  Direction helpers ──────────────────────────────────────

_DIR_ANGLES: dict[Direction, float] = {
    Direction.RIGHT: 0.0,
    Direction.DOWN:  math.pi * 0.5,
    Direction.LEFT:  math.pi,
    Direction.UP:    math.pi * 1.5,
}


def _direction_to_angle(d: Direction) -> float:
    return _DIR_ANGLES.get(d, math.pi * 1.5)


def _angle_to_direction(a: float) -> Direction:
    """Snap a continuous angle to the nearest cardinal direction."""
    a = a % (2 * math.pi)
    if a < math.pi * 0.25 or a >= math.pi * 1.75:
        return Direction.RIGHT
    if a < math.pi * 0.75:
        return Direction.DOWN
    if a < math.pi * 1.25:
        return Direction.LEFT
    return Direction.UP
