"""scenes/world/topdown.py — Top-down tile view (presentation layer).

Renders tiles and entities.  Camera follows the player.
WASD to move.  E to interact.  I to open inventory.  ~ for dev panel.
Tab toggles debug HUD.  F5 to save.  F9 to load.  Escape to quit.

The scene reads world layout from a ``Session`` and never loads
zone data or spawns entities itself.
"""

from __future__ import annotations

import math
import pygame

from core.app import App
from core.constants import TILE_SIZE
from core.tiles import TILE_COLORS, PLATFORM_IDS
from core.scene import Scene
from core.types import Direction, EntityKind
from components import (
    Position, Velocity, Sprite, Player, Facing,
    Health, Identity, Inventory, Camera, GameClock, WorldClock,
    TileEntity, Collider, WorldEventLog,
)
from systems.physics import movement_system
from systems.interaction import try_interact, nearest_interactable
from systems.item_registry import ItemRegistry
from systems.spawner import spawn_from_descriptor
from ui.modal import ModalStack
from ui.commands import CloseModal, HealPlayer
from ui.inventory_modal import InventoryModal
from ui.transfer_modal import TransferModal

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.session import Session


class TopDown(Scene):
    """Top-down tile-based view (presentation only).

    All zone loading, entity spawning, and save/load orchestration
    live in ``Session``.  This scene only reads data and renders.
    """

    def __init__(self, session: "Session") -> None:
        self.session = session
        self.show_debug = False
        self.modals = ModalStack()
        self._registry = ItemRegistry()
        self._dev_panel_open = False
        self._dev_cursor = 0
        self._dev_scroll = 0
        self._dev_items: list[str] = self._registry.ids()
        self._dev_hover: int = -1

    # ── Lifecycle ─────────────────────────────────────────────────

    def on_enter(self, app: App) -> None:
        # Ensure resources exist (camera / clock set by session.new_game)
        if not app.world.resources.has(Camera):
            app.world.resources.set(Camera())
        if not app.world.resources.has(GameClock):
            app.world.resources.set(GameClock())

    # ── Events ────────────────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event, app: App) -> None:
        # Dev panel events
        if self._dev_panel_open:
            if self._handle_dev_panel_event(event, app):
                return

        # Modal events
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
                from scenes.pause_menu import PauseMenu
                app.push_scene(PauseMenu(self.session))
            elif event.key == pygame.K_TAB:
                self.show_debug = not self.show_debug
            elif event.key == pygame.K_e:
                self._do_interact(app)
            elif event.key == pygame.K_i:
                self._open_inventory(app)
            elif event.key == pygame.K_BACKQUOTE:  # ~ tilde
                self._dev_panel_open = not self._dev_panel_open
                self._dev_cursor = 0
                self._dev_scroll = 0
            elif event.key == pygame.K_F5:
                self.session.save()
            elif event.key == pygame.K_F9:
                self.session.load()
            elif event.key == pygame.K_RETURN:
                if self.session.first_person:
                    from scenes.world.firstperson import FirstPerson
                    app.push_scene(FirstPerson(self.session))
                else:
                    self.session.status = "No first-person view here"
                    self.session.status_timer = 1.5
            elif event.key == pygame.K_F4:
                from scenes.editor import MapEditor
                app.push_scene(MapEditor(self.session.zone_name))
            elif event.key == pygame.K_PERIOD:
                self._cycle_time_scale(app, 1)
            elif event.key == pygame.K_COMMA:
                self._cycle_time_scale(app, -1)

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
        """Handle E key — interact with nearest entity.

        Priority: tile entities (containers → pickup ground items) first,
        then generic interaction.
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

            # Generic interaction — open dialogue for NPCs
            ident = app.world.get(t_eid, Identity)
            if ident and ident.kind == EntityKind.NPC:
                self._open_npc_dialogue(app, t_eid)
            elif try_interact(app.world, app.world.events):
                name = ident.name if ident else "???"
                self.session.status = f"Interacted with {name}"
                self.session.status_timer = 1.5
        else:
            # No entity — check if facing a PLATFORM tile
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
            # Auto-create inventory on player if missing
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
        res = app.world.query_one(Player, Position)
        if not res:
            return
        _, _, p_pos = res

        desc = self._registry.to_descriptor(item_id)
        # Snap to grid
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

        # Container inventory — stored as an Inventory component on the entity
        container_inv = app.world.get(eid, Inventory)
        if container_inv is None:
            container_inv = Inventory(items={})
            app.world.add(eid, container_inv)

        # Roll loot on first open
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
        result = app.world.query_one(Player, Position, Facing)
        if not result:
            return False
        _, _, p_pos, p_face = result
        offsets = {
            Direction.UP:    (0, -1),
            Direction.DOWN:  (0,  1),
            Direction.LEFT:  (-1, 0),
            Direction.RIGHT: (1,  0),
        }
        dx, dy = offsets.get(p_face.direction, (0, 0))
        tx = int(p_pos.x) + dx
        ty = int(p_pos.y) + dy
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
        """Find or create an entity for a platform tile at (col, row)."""
        from core.tiles import tile_def as _tile_def
        zone = self.session.zone_name
        for eid, pos, te in app.world.query(Position, TileEntity):
            if (pos.zone == zone
                    and te.tile_type == "platform_surface"
                    and te.tiles == [[row, col]]):
                return eid
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
        import random
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
                    rolls += int(random.random() * bonus)
                entries = pool.get("entries", [])
                if not entries:
                    continue
                weights = [e.get("weight", 1) for e in entries]
                for _ in range(rolls):
                    chosen = random.choices(entries, weights=weights, k=1)[0]
                    item = chosen.get("item", "")
                    lo = chosen.get("min_count", 1)
                    hi = chosen.get("max_count", 1)
                    count = random.randint(lo, hi)
                    items[item] = items.get(item, 0) + count
            return items
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("_roll_loot(%s) failed: %s", table_id, exc)
            return {}

    # ── Dev panel (give items) ────────────────────────────────────

    def _handle_dev_panel_event(self, event: pygame.event.Event, app: App) -> bool:
        """Handle events for the dev give-item panel. Returns True if consumed."""
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_BACKQUOTE or event.key == pygame.K_ESCAPE:
                self._dev_panel_open = False
                return True
            elif event.key in (pygame.K_w, pygame.K_UP):
                self._dev_cursor = max(0, self._dev_cursor - 1)
                return True
            elif event.key in (pygame.K_s, pygame.K_DOWN):
                self._dev_cursor = min(len(self._dev_items) - 1, self._dev_cursor + 1)
                return True
            elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
                self._dev_give_item(app)
                return True
        elif event.type == pygame.MOUSEMOTION:
            # Update hover
            return True
        elif event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1:
                if self._dev_hover >= 0:
                    self._dev_cursor = self._dev_hover
                    self._dev_give_item(app)
                    return True
            elif event.button == 4:  # scroll up
                self._dev_scroll = max(0, self._dev_scroll - 1)
                return True
            elif event.button == 5:  # scroll down
                self._dev_scroll = min(
                    max(0, len(self._dev_items) - 10),
                    self._dev_scroll + 1,
                )
                return True
        return False

    def _dev_give_item(self, app: App) -> None:
        """Give the selected item to the player."""
        if not self._dev_items:
            return
        idx = min(self._dev_cursor, len(self._dev_items) - 1)
        item_id = self._dev_items[idx]

        res = app.world.query_one(Player, Inventory)
        if not res:
            # Create inventory on player
            p_res = app.world.query_one(Player, Position)
            if not p_res:
                return
            p_eid = p_res[0]
            inv = Inventory(items={})
            app.world.add(p_eid, inv)
        else:
            p_eid, _, inv = res

        inv.items[item_id] = inv.items.get(item_id, 0) + 1
        name = self._registry.display_name(item_id)
        self.session.status = f"[DEV] Gave {name}"
        self.session.status_timer = 1.5

    # ── Update ────────────────────────────────────────────────────

    def update(self, dt: float, app: App) -> None:
        # Modal ticking
        if self.modals.is_open:
            self.modals.update(dt)

        # Status fade
        if self.session.status_timer > 0:
            self.session.status_timer -= dt

        # Don't run game logic while modal or dev panel is open
        if self.modals.is_open or self._dev_panel_open:
            # Freeze player velocity
            for eid, player, vel in app.world.query(Player, Velocity):
                vel.x = 0.0
                vel.y = 0.0
            return

        # Tick fade / auto-walk state machine
        was_fading_in = (self.session._fade_direction == -1)
        self.session.update_transition(dt)

        # After fade-in starts in a new zone, check if we need to switch scene
        if was_fading_in and self.session._fade_direction == -1:
            # Still fading in — check if destination is FP zone
            pass  # keep rendering TopDown with fade overlay
        if was_fading_in and self.session._fade_direction != -1:
            # Fade-in just finished — if we're in an FP zone, push FP scene
            pass

        # If a teleport just executed (fade just started fading in),
        # and the new zone is first-person, push the FP scene
        if self.session._fade_direction == -1 and self.session.first_person:
            from scenes.world.firstperson import FirstPerson
            app.push_scene(FirstPerson(self.session))
            return

        keys = pygame.key.get_pressed()

        # ── Input → player velocity (skipped during auto-walk / fade) ─
        if not self.session.auto_walk_active and self.session._fade_direction == 0:
            dx = dy = 0.0
            if keys[pygame.K_w] or keys[pygame.K_UP]:    dy -= 1
            if keys[pygame.K_s] or keys[pygame.K_DOWN]:  dy += 1
            if keys[pygame.K_a] or keys[pygame.K_LEFT]:  dx -= 1
            if keys[pygame.K_d] or keys[pygame.K_RIGHT]: dx += 1

            # Normalise diagonal movement
            if dx and dy:
                dx *= 0.7071
                dy *= 0.7071

            for eid, player, vel in app.world.query(Player, Velocity):
                vel.x = dx * player.speed
                vel.y = dy * player.speed

                facing = app.world.get(eid, Facing)
                if facing and (abs(vel.x) > 0.01 or abs(vel.y) > 0.01):
                    if abs(vel.x) >= abs(vel.y):
                        facing.direction = (
                            Direction.RIGHT if vel.x > 0 else Direction.LEFT
                        )
                    else:
                        facing.direction = (
                            Direction.DOWN if vel.y > 0 else Direction.UP
                        )

        # ── Game clock ───────────────────────────────────────────
        clock = app.world.resources.try_get(GameClock)
        if clock:
            clock.time += dt

        # ── Background simulation (WorldClock, ZoneSim, beasts) ──
        self.session.tick_world(dt)

        # ── Physics ──────────────────────────────────────────────
        movement_system(app.world, dt, self.session.tiles,
                        portal_tiles=self.session.portal_positions)

        # ── Events ───────────────────────────────────────────────
        app.world.events.flush()

        # ── Portal check (only when not already transitioning) ───
        if self.session.check_portals(dt):
            pass  # fade-out has started; the scene will keep rendering

        # ── Camera follow player ─────────────────────────────────
        cam = app.world.resources.try_get(Camera)
        result = app.world.query_one(Player, Position)
        if cam and result:
            _, _, pos = result
            cam.x = pos.x
            cam.y = pos.y

        app.world.purge()

    # ── Draw ──────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, app: App) -> None:
        surface.fill((20, 20, 25))
        cam = app.world.resources.try_get(Camera) or Camera()
        sw, sh = surface.get_size()

        zone = self.session.zone_name
        tiles = self.session.tiles
        map_h = self.session.map_h
        map_w = self.session.map_w

        ox = sw // 2 - int(cam.x * TILE_SIZE)
        oy = sh // 2 - int(cam.y * TILE_SIZE)

        # Visible tile range (culling)
        c0 = max(0, -ox // TILE_SIZE)
        r0 = max(0, -oy // TILE_SIZE)
        c1 = min(map_w, (sw - ox) // TILE_SIZE + 1)
        r1 = min(map_h, (sh - oy) // TILE_SIZE + 1)

        # ── Tiles ────────────────────────────────────────────────
        for row in range(r0, r1):
            for col in range(c0, c1):
                tid = tiles[row][col]
                color = TILE_COLORS.get(tid, (40, 40, 40))
                rect = (ox + col * TILE_SIZE, oy + row * TILE_SIZE,
                        TILE_SIZE, TILE_SIZE)
                pygame.draw.rect(surface, color, rect)

        # ── Entities ─────────────────────────────────────────────
        for eid, pos, sprite in app.world.query(Position, Sprite):
            if pos.zone != zone:
                continue

            # Tile entity indicator ring
            te = app.world.get(eid, TileEntity)
            if te:
                cx = ox + int(pos.x * TILE_SIZE)
                cy = oy + int(pos.y * TILE_SIZE)
                if te.tile_type == "container":
                    pygame.draw.rect(surface, (180, 140, 80),
                                     (cx - TILE_SIZE // 2, cy - TILE_SIZE // 2,
                                      TILE_SIZE, TILE_SIZE), 1)
                elif te.tile_type == "ground_item":
                    pygame.draw.circle(surface, (220, 220, 120),
                                       (cx, cy), TILE_SIZE // 3, 1)
                elif te.tile_type == "crop":
                    pygame.draw.rect(surface, (80, 180, 60),
                                     (cx - TILE_SIZE // 2, cy - TILE_SIZE // 2,
                                      TILE_SIZE, TILE_SIZE), 1)

            # Centre the sprite glyph on the entity position
            img = app.font.render(sprite.char, True, sprite.color)
            px = ox + int(pos.x * TILE_SIZE) - img.get_width() // 2
            py = oy + int(pos.y * TILE_SIZE) - img.get_height() // 2
            surface.blit(img, (px, py))

            # Health bar for non-player entities
            hp = app.world.get(eid, Health)
            if hp and not app.world.has(eid, Player) and hp.current < hp.maximum:
                bar_w = TILE_SIZE - 4
                ratio = max(0.0, hp.current / hp.maximum) if hp.maximum > 0 else 0.0
                bar_x = ox + int(pos.x * TILE_SIZE) - bar_w // 2
                bar_y = py - 6
                pygame.draw.rect(surface, (60, 0, 0),
                                 (bar_x, bar_y, bar_w, 3))
                pygame.draw.rect(surface, (0, 200, 0),
                                 (bar_x, bar_y, int(bar_w * ratio), 3))

        # ── Day / night tint overlay ─────────────────────────────
        self._draw_day_night(surface, app)

        # ── HUD ──────────────────────────────────────────────────
        self._draw_hud(surface, app)

        # ── Notifications / toasts ───────────────────────────────
        self._draw_notifications(surface, app)

        # ── Debug overlay ────────────────────────────────────────
        if self.show_debug:
            self._draw_debug(surface, app)

        # ── Fade overlay ─────────────────────────────────────────
        if self.session.fade_alpha > 0.01:
            fade_surf = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
            a = int(min(255, self.session.fade_alpha * 255))
            fade_surf.fill((0, 0, 0, a))
            surface.blit(fade_surf, (0, 0))

        # ── Modals ───────────────────────────────────────────────
        if self.modals.is_open:
            self.modals.draw(surface, app)

        # ── Dev panel ────────────────────────────────────────────
        if self._dev_panel_open:
            self._draw_dev_panel(surface, app)

    # ── HUD ───────────────────────────────────────────────────────

    def _draw_hud(self, surface: pygame.Surface, app: App) -> None:
        """Minimal HUD: health bar, zone name, clock, controls hint."""
        sw, sh = surface.get_size()

        # Health bar
        result = app.world.query_one(Player, Health)
        if result:
            _, _, hp = result
            bar_x, bar_y = 10, 10
            bar_w, bar_h = 120, 12
            ratio = max(0.0, hp.current / hp.maximum) if hp.maximum > 0 else 0.0
            pygame.draw.rect(surface, (60, 0, 0), (bar_x, bar_y, bar_w, bar_h))
            pygame.draw.rect(surface, (0, 200, 0),
                             (bar_x, bar_y, int(bar_w * ratio), bar_h))
            app.draw_text(surface, f"{int(hp.current)}/{int(hp.maximum)} HP",
                          bar_x + bar_w + 6, bar_y - 1, (200, 200, 200),
                          app.font_sm)

        # Zone name
        app.draw_text(surface, self.session.zone_name, sw - 100, 10,
                      (120, 140, 130), app.font_sm)

        # World clock
        wc = app.world.resources.try_get(WorldClock)
        if wc:
            hour = int(wc.day_phase * 24) % 24
            minute = int((wc.day_phase * 24 * 60) % 60)
            time_str = f"Day {wc.day + 1}  {hour:02d}:{minute:02d}"
            # Color shifts with time of day
            if 0.25 <= wc.day_phase < 0.75:  # daytime
                time_col = (220, 200, 140)
            elif 0.75 <= wc.day_phase < 0.85:  # dusk
                time_col = (220, 140, 80)
            elif wc.day_phase >= 0.85 or wc.day_phase < 0.15:  # night
                time_col = (100, 120, 180)
            else:  # dawn
                time_col = (180, 160, 120)
            app.draw_text(surface, time_str, sw - 100, 24,
                          time_col, app.font_sm)
            if wc.time_scale > 1.0:
                app.draw_text(surface, f"\u25b6\u25b6{int(wc.time_scale)}\u00d7",
                              sw - 100, 38, (255, 180, 60), app.font_sm)

        # Interaction prompt — tile entity aware
        target = nearest_interactable(app.world)
        if target and not self.modals.is_open and not self._dev_panel_open:
            t_eid, _ = target
            ident = app.world.get(t_eid, Identity)
            te = app.world.get(t_eid, TileEntity)
            name = ident.name if ident else f"Entity #{t_eid}"
            if te and te.tile_type == "ground_item":
                label = f"[E] Pick up {name}"
            elif te and te.tile_type == "container":
                label = f"[E] Open {name}"
            else:
                label = f"[E] {name}"
            app.draw_text(surface, label,
                          sw // 2 - 60, sh - 36,
                          (255, 230, 150), app.font_sm)

        # Status label (save/load/interaction feedback)
        if self.session.status_timer > 0 and self.session.status:
            alpha = min(1.0, self.session.status_timer / 0.5)
            c = int(220 * alpha)
            app.draw_text_bg(surface, self.session.status,
                             sw // 2 - 80, 40, (c, c, c))

        # Controls
        hint = "WASD=move  E=interact  I=inv  ~=dev  Tab=debug  F4=editor  F5=save  F6=LOD"
        if self.session.first_person:
            hint = "WASD  E=interact  I=inv  Enter=FP  ~=dev  F4=editor  F5=save  F6=LOD"
        app.draw_text(surface, hint,
                      10, sh - 18,
                      (80, 100, 90), app.font_sm)

    def _draw_dev_panel(self, surface: pygame.Surface, app: App) -> None:
        """Draw the dev give-item panel overlay."""
        sw, sh = surface.get_size()

        # Dark overlay
        overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 140))
        surface.blit(overlay, (0, 0))

        panel_w = 360
        panel_h = min(sh - 40, 500)
        px = (sw - panel_w) // 2
        py = (sh - panel_h) // 2

        pygame.draw.rect(surface, (30, 30, 45), (px, py, panel_w, panel_h))
        pygame.draw.rect(surface, (200, 140, 60), (px, py, panel_w, panel_h), 2)

        # Title
        pygame.draw.rect(surface, (50, 40, 30), (px, py, panel_w, 30))
        app.draw_text(surface, "DEV: Give Item  (~=close)", px + 10, py + 7,
                      (255, 200, 80), app.font)

        # Item list
        y = py + 38
        max_rows = (panel_h - 70) // 22
        visible = self._dev_items[self._dev_scroll:self._dev_scroll + max_rows]

        self._dev_hover = -1
        mx, my_pos = pygame.mouse.get_pos()

        for i, item_id in enumerate(visible):
            actual_idx = self._dev_scroll + i
            row_y = y + i * 22
            row_rect = pygame.Rect(px + 4, row_y, panel_w - 8, 20)

            # Hover detect
            if row_rect.collidepoint(mx, my_pos):
                self._dev_hover = actual_idx

            # Highlight
            if actual_idx == self._dev_cursor:
                pygame.draw.rect(surface, (60, 50, 30), row_rect)
            elif actual_idx == self._dev_hover:
                pygame.draw.rect(surface, (45, 45, 55), row_rect)

            defn = self._registry.get(item_id)
            char = defn.char if defn else "?"
            color = defn.color if defn else (200, 200, 200)
            name = defn.name if defn else item_id
            itype = defn.type if defn else "?"

            app.draw_text(surface, char, px + 10, row_y + 2, color, app.font)
            app.draw_text(surface, f"{name}", px + 30, row_y + 3,
                          (220, 220, 220), app.font_sm)
            app.draw_text(surface, f"({itype})", px + panel_w - 80, row_y + 3,
                          (140, 140, 160), app.font_sm)

        # Scrollbar indicator
        if len(self._dev_items) > max_rows:
            ratio = self._dev_scroll / max(1, len(self._dev_items) - max_rows)
            sb_h = max(20, int(panel_h * max_rows / len(self._dev_items)))
            sb_y = py + 38 + int((panel_h - 70 - sb_h) * ratio)
            pygame.draw.rect(surface, (80, 70, 50),
                             (px + panel_w - 6, sb_y, 4, sb_h))

        # Show player inventory summary
        inv_y = py + panel_h - 26
        res = app.world.query_one(Player, Inventory)
        if res:
            _, _, inv = res
            total = sum(inv.items.values())
            app.draw_text(surface, f"Bag: {total} items  |  [Enter/Click] Give",
                          px + 10, inv_y, (150, 200, 150), app.font_sm)
        else:
            app.draw_text(surface, "[Enter/Click] Give  (no inventory yet)",
                          px + 10, inv_y, (150, 150, 150), app.font_sm)

    def _draw_debug(self, surface: pygame.Surface, app: App) -> None:
        """Debug overlay: FPS, position, entity count, zone sim stats."""
        y = 30
        fps = app.clock.get_fps()
        app.draw_text_bg(surface, f"FPS: {fps:.0f}", 10, y, (0, 255, 200))
        y += 16

        result = app.world.query_one(Player, Position)
        if result:
            _, _, pos = result
            app.draw_text_bg(surface, f"Pos: ({pos.x:.1f}, {pos.y:.1f})",
                             10, y, (0, 255, 200))
            y += 16

        # Count entities in current zone
        n = len(app.world.zone_entities(self.session.zone_name))
        app.draw_text_bg(surface, f"Entities: {n}", 10, y, (0, 255, 200))
        y += 16

        clock = app.world.resources.try_get(GameClock)
        if clock:
            app.draw_text_bg(surface, f"Time: {clock.time:.1f}s",
                             10, y, (0, 255, 200))
            y += 16

        # Show off-screen entity counts per zone
        from components import CoarsePos
        zone_counts: dict[str, int] = {}
        for _, cp in app.world.all_of(CoarsePos):
            if not app.world.has(_, Position):
                zone_counts[cp.zone] = zone_counts.get(cp.zone, 0) + 1
        for zn, cnt in sorted(zone_counts.items()):
            app.draw_text_bg(surface, f"  {zn}: {cnt} off-screen",
                             10, y, (0, 200, 180))
            y += 14

    # ── Day / night tinting ──────────────────────────────────────

    def _draw_day_night(self, surface: pygame.Surface, app: App) -> None:
        """Apply a color overlay based on time of day."""
        wc = app.world.resources.try_get(WorldClock)
        if wc is None:
            return

        phase = wc.day_phase
        # Calculate tint color and alpha based on day phase:
        #   0.00 - 0.20  night     (dark blue)
        #   0.20 - 0.30  dawn      (warm orange, fading)
        #   0.30 - 0.70  day       (no tint)
        #   0.70 - 0.80  dusk      (warm orange, growing)
        #   0.80 - 1.00  night     (dark blue)

        if 0.30 <= phase < 0.70:
            return  # full daylight, no tint

        if phase < 0.20 or phase >= 0.85:
            # Full night
            color = (10, 10, 50)
            alpha = 100
        elif 0.20 <= phase < 0.30:
            # Dawn: transition from night to day
            t = (phase - 0.20) / 0.10  # 0→1
            alpha = int(100 * (1.0 - t))
            r = int(10 + 40 * t)
            g = int(10 + 20 * t)
            b = int(50 - 20 * t)
            color = (r, g, b)
        elif 0.70 <= phase < 0.80:
            # Dusk: transition from day to night
            t = (phase - 0.70) / 0.10  # 0→1
            alpha = int(80 * t)
            color = (50 - int(30 * t), 20 - int(10 * t), 10 + int(30 * t))
        else:
            # Late dusk / early night (0.80-0.85)
            t = (phase - 0.80) / 0.05  # 0→1
            alpha = int(80 + 20 * t)
            color = (20 - int(10 * t), 10, 40 + int(10 * t))

        tint_surf = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        tint_surf.fill((*color, alpha))
        surface.blit(tint_surf, (0, 0))

    # ── Toast notifications ──────────────────────────────────────

    _NOTIFICATION_COLORS = {
        "combat": (255, 100, 100),
        "travel": (100, 200, 255),
        "loot":   (255, 220, 100),
        "info":   (180, 180, 180),
    }

    def _draw_notifications(self, surface: pygame.Surface, app: App) -> None:
        """Draw recent world events as toast notifications on the right side."""
        event_log = app.world.resources.try_get(WorldEventLog)
        if event_log is None or not event_log.entries:
            return

        sw, sh = surface.get_size()
        clock = app.world.resources.try_get(GameClock)
        now = clock.time if clock else 0.0

        # Show entries from the last 8 seconds
        max_show = 5
        y = 50
        shown = 0

        for entry in reversed(event_log.entries):
            age = now - entry.time
            if age > 8.0:
                break
            if shown >= max_show:
                break

            # Fade out over last 3 seconds
            if age > 5.0:
                fade = 1.0 - (age - 5.0) / 3.0
            else:
                fade = 1.0

            color = self._NOTIFICATION_COLORS.get(entry.category, (180, 180, 180))
            color = tuple(int(c * fade) for c in color)

            # Draw background pill
            text = entry.message
            tw = len(text) * 7  # approximate width
            bx = sw - tw - 20
            by = y
            bg_surf = pygame.Surface((tw + 12, 18), pygame.SRCALPHA)
            bg_surf.fill((0, 0, 0, int(120 * fade)))
            surface.blit(bg_surf, (bx - 4, by - 2))

            app.draw_text(surface, text, bx, by, color, app.font_sm)
            y += 20
            shown += 1

        # Mark as read
        event_log.unread = 0

